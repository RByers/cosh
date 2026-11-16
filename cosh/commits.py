"""Chromium's main history, in data/private/commits.sqlite (docs/commits.md).

The one store of git history that every step and script reads: the Value
Exchange commits metric (summarize), the Feedback Index (cosh/review_feedback.py),
the feedback coach, and the analyses. Its one writer,
`python3 -m cosh commits` (also run at the end of a full `derive`), reads
the local bare clone (~/cache/chromium, or $COSH_CHROMIUM_GIT) and
never fetches: GIT_NO_LAZY_FETCH=1 and no remote command. It is incremental
(it appends the commits that landed since its last run) and rebuildable
(delete the file and rerun, about 1 h 50 min: config/dataflow.json).

Tables (SCHEMA below has the columns):
  commits       every first-parent commit of main, with its first-parent
                diff's per-file line counts in commit_files (paths in paths)
  owners_added  each email address added to an OWNERS file
  repetition    the repetition ratio of commits with a CL and 10+ files
  renames       files git finds renamed in a commit, and tip_paths the
                files at main's tip: current_paths names each path as it
                is today, so directories can be followed across renames

commit_id is landing order: 1 is the first commit landed since 2017-01-01
(HISTORY_SINCE), counting up to the newest, and the older history counts
down from -1. So `commit_id > 0` is the per-CL window.

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

from . import codefp, store
from .bots import _PATTERNS

DEFAULT_REPO = os.path.expanduser("~/cache/chromium")
COMMITS_FILE = "commits.sqlite"
ENV = {**os.environ, "GIT_NO_LAZY_FETCH": "1"}
# The per-CL window (commit_id > 0) starts at the first commit landed on or
# after this time, walking main back from its tip as `git log --since` does.
# It is "2017-01-01" as first built: git's `--since=2017-01-01` keeps the
# current time of day, and that run was at 21:47 Toronto time, so the window
# started at 2017-01-02 02:47 UTC (the 5 commits landed on New Year's Day are
# older history here).
HISTORY_SINCE = "2017-01-02T02:47:00Z"
# Inputs as first made by hand (2026-11-08), by `git log --since=<day>` in
# Toronto time: OWNERS additions from 2012, AI markers from 2023.
OWNERS_SINCE = "2012-01-01T05:00:00Z"
AI_SINCE = "2023-01-01T05:00:00Z"
# Every commit since this week's Monday, if reviews.sqlite names no fetched weeks.
FALLBACK_SINCE = "2023-06-26"
REP_MIN_FILES = 10     # repetition ratios for commits with a CL and this many files

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT) STRICT;
-- Paths raw (git's C-quoting of unusual names undone: unquote_path).
CREATE TABLE IF NOT EXISTS paths (path_id INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE) STRICT;
CREATE TABLE IF NOT EXISTS commits (
  commit_id     INTEGER PRIMARY KEY,    -- landing order; > 0 from HISTORY_SINCE on
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
  dels          INTEGER NOT NULL,
  is_lsc        INTEGER NOT NULL DEFAULT 0  -- part of a large-scale change (LSC_GREP; set by _lsc)
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
-- the same edit in many places). ratio NULL: over MAX_LINES lines.
CREATE TABLE IF NOT EXISTS repetition (commit_id INTEGER PRIMARY KEY, ratio REAL) STRICT;
-- Files git finds renamed (-M) in a commit's first-parent diff: what
-- current_paths follows to give each path its name at main's tip.
CREATE TABLE IF NOT EXISTS renames (
  commit_id   INTEGER NOT NULL,
  old_path_id INTEGER NOT NULL,
  new_path_id INTEGER NOT NULL,
  ins         INTEGER,                  -- lines added and deleted between the two (the edit, without the move);
  dels        INTEGER,                  -- -1 for binary; NULL in rows from before the columns
  PRIMARY KEY (commit_id, old_path_id)
) STRICT, WITHOUT ROWID;
-- The files at main's tip as of the last run (path ids of commit_files' paths).
CREATE TABLE IF NOT EXISTS tip_paths (path_id INTEGER PRIMARY KEY) STRICT;
-- Compatibility views of balance-git.sqlite, retired 2026-11-14: readers say commit_id > 0.
DROP VIEW IF EXISTS gcommits;
DROP VIEW IF EXISTS gfiles;
"""

