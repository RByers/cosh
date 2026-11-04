import hashlib
import json
import os
import tempfile
import unittest

from cosh.derive import account_name, derive, derive_change, mark_emailless_bots
from cosh import store
from cosh.orgs import OrgResolver, load_affiliations, parse_json5
from cosh.paths import ROOT_FILES, UNPLACED, anchor, parse_rules, place
from cosh.summarize import summarize

H = "chromium-review.googlesource.com"
OWNER = {"_account_id": 1, "email": "author@chromium.org"}
REV = {"_account_id": 2, "email": "rev@microsoft.com"}
BOT = {"_account_id": 3, "email": "chromium-scoped@luci-project-accounts.iam.gserviceaccount.com",
       "tags": ["SERVICE_USER"]}
CC = {"_account_id": 4, "email": "cc@google.com"}

CHANGE = {
    "_number": 100, "status": "MERGED", "project": "chromium/src", "branch": "main", "owner": OWNER,
    "created": "2026-10-10 10:00:00.000000000", "updated": "2026-10-28 00:00:00.000000000",
    "submitted": "2026-10-27 12:00:00.000000000", "total_comment_count": 5,
    "labels": {"Code-Review": {"all": [dict(REV, value=1, date="2026-10-26 09:00:00.000000000"),
                                       dict(BOT, value=0), dict(OWNER, value=0)]}},
}
COMMENTS = {
    "/PATCHSET_LEVEL": [
        {"id": "c1", "author": REV, "message": "lgtm", "updated": "2026-10-26 00:00:00.000000000"},
        {"id": "c2", "author": OWNER, "message": "thanks", "updated": "2026-10-26 01:00:00.000000000"},
    ],
    "content/a.cc": [
        # written in W43 on a CL that closed in W44
        {"id": "c3", "author": REV, "message": "> quoted\nnit: rename", "updated": "2026-10-20 00:00:00.000000000"},
        {"id": "c4", "author": REV, "message": "AI says x", "is_ai": True, "updated": "2026-10-26 12:00:00.000000000"},
        {"id": "c5", "author": CC, "message": "late", "updated": "2026-10-28 00:00:00.000000000"},
    ],
}


