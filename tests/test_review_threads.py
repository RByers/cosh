"""cosh.review_threads (the comment download's files) and cosh.r2 (their upload)."""
import datetime as dt
import gzip
import json
import os
import tempfile
import unittest
from unittest import mock

from cosh import r2, review_threads as RT


def c(cid, aid, at, msg, parent=None, **kw):
    d = {"id": cid, "author": {"_account_id": aid}, "updated": at, "message": msg, **kw}
    if parent:
        d["in_reply_to"] = parent
    return d


class ThreadsTest(unittest.TestCase):
    def test_shard_cls(self):
        self.assertEqual(RT.shard_cls({"cls": [[100, 5], [3, 1], [10, 0]]}), [100, 103, 113])

    def test_cl_threads(self):
        owner, rev, bot, other = 1, 2, 9, 3
        comments = {
            "a.cc": [c("r1", rev, "2026-01-02 10:11:12.000000000", "Rename", line=12, patch_set=3, unresolved=True),
                     c("o1", owner, "2026-01-02 11:00:00.000000000", "Done", parent="r1", patch_set=4,
                       unresolved=False)],
            "/PATCHSET_LEVEL": [c("r2", other, "2026-01-01 09:00:00.000000000", "LGTM", patch_set=1)],
            "b.cc": [c("own", owner, "2026-01-01 08:00:00.000000000", "Note to reviewers"),
                     c("b1", bot, "2026-01-01 08:30:00.000000000", "Lint"),
                     c("ai", rev, "2026-01-01 08:40:00.000000000", "AI says", is_ai=True)],
        }
        got = RT.cl_threads(comments, owner, {bot}, {"r1": True}.get)
        self.assertEqual(got, [
            dict(id="r2", path="/PATCHSET_LEVEL", line=None, ps=1, addressed=None, resolved=True,
                 comments=[[other, "2026-01-01T09:00Z", "LGTM"]]),
            dict(id="r1", path="a.cc", line=12, ps=3, addressed=True, resolved=True,
                 comments=[[rev, "2026-01-02T10:11Z", "Rename"], [owner, "2026-01-02T11:00Z", "Done"]]),
        ])
        self.assertEqual(RT.cl_threads(None, owner, set(), {}.get), [])

    def test_write_is_stable(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "2026H1", "k.json.gz")
            doc = {"v": 1, "cls": [{"subject": "é"}]}
            self.assertTrue(RT.write(p, doc)[1])
            with open(p, "rb") as f:
                first = f.read()
            self.assertFalse(RT.write(p, doc)[1])
            self.assertEqual(json.loads(gzip.decompress(first)), doc)
            self.assertTrue(RT.write(p, {"v": 1, "cls": []})[1])


class R2Test(unittest.TestCase):
    def test_sign_matches_aws_example(self):
        # The GET Object example of AWS's "Signature Version 4 (header-based)" S3 docs.
        cred = {"access_key_id": "AKIAIOSFODNN7EXAMPLE",
                "secret_access_key": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"}
        empty = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        h = r2.sign("GET", "https://examplebucket.s3.amazonaws.com/test.txt", {"Range": "bytes=0-9"}, empty, cred,
                    now=dt.datetime(2013, 5, 24, tzinfo=dt.timezone.utc), region="us-east-1")
        self.assertEqual(h["authorization"],
                         "AWS4-HMAC-SHA256 Credential=AKIAIOSFODNN7EXAMPLE/20130524/us-east-1/s3/aws4_request, "
                         "SignedHeaders=host;range;x-amz-content-sha256;x-amz-date, "
                         "Signature=f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41")

    def test_object_key(self):
        self.assertEqual(r2.object_key("/a/b/", os.path.join("2026H1", "k.json.gz")), ("a/b/2026H1/k.json", True))
        self.assertEqual(r2.object_key("a", "x.json"), ("a/x.json", False))

    def test_sync_uploads_changes_and_deletes_and_keeps_a_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            local, data = os.path.join(d, "files"), os.path.join(d, "data")
            os.makedirs(os.path.join(local, "H"))
            os.makedirs(data)
            for name, body in (("a.json.gz", b"A"), ("b.json.gz", b"B")):
                with open(os.path.join(local, "H", name), "wb") as f:
                    f.write(body)
            calls = []

            def fake(cred, method, key, body=b"", headers=None):
                calls.append((method, key, body, headers))
                return 200
            with mock.patch.object(r2, "request", fake):
                r2.sync(local, "p", data_dir=data, cred={}, jobs=1)
                self.assertEqual(sorted((m, k, b) for m, k, b, _ in calls),
                                 [("PUT", "p/H/a.json", b"A"), ("PUT", "p/H/b.json", b"B")])
                self.assertEqual(calls[0][3]["content-encoding"], "gzip")
                self.assertEqual(calls[0][3]["content-type"], "application/json")
                calls.clear()
                r2.sync(local, "p", data_dir=data, cred={}, jobs=1)
                self.assertEqual(calls, [])
                with open(os.path.join(local, "H", "a.json.gz"), "wb") as f:
                    f.write(b"A2")
                os.remove(os.path.join(local, "H", "b.json.gz"))
                r2.sync(local, "p", data_dir=data, cred={}, jobs=1)
                self.assertEqual([(m, k) for m, k, _, _ in calls], [("PUT", "p/H/a.json"), ("DELETE", "p/H/b.json")])
                with open(r2.manifest_path(data)) as f:
                    self.assertEqual(sorted(json.load(f)), ["p/H/a.json"])
                calls.clear()
                with open(os.path.join(local, "H", "c.json.gz"), "wb") as f:
                    f.write(b"C")
                with self.assertRaises(SystemExit):
                    r2.sync(local, "p", data_dir=data, cred={}, max_objects=0)
                with self.assertRaises(SystemExit):
                    r2.sync(local, "p", data_dir=data, cred={}, max_total_gb=1e-9)
                self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