REVIEWED_ON = re.compile(r"chromium-review\.googlesource\.com/(?:c/)?(?:chromium/src/\+/)?(\d+)$")
REVERTS = re.compile(r"^This reverts commit ([0-9a-f]{40})", re.M)
AI_MARKER = re.compile(r"^Agent-Generated:|[Gg]enerated (by|with|using) (Gemini|Claude|an? (AI|LLM)|Jetski|Cider"
                       r"|Copilot)|^Co-[Aa]uthored-[Bb]y: (Claude|Gemini|Copilot)", re.M)
# A large-scale change (LSC): the word LSC or "large-scale change" anywhere in
# the message (the LSC process's "See the LSC doc at go/lsc-chrome-...",
# "LSC:" and "LSC-Id:" lines), or `git cl split`'s footer. Such CLs are
# reviewed by policy, not line by line: since 2023-07 they drew 0.78 review
# comments per CL against 3.67, a quarter to a fifth at any size, which skews
# per-person review measures (GitHub issue #3, docs/commits.md). A Perl
# regex for `git log -i -P --grep`, matched line by line.
REVERT_GREP = "^This reverts commit"     # _reverts: `git log --grep`
LSC_GREP = r"\bLSC\b|large[- ]scale (code )?change|^This CL was uploaded by git cl split"
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
    if "is_lsc" not in {r[1] for r in db.execute("PRAGMA table_info(commits)")}:
        with db:                    # a store from before is_lsc: _lsc tags its commits on the next update
            db.execute("ALTER TABLE commits ADD COLUMN is_lsc INTEGER NOT NULL DEFAULT 0")
    if not db.execute("SELECT 1 FROM meta WHERE k = 'paths_raw'").fetchone():
        with db:                    # paths stored C-quoted, as git printed them (before 2026-11-14): unquote
            for pid, p in db.execute("SELECT path_id, path FROM paths WHERE path LIKE '\"%\"'").fetchall():
                db.execute("UPDATE paths SET path = ? WHERE path_id = ?", (unquote_path(p), pid))
            db.execute("INSERT OR REPLACE INTO meta VALUES ('paths_raw', '1')")
    if "ins" not in {r[1] for r in db.execute("PRAGMA table_info(renames)")}:
        with db:                    # renames from before the line counts: _renames redoes their commits
            db.execute("ALTER TABLE renames ADD COLUMN ins INTEGER")
            db.execute("ALTER TABLE renames ADD COLUMN dels INTEGER")
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


def fetch_main(repo=None):
    """Brings the shared clone's main up to date: one fetch of main only, no
    tags, with the contact headers (its README: cosh does these fetches,
    under cosh's extract lock, which the caller holds). Returns (old, new)
    tip."""
    from .contact import git_config, git_env
    repo = repo or repo_path()
    old = _git(repo, "rev-parse", "refs/heads/main")
    p = subprocess.run(["git", "--git-dir", repo, *git_config(), "fetch", "--no-tags", "--quiet",
                        "https://chromium.googlesource.com/chromium/src.git", "+refs/heads/main:refs/heads/main"],
                       env={**ENV, **git_env()}, capture_output=True, text=True)
    if p.returncode:
        raise SystemExit(f"fetch of main into {repo} failed: {p.stderr.strip()}")
    return old, _git(repo, "rev-parse", "refs/heads/main")


# ------------------------------------------------------------------ writing

INGEST_ARGS = ["log", "--first-parent", "--no-renames", "--numstat"]


def _ingest(db, repo, revs, ids, paths, label):
    """Reads `git log --first-parent --numstat` of `revs` in one process and
    inserts each commit not yet stored, numbering them from the iterator
    `ids` in the order git lists them."""
    p = subprocess.Popen(["git", "--git-dir", repo, *INGEST_ARGS, f"--format={FMT}", *revs],
                         stdout=subprocess.PIPE, env=ENV)
    buf, n, t0 = b"", 0, time.time()

    def flush(rec):
        nonlocal n
        head, _, stat = rec.partition(b"\x02")
        parts = head.decode("utf-8", "replace").split(SEP)
        if len(parts) < 10 or not re.fullmatch(r"[0-9a-f]{40}", parts[0]):
            print(f"commits: skipped a malformed record: {head[:60]!r}", flush=True)
            return
        sha, email, name, at, ct = parts[:5]
        if db.execute("SELECT 1 FROM commits WHERE sha = ?", (sha,)).fetchone():
            return
        cl, is_bot, rb, rv, reland, ai = _message_fields(*parts[5:10])
        files = []
        for path, a, d in _numstat(stat):
            pid = paths.get(path)
            if pid is None:
                pid = paths[path] = db.execute("INSERT INTO paths(path) VALUES (?)", (path,)).lastrowid
            files.append((pid, a, d))
        cid = next(ids)
        db.execute("INSERT INTO commits VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (cid, sha, email.lower(), name, int(at), int(ct), cl, is_bot, rb, rv,
                    0,                                  # is_revert: set by _reverts
                    reland, ai, len(files),
                    sum(max(a, 0) for _, a, _ in files), sum(max(d, 0) for _, _, d in files),
                    0))                                 # is_lsc: set by _lsc
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


