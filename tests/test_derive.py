import unittest

from cosh.derive import derive_change, human_text
from cosh.orgs import OrgResolver, load_affiliations, parse_json5

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

if __name__ == "__main__":
    unittest.main()
