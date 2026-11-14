"""cosh/review_feedback.py helpers: the address hash the page shares,
periods, bins, the AFR model, quantiles and excerpts. No data is read."""

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
        # Everyone's index: on a log2 grid, indexes under 1/8 counted as 1/8.
        f = R.fi_dist([0.0, 0.5, 1.0, 1.0, 2.0])
        self.assertEqual((f["n"], f["q"][10]), (5, 1.0))
        self.assertEqual((f["curve"][0][0], f["curve"][60][0]), (0.125, 1.0))
        self.assertEqual(max(f["curve"], key=lambda c: c[1])[0], 1.0)
        self.assertEqual(R.BIN_LABELS[:3] + R.BIN_LABELS[-2:], ["8", "16", "32", "2k", ">2k"])

    def test_rate_model(self):
        # Twenty people with 30 one-directory CLs each: half in ui/a/ (2 addressed per 100 lines)
        # and half in base/a/ (1 per 100 lines), each doubled at the lower of two levels of experience.
        def row(pid, i):
            d = "ui/a/" if pid % 2 else "base/a/"
            b = 1 if i < 15 else 3
            a = (2 if pid % 2 else 1) * (2 if b == 1 else 1)
            return R.Row(pid, 0, 100, 8 if b == 1 else 32, b, "google.com" if pid < 15 else "x.com", a,
                         [(d, 1.0, a, a + 1)], d)
        rows = [row(pid, i) for pid in range(20) for i in range(30)]
        # Plus a few CLs in a small directory, which takes its parent's rate.
        rows += [R.Row(0, 0, 100, 8, 1, "google.com", 0, [("ui/b/", 1.0, 0, 0)], "ui/b/")] * 3
        old = R.MIN_FACTOR_CLS, R.MIN_RATE_CLS
        R.MIN_FACTOR_CLS = R.MIN_RATE_CLS = 100
        try:
            m = R.rate_model(rows)
        finally:
            R.MIN_FACTOR_CLS, R.MIN_RATE_CLS = old
        self.assertEqual((m["ref_bin"][1], m["ref_bin"][3]), (3.0, 1.5))
        self.assertIsNone(m["ref_bin"][0])
        self.assertNotIn("_ue", {k for k in m if not k.startswith("_")})
        # Sums per half-year, directory and bin, then at any experience ([CLs' worth, lines, addressed]);
        # ui/ pools ui/a/ and ui/b/, which is too small for its own.
        self.assertEqual(list(m["rates"]), ["1970H1"])
        rates = m["rates"]["1970H1"]
        self.assertEqual([rates["ui/a/"][b] for b in (0, 1, 3, R.ALL_BINS)],
                         [None, [150, 15000, 600], [150, 15000, 300], [300, 30000, 900]])
        self.assertEqual(rates["ui/"][1], [153, 15300, 600])
        self.assertNotIn("ui/b/", rates)
        self.assertEqual(R.dir_levels("ui/a/b/"), ["ui/a/b/", "ui/a/", "ui/", ""])
        # Everyone's lines, or without the person's own: pid 0's three ui/b/ CLs come off ui/.
        old = R.MIN_RATE_CLS
        R.MIN_RATE_CLS = 100
        try:
            own0 = R.rate_cells([r for r in rows if r.pid == 0])
            self.assertEqual(R.peer_rate(m["rates"], None, "1970H1", "ui/b/", 1), 100 * 600 / 15300)
            self.assertEqual(R.peer_rate(m["rates"], own0, "1970H1", "ui/b/", 1), 4.0)
            self.assertEqual(R.peer_rate(m["rates"], None, "1970H1", "net/x/", 1), 100 * 900 / 30300)
        finally:
            R.MIN_RATE_CLS = old
        # A directory left under the minimum without the person falls back to its parent, then to
        # everyone's that half-year, then everyone's in an earlier half-year, else that half-year's anyway.
        cells = lambda x: [list(x) for _ in range(R.ALL_BINS + 1)]
        small = {"2025H2": {"": cells([1000, 10000, 200])},
                 "2026H1": {"": cells([150, 3000, 30]), "ui/": cells([300, 5000, 150])}}
        mine = lambda n: {("2026H1", "ui/"): cells([n, 1000, 50])}
        self.assertEqual(R.MIN_RATE_CLS, 200)
        self.assertEqual(R.peer_rate(small, None, "2026H1", "ui/x/", 0), 3.0)
        self.assertEqual(R.peer_rate(small, mine(50), "2026H1", "ui/x/", 0), 2.5)
        self.assertEqual(R.peer_rate(small, mine(120), "2026H1", "ui/x/", 0), 2.0)
        self.assertEqual(R.peer_rate({"2026H1": small["2026H1"]}, mine(120), "2026H1", "ui/x/", 0), 1.0)
        # In its own directory at its own experience everyone draws what peers do: an index of 1 each,
        # so no scaling. Without directories ui/ people draw twice what base/ people do.
        self.assertEqual(m["scale"]["ed"], 1.0)
        r = rows[1 * 30]          # pid 1 (ui/a/), bin 1: 15 CLs there of 100 lines with 4 addressed
        self.assertAlmostEqual(R.expected(r, "ed", m), 4.0)
        self.assertAlmostEqual(R.expected(r, "e", m), 100 * (900 - 60) / (30300 - 1500) * m["scale"]["e"])
        self.assertAlmostEqual(R.expected(r, "", m), 100 * (1350 - 90) / (60300 - 3000) * m["scale"][""])
        self.assertEqual(R.unit_expected(r, "edo", m), [R.expected(r, "ed", m) * m["f_org"]["ed"]["google.com"]])
        # Orgs: "*" pools those under MIN_FACTOR_CLS (x.com has 150 CLs: its own factor here).
        self.assertIn("x.com", m["f_org"]["ed"])
        self.assertIn("*", m["f_org"]["ed"])

    def test_dir_table(self):
        # Lines and threads split by lines; small directories pooled per level, with how many.
        rows = [R.Row(1, 0, 100, 0, 0, "o", 3, [("a/b/c/", 0.75, 2, 3), ("a/", 0.25, 1, 2)], "a/b/c/")] * 150
        rows += [R.Row(1, 0, 10, 0, 0, "o", 1, [("a/x/", 1.0, 1, 1)], "a/x/")] * 5
        old = R.MIN_DIR_CLS
        R.MIN_DIR_CLS = 100
        try:
            t = R.dir_table(rows)
        finally:
            R.MIN_DIR_CLS = old
        self.assertEqual(t, [["a/", 0, 15050, 755, 455], ["a/", 1, 3750, 300, 150],
                             ["a/b/", 0, 11250, 450, 300], ["a/b/c/", 0, 11250, 450, 300],
                             ["a/", 2, 50, 5, 5, 1]])

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


    def test_comment_file_lines_up_with_shard(self):
        # Threads [root, path, day, addressed, directory], listed out of order; it landed 2024-10-04.
        c = dict(change_number=7, closed_at=86400 * 20000, lines=10, exp_td=1.0, exp_ad=0.5, org="google.com",
                 prior=3, main="a/", units={"a/": [1, 2, 10]},
                 thr=[["r2", "a/x.cc", "2024-10-04", 1, "a/"], ["r1", "a/y.cc", "2024-10-03", None, "a/"],
                      ["r3", "a/x.cc", "2024-10-04", 0, "a/"]])
        sh = R.shard([c], True)
        # Each thread: [file, days after landing, addressed], in day then root order.
        self.assertEqual(sh["files"], ["a/y.cc", "a/x.cc"])
        self.assertEqual(sh["cls"][0][6], [[0, -1, None], [1, 0, 1], [1, 0, 0]])
        self.assertNotIn("counts", sh)
        # The thread index lists the same threads in the same order, and the comment file follows it.
        ids = R.thread_ids([c])
        self.assertEqual(ids, [[7, ["r1", "r2", "r3"]]])
        text = {"7/r1": "first", "7/r3": "third"}
        com = R.comment_file(ids, text, {"7/r3": -0.456})
        self.assertEqual(com, {"cls": {"7": [["r1", "first"], 0, ["r3", "third", -0.46]]}})
        self.assertEqual(R.comment_file(ids, {}, {}), {"cls": {}})
        # Older half-years: counts per unit, and no thread order to match.
        self.assertEqual(R.shard([c], False)["cls"][0][6], [[3, 1]])

    def test_shard_names_the_unit_of_a_moved_file(self):
        # old/x.cc is b/x.cc today, so its thread is in unit b/ (second), which
        # the page can't tell from the file: the thread says so.
        c = dict(change_number=8, closed_at=86400 * 20000, lines=10, exp_td=1.0, exp_ad=0.5, org="google.com",
                 prior=3, main="a/", units={"a/": [0.6, 2, 6], "b/": [0.4, 1, 4]},
                 thr=[["r1", "old/x.cc", "2024-10-04", 1, "b/"], ["r2", "a/y.cc", "2024-10-04", 0, "a/"],
                      ["r3", "gone/z.cc", "2024-10-05", 1, "a/"]])
        self.assertEqual(R.shard([c], True)["cls"][0][6], [[0, 0, 1, 1], [1, 0, 0], [2, 1, 1]])


if __name__ == "__main__":
    unittest.main()