def _message_fields(subj, ron, rby, bot, body):
    """(change_number, is_bot, reviewed_by, reverts_sha, is_reland,
    ai_marker) of a commit, from FMT's subject, trailers and body."""
    m = REVIEWED_ON.search(ron.split("\x1f")[0].strip()) if ron else None
    rb = [e.lower() for v in rby.split("\x1f") if v for e in EMAIL.findall(v)]
    rv = REVERTS.search(body)
    return (int(m.group(1)) if m else None, int(bool(bot.strip())), json.dumps(rb) if rb else None,
            rv.group(1) if rv else None, int(subj.lower().startswith("reland")),
            int(bool(AI_MARKER.search(subj + "\n" + body))))


def _numstat(stat):
    """[(raw path, added, deleted)] of a commit's `--numstat` lines (bytes);
    -1 and -1 for a binary file."""
    out = []
    for line in stat.decode("utf-8", "replace").splitlines():
        if not line.strip():
            continue
        f = line.split("\t", 2)
        if len(f) != 3 or not (f[0].isdigit() or f[0] == "-"):
            continue
        a, d, path = f
        out.append((unquote_path(path),             # git C-quotes unusual paths; the store keeps them raw
                    *((-1, -1) if a == "-" else (int(a), int(d)))))
    return out


def _remessage(db, repo, tip):
    """Recomputes _message_fields for every stored commit, from one
    `git log` of messages only, in one transaction (part "messages")."""
    p = subprocess.Popen(["git", "--git-dir", repo, "log", "--first-parent", f"--format={FMT}", tip],
                         stdout=subprocess.PIPE, env=ENV)
    rows, buf = [], b""

    def take(rec):
        parts = rec.split(b"\x02")[0].decode("utf-8", "replace").split(SEP)
        if len(parts) >= 10 and re.fullmatch(r"[0-9a-f]{40}", parts[0]):
            rows.append((*_message_fields(*parts[5:10]), parts[0]))
    with p:
        for chunk in iter(lambda: p.stdout.read(1 << 20), b""):
            buf += chunk
            recs = buf.split(b"\x01\x02\x03")
            buf = recs.pop()
            for rec in recs:
                if rec.strip():
                    take(rec)
        if buf.strip():
            take(buf)
    if p.wait():
        raise SystemExit("git log failed; rerun to retry")
    db.executemany("UPDATE commits SET change_number = ?, is_bot = ?, reviewed_by = ?, reverts_sha = ?, "
                   "is_reland = ?, ai_marker = ? WHERE sha = ?", rows)
    return len(rows)


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
    shas = _git(repo, "log", "--first-parent", f"--grep={REVERT_GREP}", "--format=%H", *revs).split()
    with db:
        db.executemany("UPDATE commits SET is_revert = 1 WHERE sha = ?", [(s,) for s in shas])
        db.execute("INSERT OR REPLACE INTO meta VALUES ('reverts_through', ?)", (tip,))
    return len(shas)


def _lsc(db, repo, tip):
    """Sets is_lsc on the commits since the last run's tip whose message
    matches LSC_GREP (all of history on the first run)."""
    done = db.execute("SELECT v FROM meta WHERE k = 'lsc_through'").fetchone()
    revs = [f"{done[0]}..{tip}"] if done else [tip]
    shas = _git(repo, "log", "--first-parent", "-i", "-P", f"--grep={LSC_GREP}", "--format=%H", *revs).split()
    with db:
        db.executemany("UPDATE commits SET is_lsc = 1 WHERE sha = ?", [(s,) for s in shas])
        db.execute("INSERT OR REPLACE INTO meta VALUES ('lsc_through', ?)", (tip,))
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


