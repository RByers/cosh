import json
import os
import tempfile
import unittest

from cosh.derive import account_name, derive_change, human_text, mark_emailless_bots
from cosh import store
from cosh.orgs import OrgResolver, load_affiliations, parse_json5
from cosh.summarize import summarize

OWNER = {"_account_id": 1, "email": "author@chromium.org"}
REV = {"_account_id": 2, "email": "rev@microsoft.com"}
BOT = {"_account_id": 3, "email": "chromium-scoped@luci-project-accounts.iam.gserviceaccount.com",
       "tags": ["SERVICE_USER"]}
CC = {"_account_id": 4, "email": "cc@google.com"}

CHANGE = {
    "_number": 100, "status": "MERGED", "project": "chromium/src", "branch": "main", "owner": OWNER,
    "created": "2026-10-20 10:00:00.000000000", "submitted": "2026-10-27 12:00:00.000000000",
    "total_comment_count": 5,
    "labels": {"Code-Review": {"all": [dict(REV, value=1), dict(BOT, value=0),
                                       dict(OWNER, value=0)]}},
}
COMMENTS = {
    "/PATCHSET_LEVEL": [
        {"author": REV, "message": "lgtm", "updated": "2026-10-26 00:00:00.000000000"},
        {"author": OWNER, "message": "thanks", "updated": "2026-10-26 01:00:00.000000000"},
    ],
    "a.cc": [
        {"author": REV, "message": "> quoted\nnit: rename", "updated": "2026-10-25 00:00:00.000000000"},
        {"author": REV, "message": "AI says x", "is_ai": True, "updated": "2026-10-25 00:00:00.000000000"},
        {"author": CC, "message": "late", "updated": "2026-10-28 00:00:00.000000000"},
    ],
}


class DeriveTest(unittest.TestCase):
    def test_rows(self):
        accounts, ch, reviews = derive_change(CHANGE, COMMENTS)
        self.assertEqual(set(reviews), {2, 4})          # owner + zero-vote bot excluded
        r = reviews[2]
        self.assertEqual((r["review_comments"], r["review_chars"], r["ai_comments"], r["voted_cr"]),
                         (2, len("lgtm") + len("nit: rename"), 1, 1))
        self.assertEqual((reviews[4]["review_comments"], reviews[4]["post_merge_comments"]), (0, 1))
        self.assertEqual(ch["iso_week"], "2026-W44")
        self.assertEqual(ch["is_bot_owned"], 0)

    def test_vote_only_when_comments_not_fetched(self):
        _, _, reviews = derive_change(CHANGE, None)
        self.assertEqual(reviews[2]["voted_cr"], 1)
        self.assertEqual(reviews[2]["review_comments"], 0)

    def test_bot_owned_cl_has_change_row_but_no_reviews(self):
        bot_cl = dict(CHANGE, owner=BOT)
        _, ch, reviews = derive_change(bot_cl, COMMENTS)
        self.assertEqual(ch["is_bot_owned"], 1)
        self.assertEqual(reviews, {})

    def test_abandoned_cl_bucketed_by_updated(self):
        ab = dict(CHANGE, status="ABANDONED", updated="2026-10-27 12:00:00.000000000")
        del ab["submitted"]
        _, ch, reviews = derive_change(ab, COMMENTS)
        self.assertEqual((ch["status"], ch["submitted_at"], ch["iso_week"]), ("ABANDONED", None, "2026-W44"))
        self.assertEqual(reviews[2]["review_comments"], 2)

    def test_account_details_from_anywhere_in_listing(self):
        cl = dict(CHANGE, attention_set={"9": {"account": {"_account_id": 9, "email": "x@igalia.com"}}},
                  removed_from_attention_set={"7": {"account": {"_account_id": 7, "tags": ["SERVICE_USER"],
                                                                "email": "ai@system.gserviceaccount.com"}}})
        comments = {"a.cc": [{"author": {"_account_id": 9}, "message": "hi", "updated": "2026-10-25 00:00:00"},
                             {"author": {"_account_id": 7}, "message": "bot", "updated": "2026-10-25 00:00:00"}]}
        accounts, _, _ = derive_change(cl, comments)
        self.assertEqual(accounts[9]["email"], "x@igalia.com")
        self.assertIn("SERVICE_USER", accounts[7]["tags"])

    def test_human_text(self):
        self.assertEqual(human_text("> a\n  > b\nok"), "ok")

    def test_org_resolver(self):
        r = OrgResolver({"cav@chromium.org": [("2026-01-12", "microsoft.com"),
                                              ("2022-05-03", "intel.com")]})
        self.assertEqual(r("cav@chromium.org", "2026-10-27 12:00:00"), "microsoft.com")
        self.assertEqual(r("Cav@chromium.org", "2023-01-01"), "intel.com")
        self.assertEqual(r("cav@chromium.org", "2020-01-01"), "google.com")   # before first start
        self.assertEqual(r("someone@chromium.org", "2026-01-01"), "google.com")
        self.assertEqual(r("x@igalia.com"), "igalia.com")
        self.assertEqual(r(None), "(no email)")

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
            db = store.open_cosh(d)
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
            db = store.open_cosh(d)
            h = "chromium-review.googlesource.com"
            with db:
                db.execute("INSERT INTO accounts VALUES (?,1,'a@igalia.com','A',0)", (h,))
                db.execute("INSERT INTO accounts VALUES (?,2,NULL,'Jetski (agent)',0)", (h,))
                db.execute("INSERT INTO accounts VALUES (?,3,NULL,NULL,0)", (h,))
                self.assertEqual(mark_emailless_bots(db), 2)
            self.assertEqual(db.execute("SELECT account_id, is_bot FROM accounts ORDER BY 1").fetchall(),
                             [(1, 0), (2, 1), (3, 1)])
            db.close()


