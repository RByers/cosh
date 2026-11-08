import unittest
from collections import Counter
from datetime import datetime, timezone

from cosh import balance


def ts(s):
    return int(datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc).timestamp())


class CompareTest(unittest.TestCase):
    def test_rebase_is_no_change(self):
        # Same added/removed lines, different positions (as after a rebase).
        d0 = {b"a.cc": (Counter({1: 1, 2: 1}), Counter({3: 1}))}
        d1 = {b"a.cc": (Counter({2: 1, 1: 1}), Counter({3: 1}))}
        self.assertEqual(balance.compare(d0, d1), (3, 3, 0, 0, 0, 0))

    def test_edits_added_and_dropped_files(self):
        d0 = {b"a.cc": (Counter({1: 1}), Counter()), b"old.cc": (Counter({9: 2}), Counter())}
        d1 = {b"a.cc": (Counter({1: 1, 2: 1}), Counter()), b"new.cc": (Counter({5: 1}), Counter({6: 1}))}
        # a.cc: one line more; new.cc adds 2; old.cc drops 2.
        self.assertEqual(balance.compare(d0, d1), (3, 4, 5, 1, 1, 1))


class MetaLogTest(unittest.TestCase):
    def test_uploads_and_attention(self):
        add = ('Attention: {"person_ident":"Gerrit User 7 <7@x>","operation":"ADD","reason":"r"}')
        rem = ('Attention: {"person_ident":"Gerrit User 7 <7@x>","operation":"REMOVE","reason":"r"}')
        entries = [
            (100, 1, "Create change\n\nPatch-set: 1\nCommit: " + "a" * 40),
            (200, 1, "Update patch set 1\n\nPatch-set: 1\n" + add),
            (500, 7, "Update patch set 1\n\nPatch Set 1:\n\n(1 comment)\n\nPatch-set: 1\n" + rem),
            (600, 1, "Create patch set 2\n\nUploaded patch set 2: Patch Set 1 was rebased.\n\n"
                     "Patch-set: 2\nCommit: " + "b" * 40),
            (700, 1, "Create patch set 3\n\nUploaded patch set 3.\n\nPatch-set: 3\n" + add),
            (900, 1, "Update patch set 3\n\nStatus: merged\nPatch-set: 3"),
        ]
        ups, spans = balance.parse_meta_log(entries)
        self.assertEqual([(ps, k) for ps, _, _, k, _ in ups], [(1, "initial"), (2, "rebase"), (3, "rework")])
        self.assertEqual(ups[0][4], "a" * 40)
        # Closed at 500; the second ADD stays open until the merge at 900.
        self.assertEqual(sorted(spans), [(7, 200, 500), (7, 700, 900)])


class HoursTest(unittest.TestCase):
    def test_union(self):
        self.assertEqual(balance.union_hours([(0, 3600), (1800, 7200), (10800, 14400)], 0, 99999), 3.0)
        self.assertEqual(balance.union_hours([(0, 7200)], 3600, 99999), 1.0)

    def test_weekdays(self):
        # 2026-11-06 is a Friday: Friday 12:00 to Monday 12:00 has 24 weekday hours.
        self.assertEqual(balance.weekday_seconds(ts("2026-11-06 12:00"), ts("2026-11-09 12:00")), 24 * 3600)


if __name__ == "__main__":
    unittest.main()