# Rename detection (`git diff-tree -M`) looks only at commits that could
# hold a rename: by --no-renames line counts, a deleted-looking file
# (0 added) and an added-looking one (0 deleted), or two binary or two empty
# files. 147k of 1.68M commits, about 12 min. Inexact renames are looked for
# among at most RENAME_LIMIT files a side (git's -l).
RENAME_CANDIDATES = """SELECT f.commit_id, c.sha FROM commit_files f JOIN commits c USING (commit_id)
  WHERE f.commit_id > ? GROUP BY f.commit_id
  HAVING (sum(f.ins = 0 AND f.dels > 0) > 0 AND sum(f.dels = 0 AND f.ins > 0) > 0)
      OR sum(f.ins = -1) >= 2 OR sum(f.ins = 0 AND f.dels = 0) >= 2
  ORDER BY f.commit_id"""
RENAME_LIMIT = 5000


_C_ESCAPES = {"a": 7, "b": 8, "t": 9, "n": 10, "v": 11, "f": 12, "r": 13, '"': 34, "\\": 92}


def unquote_path(p):
    """A path as git prints it without -z (C-quoted when it has non-ASCII
    bytes or special characters) as raw text, as the paths table keeps it."""
    if not (len(p) >= 2 and p[0] == '"' and p[-1] == '"'):
        return p
    out, i, s = bytearray(), 0, p[1:-1]
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s):
            nx = s[i + 1]
            if len(s) >= i + 4 and all(c in "01234567" for c in s[i + 1:i + 4]):
                out.append(int(s[i + 1:i + 4], 8))
                i += 4
                continue
            if nx in _C_ESCAPES:
                out.append(_C_ESCAPES[nx])
                i += 2
                continue
        out += ch.encode("utf-8", "surrogateescape")
        i += 1
    return out.decode("utf-8", "surrogateescape")


def _renames(db, repo):
    """Appends renames, with the lines changed between the two names, for the
    commits after the last run's (all of history on the first run), and
    redoes commits whose renames have no line counts yet; from one
    `git diff-tree --stdin -z -M --numstat` process."""
    import threading
    done = db.execute("SELECT v FROM meta WHERE k = 'renames_through'").fetchone()
    lo = int(done[0]) if done else -(1 << 62)
    todo = db.execute(RENAME_CANDIDATES, (lo,)).fetchall()
    todo += db.execute("SELECT DISTINCT r.commit_id, c.sha FROM renames r JOIN commits c USING (commit_id) "
                       "WHERE r.ins IS NULL").fetchall()
    top = db.execute("SELECT max(commit_id) FROM commits").fetchone()[0]
    ids = {sha: cid for cid, sha in todo}
    if not ids:
        if top is not None:
            with db:
                db.execute("INSERT OR REPLACE INTO meta VALUES ('renames_through', ?)", (str(top),))
        return 0
    pid = dict(db.execute("SELECT path, path_id FROM paths"))    # raw, as -z prints them
    p = subprocess.Popen(["git", "--git-dir", repo, "diff-tree", "--stdin", "-z", "-r", "-M", f"-l{RENAME_LIMIT}",
                          "--diff-filter=R", "--numstat"],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=ENV)
    w = threading.Thread(target=lambda: (p.stdin.write("".join(s + "\n" for s in ids).encode()), p.stdin.close()))
    w.start()
    rows, cid, n = [], None, 0

    def tokens():
        buf = b""
        for chunk in iter(lambda: p.stdout.read(1 << 20), b""):
            buf += chunk
            *done, buf = buf.split(b"\0")
            yield from done
        if buf:
            yield buf
    with p:
        it = tokens()
        for t in it:
            t = t.decode("utf-8", "surrogateescape").lstrip("\n")
            if t in ids:
                cid = ids[t]
                continue
            f = t.split("\t")              # "<added>\t<deleted>\t", then the old and new paths
            if len(f) != 3 or f[2]:
                continue
            old = next(it, b"").decode("utf-8", "surrogateescape")
            new = next(it, b"").decode("utf-8", "surrogateescape")
            a, b = pid.get(old), pid.get(new)
            if cid is not None and a is not None and b is not None:
                rows.append((cid, a, b, -1 if f[0] == "-" else int(f[0]), -1 if f[1] == "-" else int(f[1])))
            if len(rows) >= 50_000:
                n += len(rows)
                with db:
                    db.executemany("INSERT OR REPLACE INTO renames VALUES (?,?,?,?,?)", rows)
                rows = []
    rc = p.wait()
    w.join()
    if rc:
        raise SystemExit(f"git diff-tree exited {rc}; rerun to resume")
    n += len(rows)
    with db:
        db.executemany("INSERT OR REPLACE INTO renames VALUES (?,?,?,?,?)", rows)
        db.execute("DELETE FROM renames WHERE ins IS NULL")    # redone above, and no longer found
        if top is not None:
            db.execute("INSERT OR REPLACE INTO meta VALUES ('renames_through', ?)", (str(top),))
    return n


