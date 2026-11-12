"""config/dataflow.json stays true to the repository, and the planner works."""
import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import dataflow  # noqa: E402


class InventoryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = dataflow.load()

    def test_inventory_matches_the_repository(self):
        # Ids resolve, code and committed files exist, every committed data
        # file and every file a page imports is listed, and nothing loops.
        self.assertEqual(dataflow.check(self.d), [])

    def test_check_reports_drift(self):
        d = copy.deepcopy(self.d)
        d["steps"][0]["inputs"].append("no-such-store")
        d["steps"][0]["code"].append("cosh/gone.py")
        d["stores"] = [s for s in d["stores"] if s["id"] != "summaries/balance_authors.json"]
        d["pages"] = [p for p in d["pages"] if p["id"] != "page-dataflow"]
        problems = "\n".join(dataflow.check(d))
        self.assertIn("extract: unknown id no-such-store", problems)
        self.assertIn("extract: code cosh/gone.py doesn't exist", problems)
        self.assertIn("summaries/balance_authors.json: committed data file that no store lists", problems)
        self.assertIn("web/dataflow.html: page that the inventory doesn't list", problems)
        self.assertIn("config/dataflow.json: imported by a page script but in no page's reads", problems)

    def test_plan_for_a_new_week(self):
        p = dataflow.plan(self.d, ["gerrit-rest", "gerrit-notedb"])
        ids = [s["id"] for s in p["steps"]]
        for a, b in (("extract", "derive"), ("derive", "classify"), ("classify", "summarize"),
                     ("derive", "balance-timeline"), ("balance-cl", "review-feedback"),
                     ("summarize", "pages-deploy")):
            self.assertLess(ids.index(a), ids.index(b), f"{a} before {b}")
        # Backfills and analysis scripts are never part of an update.
        self.assertNotIn("backfill", ids)
        self.assertNotIn("roi-analysis", ids)
        by_id = {s["id"]: s for s in p["steps"]}
        self.assertEqual(by_id["classify"]["refresh"], "optional")
        self.assertFalse(by_id["summarize"]["after_optional"])
        self.assertFalse(by_id["web-build"]["after_optional"])
        self.assertIn("summaries/org_weekly.json", p["commit"])
        self.assertIn("web/value.html", p["pages"])
        # Nothing private is ever listed for commit.
        self.assertFalse([f for f in p["commit"] if f.startswith("data/private")])

    def test_plan_for_new_radar_data(self):
        p = dataflow.plan(self.d, ["cloudflare-radar"])
        self.assertEqual([s["id"] for s in p["steps"]], ["radar", "web-build", "pages-deploy"])
        self.assertEqual(p["commit"], ["data/public/radar/raw/*", "data/public/radar_browser_share.csv"])
        self.assertEqual(p["pages"], ["web/value.html"])


if __name__ == "__main__":
    unittest.main()
