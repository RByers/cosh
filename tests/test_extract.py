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
        # `_merged_at` (test only): Gerrit's index merge time for a CL whose
        # listing has no `submitted`, as seen for CL 5039071.
        branch = re.search(r"branch:(\w+)", q).group(1)
        hits = [c for c in self.changes if c["status"] == want and c["branch"] == branch
                and lo <= ((field == "submitted" and c.get("_merged_at")) or c.get(field, ""))[:19] <= hi]
        hits = sorted(hits, key=lambda c: c["updated"], reverse=True)
        out = [{k: v for k, v in c.items() if k != "_merged_at"} for c in hits[:self.page]]
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


class ExtractWeekTest(unittest.TestCase):
    def test_merged_cl_without_submitted_stays_in_its_listed_week(self):
        changes = [
            cl(1, "MERGED", "2023-12-05 00:00:00", submitted="2023-12-04 10:00:00"),
            # Listed by Gerrit's merge time in W49, but no `submitted`, and
            # `updated` is in W50 (CL 5039071).
            dict(cl(2, "MERGED", "2023-12-15 04:26:05"), _merged_at="2023-12-04 03:00:00"),
            cl(3, "MERGED", "2023-12-12 00:00:00", submitted="2023-12-11 10:00:00"),  # W50
        ]
        fake = FakeGerrit(changes)
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(extract, "GerritClient", lambda host, min_interval: fake), \
                mock.patch.object(extract, "fetch_notedb", lambda *a, **k: []):
            extract.extract_week(H, P, "2023-W49", data_dir=d)
            raw = store.open_raw(d)
            listed = sorted(n for (n,) in raw.execute(
                "SELECT change_number FROM week_changes WHERE iso_week='2023-W49'"))
            raw.close()
        self.assertEqual(listed, [1, 2])

    def test_weeks_before_the_rename_list_master_too(self):
        changes = [
            dict(cl(1, "MERGED", "2020-03-03 00:00:00", submitted="2020-03-03 00:00:00"),
                 branch="master"),
            cl(2, "MERGED", "2020-03-04 00:00:00", submitted="2020-03-04 00:00:00"),
            dict(cl(3, "ABANDONED", "2020-03-05 00:00:00"), branch="master"),
            dict(cl(4, "MERGED", "2020-03-05 00:00:00", submitted="2020-03-05 00:00:00"),
                 branch="refs/branch-heads/4044"),
        ]
        fake = FakeGerrit(changes)
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(extract, "GerritClient", lambda host, min_interval: fake), \
                mock.patch.object(extract, "fetch_notedb", lambda *a, **k: []):
            extract.extract_week(H, P, "2020-W10", data_dir=d)
            raw = store.open_raw(d)
            listed = sorted(n for (n,) in raw.execute(
                "SELECT change_number FROM week_changes WHERE iso_week='2020-W10'"))
            raw.close()
        self.assertEqual(listed, [1, 2, 3])
        self.assertEqual(sum("branch:master" in q for q in fake.queries),
                         sum("branch:main" in q for q in fake.queries))
        # After the rename, `main` only.
        self.assertEqual(extract.branches_for(datetime(2021, 6, 1, tzinfo=timezone.utc)), ("main",))

    def test_closed_ts_falls_back_to_updated(self):
        self.assertEqual(extract.closed_ts(cl(2, "MERGED", "2023-12-15 04:26:05")), "2023-12-15 04:26:05")
        self.assertEqual(extract.closed_ts(cl(1, "MERGED", "x", submitted="2023-12-04 10:00:00")),
                         "2023-12-04 10:00:00")