def _tip_paths(db, repo, tip):
    """Replaces tip_paths with the files at `tip` (`git ls-tree`), those
    commit_files has a path for."""
    p = subprocess.run(["git", "--git-dir", repo, "ls-tree", "-r", "--name-only", tip],
                       env=ENV, capture_output=True, check=True)
    pid = dict(db.execute("SELECT path, path_id FROM paths"))
    have = [(pid[x],) for x in map(unquote_path, p.stdout.decode("utf-8", "replace").splitlines()) if x in pid]
    with db:
        db.execute("DELETE FROM tip_paths")
        db.executemany("INSERT INTO tip_paths VALUES (?)", have)
    return len(have)


MAX_LINES = 50_000   # a patch set's diff bigger than this is not compared


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


def ratios(repo, shas):
    """{sha: repetition ratio, or None over MAX_LINES} of commits
    against their first parent: 1 - distinct changed lines / changed lines.
    Mechanical edits (the same line added in 300 files, renames of a symbol)
    score near 1."""
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


REPETITION_TODO = """SELECT c.commit_id, c.sha FROM commits c LEFT JOIN repetition r USING (commit_id)
  WHERE c.change_number IS NOT NULL AND c.files >= ? AND r.commit_id IS NULL ORDER BY c.commit_id"""


def _repetition(db, repo, jobs):
    todo = db.execute(REPETITION_TODO, (REP_MIN_FILES,)).fetchall()
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


# ------------------------------------------------------- code fingerprints
#
# Each part of the store keeps a fingerprint of the code that computed it
# (cosh/codefp.py, meta rows 'code_fp:<part>'). When one changes, update()
# redoes that part alone: it resets the part's rows and marker in the same
# transaction that records the new fingerprint, then the part's step
# recomputes all of history. "messages" is recomputed in place from one
# `git log` of messages (a minute or two). "core" (the commits, their
# numstat and paths, which every other part hangs off) is the whole store:
# update() refuses to run until called with rebuild=True (`cosh commits
# --rebuild`, about 1 h 55 min). Bump a part's version for a change its
# fingerprint can't see (a git flag in update(), say). tip_paths is
# rebuilt on every run, so it needs none.
PART_VERSIONS = {"core": 1, "messages": 1, "reverts": 1, "lsc": 1, "owners": 1, "repetition": 1, "renames": 1}


def part_fingerprints():
    v = PART_VERSIONS
    fp = codefp.fingerprint
    return {
        "core": fp(v["core"], INGEST_ARGS, FMT, SEP, HISTORY_SINCE, _numstat, unquote_path, _count_from),
        "messages": fp(v["messages"], FMT, SEP, _message_fields, REVIEWED_ON, REVERTS, AI_MARKER, EMAIL),
        "reverts": fp(v["reverts"], _reverts, REVERT_GREP),
        "lsc": fp(v["lsc"], _lsc, LSC_GREP),
        "owners": fp(v["owners"], _owners, _owner_rows, OWNER_EMAIL),
        "repetition": fp(v["repetition"], REPETITION_TODO, REP_MIN_FILES, MAX_LINES, ratios, diff_lines),
        "renames": fp(v["renames"], _renames, RENAME_CANDIDATES, RENAME_LIMIT),
    }


def _forget(*keys):
    return lambda db: db.executemany("DELETE FROM meta WHERE k = ?", [(k,) for k in keys])


def _reset_all(db):
    for t in ("commits", "commit_files", "paths", "owners_added", "repetition", "renames", "tip_paths"):
        db.execute(f"DELETE FROM {t}")
    db.execute("DELETE FROM meta WHERE k != 'paths_raw'")


PART_RESETS = {
    "core": _reset_all,
    "messages": None,                   # recomputed in place by _remessage
    "reverts": lambda db: (db.execute("UPDATE commits SET is_revert = 0 WHERE is_revert"),
                           _forget("reverts_through")(db)),
    "lsc": lambda db: (db.execute("UPDATE commits SET is_lsc = 0 WHERE is_lsc"), _forget("lsc_through")(db)),
    "owners": lambda db: (db.execute("DELETE FROM owners_added"), _forget("owners_through")(db)),
    "repetition": lambda db: db.execute("DELETE FROM repetition"),
    "renames": lambda db: (db.execute("DELETE FROM renames"), _forget("renames_through")(db)),
}


