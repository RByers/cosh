"""cosh.bugs: footer parsing, response parsing and the fetch stop rules.
No network: a fake transport stands in for issues.chromium.org."""

import gzip
import io
import json
import os
import tempfile
import unittest

os.environ.setdefault("COSH_CONTACT", "test@example.invalid")

from cosh import bugs  # noqa: E402

FIELD_DEFS = [
    [1223136, 1363614, 5, None, "CVE", None, None, None, 2],
    [1544844, 1363614, 1, None, "Introduced In", None, None, None, 2],
    [1223085, 1363614, 8, None, "Milestone", None, None, None, 2],
    [1223031, 1363614, 5, None, "Chromium Labels", None, None, None, 2],
    [1222907, 1363614, 7, None, "Component Tags", None, None, ["Blink"], 1],
]


def cf(field_id, display):
    return [field_id, None, None, None, None, None, None, None, None, display,
            [[None, display]]]


def issue(n, status=4, typ=1, pri=2, sev=3, custom=(), fixes=(), resolved=True):
    """A synthetic issue in the shape of a b.IssueSearchResponse entry."""
    core = [None] * 40
    core[:6] = [1456393, typ, status, pri, sev, f"title {n}"]
    core[13] = [4667236]
    core[14] = [cf(*c) for c in custom]
    core[16] = ["135"]
    core[34] = [list(f) for f in fixes] or None
    core[39] = 1456393
    i = [None] * 48
    i[1], i[2] = n, core
    i[4], i[5] = [1741603356, 916000000], [1743086443, 435000000]
    i[6] = [1743086443, 0] if resolved else None
    i[14] = FIELD_DEFS
    i[41] = 157
    return i


def search_body(issues):
    d = [["b.IssueSearchResponse", None, None, None, None, None,
          [issues, None, len(issues), True]]]
    return b")]}'\n\n" + json.dumps(d).encode()


class FakeTransport:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, method, url, body, headers):
        self.calls.append((method, url, body, headers))
        st, ctype, rbody = self.replies.pop(0)
        return st, {"content-type": ctype}, rbody, rbody, url


class FooterTest(unittest.TestCase):
    def test_forms(self):
        ids, skipped = bugs.footer_ids(
            "123456789, chromium:1234567 crbug.com/40012345, https://crbug.com/987654321, "
            "b:333333333, b/444444444 v8:12345 https://issues.chromium.org/issues/40099999.")
        self.assertEqual(ids, [123456789, 1234567, 40012345, 987654321, 40099999])
        self.assertEqual(skipped, 3)

    def test_junk(self):
        self.assertEqual(bugs.footer_ids("None"), ([], 0))
        self.assertEqual(bugs.footer_ids("12, N/A"), ([], 1))

    def test_build_wanted(self):
        db = bugs.open_db(tempfile.mkdtemp())
        footers = [("2024-01-02T00:00:00+00:00", "Bug", "400000001, 1234567"),
                   ("2024-03-01T00:00:00+00:00", "Fixed", "400000001"),
                   ("2023-08-01T00:00:00+00:00", "Bug", "b:400000009")]
        c = bugs.build_wanted(db, footers, [400000002, 1234567])
        self.assertEqual(c["ids"], 3)
        self.assertEqual(c["security_only"], 1)
        self.assertEqual(c["monorail_era"], 1)
        self.assertEqual(c["skipped_tokens"], 1)
        row = db.execute("SELECT * FROM wanted WHERE id=400000001").fetchone()
        self.assertEqual(row, (400000001, 1, 1, 0, "2024-01-02T00:00:00+00:00",
                               "2024-03-01T00:00:00+00:00"))
        # Monorail-era IDs are mapped first, not asked directly.
        self.assertEqual(bugs.to_ask(db), [400000002, 400000001])