class NoteDbRepoTest(unittest.TestCase):
    def test_init_repo_applies_config_and_maintain_is_lossless(self):
        from cosh import notedb
        with tempfile.TemporaryDirectory() as d:
            repo = notedb.init_repo(f"{d}/x.git")
            for k, v in notedb.REPO_CONFIG.items():
                self.assertEqual(notedb.git(repo, "config", k).stdout.strip(), v)
            # A local "meta ref" with one commit; maintain must keep it.
            tree = notedb.git(repo, "mktree", input="").stdout.strip()
            c = notedb.git(repo, "commit-tree", tree, "-m", "x").stdout.strip()
            notedb.git(repo, "update-ref", "refs/meta/42", c)
            notedb.maintain(repo)
            self.assertEqual(notedb.fetched_numbers(repo), {42})
            self.assertEqual(notedb.git(repo, "rev-parse", "refs/meta/42").stdout.strip(), c)

    def test_batched_read_matches_tree_order_with_fanout_and_missing_refs(self):
        from cosh import notedb
        with tempfile.TemporaryDirectory() as d:
            repo = notedb.init_repo(f"{d}/x.git")

            def blob(*uuids, path="a.cc"):
                doc = {"comments": [{"key": {"uuid": u, "filename": path, "patchSetId": 1},
                                     "author": {"id": 7}, "writtenOn": "2026-10-22T00:15:10Z",
                                     "message": u} for u in uuids]}
                return notedb.git(repo, "hash-object", "-w", "--stdin",
                                  input=json.dumps(doc)).stdout.strip()

            def tree(entries):   # [(name, "blob"|"tree", sha)]
                spec = "".join(f"{'040000' if t == 'tree' else '100644'} {t} {s}\t{n}\n"
                               for n, t, s in entries)
                return notedb.git(repo, "mktree", input=spec).stdout.strip()

            def ref(n, t):
                c = notedb.git(repo, "commit-tree", t, "-m", "x").stdout.strip()
                notedb.git(repo, "update-ref", f"refs/meta/{n}", c)

            ref(1, tree([("aa", "blob", blob("c1", "c2")), ("bb", "blob", blob("c3", path="b.cc"))]))
            # Notes fanout: a subtree between two blobs; also a non-JSON blob.
            junk = notedb.git(repo, "hash-object", "-w", "--stdin", input="not json").stdout.strip()
            ref(2, tree([("00", "blob", blob("f1")),
                         ("ab", "tree", tree([("cd", "blob", blob("f2")), ("ef", "blob", junk)])),
                         ("zz", "blob", blob("f3"))]))
            ref(3, tree([]))

            got = notedb.read_comments_many(repo, [1, 2, 3, 99])
            self.assertEqual(set(got), {1, 2, 3})
            ids = lambda cs: {p: [c["id"] for c in v] for p, v in cs.items()}
            self.assertEqual(ids(got[1]), {"a.cc": ["c1", "c2"], "b.cc": ["c3"]})
            self.assertEqual(ids(got[2]), {"a.cc": ["f1", "f2", "f3"]})   # ls-tree -r order
            self.assertEqual(got[3], {})
            self.assertEqual(got[1]["a.cc"][0], {"author": {"_account_id": 7}, "id": "c1", "patch_set": 1,
                                                 "updated": "2026-10-22 00:15:10.000000000",
                                                 "message": "c1"})
            self.assertEqual(notedb.read_comments(repo, 2), got[2])
            self.assertIsNone(notedb.read_comments(repo, 99))
            self.assertEqual(notedb.read_comments_many(repo, []), {})


class StaleRefsTest(unittest.TestCase):
    def test_missing_or_older_than_listing(self):
        t = lambda s: datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
        listed = {n: ("k", {"updated": "2026-10-01 00:00:00.000000000"}) for n in (1, 2, 3)}
        tips = {1: t("2026-10-01 00:00:00"), 2: t("2026-09-30 23:59:59")}
        self.assertEqual(extract.stale_refs([1, 2, 3], listed, tips), [2, 3])


class ContactTest(unittest.TestCase):
    """The contact e-mail comes from COSH_CONTACT or a gitignored settings.json."""

    def setUp(self):
        import os
        from cosh import contact
        self.contact = contact
        self.dirs = [tempfile.mkdtemp(), tempfile.mkdtemp()]   # data dir, main checkout's
        env = {k: v for k, v in os.environ.items() if k != "COSH_CONTACT"}
        for p in (mock.patch.dict(os.environ, env, clear=True),
                  mock.patch.object(store, "DATA_DIR", self.dirs[0]),
                  mock.patch.object(contact, "_main_checkout_data_dir", lambda: self.dirs[1])):
            p.start()
            self.addCleanup(p.stop)
        contact.contact.cache_clear()
        self.addCleanup(contact.contact.cache_clear)

    def write(self, i, settings):
        with open(f"{self.dirs[i]}/settings.json", "w") as f:
            json.dump(settings, f)

    def test_missing_fails_naming_the_file(self):
        with self.assertRaises(self.contact.ContactMissing) as cm:
            self.contact.http_headers()
        self.assertIn(f"{self.dirs[0]}/settings.json", str(cm.exception))
        self.assertIn("e-mail", str(cm.exception))

    def test_settings_in_data_dir(self):
        self.write(0, {"contact_email": "a@example.com"})
        self.write(1, {"contact_email": "b@example.com"})
        self.assertEqual(self.contact.http_headers()["From"], "a@example.com")
        self.assertIn("contact: a@example.com", self.contact.git_env()["GIT_USER_AGENT"])
        self.assertEqual(self.contact.git_config(), ["-c", "http.extraHeader=From: a@example.com"])

    def test_worktree_falls_back_to_main_checkout(self):
        self.write(1, {"contact_email": "b@example.com"})
        self.assertEqual(self.contact.contact(), "b@example.com")

    def test_env_overrides(self):
        import os
        self.write(0, {"contact_email": "a@example.com"})
        os.environ["COSH_CONTACT"] = "env@example.com"
        self.assertEqual(self.contact.contact(), "env@example.com")

    def test_network_commands_fail_fast_offline_ones_dont_check(self):
        import io
        from contextlib import redirect_stderr
        from cosh.__main__ import main
        err = io.StringIO()
        with redirect_stderr(err), self.assertRaises(SystemExit) as cm:
            main(["extract", "--week", "2026-W44"])
        self.assertEqual(cm.exception.code, 2)
        self.assertIn("contact e-mail", err.getvalue())
        with mock.patch("cosh.backfill.backfill") as bf:
            main(["backfill", "--weeks", "1", "--newest", "2026-W44"])   # plan only: no check
        bf.assert_called_once()

    def test_local_git_needs_no_contact(self):
        from cosh import notedb
        with tempfile.TemporaryDirectory() as d:
            notedb.init_repo(f"{d}/x.git")          # raises if it wanted the contact


if __name__ == "__main__":
    unittest.main()