class SummarizeTest(unittest.TestCase):
    def test_post_merge_comments_reported_separately(self):
        with tempfile.TemporaryDirectory() as d:
            db = store.open_cosh(d)
            h = "chromium-review.googlesource.com"
            with db:
                db.execute("INSERT INTO accounts VALUES (?,1,'owner@igalia.com',NULL,0)", (h,))
                for aid in range(2, 7):   # 5 igalia.com reviewers
                    db.execute("INSERT INTO accounts VALUES (?,?,?,NULL,0)", (h, aid, f"r{aid}@igalia.com"))
                db.execute("""INSERT INTO changes(host, change_number, project, branch, owner_account,
                              status, created_at, closed_at, iso_week)
                              VALUES (?,100,'chromium/src','main',1,'MERGED','2026-10-26 00:00:00',
                              '2026-10-27 12:00:00','2026-W44')""", (h,))
                # (account, review_comments, ai_comments, post_merge_comments)
                for aid, rc, ai, pm in [(2, 3, 1, 2), (3, 0, 0, 1), (4, 1, 0, 0), (5, 1, 0, 0), (6, 1, 0, 0)]:
                    db.execute("""INSERT INTO reviews(host, change_number, account_id, review_comments,
                                  review_chars, ai_comments, post_merge_comments)
                                  VALUES (?,100,?,?,?,?,?)""", (h, aid, rc, rc * 10, ai, pm))
            db.close()
            out = os.path.join(d, "summaries")
            rows = summarize(data_dir=d, out_dir=out)
            with open(os.path.join(out, "reviewer_weekly.json")) as fh:
                data = json.load(fh)
        self.assertEqual([(r["org"], r["comments"], r["ai_comments"], r["post_merge_comments"],
                           r["reviewers"]) for r in rows], [("igalia.com", 6, 1, 3, 5)])
        # Every reviewer (valid JSON despite the hand-rolled layout), AI/post-merge excluded;
        # account 3 (post-merge only) still reviewed the CL so counts for CLs.
        self.assertEqual(data["meta"]["columns"], ["account_id", "org", "comments", "cls", "chars"])
        self.assertEqual(data["orgs"], ["igalia.com"])
        self.assertEqual(data["accounts"], {str(a): f"r{a}" for a in range(2, 7)})
        self.assertEqual(data["weeks"]["2026-W44"],
                         [[2, 0, 3, 1, 30], [4, 0, 1, 1, 10], [5, 0, 1, 1, 10], [6, 0, 1, 1, 10],
                          [3, 0, 0, 1, 0]])

    def test_reviewer_weeks_keeps_everyone_split_by_org(self):
        from cosh.summarize import reviewer_weeks
        # (week, closed, cl, email, aid, comments, chars, ai, post_merge, name)
        rows = [("W", "2026-10-27", 1, "a@x.com", 1, 10, 1, 0, 0, "A"),
                ("W", "2026-10-27", 1, "b@x.com", 2, 1, 900, 0, 0, None),
                ("W", "2026-10-27", 2, "c@x.com", 3, 5, 5, 0, 0, "C"),
                ("W", "2026-10-27", 3, "c@x.com", 3, 0, 0, 0, 0, "C"),
                ("W", "2026-10-28", 4, "c@y.com", 3, 2, 2, 0, 0, "C"),
                ("V", "2026-10-20", 5, "a@x.com", 1, 1, 1, 0, 0, "A")]
        names, weeks = reviewer_weeks(rows, lambda email, when: email.split("@")[1])
        self.assertEqual(names, {1: "A", 2: "b", 3: "C"})
        self.assertEqual(list(weeks), ["V", "W"])
        # Nobody is dropped; C's reviews under y.com get their own row.
        self.assertEqual([(r["account_id"], r["org"], r["comments"], r["cls"], r["chars"]) for r in weeks["W"]],
                         [(1, "x.com", 10, 1, 1), (3, "x.com", 5, 2, 5), (3, "y.com", 2, 1, 2),
                          (2, "x.com", 1, 1, 900)])

    def test_gmail_folded_into_other(self):
        with tempfile.TemporaryDirectory() as d:
            db = store.open_cosh(d)
            h = "chromium-review.googlesource.com"
            with db:
                db.execute("INSERT INTO accounts VALUES (?,1,'owner@igalia.com',NULL,0)", (h,))
                for aid in range(2, 8):   # 6 gmail.com reviewers
                    db.execute("INSERT INTO accounts VALUES (?,?,?,NULL,0)", (h, aid, f"r{aid}@gmail.com"))
                db.execute("INSERT INTO accounts VALUES (?,8,'solo@opera.com',NULL,0)", (h,))
                db.execute("""INSERT INTO changes(host, change_number, project, branch, owner_account,
                              status, created_at, closed_at, iso_week)
                              VALUES (?,100,'chromium/src','main',1,'MERGED','2026-10-26 00:00:00',
                              '2026-10-27 12:00:00','2026-W44')""", (h,))
                for aid in range(2, 9):
                    db.execute("""INSERT INTO reviews(host, change_number, account_id, review_comments,
                                  review_chars, ai_comments, post_merge_comments)
                                  VALUES (?,100,?,2,20,0,0)""", (h, aid))
            db.close()
            rows = summarize(data_dir=d, out_dir=os.path.join(d, "summaries"))
        # gmail.com folds into Other; a one-reviewer org is reported on its own.
        self.assertEqual([(r["org"], r["reviewers"], r["comments"]) for r in rows],
                         [("Other", 6, 12), ("opera.com", 1, 2)])

    def test_vote_without_comment_counts_as_one(self):
        with tempfile.TemporaryDirectory() as d:
            db = store.open_cosh(d)
            h = "chromium-review.googlesource.com"
            with db:
                db.execute("INSERT INTO accounts VALUES (?,1,'owner@igalia.com',NULL,0)", (h,))
                for aid in range(2, 7):
                    db.execute("INSERT INTO accounts VALUES (?,?,?,NULL,0)", (h, aid, f"r{aid}@igalia.com"))
                db.execute("""INSERT INTO changes(host, change_number, project, branch, owner_account,
                              status, created_at, closed_at, iso_week)
                              VALUES (?,100,'chromium/src','main',1,'MERGED','2026-10-26 00:00:00',
                              '2026-10-27 12:00:00','2026-W44')""", (h,))
                # (account, review_comments, ai_comments, voted_cr)
                for aid, rc, ai, vote in [(2, 0, 0, 1),     # bare +1: counts as 1
                                          (3, 2, 0, 1),     # LGTM + nit + vote: stays 2, not 3
                                          (4, 0, 1, -1),    # only an AI comment, plus a vote: 1
                                          (5, 0, 0, None),  # post-merge comment only, no vote: 0
                                          (6, 1, 0, None)]:
                    db.execute("""INSERT INTO reviews(host, change_number, account_id, review_comments,
                                  review_chars, ai_comments, post_merge_comments, voted_cr)
                                  VALUES (?,100,?,?,?,?,?,?)""",
                               (h, aid, rc, rc * 10, ai, 1 if aid == 5 else 0, vote))
            db.close()
            rows = summarize(data_dir=d, out_dir=os.path.join(d, "summaries"))
        self.assertEqual([(r["comments"], r["vote_only_reviews"], r["review_chars"]) for r in rows],
                         [(5, 2, 30)])


if __name__ == "__main__":
    unittest.main()