class DeriveChangeTest(unittest.TestCase):
    def test_comment_rows_keyed_by_time_written(self):
        _, ch, rows = derive_change(CHANGE, COMMENTS)
        got = {r["comment_id"]: (r["account_id"], r["iso_week"], r["path"], r["is_ai"], r["after_close"])
               for r in rows}
        self.assertEqual(got, {
            "c1": (2, "2026-W44", "/PATCHSET_LEVEL", 0, 0),
            "c3": (2, "2026-W43", "content/a.cc", 0, 0),
            "c4": (2, "2026-W44", "content/a.cc", 1, 0),
            "c5": (4, "2026-W44", "content/a.cc", 0, 1),   # after the CL merged
        })                                                 # owner's c2 excluded
        self.assertEqual((ch["close_week"], ch["closed_at"], ch["is_bot_owned"], ch["anchor_path"]),
                         ("2026-W44", "2026-10-27 12:00:00", 0, "content/a.cc"))

    def test_anchor_counts_owner_inline_comments(self):
        comments = {"/PATCHSET_LEVEL": [{"id": "p", "author": REV, "updated": "2026-10-26 00:00:00"}],
                    "base/x.cc": [{"id": "x", "author": REV, "updated": "2026-10-26 00:00:00"}],
                    "ui/y.cc": [{"id": f"y{i}", "author": OWNER, "updated": "2026-10-26 00:00:00"}
                                for i in range(2)]}
        _, ch, rows = derive_change(CHANGE, comments)
        self.assertEqual(ch["anchor_path"], "ui/y.cc")   # the owner's replies count here
        self.assertEqual(len(rows), 2)                   # ... but not as review comments

    def test_no_rows_when_comments_not_fetched(self):
        _, ch, rows = derive_change(CHANGE, None)
        self.assertEqual((rows, ch["anchor_path"]), ([], None))

    def test_bot_owned_cl_has_change_row_only(self):
        _, ch, rows = derive_change(dict(CHANGE, owner=BOT), COMMENTS)
        self.assertEqual((ch["is_bot_owned"], rows, ch["anchor_path"]), (1, [], None))

    def test_open_cl_has_no_close(self):
        op = dict(CHANGE, status="NEW")
        del op["submitted"]
        _, ch, rows = derive_change(op, COMMENTS)
        self.assertEqual((ch["status"], ch["closed_at"], ch["close_week"]), ("NEW", None, None))
        self.assertFalse(any(r["after_close"] for r in rows))

    def test_abandoned_cl_closes_at_updated(self):
        ab = dict(CHANGE, status="ABANDONED", updated="2026-10-27 12:00:00.000000000")
        del ab["submitted"]
        _, ch, rows = derive_change(ab, COMMENTS)
        self.assertEqual((ch["submitted_at"], ch["close_week"]), (None, "2026-W44"))
        self.assertEqual(sum(r["after_close"] for r in rows), 1)

    def test_account_details_from_anywhere_in_listing(self):
        cl = dict(CHANGE, attention_set={"9": {"account": {"_account_id": 9, "email": "x@igalia.com"}}},
                  removed_from_attention_set={"7": {"account": {"_account_id": 7, "tags": ["SERVICE_USER"],
                                                                "email": "ai@system.gserviceaccount.com"}}})
        comments = {"a.cc": [{"author": {"_account_id": 9}, "message": "hi", "updated": "2026-10-25 00:00:00"},
                             {"author": {"_account_id": 7}, "message": "bot", "updated": "2026-10-25 00:00:00"}]}
        accounts, _, rows = derive_change(cl, comments)
        self.assertEqual(accounts[9]["email"], "x@igalia.com")
        self.assertIn("SERVICE_USER", accounts[7]["tags"])
        self.assertEqual(len({r["comment_id"] for r in rows}), 2)   # ids synthesized when missing

    def test_org_resolver(self):
        r = OrgResolver({"cav@chromium.org": [("2026-01-12", "microsoft.com"),
                                              ("2022-05-03", "intel.com")]})
        self.assertEqual(r("cav@chromium.org", "2026-10-27 12:00:00"), "microsoft.com")
        self.assertEqual(r("Cav@chromium.org", "2023-01-01"), "intel.com")
        self.assertEqual(r("cav@chromium.org", "2020-01-01"), "google.com")   # before first start
        self.assertEqual(r("someone@chromium.org", "2026-01-01"), "google.com")
        self.assertEqual(r("x@igalia.com"), "igalia.com")
        self.assertEqual(r(None), "(no email)")

    def test_org_resolver_maps_fb_com_to_meta(self):
        r = OrgResolver({"old@chromium.org": [("2020-01-01", "fb.com")]})
        self.assertEqual(r("someone@fb.com", "2022-01-01"), "meta.com")
        self.assertEqual(r("someone@meta.com", "2026-01-01"), "meta.com")
        self.assertEqual(r("old@chromium.org", "2021-01-01"), "meta.com")   # via affiliations

    def test_json5(self):
        self.assertEqual(parse_json5('/* c */ {"a@b.org": { k: [ {start: "x",}, ], }, // t\n}'),
                         {"a@b.org": {"k": [{"start": "x"}]}})

    def test_real_affiliations_file_parses(self):
        aff = load_affiliations()
        self.assertGreater(len(aff), 20)
        self.assertTrue(all("@" in e for e in aff))


