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
        self.assertEqual(R.periods_of(t), ("all", "2026H2"))
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

    def test_yearly_changes(self):
        none = {k: None for k in R.METRICS}
        val = lambda td, ad=None: {**none, "td": td, "ad": ad}
        years = {
            # 2022 -> 2024 isn't consecutive, so it gives no value.
            "p1": {2018: ("google.com", val(4.0), none), 2019: ("google.com", val(2.0), none),
                   2020: ("google.com", val(3.0), none), 2021: ("google.com", val(1.0), none),
                   2022: ("google.com", val(0.5), none), 2024: ("google.com", val(0.25, 1.0), none),
                   2025: ("igalia.com", val(0.25, 0.5), val(2.0)), 2026: ("igalia.com", val(0.0, 1.0), val(1.0))},
        }
        groups = {"all": lambda o: True, "nongoogle": lambda o: o != "google.com", "dir:all": lambda o: True}
        ch = R.yearly_changes(years, groups)
        # 2018->19 (50%), 2019->20 (-50%), 2020->21 (67%), 2021->22 (50%), 2024->25 (0%),
        # 2025->26 (0.25 -> 0 counts as FLOOR: 80%).
        self.assertEqual(ch["all"]["td"]["n"], 6)
        self.assertEqual(ch["all"]["td"]["people"], 1)
        self.assertEqual(ch["all"]["td"]["median"], 50.0)
        # Addressed: 2024->25 (50% less), 2025->26 (100% more).
        self.assertEqual(ch["all"]["ad"]["n"], 2)
        self.assertEqual(ch["all"]["ad"]["median"], -25.0)
        # Groups go by the later year's org; "dir:" reads the directory-experience values.
        self.assertEqual(ch["nongoogle"]["td"]["n"], 2)
        self.assertEqual(ch["dir:all"]["td"]["n"], 1)
        self.assertEqual(ch["dir:all"]["td"]["median"], 50.0)
        self.assertEqual(sum(ch["all"]["td"]["counts"]), 6)

    def test_histogram(self):
        self.assertEqual(R.histogram([-99, -10, 0, 5, 10, 500], [-10, 0, 10, 20]), [2, 2, 2])

    def test_tenure_trends(self):
        m = {k: 1.0 for k in R.METRICS}
        half_m = {k: 0.5 for k in R.METRICS}
        # Twenty people who started in 2020, at 3, 3.5 and 4 years, halving each year.
        pts = [[(2020, 3.2, "google.com", m, m), (2020, 3.7, "google.com", m, m), (2020, 4.2, "google.com", half_m, m)]
               for _ in range(R.MIN_COHORT)]
        pts.append([(2021, 1.0, "igalia.com", m, m)])
        cohorts = R.tenure_trends(pts, {"all": lambda o: True, "org:igalia": lambda o: o == "igalia.com"})
        self.assertEqual(cohorts["all"]["td"]["2020"], [[3.0, 1.0, 20], [3.5, 1.0, 20], [4.0, 0.5, 20]])
        self.assertEqual(cohorts["all"]["td"]["2021"], [])           # one person: too few for a point
        self.assertEqual(cohorts["org:igalia"]["td"], {"2021": []})

    def test_tenure_trends_older_points(self):
        m = {k: 1.0 for k in R.METRICS}
        none = {k: None for k in R.METRICS}
        # Older half-years have only the all-threads measures.
        pts = [[(2018, 0.2, "google.com", {**none, "td": 2.0}, none, True),
                (2018, 5.2, "google.com", m, m), (2018, 5.7, "google.com", m, m)] for _ in range(R.MIN_COHORT)]
        cohorts = R.tenure_trends(pts, {"all": lambda o: True})
        self.assertEqual(cohorts["all"]["td"]["2018"], [[0.0, 2.0, 20], [5.0, 1.0, 20], [5.5, 1.0, 20]])
        self.assertEqual(cohorts["all"]["ad"]["2018"], [[5.0, 1.0, 20], [5.5, 1.0, 20]])

    def test_excerpt(self):
        self.assertEqual(R.excerpt("  a \n b "), "a b")
        long = "word " * 100
        e = R.excerpt(long)
        self.assertTrue(e.endswith("…") and len(e) <= R.EXCERPT + 1)
        self.assertEqual(R.excerpt(None), "")


if __name__ == "__main__":
    unittest.main()
