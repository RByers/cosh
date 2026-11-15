"""Author/reviewer balance data (docs/balance.md), in data/private/balance.sqlite.

Offline only: reads commits.sqlite (main's history, cosh/commits.py), the
patch-set git repo, review-timeline.sqlite and reviews.sqlite, and fetches
nothing. Every git command runs with GIT_NO_LAZY_FETCH=1. balance.sqlite is
rebuildable: delete it and rerun.

Each CL's NoteDb timeline (uploads, attention set, votes, and each
reviewer's wait) is not a balance stage: `python3 -m cosh.review_timeline`
writes it (cosh/review_timeline.py), the Review Load page reads it too,
and the stages here consume it. Run it first.

Stages (each resumable):
  interdiff  per reviewed CL: how much its diff changed between the first
             reviewed patch set and the final one, comparing diffs, not files,
             so rebases don't count (data/private/balance-interdiff.sqlite)
  cl         one row per CL joining the timeline and the interdiff with review
             threads and the landed commits (commits.sqlite's commits and
             commit_files with commit_id > 0: main since 2017-01-01)

  python3 -m cosh.balance interdiff|cl [--db PATH]

db_path("git") is commits.sqlite, db_path("timeline") is
review-timeline.sqlite. The per-CL scripts read commits.sqlite's commits and
commit_files with commit_id > 0 (since 2017-01-01), and paths.
"""

import argparse
import os
import sqlite3
import subprocess
import time

from . import codefp, review_timeline, store
from .cl_facts import CL_FACTS, cl_dirs, cl_facts, epoch, iter_cl_dirs, iter_cl_facts  # noqa: F401 (moved there)
from .commits import HISTORY_SINCE, MAX_LINES, diff_lines  # noqa: F401 (moved there)
from .review_timeline import union_spans, weekday_seconds  # noqa: F401 (moved there)

SHARED = os.path.expanduser("~/projects/shared/chromium")
PATCHSETS = os.path.join(store.DATA_DIR, "git", "chromium-patchsets.git")
ENV = {**os.environ, "GIT_NO_LAZY_FETCH": "1"}
SINCE = "2017-01-01"     # commit_id > 0 in commits.sqlite starts here

# Each stage's file holds only its own tables; `cl` makes its own (CL_SCHEMA).
SCHEMA = {}
SCHEMA["interdiff"] = """
-- Per reviewed CL: the first reviewed patch set against the final one.
CREATE TABLE IF NOT EXISTS interdiff (
  change_number INTEGER PRIMARY KEY,
  seen_ps       INTEGER NOT NULL,
  final_ps      INTEGER NOT NULL,
  lines_seen    INTEGER,               -- changed lines in the reviewed patch set's diff
  lines_final   INTEGER,
  lines_changed INTEGER,               -- changed lines present in one diff but not the other
  files_changed INTEGER,               -- files whose diff differs
  files_added   INTEGER,
  files_dropped INTEGER,
  status        TEXT NOT NULL          -- ok | missing (patch sets not local) | too_big
) STRICT;
-- The stage's code fingerprint ('code_fp:interdiff', cosh/codefp.py).
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT) STRICT;
"""


def db_path(stage):
    """Each stage writes its own file; `cl` reads them all and writes
    balance.sqlite. COSH_BALANCE_<STAGE> (e.g. COSH_BALANCE_INTERDIFF) points
    one stage at another file, for writers and readers alike. "git" is
    commits.sqlite (cosh/commits.py, $COSH_COMMITS_DB) and "timeline" is
    review-timeline.sqlite (cosh/review_timeline.py, $COSH_REVIEW_TIMELINE)."""
    if os.environ.get(f"COSH_BALANCE_{stage.upper()}"):
        return os.environ[f"COSH_BALANCE_{stage.upper()}"]
    if stage == "git":
        from . import commits
        return commits.db_path()
    if stage == "timeline":
        return review_timeline.db_path()
    return os.path.join(store.DATA_DIR, "balance.sqlite" if stage == "cl" else f"balance-{stage}.sqlite")


