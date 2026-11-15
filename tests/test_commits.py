"""commits.sqlite's per-part code fingerprints, against a tiny git repo."""

import contextlib
import io
import os
import subprocess
import tempfile
import unittest
from unittest import mock

from cosh import commits

CL = "\n\nReviewed-on: https://chromium-review.googlesource.com/c/chromium/src/+/{}\n"


class PartsTest(unittest.TestCase):
    def git(self, *args):
        p = subprocess.run(["git", "-C", self.repo, *args], capture_output=True, text=True, env=self.env)
        if p.returncode:
            raise AssertionError(f"git {args[0]} failed: {p.stderr}")
        return p.stdout.strip()

    def commit(self, msg, files=(), at=0):
        for name, text in files:
            with open(os.path.join(self.repo, name), "w") as f:
                f.write(text)
        self.git("add", "-A")
        self.env["GIT_AUTHOR_DATE"] = self.env["GIT_COMMITTER_DATE"] = f"@{1_700_000_000 + at} +0000"
        self.git("commit", "-q", "--allow-empty", "-m", msg)
        return self.git("rev-parse", "HEAD")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.tmp.name, "src")
        self.env = {**os.environ, "GIT_AUTHOR_NAME": "A", "GIT_AUTHOR_EMAIL": "a@chromium.org",
                    "GIT_COMMITTER_NAME": "A", "GIT_COMMITTER_EMAIL": "a@chromium.org",
                    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
        os.makedirs(self.repo)
        self.git("init", "-q", "-b", "main")
        first = self.commit("Add a" + CL.format(100), [("a.txt", "a\nb\nc\n"), ("OWNERS", "x@chromium.org\n")], 0)
        self.commit("LSC: the same line everywhere" + CL.format(101),
                    [(f"f{i}.txt", "same\n") for i in range(10)], 10)
        os.rename(os.path.join(self.repo, "a.txt"), os.path.join(self.repo, "b.txt"))
        self.commit("Move a" + CL.format(102), at=20)
        self.commit(f"Revert \"Add a\"\n\nThis reverts commit {first}.\n" + CL.format(103), at=30)
        self.path = os.path.join(self.tmp.name, "commits.sqlite")
        self.update()

    def tearDown(self):
        self.tmp.cleanup()

    def update(self, **kw):
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            commits.update(self.path, self.repo, jobs=1, **kw)

    def q(self, sql):
        db = commits.open_ro(self.path)
        try:
            return db.execute(sql).fetchall()
        finally:
            db.close()

    def state(self):
        return {"lsc": self.q("SELECT change_number FROM commits WHERE is_lsc"),
                "reverts": self.q("SELECT change_number FROM commits WHERE is_revert"),
                "owners": self.q("SELECT email FROM owners_added"),
                "repetition": self.q("SELECT round(ratio, 2) FROM repetition"),
                "renames": self.q("SELECT count(*) FROM renames"),
                "messages": self.q("SELECT change_number FROM commits WHERE is_reland ORDER BY 1")}

    def tamper(self):
        """Stale rows in every part, as if older code had made them."""
        db = commits.connect(self.path)
        with db:
            db.execute("UPDATE commits SET is_lsc = 1 - is_lsc, is_revert = 1 - is_revert, is_reland = 1")
            db.execute("DELETE FROM owners_added")
            db.execute("UPDATE repetition SET ratio = -1")
            db.execute("DELETE FROM renames")
        db.close()

    def test_first_build(self):
        self.assertEqual(self.state(), {"lsc": [(101,)], "reverts": [(103,)], "owners": [("x@chromium.org",)],
                                        "repetition": [(0.9,)], "renames": [(1,)], "messages": []})
        fps = commits.part_fingerprints()
        db = commits.open_ro(self.path)
        self.assertEqual({k[len("code_fp:"):]: v for k, v in db.execute(
            "SELECT k, v FROM meta WHERE k LIKE 'code_fp:%'")}, fps)
        db.close()

    def test_unchanged_code_keeps_rows(self):
        self.tamper()
        stale = self.state()
        self.update()
        self.assertEqual(self.state(), stale)

    def test_changed_part_alone_is_recomputed(self):
        good = self.state()
        self.tamper()
        stale = self.state()
        bumped = {}                     # cumulative, so earlier parts stay at their new code
        for part in ("messages", "reverts", "lsc", "owners", "repetition", "renames"):
            bumped[part] = 2
            with self.subTest(part), mock.patch.dict(commits.PART_VERSIONS, bumped):
                self.update()
                now = self.state()
                self.assertEqual(now[part], good[part])
                for other in now.keys() - {part}:
                    self.assertEqual(now[other], stale[other], other)
                # Recorded: a second run with the same code changes nothing.
                self.tamper()
                stale = self.state()
                self.update()
                self.assertEqual(self.state(), stale)

    def test_changed_regex_is_seen(self):
        self.tamper()
        with mock.patch.object(commits, "LSC_GREP", r"\bLSC\b"):
            self.update()
        self.assertEqual(self.state()["lsc"], [(101,)])
        self.assertEqual(self.state()["owners"], [])          # other parts left alone

    def test_core_change_needs_rebuild(self):
        self.tamper()
        with mock.patch.dict(commits.PART_VERSIONS, {"core": 2}):
            with self.assertRaises(SystemExit):
                self.update()
            self.assertEqual(self.state()["owners"], [])      # nothing touched
            self.update(rebuild=True)
        self.assertEqual(self.state()["owners"], [("x@chromium.org",)])
        self.assertEqual(self.state()["lsc"], [(101,)])
        self.assertEqual(self.q("SELECT count(*) FROM commits"), [(4,)])


if __name__ == "__main__":
    unittest.main()
