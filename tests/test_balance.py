import contextlib
import io
import os
import sqlite3
import subprocess
import tempfile
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
        self.assertEqual(balance.parse_votes(entries), [
            (7, -1, 100, 2),       # the commit author votes
            (8, 2, 200, 3),        # a vote uuid suffix is ignored
            (99, -1, 200, 3),      # cast on behalf of another account
            (7, 0, 300, 3),        # removal; the Copied-Label line is skipped
            (9, 0, 400, 4),
        ])

    def test_no_votes(self):
        self.assertEqual(balance.parse_votes([(1, 2, "Patch-set: 1\nLabel: Commit-Queue=+2")]), [])


class StageTimelineTest(unittest.TestCase):
    """stage_timeline against a tiny NoteDb-like repo: two CLs with meta refs,
    one without, and an unrelated ref."""

    def git(self, *args, msg=None):
        p = subprocess.run(["git", "--git-dir", self.repo, *args], input=msg, capture_output=True,
                           text=True, env={**os.environ, **self.ident})
        if p.returncode:
            raise AssertionError(f"git {args[0]} failed: {p.stderr}")
        return p.stdout.strip()

    def commit(self, ref, msgs, at, parent=None):
        parent = ["-p", parent] if parent else []
        for k, m in enumerate(msgs):
            self.ident["GIT_AUTHOR_DATE"] = self.ident["GIT_COMMITTER_DATE"] = f"@{at + k} +0000"
            sha = self.git("commit-tree", self.tree, *parent, msg=m)
            parent = ["-p", sha]
        self.git("update-ref", ref, sha)
        return sha

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.tmp.name, "notedb.git")
        self.ident = {"GIT_AUTHOR_NAME": "Gerrit User 7", "GIT_AUTHOR_EMAIL": "7@x",
                      "GIT_COMMITTER_NAME": "Gerrit", "GIT_COMMITTER_EMAIL": "g@x"}
        subprocess.run(["git", "init", "-q", "--bare", self.repo], check=True)
        self.tree = self.git("mktree", msg="")
        self.tip101 = self.commit("refs/meta/101", [
            "Create change\n\nPatch-set: 1\nCommit: " + "a" * 40 + "\n",
            "Review\n\nPatch-set: 1\nLabel: Code-Review=-1\n"], 1000)
        self.commit("refs/meta/102", ["Review\n\nPatch-set: 2\nLabel: Code-Review=+2\n"], 2000)
        self.commit("refs/heads/other", ["not a meta ref\n\nPatch-set: 1\nLabel: Code-Review=+1\n"], 3000)
        self.old = balance.NOTEDB
        balance.NOTEDB = self.repo
        self.db = balance.connect(os.path.join(self.tmp.name, "timeline.sqlite"), "timeline")

    def tearDown(self):
        balance.NOTEDB = self.old
        self.db.close()
        self.tmp.cleanup()

    def run_stage(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            balance.stage_timeline(self.db, numbers=[101, 102, 103], batch=2)
        return out.getvalue()

    def rows(self, sql):
        return self.db.execute(sql).fetchall()

    def test_votes_uploads_and_tip_keyed_resume(self):
        self.assertEqual(balance.meta_refs().keys(), {101, 102})
        self.run_stage()
        self.assertEqual(self.rows("SELECT change_number, voter, value, at, ps FROM votes ORDER BY 1"),
                         [(101, 7, -1, 1001, 1), (102, 7, 2, 2000, 2)])
        self.assertEqual(self.rows("SELECT change_number, ps, kind FROM uploads"), [(101, 1, "initial")])
        # 103 has no meta ref, so it is not marked done and is looked for again.
        done = dict(self.rows("SELECT change_number, tip FROM timeline_done"))
        self.assertEqual(done, balance.meta_refs())
        self.assertIn("0 CLs to read", self.run_stage())
        # A later NoteDb update moves 101's tip: only 101 is read again, and
        # its rows are replaced (the -1 is now a removal, a new patch set).
        self.commit("refs/meta/101", ["Create patch set 2\n\nUploaded patch set 2.\n\nPatch-set: 2\n"
                                      "Label: -Code-Review\n"], 1100, parent=self.tip101)
        self.assertIn("1 CLs to read (1 of them updated", self.run_stage())
        self.assertEqual(self.rows("SELECT change_number, voter, value, at FROM votes ORDER BY 1, 4"),
                         [(101, 7, -1, 1001), (101, 7, 0, 1100), (102, 7, 2, 2000)])
        self.assertEqual(self.rows("SELECT ps, kind FROM uploads WHERE change_number = 101 ORDER BY 1"),
                         [(1, "initial"), (2, "rework")])
        self.assertEqual(dict(self.rows("SELECT change_number, tip FROM timeline_done")), balance.meta_refs())

    def test_old_store_is_read_again(self):
        path = os.path.join(self.tmp.name, "old.sqlite")
        old = sqlite3.connect(path)
        old.executescript("CREATE TABLE timeline_done (change_number INTEGER PRIMARY KEY) STRICT;"
                          "INSERT INTO timeline_done VALUES (101), (102);"
                          "CREATE TABLE uploads (change_number INTEGER NOT NULL, ps INTEGER NOT NULL, "
                          "at INTEGER NOT NULL, uploader INTEGER NOT NULL, kind TEXT NOT NULL, sha TEXT, "
                          "PRIMARY KEY (change_number, ps)) STRICT, WITHOUT ROWID;"
                          "INSERT INTO uploads VALUES (101, 9, 1, 1, 'rework', NULL);")
        old.close()
        self.db.close()
        self.db = balance.connect(path, "timeline")
        # Every CL is read again (2 of them already read), its stale rows replaced.
        self.assertIn("2 CLs to read (2 of them updated", self.run_stage())
        self.assertEqual(self.rows("SELECT count(*) FROM votes"), [(2,)])
        self.assertEqual(self.rows("SELECT change_number, ps FROM uploads"), [(101, 1)])
        self.assertIn("0 CLs to read", self.run_stage())

    def test_stage_files_hold_only_their_tables(self):
        tables = {r[0] for r in self.rows("SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertEqual(tables, {"uploads", "attention", "votes", "timeline_done"})


class ClFactsTest(unittest.TestCase):
    """cl_facts and cl_dirs: the part of `cl` the Feedback Index reads without balance.sqlite."""

    def test_facts_and_dirs(self):
        ddb, gdb = sqlite3.connect(":memory:"), sqlite3.connect(":memory:")
        ddb.executescript("""
            CREATE TABLE accounts (account_id INTEGER, email TEXT);
            CREATE TABLE changes (change_number INTEGER, owner_account INTEGER, status TEXT, created_at TEXT,
              closed_at TEXT, close_week TEXT, insertions INTEGER, deletions INTEGER, patchsets INTEGER,
              is_bot_owned INTEGER, project TEXT, branch TEXT);
            INSERT INTO accounts VALUES (1, 'A@chromium.org');
            INSERT INTO changes VALUES
              (20, 1, 'MERGED', '2026-11-02 10:00:00', '2026-11-03 10:00:00', '2026-W45', 5, 2, 3, 0, 'chromium/src', 'main'),
              (10, 1, 'ABANDONED', '2026-11-02 10:00:00', NULL, NULL, 1, 0, 1, 0, 'chromium/src', 'main'),
              (30, 1, 'MERGED', '2026-11-02 10:00:00', '2026-11-03 10:00:00', '2026-W45', 1, 1, 1, 1, 'chromium/src', 'main'),
              (40, 1, 'MERGED', '2026-11-02 10:00:00', '2026-11-03 10:00:00', '2026-W45', 1, 1, 1, 0, 'chromium/src', 'other');
        """)
        gdb.executescript("""
            CREATE TABLE gcommits (commit_id INTEGER, change_number INTEGER, sha TEXT, files INTEGER, ins INTEGER,
              dels INTEGER, reverts_sha TEXT, is_reland INTEGER, landed_at INTEGER);
            CREATE TABLE paths (path_id INTEGER, path TEXT);
            CREATE TABLE gfiles (commit_id INTEGER, path_id INTEGER, ins INTEGER, dels INTEGER);
            INSERT INTO gcommits VALUES (7, 20, 'abc', 2, 4, 2, NULL, 0, 100), (8, NULL, 'def', 1, 0, 4, 'abc', 0, 150),
              (9, 10, 'ghi', 1, 1, 0, NULL, 0, 90);
            INSERT INTO paths VALUES (1, 'a/b/c/d.cc'), (2, 'a/b/c/e/f.cc'), (3, 'top.txt');
            INSERT INTO gfiles VALUES (7, 1, 3, 1), (7, 2, 1, 1), (8, 3, 0, 4), (9, 3, 1, 0);
        """)
        rows, by_cid = balance.cl_facts(ddb, gdb)
        facts = [dict(zip(balance.CL_FACTS, r)) for r in rows]
        self.assertEqual([f["change_number"] for f in facts], [10, 20])      # sorted, bots and other branches out
        self.assertEqual(facts[1], dict(change_number=20, owner=1, owner_email="A@chromium.org", status="MERGED",
                                        created_at=ts("2026-11-02 10:00"), closed_at=ts("2026-11-03 10:00"),
                                        close_week="2026-W45", ins=5, dels=2, patchsets=3, sha="abc", files=2,
                                        git_lines=6, is_revert=0, is_reland=0, reverted_at=150))
        self.assertIsNone(facts[0]["sha"])               # not merged: no landed commit
        self.assertEqual(by_cid, {7: 20, 9: 10})
        self.assertEqual(dict(balance.cl_dirs(gdb, by_cid)), {(20, "a/b/c/"): [2, 6], (10, "(root)/"): [1, 1]})
        self.assertEqual(dict(balance.cl_dirs(gdb, by_cid, {20})), {(20, "a/b/c/"): [2, 6]})


class HoursTest(unittest.TestCase):
    def test_union(self):
        self.assertEqual(balance.union_hours([(0, 3600), (1800, 7200), (10800, 14400)], 0, 99999), 3.0)
        self.assertEqual(balance.union_hours([(0, 7200)], 3600, 99999), 1.0)

    def test_weekdays(self):
        # 2026-11-06 is a Friday: Friday 12:00 to Monday 12:00 has 24 weekday hours.
        self.assertEqual(balance.weekday_seconds(ts("2026-11-06 12:00"), ts("2026-11-09 12:00")), 24 * 3600)


if __name__ == "__main__":
    unittest.main()