def connect(path, stage):
    db = sqlite3.connect(path, timeout=60)
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript(SCHEMA.get(stage, ""))
    return db


def git_popen(git_dir, *args, stdin=None):
    return subprocess.Popen(["git", "--git-dir", git_dir, *args], stdout=subprocess.PIPE,
                            stdin=subprocess.PIPE if stdin else None, env=ENV)


# ---------------------------------------------------------- interdiff stage



def first_review_times():
    """{CL: unix time of its first substantive review}: the first inline
    reviewer comment (a file or the commit message) by a human non-owner
    before the CL closed, else the root of the first reviewer thread the
    owner answered. A lone "LGTM" is not substantive review."""
    d = sqlite3.connect(f"file:{os.path.join(store.DATA_DIR, store.DERIVED_FILE)}?mode=ro", uri=True)
    q = """SELECT c.change_number, min(c.written_at)
           FROM comments c JOIN accounts a ON a.host = c.host AND a.account_id = c.account_id
           WHERE a.is_bot = 0 AND c.after_close = 0 AND c.path != '/PATCHSET_LEVEL' GROUP BY c.change_number"""
    out = {n: epoch(t) for n, t in d.execute(q)}
    q = """SELECT t.change_number, min(c.written_at)
           FROM threads t JOIN comments c ON c.host = t.host AND c.change_number = t.change_number
                AND c.comment_id = t.root_uuid
           JOIN accounts a ON a.host = t.host AND a.account_id = t.root_account
           WHERE a.is_bot = 0 AND t.last_owner_reply_at IS NOT NULL GROUP BY t.change_number"""
    for n, t in d.execute(q):
        out.setdefault(n, epoch(t))
    return out


def compare(d0, d1):
    """Lines and files that differ between two patch sets' diffs."""
    changed = fchanged = 0
    for path in d0.keys() | d1.keys():
        a, b = d0.get(path), d1.get(path)
        if a is None or b is None:
            continue
        x = sum(((a[0] - b[0]) + (b[0] - a[0]) + (a[1] - b[1]) + (b[1] - a[1])).values())
        changed += x
        fchanged += x > 0
    added = d1.keys() - d0.keys()
    dropped = d0.keys() - d1.keys()
    changed += sum(sum(d1[p][0].values()) + sum(d1[p][1].values()) for p in added)
    changed += sum(sum(d0[p][0].values()) + sum(d0[p][1].values()) for p in dropped)
    size = lambda d: sum(sum(a.values()) + sum(m.values()) for a, m in d.values())
    return size(d0), size(d1), changed, fchanged, len(added), len(dropped)


def stage_interdiff(db, batch=300, shard=(0, 1)):
    tl = sqlite3.connect(f"file:{db_path('timeline')}?mode=ro", uri=True)
    fetched = os.path.join(PATCHSETS, "cosh-fetched.txt")
    with open(fetched) as f:
        have = {int(x) for x in f.read().split() if x.isdigit()}
    first = first_review_times()
    if codefp.check(db, "interdiff", interdiff_fingerprint(), reset_interdiff) == "changed":
        print("interdiff: its code changed: every CL is compared again", flush=True)
    done = {r[0] for r in db.execute("SELECT change_number FROM interdiff")}
    ups = {}
    for n, ps, at, sha in tl.execute("SELECT change_number, ps, at, sha FROM uploads ORDER BY change_number, ps"):
        ups.setdefault(n, []).append((ps, at, sha))
    tl.close()
    todo = sorted(n for n in have & first.keys() & ups.keys() if n not in done and n % shard[1] == shard[0])
    print(f"interdiff: {len(todo):,} CLs to compare ({len(done):,} done)", flush=True)
    t0 = time.time()
    for i in range(0, len(todo), batch):
        db.executemany("INSERT OR REPLACE INTO interdiff VALUES (?,?,?,?,?,?,?,?,?,?)",
                       interdiff_rows(todo[i:i + batch], ups, first))
        db.commit()
        k = i + batch
        print(f"interdiff: {min(k, len(todo)):,}/{len(todo):,} ({k / (time.time() - t0):.0f} CLs/s)", flush=True)


