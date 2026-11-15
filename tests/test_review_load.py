import gzip
import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone

from cosh import commits as C
from cosh import review_load as L
from cosh import review_timeline as rt
from cosh.review_feedback import file_name


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
        # Before the first quarter: two more CLs approved as rev@google.com, which is no Gerrit
        # account's address; account 7 (rev@chromium.org) voted on them, so the two are one person.
        for cid, n in ((9, 109), (10, 110)):
            commit(cid, "author@chromium.org", ts("2025-01-06 12:00"), n, json.dumps(["rev@google.com"]))
        g.executescript("""
            INSERT INTO paths VALUES (1, 'a/b/c/x.cc'), (2, 'a/b/y.cc'), (3, 'z/big.cc');
            INSERT INTO tip_paths VALUES (1), (2), (3);
            INSERT INTO commit_files VALUES (1, 1, 30, 10), (2, 1, 60, 0), (2, 2, 15, 5), (2, 3, 0, -1), (6, 3, 500, 0);
        """)
        d = self.ddb = sqlite3.connect(":memory:")
        d.executescript("""
            CREATE TABLE meta (k TEXT, v TEXT);
            CREATE TABLE accounts (host TEXT DEFAULT 'chromium-review.googlesource.com', account_id INTEGER, email TEXT);
            CREATE TABLE changes (host TEXT DEFAULT 'chromium-review.googlesource.com', change_number INTEGER,
                                  created_at TEXT, is_bot_owned INTEGER, status TEXT, owner_account INTEGER DEFAULT 6,
                                  project TEXT DEFAULT 'chromium/src', branch TEXT DEFAULT 'main');
            INSERT INTO meta VALUES ('fetched_weeks', '["2026-W18", "2026-W44"]');
            INSERT INTO accounts (account_id, email) VALUES (6, 'author@chromium.org'), (7, 'rev@chromium.org'),
                                                            (8, 'two@x.org'), (9, NULL);
            INSERT INTO changes (change_number, created_at, is_bot_owned, status) VALUES
                (101, '2026-05-04 08:00:00', 0, 'MERGED'), (102, '2026-07-31 12:00:00', 0, 'MERGED'),
                (106, '2026-08-03 08:00:00', 0, 'MERGED');
        """)
        t = self.tdb = rt.connect(":memory:")
        t.executescript(rt.SCHEMA + rt.REVIEWERS_SCHEMA)
        # Account 7 approved every CL whose Reviewed-by names rev@google.com.
        t.executemany("INSERT INTO votes VALUES (?,?,?,?,?)", [(n, 7, 1, 0, 1) for n in (101, 104, 105, 106, 108, 109, 110)])
        fri = ts("2026-07-31 12:00")
        t.executemany("INSERT INTO cl_reviewers VALUES (?,?,?,?,?,?)", [
            (101, 7, None, ts("2026-05-04 10:00"), None, None),            # before the attention set: 2 h to first review
            (102, 7, fri + 3600, fri + 3 * 86400, 80.0, 30.0),             # asked Friday 13:00, answered Monday 12:00
            (102, 8, fri + 7200, None, 10.0, 10.0),                        # asked, never answered: open at the close
            (102, 9, fri, fri + 60, 1.0, 1.0),                             # no address: not counted
            (106, 7, fri, fri + 60, 5.0, 5.0),                             # a mechanical commit's CL: not counted
        ])
        t.executemany("INSERT INTO cl_turns VALUES (?,?,?,?,?)", [
            (102, 7, fri + 3600, fri + 86400, 20.0), (102, 7, fri + 2 * 86400, fri + 3 * 86400, 4.0),
            (102, 9, fri, fri + 60, 1.0), (106, 7, fri, fri + 60, 5.0)])

    def tearDown(self):
        L.FIRST_QUARTER, L.ATTENTION_FROM, L.MIN_DIR_LINES = self.old

    def test_figures(self):
        data, people, pdirs, aliases, prows = L.compute(self.gdb, self.ddb, self.tdb)
        self.assertEqual(data["quarters"], ["2026Q2", "2026Q3"])
        self.assertEqual(data["commits"], [1, 6])
        self.assertEqual(data["human"], [1, 5])
        self.assertEqual(data["reviewed"], [1, 1])
        # The author's own footer and the bot's don't count; two reviewers count the lines twice.
        self.assertEqual(data["reviewed_lines"], [40, 160])
        self.assertEqual(data["reviewers"], [1, 2])
        # Q3's commit has two reviewers: its 80 lines count twice in reviewed_lines.
        self.assertEqual(data["reviewers_per_commit"], dict(lines=[40, 80], reviews=[1, 2], multi=[0, 1]))
        self.assertNotIn("first", data)
        # Asked Friday 13:00, answered Monday 12:00: 23 weekday hours. Nothing before the attention set.
        self.assertEqual(data["reply"], dict(p10=[None, 23.0], p25=[None, 23.0], p50=[None, 23.0], p75=[None, 23.0],
                                             p90=[None, 23.0], mean=[None, 23.0], n=[0, 1]))
        # Lines per reviewer: rev's 40 in Q2; rev's and two@x.org's 80 each in Q3.
        q = [40, 80]
        self.assertEqual(data["reviewer_lines"], dict(p10=q, p25=q, p50=q, p75=q, p90=q, mean=q, n=[1, 2]))
        # Reviewer 7's turns of 20 and 4 hours.
        self.assertEqual(data["turns"], dict(p10=[None, 5.6], p25=[None, 8.0], p50=[None, 12.0], p75=[None, 16.0],
                                             p90=[None, 18.4], mean=[None, 12.0], n=[0, 2]))
        self.assertEqual(data["table_quarters"], ["2026Q2", "2026Q3"])
        self.assertIsNone(data["owners"])
        # Each row's weighted percentiles; the CL's turns weigh by its lines (60 of 80 in a/b/c/, 20 in a/b/).
        pc = [4.0, 20.0, 20.0]
        self.assertEqual(data["dirs"], [["a/", [40, 160], [pc], [2.0], pc], ["a/b/", [40, 160], [pc], [2.0], pc],
                                        ["a/b/c/", [40, 120], [pc], [1.5], pc]])
        # a/b/'s own files are its "Other"; a/ has nothing outside a/b/.
        self.assertEqual(data["others"], [["a/", [None], [0], None], ["a/b/", [pc], [0.5], pc]])
        # rev@google.com (the Q2 footer) and account 7 are one identity, by the votes; not by domain.
        rev = "rev@chromium.org"
        self.assertEqual(aliases, {"rev@google.com": rev})
        self.assertEqual(people[rev], {"2026": {"2": [1, 40, 0.0, 0, 0.0, 0], "3": [1, 80, 30.0, 1, 23.0, 1]}})
        self.assertEqual(people["two@x.org"], {"2026": {"3": [1, 80, 10.0, 1, 0.0, 0]}})
        # Directories only for the table's quarters after the first.
        self.assertEqual(pdirs, {"2026Q3": {rev: [["a/b/", 20], ["a/b/c/", 60]],
                                            "two@x.org": [["a/b/", 20], ["a/b/c/", 60]]}})
        self.assertEqual(prows, {rev: {"turns": {"2026Q3": [12.0, 2]},
                                       "rows": {"d:a/": [*pc, 2.0], "d:a/b/": [*pc, 2.0], "d:a/b/c/": [*pc, 1.5],
                                                "o:a/b/": [*pc, 0.5]}}})
        self.assertEqual(L.table_rows("q/r/s/", {"a/"}, set()), ("o:",))
        self.assertEqual(L.weighted_pcts([(1, 1), (2, 1), (3, 1), (9, 0)]), [2, 3, 3])

    def test_owners(self):
        from cosh.owners import Owners
        # A third commit: by new@x.org, who has never voted, approved by rev and two@x.org.
        self.gdb.execute("INSERT INTO commits VALUES (11,'sha11','new@x.org','n',?,?,111,0,?,NULL,0,0,0,1,0,0,0)",
                         (ts("2026-08-04 12:00"),) * 2 + (json.dumps(["rev@chromium.org", "two@x.org"]),))
        self.gdb.execute("INSERT INTO commit_files VALUES (11, 1, 10, 0), (11, 2, 10, 0)")
        seen = []
        own = Owners({"OWNERS": "root@x.org\n", "a/OWNERS": "rev@google.com  # an alias of rev\nidle@x.org\n",
                      "a/b/c/OWNERS": "set noparent\nfile://a/b/C_OWNERS\nper-file x.cc=nobody@x.org\n",
                      "a/b/C_OWNERS": "two@x.org\n", "a/b/c/d/e/OWNERS": "deep@x.org\n"})
        self.assertEqual(own.of("a/b"), ({"root@x.org", "rev@google.com", "idle@x.org"}, False))
        self.assertEqual(own.of("a/b/c"), ({"two@x.org"}, False))
        self.assertEqual(own.of("gone/dir"), ({"root@x.org"}, False))
        data, *_ = L.compute(self.gdb, self.ddb, self.tdb, lambda sha: seen.append(sha) or own)
        self.assertEqual(seen, ["sha11"])                 # the last quarter's last commit
        self.assertEqual(data["owners"]["at"], "2026-08-04")
        # Q3: commit 2 (rev, two: 60 lines in a/b/c, 20 in a/b) and commit 11 (rev, two: 10 and 10).
        # a/b/c is two's alone, a/b is rev's. author@ has voted nowhere but landed commit 1 with one
        # reviewer, so only new@x.org's commit needed two approvals, and no file had two owners.
        figures = {d[0]: d[5] for d in data["dirs"]}
        self.assertEqual(figures["a/b/c/"], [2, 1, 2, 1, 70, 10, 0])
        self.assertEqual(figures["a/b/"], [2, 1, 2, 1, 100, 20, 0])
        self.assertEqual(figures["a/"], [2, 1, 4, 2, 100, 20, 0])
        self.assertEqual(data["owners"]["all"], [2, 1, 5, 2, 100, 20, 0])
        self.assertEqual(L.half_by([5, 1, 1, 1]), 1)
        self.assertEqual(L.half_by([2, 2, 2, 2]), 2)
        self.assertEqual(L.half_by([]), 0)

    def test_files(self):
        data, people, pdirs, aliases, prows = L.compute(self.gdb, self.ddb, self.tdb)
        with tempfile.TemporaryDirectory() as out, tempfile.TemporaryDirectory() as pout:
            os.makedirs(os.path.join(out, "2019"))               # a per-reviewer folder from before R2 goes
            open(os.path.join(out, "2019", "old.json"), "w").close()
            os.makedirs(os.path.join(pout, "2019"))              # so does a stale year's file
            open(os.path.join(pout, "2019", "old.json.gz"), "w").close()
            n = L.write(out, data, people, pdirs, pout, aliases, prows)
            k = file_name("rev@chromium.org")
            self.assertEqual(k, "rev@chromium.org")
            self.assertEqual(n, 3)
            self.assertEqual(sorted(os.listdir(out)), ["all.json"])
            self.assertEqual(sorted(os.listdir(pout)), [f"{k}.json.gz", "rev@google.com.json.gz", "two@x.org.json.gz"])
            gz = lambda *p: json.loads(gzip.decompress(open(os.path.join(pout, *p), "rb").read()))
            # The other address finds them through a stub.
            self.assertEqual(gz("rev@google.com.json.gz"), {"see": k})
            self.assertEqual(gz(f"{k}.json.gz"), {
                "v": 2, "years": {"2026": {"q": {"2": [1, 40, 0.0, 0, 0.0, 0], "3": [1, 80, 30.0, 1, 23.0, 1]}}},
                "turns": {"2026Q3": [12.0, 2]},
                "dirs": {"2026Q3": [["a/b/", 20], ["a/b/c/", 60]]},
                "rows": {"d:a/": [4.0, 20.0, 20.0, 2.0], "d:a/b/": [4.0, 20.0, 20.0, 2.0],
                         "d:a/b/c/": [4.0, 20.0, 20.0, 1.5], "o:a/b/": [4.0, 20.0, 20.0, 0.5]}})
            self.assertEqual(read(out, "all.json")["reviewed_lines"], [40, 160])
            # A second run leaves unchanged files' bytes alone.
            before = open(os.path.join(pout, f"{k}.json.gz"), "rb").read()
            L.write(out, data, people, pdirs, pout, aliases, prows)
            self.assertEqual(open(os.path.join(pout, f"{k}.json.gz"), "rb").read(), before)



