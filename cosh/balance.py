"""Author/reviewer balance data (docs/balance.md), in data/private/balance.sqlite.

Offline only: reads the local git clones, the NoteDb meta refs and
derived.sqlite, and fetches nothing. Every git command runs with
GIT_NO_LAZY_FETCH=1. balance.sqlite is rebuildable: delete it and rerun.

Stages (each resumable; git, timeline and interdiff may run at once, but
interdiff needs timeline's uploads; each writes data/private/balance-<stage>.sqlite):
  git        first-parent history of chromium/src main since 2017-01-01: author,
             dates, CL number, Reviewed-by footers, reverts, per-file line counts
  timeline   per CL from NoteDb: uploads (kind, time, uploader) and attention-set
             intervals per account
  interdiff  per reviewed CL: how much its diff changed between the first
             reviewed patch set and the final one, comparing diffs, not files,
             so rebases don't count
  cl         one row per CL joining all of the above with review threads

  python3 -m cosh.balance git|timeline|interdiff|cl [--db PATH]
"""

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone

from . import store

SHARED = os.path.expanduser("~/projects/shared/chromium")
PATCHSETS = os.path.join(store.DATA_DIR, "git", "chromium-patchsets.git")
NOTEDB = os.path.join(store.DATA_DIR, "notedb", "chromium_src.git")
ENV = {**os.environ, "GIT_NO_LAZY_FETCH": "1"}
SINCE = "2017-01-01"

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT) STRICT;
CREATE TABLE IF NOT EXISTS paths (path_id INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE) STRICT;
-- First-parent commits of main since SINCE.
CREATE TABLE IF NOT EXISTS gcommits (
  commit_id     INTEGER PRIMARY KEY,
  sha           TEXT    NOT NULL UNIQUE,
  author_email  TEXT    NOT NULL,       -- lowercased
  authored_at   INTEGER NOT NULL,       -- unix seconds
  landed_at     INTEGER NOT NULL,
  change_number INTEGER,                -- chromium/src Reviewed-on; NULL if none
  is_bot        INTEGER NOT NULL,       -- Bot-Commit footer
  reviewed_by   TEXT,                   -- JSON list of lowercased emails, NULL if none
  reverts_sha   TEXT,                   -- "This reverts commit <sha>"
  is_reland     INTEGER NOT NULL,
  files         INTEGER NOT NULL,
  ins           INTEGER NOT NULL,       -- text lines (binary files count 0)
  dels          INTEGER NOT NULL
) STRICT;
CREATE INDEX IF NOT EXISTS gcommits_cl ON gcommits(change_number);
CREATE INDEX IF NOT EXISTS gcommits_author ON gcommits(author_email, landed_at);
CREATE TABLE IF NOT EXISTS gfiles (
  commit_id INTEGER NOT NULL,
  path_id   INTEGER NOT NULL,
  ins       INTEGER NOT NULL,           -- -1 for binary
  dels      INTEGER NOT NULL,
  PRIMARY KEY (commit_id, path_id)
) STRICT, WITHOUT ROWID;

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
CREATE TABLE IF NOT EXISTS timeline_done (change_number INTEGER PRIMARY KEY) STRICT;

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
"""


def db_path(stage):
    """Each stage writes its own file, so stages can run at the same time;
    `cl` reads them all and writes balance.sqlite."""
    return os.path.join(store.DATA_DIR, "balance.sqlite" if stage == "cl" else f"balance-{stage}.sqlite")


def connect(path):
    db = sqlite3.connect(path, timeout=60)
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript(SCHEMA)
    return db


def git_popen(git_dir, *args, stdin=None):
    return subprocess.Popen(["git", "--git-dir", git_dir, *args], stdout=subprocess.PIPE,
                            stdin=subprocess.PIPE if stdin else None, env=ENV)


# ---------------------------------------------------------------- git stage

REVIEWED_ON = re.compile(r"chromium-review\.googlesource\.com/(?:c/)?(?:chromium/src/\+/)?(\d+)$")
REVERTS = re.compile(rb"^This reverts commit ([0-9a-f]{40})", re.M)
EMAIL = re.compile(r"<([^>]+)>")
SEP = "\x1e"


def stage_git(db, since=SINCE):
    """Read `git log --first-parent --numstat` of main since `since` (or since
    the newest commit already stored) in one process."""
    last = db.execute("SELECT max(landed_at) FROM gcommits").fetchone()[0]
    after = datetime.fromtimestamp(last, timezone.utc).isoformat() if last else since
    fmt = SEP.join(["%x01%x02%x03%H", "%ae", "%at", "%ct", "%s",
                    "%(trailers:key=Reviewed-on,valueonly,separator=%x1f)",
                    "%(trailers:key=Reviewed-by,valueonly,separator=%x1f)",
                    "%(trailers:key=Bot-Commit,valueonly,separator=%x1f)", "%b%x02"])
    p = git_popen(SHARED, "log", "--first-parent", "--reverse", f"--since={after}", "--no-renames",
                  "--numstat", f"--format={fmt}", "main")
    paths = dict(db.execute("SELECT path, path_id FROM paths"))
    known = {r[0] for r in db.execute("SELECT sha FROM gcommits WHERE landed_at >= ?", (last or 0,))}
    buf, n, t0 = b"", 0, time.time()

    def flush(rec):
        nonlocal n
        head, _, stat = rec.partition(b"\x02")
        parts = head.decode("utf-8", "replace").split(SEP)
        if len(parts) < 9 or not re.fullmatch(r"[0-9a-f]{40}", parts[0]):
            print(f"git: skipped a malformed record: {head[:60]!r}", flush=True)
            return
        sha, email, at, ct, subj, ron, rby, bot, body = parts[:9]
        if sha in known:
            return
        m = REVIEWED_ON.search(ron.split("\x1f")[0].strip()) if ron else None
        rb = [e.lower() for v in rby.split("\x1f") if v for e in EMAIL.findall(v)]
        rv = REVERTS.search(body.encode())
        files, ins, dels = [], 0, 0
        for line in stat.decode("utf-8", "replace").splitlines():
            if not line.strip():
                continue
            f = line.split("\t", 2)
            if len(f) != 3 or not (f[0].isdigit() or f[0] == "-"):
                continue
            a, d, path = f
            a, d = (-1, -1) if a == "-" else (int(a), int(d))
            pid = paths.get(path)
            if pid is None:
                pid = paths[path] = db.execute("INSERT INTO paths(path) VALUES (?)", (path,)).lastrowid
            files.append((pid, a, d))
            ins += max(a, 0)
            dels += max(d, 0)
        cid = db.execute("INSERT INTO gcommits(sha, author_email, authored_at, landed_at, change_number, "
                         "is_bot, reviewed_by, reverts_sha, is_reland, files, ins, dels) "
                         "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                         (sha, email.lower(), int(at), int(ct), int(m.group(1)) if m else None,
                          int(bool(bot.strip())), json.dumps(rb) if rb else None,
                          rv.group(1).decode() if rv else None,
                          int(subj.lower().startswith("reland")), len(files), ins, dels)).lastrowid
        db.executemany("INSERT OR IGNORE INTO gfiles VALUES (?,?,?,?)", [(cid, *f) for f in files])
        n += 1
        if n % 5000 == 0:
            db.commit()
            print(f"git: {n:,} commits, {datetime.fromtimestamp(int(ct), timezone.utc):%Y-%m-%d}, "
                  f"{n / (time.time() - t0):.0f}/s", flush=True)

    for chunk in iter(lambda: p.stdout.read(1 << 20), b""):
        buf += chunk
        recs = buf.split(b"\x01\x02\x03")
        buf = recs.pop()
        for rec in recs:
            if rec.strip():
                flush(rec)
    if buf.strip():
        flush(buf)
    rc = p.wait()
    db.commit()
    if rc:
        raise SystemExit(f"git log exited {rc}; rerun to resume")
    print(f"git: done, {n:,} new commits")


# ----------------------------------------------------------- timeline stage

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
    attention intervals {account: [(start, end)]}, end None while open."""
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