class AccountTest(unittest.TestCase):
    def test_name_falls_back_to_display_name(self):
        self.assertEqual(account_name({"name": "A B", "display_name": "AB"}), "A B")
        self.assertEqual(account_name({"display_name": "Jetski (agent)"}), "Jetski (agent)")
        self.assertIsNone(account_name({"_account_id": 7}))
        self.assertEqual(account_name({"_account_id": 7, "deleted": True}), "Deleted User")
        self.assertEqual(account_name({"name": "A B", "deleted": True}), "A B")

    def test_real_name_wins_over_deleted_placeholder(self):
        from cosh.derive import NAME_UPSERT
        with tempfile.TemporaryDirectory() as d:
            db = store.open_derived(d)
            up = ("INSERT INTO accounts VALUES ('h',1,NULL,?,0) ON CONFLICT(host, account_id) "
                  "DO UPDATE SET " + NAME_UPSERT)
            name = lambda: db.execute("SELECT name FROM accounts").fetchone()[0]
            db.execute(up, ("Deleted User",))
            self.assertEqual(name(), "Deleted User")
            db.execute(up, ("A B",))
            self.assertEqual(name(), "A B")
            db.execute(up, ("Deleted User",))
            db.execute(up, (None,))
            self.assertEqual(name(), "A B")
            db.close()

    def test_accounts_without_email_are_bots(self):
        with tempfile.TemporaryDirectory() as d:
            db = store.open_derived(d)
            with db:
                db.execute("INSERT INTO accounts VALUES (?,1,'a@igalia.com','A',0)", (H,))
                db.execute("INSERT INTO accounts VALUES (?,2,NULL,'Jetski (agent)',0)", (H,))
                db.execute("INSERT INTO accounts VALUES (?,3,NULL,NULL,0)", (H,))
                self.assertEqual(mark_emailless_bots(db), 2)
            self.assertEqual(db.execute("SELECT account_id, is_bot FROM accounts ORDER BY 1").fetchall(),
                             [(1, 0), (2, 1), (3, 1)])
            db.close()


def put_window(raw, key, changes):
    store.put_response(raw, H, "list_window", key, "u", 200, json.dumps(changes))


