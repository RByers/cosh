import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import balance_signals as S  # noqa: E402


class VoteParserTest(unittest.TestCase):
    def test_votes_removals_behalf_and_copies(self):
        entries = [
            (100, 7, "Update patch set 2\n\nPatch Set 2: Code-Review-1\n\nPatch-set: 2\nLabel: Code-Review=-1\n"),
            (200, 8, "Patch-set: 3\nLabel: Code-Review=+2, 1a2b3c4d-aaaa\n"
                     "Label: Code-Review=-1 Gerrit User 99 <99@abcd>\nLabel: Commit-Queue=+1"),
            (300, 7, "Patch-set: 3\nLabel: -Code-Review\n"
                     "Copied-Label: Code-Review=-1, ab12 Gerrit User 7 <7@x>"),
            (400, 9, "Patch-set: 4\nLabel: Code-Review=0"),
        ]
        self.assertEqual(S.parse_votes(entries), [
            (7, -1, 100, 2),       # the commit author votes
            (8, 2, 200, 3),        # a vote uuid suffix is ignored
            (99, -1, 200, 3),      # cast on behalf of another account
            (7, 0, 300, 3),        # removal; the Copied-Label line is skipped
            (9, 0, 400, 4),
        ])

    def test_no_votes(self):
        self.assertEqual(S.parse_votes([(1, 2, "Patch-set: 1\nLabel: Commit-Queue=+2")]), [])


class HelperTest(unittest.TestCase):
    def test_bucket_and_boot(self):
        self.assertEqual(S.bucket(4.5, S.TENURE), "3-6")
        self.assertEqual(S.bucket(200, S.TENURE), "120+")
        r = S.boot_ci([1.0] * 20)
        self.assertEqual((r["n"], r["mean"], r["lo"], r["hi"]), (20, 1.0, 1.0, 1.0))
        self.assertIsNone(S.boot_ci([1.0] * 3)["mean"])


if __name__ == "__main__":
    unittest.main()