def check_parts(db, rebuild=False, fps=None):
    """Compares each part's stored fingerprint with the code's and resets
    the parts that changed. Returns {part: "same" | "new" | "changed"}."""
    fps = fps or part_fingerprints()
    old = codefp.stored(db, "core")
    if old is not None and old != fps["core"] and not rebuild:
        raise SystemExit("commits: the code that reads commits and their files changed (part \"core\"); "
                         "rerun with --rebuild to rebuild the store from empty (about 1 h 55 min)")
    out = {"core": codefp.check(db, "core", fps["core"], PART_RESETS["core"])}
    for part, fp in fps.items():
        if part != "core":
            out[part] = codefp.check(db, part, fp, PART_RESETS[part])
            if out[part] == "changed":
                print(f"commits: the code of part {part!r} changed: recomputing it", file=sys.stderr, flush=True)
    return out


def update(path=None, repo=None, jobs=4, rebuild=False):
    """Brings the store up to date with the clone's main: new commits, then
    (on the first runs) the history before HISTORY_SINCE, then OWNERS
    additions and repetition ratios for whatever is new, after redoing the
    parts whose code changed (check_parts). Resumable."""
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
        fps = part_fingerprints()
        parts = check_parts(db, rebuild, fps)
        paths = dict(db.execute("SELECT path, path_id FROM paths"))
        top = db.execute("SELECT max(commit_id), min(commit_id) FROM commits").fetchone()
        if top[0] is None or top[0] < 1:
            n = _ingest(db, repo, ["--reverse", f"--since={HISTORY_SINCE}", tip], _count_from(1, 1),
                        paths, f"since {HISTORY_SINCE[:10]}")
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
        if parts["messages"] == "changed":
            with db:
                k = _remessage(db, repo, tip)
                codefp.record(db, "messages", fps["messages"])
            print(f"commits: {k:,} messages read again", file=sys.stderr, flush=True)
        k = _reverts(db, repo, tip)
        print(f"commits: {k:,} reverts", file=sys.stderr, flush=True)
        k = _lsc(db, repo, tip)
        print(f"commits: {k:,} LSC commits", file=sys.stderr, flush=True)
        k = _owners(db, repo, tip)
        print(f"commits: {k:,} OWNERS additions", file=sys.stderr, flush=True)
        k = _repetition(db, repo, jobs)
        print(f"commits: {k:,} repetition ratios", file=sys.stderr, flush=True)
        k = _renames(db, repo)
        print(f"commits: {k:,} renamed files", file=sys.stderr, flush=True)
        k = _tip_paths(db, repo, tip)
        print(f"commits: {k:,} files at the tip", file=sys.stderr, flush=True)
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
    """Monday of the oldest week fetched into reviews.sqlite (the Value
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
    since reviews.sqlite's oldest fetched week. Yields (commit_id, CL, author
    email, landed 'YYYY-MM-DD HH:MM:SS' UTC, is_bot, files). A commit is a
    bot's if its CL's owner is a bot (changes.is_bot_owned) or config/bots.txt
    matches its git author: some bots (e.g. a WebLayer builder) author commits
    on CLs a person owns. Commits of a large-scale change (is_lsc) aren't
    counted at all. Also returns the window's lower bound."""
    lo = window_start(db, derived_since(ddb) + "T00:00:00Z")
    bot_owned = dict(ddb.execute("SELECT change_number, is_bot_owned FROM changes WHERE branch = 'main'"))
    rows = []
    for cid, cl, email, landed, files in db.execute(
            "SELECT commit_id, change_number, author_email, landed_at, files FROM commits "
            "WHERE commit_id > ? AND NOT is_lsc ORDER BY commit_id DESC", (lo,)):
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


# Per-person queries (cosh.people identities), shared by the Feedback Index
# (cosh/review_feedback.py) and the analyses in scripts/.

def first_people(db, norm=None):
    """{person: unix time of their first human commit on main}, over all of
    its history. Addresses go through `norm` (default cosh.people.person;
    the pages pass cosh.people.address)."""
    from .people import is_bot_email, person
    norm = norm or person
    first = {}
    for e, (t, bot) in first_commits(db).items():
        if not bot and not is_bot_email(e):
            e = norm(e)
            first[e] = min(t, first.get(e, t))
    return first


HUMAN_COMMIT_FIELDS = ("cid", "sha", "email", "at", "n", "rb", "is_revert", "reland", "files", "lines", "reverted_at")


