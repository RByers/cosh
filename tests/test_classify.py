import json
import os
import tempfile
import unittest
from unittest import mock

from cosh import classify, store
from cosh.derive import derive_change, derive_threads
from cosh.summarize import summarize

H = "chromium-review.googlesource.com"
OWNER = 1


def c(cid, aid, ts, msg, parent=None, path="content/a.cc"):
    d = {"id": cid, "author": {"_account_id": aid}, "updated": f"2026-10-27 {ts}.000000000", "message": msg}
    if parent:
        d["in_reply_to"] = parent
    return path, d


def comments(*items):
    out = {}
    for path, d in items:
        out.setdefault(path, []).append(d)
    return out


CHANGE = {"_number": 100, "project": "chromium/src", "branch": "main", "status": "MERGED",
          "owner": {"_account_id": OWNER, "email": "o@google.com"}, "created": "2026-10-26 00:00:00.000000000",
          "updated": "2026-10-28 00:00:00.000000000", "submitted": "2026-10-28 00:00:00.000000000",
          "current_revision_number": 2, "total_comment_count": 6, "subject": "s"}

# r1: reviewer 2 asks, owner says Done, reviewer 2 thanks (after the change).
# r2: reviewer 3 asks, owner explains, reviewer 4 joins, owner changes it ("ok, switched").
# r3: owner starts a thread, reviewer 2 replies.
# r4: reviewer 4 comments, owner never replies.
THREADS = comments(
    c("r1", 2, "01:00:00", "nit: rename this"),
    c("a1", OWNER, "02:00:00", "Done", "r1"),
    c("t1", 2, "03:00:00", "Thanks!", "a1"),
    c("r2", 3, "01:00:00", "Why not use X?"),
    c("a2", OWNER, "02:00:00", "Because Y."),
    c("b2", 4, "02:30:00", "Y doesn't hold here", "r2"),
    c("d2", OWNER, "03:00:00", "Fair, switched to X", "b2"),
    c("r3", OWNER, "01:00:00", "PTAL at this part", path="/PATCHSET_LEVEL"),
    c("e3", 2, "02:00:00", "Looks fine", "r3", path="/PATCHSET_LEVEL"),
    c("r4", 4, "04:00:00", "FYI this exists elsewhere"),
)
# a2 is a top-level owner comment in the draft above; make it a reply to r2.
THREADS["content/a.cc"][4]["in_reply_to"] = "r2"


class ThreadTest(unittest.TestCase):
    def test_threads_follow_reply_chains_and_skip_owner_roots(self):
        ts = {t["root_id"]: t for t in classify.build_threads(THREADS, OWNER)}
        self.assertEqual(sorted(ts), ["r1", "r2", "r4"])
        self.assertEqual([i[0] for i in ts["r2"]["items"]], ["r2", "a2", "b2", "d2"])
        self.assertIn("r3", {t["root_id"] for t in classify.build_threads(THREADS, OWNER, include_owner=True)})

    def test_missing_parent_starts_a_thread(self):
        ts = classify.build_threads(comments(c("x", 2, "01:00:00", "hi", parent="gone")), OWNER)
        self.assertEqual([t["root_id"] for t in ts], ["x"])

    def test_thread_rows(self):
        rows = {r["root_uuid"]: r for r in derive_threads(CHANGE, THREADS)}
        self.assertEqual(rows["r1"]["regex_addressed"], 1)
        self.assertEqual(rows["r1"]["last_owner_reply_at"], "2026-10-27 02:00:00")
        self.assertEqual(rows["r2"]["regex_addressed"], 0)     # "Because Y." first
        self.assertEqual(rows["r2"]["last_owner_reply_at"], "2026-10-27 03:00:00")
        self.assertIsNone(rows["r4"]["last_owner_reply_at"])
        self.assertEqual(rows["r2"]["n_comments"], 4)

    def test_render_roles_and_hash(self):
        t = {x["root_id"]: x for x in classify.build_threads(THREADS, OWNER)}["r2"]
        text = classify.render(t, OWNER)
        self.assertEqual(text.splitlines(), ["REVIEWER: Why not use X?", "OWNER: Because Y.",
                                             "OTHER: Y doesn't hold here", "OWNER: Fair, switched to X"])
        h = classify.input_hash(text)
        self.assertEqual(h, classify.input_hash(text))
        self.assertTrue(-2 ** 63 <= h < 2 ** 63)
        self.assertNotEqual(h, classify.input_hash(text + "\nOWNER: more"))

    def test_regex(self):
        for yes in ["Done", "Done.", "done, thanks", "Fix applied.", "Good catch, fixed", "Removed."]:
            self.assertTrue(classify.DONE.match(yes), yes)
        for no in ["Acknowledged", "Because Y.", "I'd rather not", "Not done yet"]:
            self.assertFalse(classify.DONE.match(no), no)

    def test_derive_change_sets_root_uuid(self):
        _, _, rows = derive_change(CHANGE, THREADS)
        roots = {r["comment_id"]: r["root_uuid"] for r in rows}
        self.assertEqual(roots["t1"], "r1")
        self.assertEqual(roots["b2"], "r2")
        self.assertEqual(roots["e3"], "r3")        # owner-started thread still has a root
        self.assertNotIn("a1", roots)              # owner comments aren't rows


