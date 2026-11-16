import io
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from cosh import memcap

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOLD_THEN_EXIT = ("import sys, time; from cosh import memcap; memcap.acquire(); "
                  "print('held', flush=True); time.sleep(float(sys.argv[1]))")


class HeavyRunLockTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = {k: v for k, v in os.environ.items() if k not in (memcap.HELD, "COSH_MEMCAP")}
        self.env["COSH_MEMCAP_LOCK"] = os.path.join(self.tmp.name, "heavy.lock")
        patch = mock.patch.dict(os.environ, self.env, clear=True)
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(memcap.release)

    def holder(self, secs, *cmd):
        p = subprocess.Popen(list(cmd) or [sys.executable, "-c", HOLD_THEN_EXIT, str(secs)],
                             cwd=ROOT, env=self.env, stdout=subprocess.PIPE, text=True)
        self.addCleanup(p.stdout.close)
        self.addCleanup(p.wait)
        self.assertEqual(p.stdout.readline().strip(), "held")
        return p

    def test_waits_for_another_process_and_names_it(self):
        self.holder(0.5)
        err = io.StringIO()
        with mock.patch.object(sys, "stderr", err):
            t0 = time.time()
            self.assertTrue(memcap.acquire())
        self.assertGreater(time.time() - t0, 0.3)
        self.assertIn("waiting for the heavy run before this one", err.getvalue())
        self.assertEqual(os.environ[memcap.HELD], str(os.getpid()))
        memcap.release()
        self.assertNotIn(memcap.HELD, os.environ)

    def test_children_of_a_holder_do_not_wait(self):
        with memcap.hold():
            with memcap.hold():          # nested: still held after the inner one
                pass
            self.assertIn(memcap.HELD, os.environ)
            t0 = time.time()
            subprocess.run([sys.executable, "-c", "from cosh import memcap; assert memcap.acquire()"],
                           cwd=ROOT, check=True, timeout=10)
            self.assertLess(time.time() - t0, 5)
        self.assertNotIn(memcap.HELD, os.environ)

    def test_a_wrapped_command_keeps_the_lock(self):
        # `python3 -m cosh.memcap CMD` (here without systemd: an empty PATH)
        with tempfile.TemporaryDirectory() as empty:
            self.env["PATH"] = empty
            self.holder(0, sys.executable, os.path.join(ROOT, "cosh", "memcap.py"), "/bin/sh", "-c",
                        "echo held; exec /bin/sleep 0.5")
        t0 = time.time()
        with mock.patch.object(sys, "stderr", io.StringIO()):
            memcap.acquire()
        self.assertGreater(time.time() - t0, 0.3)

    def test_off_skips_it(self):
        os.environ["COSH_MEMCAP"] = "off"
        self.assertFalse(memcap.acquire())
        self.assertFalse(memcap.join())


if __name__ == "__main__":
    unittest.main()
