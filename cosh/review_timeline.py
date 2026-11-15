"""Each CL's review timeline, in data/private/review-timeline.sqlite: who was
asked to review it, when they first answered and how long it sat in their
attention set. Shared: the Review Load page (cosh/review_load.py) and the
Review Balance stages (cosh/balance.py) both read it, so either can be
updated without the other.

Offline only: reads the NoteDb meta refs, the listings in gerrit.sqlite and
reviews.sqlite, and fetches nothing. Every git command runs with
GIT_NO_LAZY_FETCH=1. The store is rebuildable: delete it and rerun.

  python3 -m cosh.review_timeline [--db PATH] [--only walk|listing|reviewers]

One run does three things, in order:
  walk       per CL from its NoteDb meta ref: uploads (kind, time, uploader),
             attention-set intervals per account and Code-Review votes.
             Incremental: rereads a CL only when its meta ref moved.
  listing    the Code-Review votes on CLs that have no comments, and so no
             local meta ref (extract fetches NoteDb only for CLs with
             comments), from the listing each was fetched with. Incremental:
             reads a listing only when its body is new.
  reviewers  cl_reviewers, one row per CL and human reviewer (not the owner,
             not a bot): when they were first asked (entered the attention
             set), when they first answered (a Code-Review vote or a comment)
             and their hours in the attention set, also with Saturdays and
             Sundays (UTC) left out; and cl_turns, each of their turns
             (overlapping intervals merged) that ended before the CL closed,
             with its weekday hours and its working hours, the reviewer's
             and the CL owner's (cosh/work_hours.py), from work_windows: each
             person's 8-hour window per quarter. Rebuilt whole, from the
             tables above and reviews.sqlite's comments.

$COSH_REVIEW_TIMELINE points the step and its readers at another file.
"""

import argparse
import json
import os
import re
import sqlite3
import subprocess
import time
import zlib
from collections import defaultdict
from datetime import datetime, timezone

from . import codefp, store, work_hours
from .bots import is_bot_account
from .cl_facts import epoch

FILE = "review-timeline.sqlite"
NOTEDB = os.path.join(store.DATA_DIR, "notedb", "chromium_src.git")
ENV = {**os.environ, "GIT_NO_LAZY_FETCH": "1"}
PROJECT = "chromium/src"

SCHEMA = """
-- Per CL, from its NoteDb meta ref.
CREATE TABLE IF NOT EXISTS uploads (
  change_number INTEGER NOT NULL,
  ps            INTEGER NOT NULL,
  at            INTEGER NOT NULL,
  uploader      INTEGER NOT NULL,
  kind          TEXT    NOT NULL,       -- initial | rework | rebase | message_only | no_change
  sha           TEXT,
  PRIMARY KEY (change_number, ps)
) STRICT, WITHOUT ROWID;
-- Time each account spent in the attention set, closed at the CL's close (or
-- its last meta update while open).
CREATE TABLE IF NOT EXISTS attention (
  change_number INTEGER NOT NULL,
  account_id    INTEGER NOT NULL,
  start_at      INTEGER NOT NULL,
  end_at        INTEGER NOT NULL,
  PRIMARY KEY (change_number, account_id, start_at)
) STRICT, WITHOUT ROWID;
-- Every Code-Review vote cast (parse_votes).
CREATE TABLE IF NOT EXISTS votes (
  change_number INTEGER NOT NULL,
  voter         INTEGER NOT NULL,
  value         INTEGER NOT NULL,      -- -2..+2; 0 = vote removed
  at            INTEGER NOT NULL,
  ps            INTEGER NOT NULL,
  PRIMARY KEY (change_number, voter, at, value)
) STRICT, WITHOUT ROWID;
-- The meta ref's tip when the CL was read: a CL is read again when its tip moves.
CREATE TABLE IF NOT EXISTS timeline_done (change_number INTEGER PRIMARY KEY, tip TEXT NOT NULL) STRICT;
-- The Code-Review votes standing on a CL without comments (no meta ref), from its listing.
CREATE TABLE IF NOT EXISTS listing_votes (
  change_number INTEGER NOT NULL,
  voter         INTEGER NOT NULL,
  value         INTEGER NOT NULL,      -- -2..+2, never 0
  at            INTEGER NOT NULL,
  PRIMARY KEY (change_number, voter)
) STRICT, WITHOUT ROWID;
-- The listings read, by the hash of their body: a refetched listing is read again.
CREATE TABLE IF NOT EXISTS listing_done (window_key TEXT PRIMARY KEY, body_sha256 TEXT NOT NULL) STRICT;
-- The code fingerprints of walk and listing ('code_fp:<stage>', cosh/codefp.py).
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT) STRICT;
"""

