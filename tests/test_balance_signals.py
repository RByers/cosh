import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import balance_signals as S  # noqa: E402


class HelperTest(unittest.TestCase):
    def test_bucket_and_boot(self):
        self.assertEqual(S.bucket(4.5, S.TENURE), "3-6")
        self.assertEqual(S.bucket(200, S.TENURE), "120+")
        r = S.boot_ci([1.0] * 20)
        self.assertEqual((r["n"], r["mean"], r["lo"], r["hi"]), (20, 1.0, 1.0, 1.0))
        self.assertIsNone(S.boot_ci([1.0] * 3)["mean"])


if __name__ == "__main__":
    unittest.main()