class DeriveEndToEndTest(unittest.TestCase):
    """raw.sqlite with a weekly listing and an open-CL snapshot -> derived.sqlite."""

    def build(self, d):
        raw = store.open_raw(d)
        with raw:
            # CL 100 closed in W44 (listed weekly). CL 200 was open in the
            # snapshot and later merged: its weekly listing is the newer one.
            put_window(raw, "wk", [CHANGE, dict(CHANGE, _number=200, submitted="2026-10-29 00:00:00",
                                                updated="2026-10-29 00:00:00")])
            put_window(raw, "snap", [dict(CHANGE, _number=200, status="NEW", submitted=None,
                                          updated="2026-10-21 00:00:00"),
                                     dict(CHANGE, _number=300, status="NEW", submitted=None,
                                          updated="2026-10-30 00:00:00")])
            raw.executemany("INSERT INTO week_changes VALUES (?,?,?,?,?)",
                            [(H, "chromium/src", "2026-W44", 100, "wk"),
                             (H, "chromium/src", "2026-W44", 200, "wk")])
            raw.execute("INSERT INTO open_listings(host, project, listed_at, since, closed_since, "
                        "fetched_at) VALUES (?,?,?,?,?,?)",
                        (H, "chromium/src", "2026-10-31T00:00:00Z", "x", "y", "2026-10-31T01:00:00Z"))
            raw.executemany("INSERT INTO open_changes VALUES (?,?,?,?,?)",
                            [(H, "chromium/src", "2026-10-31T00:00:00Z", 200, "snap"),
                             (H, "chromium/src", "2026-10-31T00:00:00Z", 300, "snap")])
            raw.executemany("INSERT INTO week_progress(host, project, iso_week, fetched_at) VALUES (?,?,?,?)",
                            [(H, "chromium/src", "2026-W43", "t"), (H, "chromium/src", "2026-W44", "t")])
            for n in (100, 200, 300):
                store.put_response(raw, H, "comments", str(n), "u", 200, json.dumps(COMMENTS))
        raw.close()

    def test_derive_and_summarize(self):
        with tempfile.TemporaryDirectory() as d:
            self.build(d)
            with open(os.path.join(d, "raw.sqlite"), "rb") as fh:
                before = hashlib.sha256(fh.read()).hexdigest()
            derive(data_dir=d)
            with open(os.path.join(d, "raw.sqlite"), "rb") as fh:
                self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), before)   # read-only
            db = store.open_derived(d)
            self.assertEqual(db.execute("SELECT change_number, status, close_week FROM changes "
                                        "ORDER BY 1").fetchall(),
                             [(100, "MERGED", "2026-W44"), (200, "MERGED", "2026-W44"),
                              (300, "NEW", None)])
            self.assertEqual(db.execute("SELECT iso_week, count(*) FROM comments GROUP BY 1").fetchall(),
                             [("2026-W43", 3), ("2026-W44", 9)])
            self.assertEqual({r[0] for r in db.execute("SELECT anchor_path FROM changes")}, {"content/a.cc"})
            db.close()

            rows = summarize(data_dir=d, out_dir=os.path.join(d, "s"))
        got = {(r["iso_week"], r["org"]): (r["comments"], r["review_chars"], r["ai_comments"],
                                           r["post_merge_comments"], r["reviewers"], r["reviewed_cls"],
                                           r["share"]) for r in rows}
        n = len("nit: rename")
        self.assertEqual(got, {
            # One W43 comment per CL, on 3 CLs, two of which closed only in W44
            # and one that is still open. No CL closed in W43.
            ("2026-W43", "microsoft.com"): (3, 3 * n, 0, 0, 1, 0, 1.0),
            # W44: lgtm x3 (placed on each CL's anchor, content/a.cc) and AI x3,
            # both in the metric. c5 (10-28) x3 all count; it is post-merge only
            # on CL 100 (merged 10-27); CL 200 merged 10-29 and CL 300 is open.
            # REV's vote adds nothing. Reviewed CLs (by close week): 100 and 200.
            ("2026-W44", "microsoft.com"): (6, 12 + 3 * len("AI says x"), 3, 0, 1, 2, 0.6667),
            ("2026-W44", "google.com"): (3, 12, 0, 1, 1, 2, 0.3333),
        })

    def test_summary_drops_unfetched_weeks(self):
        with tempfile.TemporaryDirectory() as d:
            self.build(d)
            raw = store.open_raw(d)
            with raw:
                raw.execute("DELETE FROM week_progress WHERE iso_week = '2026-W43'")
            raw.close()
            derive(data_dir=d)
            rows = summarize(data_dir=d, out_dir=os.path.join(d, "s"))
        self.assertEqual({r["iso_week"] for r in rows}, {"2026-W44"})

    def test_incremental_week_derive_matches_full(self):
        with tempfile.TemporaryDirectory() as d:
            self.build(d)
            full, part = os.path.join(d, "full.sqlite"), os.path.join(d, "part.sqlite")
            derive(data_dir=d, out_path=full)
            derive(data_dir=d, weeks=["2026-W44"], out_path=part)
            q = "SELECT * FROM comments ORDER BY 1, 2, 3"
            a, b = store.open_derived(path=full), store.open_derived(path=part)
            # The week derive covers CLs 100 and 200 (200 via its newest listing).
            self.assertEqual([r for r in a.execute(q) if r[1] != 300], b.execute(q).fetchall())
            a.close()
            b.close()


def summary_db(d, accounts, comments, close_week="2026-W44", cls=None):
    """A derived.sqlite with merged CLs (default: CL 100, anchored on
    content/a.cc) and the given comments [(account, n_human, n_ai,
    n_post_merge)] or [(account, n_human, n_ai, n_post_merge, cl, path)],
    all written in W44 and 10 chars long. cls: {cl: anchor_path}."""
    db = store.open_derived(d)
    with db:
        for aid, email in accounts:
            db.execute("INSERT INTO accounts VALUES (?,?,?,NULL,0)", (H, aid, email))
        for cl, anchor_path in (cls or {100: "content/a.cc"}).items():
            db.execute("""INSERT INTO changes(host, change_number, project, branch, owner_account, status,
                          created_at, updated_at, closed_at, close_week, anchor_path)
                          VALUES (?,?,'chromium/src','main',1,'MERGED','2026-10-26 00:00:00',
                          '2026-10-27 12:00:00','2026-10-27 12:00:00',?,?)""",
                       (H, cl, close_week, anchor_path))
        i = 0
        for aid, n, ai, pm, *where in comments:
            cl, path = where or (100, "content/a.cc")
            for kind in [(0, 0)] * n + [(1, 0)] * ai + [(0, 1)] * pm:
                i += 1
                db.execute("INSERT INTO comments VALUES (?,?,?,?,'2026-10-27 00:00:00','2026-W44',?,10,?,?)",
                           (H, cl, f"c{i}", aid, path) + kind)
    db.close()


