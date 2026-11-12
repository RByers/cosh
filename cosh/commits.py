"""Chromium's main history, in data/private/commits.sqlite (docs/commits.md).

The one store of git history that every step and script reads: the Value
Exchange commits metric (summarize), the feedback coach, the balance stages
and scripts, the Feedback Index and the review-ROI scripts. Its one writer,
`python3 -m cosh commits` (also run at the end of a full `derive`), reads
the local bare clone (~/projects/shared/chromium, or $COSH_CHROMIUM_GIT) and
never fetches: GIT_NO_LAZY_FETCH=1 and no remote command. It is incremental
(it appends the commits that landed since its last run) and rebuildable
(delete the file and rerun, about 2 h, most of it the repetition ratios).

Tables (SCHEMA below has the columns):
  commits       every first-parent commit of main, with its first-parent
                diff's per-file line counts in commit_files (paths in paths)
  owners_added  each email address added to an OWNERS file
  repetition    the repetition ratio of commits with a CL and 10+ files
  gcommits, gfiles  views: the commits landed since 2017-01-01, the window
                the balance analyses use

commit_id is landing order: 1 is the first commit landed since 2017-01-01
(BALANCE_SINCE), counting up to the newest, and the older history counts
down from -1. So `commit_id > 0` is the balance window, and its ids, path ids
and row order are those of the former balance-git.sqlite.

$COSH_COMMITS_DB overrides the path (for a scratch copy).
"""

import fcntl
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from collections import Counter
from datetime import date, datetime, timezone

from . import store
from .bots import _PATTERNS

DEFAULT_REPO = os.path.expanduser("~/projects/shared/chromium")
COMMITS_FILE = "commits.sqlite"
ENV = {**os.environ, "GIT_NO_LAZY_FETCH": "1"}
# The balance window (commit_id > 0) starts at the first commit landed on or
# after this time, walking main back from its tip as `git log --since` does.
# It is "2017-01-01" as the former balance-git.sqlite had it: git's
# `--since=2017-01-01` keeps the current time of day, and its first run was
# at 21:47 Toronto time, so the window started at 2017-01-02 02:47 UTC (the 5
# commits landed on New Year's Day are older history here).
BALANCE_SINCE = "2017-01-02T02:47:00Z"
# Inputs as first made by hand (2026-11-08), by `git log --since=<day>` in
# Toronto time: OWNERS additions from 2012, AI markers from 2023.
OWNERS_SINCE = "2012-01-01T05:00:00Z"
AI_SINCE = "2023-01-01T05:00:00Z"
# Every commit since this week's Monday, if derived.sqlite names no fetched weeks.
FALLBACK_SINCE = "2023-06-26"
REP_MIN_FILES = 10     # repetition ratios for commits with a CL and this many files

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT) STRICT;
CREATE TABLE IF NOT EXISTS paths (path_id INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE) STRICT;
CREATE TABLE IF NOT EXISTS commits (
  commit_id     INTEGER PRIMARY KEY,    -- landing order; > 0 from BALANCE_SINCE on
  sha           TEXT    NOT NULL UNIQUE,
  author_email  TEXT    NOT NULL,       -- git author, lowercased
  author_name   TEXT    NOT NULL,
  authored_at   INTEGER NOT NULL,       -- unix seconds
  landed_at     INTEGER NOT NULL,       -- committer date
  change_number INTEGER,                -- chromium/src Reviewed-on; NULL if none
  is_bot        INTEGER NOT NULL,       -- Bot-Commit footer
  reviewed_by   TEXT,                   -- JSON list of lowercased emails, NULL if none
  reverts_sha   TEXT,                   -- "This reverts commit <sha>"
  is_revert     INTEGER NOT NULL,       -- a message line starts "This reverts commit" (SVN-era ones may name no sha)
  is_reland     INTEGER NOT NULL,       -- subject starts with "Reland"
  ai_marker     INTEGER NOT NULL,       -- AI_MARKER in the message
  files         INTEGER NOT NULL,       -- files in its first-parent diff
  ins           INTEGER NOT NULL,       -- text lines (binary files count 0)
  dels          INTEGER NOT NULL
) STRICT;
CREATE INDEX IF NOT EXISTS commits_cl ON commits(change_number);
CREATE INDEX IF NOT EXISTS commits_author ON commits(author_email, landed_at);
CREATE TABLE IF NOT EXISTS commit_files (
  commit_id INTEGER NOT NULL,
  path_id   INTEGER NOT NULL,
  ins       INTEGER NOT NULL,           -- -1 for binary
  dels      INTEGER NOT NULL,
  PRIMARY KEY (commit_id, path_id)
) STRICT, WITHOUT ROWID;
-- Each address on a line added to an OWNERS file (the first on the line),
-- in diff order: when people became owners where.
CREATE TABLE IF NOT EXISTS owners_added (
  commit_id INTEGER NOT NULL,
  seq       INTEGER NOT NULL,
  email     TEXT    NOT NULL,           -- lowercased
  path      TEXT    NOT NULL,           -- the OWNERS file
  PRIMARY KEY (commit_id, seq)
) STRICT, WITHOUT ROWID;
-- 1 - distinct changed lines / changed lines of the commit's diff (near 1:
-- the same edit in many places). ratio NULL: over balance.MAX_LINES lines.
CREATE TABLE IF NOT EXISTS repetition (commit_id INTEGER PRIMARY KEY, ratio REAL) STRICT;
CREATE VIEW IF NOT EXISTS gcommits AS
  SELECT commit_id, sha, author_email, authored_at, landed_at, change_number, is_bot, reviewed_by,
         reverts_sha, is_reland, files, ins, dels FROM commits WHERE commit_id > 0;
