"""scripts/notedb_chunked_repack.sh on a small repo: many packs in, a few out, lossless."""
import os
import subprocess
import tempfile
import unittest

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "scripts", "notedb_chunked_repack.sh")
ENV = {**os.environ, "GIT_AUTHOR_NAME": "a", "GIT_AUTHOR_EMAIL": "a@x",
       "GIT_COMMITTER_NAME": "a", "GIT_COMMITTER_EMAIL": "a@x", "GIT_NO_LAZY_FETCH": "1"}


class ChunkedRepackTest(unittest.TestCase):
    def git(self, *args, i=None, check=True):
        p = subprocess.run(["git", "--git-dir", self.repo, *args], input=i, capture_output=True,
                           text=True, env=ENV)
        if check and p.returncode:
            raise AssertionError(f"git {args[0]}: {p.stderr}")
        return p.stdout.strip()

    def packs(self, d=None):
        d = d or os.path.join(self.repo, "objects", "pack")
        return sorted(f for f in os.listdir(d) if f.endswith(".pack"))

    def pack(self, ids):
        self.git("pack-objects", "-q", os.path.join(self.repo, "objects", "pack", "pack"), i="\n".join(ids) + "\n")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.tmp.name, "r.git")
        subprocess.run(["git", "init", "-q", "--bare", self.repo], check=True)
        tree = self.git("mktree", i="")
        self.pack([tree])
        self.tips = {}
        for k in range(6):            # one pack per commit, like one fetch per batch
            n = k % 3
            parent = ["-p", self.tips[n]] if n in self.tips else []
            c = self.git("commit-tree", tree, *parent, i=f"Update\n\nPatch-set: {k}\nLabel: Code-Review=+1\n" * 40)
            self.git("update-ref", f"refs/meta/{n}", c)
            self.tips[n] = c
            self.pack([c])
        # An object no ref reaches must survive too (nothing is pruned).
        self.blob = self.git("hash-object", "-w", "--stdin", i="unreachable")
        self.pack([self.blob])
        self.git("prune-packed")
        self.git("multi-pack-index", "write")
        self.before = self.packs()

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, group_bytes, work="work"):
        work = os.path.join(self.tmp.name, work)
        p = subprocess.run([SCRIPT, self.repo, work], capture_output=True, text=True,
                           env={**ENV, "GROUP_BYTES": str(group_bytes)})
        return p, work

    def test_repack_is_lossless_and_moves_old_packs_aside(self):
        self.assertEqual(len(self.before), 8)
        p, work = self.run_script(1)      # every pack its own group: names may repeat
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("DONE", p.stdout)
        self.assertEqual(os.listdir(os.path.join(work, "stage")), [])
        p, work = self.run_script(10**9, "work2")   # again, all in one group
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        after = self.packs()
        self.assertEqual(len(after), 1, p.stdout)
        for n, c in self.tips.items():
            self.assertEqual(self.git("rev-parse", f"refs/meta/{n}"), c)
        self.assertEqual(self.git("cat-file", "-p", self.blob), "unreachable")
        self.assertEqual(self.git("rev-list", "--count", "--all"), "6")
        self.assertEqual(self.git("fsck", "--no-dangling"), "")
        self.git("multi-pack-index", "verify")
        self.assertEqual(len(self.packs(os.path.join(work, "old-packs"))), 8)   # kept, not deleted

    def test_reader_started_before_the_swap_still_finds_everything(self):
        reader = subprocess.Popen(["git", "--git-dir", self.repo, "cat-file", "--batch-check"],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=ENV)
        reader.stdin.write(self.tips[0] + "\n")      # it has loaded the old packs
        reader.stdin.flush()
        self.assertIn(" commit ", reader.stdout.readline())
        p, _ = self.run_script(10**9)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        for oid in [*self.tips.values(), self.blob]:
            reader.stdin.write(oid + "\n")
            reader.stdin.flush()
            self.assertNotIn("missing", reader.stdout.readline())
        reader.stdin.close()
        self.assertEqual(reader.wait(), 0)
        reader.stdout.close()

    def stage_first_group(self, n=3):
        """What a run killed after its first group leaves: before.txt, done-src.txt
        and one finished pack in the staging dir."""
        work = os.path.join(self.tmp.name, "work")
        os.makedirs(os.path.join(work, "stage"))
        with open(os.path.join(work, "before.txt"), "w") as f:
            f.write("\n".join(self.before) + "\n")
        with open(os.path.join(work, "done-src.txt"), "w") as f:
            f.write("\n".join(self.before[:n]) + "\n")
        self.git("pack-objects", "--stdin-packs", "-q", os.path.join(work, "stage", "pack"),
                 i="\n".join(self.before[:n]) + "\n")
        return work

    def test_resume_after_a_killed_run(self):
        self.stage_first_group()
        p, work = self.run_script(10**9)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("resuming: 3 of 8", p.stdout)
        self.assertEqual(len(self.packs()), 2)                 # the staged group + the rest
        self.assertEqual(self.git("cat-file", "-p", self.blob), "unreachable")
        self.assertEqual(self.git("fsck", "--no-dangling"), "")
        self.assertEqual(len(self.packs(os.path.join(work, "old-packs"))), 8)

    def test_refuses_to_resume_if_the_packs_changed(self):
        self.stage_first_group()
        self.pack([self.git("hash-object", "-w", "--stdin", i="fetched meanwhile")])
        p, _ = self.run_script(10**9)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("refusing to resume", p.stdout)
        self.assertEqual(len(self.packs()), 9)

    def test_refuses_a_non_empty_staging_dir(self):
        work = os.path.join(self.tmp.name, "work")
        os.makedirs(os.path.join(work, "stage"))
        open(os.path.join(work, "stage", "x"), "w").close()
        p, _ = self.run_script(10**9)
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(self.packs(), self.before)


if __name__ == "__main__":
    unittest.main()