REVIEWERS_SCHEMA = """
DROP TABLE IF EXISTS cl_reviewers;
CREATE TABLE cl_reviewers (       -- each human other than the owner who was asked to review a CL or answered
  change_number       INTEGER NOT NULL,
  account_id          INTEGER NOT NULL,
  asked_at            INTEGER,    -- first time in the attention set; NULL if never (or before it existed)
  responded_at        INTEGER,    -- first Code-Review vote or comment before the CL closed; NULL if none
  attention_h         REAL,       -- hours in the attention set, from the CL's creation to its close
  attention_weekday_h REAL,       -- the same, Saturdays and Sundays (UTC) left out
  PRIMARY KEY (change_number, account_id)
) STRICT, WITHOUT ROWID;
DROP TABLE IF EXISTS cl_turns;
CREATE TABLE cl_turns (           -- each turn of those reviewers in the attention set (overlapping intervals merged)
  change_number INTEGER NOT NULL, -- that ended before the CL closed: one still open then is left out (the CL
  account_id    INTEGER NOT NULL, -- didn't wait on it)
  start_at      INTEGER NOT NULL,
  end_at        INTEGER NOT NULL,
  weekday_h     REAL    NOT NULL, -- its hours, Saturdays and Sundays (UTC) left out
  work_h        REAL,             -- its hours inside the reviewer's working window (NULL: no window)
  owner_work_h  REAL,             -- the same in the CL owner's window: the wait as the owner saw it
  PRIMARY KEY (change_number, account_id, start_at)
) STRICT, WITHOUT ROWID;
DROP TABLE IF EXISTS work_windows;
CREATE TABLE work_windows (       -- each person's working window per quarter (cosh/work_hours.py)
  account_id INTEGER NOT NULL,
  quarter    TEXT    NOT NULL,    -- '2026Q3'
  start_h    INTEGER NOT NULL,    -- the window's first hour, UTC (8 hours, wrapping midnight)
  basis      TEXT    NOT NULL,    -- quarter: fitted to that quarter's activity; history: too little, fitted to earlier
  events     INTEGER NOT NULL,    -- comments, votes and uploads in the quarter
  PRIMARY KEY (account_id, quarter)
) STRICT, WITHOUT ROWID;
"""


def db_path():
    return os.environ.get("COSH_REVIEW_TIMELINE") or os.path.join(store.DATA_DIR, FILE)


def connect(path=None):
    db = sqlite3.connect(path or db_path(), timeout=60)
    db.execute("PRAGMA journal_mode=WAL")
    if db.execute("SELECT 1 FROM pragma_table_info('timeline_done') WHERE name = 'change_number'").fetchone() \
            and not db.execute("SELECT 1 FROM pragma_table_info('timeline_done') WHERE name = 'tip'").fetchone():
        # A store from before tips (and votes) were kept: an empty tip makes
        # every CL read again, its old rows replaced.
        db.execute("ALTER TABLE timeline_done ADD COLUMN tip TEXT NOT NULL DEFAULT ''")
    db.executescript(SCHEMA)
    return db


def open_ro(path=None):
    return sqlite3.connect(f"file:{path or db_path()}?mode=ro", uri=True)


def reviews_ro():
    return sqlite3.connect(f"file:{os.path.join(store.DATA_DIR, store.DERIVED_FILE)}?mode=ro", uri=True)


# --------------------------------------------------------------------- walk

def kind_of(upload_line):
    rest = upload_line.split(":", 1)[1] if ":" in upload_line else ""
    if "same tree, parent tree" in rest:
        return "no_change"
    if "was rebased" in rest:
        return "rebase"
    if "Commit message was updated" in rest:
        return "message_only"
    return "rework"


ATTN = re.compile(r'^Attention: (\{.*\})$', re.M)
GERRIT_USER = re.compile(r"Gerrit User (\d+) <")


