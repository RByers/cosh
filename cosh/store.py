"""SQLite storage: raw.sqlite (response cache + progress, source of truth) and
derived.sqlite (derived tables, rebuildable). See docs/storage-design.md §3."""

import fcntl
import hashlib
import os
import sqlite3
import zlib
from contextlib import contextmanager
from datetime import datetime, timezone

# COSH_DATA_DIR lets code in a worktree read the main checkout's data.
DATA_DIR = os.environ.get("COSH_DATA_DIR") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "private")

RAW_SCHEMA = """
CREATE TABLE IF NOT EXISTS responses (
  host        TEXT    NOT NULL,
  kind        TEXT    NOT NULL,      -- 'list_window' | 'comments' (REST) | 'account'
  key         TEXT    NOT NULL,      -- window spec, or change number
  url         TEXT    NOT NULL,
  fetched_at  TEXT    NOT NULL,
  http_status INTEGER NOT NULL,
  body_zlib   BLOB    NOT NULL,      -- zlib(body without XSSI prefix)
  body_sha256 TEXT    NOT NULL,
  PRIMARY KEY (host, kind, key)
) STRICT, WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS extract_runs (
  run_id      INTEGER PRIMARY KEY,
  started_at  TEXT NOT NULL,
  finished_at TEXT,
  command     TEXT NOT NULL,
  requests    INTEGER,
  status      TEXT NOT NULL          -- running | ok | failed | interrupted
) STRICT;

CREATE TABLE IF NOT EXISTS week_progress (
  host          TEXT NOT NULL,
  project       TEXT NOT NULL,
  iso_week      TEXT NOT NULL,
  listed_at     TEXT,
  cl_count      INTEGER,
  fetched_at    TEXT,                -- all comment fetches done
  last_run_id   INTEGER,
  PRIMARY KEY (host, project, iso_week)
) STRICT;

CREATE TABLE IF NOT EXISTS week_changes (
  host TEXT NOT NULL, project TEXT NOT NULL, iso_week TEXT NOT NULL,
  change_number INTEGER NOT NULL,
  window_key    TEXT NOT NULL,       -- which list_window response holds its JSON
  PRIMARY KEY (host, project, iso_week, change_number)
) STRICT, WITHOUT ROWID;

-- Open CLs, plus CLs closed after the newest fetched week. Without these, a
-- comment is invisible until its CL closes. Each listing is a snapshot.
CREATE TABLE IF NOT EXISTS open_listings (
  host         TEXT NOT NULL,
  project      TEXT NOT NULL,
  listed_at    TEXT NOT NULL,        -- snapshot id: when the listing started (UTC ISO)
  since        TEXT NOT NULL,        -- open CLs updated at/after this (UTC ISO)
  closed_since TEXT NOT NULL,        -- plus CLs closed at/after this (UTC ISO)
  cl_count     INTEGER,
  fetched_at   TEXT,                 -- all NoteDb fetches done
  last_run_id  INTEGER,
  PRIMARY KEY (host, project, listed_at)
) STRICT;

CREATE TABLE IF NOT EXISTS open_changes (
  host TEXT NOT NULL, project TEXT NOT NULL, listed_at TEXT NOT NULL,
  change_number INTEGER NOT NULL,
  window_key    TEXT NOT NULL,       -- which list_window response holds its JSON
  PRIMARY KEY (host, project, listed_at, change_number)
) STRICT, WITHOUT ROWID;
"""

DERIVED_FILE = "derived.sqlite"

# Review activity is keyed by *when it happened*, not by when the CL closed.
# Rebuildable: `rm data/private/derived.sqlite && python3 -m cosh derive`.
DERIVED_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT) STRICT;

CREATE TABLE IF NOT EXISTS accounts (
  host        TEXT    NOT NULL,
  account_id  INTEGER NOT NULL,
  email       TEXT,
  name        TEXT,
  is_bot      INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (host, account_id)
) STRICT;
CREATE INDEX IF NOT EXISTS accounts_email ON accounts(email);