def build_db(d, label_r2=None, stale=False):
    """derived.sqlite for CHANGE + THREADS, and labels.sqlite with r2's label."""
    db = store.open_derived(d)
    accounts, ch, rows = derive_change(CHANGE, THREADS)
    with db:
        for aid, email in [(1, "o@google.com"), (2, "a@google.com"), (3, "b@microsoft.com"), (4, "c@igalia.com")]:
            db.execute("INSERT INTO accounts VALUES (?,?,?,NULL,0)", (H, aid, email))
        cols = list(ch)
        db.execute(f"INSERT INTO changes(host,{','.join(cols)}) VALUES (?,{','.join('?' * len(cols))})",
                   [H] + [ch[k] for k in cols])
        for r in rows:
            db.execute("INSERT INTO comments VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                       (H, 100, r["comment_id"], r["account_id"], r["written_at"], r["iso_week"], r["path"],
                        r["chars"], r["is_ai"], r["after_close"], r["root_uuid"]))
        for t in derive_threads(CHANGE, THREADS):
            db.execute("INSERT INTO threads VALUES (?,?,?,?,?,?,?,?)",
                       (H, 100, t["root_uuid"], t["root_account"], t["n_comments"], t["last_owner_reply_at"],
                        t["input_hash"], t["regex_addressed"]))
    hashes = dict(db.execute("SELECT root_uuid, input_hash FROM threads"))
    db.close()
    if label_r2 is not None:
        ldb = classify.open_labels(d)
        with ldb:
            ldb.execute("INSERT INTO classifiers VALUES (1, 'claude-haiku-test', ?, ?, 'now')",
                        (classify.DEF_VERSION, classify.PROMPT_SHA))
            ldb.execute("INSERT INTO runs(run_id, started_at) VALUES (1, 'now')")
            ldb.execute("INSERT INTO labels VALUES (100, 'r2', 1, ?, ?, 1)",
                        (hashes["r2"] + (1 if stale else 0), int(label_r2)))
        ldb.close()


