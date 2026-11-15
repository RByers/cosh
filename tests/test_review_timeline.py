import contextlib
import io
import json
import os
import sqlite3
import subprocess
import tempfile
import unittest
import zlib
from unittest import mock
from datetime import datetime, timezone

from cosh import review_timeline as rt


def ts(s):
    return int(datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc).timestamp())


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
        ups, spans = rt.parse_meta_log(entries)
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
        self.assertEqual(rt.parse_votes(entries), [
            (7, -1, 100, 2),       # the commit author votes
            (8, 2, 200, 3),        # a vote uuid suffix is ignored
            (99, -1, 200, 3),      # cast on behalf of another account
            (7, 0, 300, 3),        # removal; the Copied-Label line is skipped
            (9, 0, 400, 4),
        ])

    def test_no_votes(self):
        self.assertEqual(rt.parse_votes([(1, 2, "Patch-set: 1\nLabel: Commit-Queue=+2")]), [])


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
        self.old = rt.NOTEDB
        rt.NOTEDB = self.repo
        self.db = rt.connect(os.path.join(self.tmp.name, "timeline.sqlite"))

    def tearDown(self):
        rt.NOTEDB = self.old
        self.db.close()
        self.tmp.cleanup()

    def run_stage(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rt.stage_timeline(self.db, numbers=[101, 102, 103], batch=2)
        return out.getvalue()

    def rows(self, sql):
        return self.db.execute(sql).fetchall()

    def test_votes_uploads_and_tip_keyed_resume(self):
        self.assertEqual(rt.meta_refs().keys(), {101, 102})
        self.run_stage()
        self.assertEqual(self.rows("SELECT change_number, voter, value, at, ps FROM votes ORDER BY 1"),
                         [(101, 7, -1, 1001, 1), (102, 7, 2, 2000, 2)])
        self.assertEqual(self.rows("SELECT change_number, ps, kind FROM uploads"), [(101, 1, "initial")])
        # 103 has no meta ref, so it is not marked done and is looked for again.
        done = dict(self.rows("SELECT change_number, tip FROM timeline_done"))
        self.assertEqual(done, rt.meta_refs())
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
        self.assertEqual(dict(self.rows("SELECT change_number, tip FROM timeline_done")), rt.meta_refs())

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
        self.db = rt.connect(path)
        # Every CL is read again (2 of them already read), its stale rows replaced.
        self.assertIn("2 CLs to read (2 of them updated", self.run_stage())
        self.assertEqual(self.rows("SELECT count(*) FROM votes"), [(2,)])
        self.assertEqual(self.rows("SELECT change_number, ps FROM uploads"), [(101, 1)])
        self.assertIn("0 CLs to read", self.run_stage())

    def test_tables(self):
        tables = {r[0] for r in self.rows("SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertEqual(tables, {"uploads", "attention", "votes", "timeline_done", "listing_votes", "listing_done",
                                  "meta"})

    def test_code_change_reads_every_cl_again(self):
        self.run_stage()
        self.db.execute("UPDATE votes SET value = 9")          # as if older code had made them
        self.db.commit()
        self.assertIn("0 CLs to read", self.run_stage())
        self.assertEqual(self.rows("SELECT DISTINCT value FROM votes"), [(9,)])
        with mock.patch.object(rt, "WALK_VERSION", 2):
            out = self.run_stage()
            self.assertIn("code that reads meta refs changed", out)
            self.assertIn("2 CLs to read (0 of them updated", out)
            self.assertEqual(self.rows("SELECT change_number, value FROM votes ORDER BY 1"), [(101, -1), (102, 2)])
            self.assertIn("0 CLs to read", self.run_stage())
            self.assertEqual(self.rows("SELECT k, v FROM meta"), [("code_fp:walk", rt.walk_fingerprint())])


class ListingTest(unittest.TestCase):
    def test_votes_standing_on_a_listed_cl(self):
        change = {"labels": {"Code-Review": {"all": [
            {"_account_id": 7, "value": 1, "date": "2018-03-05 10:00:00.000000000"},
            {"_account_id": 8, "value": 0},                      # a reviewer who didn't vote
            {"_account_id": 9, "value": -1, "date": "2018-03-05 11:00:00.000000000"}]}}}
        self.assertEqual(rt.listing_votes(change), [(7, 1, ts("2018-03-05 10:00")), (9, -1, ts("2018-03-05 11:00"))])
        self.assertEqual(rt.listing_votes({}), [])

    def test_only_cls_without_comments_and_only_new_listings(self):
        raw = sqlite3.connect(":memory:")
        raw.executescript("""
            CREATE TABLE responses (host TEXT, kind TEXT, key TEXT, http_status INTEGER, body_zlib BLOB, body_sha256 TEXT);
            CREATE TABLE week_changes (window_key TEXT);
            INSERT INTO week_changes VALUES ('w1');""")
        vote = {"Code-Review": {"all": [{"_account_id": 7, "value": 1, "date": "2018-03-05 10:00:00.000000000"}]}}
        body = [dict(_number=1, project="chromium/src", owner={"email": "a@chromium.org"}, labels=vote),
                dict(_number=2, project="chromium/src", owner={"email": "a@chromium.org"}, labels=vote,
                     total_comment_count=3),
                dict(_number=3, project="chromium/src", owner={"tags": ["SERVICE_USER"]}, labels=vote),
                dict(_number=4, project="other", owner={"email": "a@chromium.org"}, labels=vote)]
        raw.execute("INSERT INTO responses VALUES ('h', 'list_window', 'w1', 200, ?, 'sha1')",
                    (zlib.compress(json.dumps(body).encode()),))
        db = rt.connect(":memory:")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rt.stage_listing(db, raw)
            rt.stage_listing(db, raw)
        self.assertEqual(db.execute("SELECT * FROM listing_votes").fetchall(), [(1, 7, 1, ts("2018-03-05 10:00"))])
        self.assertIn("listing: 1 listings to read (0 done)", out.getvalue())
        self.assertIn("listing: 0 listings to read (1 done)", out.getvalue())
        db.execute("UPDATE listing_votes SET value = 9")
        with contextlib.redirect_stdout(io.StringIO()):
            rt.stage_listing(db, raw)
        self.assertEqual(db.execute("SELECT value FROM listing_votes").fetchall(), [(9,)])
        out = io.StringIO()
        with contextlib.redirect_stdout(out), mock.patch.object(rt, "LISTING_VERSION", 2):
            rt.stage_listing(db, raw)
        self.assertIn("listing: 1 listings to read (0 done)", out.getvalue())
        self.assertEqual(db.execute("SELECT * FROM listing_votes").fetchall(), [(1, 7, 1, ts("2018-03-05 10:00"))])


class ReviewersTest(unittest.TestCase):
    def test_rows(self):
        mon = ts("2026-11-02 00:00")                 # a Monday
        cls = [(1, 10, mon, mon + 8 * 86400), (2, 10, mon, None)]
        attention = {1: [(7, mon + 3600, mon + 7200), (7, mon + 5400, mon + 10800),      # overlap: one 2 h turn
                         (7, mon + 86400, mon + 88200),                                 # a second turn, 0.5 h
                         (8, mon + 4 * 86400, mon + 7 * 86400),                         # Friday to Monday
                         (11, mon + 7 * 86400, mon + 8 * 86400),                        # still open at the close
                         (10, mon, mon + 3600), (99, mon, mon + 3600)],                 # the owner, a bot
                     2: [(7, mon + 100, mon + 3700)]}
        responses = {1: {7: mon + 9000, 9: mon + 500, 10: mon + 1, 99: mon + 2}}
        rows = rt.reviewer_rows(cls, {99}, attention, responses)
        self.assertEqual(rows, [
            (1, 7, mon + 3600, mon + 9000, 2.5, 2.5, 2, 2.5),
            (1, 8, mon + 4 * 86400, None, 72.0, 24.0, 1, 24.0),   # the weekend is left out
            (1, 9, None, mon + 500, None, None, None, None),      # answered without being in the attention set
            (1, 11, mon + 7 * 86400, None, 24.0, 24.0, 0, 0.0),   # the CL closed without waiting on this turn
            (2, 7, mon + 100, None, 1.0, 1.0, 0, 0.0),            # an open CL: to its last interval's end, still open
        ])

    def test_stage(self):
        ddb = sqlite3.connect(":memory:")
        ddb.executescript("""
            CREATE TABLE accounts (account_id INTEGER, is_bot INTEGER);
            CREATE TABLE changes (change_number INTEGER, owner_account INTEGER, created_at TEXT, closed_at TEXT,
              is_bot_owned INTEGER, project TEXT, branch TEXT);
            CREATE TABLE comments (change_number INTEGER, account_id INTEGER, written_at TEXT, after_close INTEGER);
            INSERT INTO accounts VALUES (7, 0), (99, 1);
            INSERT INTO changes VALUES (1, 10, '2026-11-02 00:00:00', '2026-11-03 00:00:00', 0, 'chromium/src', 'main'),
                                       (2, 10, '2026-11-02 00:00:00', '2026-11-03 00:00:00', 0, 'chromium/src', 'main');
            INSERT INTO comments VALUES (1, 7, '2026-11-02 05:00:00', 0), (1, 7, '2026-11-02 03:00:00', 0),
                                        (1, 8, '2026-11-04 00:00:00', 1), (1, 99, '2026-11-02 01:00:00', 0);
        """)
        db = rt.connect(":memory:")
        mon = ts("2026-11-02 00:00")
        db.executescript(f"""
            INSERT INTO timeline_done VALUES (1, 'tip');
            INSERT INTO votes VALUES (1, 7, 1, {mon + 7200}, 1), (1, 8, 0, {mon + 100}, 1), (1, 6, 2, {mon + 200}, 1);
            INSERT INTO listing_votes VALUES (1, 5, 1, {mon + 50}), (2, 5, 1, {mon + 60});
            INSERT INTO attention VALUES (1, 7, {mon + 3600}, {mon + 7200});
        """)
        with contextlib.redirect_stdout(io.StringIO()):
            rt.stage_reviewers(db, ddb)
        self.assertEqual(db.execute("SELECT * FROM cl_reviewers ORDER BY 1, 2").fetchall(), [
            (1, 6, None, mon + 200, None, None, None, None),
            (1, 7, mon + 3600, mon + 7200, 1.0, 1.0, 1, 1.0),      # the vote comes before the comments
            # 8 only removed a vote and commented after the close; 99 is a bot;
            # 1 has a meta ref, so its listing votes are not used
            (2, 5, None, mon + 60, None, None, None, None),
        ])


if __name__ == "__main__":
    unittest.main()
