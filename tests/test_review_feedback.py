"""scripts/review_feedback.py helpers: the address hash the page shares,
periods, bands, quantiles and excerpts. No data is read."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import review_feedback as R  # noqa: E402


class ReviewFeedbackTest(unittest.TestCase):
    def test_key_matches_the_page(self):
        # web/test/unit.test.ts checks personKey() against these same values.
        self.assertEqual(R.key("Foo.Bar@Chromium.org"), "fb3b9e32f56a8f89c2ea38de91844541")
        self.assertEqual(R.key("foo.bar@google.com"), R.key("Foo.Bar@Chromium.org"))
        self.assertEqual(R.key("  someone@microsoft.com "), "5005b7c30306573a80bf031dd778435d")
        self.assertEqual(len(R.key("x@y.z")), 32)

    def test_periods_and_bands(self):
        t = 1767225600 + 200 * 86400          # 2026-07-20
        self.assertEqual(R.periods_of(t), ("all", "2026", "2026H2"))
        self.assertEqual([R.xp_band(n) for n in (0, 1, 4, 5, 19, 20, 99, 100)], [0, 1, 1, 2, 2, 3, 3, 4])
        self.assertEqual([R.tenure_band(y) for y in (0.5, 1, 3, 7, 12, None)],
                         ["<1y", "1-2y", "2-5y", "5-10y", "10y+", None])
        self.assertEqual([R.changes_band(n) for n in (0, 49, 50, 199, 200, 499, 500, 999, 1000, None)],
                         ["<50", "<50", "50-199", "50-199", "200-499", "200-499", "500-999", "500-999", "1000+", None])
        self.assertEqual(R.day_of("1970-01-02 03:00:00"), 1)
        self.assertEqual(R.epoch_day(86400 * 3 + 5), 3)

    def test_quantiles(self):
        q = R.quantiles(range(21))
        self.assertEqual(q, [float(i) for i in range(21)])
        self.assertEqual(R.quantiles([5]), [5] * 21)
        self.assertIsNone(R.quantiles([]))

    def test_excerpt(self):
        self.assertEqual(R.excerpt("  a \n b "), "a b")
        long = "word " * 100
        e = R.excerpt(long)
        self.assertTrue(e.endswith("…") and len(e) <= R.EXCERPT + 1)
        self.assertEqual(R.excerpt(None), "")


if __name__ == "__main__":
    unittest.main()
