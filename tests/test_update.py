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


class UpdateTraceTest(unittest.TestCase):
    """A step reruns when a module or config file it read changes, though
    its `code` list doesn't name it."""

    def test_reruns_when_a_traced_file_changes(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(root, "scripts"))
            os.makedirs(os.path.join(root, "config"))
            helper = os.path.join(root, "scripts", "helper_mod.py")
            conf = os.path.join(root, "config", "x.txt")
            other = os.path.join(root, "scripts", "unused_mod.py")
            for f, text in ((helper, "N = 1\n"), (conf, "a\n"), (other, "M = 1\n")):
                with open(f, "w") as fh:
                    fh.write(text)
            main = os.path.join(root, "scripts", "main_mod.py")
            with open(main, "w") as fh:
                fh.write("import sys\nsys.path.insert(0, %r)\nimport helper_mod\n"
                         "open(%r).read()\nopen(%r, 'a').write('x\\n')\n"
                         % (os.path.dirname(main), conf, os.path.join(d, "out.txt")))
            out = os.path.join(d, "out.txt")
            dfl = {"sources": [{"id": "src", "kind": "model"}],
                   "stores": [{"id": "out", "path": "data/private/out.txt"}],
                   "steps": [{"id": "step", "run": f"python3 {main}", "code": ["scripts/main_mod.py"],
                              "inputs": ["src"], "outputs": ["out"], "refresh": "routine"}]}
            plan = {"steps": [dict(id="step", command="step", refresh="routine", run=dfl["steps"][0]["run"],
                                   duration=None, token_cost=None)], "commit": []}
            fake = types.SimpleNamespace(load=lambda: dfl, plan=lambda d, changed: plan)

            def runs():
                with mock.patch.object(store, "DATA_DIR", d), mock.patch.object(update, "ROOT", root), \
                        mock.patch.object(update, "_dataflow", lambda: fake), \
                        contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(update.main([]), 0)
                with open(out) as f:
                    return len(f.read().split())

            self.assertEqual(runs(), 1)
            self.assertEqual(runs(), 1)
            with open(other, "w") as fh:       # not read by the step
                fh.write("M = 2\n")
            self.assertEqual(runs(), 1)
            with open(helper, "w") as fh:      # imported by the step
                fh.write("N = 2\n")
            self.assertEqual(runs(), 2)
            self.assertEqual(runs(), 2)
            with open(conf, "w") as fh:        # a config file it opened
                fh.write("b\n")
            self.assertEqual(runs(), 3)
            with mock.patch.object(store, "DATA_DIR", d):
                rec = update._load_state()["step"]
            self.assertIn("scripts/helper_mod.py", rec["code_files"])
            self.assertIn("config/x.txt", rec["code_files"])
            self.assertNotIn("scripts/unused_mod.py", rec["code_files"])
            self.assertGreater(rec["peak_rss_mb"], 0)


class SignatureTest(unittest.TestCase):
    def test_sees_the_wal_of_a_symlinked_sqlite_file(self):
        # Stores on /protected are symlinks; SQLite puts the WAL beside the real file.
        with tempfile.TemporaryDirectory() as d:
            real = os.path.join(d, "real")
            os.mkdir(real)
            db = os.path.join(real, "x.sqlite")
            for f in (db, db + "-wal"):
                with open(f, "w") as fh:
                    fh.write("a")
            link = os.path.join(d, "x.sqlite")
            os.symlink(db, link)
            self.assertEqual([n for n, *_ in update.signature(link)], ["x.sqlite", "x.sqlite-wal"])
            before = update.signature(link)
            with open(db + "-wal", "a") as fh:
                fh.write("more")
            self.assertNotEqual(update.signature(link), before)


if __name__ == "__main__":
    unittest.main()
