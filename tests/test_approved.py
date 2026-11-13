"""config/approved.json bounds what the fetchers may request."""
import unittest

from cosh import approved


class ApprovedTest(unittest.TestCase):
    def test_gerrit_weeks(self):
        r = approved.load()["gerrit_weeks"]
        approved.check_weeks([r["from"], r["to"], "2024-W01"])
        with self.assertRaises(approved.NotApproved):
            approved.check_weeks(["2026-W45"])
        with self.assertRaises(approved.NotApproved):
            approved.check_weeks(["2017-W26"])

    def test_patchsets(self):
        r = approved.load()["patchsets"]
        self.assertEqual(approved.patchsets_range(), (r["since"], r["until"]))
        self.assertEqual(approved.patchsets_range("2025-01-01"), ("2025-01-01", r["until"]))
        with self.assertRaises(approved.NotApproved):
            approved.patchsets_range("2020-01-01")


if __name__ == "__main__":
    unittest.main()