def parse_meta_log(entries):
    """entries: [(at, author_id, body)] oldest first. Returns uploads and
    attention intervals [(account, start, end)], closed at the CL's close
    (or its last entry while open)."""
    uploads, open_at, spans, status_at = [], {}, [], None
    for at, author, body in entries:
        first = body.split("\n", 1)[0]
        if first == "Create change" or first.startswith("Create patch set"):
            ps = re.search(r"^Patch-set: (\d+)", body, re.M)
            up = re.search(r"^Uploaded patch set \d+.*$", body, re.M)
            sha = re.search(r"^Commit: ([0-9a-f]{40})", body, re.M)
            kind = "initial" if first == "Create change" else kind_of(up.group(0) if up else "")
            uploads.append((int(ps.group(1)) if ps else 0, at, author, kind, sha.group(1) if sha else None))
        for m in ATTN.finditer(body):
            try:
                a = json.loads(m.group(1))
            except ValueError:
                continue
            who = GERRIT_USER.search(a.get("person_ident", ""))
            if not who:
                continue
            acct = int(who.group(1))
            if a.get("operation") == "ADD":
                open_at.setdefault(acct, at)
            elif acct in open_at:
                spans.append((acct, open_at.pop(acct), at))
        if re.search(r"^Status: (merged|abandoned)", body, re.M):
            status_at = at
    end = status_at or (entries[-1][0] if entries else 0)
    spans += [(acct, s, max(s, end)) for acct, s in open_at.items()]
    return uploads, spans


# "Label: Code-Review=-1", "Label: Code-Review=+2, <uuid>",
# "Label: Code-Review=-1 Gerrit User 123 <123@uuid>" (on behalf of),
# "Label: -Code-Review" / "=0" (vote removed). Copied-Label lines are copies
# of an earlier vote onto a new patch set, so they are skipped.
LABEL = re.compile(r"^Label: (-?)Code-Review(?:=([+-]?\d+))?(?:, [0-9a-f-]+)?(?: Gerrit User (\d+) <[^>]*>)?\s*$", re.M)
PATCH_SET = re.compile(r"^Patch-set: (\d+)", re.M)


def parse_votes(entries):
    """entries: [(at, author_id, body)] oldest first. Returns
    [(voter, value, at, ps)]: every Code-Review vote cast, 0 for a removal."""
    out = []
    for at, author, body in entries:
        ps = PATCH_SET.search(body)
        ps = int(ps.group(1)) if ps else 0
        for m in LABEL.finditer(body):
            removed, value, behalf = m.groups()
            voter = int(behalf) if behalf else author
            v = 0 if removed or value is None else int(value)
            out.append((voter, v, at, ps))
    return out


def meta_refs(git_dir=None):
    """{change number: tip sha} of the refs/meta/<n> refs in the NoteDb repo.

    List the refs once and intersect in Python: `for-each-ref` with many
    refnames as patterns matches every ref against every pattern, which took
    54 s per 2,000 CLs against 715k refs (2026-11-12)."""
    out = subprocess.run(["git", "--git-dir", git_dir or NOTEDB, "for-each-ref",
                          "--format=%(objectname) %(refname:lstrip=2)", "refs/meta/"],
                         capture_output=True, text=True, env=ENV, check=True).stdout
    return {int(n): sha for sha, n in (line.split() for line in out.splitlines()) if n.isdigit()}


def stage_timeline(db, numbers=None, batch=2000):
    """Walk each CL's meta ref history, many refs per `git log` process, and
    keep its uploads, attention-set intervals and Code-Review votes. A CL is
    read again (its rows replaced) when its ref's tip has moved since; CLs
    with no ref are not marked, so a ref that arrives later is read."""
    if numbers is None:
        numbers = [r[0] for r in reviews_ro().execute(
            "SELECT change_number FROM changes WHERE is_bot_owned = 0 AND project = ? AND branch = 'main'",
            (PROJECT,))]
    if codefp.check(db, "walk", walk_fingerprint(), reset_walk) == "changed":
        print("timeline: the code that reads meta refs changed: every CL is read again", flush=True)
    done = dict(db.execute("SELECT change_number, tip FROM timeline_done"))
    have = meta_refs()
    numbers = set(numbers)
    missing = numbers - have.keys()
    if missing:
        print(f"timeline: {len(missing):,} CLs have no meta ref locally; skipped", flush=True)
    todo = sorted(n for n in numbers & have.keys() if done.get(n) != have[n])
    again = sum(1 for n in todo if n in done)
    print(f"timeline: {len(todo):,} CLs to read ({again:,} of them updated since read; "
          f"{len(done):,} done)", flush=True)
    t0 = time.time()
    for i in range(0, len(todo), batch):
        part = todo[i:i + batch]
        _walk(db, part, done)
        db.commit()
        k = i + len(part)
        print(f"timeline: {k:,}/{len(todo):,} ({k / (time.time() - t0):.0f} CLs/s)", flush=True)


