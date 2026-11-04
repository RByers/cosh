"""Offline tests of the open-CL snapshot: a fake Gerrit client stands in for
the network, and the NoteDb fetch is stubbed out."""

import json
import re
import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock

from cosh import extract, store

H = "chromium-review.googlesource.com"
P = "chromium/src"
OWNER = {"_account_id": 1, "email": "o@chromium.org"}


def cl(n, status, updated, submitted=None, comments=1):
    c = {"_number": n, "status": status, "project": P, "branch": "main", "owner": OWNER,
         "created": "2025-01-01 00:00:00.000000000", "updated": updated,
         "total_comment_count": comments}
    if submitted:
        c["submitted"] = submitted
    return c


class FakeGerrit:
    """Answers /changes/ queries over a fixed list of CLs, like Gerrit would."""
    def __init__(self, changes, page=500):
        self.changes, self.page, self.queries, self.request_count = changes, page, [], 0
        self.host = H

    def get(self, path, params=None):
        self.request_count += 1
        q = dict(params)["q"]
        self.queries.append(q)
        status = re.search(r"status:(\w+)", q).group(1)
        lo, hi = re.findall(r'"([\d\- :]+) \+0000"', q)
        field = "submitted" if "mergedafter" in q else "updated"
        want = {"open": "NEW", "merged": "MERGED", "abandoned": "ABANDONED"}[status]
        hits = [c for c in self.changes if c["status"] == want
                and lo <= c.get(field, "")[:19] <= hi]
        hits = sorted(hits, key=lambda c: c["updated"], reverse=True)
        out = [dict(c) for c in hits[:self.page]]
        if len(hits) > self.page:
            out[-1]["_more_changes"] = True
        return 200, json.dumps(out), "https://" + H + path


class ExtractOpenTest(unittest.TestCase):
    def run_open(self, d, changes, page=500, **kw):
        fake = FakeGerrit(changes, page)
        fetched = []

        def fake_fetch(client, raw, project, todo, listed, *a, **k):
            fetched.append(sorted(todo))
            return []
        now = datetime(2026, 11, 4, 12, tzinfo=timezone.utc)
        with mock.patch.object(extract, "GerritClient", lambda host, min_interval: fake), \
                mock.patch.object(extract, "fetch_notedb", fake_fetch), \
                mock.patch.object(store, "now_iso", lambda: "2026-11-04T12:00:00Z"), \
                mock.patch.object(extract, "datetime", wraps=datetime) as dt:
            dt.now.return_value = now
            dt.strptime = datetime.strptime
            extract.extract_open(H, P, data_dir=d, **kw)
        return fake, fetched

    def test_snapshot_lists_open_and_recently_closed(self):
        changes = [
            cl(1, "NEW", "2025-12-01 00:00:00"),                       # open, in range
            cl(2, "NEW", "2025-10-01 00:00:00"),                       # open, too old
            cl(3, "NEW", "2026-06-01 00:00:00", comments=0),           # open, no comments
            cl(4, "MERGED", "2026-11-03 00:00:00", "2026-11-03 00:00:00"),   # closed after W44
            cl(5, "MERGED", "2026-11-03 00:00:00", "2026-10-30 00:00:00"),   # closed in W44
            cl(6, "ABANDONED", "2026-11-02 05:00:00"),                 # abandoned after W44
            cl(7, "NEW", "2026-11-04 12:00:00"),                       # updated mid-listing
        ]
        with tempfile.TemporaryDirectory() as d:
            raw = store.open_raw(d)
            with raw:
                raw.executemany("INSERT INTO week_progress(host, project, iso_week, fetched_at) "
                                "VALUES (?,?,?,?)", [(H, P, "2025-W45", "t"), (H, P, "2026-W44", "t")])
            raw.close()
            fake, fetched = self.run_open(d, changes)
            raw = store.open_raw(d)
            snap = raw.execute("SELECT listed_at, since, closed_since, cl_count, fetched_at "
                               "FROM open_listings").fetchall()
            listed = sorted(n for (n,) in raw.execute("SELECT change_number FROM open_changes"))
            raw.close()
        self.assertEqual(snap, [("2026-11-04T12:00:00Z", "2025-11-03T00:00:00Z",
                                 "2026-11-02T00:00:00Z", 5, "2026-11-04T12:00:00Z")])
        self.assertEqual(listed, [1, 3, 4, 6, 7])
        self.assertEqual(fetched, [[1, 4, 6, 7]])          # CL 3 has no comments
        self.assertTrue(all("branch:main" in q for q in fake.queries))
        # weekly open windows over the year, then closed-since windows, then catch-up
        self.assertEqual(sum("status:open" in q for q in fake.queries), 53 + 1)

    def test_overflowing_window_is_bisected(self):
        changes = [cl(n, "NEW", f"2026-01-0{1 + n % 5} 00:00:00") for n in range(10)]
        with tempfile.TemporaryDirectory() as d:
            fake, fetched = self.run_open(d, changes, page=4, since="2026-01-01T00:00:00Z",
                                          closed_since="2026-11-04T00:00:00Z")
        self.assertEqual(fetched, [list(range(10))])

    def test_unfinished_snapshot_is_resumed(self):
        with tempfile.TemporaryDirectory() as d:
            raw = store.open_raw(d)
            with raw:
                raw.execute("INSERT INTO open_listings(host, project, listed_at, since, closed_since) "
                            "VALUES (?,?,?,?,?)", (H, P, "2026-11-01T00:00:00Z",
                                                   "2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z"))
            raw.close()
            fake, _ = self.run_open(d, [cl(1, "NEW", "2026-10-15 00:00:00")])
            raw = store.open_raw(d)
            rows = raw.execute("SELECT listed_at, fetched_at FROM open_listings").fetchall()
            raw.close()
        self.assertEqual(rows, [("2026-11-01T00:00:00Z", "2026-11-04T12:00:00Z")])


class StaleRefsTest(unittest.TestCase):
    def test_missing_or_older_than_listing(self):
        t = lambda s: datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
        listed = {n: ("k", {"updated": "2026-10-01 00:00:00.000000000"}) for n in (1, 2, 3)}
        tips = {1: t("2026-10-01 00:00:00"), 2: t("2026-09-30 23:59:59")}
        self.assertEqual(extract.stale_refs([1, 2, 3], listed, tips), [2, 3])


if __name__ == "__main__":
    unittest.main()