# What interdiff's rows are a function of besides their inputs
# (cosh/codefp.py): when it changes, every row is deleted and compared again.
# Bump the version for a change the fingerprint can't see.
INTERDIFF_VERSION = 1


def interdiff_fingerprint():
    return codefp.fingerprint(INTERDIFF_VERSION, interdiff_rows, compare, first_review_times, diff_lines,
                              MAX_LINES, epoch)


def reset_interdiff(db):
    db.execute("DELETE FROM interdiff")


def interdiff_rows(cls, ups, first):
    """interdiff's rows for the CLs `cls`, from their uploads
    {CL: [(ps, at, sha)]} and first review times."""
    rows, pairs = [], {}
    for n in cls:
        u = ups[n]
        final = u[-1]
        seen = max((x for x in u if x[1] <= first[n]), default=u[0])
        if seen[0] == final[0]:
            rows.append((n, seen[0], final[0], None, None, 0, 0, 0, 0, "ok"))
        elif seen[2] and final[2]:
            pairs[n] = (seen, final)
        else:
            rows.append((n, seen[0], final[0], None, None, None, None, None, None, "missing"))
    diffs = diff_lines(PATCHSETS, [x[2] for s, f in pairs.values() for x in (s, f)])
    for n, (seen, final) in pairs.items():
        d0, d1 = diffs.get(seen[2], {}), diffs.get(final[2], {})
        if seen[2] not in diffs or final[2] not in diffs:
            rows.append((n, seen[0], final[0], None, None, None, None, None, None, "missing"))
        elif d0 is None or d1 is None:
            rows.append((n, seen[0], final[0], None, None, None, None, None, None, "too_big"))
        else:
            rows.append((n, seen[0], final[0], *compare(d0, d1), "ok"))
    return rows


# ----------------------------------------------------------------- cl stage

CL_SCHEMA = """
DROP TABLE IF EXISTS cl;
CREATE TABLE cl (
  change_number   INTEGER PRIMARY KEY,
  owner           INTEGER NOT NULL,
  owner_email     TEXT,
  status          TEXT NOT NULL,
  created_at      INTEGER NOT NULL,
  closed_at       INTEGER,
  close_week      TEXT,
  ins             INTEGER, dels INTEGER,          -- Gerrit's, final patch set (renames detected)
  patchsets       INTEGER,
  sha             TEXT,                           -- landed commit on main
  files           INTEGER,                        -- of the landed commit
  git_lines       INTEGER,                        -- ins + dels of the landed commit (no renames)
  is_revert       INTEGER, is_reland INTEGER,
  reverted_at     INTEGER,                        -- first commit reverting the landed commit
  comments        INTEGER, chars INTEGER, reviewers INTEGER,
  threads         INTEGER, addressed INTEGER, pending INTEGER,
  first_review_at INTEGER,                        -- first substantive review: an inline reviewer comment,
                                                  -- or a reviewer thread the owner answered; NULL if none
  sent_at         INTEGER,                        -- first time a non-owner entered the attention set
                                                  -- (review-timeline's cl_reviewers.asked_at)
  rework_after    INTEGER,                        -- rework uploads after first_review_at
  rounds          INTEGER,                        -- owner rework uploads after sent_at that follow a
                                                  -- new reviewer-started thread
  reviewer_wait_h REAL,                           -- hours some non-owner human was in the attention set
  reviewer_wait_wd_h REAL,                        -- the same, Saturdays and Sundays (UTC) left out
  owner_wait_h    REAL,                           -- hours the owner was
  seen_ps INTEGER, lines_seen INTEGER, lines_final INTEGER, lines_changed INTEGER,
  files_changed INTEGER, files_added INTEGER, interdiff_status TEXT
) STRICT;
DROP TABLE IF EXISTS cl_attention;
CREATE TABLE cl_attention (       -- each non-owner human's attention-set hours on a CL
                                  -- (copied from review-timeline's cl_reviewers)
  change_number INTEGER NOT NULL,
  account_id    INTEGER NOT NULL,
  hours         REAL NOT NULL,
  weekday_hours REAL NOT NULL,
  PRIMARY KEY (change_number, account_id)
) STRICT, WITHOUT ROWID;
DROP TABLE IF EXISTS cl_dirs;
CREATE TABLE cl_dirs (            -- landed commit's lines per directory (3 levels)
  change_number INTEGER NOT NULL,
  dir           TEXT NOT NULL,
  files         INTEGER NOT NULL,
  lines         INTEGER NOT NULL,
  PRIMARY KEY (change_number, dir)
) STRICT, WITHOUT ROWID;
"""


