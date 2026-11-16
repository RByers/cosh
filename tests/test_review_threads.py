"""cosh.review_threads (the comment download's files) and cosh.r2 (their upload)."""
import datetime as dt
import gzip
import hashlib
import json
import os
import subprocess
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
    def test_read_index(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "feedback-cls.json.gz")
            with gzip.open(p, "wt") as f:
                json.dump({"v": 1, "dirs": ["a/b/c/", "a/"], "people": {"a@google.com": {
                    "2026H1": [[5, ["a@google.com", "b@x.org"], {"r1": 1, "r2": 0}], [7, [], {}]]}}}, f)
            self.assertEqual(RT.read_index(p), {"a@google.com": {"2026H1": [
                (5, ["a@google.com", "b@x.org"], {"r1": "a/", "r2": "a/b/c/"}), (7, [], {})]}})

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

    def test_person_doc(self):
        # [project, subject, owner, closed_at, insertions] per CL; 6 has no reviewer threads, 9 isn't
        # in reviews.sqlite.
        info = {6: ("chromium/src", "Quiet", 1, "2026-02-01 00:00:00", 4),
                7: ("chromium/src", None, 1, "2026-07-02 10:00:00", 50),
                8: ("chromium/src", "Earlier", 1, "2026-07-01 09:00:00", None)}
        th = lambda root, who: dict(id=root, path="a.cc", line=1, ps=1, addressed=True, resolved=True,
                                    comments=[[who, "2026-07-01T00:00Z", "x"], [1, "2026-07-01T01:00Z", "Done"]])
        per_cl = {6: [], 7: [th("r7", 2), th("r7b", 3)], 8: [th("r8", 3)]}
        accounts = {1: ("Own Er", False, "o@x.org"), 2: ("Rev", False, "rev@google.com")}
        ident = {1: "o@x.org", 2: "rev@google.com", 3: "other@x.org"}
        cls = [(7, ["rev@google.com", "b@x.org"], {"r7": "ui/"}), (8, [], {"r8": "base/"}), (9, [], {})]
        doc, aids = RT.person_doc(cls, info, per_cl, accounts, ident, {"rev@google.com"}, "2026H2")
        self.assertEqual(aids, [1, 3, 2])
        self.assertEqual({k: doc[k] for k in ("v", "half", "people", "reviewers")}, {
            "v": 5, "half": "2026H2", "people": ["Own Er", "account 3", "Rev"],
            "reviewers": [None, None, "rev@google.com"]})
        # Oldest first.
        self.assertEqual([(c["n"], c["landed"], c["subject"], c["lines"], c["owner"], c["approvers"])
                          for c in doc["cls"]],
                         [(8, "2026-07-01", "Earlier", None, 0, []),
                          (7, "2026-07-02", "", 50, 0, ["b@x.org", "rev@google.com"])])
        self.assertEqual([(t["id"], t["dir"], t["comments"][0][0]) for t in doc["cls"][1]["threads"]],
                         [("r7", "ui/", 2), ("r7b", None, 1)])
        # No reviewer threads in the half-year: no file.
        self.assertEqual(RT.person_doc([(6, [], {}), (9, [], {})], info, per_cl, accounts, ident, set(), "2026H1"), (None, []))

    def test_stale(self):
        accounts = {1: ("Own Er", False, "o@x.org"), 2: ("Rev", False, "rev@google.com")}
        cls = [(8, [], {}), (7, ["rev@google.com"], {"r7": "ui/"})]
        entry = {"cls": [7, 8], "classifier": 3, "fields": RT.FIELDS, "file": True,
                 "people": [[1, "Own Er"], [2, "Rev"], [5, "account 5"]]}
        self.assertFalse(RT.stale(entry, cls, accounts, 3))
        self.assertTrue(RT.stale(None, cls, accounts, 3))
        # Built before each CL listed its approvers: rebuilt.
        self.assertTrue(RT.stale({k: v for k, v in entry.items() if k != "fields"}, cls, accounts, 3))
        # Another classifier, other changes, or a renamed commenter: rebuilt.
        self.assertTrue(RT.stale(entry, cls, accounts, 4))
        self.assertTrue(RT.stale(entry, cls[:1], accounts, 3))
        self.assertTrue(RT.stale(entry, cls, {**accounts, 2: ("Rev Newname", False, "rev@google.com")}, 3))

    def test_prune_removes_old_files_and_folders(self):
        with tempfile.TemporaryDirectory() as d:
            keep = os.path.join(d, "2026H1", "a@x.org.json.gz")
            other = os.path.join(d, "notes.txt")
            # The v4 layout's flat files, a person no longer published and a half-year no longer kept go.
            for p in (keep, other, os.path.join(d, "a@x.org.json.gz"), os.path.join(d, "2026H1", "gone@x.org.json.gz"),
                      os.path.join(d, "2022H1", "a@x.org.json.gz")):
                os.makedirs(os.path.dirname(p), exist_ok=True)
                open(p, "w").close()
            self.assertEqual(RT.prune(d, {keep}), 3)
            self.assertEqual(sorted(os.listdir(d)), ["2026H1", "notes.txt"])
            self.assertEqual(os.listdir(os.path.join(d, "2026H1")), ["a@x.org.json.gz"])

    def test_write_is_stable(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "k.json.gz")
            doc = {"v": 1, "cls": [{"subject": "é"}]}
            self.assertTrue(RT.write(p, doc)[1])
            with open(p, "rb") as f:
                first = f.read()
            self.assertFalse(RT.write(p, doc)[1])
            self.assertEqual(json.loads(gzip.decompress(first)), doc)
            self.assertTrue(RT.write(p, {"v": 1, "cls": []})[1])


