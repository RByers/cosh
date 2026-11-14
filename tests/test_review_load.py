import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone

from cosh import commits as C
from cosh import review_load as L
from cosh import review_timeline as rt
from cosh.review_feedback import key


def read(*path):
    with open(os.path.join(*path)) as f:
        return json.load(f)


def ts(s):
    return int(datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc).timestamp())


class QuartersTest(unittest.TestCase):
    def test_quarters(self):
        self.assertEqual(L.quarter(ts("2026-09-30 23:59")), "2026Q3")
        self.assertEqual(L.quarter(ts("2026-10-01 00:00")), "2026Q4")
        self.assertEqual(L.quarters("2025Q3", "2026Q1"), ["2025Q3", "2025Q4", "2026Q1"])
        self.assertEqual(L.quarters("2026Q2", "2026Q1"), [])
        self.assertEqual(L.quarter_start("2026Q4"), ts("2026-10-01 00:00"))
        # Only whole quarters: data ending in November shows through Q3; ending on 1 January, through Q4.
        self.assertEqual(L.last_whole_quarter(ts("2026-11-02 00:00")), "2026Q3")
        self.assertEqual(L.last_whole_quarter(ts("2027-01-01 00:00")), "2026Q4")
        self.assertEqual(L.dir_levels("a/b/c/"), ["a/", "a/b/", "a/b/c/"])
        self.assertEqual(L.dir_levels("(root)/"), ["(root)/"])


