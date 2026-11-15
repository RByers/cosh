import contextlib
import io
import os
import tempfile
import time
import types
import unittest
from unittest import mock

from cosh import store, update


def fake_dataflow(data_dir, source_kind="model"):
    out = os.path.join(data_dir, "out.txt")
    d = {"sources": [{"id": "src", "kind": source_kind}],
         "stores": [{"id": "in", "path": "data/private/in.txt"},
                    {"id": "out", "path": "data/private/out.txt"}],
         "steps": [{"id": "step", "run": f"echo x >> {out}", "code": ["cosh/update.py"],
                    "inputs": ["in", "src"], "outputs": ["out"], "refresh": "routine"}]}
    plan = {"steps": [dict(id="step", command="step", refresh="routine", run=d["steps"][0]["run"],
                           duration=None, token_cost=None)], "commit": []}
    return types.SimpleNamespace(load=lambda: d, plan=lambda d, changed: plan)


class UpdateSkipTest(unittest.TestCase):
    def run_update(self, d, *args, source_kind="model"):
        buf = io.StringIO()
        with mock.patch.object(store, "DATA_DIR", d), \
                mock.patch.object(update, "_dataflow", lambda: fake_dataflow(d, source_kind)), \
                contextlib.redirect_stdout(buf):
            self.assertEqual(update.main(list(args)), 0)
        with open(os.path.join(d, "out.txt")) as f:
            return buf.getvalue(), len(f.read().split())

    def test_skips_until_an_input_or_output_changes(self):
        with tempfile.TemporaryDirectory() as d:
            inp = os.path.join(d, "in.txt")
            with open(inp, "w") as f:
                f.write("a")
            self.assertEqual(self.run_update(d)[1], 1)
            log, runs = self.run_update(d)
            self.assertEqual(runs, 1)
            self.assertIn("skipped", log)
            self.assertEqual(self.run_update(d, "--force")[1], 2)
            # A changed input runs it again.
            with open(inp, "w") as f:
                f.write("bb")
            self.assertEqual(self.run_update(d)[1], 3)
            self.assertEqual(self.run_update(d)[1], 3)
            # So does an output changed or removed since.
            later = time.time() + 5
            os.utime(os.path.join(d, "out.txt"), (later, later))
            self.assertEqual(self.run_update(d)[1], 4)

    def test_a_step_reading_a_fetched_source_always_runs(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "in.txt"), "w") as f:
                f.write("a")
            self.assertEqual(self.run_update(d, source_kind="file")[1], 1)
            self.assertEqual(self.run_update(d, source_kind="file")[1], 2)

    def test_record_marks_done_without_running(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "in.txt"), "w") as f:
                f.write("a")
            with open(os.path.join(d, "out.txt"), "w") as f:
                f.write("x")
            log, runs = self.run_update(d, "--record")
            self.assertIn("recorded 1 steps", log)
            self.assertEqual(self.run_update(d)[1], 1)


if __name__ == "__main__":
    unittest.main()