def human_commits(db, norm=None, row=dict):
    """Human commits on main since 2017 (commit_id > 0) as dicts: cid, sha, email
    (through `norm`, default cosh.people.person), at, n (CL), rb (Reviewed-by
    people), is_revert, reland, files, lines, reverted_at (HUMAN_COMMIT_FIELDS).
    `row` makes each one from those keywords (a cosh.records type for less
    memory)."""
    import json
    from .people import is_bot_email, person
    norm = norm or person
    # Streamed, not fetched whole: the first revert of each sha comes from SQL.
    reverted = dict(db.execute("SELECT reverts_sha, min(landed_at) FROM commits "
                               "WHERE commit_id > 0 AND reverts_sha IS NOT NULL AND reverts_sha != '' "
                               "GROUP BY reverts_sha"))
    out = []
    for cid, sha, email, at, n, bot, rb, rv, rl, files, lines in db.execute(
            "SELECT commit_id, sha, author_email, landed_at, change_number, is_bot, reviewed_by, "
            "reverts_sha, is_reland, files, ins + dels FROM commits WHERE commit_id > 0"):
        if bot or is_bot_email(email):
            continue
        out.append(row(cid=cid, sha=sha, email=norm(email), at=at, n=n,
                        rb=[norm(x) for x in json.loads(rb)] if rb else [],
                        is_revert=rv is not None, reland=rl, files=files, lines=lines,
                        reverted_at=reverted.get(sha)))
    return out


def mechanical(db, cls):
    """Mechanical CLs: merged CLs (dicts with change_number, status, sha,
    files) whose landed commit has 100 or more files, or 10 or more with a
    repetition ratio of 0.8 or more."""
    rep = repetition(db)
    out = set()
    for c in cls:
        if c["status"] != "MERGED" or c["files"] is None or c["files"] < 10:
            continue
        r = rep.get(c["sha"])
        if c["files"] >= 100 or (r is not None and r >= 0.8):
            out.add(c["change_number"])
    return out


def lsc_cls(db):
    """Change numbers of the CLs whose landed commit is part of a
    large-scale change (is_lsc). They're left out wherever mechanical CLs
    are, and from the Value Exchange commits metric."""
    return {n for (n,) in db.execute("SELECT change_number FROM commits WHERE is_lsc AND change_number IS NOT NULL")}


def left_out(db, cls):
    """The CLs per-CL review measures leave out: mechanical(db, cls) and
    lsc_cls(db)."""
    return mechanical(db, cls) | lsc_cls(db)


def dir_of(path, depth):
    """The `depth`-level directory of a path, with a trailing slash."""
    parts = path.split("/")[:-1]
    return "/".join(parts[:depth]) + "/" if parts else "(root)/"


# A directory that's gone from main's tip takes the name most of its renamed
# files moved to (current_paths) if this share of its moves went there, at
# least this many files, and they're at least DIR_MOVE_COVER of the files
# ever renamed anywhere under it (so a few files leaving a big directory
# don't rename it).
DIR_MOVE_SHARE, DIR_MOVE_MIN, DIR_MOVE_COVER = 0.9, 5, 0.5