def union_hours(spans, lo, hi):
    spans = sorted((max(s, lo), min(e, hi)) for s, e in spans if min(e, hi) > max(s, lo))
    tot, cur_s, cur_e = 0, None, None
    for s, e in spans:
        if cur_e is None or s > cur_e:
            if cur_e is not None:
                tot += cur_e - cur_s
            cur_s, cur_e = s, e
        else:
            cur_e = max(cur_e, e)
    if cur_e is not None:
        tot += cur_e - cur_s
    return tot / 3600


class _ByCL:
    """The rows of a query ordered by change number (its first column),
    handed out one CL at a time to a caller going through CLs in increasing
    order: a merge join, so no table is held in memory."""

    def __init__(self, cur):
        self.it = iter(cur)
        self.row = next(self.it, None)

    def take(self, n):
        out = []
        while self.row is not None and self.row[0] < n:
            self.row = next(self.it, None)
        while self.row is not None and self.row[0] == n:
            out.append(self.row)
            self.row = next(self.it, None)
        return out


def stage_cl(db):
    db.executescript(CL_SCHEMA)
    derived = os.path.join(store.DATA_DIR, store.DERIVED_FILE)
    # Every input is read in change-number order on its own connection and
    # merged with the CLs one at a time (_ByCL): about 1.1M CLs and their
    # comments, threads, uploads and attention never sit in memory together.
    rd = sqlite3.connect(f"file:{derived}?mode=ro", uri=True)
    for st in ("timeline", "interdiff"):
        rd.execute(f"ATTACH 'file:{db_path(st)}?mode=ro' AS {st[0]}{st[1:3]}")
    gdb = sqlite3.connect(f"file:{db_path('git')}?mode=ro", uri=True)
    print("cl: loading", flush=True)
    bots = {r[0] for r in rd.execute("SELECT account_id FROM accounts WHERE is_bot = 1")}
    facts, by_cid = iter_cl_facts(rd, gdb)
    # Review from reviews.sqlite, as summarize counts it (human non-owners);
    # the active classifier's addressed labels joined in SQLite.
    from . import classify
    lp = classify.labels_path(store.DATA_DIR)
    label, active = "NULL", None
    if os.path.exists(lp):
        rd.execute(f"ATTACH 'file:{lp}?mode=ro' AS lab")
        active = classify.active_classifier(
            sqlite3.connect(f"file:{lp}?mode=ro", uri=True))
        if active:
            label = "l.addressed"
    lab_join = ("LEFT JOIN lab.labels l ON l.change_number = t.change_number AND l.root_uuid = t.root_uuid "
                "AND l.classifier_id = ? AND l.input_hash = t.input_hash") if active else ""
    q = lambda sql, *a: _ByCL(rd.execute(sql, a))
    comments = q("SELECT change_number, account_id, written_at, path, chars FROM comments WHERE after_close = 0 "
                 "ORDER BY change_number")
    threads = q("SELECT t.change_number, t.last_owner_reply_at, t.regex_addressed, t.root_account, c.written_at, "
                f"{label} FROM threads t LEFT JOIN comments c ON c.host = t.host "
                f"AND c.change_number = t.change_number AND c.comment_id = t.root_uuid {lab_join} "
                "ORDER BY t.change_number", *([active[0]] if active else []))
    uploads = q("SELECT change_number, at, kind, uploader FROM tim.uploads ORDER BY change_number")
    attention = q("SELECT change_number, account_id, start_at, end_at FROM tim.attention ORDER BY change_number")
    interdiff = q("SELECT change_number, seen_ps, lines_seen, lines_final, lines_changed, files_changed, "
                  "files_added, status FROM int.interdiff ORDER BY change_number")
    asked = q("SELECT change_number, min(asked_at) FROM tim.cl_reviewers GROUP BY 1 ORDER BY 1")

    def rows():
        for fact in facts:
            n, owner, c0, c1 = fact[0], fact[1], fact[4], fact[5]
            r = None      # comments, chars, reviewers, first inline
            for _, acct, at, path, chars in comments.take(n):
                if acct in bots:
                    continue
                if r is None:
                    r = [0, 0, set(), None]
                t = epoch(at)
                r[0] += 1
                r[1] += chars
                r[2].add(acct)
                if path != "/PATCHSET_LEVEL" and (r[3] is None or t < r[3]):
                    r[3] = t
            th, roots = [0, 0, 0], []      # threads, addressed, unlabelled; [(root time, owner replied)]
            for _, reply, rx, acct, at, lab in threads.take(n):
                if acct in bots:
                    continue
                if at:
                    roots.append((epoch(at), reply is not None))
                th[0] += 1
                pt = 0 if reply is None else 1 if rx else lab
                th[1] += pt or 0
                th[2] += pt is None
            engaged = [t for t, replied in roots if replied]
            first = (r[3] if r else None) or (min(engaged) if engaged else None)
            u = sorted(x[1:] for x in uploads.take(n))
            rework_after = sum(1 for at, k, _ in u if first and at > first and k == "rework") if u and first else None
            a = [x[1:] for x in attention.take(n)]
            hi = c1 or max([e for _, _, e in a] or [c0])
            others = [(s, e) for acct, s, e in a if acct != owner and acct not in bots]
            sent = asked.take(n)
            sent = sent[0][1] if sent else None
            rounds = None
            if u:
                ev = sorted([(t, 0) for t, _ in roots] +
                            [(at, 1) for at, k, who in u if k == "rework" and who == owner and (sent is None or at > sent)])
                rounds, waiting = 0, False
                for _, kind in ev:
                    if kind == 0:
                        waiting = True
                    elif waiting:
                        rounds += 1
                        waiting = False
            ous = union_spans(others, c0, hi)
            i = interdiff.take(n)
            i = i[0][1:] if i else (None,) * 7
            yield (*fact,
                   r[0] if r else 0, r[1] if r else 0, len(r[2]) if r else 0, th[0], th[1], th[2],
                   first, sent, rework_after, rounds,
                   union_hours(others, c0, hi) if a else None,
                   sum(weekday_seconds(s_, e_) for s_, e_ in ous) / 3600 if a else None,
                   union_hours([(s, e) for acct, s, e in a if acct == owner], c0, hi) if a else None,
                   *(i if first else (None,) * 7))
    print("cl: joining", flush=True)
    before = db.total_changes
    db.executemany(f"INSERT INTO cl VALUES ({','.join('?' * 36)})", rows())
    ncl = db.total_changes - before
    db.execute(f"ATTACH 'file:{db_path('timeline')}?mode=ro' AS tim")
    db.execute("INSERT INTO cl_attention SELECT r.change_number, r.account_id, r.attention_h, "
               "r.attention_weekday_h FROM tim.cl_reviewers r JOIN cl USING (change_number) "
               "WHERE r.attention_h IS NOT NULL")
    print("cl: directories", flush=True)
    before = db.total_changes
    db.executemany("INSERT INTO cl_dirs VALUES (?,?,?,?)", iter_cl_dirs(gdb, by_cid))
    db.commit()
    print(f"cl: done, {ncl:,} CLs, {db.total_changes - before:,} CL directories", flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="cosh.balance")
    ap.add_argument("stage", choices=["interdiff", "cl"])
    ap.add_argument("--db")
    ap.add_argument("--shard", default="0/1", help="interdiff: i/k, the CLs with number %% k == i")
    args = ap.parse_args(argv)
    db = connect(args.db or db_path(args.stage), args.stage)
    if args.stage == "interdiff":
        stage_interdiff(db, shard=tuple(map(int, args.shard.split("/"))))
    else:
        stage_cl(db)


if __name__ == "__main__":
    main()