class AddressedSummaryTest(unittest.TestCase):
    def run_summary(self, **kw):
        with tempfile.TemporaryDirectory() as d:
            build_db(d, **kw)
            out = os.path.join(d, "s")
            rows = summarize(data_dir=d, out_dir=out)
            with open(os.path.join(out, "org_weekly.json")) as fh:
                meta = json.load(fh)["meta"]
            with open(os.path.join(out, "reviewer_weekly.json")) as fh:
                reviewers = json.load(fh)
        return {r["org"]: r for r in rows}, meta, reviewers

    def test_points_per_comment_with_label(self):
        rows, meta, reviewers = self.run_summary(label_r2=True)
        # google.com (2): r1 scores, its "Thanks!" after the owner's last reply doesn't,
        # and e3 is in an owner-started thread. microsoft.com (3): r2. igalia.com (4):
        # b2 in r2 scores; r4 has no owner reply.
        self.assertEqual({o: (r["comments"], r["addressed_comments"], r["pending_comments"]) for o, r in rows.items()},
                         {"google.com": (3, 1, 0), "microsoft.com": (1, 1, 0), "igalia.com": (2, 1, 0)})
        self.assertEqual(rows["microsoft.com"]["share_addressed"], 0.3333)
        self.assertEqual(meta["addressed"]["coverage"], {"2026-W44": 1.0})
        self.assertEqual(meta["addressed"]["classifier"], "claude-haiku-test")
        self.assertEqual(reviewers["meta"]["columns"][-1], "addressed")

    def test_thread_breakdown(self):
        _, meta, _ = self.run_summary(label_r2=True)
        a = meta["addressed"]
        # r1: owner's "Done"; r2: Haiku says addressed; r4: no owner reply; r3 is the owner's own.
        self.assertEqual(dict(zip(a["thread_outcomes"], a["threads"]["2026-W44"])),
                         {"done_reply": 1, "model_addressed": 1, "model_not": 0, "no_reply": 1, "pending": 0})
        _, meta, _ = self.run_summary()
        self.assertEqual(dict(zip(meta["addressed"]["thread_outcomes"], meta["addressed"]["threads"]["2026-W44"]))
                         ["pending"], 1)

    def test_label_not_addressed(self):
        rows, _, _ = self.run_summary(label_r2=False)
        self.assertEqual(rows["microsoft.com"]["addressed_comments"], 0)
        self.assertEqual(rows["igalia.com"]["addressed_comments"], 0)

    def test_unlabelled_thread_is_pending(self):
        for kw in ({}, {"label_r2": True, "stale": True}):    # no labels file; label for an older input
            rows, meta, _ = self.run_summary(**kw)
            self.assertEqual(rows["microsoft.com"]["pending_comments"], 1)
            self.assertEqual(rows["igalia.com"]["pending_comments"], 1)
            self.assertEqual(meta["addressed"]["coverage"], {"2026-W44": round(1 - 2 / 6, 4)})

    def test_db_without_threads_is_all_pending(self):
        with tempfile.TemporaryDirectory() as d:
            build_db(d)
            db = store.open_derived(d)
            with db:
                db.execute("UPDATE comments SET root_uuid = NULL")
                db.execute("DELETE FROM threads")
            db.close()
            rows = summarize(data_dir=d, out_dir=os.path.join(d, "s"))
        self.assertEqual(sum(r["addressed_comments"] for r in rows), 0)
        self.assertEqual(sum(r["pending_comments"] for r in rows), 6)


class PendingTest(unittest.TestCase):
    def test_pending_threads(self):
        with tempfile.TemporaryDirectory() as d:
            build_db(d)
            db = store.open_derived(d)
            ldb = classify.open_labels(d)
            # Only r2 needs a model: r1 is settled by the regex, r4 has no owner reply.
            self.assertEqual([r[:2] for r in classify.pending_threads(db, ldb, None)], [(100, "r2")])
            self.assertEqual(classify.pending_threads(db, ldb, ["2026-W01"]), [])
            db.close()
            ldb.close()

    def test_claude_batch_parses_structured_output(self):
        out = json.dumps({"structured_output": {"labels": [{"id": "T0", "done": True}, {"id": "T1", "done": False}]},
                          "usage": {"input_tokens": 5, "output_tokens": 7, "cache_creation_input_tokens": 100},
                          "modelUsage": {"claude-haiku-x": {}}, "total_cost_usd": 0.01})
        with mock.patch("subprocess.run", return_value=mock.Mock(stdout=out, stderr="", returncode=0)) as run:
            got, cost = classify.claude_batch("haiku", [("T0", "a"), ("T1", "b")], "/tmp")
        self.assertEqual(got, {"T0": True, "T1": False})
        self.assertEqual((cost["model"], cost["tokens"]), ("claude-haiku-x", 112))
        cmd = run.call_args[0][0]
        self.assertIn("--json-schema", cmd)
        self.assertIn("--strict-mcp-config", cmd)


if __name__ == "__main__":
    unittest.main()
