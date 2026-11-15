import hashlib
import os
import re
import sqlite3
import unittest

from cosh import codefp, derive


def one():
    return 1


def two():
    return 2


class FingerprintTest(unittest.TestCase):
    def test_parts_and_files(self):
        fp = codefp.fingerprint
        self.assertEqual(fp("a", 1, one), fp("a", 1, one))
        self.assertNotEqual(fp("a", 1, one), fp("a", 1, two))
        self.assertNotEqual(fp("a", 1, one), fp("a", 2, one))
        self.assertNotEqual(fp(re.compile("x")), fp(re.compile("x", re.M)))
        self.assertNotEqual(fp("a"), fp("a", files=["config/bots.txt"]))
        self.assertEqual(len(fp("a")), 16)

    def test_derive_fingerprint_unchanged_by_the_move(self):
        # derive's per-CL fingerprints were made by this computation before
        # codefp existed: the same value means no CL is re-derived for it.
        h = hashlib.sha256(f"{derive.METRIC_VERSION}|auto".encode())
        for f in derive.CODE_FILES:
            h.update(f.encode())
            with open(os.path.join(codefp.ROOT, f), "rb") as fh:
                h.update(hashlib.sha256(fh.read()).digest())
        self.assertEqual(derive.code_fingerprint("auto"), h.hexdigest()[:16])


class CheckTest(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.executescript("CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT);"
                              "CREATE TABLE rows (x INTEGER); INSERT INTO rows VALUES (1);")
        self.resets = 0

    def reset(self, db):
        self.resets += 1
        db.execute("DELETE FROM rows")

    def test_new_same_changed(self):
        self.assertEqual(codefp.check(self.db, "p", "f1", self.reset), "new")
        self.assertEqual(self.db.execute("SELECT count(*) FROM rows").fetchone(), (1,))   # adopted, kept
        self.assertEqual(codefp.check(self.db, "p", "f1", self.reset), "same")
        self.assertEqual(self.resets, 0)
        self.assertEqual(codefp.check(self.db, "p", "f2", self.reset), "changed")
        self.assertEqual((self.resets, self.db.execute("SELECT count(*) FROM rows").fetchone()), (1, (0,)))
        self.assertEqual(codefp.stored(self.db, "p"), "f2")
        self.assertFalse(self.db.in_transaction)

    def test_without_reset_the_caller_records(self):
        codefp.check(self.db, "p", "f1")
        self.assertEqual(codefp.check(self.db, "p", "f2"), "changed")
        self.assertEqual(codefp.stored(self.db, "p"), "f1")
        codefp.record(self.db, "p", "f2")
        self.assertEqual(codefp.check(self.db, "p", "f2"), "same")

    def test_failed_reset_keeps_old_rows_and_fingerprint(self):
        codefp.check(self.db, "p", "f1", self.reset)

        def bad(db):
            db.execute("DELETE FROM rows")
            raise RuntimeError("boom")
        with self.assertRaises(RuntimeError):
            codefp.check(self.db, "p", "f2", bad)
        self.assertEqual(self.db.execute("SELECT count(*) FROM rows").fetchone(), (1,))
        self.assertEqual(codefp.stored(self.db, "p"), "f1")


if __name__ == "__main__":
    unittest.main()