class ComputeTest(unittest.TestCase):
    """A made-up history: two reviewed commits and what never counts as review."""

    def setUp(self):
        self.old = L.FIRST_QUARTER, L.ATTENTION_FROM, L.MIN_DIR_LINES
        L.FIRST_QUARTER, L.ATTENTION_FROM, L.MIN_DIR_LINES = "2026Q2", "2026Q3", 10
        g = self.gdb = sqlite3.connect(":memory:")
        g.executescript(C.SCHEMA)
        rb = json.dumps(["rev@google.com", "author@chromium.org", "bot@skia-public.iam.gserviceaccount.com"])
        q2, q3 = ts("2026-05-04 12:00"), ts("2026-08-03 12:00")

        def commit(cid, email, at, n, reviewed=rb, bot=0, revert=0, files=1, lsc=0):
            g.execute("INSERT INTO commits VALUES (?,?,?,?,?,?,?,?,?,NULL,?,0,0,?,0,0,?)",
                      (cid, f"sha{cid}", email, "n", at, at, n, bot, reviewed, revert, files, lsc))
        commit(1, "author@chromium.org", q2, 101)                              # reviewed, Q2
        commit(2, "author@chromium.org", q3, 102, json.dumps(["rev@chromium.org", "two@x.org"]))   # reviewed, Q3
        commit(3, "author@chromium.org", q3, 103, None)                        # no reviewer
        commit(4, "author@chromium.org", q3, 104, revert=1)                    # a revert
        commit(5, "author@chromium.org", q3, 105, lsc=1)                       # large-scale change
        commit(6, "author@chromium.org", q3, 106, files=100)                   # mechanical
        commit(7, "chromium-autoroll@skia-public.iam.gserviceaccount.com", q3, 107, bot=1)
        commit(8, "author@chromium.org", ts("2026-10-05 12:00"), 108)          # after the last whole quarter
        g.executescript("""
            INSERT INTO paths VALUES (1, 'a/b/c/x.cc'), (2, 'a/b/y.cc'), (3, 'z/big.cc');
            INSERT INTO tip_paths VALUES (1), (2), (3);
            INSERT INTO commit_files VALUES (1, 1, 30, 10), (2, 1, 60, 0), (2, 2, 15, 5), (2, 3, 0, -1), (6, 3, 500, 0);
        """)
        d = self.ddb = sqlite3.connect(":memory:")
        d.executescript("""
            CREATE TABLE meta (k TEXT, v TEXT);
            CREATE TABLE accounts (account_id INTEGER, email TEXT);
            CREATE TABLE changes (change_number INTEGER, created_at TEXT, is_bot_owned INTEGER, status TEXT);
            INSERT INTO meta VALUES ('fetched_weeks', '["2026-W18", "2026-W44"]');
            INSERT INTO accounts VALUES (7, 'rev@chromium.org'), (8, 'two@x.org'), (9, NULL);
            INSERT INTO changes VALUES (101, '2026-05-04 08:00:00', 0, 'MERGED'), (102, '2026-07-31 12:00:00', 0, 'MERGED'),
                                       (106, '2026-08-03 08:00:00', 0, 'MERGED');
        """)
        t = self.tdb = rt.connect(":memory:")
        t.executescript(rt.REVIEWERS_SCHEMA)
        fri = ts("2026-07-31 12:00")
        t.executemany("INSERT INTO cl_reviewers VALUES (?,?,?,?,?,?)", [
            (101, 7, None, ts("2026-05-04 10:00"), None, None),            # before the attention set: 2 h to first review
            (102, 7, fri + 3600, fri + 3 * 86400, 80.0, 30.0),             # asked Friday 13:00, answered Monday 12:00
            (102, 8, fri + 7200, None, 10.0, 10.0),                        # asked, never answered
            (102, 9, fri, fri + 60, 1.0, 1.0),                             # no address: not counted
            (106, 7, fri, fri + 60, 5.0, 5.0),                             # a mechanical commit's CL: not counted
        ])

    def tearDown(self):
        L.FIRST_QUARTER, L.ATTENTION_FROM, L.MIN_DIR_LINES = self.old

    def test_figures(self):
        data, people, pdirs = L.compute(self.gdb, self.ddb, self.tdb)
        self.assertEqual(data["quarters"], ["2026Q2", "2026Q3"])
        self.assertEqual(data["commits"], [1, 6])
        self.assertEqual(data["human"], [1, 5])
        self.assertEqual(data["reviewed"], [1, 1])
        # The author's own footer and the bot's don't count; two reviewers count the lines twice.
        self.assertEqual(data["reviewed_lines"], [40, 160])
        self.assertEqual(data["reviewers"], [1, 2])
        # Upload to first review, weekends out: 2 h; Friday 12:00 to Monday 12:00 is 24 weekday hours.
        self.assertEqual(data["first"], dict(mean=[2.0, 24.0], median=[2.0, 24.0], n=[1, 1]))
        # Asked Friday 13:00, answered Monday 12:00: 23 weekday hours. Nothing before the attention set.
        self.assertEqual(data["reply"], dict(mean=[None, 23.0], median=[None, 23.0], n=[0, 1]))
        self.assertEqual(data["attention"], dict(hours=[None, 40], turns=[None, 2], reviewers=[None, 2]))
        self.assertEqual(data["table_quarters"], ["2026Q2", "2026Q3"])
        # Each level's sums; the CL's attention is split by its lines (60 of 80 in a/b/c/, 20 in a/b/).
        self.assertEqual(data["dirs"], [["a/", [40, 160], [40.0], [2.0]], ["a/b/", [40, 160], [40.0], [2.0]],
                                        ["a/b/c/", [40, 120], [30.0], [1.5]]])
        rev = L.person("rev@chromium.org")
        self.assertEqual(people[rev], {"2026": {"2": [1, 40, 0.0, 0, 0.0, 0], "3": [1, 80, 30.0, 1, 23.0, 1]}})
        self.assertEqual(people["two@x.org"], {"2026": {"3": [1, 80, 10.0, 1, 0.0, 0]}})
        # Directories only for the table's quarters after the first.
        self.assertEqual(pdirs, {"2026Q3": {rev: [["a/b/", 20, 7.5, 0.25], ["a/b/c/", 60, 22.5, 0.75]],
                                            "two@x.org": [["a/b/", 20, 2.5, 0.25], ["a/b/c/", 60, 7.5, 0.75]]}})

    def test_files(self):
        data, people, pdirs = L.compute(self.gdb, self.ddb, self.tdb)
        with tempfile.TemporaryDirectory() as out:
            os.makedirs(os.path.join(out, "2019"))               # a stale year folder goes
            open(os.path.join(out, "2019", "old.json"), "w").close()
            n = L.write(out, data, people, pdirs)
            k = key("rev@google.com")                             # one person across the two domains
            self.assertEqual(n, 4)
            self.assertEqual(sorted(os.listdir(out)), ["2026", "all.json", "dirs"])
            self.assertEqual(read(out, "2026", f"{k}.json"),
                             {"q": {"2": [1, 40, 0.0, 0, 0.0, 0], "3": [1, 80, 30.0, 1, 23.0, 1]}})
            self.assertEqual(read(out, "dirs", "2026Q3", f"{k}.json"),
                             [["a/b/", 20, 7.5, 0.25], ["a/b/c/", 60, 22.5, 0.75]])
            self.assertEqual(read(out, "all.json")["reviewed_lines"], [40, 160])


if __name__ == "__main__":
    unittest.main()
