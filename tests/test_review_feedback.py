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

    def test_annual_change(self):
        # Halving every year is -50%; too few points or too short a span gives nothing.
        self.assertAlmostEqual(R.annual_change([(1, 4.0), (2, 2.0), (3, 1.0)]), -0.5)
        self.assertAlmostEqual(R.annual_change([(0, 1.0), (0.5, 1.0), (1, 1.0)]), 0.0)
        self.assertIsNone(R.annual_change([(1, 4.0), (2, 2.0)]))
        self.assertIsNone(R.annual_change([(1, 4.0), (1.5, 2.0), (1.9, 1.0)]))
        self.assertIsNone(R.annual_change([(1, 4.0), (2, None), (3, 1.0)]))
        # Zero counts as FLOOR instead of minus infinity.
        self.assertAlmostEqual(R.annual_change([(0, R.FLOOR), (1, 0.0), (2, R.FLOOR)]), 0.0)

    def test_histogram(self):
        self.assertEqual(R.histogram([-99, -10, 0, 5, 10, 500], [-10, 0, 10, 20]), [2, 2, 2])

    def test_tenure_trends(self):
        m = {k: 1.0 for k in R.METRICS}
        half_m = {k: 0.5 for k in R.METRICS}
        # Twenty people who started in 2020, at 3, 3.5 and 4 years, halving each year.
        pts = [[(2020, 3.2, "google.com", m, m), (2020, 3.7, "google.com", m, m), (2020, 4.2, "google.com", half_m, m)]
               for _ in range(R.MIN_COHORT)]
        pts.append([(2021, 1.0, "igalia.com", m, m)])
        cohorts, change = R.tenure_trends(pts, {"all": lambda o: True, "org:igalia": lambda o: o == "igalia.com"})
        self.assertEqual(cohorts["all"]["td"]["2020"], [[3.0, 1.0, 20], [3.5, 1.0, 20], [4.0, 0.5, 20]])
        self.assertEqual(cohorts["all"]["td"]["2021"], [])           # one person: too few for a point
        self.assertEqual(cohorts["org:igalia"]["td"], {"2021": []})
        self.assertEqual(change["all"]["td"]["n"], 20)
        self.assertGreater(change["all"]["td"]["median"], 0)          # less feedback: a positive reduction
        self.assertEqual(sum(change["all"]["td"]["counts"]), 20)
        self.assertEqual(change["org:igalia"]["td"], dict(n=0, median=None, counts=[0] * (len(R.CHANGE_EDGES) - 1)))

    def test_excerpt(self):
        self.assertEqual(R.excerpt("  a \n b "), "a b")
        long = "word " * 100
        e = R.excerpt(long)
        self.assertTrue(e.endswith("…") and len(e) <= R.EXCERPT + 1)
        self.assertEqual(R.excerpt(None), "")


if __name__ == "__main__":
    unittest.main()
