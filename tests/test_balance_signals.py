import contextlib
import io
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import balance_signals as S  # noqa: E402


class VoteParserTest(unittest.TestCase):
    def test_votes_removals_behalf_and_copies(self):
        entries = [
            (100, 7, "Update patch set 2\n\nPatch Set 2: Code-Review-1\n\nPatch-set: 2\nLabel: Code-Review=-1\n"),
            (200, 8, "Patch-set: 3\nLabel: Code-Review=+2, 1a2b3c4d-aaaa\n"
                     "Label: Code-Review=-1 Gerrit User 99 <99@abcd>\nLabel: Commit-Queue=+1"),
            (300, 7, "Patch-set: 3\nLabel: -Code-Review\n"
                     "Copied-Label: Code-Review=-1, ab12 Gerrit User 7 <7@x>"),
            (400, 9, "Patch-set: 4\nLabel: Code-Review=0"),
        ]
        self.assertEqual(S.parse_votes(entries), [
            (7, -1, 100, 2),       # the commit author votes
            (8, 2, 200, 3),        # a vote uuid suffix is ignored
            (99, -1, 200, 3),      # cast on behalf of another account
            (7, 0, 300, 3),        # removal; the Copied-Label line is skipped
            (9, 0, 400, 4),
        ])

    def test_no_votes(self):
        self.assertEqual(S.parse_votes([(1, 2, "Patch-set: 1\nLabel: Commit-Queue=+2")]), [])


class StageVotesTest(unittest.TestCase):
    """stage_votes against a tiny NoteDb-like repo: two CLs with meta refs,
    one without, and an unrelated ref."""

    def git(self, *args, msg=None):
        p = subprocess.run(["git", "--git-dir", self.repo, *args], input=msg, capture_output=True,
                           text=True, env={**os.environ, **self.ident})
        if p.returncode:
            raise AssertionError(f"git {args[0]} failed: {p.stderr}")
        return p.stdout.strip()

    def commit(self, ref, msgs, at):
        parent = []
        for k, m in enumerate(msgs):
            self.ident["GIT_AUTHOR_DATE"] = self.ident["GIT_COMMITTER_DATE"] = f"@{at + k} +0000"
            sha = self.git("commit-tree", self.tree, *parent, msg=m)
            parent = ["-p", sha]
        self.git("update-ref", ref, sha)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.tmp.name, "notedb.git")
        self.ident = {"GIT_AUTHOR_NAME": "Gerrit User 7", "GIT_AUTHOR_EMAIL": "7@x",
                      "GIT_COMMITTER_NAME": "Gerrit", "GIT_COMMITTER_EMAIL": "g@x"}
        subprocess.run(["git", "init", "-q", "--bare", self.repo], check=True)
        self.tree = self.git("mktree", msg="")
        self.commit("refs/meta/101", ["Create change\n\nPatch-set: 1\n",
                                      "Review\n\nPatch-set: 1\nLabel: Code-Review=-1\n"], 1000)
        self.commit("refs/meta/102", ["Review\n\nPatch-set: 2\nLabel: Code-Review=+2\n"], 2000)
        self.commit("refs/heads/other", ["not a meta ref\n\nPatch-set: 1\nLabel: Code-Review=+1\n"], 3000)
        self.old = S.balance.NOTEDB
        S.balance.NOTEDB = self.repo

    def tearDown(self):
        S.balance.NOTEDB = self.old
        self.tmp.cleanup()

    def test_meta_refs_and_votes(self):
        self.assertEqual(S.balance.meta_refs(), {101, 102})
        out = os.path.join(self.tmp.name, "votes.sqlite")
        with contextlib.redirect_stdout(io.StringIO()):
            S.stage_votes(batch=2, numbers=[101, 102, 103], out=out)
        db = sqlite3.connect(out)
        self.assertEqual(db.execute("SELECT change_number, voter, value, at, ps FROM votes ORDER BY 1").fetchall(),
                         [(101, 7, -1, 1001, 1), (102, 7, 2, 2000, 2)])
        # 103 has no meta ref: done without a git call, so a rerun reads nothing.
        self.assertEqual([n for n, in db.execute("SELECT change_number FROM votes_done ORDER BY 1")],
                         [101, 102, 103])


class HelperTest(unittest.TestCase):
    def test_bucket_and_boot(self):
        self.assertEqual(S.bucket(4.5, S.TENURE), "3-6")
        self.assertEqual(S.bucket(200, S.TENURE), "120+")
        r = S.boot_ci([1.0] * 20)
        self.assertEqual((r["n"], r["mean"], r["lo"], r["hi"]), (20, 1.0, 1.0, 1.0))
        self.assertIsNone(S.boot_ci([1.0] * 3)["mean"])


if __name__ == "__main__":
    unittest.main()