class IdentityTest(unittest.TestCase):
    def test_exact_addresses(self):
        from cosh import people as P
        self.assertEqual(P.address(" A@Chromium.ORG "), "a@chromium.org")
        self.assertEqual(P.address("x@chromium.org@0039d316-1c4b-4281-b951-d872f2087c98"), "x@chromium.org")
        ids = P.Ids(P.address)
        self.assertNotEqual(ids.find("a@chromium.org"), ids.find("a@google.com"))
        ids.union("a@google.com", "b@x.org")
        self.assertEqual(ids.groups()["a@google.com"], {"a@google.com", "b@x.org"})

    def test_vote_links(self):
        from cosh import people as P
        accounts = {1: "new@google.com", 2: "other@x.org", 3: "third@x.org"}
        rb = [(1, ["old@chromium.org"]), (2, ["old@chromium.org"]), (3, ["old@chromium.org", "other@x.org"]),
              # Two unknown addresses on one CL: no link from it.
              (4, ["old@chromium.org", "gone@x.org"])]
        voters = {1: {1}, 2: {1}, 3: {1, 2}, 4: {1, 3}}
        self.assertEqual(P.vote_links(rb, accounts, voters), [("old@chromium.org", "new@google.com")])
        # One CL isn't enough.
        self.assertEqual(P.vote_links(rb[:1], accounts, voters), [])


if __name__ == "__main__":
    unittest.main()
