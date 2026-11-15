"""config/dataflow.json stays true to the repository, and the planner works."""
import copy
import json
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
        # file and every file a page imports is listed, nothing loops, and
        # the flow rules hold.
        self.assertEqual(dataflow.check(self.d), [])

    def test_check_reports_drift(self):
        d = copy.deepcopy(self.d)
        d["steps"][0]["inputs"].append("no-such-store")
        d["steps"][0]["code"].append("cosh/gone.py")
        d["stores"] = [s for s in d["stores"] if s["id"] != "summaries/balance_authors.json"]
        d["pages"] = [p for p in d["pages"] if p["id"] != "page-dataflow"]
        problems = "\n".join(dataflow.check(d))
        self.assertIn("gerrit-fetch: unknown id no-such-store", problems)
        self.assertIn("gerrit-fetch: code cosh/gone.py doesn't exist", problems)
        self.assertIn("summaries/balance_authors.json: committed data file that no store lists", problems)
        self.assertIn("web/dataflow.html: page that the inventory doesn't list", problems)
        self.assertIn("config/dataflow.json: imported by a page script but in no page's reads", problems)

    def test_samples_keep_out_what_is_withheld(self):
        # The published samples hold no rows of a withheld store or table,
        # no redacted value, and every column shown has a meaning.
        with open(dataflow.SAMPLES, encoding="utf-8") as f:
            samples = json.load(f)
        self.assertEqual(dataflow.sample_problems(self.d, samples), [])
        bad = copy.deepcopy(samples)
        by = bad["stores"]
        by["data/private/feedback-coach/"]["parts"] = [{"name": None, "kind": "files", "columns": ["file"], "rows": [["x"]]}]
        scores = next(p for p in by["data/private/sentiment.sqlite"]["parts"] if p["name"] == "scores")
        scores["rows"] = [[1] * len(scores["columns"])]
        req = next(p for p in by["data/private/bugs/bugs.sqlite"]["parts"] if p["name"] == "requests")
        req["rows"] = [["x"] * len(req["columns"])]
        labels = next(p for p in by["data/private/addressed.sqlite"]["parts"] if p["name"] == "labels")
        labels["columns"].append("new_column")
        problems = "\n".join(dataflow.sample_problems(self.d, bad))
        self.assertIn("data/private/feedback-coach/: withheld, but the samples have its rows", problems)
        self.assertIn("data/private/sentiment.sqlite scores: withheld, but the samples have its rows", problems)
        self.assertIn("data/private/bugs/bugs.sqlite requests: column headers is redacted, but the samples show it", problems)
        self.assertIn("data/private/addressed.sqlite labels: column new_column has no meaning", problems)

    def test_flow_rules(self):
        d = copy.deepcopy(self.d)
        by = {s["id"]: s for s in d["steps"]}
        # A store a page depends on loses its writer: no inflow.
        by["review-feedback"]["outputs"] = []
        # A routine step that reaches no page.
        by["feedback-coach"]["refresh"] = "routine"
        problems = "\n".join(dataflow.check(d))
        self.assertIn("review-feedback: writes nothing", problems)
        self.assertIn("feedback-people: read on the way to page-feedback but written by no step", problems)
        self.assertIn("feedback-coach: routine but reaches no page", problems)
        # A balance store that feeds another page.
        d = copy.deepcopy(self.d)
        next(s for s in d["steps"] if s["id"] == "review-feedback")["inputs"].append("data/private/balance.sqlite")
        problems = "\n".join(dataflow.check(d))
        self.assertIn("data/private/balance.sqlite: named 'balance' (Review Balance) but also feeds page-feedback", problems)

    def test_non_balance_pages_need_nothing_named_balance(self):
        g = dataflow.Graph(self.d)
        for pid in ("page-value", "page-sentiment", "page-feedback", "page-review-load"):
            up = g.reach_back([pid])
            self.assertEqual([i for i in up if "balance" in i], [], pid)

    def test_plan_for_a_new_week(self):
        p = dataflow.plan(self.d, ["gerrit"])
        ids = [s["id"] for s in p["steps"]]
        for a, b in (("gerrit-fetch", "derive"), ("derive", "classify"), ("classify", "summarize"),
                     ("derive", "review-timeline"), ("review-timeline", "review-load"), ("review-timeline", "balance-cl"), ("comments-collect", "review-feedback"),
                     ("comments-score", "tone-publish")):
            self.assertLess(ids.index(a), ids.index(b), f"{a} before {b}")
        # Analysis scripts and maintenance are never part of an update.
        self.assertNotIn("roi-analysis", ids)
        self.assertNotIn("notedb-maintain", ids)
        # Uploads to R2 happen only when deploying, never in an update.
        self.assertNotIn("r2-feedback", ids)
        self.assertNotIn("r2-review-load", ids)
        by_id = {s["id"]: s for s in p["steps"]}
        self.assertEqual(by_id["classify"]["refresh"], "optional")
        self.assertFalse(by_id["summarize"]["after_optional"])
        self.assertTrue(by_id["gerrit-fetch"]["network"])
        self.assertEqual(by_id["derive"]["run"], "python3 -m cosh derive")
        self.assertIn("summaries/org_weekly.json", p["commit"])
        self.assertIn("web/value.html", p["pages"])
        # Nothing private is ever listed for commit.
        self.assertFalse([f for f in p["commit"] if f.startswith("data/private")])

    def test_plan_for_new_radar_data(self):
        p = dataflow.plan(self.d, ["cloudflare-radar"])
        self.assertEqual([s["id"] for s in p["steps"]], ["radar"])
        self.assertEqual(p["commit"], ["data/public/radar/raw/*", "data/public/radar_browser_share.csv"])
        self.assertEqual(p["pages"], ["web/value.html"])


class CommittedSummariesTest(unittest.TestCase):
    def test_area_files_match_area_weekly(self):
        # area_commits/authors/reviewers.json index area_weekly.json's nodes
        # and name the run that wrote it (meta.areas_generated_at); the page
        # ignores a file that names another (commitBoard in web/src/data.ts),
        # so committing only some of one summarize run's files empties the
        # directory chart. Commit every summaries/ file a run writes.
        import json
        root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "summaries")

        def meta(name):
            with open(os.path.join(root, name)) as f:
                return json.load(f)["meta"]
        stamp = meta("area_weekly.json")["generated_at"]
        for name in ("area_commits.json", "area_authors.json", "area_reviewers.json"):
            self.assertEqual(meta(name).get("areas_generated_at"), stamp, name)


if __name__ == "__main__":
    unittest.main()
