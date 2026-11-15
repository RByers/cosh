import json
import os
import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timezone

from cosh import data_span as D


def reviews(weeks):
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT)")
    db.execute("INSERT INTO meta VALUES ('fetched_weeks', ?)", (json.dumps(weeks),))
    return db


def commits(*days):
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE commits (landed_at INTEGER)")
    for d in days:
        db.execute("INSERT INTO commits VALUES (?)", (int(datetime.fromisoformat(d).replace(tzinfo=timezone.utc).timestamp()),))
    return db


class DataSpanTest(unittest.TestCase):
    def test_gerrit_span(self):
        self.assertEqual(D.gerrit_span(reviews(["2026-W44", "2017-W27"])), (date(2017, 7, 3), date(2026, 11, 2)))
        self.assertIsNone(D.gerrit_span(reviews([])))

    def test_git_end_is_the_day_after_the_newest_commit(self):
        self.assertEqual(D.git_end(commits("2026-11-01T10:00", "2026-11-07T15:48")), date(2026, 11, 8))
        self.assertIsNone(D.git_end(commits()))

    def test_the_older_source_wins(self):
        ddb = reviews(["2017-W27", "2026-W44"])                 # through Sunday 2026-11-01
        newer_git = D.of_data(ddb=ddb, cdb=commits("2026-11-07T15:48"))
        self.assertEqual(newer_git, dict(first="2017-07-03", last="2026-11-01", sources=["gerrit", "git"]))
        older_git = D.of_data(ddb=ddb, cdb=commits("2026-10-20T08:00"))
        self.assertEqual(older_git["last"], "2026-10-20")

    def test_the_step_end_and_first(self):
        ddb = reviews(["2017-W27", "2026-W44"])
        s = D.of_data("2025-11-01", datetime(2026, 11, 1, tzinfo=timezone.utc), ddb=ddb, cdb=commits("2026-11-07"))
        self.assertEqual((s["first"], s["last"]), ("2025-11-01", "2026-10-31"))
        # Unix seconds, as review_feedback's START and END are.
        s = D.of_data(int(datetime(2017, 7, 3, tzinfo=timezone.utc).timestamp()), "2026-11-01",
                      sources=("gerrit",), ddb=ddb)
        self.assertEqual(s, dict(first="2017-07-03", last="2026-10-31", sources=["gerrit"]))

    def test_missing_files(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(D.of_data(data_dir=d))
            os.environ["COSH_COMMITS_DB"] = os.path.join(d, "none.sqlite")
            try:
                self.assertEqual(D.of_data("2026-01-05", "2026-02-02", data_dir=d)["last"], "2026-02-01")
            finally:
                del os.environ["COSH_COMMITS_DB"]


if __name__ == "__main__":
    unittest.main()