class PathScopeTest(unittest.TestCase):
    SCOPE = parse_rules("# c\nexclude chrome/\nexclude ios/\ninclude chrome/browser/web_applications/\n"
                        "area third_party/blink/\n")

    def test_longest_prefix_wins_and_default_is_included(self):
        s = self.SCOPE
        self.assertFalse(s.includes("chrome/browser/ui/a.cc"))
        self.assertTrue(s.includes("chrome/browser/web_applications/a.cc"))
        self.assertTrue(s.includes("chromecast/a.cc"))          # a prefix is a directory
        self.assertTrue(s.includes("content/a.cc"))
        self.assertTrue(s.includes("DEPS"))
        self.assertFalse(s.includes(None))                       # unplaced

    def test_areas(self):
        s = self.SCOPE
        self.assertEqual(s.area("third_party/blink/renderer/core/a.cc"), "third_party/blink/")
        self.assertEqual(s.area("third_party/skia/a.cc"), "third_party/")
        # Re-included directories stay inside their parent's area.
        self.assertEqual(s.area("chrome/browser/web_applications/x/a.cc"), "chrome/")
        self.assertEqual(s.area("chrome/browser/ui/a.cc"), "chrome/")
        self.assertEqual(s.area("DEPS"), ROOT_FILES)
        self.assertEqual(s.area(None), UNPLACED)

    def test_anchor_and_place(self):
        self.assertEqual(anchor({"/PATCHSET_LEVEL": 9, "b.cc": 2, "a.cc": 2, "c.cc": 1}), "a.cc")
        self.assertIsNone(anchor({"/PATCHSET_LEVEL": 3, "/COMMIT_MSG": 1}))
        self.assertEqual(place("/PATCHSET_LEVEL", "a.cc"), "a.cc")
        self.assertEqual(place("/COMMIT_MSG", None), None)
        self.assertEqual(place("x/b.cc", "a.cc"), "x/b.cc")

    def test_directory_and_parent(self):
        from cosh.paths import directory, parent_dir
        self.assertEqual(directory("a/b/c.cc"), "a/b/")
        self.assertEqual(directory("DEPS"), ROOT_FILES)
        self.assertEqual(directory(None), UNPLACED)
        self.assertEqual(parent_dir("a/b/c/"), "a/b/")
        self.assertIsNone(parent_dir("a/"))

    def test_dir_tree_keeps_the_largest_and_rolls_the_rest_up(self):
        from cosh.paths import dir_tree
        totals = {"a/b/c/": 5, "a/b/d/": 1, "a/x/": 3, "a/b/web/": 0, UNPLACED: 2}
        nodes, bucket = dir_tree(totals, parse_rules("exclude a/\ninclude a/b/web/\n"), limit=1)
        # a/b/c/ is kept with its ancestor a/b/, and every rule directory is kept
        # (a/b/web/ inside a/b/, not a root); the rest roll up into their nearest
        # kept ancestor.
        self.assertEqual(nodes, [(UNPLACED, None), ("a/", None), ("a/b/", "a/"), ("a/b/c/", "a/b/"),
                                 ("a/b/web/", "a/b/")])
        self.assertEqual([bucket(d) for d in ["a/b/c/", "a/b/d/", "a/x/", "a/b/web/x/", UNPLACED]],
                         ["a/b/c/", "a/b/", "a/", "a/b/web/", UNPLACED])

    def test_bad_rule_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_rules("exclude chrome")                         # not a directory
        with self.assertRaises(ValueError):
            parse_rules("skip chrome/")

    def test_real_config_parses(self):
        from cosh.paths import load_scope
        s = load_scope()
        self.assertFalse(s.includes("chrome/browser/ui/a.cc"))
        self.assertFalse(s.includes("ios/chrome/a.mm"))
        self.assertFalse(s.includes("android_webview/a.cc"))
        self.assertFalse(s.includes("ash/shell.cc"))
        self.assertFalse(s.includes("chromeos/ash/components/a.cc"))
        self.assertTrue(s.includes("chrome/browser/webnn/a.cc"))
        self.assertTrue(s.includes("chrome/browser/web_applications/a.cc"))
        self.assertTrue(s.includes("third_party/blink/renderer/core/a.cc"))
        self.assertFalse(s.includes("components/autofill/core/a.cc"))
        self.assertTrue(s.includes("components/viz/service/display/a.cc"))
        self.assertTrue(s.includes("components/services/storage/dom_storage/a.cc"))
        self.assertFalse(s.includes("components/services/print_compositor/a.cc"))
        self.assertTrue(s.includes("content/browser/a.cc"))