class ParseTest(unittest.TestCase):
    def test_issue(self):
        i = issue(400000001, custom=[(1223136, "CVE-2026-1234"), (1544844, "134"),
                                     (1222907, "Blink>Layout"), (999, "x")],
                  fixes=[("chromium", "chromium/src", 6401913, 2)])
        r = bugs.parse_issue(i)
        self.assertEqual(r["id"], 400000001)
        self.assertEqual((r["type_name"], r["status_name"], r["priority"], r["severity"]),
                         ("Bug", "Fixed", "P1", "S2"))
        self.assertEqual(r["created"], "2025-03-10T10:42:36Z")
        self.assertEqual(r["resolved"], "2025-03-27T14:40:43Z")
        self.assertEqual((r["cve"], r["introduced_in"], r["component_path"]),
                         ("CVE-2026-1234", "134", "Blink>Layout"))
        self.assertEqual(json.loads(r["fixed_by"]), ["chromium/chromium/src/6401913"])
        self.assertEqual(json.loads(r["custom"])["999"], "x")
        self.assertEqual(r["regression"], 1)
        self.assertEqual(r["hotlists"], "[4667236]")

    def test_open_no_custom(self):
        r = bugs.parse_issue(issue(1, status=1, typ=6, pri=1, sev=None, resolved=False))
        self.assertEqual((r["status_name"], r["type_name"], r["priority"], r["severity"],
                          r["resolved"], r["regression"]), ("New", "Vulnerability", "P0",
                                                            None, None, 0))

    def test_label_regression(self):
        r = bugs.parse_issue(issue(1, custom=[(1223031, "Type-Bug-Regression, allpublic")]))
        self.assertEqual(r["regression"], 1)

    def test_shapes(self):
        self.assertEqual(len(bugs.search_issues(search_body([issue(5)]))), 1)
        empty = b")]}'\n\n" + json.dumps(
            [["b.IssueSearchResponse", None, None, None, None, None, None]]).encode()
        self.assertEqual(bugs.search_issues(empty), [])
        for bad in (b'{"a":1}', b")]}'\n\n[[\"er\",null,null,null,null,405]]",
                    b")]}'\n\n" + json.dumps([["b.IssueSearchResponse", None, None, None,
                                               None, None, [[[1, 2]]]]]).encode()):
            with self.assertRaises(ValueError):
                bugs.search_issues(bad)

    def test_monorail(self):
        stub = b'<script>\n  const url = "https://issues.chromium.org/40097049"\n</script>'
        self.assertEqual(bugs.monorail_target(stub), 40097049)
        self.assertIsNone(bugs.monorail_target(b"<html>nothing</html>"))


class FetchTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.db = bugs.open_db(self.dir)
        self.slept = []
        self.now = [0.0]

    def fetcher(self, replies, backoff=(300, 900)):
        self.t = FakeTransport(replies)

        def sleep(s):
            self.slept.append(s)
            self.now[0] += s

        def clock():
            self.now[0] += 0.5
            return self.now[0]
        return bugs.Fetcher(self.db, data_dir=self.dir, interval=2, transport=self.t,
                            log=io.StringIO(), sleep=sleep, clock=clock,
                            backoff=backoff)

    def test_batch(self):
        f = self.fetcher([(200, "application/json", search_body([issue(11), issue(13)])),
                          (200, "application/json", search_body([]))])
        self.assertEqual(f.fetch_batch([11, 12, 13]), 2)
        self.assertEqual(f.fetch_batch([14]), 0)
        method, url, body, headers = self.t.calls[0]
        self.assertEqual((method, url), ("POST", bugs.LIST_URL))
        q = json.loads(body)
        self.assertEqual(q[5], ["157"])
        self.assertEqual(q[6][0], "id:(11 | 12 | 13)")
        self.assertIn("test@example.invalid", headers["User-Agent"])
        self.assertEqual(self.db.execute("SELECT id, visible FROM asked ORDER BY id").fetchall(),
                         [(11, 1), (12, 0), (13, 1), (14, 0)])
        self.assertEqual(self.db.execute("SELECT count(*) FROM bugs").fetchone()[0], 2)
        rel = self.db.execute("SELECT file FROM requests WHERE seq=1").fetchone()[0]
        with gzip.open(os.path.join(self.dir, "bugs", rel)) as fh:
            self.assertEqual(fh.read(), search_body([issue(11), issue(13)]))
        self.assertTrue(self.slept and all(s <= 2 for s in self.slept))  # paced

    def test_retry_missing(self):
        f = self.fetcher([(200, "application/json", search_body([issue(11)]))])
        f.fetch_batch([11, 12])
        self.assertEqual(bugs.to_ask(self.db, retry_missing=True, older_than_days=0), [12])
        self.assertEqual(bugs.to_ask(self.db, retry_missing=True, older_than_days=30), [])

    def test_429_backs_off_then_stops(self):
        f = self.fetcher([(429, "text/plain", b"slow down")] * 3)
        with self.assertRaises(bugs.Stop):
            f.fetch_batch([11])
        self.assertIn(300, self.slept)
        self.assertIn(900, self.slept)
        self.assertEqual(len(self.t.calls), 3)

    def test_429_recovers(self):
        f = self.fetcher([(503, "text/plain", b""),
                          (200, "application/json", search_body([issue(11)]))])
        self.assertEqual(f.fetch_batch([11]), 1)

    def test_captcha_stops(self):
        f = self.fetcher([(200, "text/html", b"<html>Our systems have detected unusual "
                                             b"traffic</html>")])
        with self.assertRaises(bugs.Stop):
            f.fetch_batch([11])
        self.assertEqual(self.db.execute("SELECT outcome FROM requests").fetchone()[0],
                         "blocked")

    def test_403_stops(self):
        f = self.fetcher([(403, "application/json", b"denied")])
        with self.assertRaises(bugs.Stop):
            f.fetch_batch([11])

    def test_bad_shapes_stop(self):
        bad = (200, "application/json", b")]}'\n\n[]")
        f = self.fetcher([bad] * 3)
        self.assertEqual(f.fetch_batch([1]), 0)
        self.assertEqual(f.fetch_batch([2]), 0)
        with self.assertRaises(bugs.Stop):
            f.fetch_batch([3])
        self.assertEqual(self.db.execute("SELECT count(*) FROM asked").fetchone()[0], 0)

    def test_title_words_dont_trip_block_check(self):
        i = issue(11)
        i[2][5] = "captcha accounts.google.com unusual traffic"
        f = self.fetcher([(200, "application/json", search_body([i]))])
        self.assertEqual(f.fetch_batch([11]), 1)

    def test_interval_floor(self):
        with self.assertRaises(SystemExit):
            bugs.Fetcher(self.db, data_dir=self.dir, interval=0.5)

    def test_monorail_lookup(self):
        stub = b'<script>const url = "https://issues.chromium.org/40097049"</script>'
        f = self.fetcher([(200, "text/html", stub), (404, "text/html", b"not found")])
        self.assertEqual(f.resolve_monorail(1018677), 40097049)
        self.assertIsNone(f.resolve_monorail(1018678))
        self.assertEqual(self.db.execute("SELECT * FROM monorail_map ORDER BY old_id")
                         .fetchall()[0][:3], (1018677, 40097049, 200))

    def test_parse_rebuilds(self):
        f = self.fetcher([(200, "application/json", search_body([issue(11)]))])
        f.fetch_batch([11])
        self.db.execute("DELETE FROM bugs")
        self.db.commit()
        old = bugs.store.DATA_DIR
        bugs.store.DATA_DIR = self.dir
        try:
            import contextlib
            import io
            with contextlib.redirect_stdout(io.StringIO()):
                bugs.cmd_parse(None)
        finally:
            bugs.store.DATA_DIR = old
        self.assertEqual(self.db.execute("SELECT id FROM bugs").fetchall(), [(11,)])


if __name__ == "__main__":
    unittest.main()