def _walk(db, part, done):
    """Reads the meta refs of the CLs `part` (one `git log`) and replaces
    their uploads, attention and votes rows (uncommitted)."""
    p = subprocess.run(["git", "--git-dir", NOTEDB, "log", "--decorate=full", "--decorate-refs=refs/meta/",
                        "--format=%x01%x02%x03%H%x00%P%x00%D%x00%at%x00%an%x00%B", *[f"refs/meta/{n}" for n in part]],
                       capture_output=True, env=ENV)
    if p.returncode:
        raise SystemExit(f"git log failed: {p.stderr[:500]!r}")
    commits, tips = {}, {}
    for rec in p.stdout.split(b"\x01\x02\x03")[1:]:
        fields = rec.decode("utf-8", "replace").split("\x00", 5)
        if len(fields) < 6:
            continue
        sha, parent, refs, at, an, body = fields
        who = re.match(r"Gerrit User (\d+)", an)
        commits[sha] = (parent.split()[0] if parent else None, int(at), int(who.group(1)) if who else 0, body)
        for m in re.finditer(r"refs/meta/(\d+)", refs):
            tips[int(m.group(1))] = sha
    del p
    for n, tip in tips.items():
        ents, sha = [], tip
        while sha in commits:
            parent, at, who, body = commits[sha]
            ents.append((at, who, body))
            sha = parent
        ents.reverse()
        ups, spans = parse_meta_log(ents)
        if n in done:
            for t in ("uploads", "attention", "votes"):
                db.execute(f"DELETE FROM {t} WHERE change_number = ?", (n,))
        db.executemany("INSERT OR REPLACE INTO uploads VALUES (?,?,?,?,?,?)",
                       [(n, ps, at, who, kind, sha) for ps, at, who, kind, sha in ups])
        db.executemany("INSERT OR REPLACE INTO attention VALUES (?,?,?,?)",
                       [(n, a, s, e) for a, s, e in spans])
        db.executemany("INSERT OR IGNORE INTO votes VALUES (?,?,?,?,?)",
                       [(n, *v) for v in parse_votes(ents)])
        # The tip actually walked, which is newer than `have` if the ref moved meanwhile.
        db.execute("INSERT OR REPLACE INTO timeline_done VALUES (?,?)", (n, tip))


# What each incremental stage's rows are a function of besides its inputs
# (cosh/codefp.py). When one changes, the stage's rows are deleted and it
# reads everything again (walk about 35 min, listing a few minutes); the
# reviewers stage is rebuilt whole on every run anyway. Bump a version for
# a change the fingerprint can't see.
WALK_VERSION = 1
LISTING_VERSION = 1


def walk_fingerprint():
    return codefp.fingerprint(WALK_VERSION, _walk, parse_meta_log, kind_of, parse_votes,
                              ATTN, GERRIT_USER, LABEL, PATCH_SET)


def listing_fingerprint():
    return codefp.fingerprint(LISTING_VERSION, stage_listing_rows, listing_votes, epoch,
                              files=["cosh/bots.py", "config/bots.txt"])


def reset_walk(db):
    for t in ("uploads", "attention", "votes", "timeline_done"):
        db.execute(f"DELETE FROM {t}")


def reset_listing(db):
    for t in ("listing_votes", "listing_done"):
        db.execute(f"DELETE FROM {t}")


# ------------------------------------------------------------------ listing

def listing_votes(change):
    """[(voter, value, at)] of the Code-Review votes standing on a listed CL:
    the newest vote of each account, as the listing's DETAILED_LABELS gives
    them. Earlier votes that a new patch set cleared are not in a listing."""
    out = []
    for a in ((change.get("labels") or {}).get("Code-Review") or {}).get("all") or []:
        if a.get("value") and a.get("date") and a.get("_account_id") is not None:
            out.append((a["_account_id"], int(a["value"]), epoch(a["date"])))
    return out


