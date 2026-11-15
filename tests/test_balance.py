import contextlib
import io
import os
import sqlite3
import tempfile
import unittest
from unittest import mock
from collections import Counter
from datetime import datetime, timezone

from cosh import balance


def ts(s):
    return int(datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc).timestamp())


class CompareTest(unittest.TestCase):
    def test_rebase_is_no_change(self):
        # Same added/removed lines, different positions (as after a rebase).
        d0 = {b"a.cc": (Counter({1: 1, 2: 1}), Counter({3: 1}))}
        d1 = {b"a.cc": (Counter({2: 1, 1: 1}), Counter({3: 1}))}
        self.assertEqual(balance.compare(d0, d1), (3, 3, 0, 0, 0, 0))

    def test_edits_added_and_dropped_files(self):
        d0 = {b"a.cc": (Counter({1: 1}), Counter()), b"old.cc": (Counter({9: 2}), Counter())}
        d1 = {b"a.cc": (Counter({1: 1, 2: 1}), Counter()), b"new.cc": (Counter({5: 1}), Counter({6: 1}))}
        # a.cc: one line more; new.cc adds 2; old.cc drops 2.
        self.assertEqual(balance.compare(d0, d1), (3, 4, 5, 1, 1, 1))


class ClFactsTest(unittest.TestCase):
    """cl_facts and cl_dirs: the part of `cl` the Feedback Index reads without balance.sqlite."""

    def test_facts_and_dirs(self):
        ddb, gdb = sqlite3.connect(":memory:"), sqlite3.connect(":memory:")
        ddb.executescript("""
            CREATE TABLE accounts (account_id INTEGER, email TEXT);
            CREATE TABLE changes (change_number INTEGER, owner_account INTEGER, status TEXT, created_at TEXT,
              closed_at TEXT, close_week TEXT, insertions INTEGER, deletions INTEGER, patchsets INTEGER,
              is_bot_owned INTEGER, project TEXT, branch TEXT);
            INSERT INTO accounts VALUES (1, 'A@chromium.org');
            INSERT INTO changes VALUES
              (20, 1, 'MERGED', '2026-11-02 10:00:00', '2026-11-03 10:00:00', '2026-W45', 5, 2, 3, 0, 'chromium/src', 'main'),
              (10, 1, 'ABANDONED', '2026-11-02 10:00:00', NULL, NULL, 1, 0, 1, 0, 'chromium/src', 'main'),
              (30, 1, 'MERGED', '2026-11-02 10:00:00', '2026-11-03 10:00:00', '2026-W45', 1, 1, 1, 1, 'chromium/src', 'main'),
              (40, 1, 'MERGED', '2026-11-02 10:00:00', '2026-11-03 10:00:00', '2026-W45', 1, 1, 1, 0, 'chromium/src', 'other');
        """)
        gdb.executescript("""
            CREATE TABLE commits (commit_id INTEGER, change_number INTEGER, sha TEXT, files INTEGER, ins INTEGER,
              dels INTEGER, reverts_sha TEXT, is_reland INTEGER, landed_at INTEGER);
            CREATE TABLE paths (path_id INTEGER, path TEXT);
            CREATE TABLE commit_files (commit_id INTEGER, path_id INTEGER, ins INTEGER, dels INTEGER);
            INSERT INTO commits VALUES (7, 20, 'abc', 2, 4, 2, NULL, 0, 100), (8, NULL, 'def', 1, 0, 4, 'abc', 0, 150),
              (9, 10, 'ghi', 1, 1, 0, NULL, 0, 90);
            INSERT INTO paths VALUES (1, 'a/b/c/d.cc'), (2, 'a/b/c/e/f.cc'), (3, 'top.txt');
            INSERT INTO commit_files VALUES (7, 1, 3, 1), (7, 2, 1, 1), (8, 3, 0, 4), (9, 3, 1, 0);
        """)
        rows, by_cid = balance.cl_facts(ddb, gdb)
        facts = [dict(zip(balance.CL_FACTS, r)) for r in rows]
        self.assertEqual([f["change_number"] for f in facts], [10, 20])      # sorted, bots and other branches out
        self.assertEqual(facts[1], dict(change_number=20, owner=1, owner_email="A@chromium.org", status="MERGED",
                                        created_at=ts("2026-11-02 10:00"), closed_at=ts("2026-11-03 10:00"),
                                        close_week="2026-W45", ins=5, dels=2, patchsets=3, sha="abc", files=2,
                                        git_lines=6, is_revert=0, is_reland=0, reverted_at=150))
        self.assertIsNone(facts[0]["sha"])               # not merged: no landed commit
        self.assertEqual(by_cid, {7: 20, 9: 10})
        self.assertEqual(dict(balance.cl_dirs(gdb, by_cid)), {(20, "a/b/c/"): [2, 6], (10, "(root)/"): [1, 1]})
        self.assertEqual(dict(balance.cl_dirs(gdb, by_cid, {20})), {(20, "a/b/c/"): [2, 6]})
        # The Feedback Index's lines: insertions alone.
        self.assertEqual(dict(balance.cl_dirs(gdb, by_cid, dels=False)), {(20, "a/b/c/"): [2, 4], (10, "(root)/"): [1, 1]})
        # Streamed, one landed commit at a time, as the stage `cl` writes them.
        self.assertEqual(sorted(balance.iter_cl_dirs(gdb, by_cid)), [(10, "(root)/", 1, 1), (20, "a/b/c/", 2, 6)])

    def test_by_cl_merge(self):
        rows = balance._ByCL([(1, "a"), (3, "b"), (3, "c"), (5, "d")])
        self.assertEqual(rows.take(2), [])
        self.assertEqual(rows.take(3), [(3, "b"), (3, "c")])
        self.assertEqual(rows.take(6), [])          # 5 skipped: no CL asked for it
        self.assertEqual(rows.take(7), [])