CREATE VIEW IF NOT EXISTS gfiles AS SELECT commit_id, path_id, ins, dels FROM commit_files WHERE commit_id > 0;
"""

REVIEWED_ON = re.compile(r"chromium-review\.googlesource\.com/(?:c/)?(?:chromium/src/\+/)?(\d+)$")
REVERTS = re.compile(r"^This reverts commit ([0-9a-f]{40})", re.M)
AI_MARKER = re.compile(r"^Agent-Generated:|[Gg]enerated (by|with|using) (Gemini|Claude|an? (AI|LLM)|Jetski|Cider"
                       r"|Copilot)|^Co-[Aa]uthored-[Bb]y: (Claude|Gemini|Copilot)", re.M)
OWNER_EMAIL = re.compile(rb"[A-Za-z0-9._%-][A-Za-z0-9._%+-]*@[A-Za-z0-9.-]+\.[a-z]+")
EMAIL = re.compile(r"<([^>]+)>")
SEP = "\x1e"
FMT = SEP.join(["%x01%x02%x03%H", "%ae", "%an", "%at", "%ct", "%s",
                "%(trailers:key=Reviewed-on,valueonly,separator=%x1f)",
                "%(trailers:key=Reviewed-by,valueonly,separator=%x1f)",
                "%(trailers:key=Bot-Commit,valueonly,separator=%x1f)", "%b%x02"])


def repo_path():
    return os.environ.get("COSH_CHROMIUM_GIT") or DEFAULT_REPO


def db_path(data_dir=None):
    return os.environ.get("COSH_COMMITS_DB") or os.path.join(data_dir or store.DATA_DIR, COMMITS_FILE)


def connect(path=None):
    path = path or db_path()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    db = sqlite3.connect(path, timeout=60)
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript(SCHEMA)
    return db


def open_ro(path=None):
    """The store read-only, or None if it doesn't exist yet."""
    path = path or db_path()
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True) if os.path.exists(path) else None


def is_bot_email(email):
    return any(p.search(email) for p in _PATTERNS)


def unix(iso):
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())


def _git(repo, *args, check=True):
    p = subprocess.run(["git", "-C", repo, *args], env=ENV, capture_output=True, text=True)
    if check and p.returncode:
        raise SystemExit(f"git {args[0]} in {repo} failed: {p.stderr.strip()}")
    return p.stdout.strip() if p.returncode == 0 else None


# ------------------------------------------------------------------ writing

