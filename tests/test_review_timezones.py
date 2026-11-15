import unittest

from cosh import owners
from cosh import review_timezones as T
from tests import test_review_load as RLT
from tests.test_review_load import ts


class TimezonesTest(unittest.TestCase):
    """Review Load's made-up history, with working windows: CL 102 (landed in 2026Q3) is by account 6,
    who works Asia-Pacific hours; its reviewers are 7 (Americas, and the owner of a/b/) and 8
    (Asia-Pacific)."""

    def setUp(self):
        base = RLT.ComputeTest()
        base.setUp()
        self.addCleanup(base.tearDown)
        self.gdb, self.ddb, self.tdb = base.gdb, base.ddb, base.tdb
        self.ddb.execute("ALTER TABLE accounts ADD COLUMN is_bot INTEGER DEFAULT 0")
        self.tdb.execute("DELETE FROM cl_turns")
        fri = ts("2026-07-31 12:00")
        self.tdb.executemany("INSERT INTO cl_turns VALUES (?,?,?,?,?,?,?)", [
            (102, 7, fri, fri + 3600, 1.0, 1.0, 5.0), (102, 8, fri, fri + 3600, 1.0, 1.0, 1.0),
            (101, 7, fri, fri + 3600, 1.0, 1.0, 9.0)])            # landed in Q2: not shown
        self.tdb.executemany("INSERT INTO work_windows VALUES (?,?,?,?,?)", [
            (6, "2026Q3", 1, "quarter", 50), (7, "2026Q3", 13, "quarter", 50), (8, "2026Q3", 2, "quarter", 50)])
        self.old = T.QUARTERS, T.MIN_DIR_TURNS, T.MIN_GROUP_TURNS
        T.QUARTERS, T.MIN_DIR_TURNS, T.MIN_GROUP_TURNS = 1, 1, 1

    def tearDown(self):
        T.QUARTERS, T.MIN_DIR_TURNS, T.MIN_GROUP_TURNS = self.old

    def test_compute(self):
        own = owners.Owners({"a/b/OWNERS": "rev@chromium.org\n", "z/OWNERS": "two@x.org\n"})
        data = T.compute(self.gdb, self.ddb, self.tdb, lambda sha: own)
        self.assertEqual(data["quarters"], ["2026Q3"])
        self.assertEqual(data["turns"], 2)
        # 7 shares no hours with the author, 8 shares 7.
        self.assertEqual([(b["lo"], b["n"]) for b in data["overlap"]], [(0, 1), (1, 0), (3, 0), (5, 0), (7, 1)])
        self.assertEqual(data["overlap"][0]["p"][2], 5.0)
        apac = data["by_region"]["APAC"]
        self.assertEqual((apac["n"], apac["by"]), (2, [[1, 5.0], [0, None], [1, 1.0]]))
        self.assertEqual(data["people"], [1, 0, 2])
        # Most of CL 102's lines are under a/b/OWNERS, whose one owner works other hours than the author.
        self.assertEqual(data["dirs"], [dict(d="a/b/", n=2, listed=1, owners=[1, 0, 0], unc=2, reg="APAC",
                                             mu=5.0, mc=None, extra=0)])

    def test_owners_dir(self):
        own = owners.Owners({"OWNERS": "", "a/OWNERS": "x@y.org\n"})
        self.assertEqual(T.owners_dir(own, "a/b/c"), "a")
        self.assertEqual(T.owners_dir(own, "z"), "")


if __name__ == "__main__":
    unittest.main()