class RecordTest(unittest.TestCase):
    def test_reads_and_writes_like_a_dict(self):
        from cosh.records import record_type
        R = record_type("R", ("a", "b"), ("x",))
        r = R(1, b=2)
        self.assertEqual((r["a"], r["b"], r.get("x"), r.get("y", 9)), (1, 2, None, 9))
        self.assertNotIn("x", r)
        r["x"] = 3
        r["y"] = 4                                 # neither field nor extra: a per-record dict
        r["a"] += 1
        self.assertEqual((r["a"], r["x"], r["y"]), (2, 3, 4))
        self.assertIn("y", r)
        with self.assertRaises(AttributeError):
            r["z"]


class HoursTest(unittest.TestCase):
    def test_union(self):
        self.assertEqual(balance.union_hours([(0, 3600), (1800, 7200), (10800, 14400)], 0, 99999), 3.0)
        self.assertEqual(balance.union_hours([(0, 7200)], 3600, 99999), 1.0)

    def test_weekdays(self):
        # 2026-11-06 is a Friday: Friday 12:00 to Monday 12:00 has 24 weekday hours.
        self.assertEqual(balance.weekday_seconds(ts("2026-11-06 12:00"), ts("2026-11-09 12:00")), 24 * 3600)


class InterdiffFingerprintTest(unittest.TestCase):
    """stage_interdiff compares a CL once, and every CL again when its code
    changes."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tl = os.path.join(self.tmp.name, "timeline.sqlite")
        t = sqlite3.connect(tl)
        t.executescript("CREATE TABLE uploads (change_number INTEGER, ps INTEGER, at INTEGER, sha TEXT);"
                        "INSERT INTO uploads VALUES (5, 1, 100, NULL), (6, 1, 100, NULL), (6, 2, 300, NULL);")
        t.commit()
        t.close()
        with open(os.path.join(self.tmp.name, "cosh-fetched.txt"), "w") as f:
            f.write("5\n6\n")
        self.patches = [mock.patch.dict(os.environ, {"COSH_BALANCE_TIMELINE": tl}),
                        mock.patch.object(balance, "PATCHSETS", self.tmp.name),
                        mock.patch.object(balance, "first_review_times", lambda: {5: 200, 6: 200}),
                        mock.patch.object(balance, "diff_lines", lambda git_dir, shas: {})]
        for p in self.patches:
            p.start()
        self.db = balance.connect(os.path.join(self.tmp.name, "interdiff.sqlite"), "interdiff")

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.db.close()
        self.tmp.cleanup()

    def run_stage(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            balance.stage_interdiff(self.db)
        return out.getvalue()

    def test_recomputed_only_when_code_changes(self):
        self.assertIn("2 CLs to compare (0 done)", self.run_stage())
        good = self.db.execute("SELECT * FROM interdiff ORDER BY 1").fetchall()
        self.assertEqual([r[-1] for r in good], ["ok", "missing"])
        self.db.execute("UPDATE interdiff SET status = 'stale'")
        self.db.commit()
        self.assertIn("0 CLs to compare (2 done)", self.run_stage())
        with mock.patch.object(balance, "INTERDIFF_VERSION", 2):
            out = self.run_stage()
            self.assertIn("its code changed", out)
            self.assertIn("2 CLs to compare (0 done)", out)
            self.assertEqual(self.db.execute("SELECT * FROM interdiff ORDER BY 1").fetchall(), good)
            self.assertIn("0 CLs to compare (2 done)", self.run_stage())


if __name__ == "__main__":
    unittest.main()