def current_paths(db):
    """{path: its name at main's tip}, for the paths that have another one.

    A path renamed (the renames table) takes its last new name, following
    renames of renames. A path that's then not at the tip (deleted before or
    after a move) takes its directory's new name if the directory is gone
    from the tip and DIR_MOVE_SHARE of its renamed files went to one place:
    the deepest such directory below the deepest one still at the tip (a
    gone directory whose files went to several places defers to its
    parent). So third_party/WebKit/Source/core/dom/X.cpp, deleted
    in 2017, is third_party/blink/renderer/core/dom/X.cpp. A move into a
    directory's own subdirectory (wpt/x.html to wpt/css/x.html) is a
    reorganisation, not a new name for the directory, and doesn't count.
    Paths that git
    didn't see renamed (moved with heavy edits, or copied and later deleted)
    keep their names. Empty if the store has no renames yet."""
    rows = db.execute("SELECT r.commit_id, o.path, n.path FROM renames r JOIN paths o ON o.path_id = r.old_path_id "
                      "JOIN paths n ON n.path_id = r.new_path_id ORDER BY r.commit_id DESC").fetchall()
    if not rows:
        return {}
    final = {}
    for _, a, b in rows:                 # newest first: b's later names are known
        final[a] = final.get(b, b)
    tip = {p for p, in db.execute("SELECT p.path FROM tip_paths t JOIN paths p USING (path_id)")}
    live = set()                         # every directory at the tip, as a tuple of names
    for p in tip:
        parts = tuple(p.split("/")[:-1])
        for i in range(1, len(parts) + 1):
            live.add(parts[:i])
    # Directory moves: each rename, with the directories' common tail left off.
    votes, under = {}, Counter()
    for a in {a for _, a, _ in rows}:
        parts = a.split("/")[:-1]
        for i in range(1, len(parts) + 1):
            under[tuple(parts[:i])] += 1
    for _, a, b in rows:
        x, y = a.split("/")[:-1], b.split("/")[:-1]
        while x and y and x[-1] == y[-1]:
            x.pop()
            y.pop()
        if x and y[:len(x)] != x:        # not a move into its own subdirectory (a reorganisation)
            c = votes.setdefault(tuple(x), Counter())
            c[tuple(y)] += 1
    moved = {}
    for d, c in votes.items():
        to, k = c.most_common(1)[0]
        tot = sum(c.values())
        if d not in live and k >= DIR_MOVE_MIN and k >= DIR_MOVE_SHARE * tot and k >= DIR_MOVE_COVER * under[d]:
            moved[d] = to

    def by_dir(p):
        parts = p.split("/")
        for i in range(len(parts) - 1, 0, -1):
            d = tuple(parts[:i])
            if d in live:
                return p
            to = moved.get(d)
            if to is not None:
                return "/".join((*to, *parts[i:]))
        return p
    out = {}
    for (p,) in db.execute("SELECT path FROM paths"):
        q = p if p in tip else final.get(p, p)    # a name in use again is today's file
        seen = {q}
        for _ in range(4):                  # a directory's new name may itself have moved later
            if q in tip:
                break
            r = by_dir(q)
            r = final.get(r, r)
            if r in seen:                   # unchanged, or back and forth
                break
            seen.add(r)
            q = r
        if q != p:
            out[p] = q
    return out


def moved_lines(db, first=None, last=None):
    """{(commit_id, path_id): (ins, dels)} replacing commit_files' counts for
    files a commit renamed: the new name gets the lines changed between the
    two (0 and 0 for a plain move), the old name none. commit_files, without
    rename detection, has the whole file deleted and added. Renames from
    before their line counts are left out. `first` and `last` limit it to
    those commit_ids (both included)."""
    out = {}
    lo, hi = (first, last) if first is not None else (-2 ** 62, 2 ** 62)
    for cid, a, b, ins, dels in db.execute("SELECT commit_id, old_path_id, new_path_id, ins, dels FROM renames "
                                           "WHERE ins IS NOT NULL AND commit_id BETWEEN ? AND ?", (lo, hi)):
        out[(cid, a)] = (0, 0)
        out[(cid, b)] = (ins, dels)
    return out


def commit_dirs(db, depth=3, current=None, moved=None):
    """{commit_id: (top dir by lines, frozenset of dirs)} of the commits since
    2017 (commit_id > 0). With `current` (current_paths), each file counts
    in the directory it's in today; with `moved` (moved_lines), a renamed
    file by the lines changed, not moved."""
    # Each path's directory, interned: 1.6M paths but about 116k directories,
    # so no path string is kept. Equal results are shared too: most commits
    # touch a directory set some other commit already did.
    cache = {}
    for pid, path in db.execute("SELECT path_id, path FROM paths"):
        if current:
            path = current.get(path, path)
        cache[pid] = sys.intern(dir_of(path, depth))
    shared, out, cur, acc = {}, {}, None, None

    def done():
        if cur is not None and acc:
            v = (max(acc, key=acc.get), frozenset(acc))
            out[cur] = shared.setdefault(v, v)
    for cid, pid, w in db.execute("SELECT commit_id, path_id, max(ins, 0) + max(dels, 0) + 1 FROM commit_files WHERE commit_id > 0"):
        if moved:
            m = moved.get((cid, pid))
            if m is not None:
                w = max(m[0], 0) + max(m[1], 0) + 1
        if cid != cur:
            done()
            cur, acc = cid, {}
        d = cache[pid]
        acc[d] = acc.get(d, 0) + w
    done()
    return out


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="cosh commits")
    ap.add_argument("--db", help=f"store path (default: $COSH_COMMITS_DB or data/private/{COMMITS_FILE})")
    ap.add_argument("--jobs", type=int, default=4, help="git diff processes for the repetition ratios")
    ap.add_argument("--rebuild", action="store_true",
                    help="rebuild from empty if the core code changed (about 1 h 55 min; it refuses without)")
    a = ap.parse_args(argv)
    update(a.db, jobs=max(1, min(a.jobs, 4)), rebuild=a.rebuild)