def _ingest(db, repo, revs, ids, paths, label):
    """Reads `git log --first-parent --numstat` of `revs` in one process and
    inserts each commit not yet stored, numbering them from the iterator
    `ids` in the order git lists them."""
    p = subprocess.Popen(["git", "--git-dir", repo, "log", "--first-parent", "--no-renames", "--numstat",
                          f"--format={FMT}", *revs], stdout=subprocess.PIPE, env=ENV)
    buf, n, t0 = b"", 0, time.time()

    def flush(rec):
        nonlocal n
        head, _, stat = rec.partition(b"\x02")
        parts = head.decode("utf-8", "replace").split(SEP)
        if len(parts) < 10 or not re.fullmatch(r"[0-9a-f]{40}", parts[0]):
            print(f"commits: skipped a malformed record: {head[:60]!r}", flush=True)
            return
        sha, email, name, at, ct, subj, ron, rby, bot, body = parts[:10]
        if db.execute("SELECT 1 FROM commits WHERE sha = ?", (sha,)).fetchone():
            return
        m = REVIEWED_ON.search(ron.split("\x1f")[0].strip()) if ron else None
        rb = [e.lower() for v in rby.split("\x1f") if v for e in EMAIL.findall(v)]
        rv = REVERTS.search(body)
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
        cid = next(ids)
        db.execute("INSERT INTO commits VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (cid, sha, email.lower(), name, int(at), int(ct), int(m.group(1)) if m else None,
                    int(bool(bot.strip())), json.dumps(rb) if rb else None, rv.group(1) if rv else None,
                    0,                                  # is_revert: set by _reverts
                    int(subj.lower().startswith("reland")), int(bool(AI_MARKER.search(subj + "\n" + body))),
                    len(files), ins, dels))
        db.executemany("INSERT OR IGNORE INTO commit_files VALUES (?,?,?,?)", [(cid, *f) for f in files])
        n += 1
        if n % 5000 == 0:
            db.commit()
            print(f"commits ({label}): {n:,}, {datetime.fromtimestamp(int(ct), timezone.utc):%Y-%m-%d}, "
                  f"{n / (time.time() - t0):.0f}/s", flush=True)

    with p:
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
    return n


def _count_from(start, step):
    while True:
        yield start
        start += step


def _reverts(db, repo, tip):
    """Sets is_revert on the commits since the last run's tip whose message
    has a line starting "This reverts commit" (`git log --grep`: any line,
    the subject's paragraph too)."""
    done = db.execute("SELECT v FROM meta WHERE k = 'reverts_through'").fetchone()
    revs = [f"{done[0]}..{tip}"] if done else [tip]
    shas = _git(repo, "log", "--first-parent", "--grep=^This reverts commit", "--format=%H", *revs).split()
    with db:
        db.executemany("UPDATE commits SET is_revert = 1 WHERE sha = ?", [(s,) for s in shas])
        db.execute("INSERT OR REPLACE INTO meta VALUES ('reverts_through', ?)", (tip,))
    return len(shas)


def _owners(db, repo, tip):
    """Appends owners_added for the commits since the last run's tip."""
    done = db.execute("SELECT v FROM meta WHERE k = 'owners_through'").fetchone()
    revs = [f"{done[0]}..{tip}"] if done else [tip]
    p = subprocess.Popen(["git", "--git-dir", repo, "log", "--first-parent", "-p", "-U0", "--no-renames",
                          "--format=%x01%H", *revs, "--", "*OWNERS"], stdout=subprocess.PIPE, env=ENV)
    with p:
        rows = _owner_rows(db, p.stdout)
    rc = p.wait()
    if rc:
        raise SystemExit(f"git log exited {rc}; rerun to resume")
    with db:
        db.executemany("INSERT OR IGNORE INTO owners_added VALUES (?,?,?,?)", rows)
        db.execute("INSERT OR REPLACE INTO meta VALUES ('owners_through', ?)", (tip,))
    return len(rows)


def _owner_rows(db, lines):
    """(commit_id, seq, email, path) for each address on an added line of
    an OWNERS file (the first on the line) in `git log -p` output."""
    cid = seq = path = None
    rows = []
    for line in lines:
        if line.startswith(b"\x01"):
            sha = line[1:].strip().decode()
            cid = db.execute("SELECT commit_id FROM commits WHERE sha = ?", (sha,)).fetchone()
            if cid is None:
                raise SystemExit(f"owners: {sha} is not in commits")
            cid, seq = cid[0], 0
        elif line.startswith(b"+++ b/"):
            path = line[6:].rstrip(b"\n").decode("utf-8", "replace")
        elif line[:1] == b"+" and len(line) > 1 and line[1:2] not in (b"+", b"\n"):
            m = OWNER_EMAIL.search(line, 1)
            if m and path is not None:
                rows.append((cid, seq, m.group().decode().lower(), path))
                seq += 1
    return rows


def ratios(repo, shas):
    """{sha: repetition ratio, or None over balance.MAX_LINES} of commits
    against their first parent: 1 - distinct changed lines / changed lines.
    Mechanical edits (the same line added in 300 files, renames of a symbol)
    score near 1."""
    from .balance import diff_lines
    out = {}
    for sha, files in diff_lines(repo, shas).items():
        if files is None:
            out[sha] = None
            continue
        tot, distinct = 0, set()
        for a, d in files.values():
            for k, v in list(a.items()) + list(d.items()):
                tot += v
                distinct.add(k)
        out[sha] = 1 - len(distinct) / tot if tot else 0.0
    return out


