"""cosh/feedback.py helpers: the address hash the page shares,
periods, bands, quantiles and excerpts. No data is read."""

import unittest

from cosh import feedback as R


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

    def test_last_whole_half(self):
        t = lambda s: R.datetime.fromisoformat(s + "T00:00:00+00:00").timestamp()
        start = t("2017-07-03")
        self.assertEqual(R.last_whole_half(start, t("2026-11-01")), "2026H1")
        self.assertEqual(R.last_whole_half(start, t("2026-07-01")), "2026H1")
        self.assertEqual(R.last_whole_half(start, t("2026-06-30")), "2025H2")
        self.assertEqual(R.last_whole_half(t("2017-07-01"), t("2027-01-01")), "2026H2")
        self.assertIsNone(R.last_whole_half(t("2026-03-01"), t("2026-11-01")))

    def test_count_peers(self):
        t = lambda s: R.datetime.fromisoformat(s + "T00:00:00+00:00").timestamp()
        row = lambda cls, thr, acls, org: dict(cls=cls, threads=thr, acls=acls, addressed=acls // 2, org=org)
        # 12 Googlers and 3 others in 2026H1, whatever their tenure; 2026H2 isn't whole yet,
        # and one person was active only in 2025H2.
        per = {f"g{i}": {"2026H1": row(i + 1, 10 * i, i, "google.com"), "2026H2": row(99, 99, 99, "google.com")}
               for i in range(12)}
        per.update({f"o{i}": {"2026H1": row(1, 1, 0, "igalia.com")} for i in range(3)})
        per["old"] = {"2025H2": row(500, 500, 500, "google.com")}
        out = R.count_peers(per, t("2017-07-03"), t("2026-11-01"), t("2023-07-01"))
        self.assertEqual(out["count_half"], "2026H1")
        c = out["counts_half"]
        self.assertEqual((c["all"]["cls"]["n"], c["google"]["cls"]["n"], c["nongoogle"]["cls"]["n"]), (15, 12, 3))
        self.assertEqual((c["google"]["cls"]["q"][0], c["google"]["cls"]["q"][-1]), (1, 12))
        self.assertIsNone(c["nongoogle"]["cls"]["q"])          # fewer than MIN_PEERS
        # Labelled counts: only people with labelled changes (g0 has none).
        self.assertEqual(c["all"]["acls"]["n"], 11)
        # Labels that start after the half-year began give no addressed peers.
        late = R.count_peers(per, t("2017-07-03"), t("2026-11-01"), t("2026-02-01"))["counts_half"]
        self.assertEqual((late["all"]["cls"]["n"], late["all"]["acls"]["n"]), (15, 0))

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
        # Ratios 0.5, 1.5, 1/3, 0.5, 1, 0.2 in the bins below 0.397, [0.397, 0.5), [0.5, 0.63), ... from 2.52 on.
        self.assertEqual(ch["all"]["td"]["counts"], [2, 0, 2, 0, 0, 1, 1, 0, 0, 0])

    def test_matched_changes(self):
        none = {k: None for k in R.METRICS}
        val = lambda td: {**none, "td": td}
        y = lambda org, plain, time, changes, d: (org, dict(none=val(plain), time=val(time), changes=val(changes),
                                                            dir=val(d)))
        years = {
            "p1": {2024: y("google.com", 2.0, 1.0, 1.0, 1.0), 2025: y("google.com", 1.0, 0.8, 1.0, 1.5)},
            # 2025 -> 26 lacks a value by directory experience, so it isn't counted for any measure.
            "p2": {2024: y("igalia.com", 1.0, 1.0, 1.0, 1.0), 2025: y("igalia.com", 0.5, 1.0, 1.0, 0.5),
                   2026: y("igalia.com", 0.25, 1.0, 1.0, None)},
        }
        ch = R.matched_changes(years, {"all": lambda o: True, "nongoogle": lambda o: o != "google.com"})
        a = ch["all"]["td"]
        self.assertEqual((a["n"], a["people"]), (2, 2))
        # Medians of the two ratios each, as % less: plain 0.5 and 0.5; time 0.8 and 1; changes 1 and 1;
        # directory 1.5 and 0.5.
        self.assertEqual((a["none"], a["time"], a["changes"], a["dir"]), (50.0, 10.0, 0.0, 0.0))
        self.assertEqual(ch["nongoogle"]["td"]["n"], 1)
        self.assertIsNone(ch["all"]["ad"]["none"])

    def test_histogram(self):
        self.assertEqual(R.histogram([0.1, 0.5, 1, 2, 5], [0.5, 1, 2]), [1, 1, 1, 2])
        # The ratio bins pair each edge with its reciprocal.
        self.assertEqual([round(1 / r, 6) for r in reversed(R.CHANGE_RATIOS)], [round(r, 6) for r in R.CHANGE_RATIOS])

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

    def test_changes_bins(self):
        # Bins of earlier changes for the cohort curves and the all-against-addressed chart.
        self.assertEqual([R.chg_bin(n) for n in (0, 9, 10, 24, 25, 99, 100, 499, 500, 999, 1000, 5000)],
                         [0, 0, 1, 1, 2, 3, 4, 5, 6, 6, 7, 7])
        self.assertEqual(len(R.CHG_LABELS), len(R.CHG_EDGES) + 1)
        # Doublings for the histogram start at DOUBLING_FROM.
        self.assertEqual([R.doubling(n) for n in (0, 31, 32, 63, 64, 127, 128, 1024, 2047, 2048)],
                         [None, None, 0, 0, 1, 1, 2, 5, 5, 6])
        m = {k: 1.0 for k in R.METRICS}
        pts = [[(2020, 5, "google.com", m, m), (2020, 30, "google.com", m, m)] for _ in range(R.MIN_COHORT)]
        cohorts = R.tenure_trends(pts, {"all": lambda o: True}, R.chg_bin)
        self.assertEqual(cohorts["all"]["td"]["2020"], [[0, 1.0, 20], [2, 1.0, 20]])

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