class SummarizeTest(unittest.TestCase):
    def test_post_merge_comments_counted_and_reported(self):
        with tempfile.TemporaryDirectory() as d:
            summary_db(d, [(1, "owner@igalia.com")] + [(a, f"r{a}@igalia.com") for a in range(2, 7)],
                       [(2, 3, 1, 2), (3, 0, 0, 1), (4, 1, 0, 0), (5, 1, 0, 0), (6, 1, 0, 0)])
            out = os.path.join(d, "summaries")
            rows = summarize(data_dir=d, out_dir=out)
            with open(os.path.join(out, "reviewer_weekly.json")) as fh:
                data = json.load(fh)
        # Post-merge and AI comments are in the metric, and also reported as subsets.
        self.assertEqual([(r["org"], r["comments"], r["review_chars"], r["ai_comments"],
                           r["post_merge_comments"], r["reviewers"], r["reviewed_cls"], r["share"])
                          for r in rows],
                         [("igalia.com", 10, 100, 1, 3, 5, 1, 1.0)])
        # Every reviewer (valid JSON despite the hand-rolled layout), AI included;
        # account 3 (post-merge only) is credited like any other reviewer.
        self.assertEqual(data["meta"]["columns"], ["account_id", "org", "comments", "cls", "chars"])
        self.assertEqual(data["orgs"], ["igalia.com"])
        self.assertEqual(data["accounts"], {str(a): f"r{a}" for a in range(2, 7)})
        self.assertEqual(data["emails"], {str(a): f"r{a}@igalia.com" for a in range(2, 7)})
        self.assertEqual(data["weeks"]["2026-W44"],
                         [[2, 0, 6, 1, 60], [3, 0, 1, 1, 10], [4, 0, 1, 1, 10], [5, 0, 1, 1, 10],
                          [6, 0, 1, 1, 10]])

    def test_path_scope(self):
        # CL 100 is anchored in chrome/ (excluded), CL 101 in blink, CL 102 has
        # no inline comments, so its patchset-level comments can't be placed.
        accounts = [(1, "owner@igalia.com"), (2, "a@microsoft.com"), (3, "b@google.com")]
        with tempfile.TemporaryDirectory() as d:
            summary_db(d, accounts, [
                (2, 1, 0, 0, 100, "chrome/browser/web_applications/x.cc"),   # included again
                (2, 2, 0, 0, 100, "/PATCHSET_LEVEL"),                       # -> chrome/ui: out
                (3, 4, 0, 0, 100, "chrome/browser/ui/v.cc"),                 # out
                (3, 1, 1, 0, 101, "/PATCHSET_LEVEL"),                       # -> blink: in
                (2, 3, 0, 0, 101, "third_party/blink/renderer/core/a.cc"),  # in
                (3, 5, 0, 0, 102, "/PATCHSET_LEVEL"),                       # unplaced: out
            ], cls={100: "chrome/browser/ui/v.cc", 101: "third_party/blink/renderer/core/a.cc", 102: None})
            out = os.path.join(d, "s")
            rows = summarize(data_dir=d, out_dir=out)
            with open(os.path.join(out, "area_weekly.json")) as fh:
                areas = json.load(fh)
            with open(os.path.join(out, "area_reviewers.json")) as fh:
                area_reviewers = json.load(fh)
            with open(os.path.join(out, "org_weekly.json")) as fh:
                meta = json.load(fh)["meta"]
        self.assertEqual([(r["org"], r["comments"], r["ai_comments"], r["reviewers"], r["share"],
                           r["reviewed_cls"], r["share_cls"]) for r in rows],
                         [("microsoft.com", 4, 0, 1, 0.6667, 2, 0.6667),
                          ("google.com", 2, 1, 1, 0.3333, 1, 0.3333)])
        self.assertEqual(meta["path_rules"][0], {"prefix": "chrome/browser/web_applications/", "included": True})
        # Every comment appears in the directory tree, in scope or not.
        nodes = areas["nodes"]

        def full(i):
            parent, label, _ = nodes[i]
            return label if parent < 0 else full(parent) + label
        paths = [full(i) for i in range(len(nodes))]
        roots = {paths[i] for i, n in enumerate(nodes) if n[0] < 0}
        # Roots: top-level directories and `area` prefixes. Every rule directory
        # is a node, so re-included ones sit inside their (excluded) parents.
        self.assertEqual(roots, {UNPLACED, "chrome/", "ios/", "android_webview/", "ash/", "chromeos/", "components/",
                                 "third_party/blink/"})
        self.assertEqual(set(paths) - roots, {
            "chrome/browser/", "chrome/browser/ui/", "chrome/browser/web_applications/", "chrome/browser/webnn/",
            "components/viz/", "components/services/", "components/services/storage/",
            "third_party/blink/renderer/", "third_party/blink/renderer/core/"})
        # Children store only their own segment; parents come first.
        self.assertEqual(nodes[paths.index("chrome/browser/ui/")][1], "ui/")
        self.assertTrue(all(n[0] < i for i, n in enumerate(nodes)))
        self.assertEqual({p for i, p in enumerate(paths) if nodes[i][2]}, {
            "chrome/browser/web_applications/", "chrome/browser/webnn/", "components/viz/",
            "components/services/storage/", "third_party/blink/", "third_party/blink/renderer/",
            "third_party/blink/renderer/core/"})
        # [comments, reviewed CLs, chars] per (bucket, org).
        got = {(paths[n], areas["orgs"][o]): v for n, o, *v in areas["weeks"]["2026-W44"]}
        self.assertEqual(got, {("chrome/browser/ui/", "microsoft.com"): [2, 1, 20],
                               ("chrome/browser/ui/", "google.com"): [4, 1, 40],
                               (UNPLACED, "google.com"): [5, 1, 50],
                               ("third_party/blink/renderer/core/", "microsoft.com"): [3, 1, 30],
                               ("third_party/blink/renderer/core/", "google.com"): [2, 1, 20],
                               ("chrome/browser/web_applications/", "microsoft.com"): [1, 1, 10]})
        # The same buckets' comments by reviewer, indexed like area_weekly.json.
        self.assertEqual(area_reviewers["meta"]["areas_generated_at"], areas["meta"]["generated_at"])
        got = {(paths[n], areas["orgs"][o]): pairs for n, o, *pairs in area_reviewers["weeks"]["2026-W44"]}
        self.assertEqual(got, {("chrome/browser/ui/", "microsoft.com"): [2, 2],
                               ("chrome/browser/ui/", "google.com"): [3, 4],
                               (UNPLACED, "google.com"): [3, 5],
                               ("third_party/blink/renderer/core/", "microsoft.com"): [2, 3],
                               ("third_party/blink/renderer/core/", "google.com"): [3, 2],
                               ("chrome/browser/web_applications/", "microsoft.com"): [2, 1]})

    def test_summarize_refuses_a_missing_db(self):
        with tempfile.TemporaryDirectory() as d:
            missing = os.path.join(d, "nope.sqlite")
            with self.assertRaises(SystemExit):
                summarize(data_dir=d, out_dir=os.path.join(d, "s"), db_path=missing)
            self.assertFalse(os.path.exists(missing))

    def test_metric_picks_the_share_column(self):
        accounts = [(1, "owner@igalia.com"), (2, "a@microsoft.com"), (3, "b@google.com")]
        with tempfile.TemporaryDirectory() as d:
            # Microsoft: 1 comment on each of CLs 100 and 101; Google: 5 on CL 100.
            summary_db(d, accounts, [(2, 1, 0, 0, 100, "content/a.cc"), (2, 1, 0, 0, 101, "content/b.cc"),
                                     (3, 5, 0, 0, 100, "content/a.cc")],
                       cls={100: "content/a.cc", 101: "content/b.cc"})
            by_comments = summarize(data_dir=d, out_dir=os.path.join(d, "a"))
            by_cls = summarize(data_dir=d, out_dir=os.path.join(d, "b"), metric="cls")
            with self.assertRaises(ValueError):
                summarize(data_dir=d, out_dir=os.path.join(d, "c"), metric="votes")
        self.assertEqual([(r["org"], r["share"]) for r in by_comments],
                         [("google.com", 0.7143), ("microsoft.com", 0.2857)])
        # CLs: Microsoft reviewed 2, Google 1; rows are sorted by the metric.
        self.assertEqual([(r["org"], r["share"], r["share_comments"]) for r in by_cls],
                         [("microsoft.com", 0.6667, 0.2857), ("google.com", 0.3333, 0.7143)])

    def test_reviewer_weeks_keeps_everyone_split_by_org(self):
        from cosh.summarize import reviewer_weeks

        def f(week, aid, name, email, org, comments, chars=1, cls=(1,)):
            return dict(week=week, account_id=aid, name=name, email=email, org=org, comments=comments,
                        chars=chars, cls=set(cls))
        facts = [f("W", 1, "A", "a@x.com", "x.com", 10), f("W", 2, None, "b@x.com", "x.com", 1, 900),
                 f("W", 3, "C", "c@x.com", "x.com", 5, 5, [2, 3]), f("W", 3, "C", "c@y.com", "y.com", 2, 2, [4]),
                 f("V", 1, "A", "a@x.com", "x.com", 1)]
        names, weeks = reviewer_weeks(facts)
        self.assertEqual(names, {1: "A", 2: "b", 3: "C"})
        self.assertEqual(list(weeks), ["V", "W"])
        # Nobody is dropped; C's activity under y.com gets its own row.
        self.assertEqual([(r["account_id"], r["org"], r["comments"], r["cls"], r["chars"]) for r in weeks["W"]],
                         [(1, "x.com", 10, 1, 1), (3, "x.com", 5, 2, 5), (3, "y.com", 2, 1, 2),
                          (2, "x.com", 1, 1, 900)])

    def test_gmail_folded_into_other(self):
        with tempfile.TemporaryDirectory() as d:
            summary_db(d, [(1, "owner@igalia.com")] + [(a, f"r{a}@gmail.com") for a in range(2, 8)]
                       + [(8, "solo@opera.com")], [(a, 2, 0, 0) for a in range(2, 9)])
            rows = summarize(data_dir=d, out_dir=os.path.join(d, "summaries"))
        # gmail.com folds into Other; a one-reviewer org is reported on its own.
        self.assertEqual([(r["org"], r["reviewers"], r["comments"]) for r in rows],
                         [("Other", 6, 12), ("opera.com", 1, 2)])

    def test_old_derived_db_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            import sqlite3
            old = sqlite3.connect(os.path.join(d, "derived.sqlite"))
            old.execute("CREATE TABLE comments (host TEXT, is_inline INTEGER)")
            old.close()
            with self.assertRaises(SystemExit):
                store.open_derived(d)


if __name__ == "__main__":
    unittest.main()