def stage_timeline(db, numbers=None, batch=2000):
    """Walk each CL's meta ref history, many refs per `git log` process."""
    if numbers is None:
        d = sqlite3.connect(f"file:{os.path.join(store.DATA_DIR, store.DERIVED_FILE)}?mode=ro", uri=True)
        numbers = [r[0] for r in d.execute("SELECT change_number FROM changes WHERE is_bot_owned = 0 "
                                           "AND project = 'chromium/src' AND branch = 'main'")]
    done = {r[0] for r in db.execute("SELECT change_number FROM timeline_done")}
    have = subprocess.run(["git", "--git-dir", NOTEDB, "for-each-ref", "--format=%(refname:lstrip=2)",
                           "refs/meta/"], capture_output=True, text=True, env=ENV, check=True).stdout
    have = {int(x) for x in have.split() if x.isdigit()}
    missing = set(numbers) - have
    if missing:
        print(f"timeline: {len(missing):,} CLs have no meta ref locally; skipped", flush=True)
    todo = sorted((set(numbers) & have) - done)
    print(f"timeline: {len(todo):,} CLs to read ({len(done):,} done)", flush=True)
    t0 = time.time()
    for i in range(0, len(todo), batch):
        part = todo[i:i + batch]
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
        hist = {}
        for n, sha in tips.items():
            ents = []
            while sha in commits:
                parent, at, who, body = commits[sha]
                ents.append((at, who, body))
                sha = parent
            hist[n] = ents
        for n, ents in hist.items():
            ents.reverse()
            ups, spans = parse_meta_log(ents)
            db.executemany("INSERT OR REPLACE INTO uploads VALUES (?,?,?,?,?,?)",
                           [(n, ps, at, who, kind, sha) for ps, at, who, kind, sha in ups])
            db.executemany("INSERT OR REPLACE INTO attention VALUES (?,?,?,?)",
                           [(n, a, s, e) for a, s, e in spans])
        db.executemany("INSERT OR IGNORE INTO timeline_done VALUES (?)", [(n,) for n in part])
        db.commit()
        k = i + len(part)
        print(f"timeline: {k:,}/{len(todo):,} ({k / (time.time() - t0):.0f} CLs/s)", flush=True)