-- One row per CL, from its most recent listing (largest `updated`).
CREATE TABLE IF NOT EXISTS changes (
  host                TEXT    NOT NULL,
  change_number       INTEGER NOT NULL,
  project             TEXT    NOT NULL,
  branch              TEXT    NOT NULL,
  change_id           TEXT,
  owner_account       INTEGER NOT NULL,
  status              TEXT    NOT NULL,   -- MERGED | ABANDONED | NEW (open)
  created_at          TEXT    NOT NULL,
  updated_at          TEXT    NOT NULL,
  submitted_at        TEXT,               -- NULL unless merged
  closed_at           TEXT,               -- submit time, or `updated` if abandoned; NULL if open
  close_week          TEXT,               -- ISO week of closed_at; NULL if open
  insertions          INTEGER,
  deletions           INTEGER,
  patchsets           INTEGER,
  total_comment_count INTEGER,
  is_bot_owned        INTEGER NOT NULL DEFAULT 0,
  subject             TEXT,
  anchor_path         TEXT,               -- file with the most inline comments, from anyone
                                          -- (cosh/paths.py); NULL if none
  PRIMARY KEY (host, change_number)
) STRICT;
CREATE INDEX IF NOT EXISTS changes_close_week ON changes(close_week);

-- Core fact table: one row per published comment by a non-owner on a
-- human-owned CL, bucketed by the ISO week it was written.
CREATE TABLE IF NOT EXISTS comments (
  host          TEXT    NOT NULL,
  change_number INTEGER NOT NULL,
  comment_id    TEXT    NOT NULL,       -- Gerrit comment uuid
  account_id    INTEGER NOT NULL,
  written_at    TEXT    NOT NULL,       -- UTC 'YYYY-MM-DD HH:MM:SS'
  iso_week      TEXT    NOT NULL,       -- ISO week of written_at
  path          TEXT    NOT NULL,       -- file, or a Gerrit pseudo-path: /PATCHSET_LEVEL, /COMMIT_MSG
  chars         INTEGER NOT NULL,       -- after removing quoted '>' lines
  is_ai         INTEGER NOT NULL,       -- is_ai flag or autogenerated:* tag
  after_close   INTEGER NOT NULL,       -- written after the CL merged / was abandoned
  PRIMARY KEY (host, change_number, comment_id)
) STRICT, WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS comments_week ON comments(iso_week);
"""


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect(path, schema):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # A backfill derives each week into derived.sqlite while a full `derive`
    # may be writing it too; wait for the other writer instead of failing.
    db = sqlite3.connect(path, timeout=60)
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript(schema)
    return db


def open_raw(data_dir=DATA_DIR):
    return connect(os.path.join(data_dir, "raw.sqlite"), RAW_SCHEMA)


def open_raw_ro(data_dir=DATA_DIR):
    """raw.sqlite opened read-only without touching its schema. derive and
    summarize never write to it, so they are safe while an extractor runs."""
    db = sqlite3.connect(f"file:{os.path.join(data_dir, 'raw.sqlite')}?mode=ro", uri=True)
    db.execute("PRAGMA query_only=1")
    return db


def has_table(db, name):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                      (name,)).fetchone() is not None


def open_derived(data_dir=DATA_DIR, path=None):
    path = path or os.path.join(data_dir, DERIVED_FILE)
    if os.path.exists(path):
        old = sqlite3.connect(path)
        cols = {r[1] for r in old.execute("PRAGMA table_info(comments)")}
        old.close()
        if cols and not {"path", "chars"} <= cols:
            raise SystemExit(f"{path} predates per-file comments (metric_version 5); "
                             f"rebuild it: rm {path} && python3 -m cosh derive")
    return connect(path, DERIVED_SCHEMA)


@contextmanager
def extract_lock(data_dir=DATA_DIR):
    """Only one extractor at a time (CLAUDE.md). Held for the whole run."""
    os.makedirs(data_dir, exist_ok=True)
    fh = open(os.path.join(data_dir, "extract.lock"), "w")
    try:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("another cosh extractor holds data/private/extract.lock")
        fh.write(f"{os.getpid()}\n")
        fh.flush()
        yield
    finally:
        fh.close()


def put_response(raw, host, kind, key, url, status, body):
    data = body.encode("utf-8")
    raw.execute(
        """INSERT INTO responses VALUES (?,?,?,?,?,?,?,?)
           ON CONFLICT(host, kind, key) DO UPDATE SET url=excluded.url,
             fetched_at=excluded.fetched_at, http_status=excluded.http_status,
             body_zlib=excluded.body_zlib, body_sha256=excluded.body_sha256""",
        (host, kind, key, url, now_iso(), status, zlib.compress(data, 9),
         hashlib.sha256(data).hexdigest()))


def get_response(raw, host, kind, key):
    row = raw.execute(
        "SELECT http_status, body_zlib FROM responses WHERE host=? AND kind=? AND key=?",
        (host, kind, key)).fetchone()
    if row is None:
        return None
    return row[0], zlib.decompress(row[1]).decode("utf-8")
