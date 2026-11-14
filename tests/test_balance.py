import sqlite3
import unittest
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


class HoursTest(unittest.TestCase):
    def test_union(self):
        self.assertEqual(balance.union_hours([(0, 3600), (1800, 7200), (10800, 14400)], 0, 99999), 3.0)
        self.assertEqual(balance.union_hours([(0, 7200)], 3600, 99999), 1.0)

    def test_weekdays(self):
        # 2026-11-06 is a Friday: Friday 12:00 to Monday 12:00 has 24 weekday hours.
        self.assertEqual(balance.weekday_seconds(ts("2026-11-06 12:00"), ts("2026-11-09 12:00")), 24 * 3600)


if __name__ == "__main__":
    unittest.main()