def stage_listing_rows(db, changes):
    """Replaces listing_votes of the CLs in one listing that have no
    comments (uncommitted). Returns how many."""
    n_cls = 0
    for c in changes:
        if c.get("project") != PROJECT or c.get("total_comment_count", 0) > 0 \
                or is_bot_account(c.get("owner", {})):
            continue
        n = c["_number"]
        db.execute("DELETE FROM listing_votes WHERE change_number = ?", (n,))
        db.executemany("INSERT OR REPLACE INTO listing_votes VALUES (?,?,?,?)",
                       [(n, *v) for v in listing_votes(c)])
        n_cls += 1
    return n_cls


def stage_listing(db, raw=None):
    """Votes of the closed CLs that have no comments, from the weekly
    listings in gerrit.sqlite. A CL with comments has a meta ref, whose votes
    stage_timeline reads in full."""
    raw = raw or store.open_raw_ro()
    if codefp.check(db, "listing", listing_fingerprint(), reset_listing) == "changed":
        print("listing: the code that reads listings changed: every listing is read again", flush=True)
    done = dict(db.execute("SELECT window_key, body_sha256 FROM listing_done"))
    keys = [(h, k, sha) for h, k, sha in raw.execute(
        "SELECT host, key, body_sha256 FROM responses WHERE kind = 'list_window' AND http_status = 200 "
        "AND key IN (SELECT window_key FROM week_changes) ORDER BY key") if done.get(k) != sha]
    print(f"listing: {len(keys):,} listings to read ({len(done):,} done)", flush=True)
    n_cls = 0
    for i, (host, key, sha) in enumerate(keys):
        body = raw.execute("SELECT body_zlib FROM responses WHERE host = ? AND kind = 'list_window' AND key = ?",
                           (host, key)).fetchone()[0]
        n_cls += stage_listing_rows(db, json.loads(zlib.decompress(body)))
        db.execute("INSERT OR REPLACE INTO listing_done VALUES (?,?)", (key, sha))
        if i % 200 == 199:
            db.commit()
            print(f"listing: {i + 1:,}/{len(keys):,}", flush=True)
    db.commit()
    print(f"listing: done, {n_cls:,} CLs without comments", flush=True)


# ---------------------------------------------------------------- reviewers