class R2Test(unittest.TestCase):
    def test_config_and_local_dirs(self):
        c = r2.config()
        self.assertTrue(c["public_base"].startswith("https://") and c["public_base"].endswith("/"))
        self.assertEqual(sorted(c["prefixes"].values()), ["feedback-people", "review-load-people", "review-threads"])
        self.assertEqual(r2.local_dir("feedback-people", "/d"), "/d/feedback-people")
        self.assertRaises(ValueError, r2.local_dir, "../x", "/d")

    def test_hold_waits_for_another_process(self):
        import subprocess, sys, time
        with tempfile.TemporaryDirectory() as d:
            code = ("import sys,time; from cosh import r2; r2.hold(sys.argv[1]); print('held', flush=True); "
                    "time.sleep(1.5)")
            other = subprocess.Popen([sys.executable, "-c", code, d], stdout=subprocess.PIPE, text=True,
                                     cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            self.assertEqual(other.stdout.readline().strip(), "held")
            t = time.monotonic()
            with mock.patch("sys.stderr"):
                f = r2.hold(d)
            self.assertGreater(time.monotonic() - t, 0.5)
            other.wait()
            r2._held.remove(f)
            f.close()

    def test_prune(self):
        with tempfile.TemporaryDirectory() as d:
            keep = os.path.join(d, "a", "k.json.gz")
            for p in (keep, os.path.join(d, "a", "old.json.gz"), os.path.join(d, "b", "gone.json.gz")):
                os.makedirs(os.path.dirname(p), exist_ok=True)
                open(p, "w").close()
            self.assertEqual(r2.prune(d, {keep}), 2)
            self.assertEqual([os.listdir(d), os.listdir(os.path.join(d, "a"))], [["a"], ["k.json.gz"]])

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

    def test_sync_refuses_an_emptied_folder(self):
        with tempfile.TemporaryDirectory() as d:
            local, data = os.path.join(d, "files"), os.path.join(d, "data")
            os.makedirs(local)
            os.makedirs(data)
            with open(os.path.join(local, "a.json.gz"), "wb") as f:
                f.write(b"A")
            calls = []
            with mock.patch.object(r2, "request", lambda *a, **k: calls.append(a[1:3]) or 200), mock.patch("sys.stderr"):
                r2.sync(local, "p", data_dir=data, cred={}, jobs=1, stamp=1)
                os.remove(os.path.join(local, "a.json.gz"))
                calls.clear()
                with self.assertRaises(SystemExit) as e:
                    r2.sync(local, "p", data_dir=data, cred={}, jobs=1, stamp=5, live=2)
                self.assertIn("has no files", str(e.exception))
                self.assertEqual(calls, [])

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
                r2.sync(local, "p", data_dir=data, cred={}, jobs=1, stamp=1)
                self.assertEqual(sorted((m, k, b) for m, k, b, _ in calls),
                                 [("PUT", "p/H/a.json", b"A"), ("PUT", "p/H/b.json", b"B")])
                self.assertEqual(calls[0][3]["content-encoding"], "gzip")
                self.assertEqual(calls[0][3]["content-type"], "application/json")
                calls.clear()
                r2.sync(local, "p", data_dir=data, cred={}, jobs=1, stamp=1)
                self.assertEqual(calls, [])
                with open(os.path.join(local, "H", "a.json.gz"), "wb") as f:
                    f.write(b"A2")
                os.remove(os.path.join(local, "H", "b.json.gz"))
                r2.sync(local, "p", data_dir=data, cred={}, jobs=1, stamp=2, live=2)
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

    def test_sync_survives_files_changing_under_it(self):
        # A step rewriting the folder during a sync: a file that vanished is left
        # for the next sync, and a rewritten one is recorded as what was sent.
        with tempfile.TemporaryDirectory() as d:
            local, data = os.path.join(d, "files"), os.path.join(d, "data")
            os.makedirs(os.path.join(local, "H"))
            os.makedirs(data)
            for name in ("a.json.gz", "b.json.gz"):
                with open(os.path.join(local, "H", name), "wb") as f:
                    f.write(b"old")
            real_plan = r2.plan

            def plan_then_change(*args):
                out = real_plan(*args)
                os.remove(os.path.join(local, "H", "a.json.gz"))
                with open(os.path.join(local, "H", "b.json.gz"), "wb") as f:
                    f.write(b"new")
                return out
            sent = []
            with mock.patch.object(r2, "plan", plan_then_change), \
                    mock.patch.object(r2, "request", lambda c, m, k, body=b"", headers=None: sent.append((k, body))):
                r2.sync(local, "p", data_dir=data, cred={}, jobs=1)
            self.assertEqual(sent, [("p/H/b.json", b"new")])
            with open(r2.manifest_path(data)) as f:
                m = json.load(f)
            self.assertEqual(m, {"p/H/b.json": {"sha256": hashlib.sha256(b"new").hexdigest(), "bytes": 3,
                                                "seen": m["p/H/b.json"]["seen"]}})

    def test_sync_keeps_what_the_live_site_reads(self):
        # Publish 1 at t=10 has a and b, and is deployed. Publish 2 at t=20
        # drops b: the live site (publish 1) still reads it, so it stays. Once
        # publish 2 is deployed, publish 3 deletes it.
        with tempfile.TemporaryDirectory() as d:
            local, data = os.path.join(d, "files"), os.path.join(d, "data")
            os.makedirs(local)
            os.makedirs(data)
            for name in ("a.json", "b.json"):
                with open(os.path.join(local, name), "w") as f:
                    f.write(name)
            calls = []
            with mock.patch.object(r2, "request", lambda c, m, k, body=b"", headers=None: calls.append((m, k))):
                self.assertEqual(r2.sync(local, "p", data_dir=data, cred={}, jobs=1, stamp=10, live=None), 2)
                os.remove(os.path.join(local, "b.json"))
                calls.clear()
                self.assertEqual(r2.sync(local, "p", data_dir=data, cred={}, jobs=1, stamp=20, live=10), 2)
                self.assertEqual(calls, [])
                with open(r2.manifest_path(data)) as f:
                    m = json.load(f)
                self.assertEqual((m["p/a.json"]["seen"], m["p/b.json"]["seen"]), (20, 10))
                # Not deployed yet: the live site still reads publish 1.
                r2.sync(local, "p", data_dir=data, cred={}, jobs=1, stamp=30, live=10)
                self.assertEqual(calls, [])
                self.assertEqual(r2.sync(local, "p", data_dir=data, cred={}, jobs=1, stamp=40, live=30), 1)
                self.assertEqual(calls, [("DELETE", "p/b.json")])
                # A retired prefix (local None) loses everything the live site doesn't read.
                calls.clear()
                self.assertEqual(r2.sync(None, "p", data_dir=data, cred={}, jobs=1, stamp=50, live=40), 1)
                self.assertEqual(calls, [])
                self.assertEqual(r2.sync(None, "p", data_dir=data, cred={}, jobs=1, stamp=60, live=50), 0)
                self.assertEqual(calls, [("DELETE", "p/a.json")])

    def test_a_retired_prefix_leaves_a_prefix_inside_it_alone(self):
        manifest = {"a/t/x.json": {"sha256": "1", "seen": 1}, "a/t/v2/x.json": {"sha256": "2", "seen": 1}}
        self.assertEqual(r2.nested_in("a/t", ["a/t", "a/t/v2", "a/tv"]), ["a/t/v2"])
        ups, dels, kept, present = r2.plan(None, "a/t", manifest, live=5, nested=["a/t/v2"])
        self.assertEqual((ups, dels, kept, present), ([], ["a/t/x.json"], [], []))
        self.assertTrue(r2.owns("a/t/v2", "a/t/v2/x.json"))
        self.assertFalse(r2.owns("a/t", "a/t/v2/x.json", ["a/t/v2"]))

    def test_live_since_is_the_newest_publish_before_the_push(self):
        pubs = [dict(time=10, prefixes=["p", "q"]), dict(time=20, prefixes=["q"]), dict(time=30, prefixes=["p"])]
        self.assertEqual(r2.live_since("p", pubs, 25), 10)
        self.assertEqual(r2.live_since("q", pubs, 25), 20)
        self.assertEqual(r2.live_since("p", pubs, 30), 30)
        self.assertIsNone(r2.live_since("p", pubs, 5))
        self.assertIsNone(r2.live_since("p", pubs, None))
        self.assertIsNone(r2.live_since("r", pubs, 99))

    def test_last_push_reads_origin_mains_reflog(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(r2.last_push(d))
            env = dict(os.environ, GIT_COMMITTER_DATE="1700000000 +0000", GIT_AUTHOR_DATE="1700000000 +0000")
            run = lambda *a: subprocess.run(["git", "-C", d, *a], check=True, capture_output=True, env=env)  # noqa: E731
            run("init", "-q")
            run("-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "--allow-empty", "-m", "x")
            run("update-ref", "--create-reflog", "-m", "update by push", "refs/remotes/origin/main", "HEAD")
            self.assertEqual(r2.last_push(d), 1700000000)


if __name__ == "__main__":
    unittest.main()
