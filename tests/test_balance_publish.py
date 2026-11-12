import json
import os
import tempfile
import unittest
from datetime import datetime, timezone

from cosh import balance_publish as P

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class WindowTest(unittest.TestCase):
    def test_quarters(self):
        self.assertEqual(P.quarter_end("2026Q3"), datetime(2026, 10, 1, tzinfo=timezone.utc))
        self.assertEqual(P.quarter_end("2026Q4"), datetime(2027, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(P.last_whole_quarter(datetime(2026, 11, 1, tzinfo=timezone.utc)), "2026Q3")
        self.assertEqual(P.last_whole_quarter(datetime(2026, 10, 1, tzinfo=timezone.utc)), "2026Q3")
        self.assertEqual(P.last_whole_quarter(datetime(2027, 2, 1, tzinfo=timezone.utc)), "2026Q4")
        self.assertEqual(P.LAST_QUARTER, P.last_whole_quarter(P.DATA_END))


class RecordTest(unittest.TestCase):
    def test_one_step_per_dataset(self):
        gives = [k for s in P.STEPS for k in s.gives]
        self.assertEqual(len(gives), len(set(gives)))
        self.assertEqual(len(P.STEPS), len(P.BY_NAME))
        for name in P.FILES[1:]:
            self.assertIn(name, gives)

    def test_record_matches_the_committed_file(self):
        # Every dataset the page has comes from a step, and no step gives one it lacks.
        with open(os.path.join(HERE, "summaries", "balance.json")) as f:
            committed = set(json.load(f)["datasets"])
        gives = {k for s in P.STEPS for k in s.gives} - set(P.FILES)
        self.assertEqual(committed, gives)

    def test_narrative_runs_after_growth(self):
        names = [s.name for s in P.STEPS]
        self.assertLess(names.index("growth"), names.index("narrative"))


def fake_results(work, change=None):
    """A result file per step, each dataset [{"step": name}]."""
    os.makedirs(work, exist_ok=True)
    for s in P.STEPS:
        res = {k: ({"k": k} if k in P.FILES else [{"step": s.name}]) for k in s.gives}
        if change and change[0] in res:
            res[change[0]] = change[1]
        with open(os.path.join(work, f"{s.name}.json"), "w") as f:
            json.dump(res, f)


class AssembleTest(unittest.TestCase):
    def test_write_and_compare(self):
        with tempfile.TemporaryDirectory() as d:
            fake_results(os.path.join(d, "a"))
            fake_results(os.path.join(d, "b"), change=("exchange", [{"step": "other"}]))
            for x in "ab":
                P.write(P.assemble(P.Context(os.path.join(d, x), d)), os.path.join(d, f"out-{x}"))
            with open(os.path.join(d, "out-a", "balance.json")) as f:
                doc = json.load(f)
            self.assertEqual(list(doc["datasets"])[:2], P.STEPS[0].gives[:2])     # STEPS order
            self.assertEqual(doc["datasets"]["pipeline"], [{"step": "pipeline"}])
            with open(os.path.join(d, "out-a", "balance_dirs.json")) as f:
                self.assertEqual(json.load(f), {"k": "balance_dirs.json"})
            rows = P.compare(os.path.join(d, "out-a"), os.path.join(d, "out-b"))
            bad = [r for r in rows if r[2] != "same"]
            self.assertEqual([(r[1], r[2]) for r in bad], [("exchange", "differs")])
            # `generated` is never compared.
            doc["generated"] = "1999-01-01"
            with open(os.path.join(d, "out-a", "balance.json"), "w") as f:
                json.dump(doc, f)
            self.assertEqual(len([r for r in P.compare(os.path.join(d, "out-a"), os.path.join(d, "out-a"))
                                  if r[2] != "same"]), 0)

    def test_step_must_give_what_it_says(self):
        with tempfile.TemporaryDirectory() as d:
            P.BY_NAME["_t"] = P.Step("_t", lambda ctx: {"x": 1, "y": 2}, ["x"])
            try:
                with self.assertRaises(SystemExit):
                    P.run_step(P.Context(d, d), "_t")
                P.BY_NAME["_t"].gives = ["x", "y"]
                P.run_step(P.Context(d, d), "_t")
                self.assertEqual(P.Context(d, d).result("_t"), {"x": 1, "y": 2})
            finally:
                del P.BY_NAME["_t"]


if __name__ == "__main__":
    unittest.main()