def _repetition(db, repo, jobs):
    todo = db.execute("SELECT c.commit_id, c.sha FROM commits c LEFT JOIN repetition r USING (commit_id) "
                      "WHERE c.change_number IS NOT NULL AND c.files >= ? AND r.commit_id IS NULL "
                      "ORDER BY c.commit_id", (REP_MIN_FILES,)).fetchall()
    if not todo:
        return 0
    from concurrent.futures import ProcessPoolExecutor
    ids = dict((s, c) for c, s in todo)
    shas = [s for _, s in todo]
    parts = [shas[i:i + 300] for i in range(0, len(shas), 300)]
    n, t0 = 0, time.time()
    with ProcessPoolExecutor(max_workers=jobs) as ex:
        for got in ex.map(ratios, [repo] * len(parts), parts):
            with db:
                db.executemany("INSERT OR REPLACE INTO repetition VALUES (?,?)",
                               [(ids[s], r) for s, r in got.items()])
            n += len(got)
            if n % 6000 < 300:
                print(f"commits: repetition {n:,} of {len(shas):,}, {n / (time.time() - t0):.0f}/s", flush=True)
    return n


def update(path=None, repo=None, jobs=4):
    """Brings the store up to date with the clone's main: new commits, then
    (on the first runs) the history before BALANCE_SINCE, then OWNERS
    additions and repetition ratios for whatever is new. Resumable."""
    repo = repo or repo_path()
    if not os.path.isdir(repo):
        raise SystemExit(f"no Chromium git repo at {repo} (set COSH_CHROMIUM_GIT)")
    path = path or db_path()
    db = connect(path)
    lock = open(path + ".lock", "w")
    fcntl.flock(lock, fcntl.LOCK_EX)
    try:
        repo = _git(repo, "rev-parse", "--absolute-git-dir")    # a bare clone, or a test's work tree
        tip = _git(repo, "rev-parse", "--verify", "main^{commit}")
        paths = dict(db.execute("SELECT path, path_id FROM paths"))
        top = db.execute("SELECT max(commit_id), min(commit_id) FROM commits").fetchone()
        if top[0] is None or top[0] < 1:
            n = _ingest(db, repo, ["--reverse", f"--since={BALANCE_SINCE}", tip], _count_from(1, 1),
                        paths, f"since {BALANCE_SINCE[:10]}")
        else:
            newest = db.execute("SELECT sha FROM commits WHERE commit_id = ?", (top[0],)).fetchone()[0]
            n = _ingest(db, repo, ["--reverse", f"{newest}..{tip}"], _count_from(top[0] + 1, 1), paths, "new")
        print(f"commits: {n:,} new", file=sys.stderr, flush=True)
        if not db.execute("SELECT 1 FROM meta WHERE k = 'history_complete'").fetchone():
            low = db.execute("SELECT min(commit_id) FROM commits").fetchone()[0]
            if low is not None:
                oldest = db.execute("SELECT sha FROM commits WHERE commit_id = ?", (low,)).fetchone()[0]
                parent = _git(repo, "rev-parse", "--verify", "-q", f"{oldest}^1^{{commit}}", check=False)
                if parent:
                    k = _ingest(db, repo, [parent], _count_from(min(low, 0) - 1, -1), paths, "older history")
                    print(f"commits: {k:,} older", file=sys.stderr, flush=True)
            with db:
                db.execute("INSERT OR REPLACE INTO meta VALUES ('history_complete', ?)", (store.now_iso(),))
        del paths
        k = _reverts(db, repo, tip)
        print(f"commits: {k:,} reverts", file=sys.stderr, flush=True)
        k = _owners(db, repo, tip)
        print(f"commits: {k:,} OWNERS additions", file=sys.stderr, flush=True)
        k = _repetition(db, repo, jobs)
        print(f"commits: {k:,} repetition ratios", file=sys.stderr, flush=True)
        with db:
            db.execute("INSERT OR REPLACE INTO meta VALUES ('updated_at', ?)", (store.now_iso(),))
            db.execute("INSERT OR REPLACE INTO meta VALUES ('tip', ?)", (tip,))
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()
        db.close()


# ------------------------------------------------------------------ reading