def weekday_seconds(s, e):
    """Seconds of [s, e) that fall on Monday..Friday, UTC."""
    tot, day = 0, 86400
    t = s
    while t < e:
        nxt = min(e, (t // day + 1) * day)
        if datetime.fromtimestamp(t, timezone.utc).weekday() < 5:
            tot += nxt - t
        t = nxt
    return tot


def union_spans(spans, lo, hi):
    spans = sorted((max(s, lo), min(e, hi)) for s, e in spans if min(e, hi) > max(s, lo))
    out = []
    for s, e in spans:
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out


def work_pair(windows, reviewer, owner, s, e):
    """(the reviewer's, the owner's) working hours of [s, e); a reviewer without
    a window gets the owner's; None where neither has one."""
    if windows is None:
        return None, None
    o = windows.at(owner, s)
    r = windows.at(reviewer, s)
    r = o if r is None else r
    return tuple(None if w is None else round(work_hours.work_seconds(s, e, w) / 3600, 3) for w in (r, o))


TURN_OPEN_AT_CLOSE = 60   # seconds: a turn ending this close to the CL's close was still open at it


def reviewer_rows(cls, bots, attention, responses, windows=None):
    """cl_reviewers' rows and cl_turns' rows. cls: [(change_number, owner, created, closed or
    None)] in unix seconds; attention: {CL: [(account, start, end)]};
    responses: {CL: {account: first answer}}. Bots and the owner are left
    out. Attention is clipped to the CL's life (to its last interval's end
    while it is open), and overlapping intervals count once, as one turn.
    A turn still open at the CL's close (ending within TURN_OPEN_AT_CLOSE
    of it) isn't a row of cl_turns: the CL landed or was abandoned without
    waiting on it. `windows` (a cosh.work_hours.Windows) adds each turn's
    working hours, the reviewer's (in the owner's window when the reviewer
    has none) and the owner's; without it both are None."""
    rows, turns = [], []
    for n, owner, c0, c1 in cls:
        a = attention.get(n, ())
        hi = c1 or max([e for _, _, e in a] or [c0])
        per = defaultdict(list)
        for acct, s, e in a:
            if acct != owner and acct not in bots:
                per[acct].append((s, e))
        resp = {acct: t for acct, t in responses.get(n, {}).items() if acct != owner and acct not in bots}
        for acct in sorted(per.keys() | resp.keys()):
            sp = per.get(acct)
            if sp:
                us = union_spans(sp, c0, hi)
                wd = [weekday_seconds(s, e) / 3600 for s, e in us]
                hours = (sum(e - s for s, e in us) / 3600, sum(wd))
                turns += [(n, acct, s, e, h, *work_pair(windows, acct, owner, s, e))
                          for (s, e), h in zip(us, wd) if e < hi - TURN_OPEN_AT_CLOSE]
            rows.append((n, acct, min(s for s, _ in sp) if sp else None, resp.get(acct),
                         *(hours if sp else (None, None))))
    return rows, turns


def stage_reviewers(db, ddb=None):
    ddb = ddb or reviews_ro()
    bots = {r[0] for r in ddb.execute("SELECT account_id FROM accounts WHERE is_bot = 1")}
    cls = [(n, owner, epoch(c0), epoch(c1) if c1 else None) for n, owner, c0, c1 in ddb.execute(
        "SELECT change_number, owner_account, created_at, closed_at FROM changes "
        "WHERE is_bot_owned = 0 AND project = ? AND branch = 'main'", (PROJECT,))]
    print(f"reviewers: {len(cls):,} CLs", flush=True)
    closed = {n: c1 for n, _, _, c1 in cls}
    responses = defaultdict(dict)

    def answer(n, acct, at):
        end = closed.get(n, 0)
        if n in closed and (end is None or at <= end):
            r = responses[n]
            r[acct] = min(at, r.get(acct, at))

    for n, acct, at in ddb.execute("SELECT change_number, account_id, min(written_at) FROM comments "
                                   "WHERE after_close = 0 GROUP BY 1, 2"):
        answer(n, acct, epoch(at))
    walked = {r[0] for r in db.execute("SELECT change_number FROM timeline_done")}
    for n, acct, at in db.execute("SELECT change_number, voter, min(at) FROM votes WHERE value != 0 GROUP BY 1, 2"):
        answer(n, acct, at)
    for n, acct, at in db.execute("SELECT change_number, voter, at FROM listing_votes"):
        if n not in walked:
            answer(n, acct, at)
    attention = defaultdict(list)
    for n, acct, s, e in db.execute("SELECT change_number, account_id, start_at, end_at FROM attention"):
        attention[n].append((acct, s, e))
    windows = work_hours.Windows(work_hours.activity_counts(db, ddb))
    rows, turns = reviewer_rows(cls, bots, attention, responses, windows)
    db.executescript(REVIEWERS_SCHEMA)
    db.executemany("INSERT INTO work_windows VALUES (?,?,?,?,?)", windows.rows())
    db.executemany("INSERT INTO cl_reviewers VALUES (?,?,?,?,?,?)", rows)
    db.executemany("INSERT INTO cl_turns VALUES (?,?,?,?,?,?,?)", turns)
    db.commit()
    print(f"reviewers: done, {len(rows):,} reviewers of {len({r[0] for r in rows}):,} CLs", flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="cosh.review_timeline")
    ap.add_argument("--db")
    ap.add_argument("--only", choices=["walk", "listing", "reviewers"])
    ap.add_argument("--week", help="walk only CLs closed in this ISO week (for tests)")
    args = ap.parse_args(argv)
    db = connect(args.db)
    if args.only in (None, "walk"):
        nums = None
        if args.week:
            nums = [r[0] for r in reviews_ro().execute(
                "SELECT change_number FROM changes WHERE close_week = ? AND is_bot_owned = 0", (args.week,))]
        stage_timeline(db, nums)
    if args.only in (None, "listing"):
        stage_listing(db)
    if args.only in (None, "reviewers"):
        stage_reviewers(db)


if __name__ == "__main__":
    main()
