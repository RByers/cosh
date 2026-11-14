"""cosh/review_feedback.py helpers: the address hash the page shares,
periods, bins, the feedback rate model, quantiles and excerpts. No data is read."""

import unittest

from cosh import review_feedback as R


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
        self.assertEqual([R.tenure_band(y) for y in (0.5, 1, 3, 7, 12, None)],
                         ["<1y", "1-2y", "2-5y", "5-10y", "10y+", None])
        self.assertEqual([R.changes_band(n) for n in (0, 49, 50, 199, 200, 499, 500, 999, 1000, None)],
                         ["<50", "<50", "50-199", "50-199", "200-499", "200-499", "500-999", "500-999", "1000+", None])
        self.assertEqual(R.day_of("1970-01-02 03:00:00"), 1)
        self.assertEqual(R.epoch_day(86400 * 3 + 5), 3)

    def test_experience_bins(self):
        # Doublings of earlier commits: <8, 8–15, 16–31, ..., 1k–2k, 2k+.
        self.assertEqual([R.xbin(n) for n in (0, 7, 8, 15, 16, 1023, 1024, 2047, 2048, 50000)],
                         [0, 0, 1, 1, 2, 7, 8, 8, 9, 9])
        self.assertEqual(len(R.BIN_LABELS), len(R.BIN_EDGES) + 1)
        self.assertEqual((R.dir2("chrome/browser/ui/"), R.dir1("chrome/browser/ui/")), ("chrome/browser/", "chrome/"))
        self.assertEqual((R.dir2("(root)/"), R.dir1("ui/")), ("(root)/", "ui/"))
        # By lines, or by share where the landed commit changed none.
        self.assertEqual(R.unit_fracs([(0.6, 30), (0.4, 10)]), [0.75, 0.25])
        self.assertEqual(R.unit_fracs([(0.6, 0), (0.4, 0)]), [0.6, 0.4])

    def test_growth(self):
        # Halving per bin (doubling of changes landed): -50%.
        cells = {1: (10, 40, 1000), 2: (10, 20, 1000), 3: (10, 10, 1000)}
        self.assertEqual(R.growth(cells), -50.0)
        # Bins with too few CLs don't count, and two bins aren't enough.
        self.assertIsNone(R.growth({1: (10, 40, 1000), 2: (10, 20, 1000), 3: (R.MIN_BIN_CLS - 1, 10, 1000)}))
        # Zero feedback counts as FR_FLOOR (0.1 per 100 lines): 1.0 -> 0.1 -> 0.1, weighted by CLs.
        g = R.growth({0: (5, 10, 1000), 1: (5, 0, 1000), 2: (5, 0, 1000)})
        self.assertAlmostEqual(g, round(100 * (2 ** (-0.5 * R.math.log2(10)) - 1), 1))
        d = R.growth_dist([-50.0, -20.0, 0.0, 10.0])
        self.assertEqual((d["n"], d["median"]), (4, -10.0))
        self.assertEqual(len(d["curve"]), len(R.GROWTH_GRID))
        # The smoothed curve sums to about 100% over steps of 0.05 (it is per 0.1 of log2).
        self.assertAlmostEqual(sum(y for _, y in d["curve"]) / 2, 100, delta=1)

    def test_rate_model(self):
        # Twenty people with 30 one-directory CLs each: half in ui/ (2 addressed per 100 lines)
        # and half in base/ (1 per 100 lines), at two levels of experience.
        def row(pid, i):
            d = "ui/a/" if pid % 2 else "base/a/"
            b = 1 if i < 15 else 3
            a = (2 if pid % 2 else 1) * (2 if b == 1 else 1)
            return R.Row(pid, 0, 100, 8 if b == 1 else 32, b, "google.com" if pid < 15 else "x.com", a, [(d, 1.0, a)], d)
        rows = [row(pid, i) for pid in range(20) for i in range(30)]
        old = R.MIN_FACTOR_CLS
        R.MIN_FACTOR_CLS = 100
        try:
            m = R.rate_model(rows)
        finally:
            R.MIN_FACTOR_CLS = old
        self.assertEqual((m["ref_bin"][1], m["ref_bin"][3]), (3.0, 1.5))
        self.assertIsNone(m["ref_bin"][0])
        # ui/ draws twice what base/ does per line, whatever the experience.
        f = m["f_dir"]["e"]
        self.assertAlmostEqual(f["ui/a/"] / f["base/a/"], 2, places=2)
        # The expected threads of a CL: lines / 100 × the bin's median × the directory's factor.
        r = rows[1 * 30]          # pid 1 (ui/), bin 1
        self.assertAlmostEqual(R.expected(r, "e", m), 3.0)
        self.assertAlmostEqual(R.expected(r, "ed", m), 3.0 * f["ui/a/"])
        self.assertAlmostEqual(R.expected(r, "", m), m["ref_all"])
        # Orgs: "*" pools those under MIN_FACTOR_CLS (x.com has 150 CLs: its own factor here).
        self.assertIn("x.com", m["f_org"]["ed"])
        self.assertIn("*", m["f_org"]["ed"])

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