def window_start(db, since):
    """The commit_id before the window that `git log --since=<since>` lists:
    the newest commit landed before `since` (an ISO time or unix seconds).
    A commit is in the window if its commit_id is greater."""
    ts = since if isinstance(since, int) else unix(since)
    lo = db.execute("SELECT max(commit_id) FROM commits WHERE landed_at < ?", (ts,)).fetchone()[0]
    if lo is None:
        lo = (db.execute("SELECT min(commit_id) FROM commits").fetchone()[0] or 1) - 1
    return lo


def derived_since(ddb):
    """Monday of the oldest week fetched into derived.sqlite (the Value
    Exchange window), as 'YYYY-MM-DD'."""
    weeks = [w for (v,) in ddb.execute("SELECT v FROM meta WHERE k = 'fetched_weeks'")
             for w in json.loads(v or "[]")]
    if not weeks:
        return FALLBACK_SINCE
    y, w = min(weeks).split("-W")
    return date.fromisocalendar(int(y), int(w), 1).isoformat()


def dirs_of(db, lo, ids=None):
    """{commit_id: Counter(paths.directory -> files)} for the commits after
    `lo`, or only `ids`."""
    from .paths import directory
    cache, out = {}, {}
    if ids is None:
        rows = db.execute("SELECT commit_id, path_id FROM commit_files WHERE commit_id > ?", (lo,))
    else:
        ids = sorted(ids)
        rows = (r for i in range(0, len(ids), 500) for r in db.execute(
            f"SELECT commit_id, path_id FROM commit_files WHERE commit_id IN ({','.join('?' * len(ids[i:i + 500]))})",
            ids[i:i + 500]))
    for cid, pid in rows:
        d = cache.get(pid)
        if d is None:
            d = cache[pid] = sys.intern(directory(
                db.execute("SELECT path FROM paths WHERE path_id = ?", (pid,)).fetchone()[0]))
        c = out.get(cid)
        if c is None:
            c = out[cid] = Counter()
        c[d] += 1
    return out


def value_commits(db, ddb):
    """The commits the Value Exchange page counts, newest first: those landed
    since derived.sqlite's oldest fetched week. Yields (commit_id, CL, author
    email, landed 'YYYY-MM-DD HH:MM:SS' UTC, is_bot, files). A commit is a
    bot's if its CL's owner is a bot (changes.is_bot_owned) or config/bots.txt
    matches its git author: some bots (e.g. a WebLayer builder) author commits
    on CLs a person owns. Also returns the window's lower bound."""
    lo = window_start(db, derived_since(ddb) + "T00:00:00Z")
    bot_owned = dict(ddb.execute("SELECT change_number, is_bot_owned FROM changes WHERE branch = 'main'"))
    rows = []
    for cid, cl, email, landed, files in db.execute(
            "SELECT commit_id, change_number, author_email, landed_at, files FROM commits WHERE commit_id > ? "
            "ORDER BY commit_id DESC", (lo,)):
        bot = bool(bot_owned.get(cl)) or is_bot_email(email)
        day = datetime.fromtimestamp(landed, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        rows.append((cid, cl, email, day, int(bot), files))
    return rows, lo


def first_commits(db):
    """{email: (authored_at, Bot-Commit footer)} of each author's first commit
    on main, over all of its history (first_commit.txt as was)."""
    return {e: (t, b) for e, t, b, _ in db.execute(
        "SELECT author_email, authored_at, is_bot, min(commit_id) FROM commits GROUP BY author_email")}


def owners_added(db, since=OWNERS_SINCE):
    """[(authored_at, email, OWNERS path)], newest first, for the commits since
    `since` (owners_added.txt as was)."""
    return db.execute("SELECT c.authored_at, o.email, o.path FROM owners_added o JOIN commits c USING (commit_id) "
                      "WHERE o.commit_id > ? ORDER BY o.commit_id DESC, o.seq",
                      (window_start(db, since),)).fetchall()


def ai_marked(db, since=AI_SINCE):
    """Shas of the commits since `since` whose message has an AI marker."""
    return {s for s, in db.execute("SELECT sha FROM commits WHERE ai_marker = 1 AND commit_id > ?",
                                   (window_start(db, since),))}


def repetition(db):
    """{sha: repetition ratio or None} of the commits that have one."""
    return dict(db.execute("SELECT c.sha, r.ratio FROM repetition r JOIN commits c USING (commit_id)"))


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="cosh commits")
    ap.add_argument("--db", help=f"store path (default: $COSH_COMMITS_DB or data/private/{COMMITS_FILE})")
    ap.add_argument("--jobs", type=int, default=4, help="git diff processes for the repetition ratios")
    a = ap.parse_args(argv)
    update(a.db, jobs=max(1, min(a.jobs, 4)))
