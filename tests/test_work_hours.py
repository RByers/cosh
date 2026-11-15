import unittest
from datetime import datetime, timezone

from cosh import work_hours as W


def ts(s):
    return int(datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc).timestamp())


def hours(*hs):
    c = [0] * 24
    for h in hs:
        c[h] += 1
    return c


class WorkHoursTest(unittest.TestCase):
    def test_fit(self):
        self.assertIsNone(W.fit([0] * 24))
        # 13:00 .. 20:00 UTC holds all of these: a US East Coast day.
        self.assertEqual(W.fit(hours(13, 14, 15, 18, 20)), 13)
        # Wrapping midnight: 22:00 .. 05:00 UTC.
        self.assertEqual(W.fit(hours(22, 23, 0, 3, 5)), 22)
        # One event sits in the middle of its window, not at an edge.
        self.assertIn(W.fit(hours(10)), range(5, 9))

    def test_offset_and_region(self):
        self.assertEqual(W.offset_s(13), -4 * 3600)          # 09:00 local = 13:00 UTC: UTC-4
        self.assertEqual(W.offset_s(0), 9 * 3600)            # Tokyo
        self.assertEqual(W.offset_s(22), 11 * 3600)          # Sydney in summer
        self.assertEqual([W.region(s) for s in (13, 17, 7, 9, 0, 22, 4)],
                         ["Americas", "Americas", "EMEA", "EMEA", "APAC", "APAC", "APAC"])

    def test_overlap(self):
        self.assertEqual(W.overlap_h(13, 13), 8)
        self.assertEqual(W.overlap_h(13, 16), 5)
        self.assertEqual(W.overlap_h(22, 2), 4)              # across midnight
        self.assertEqual(W.overlap_h(13, 1), 0)

    def test_work_seconds(self):
        # A US East Coast window (13:00 .. 21:00 UTC): sent Monday 19:00 UTC, answered Tuesday 15:00 UTC.
        self.assertEqual(W.work_seconds(ts("2026-11-02 19:00"), ts("2026-11-03 15:00"), 13), 4 * 3600)
        # Friday 20:00 to Monday 14:00 UTC: one hour on Friday, one on Monday; the weekend doesn't count.
        self.assertEqual(W.work_seconds(ts("2026-11-06 20:00"), ts("2026-11-09 14:00"), 13), 2 * 3600)
        # Tokyo (00:00 .. 08:00 UTC is 09:00 .. 17:00 local): Sunday 23:00 UTC to Monday 02:00 UTC is
        # Monday morning there, so two hours count; Friday 23:00 UTC is Saturday there, so none do.
        self.assertEqual(W.work_seconds(ts("2026-11-08 23:00"), ts("2026-11-09 02:00"), 0), 2 * 3600)
        self.assertEqual(W.work_seconds(ts("2026-11-06 23:00"), ts("2026-11-07 07:00"), 0), 0)
        # Outside the window entirely.
        self.assertEqual(W.work_seconds(ts("2026-11-03 02:00"), ts("2026-11-03 06:00"), 13), 0)

    def test_windows(self):
        busy = hours(*([14] * 12))
        w = W.Windows({(1, "2026Q2"): busy, (1, "2026Q3"): hours(2), (2, "2026Q4"): hours(3)})
        s, basis = w.start(1, "2026Q2")
        self.assertEqual((W.overlap_h(s, 14) > 0, basis), (True, "quarter"))
        # Too little in Q3: fitted to everything up to Q3, which the busy Q2 dominates.
        self.assertEqual(w.start(1, "2026Q3"), (s, "history"))
        # Nothing up to Q2 for account 2: fitted to all it did.
        self.assertEqual(w.start(2, "2026Q2")[1], "history")
        self.assertEqual(w.start(3, "2026Q2"), (None, None))
        self.assertEqual(w.at(1, ts("2026-05-01 00:00")), s)
        self.assertEqual({(a, q) for a, q, *_ in w.rows()}, {(1, "2026Q2"), (1, "2026Q3"), (2, "2026Q2"), (2, "2026Q4")})


if __name__ == "__main__":
    unittest.main()
