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
from .cl_facts import CL_FACTS, cl_dirs, cl_facts, epoch  # noqa: F401 (moved there)
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


def stage_cl(db):
    from collections import defaultdict
    db.executescript(CL_SCHEMA)
    derived = os.path.join(store.DATA_DIR, store.DERIVED_FILE)
    db.execute(f"ATTACH 'file:{derived}?mode=ro' AS d")
    for st in ("timeline", "interdiff"):
        db.execute(f"ATTACH 'file:{db_path(st)}?mode=ro' AS {st[0]}{st[1:3]}")
    ddb = sqlite3.connect(f"file:{derived}?mode=ro", uri=True)
    gdb = sqlite3.connect(f"file:{db_path('git')}?mode=ro", uri=True)
    print("cl: loading", flush=True)
    bots = {r[0] for r in db.execute("SELECT account_id FROM d.accounts WHERE is_bot = 1")}
    facts, by_cid = cl_facts(ddb, gdb)
    # Review from reviews.sqlite, as summarize counts it (human non-owners).
    labels = {}
    from . import classify
    lp = classify.labels_path(store.DATA_DIR)
    if os.path.exists(lp):
        ldb = sqlite3.connect(f"file:{lp}?mode=ro", uri=True)
        active = classify.active_classifier(ldb)
        if active:
            labels = {(n, r, h): a for n, r, h, a in ldb.execute(
                "SELECT change_number, root_uuid, input_hash, addressed FROM labels WHERE classifier_id = ?",
                (active[0],))}
    rev = defaultdict(lambda: [0, 0, set(), [], None])   # comments, chars, reviewers, times, first inline
    for n, acct, at, path, chars in db.execute(
            "SELECT change_number, account_id, written_at, path, chars FROM d.comments WHERE after_close = 0"):
        if acct in bots:
            continue
        r = rev[n]
        t = epoch(at)
        r[0] += 1
        r[1] += chars
        r[2].add(acct)
        r[3].append(t)
        if path != "/PATCHSET_LEVEL" and (r[4] is None or t < r[4]):
            r[4] = t
    thr = defaultdict(lambda: [0, 0, 0])
    roots = defaultdict(list)    # CL -> [(root time, owner replied)]
    for n, root, reply, rx, h, acct, at in db.execute(
            "SELECT t.change_number, t.root_uuid, t.last_owner_reply_at, t.regex_addressed, t.input_hash, "
            "t.root_account, c.written_at FROM d.threads t LEFT JOIN d.comments c ON c.host = t.host "
            "AND c.change_number = t.change_number AND c.comment_id = t.root_uuid"):
        if acct in bots:
            continue
        if at:
            roots[n].append((epoch(at), reply is not None))
        t = thr[n]
        t[0] += 1
        pt = 0 if reply is None else 1 if rx else labels.get((n, root, h))
        t[1] += pt or 0
        t[2] += pt is None
    ups = defaultdict(list)
    for n, ps, at, who, kind in db.execute("SELECT change_number, ps, at, uploader, kind FROM tim.uploads"):
        ups[n].append((at, kind, who))
    att = defaultdict(list)
    for n, acct, s, e in db.execute("SELECT change_number, account_id, start_at, end_at FROM tim.attention"):
        att[n].append((acct, s, e))
    idf = {r[0]: r[1:] for r in db.execute(
        "SELECT change_number, seen_ps, lines_seen, lines_final, lines_changed, files_changed, files_added, "
        "status FROM int.interdiff")}
    sent_at = dict(db.execute("SELECT change_number, min(asked_at) FROM tim.cl_reviewers GROUP BY 1"))
    print(f"cl: joining {len(facts):,} CLs", flush=True)
    rows = []
    for fact in facts:
        n, owner, c0, c1 = fact[0], fact[1], fact[4], fact[5]
        r = rev.get(n)
        engaged = [t for t, replied in roots.get(n, []) if replied]
        first = (r[4] if r else None) or (min(engaged) if engaged else None)
        u = sorted(ups.get(n, []))
        rework_after = sum(1 for at, k, _ in u if first and at > first and k == "rework") if u and first else None
        a = att.get(n, [])
        hi = c1 or max([e for _, _, e in a] or [c0])
        others = [(s, e) for acct, s, e in a if acct != owner and acct not in bots]
        sent = sent_at.get(n)
        rounds = None
        if u:
            ev = sorted([(t, 0) for t, _ in roots.get(n, [])] +
                        [(at, 1) for at, k, who in u if k == "rework" and who == owner and (sent is None or at > sent)])
            rounds, waiting = 0, False
            for _, kind in ev:
                if kind == 0:
                    waiting = True
                elif waiting:
                    rounds += 1
                    waiting = False
        ous = union_spans(others, c0, hi)
        t = thr.get(n, [0, 0, 0])
        i = idf.get(n, (None,) * 7)
        rows.append((*fact,
                     r[0] if r else 0, r[1] if r else 0, len(r[2]) if r else 0, t[0], t[1], t[2],
                     first, sent, rework_after, rounds,
                     union_hours(others, c0, hi) if a else None,
                     sum(weekday_seconds(s_, e_) for s_, e_ in ous) / 3600 if a else None,
                     union_hours([(s, e) for acct, s, e in a if acct == owner], c0, hi) if a else None,
                     *(i if first else (None,) * 7)))
    db.executemany(f"INSERT INTO cl VALUES ({','.join('?' * 36)})", rows)
    db.execute("INSERT INTO cl_attention SELECT r.change_number, r.account_id, r.attention_h, "
               "r.attention_weekday_h FROM tim.cl_reviewers r JOIN cl USING (change_number) "
               "WHERE r.attention_h IS NOT NULL")
    print("cl: directories", flush=True)
    agg = cl_dirs(gdb, by_cid)
    db.executemany("INSERT INTO cl_dirs VALUES (?,?,?,?)", ((n, d, f, l) for (n, d), (f, l) in agg.items()))
    db.commit()
    print(f"cl: done, {len(rows):,} CLs, {len(agg):,} CL directories", flush=True)


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
