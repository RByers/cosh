"""cosh/review_feedback.py helpers: the file names and reviewer keys the page shares,
periods, bins, the AFR model, quantiles, the half-year files. No data is read."""

import unittest

from cosh import review_feedback as R


class ReviewFeedbackTest(unittest.TestCase):
    def test_names_match_the_page(self):
        # web/test/unit.test.ts checks personFile() and reviewerKey() against these same values.
        self.assertEqual(R.file_name("Foo.Bar@Chromium.org"), "foo.bar@google.com")
        self.assertEqual(R.file_name("  someone@Microsoft.com "), "someone@microsoft.com")
        self.assertEqual(R.file_name("a+b/c@x.org"), "a~2bb~2fc@x.org")
        self.assertEqual(R.file_name("é~@x.org"), "~c3~a9~7e@x.org")
        self.assertEqual(R.reviewer_key("Foo.Bar@Chromium.org"), "fb3b9e32f56a")
        self.assertEqual(R.reviewer_key("foo.bar@google.com"), R.reviewer_key("Foo.Bar@Chromium.org"))
        self.assertEqual(R.reviewer_key("  someone@microsoft.com "), "5005b7c30306")

    def test_periods_and_bands(self):
        t = 1767225600 + 200 * 86400          # 2026-07-20
        self.assertEqual(R.periods_of(t), ("all", "2026H2"))
        self.assertEqual(R.day_of("1970-01-02 03:00:00"), 1)
        self.assertEqual(R.epoch_day(86400 * 3 + 5), 3)

    def test_experience_bins(self):
        # Doublings of earlier commits: <8, 8–15, 16–31, ..., 2k–4k, 4k+.
        self.assertEqual([R.xbin(n) for n in (0, 7, 8, 15, 16, 1023, 1024, 2047, 2048, 4095, 4096, 50000)],
                         [0, 0, 1, 1, 2, 7, 8, 8, 9, 9, 10, 10])
        self.assertEqual(len(R.BIN_LABELS), len(R.BIN_EDGES) + 1)
        self.assertEqual((R.dir2("chrome/browser/ui/"), R.dir1("chrome/browser/ui/")), ("chrome/browser/", "chrome/"))
        self.assertEqual((R.dir2("(root)/"), R.dir1("ui/")), ("(root)/", "ui/"))
        # By lines, or equally where the landed commit inserted none.
        self.assertEqual(R.unit_fracs([30, 10]), [0.75, 0.25])
        self.assertEqual(R.unit_fracs([0, 0]), [0.5, 0.5])
        self.assertEqual(R.unit_order({"b/": 5, "a/": 5, "c/": 9}), [("c/", 9), ("a/", 5), ("b/", 5)])

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
        self.assertEqual(R.BIN_LABELS[:3] + R.BIN_LABELS[-2:], ["8", "16", "32", "4k", ">4k"])

    def test_rate_model(self):
        # Twenty people with 40 CLs of 100 lines each, all in ui/a/ at one experience: half approved by a
        # strict reviewer (4 addressed threads), half by an easy one (2), every person alike; then 10 CLs
        # each without an approver, which draw nothing.
        def row(pid, i):
            if i >= 40:
                return R.Row(pid, 0, 100, 8, 1, "o", 0, [("ui/a/", 1.0, 0, 0)], "ui/a/", ())
            strict = i % 2 == 0
            a = 4 if strict else 2
            return R.Row(pid, 0, 100, 8, 1, "o", a, [("ui/a/", 1.0, a, a)], "ui/a/",
                         ("strict@x.com",) if strict else ("easy@x.com",))
        rows = [row(pid, i) for pid in range(20) for i in range(50)]
        m = R.rate_model(rows)
        self.assertNotIn("_ue", {k for k in m if not k.startswith("_")})
        self.assertNotIn("rates", m)
        # Everyone's AFR at experience bin 1: 20 × 120 threads over 20 × 5,000 lines.
        self.assertEqual(m["rate_bin"][1], 2.4)
        # Reviewers: strict draws twice what easy does; over all CLs the factors average to 1, and CLs
        # without an approver, which drew nothing, take a factor near 0.
        f = m["_rev_factors"]
        # (a little under 2: each factor is shrunk toward 1 with FACTOR_SHRINK expected threads).
        self.assertAlmostEqual(f["strict@x.com"] / f["easy@x.com"], 2.0, delta=0.08)
        self.assertGreater(f["strict@x.com"] / f["easy@x.com"], 1.9)
        self.assertLess(m["rev_none"], 0.1)
        total = sum(r.lines / 100 * m["rate_bin"][r.bin] for r in rows)
        weighted = sum(r.lines / 100 * m["rate_bin"][r.bin] * R.rev_factor(r, f, m["rev_none"]) for r in rows)
        self.assertAlmostEqual(weighted / total, 1.0, delta=0.002)
        # Everyone is alike, so every index is 1 after scaling, and each CL's expected threads are its
        # lines / 100 × the rate × its reviewer's factor × the scale, both without the owner's CLs,
        # which here barely differ from everyone's.
        r = rows[0]
        own = m["_own"][r.pid]
        self.assertAlmostEqual(own["rate_bin"][1], 2.4)
        self.assertAlmostEqual(own["f"]["strict@x.com"], f["strict@x.com"], delta=0.01)
        self.assertEqual(set(own["f"]), {"strict@x.com", "easy@x.com"})
        self.assertAlmostEqual(R.expected(r, m), 100 / 100 * 2.4 * own["f"]["strict@x.com"] * m["scale"])
        self.assertEqual(R.unit_expected(r, m), [R.expected(r, m)])
        ex = [R.expected(x, m) for x in rows if x.pid == 3]
        self.assertAlmostEqual(sum(x.addr for x in rows if x.pid == 3) / sum(ex), 1.0, places=3)
        # The methodology: a size factor per bucket, the peer groups compared, drift per half-year.
        meth = R.method_compare(rows)
        self.assertEqual([k for k, _, _ in meth], ["e", "d", "r", "dr", "rd"])
        self.assertEqual(meth[0][2], 0.0)
        # Everyone works in ui/a/, so the directory explains nothing and the reviewer a lot.
        self.assertAlmostEqual(meth[1][2], 0.0, places=1)
        self.assertGreater(meth[2][2], 20)
        drift = R.drift_series(rows, m)
        self.assertEqual([d[0] for d in drift], ["1970H1"])
        self.assertAlmostEqual(drift[0][2], 1.0, places=3)
        self.assertEqual(R.size_deviance(rows[:1], [4.0]), 0.0)

    def test_own_changes_left_out(self):
        # Twenty people alike, as above, with one reviewer for everyone; person 99 draws three times as
        # much feedback, with a reviewer who approves only their CLs. With person 99's CLs in, that
        # reviewer would look strict and person 99's index would be pulled toward 1; without them, the
        # reviewer is the typical one and the index shows all of it.
        def row(pid, rev, a):
            return R.Row(pid, 0, 100, 8, 1, "o", a, [("ui/a/", 1.0, a, a)], "ui/a/", (rev,))
        rows = [row(pid, "all@x.com", 2) for pid in range(20) for _ in range(40)]
        rows += [row(99, "solo@x.com", 6) for _ in range(40)]
        m = R.rate_model(rows)
        self.assertGreater(m["_rev_factors"]["solo@x.com"], 1.3)
        own = m["_own"][99]
        self.assertEqual(set(own["f"]), {"solo@x.com"})
        self.assertAlmostEqual(own["f"]["solo@x.com"], own["rev_none"], places=3)
        # Everyone else's rate: 2 threads per 100 lines.
        self.assertAlmostEqual(own["rate_bin"][1], 2.0)
        mine = [r for r in rows if r.pid == 99]
        fi = sum(r.addr for r in mine) / sum(R.expected(r, m) for r in mine)
        others = [r for r in rows if r.pid == 0]
        fi0 = sum(r.addr for r in others) / sum(R.expected(r, m) for r in others)
        self.assertAlmostEqual(fi / fi0, 3.0, delta=0.15)
        # Reviewers within directories (2 levels): ui/a/ has only two reviewers, too few to list.
        self.assertEqual(R.dir_reviewers(rows), [])
        old = R.MIN_PEERS
        R.MIN_PEERS = 2
        try:
            dr = R.dir_reviewers(rows)
        finally:
            R.MIN_PEERS = old
        self.assertEqual([(d[0], d[2]) for d in dr], [("ui/a/", 2)])
        self.assertAlmostEqual(dr[0][1], 1.0, delta=0.01)

    def test_peer_rate_for_the_methodology(self):
        # A directory left under the minimum without the person falls back to its parent, then to
        # everyone's, however few.
        cells = lambda x: [list(x) for _ in R.BIN_LABELS]
        small = {"": cells([30, 3000, 30]), "ui/": cells([100, 5000, 150])}
        mine = lambda n: {"ui/": cells([n, 1000, 50])}
        self.assertEqual(R.MIN_RATE_CLS, 50)
        self.assertEqual(R.peer_rate(small, None, "ui/x/", 0), 3.0)
        self.assertEqual(R.peer_rate(small, mine(20), "ui/x/", 0), 2.5)
        self.assertEqual(R.peer_rate(small, mine(60), "ui/x/", 0), 1.0)

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

    def test_shard(self):
        # Two CLs, the second wholly in one directory. Threads [root, path (today's name), day,
        # addressed, directory], listed out of order; files that drew none aren't listed.
        c1 = dict(change_number=1007, closed_at=86400 * 20000, lines=12, prior=3,
                  units={"a/b/c/": 9, "a/": 3}, main="a/b/c/", flines={"a/b/c/x.cc": 6, "a/z.cc": 3},
                  revs=["a@x.com", "b@x.com"],
                  thr=[["r2", "a/b/c/x.cc", "2024-10-04", 1, "a/b/c/"],
                       ["r1", "/COMMIT_MSG", "2024-10-03", None, "a/b/c/"],
                       ["r3", "a/b/c/x.cc", "2024-10-04", 0, "a/b/c/"],
                       ["r4", "a/z.cc", "2024-10-05", 1, "a/"]])
        c2 = dict(change_number=1010, closed_at=86400 * 20003, lines=5, prior=4, units={"a/": 5}, main="a/",
                  flines={}, thr=[])
        sh = R.shard([c1, c2])
        self.assertEqual(sh["dirs"], ["a/b/c/", "a/"])
        self.assertEqual(sh["files"], ["/COMMIT_MSG", "a/b/c/x.cc", "a/z.cc"])
        self.assertEqual(sh["revs"], ["a@x.com", "b@x.com"])
        # [change number delta, day delta, lines, earlier commits, units, reviewers(, files)]; a file:
        # [file, lines there, threads, addressed], by name.
        self.assertEqual(sh["cls"], [[1007, 20000, 12, 3, [[0, 9], [1, 3]], [0, 1],
                                      [[0, 0, 1, 0], [1, 6, 2, 1], [2, 3, 1, 1]]],
                                     [3, 3, 5, 4, 1, []]])
        # The page puts a file's threads in its directory when that is a unit, else the first.
        self.assertEqual(R.page_dir("a/b/c/d/y.cc", {"a/b/c/": 1}, "x/"), "a/b/c/")
        self.assertEqual(R.page_dir("/COMMIT_MSG", {"a/": 1}, "x/"), "x/")


if __name__ == "__main__":
    unittest.main()