# ---------------------------------------------------------- interdiff stage

MAX_LINES = 50_000   # a patch set's diff bigger than this is not compared


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


def epoch(s):
    return int(datetime.strptime(s[:19].replace("T", " "), "%Y-%m-%d %H:%M:%S")
               .replace(tzinfo=timezone.utc).timestamp())


def diff_lines(git_dir, shas):
    """{sha: {path: (Counter of added lines, Counter of removed lines)} or None
    when too big}, each commit against its first parent, from one
    `git diff-tree --stdin -p -U0` process."""
    import threading
    from collections import Counter
    p = subprocess.Popen(["git", "--git-dir", git_dir, "diff-tree", "--stdin", "-p", "-U0", "--no-renames",
                          "--no-ext-diff", "--no-textconv"],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=ENV)
    w = threading.Thread(target=lambda: (p.stdin.write(("\n".join(shas) + "\n").encode()), p.stdin.close()))
    w.start()
    want, out = set(shas), {}
    cur = files = path = None
    in_hunk, n = False, 0
    for line in p.stdout:
        if len(line) == 41 and line[:40].decode(errors="replace") in want and line[40:] == b"\n":
            cur = line[:40].decode()
            files, n = {}, 0
            out[cur] = files
            continue
        if cur is None or out[cur] is None:
            continue
        if line.startswith(b"diff --git "):
            path = line[11:].rstrip(b"\n").split(b" b/", 1)[-1]
            files[path] = (Counter(), Counter())
            in_hunk = False
        elif line.startswith(b"@@"):
            in_hunk = True
        elif line.startswith(b"Binary files"):
            files[path][0][b"\0binary"] += 1
        elif in_hunk and line[:1] in (b"+", b"-"):
            files[path][0 if line[:1] == b"+" else 1][hash(line[1:])] += 1
            n += 1
            if n > MAX_LINES:
                out[cur] = None
    p.wait()
    w.join()
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
    have = {int(x) for x in open(fetched).read().split() if x.isdigit()}
    first = first_review_times()
    done = {r[0] for r in db.execute("SELECT change_number FROM interdiff")}
    ups = {}
    for n, ps, at, sha in tl.execute("SELECT change_number, ps, at, sha FROM uploads ORDER BY change_number, ps"):
        ups.setdefault(n, []).append((ps, at, sha))
    todo = sorted(n for n in have & first.keys() & ups.keys() if n not in done and n % shard[1] == shard[0])
    print(f"interdiff: {len(todo):,} CLs to compare ({len(done):,} done)", flush=True)
    t0 = time.time()
    for i in range(0, len(todo), batch):
        rows, pairs = [], {}
        for n in todo[i:i + batch]:
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
        db.executemany("INSERT OR REPLACE INTO interdiff VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
        db.commit()
        k = i + batch
        print(f"interdiff: {min(k, len(todo)):,}/{len(todo):,} ({k / (time.time() - t0):.0f} CLs/s)", flush=True)


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


def dir3(path):
    parts = path.split("/")[:-1]
    return "/".join(parts[:3]) + "/" if parts else "(root)/"


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
    db.execute(f"ATTACH 'file:{os.path.join(store.DATA_DIR, store.DERIVED_FILE)}?mode=ro' AS d")
    for st in ("git", "timeline", "interdiff"):
        db.execute(f"ATTACH 'file:{db_path(st)}?mode=ro' AS {st[0]}{st[1:3]}")
    print("cl: loading", flush=True)
    bots = {r[0] for r in db.execute("SELECT account_id FROM d.accounts WHERE is_bot = 1")}
    emails = dict(db.execute("SELECT account_id, email FROM d.accounts"))
    cls = db.execute("""SELECT change_number, owner_account, status, created_at, closed_at, close_week,
                               insertions, deletions, patchsets FROM d.changes
                        WHERE is_bot_owned = 0 AND project = 'chromium/src' AND branch = 'main'""").fetchall()
    landed = {}
    for cid, n, sha, files, ins, dels, rv, rl in db.execute(
            "SELECT commit_id, change_number, sha, files, ins, dels, reverts_sha IS NOT NULL, is_reland "
            "FROM git.gcommits WHERE change_number IS NOT NULL"):
        landed[n] = (cid, sha, files, ins + dels, rv, rl)
    reverted = {}
    for target, at in db.execute("SELECT reverts_sha, landed_at FROM git.gcommits WHERE reverts_sha IS NOT NULL"):
        reverted[target] = min(at, reverted.get(target, at))
    # Review from derived.sqlite, as summarize counts it (human non-owners).
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
    print(f"cl: joining {len(cls):,} CLs", flush=True)
    rows, att_rows = [], []
    for n, owner, status, created, closed, cweek, ins, dels, nps in cls:
        c0 = epoch(created)
        c1 = epoch(closed) if closed else None
        lg = landed.get(n) if status == "MERGED" else None
        r = rev.get(n)
        engaged = [t for t, replied in roots.get(n, []) if replied]
        first = (r[4] if r else None) or (min(engaged) if engaged else None)
        u = sorted(ups.get(n, []))
        rework_after = sum(1 for at, k, _ in u if first and at > first and k == "rework") if u and first else None
        a = att.get(n, [])
        hi = c1 or max([e for _, _, e in a] or [c0])
        others = [(s, e) for acct, s, e in a if acct != owner and acct not in bots]
        sent = min((s for s, e in others), default=None)
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
        per = defaultdict(list)
        for acct, s_, e_ in a:
            if acct != owner and acct not in bots:
                per[acct].append((s_, e_))
        for acct, sp in per.items():
            us = union_spans(sp, c0, hi)
            att_rows.append((n, acct, sum(e_ - s_ for s_, e_ in us) / 3600,
                             sum(weekday_seconds(s_, e_) for s_, e_ in us) / 3600))
        ous = union_spans(others, c0, hi)
        t = thr.get(n, [0, 0, 0])
        i = idf.get(n, (None,) * 7)
        rows.append((n, owner, emails.get(owner), status, c0, c1, cweek, ins, dels, nps,
                     lg[1] if lg else None, lg[2] if lg else None, lg[3] if lg else None,
                     lg[4] if lg else None, lg[5] if lg else None,
                     reverted.get(lg[1]) if lg else None,
                     r[0] if r else 0, r[1] if r else 0, len(r[2]) if r else 0, t[0], t[1], t[2],
                     first, sent, rework_after, rounds,
                     union_hours(others, c0, hi) if a else None,
                     sum(weekday_seconds(s_, e_) for s_, e_ in ous) / 3600 if a else None,
                     union_hours([(s, e) for acct, s, e in a if acct == owner], c0, hi) if a else None,
                     *(i if first else (None,) * 7)))
    db.executemany(f"INSERT INTO cl VALUES ({','.join('?' * 36)})", rows)
    db.executemany("INSERT INTO cl_attention VALUES (?,?,?,?)", att_rows)
    print("cl: directories", flush=True)
    paths = dict(db.execute("SELECT path_id, path FROM git.paths"))
    by_cid = {v[0]: n for n, v in landed.items()}
    agg = defaultdict(lambda: [0, 0])
    for cid, pid, ins, dels in db.execute("SELECT commit_id, path_id, ins, dels FROM git.gfiles"):
        n = by_cid.get(cid)
        if n is None:
            continue
        g = agg[(n, dir3(paths[pid]))]
        g[0] += 1
        g[1] += max(ins, 0) + max(dels, 0)
    db.executemany("INSERT INTO cl_dirs VALUES (?,?,?,?)", ((n, d, f, l) for (n, d), (f, l) in agg.items()))
    db.commit()
    print(f"cl: done, {len(rows):,} CLs, {len(agg):,} CL directories", flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="cosh.balance")
    ap.add_argument("stage", choices=["git", "timeline", "interdiff", "cl"])
    ap.add_argument("--db")
    ap.add_argument("--since", default=SINCE)
    ap.add_argument("--shard", default="0/1", help="interdiff: i/k, the CLs with number %% k == i")
    ap.add_argument("--week", help="timeline: only CLs closed in this ISO week (for tests)")
    args = ap.parse_args(argv)
    db = connect(args.db or db_path(args.stage))
    if args.stage == "git":
        stage_git(db, args.since)
    elif args.stage == "timeline":
        nums = None
        if args.week:
            d = sqlite3.connect(f"file:{os.path.join(store.DATA_DIR, store.DERIVED_FILE)}?mode=ro", uri=True)
            nums = [r[0] for r in d.execute("SELECT change_number FROM changes WHERE close_week = ? "
                                            "AND is_bot_owned = 0", (args.week,))]
        stage_timeline(db, nums)
    elif args.stage == "interdiff":
        stage_interdiff(db, shard=tuple(map(int, args.shard.split("/"))))
    else:
        stage_cl(db)


if __name__ == "__main__":
    main()
