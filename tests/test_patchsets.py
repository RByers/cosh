import os
import sqlite3
import subprocess
import tempfile
import unittest

from cosh import patchsets


def make_derived(path):
    db = sqlite3.connect(path)
    db.executescript("""
      CREATE TABLE accounts (host TEXT, account_id INTEGER, is_bot INTEGER DEFAULT 0);
      CREATE TABLE changes (host TEXT, change_number INTEGER, project TEXT, branch TEXT,
        owner_account INTEGER, patchsets INTEGER, closed_at TEXT, updated_at TEXT);
      CREATE TABLE comments (host TEXT, change_number INTEGER, account_id INTEGER);
    """)
    h = "h"
    db.executemany("INSERT INTO accounts VALUES (?,?,?)", [(h, 1, 0), (h, 2, 0), (h, 9, 1)])
    db.executemany("INSERT INTO changes VALUES (?,?,?,?,?,?,?,?)", [
        (h, 100, "chromium/src", "main", 1, 3, "2026-01-01", "2026-01-01"),  # reviewed by 2
        (h, 101, "chromium/src", "main", 1, 2, None, "2026-02-01"),          # open, reviewed
        (h, 102, "chromium/src", "main", 1, 5, "2026-03-01", "2026-03-01"),  # owner only
        (h, 103, "chromium/src", "main", 1, 4, "2026-03-02", "2026-03-02"),  # bot only
        (h, 104, "chromium/src", "release", 1, 1, "2026-03-03", "2026-03-03"),
        (h, 105, "chromium/src", "main", 1, None, "2025-12-01", "2025-12-01"),  # unknown account
    ])
    db.executemany("INSERT INTO comments VALUES (?,?,?)", [
        (h, 100, 2), (h, 100, 1), (h, 101, 2), (h, 102, 1), (h, 103, 9), (h, 104, 2), (h, 105, 7)])
    db.commit()


class PatchsetsTest(unittest.TestCase):
    def test_reviewed_cls_newest_first(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "derived.sqlite")
            make_derived(p)
            self.assertEqual(patchsets.reviewed_cls(p), [(101, 2), (100, 3), (105, 1)])

    def test_refspecs(self):
        self.assertEqual(patchsets.refspecs(8639211),
                         "+refs/changes/11/8639211/*:refs/patchsets/8639211/*\n"
                         "^refs/changes/11/8639211/meta\n")
        self.assertIn("/05/705/", patchsets.refspecs(705))

    def test_batches(self):
        cls = [(1, 2), (2, 2), (3, 9), (4, 1), (5, 1), (6, 1)]
        self.assertEqual(patchsets.batches(cls, max_cls=3, max_ps=5),
                         [[(1, 2), (2, 2)], [(3, 9)], [(4, 1), (5, 1), (6, 1)]])
        self.assertEqual(patchsets.batches([], 3, 5), [])

    def test_init_and_fetched(self):
        with tempfile.TemporaryDirectory() as d:
            g = patchsets.init_repo(os.path.join(d, "ps.git"))
            self.assertEqual(patchsets.git(g, "config", "fetch.hideRefs").stdout.strip(),
                             "refs/patchsets/")
            self.assertEqual(patchsets.git(g, "rev-parse", "--show-ref-format").stdout.strip(),
                             "reftable")
            env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
                   "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}
            tree = subprocess.run(["git", "-C", g, "mktree"], input="", text=True,
                                  capture_output=True, check=True).stdout.strip()
            c = subprocess.run(["git", "-C", g, "commit-tree", tree, "-m", "x"], env=env,
                               text=True, capture_output=True, check=True).stdout.strip()
            patchsets.git(g, "update-ref", "refs/patchsets/42/1", c)
            with open(os.path.join(g, patchsets.DONE_FILE), "w") as f:
                f.write("7\n")
            self.assertEqual(patchsets.fetched(g), {7, 42})

    def _run_fake(self, jobs, fail_on=None):
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "derived.sqlite")
            make_derived(db)
            g = patchsets.init_repo(os.path.join(d, "ps.git"))
            seen = []
            orig = patchsets.fetch_batch, patchsets.repack

            def fake_fetch(git_dir, cls, retries=4, throttle=None):
                if fail_on in [n for n, _ in cls]:
                    raise RuntimeError("boom")
                seen.append([n for n, _ in cls])
                return 0.0

            patchsets.fetch_batch, patchsets.repack = fake_fetch, lambda g: 0.0
            try:
                patchsets.run(go=True, derived_path=db, git_dir=g, interval=0, max_cls=1, min_free=0,
                              jobs=jobs)
            finally:
                patchsets.fetch_batch, patchsets.repack = orig
            return sorted(seen)

    def test_parallel_fetches_each_batch_once(self):
        self.assertEqual(self._run_fake(jobs=3), [[100], [101], [105]])
        self.assertEqual(self._run_fake(jobs=1), [[100], [101], [105]])

    def test_failure_stops_run(self):
        with self.assertRaises(SystemExit):
            self._run_fake(jobs=2, fail_on=100)

    def test_throttle_shrinks_on_429_and_grows_back(self):
        now = [0.0]
        t = patchsets.Throttle(3, backoff=60, max_backoff=200, grow_after=600, clock=lambda: now[0])
        for _ in range(3):
            t.acquire()
        t.release(True)            # first 429: limit 3 -> 2, pause 60 s
        t.release(True)            # same burst: pause doubles, limit stays
        self.assertEqual((t.limit, t.pause_until), (2, 120))
        now[0] = 130
        t.release(False)           # success resets the doubling but too soon to grow
        self.assertEqual((t.limit, t.strikes), (2, 0))
        t.acquire()                # pause is over and 0 < 2 active
        now[0] = 800
        t.release(False)           # 670 s since the drop: grow to 3
        self.assertEqual(t.limit, 3)
        for _ in range(9):
            now[0] += 1000  # past any pause, so acquire doesn't block
            t.acquire()
            t.release(True)
        self.assertEqual(t.limit, 1)  # never below one
        self.assertEqual(t.pause_until - now[0], 200)  # capped backoff

    def test_rate_limited_fetch_retries_without_splitting(self):
        calls = []
        replies = iter([(128, "error: RPC failed; HTTP 429 curl 22"),
                        (128, "remote: RESOURCE_EXHAUSTED: Resource has been exhausted"),
                        (128, "fatal: expected 'acknowledgments' HTTP 429"),
                        (0, "")])
        orig = patchsets.git

        def fake_git(git_dir, *args, input=None, **kw):
            calls.append(input)
            rc, err = next(replies)
            return subprocess.CompletedProcess(args, rc, "", err)

        with tempfile.TemporaryDirectory() as d:
            patchsets.git = fake_git
            try:
                t = patchsets.Throttle(2, backoff=0)
                patchsets.fetch_batch(d, [(1, 1), (2, 1)], throttle=t)
            finally:
                patchsets.git = orig
            self.assertEqual(len(calls), 4)
            self.assertEqual(len(set(calls)), 1)   # same whole batch each time
            self.assertEqual(t.limit, 1)
            self.assertEqual(open(os.path.join(d, patchsets.DONE_FILE)).read(), "1\n2\n")


if __name__ == "__main__":
    unittest.main()
