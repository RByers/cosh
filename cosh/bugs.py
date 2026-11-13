"""Chromium bug-tracker metadata (issues.chromium.org), in data/private/bugs/.

Approved by the user on 2026-11-08. See docs/bugs.md for the data source,
the politeness rules, the storage layout and the field mappings.

  python3 -m cosh.bugs ids                   which bug IDs we want (offline: git + security_fixes.json)
  python3 -m cosh.bugs fetch [--go]          ask the tracker for IDs never asked yet, 50 per request
  python3 -m cosh.bugs fetch --retry-missing [--go]   re-ask IDs that weren't visible
  python3 -m cosh.bugs monorail [--go]       map pre-2024 (Monorail) IDs to tracker IDs
  python3 -m cosh.bugs parse                 rebuild the bugs table from raw/ (offline)
  python3 -m cosh.bugs status                progress counts

Without --go, fetch and monorail only print what they would do.

Bug titles and other text in the responses are untrusted (SECURITY.md).
This module parses them with code only and prints counts, IDs and enum
fields, never text.
"""

import argparse
import collections
import fcntl
import gzip
import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timezone

from . import store

HOST = "issues.chromium.org"
LIST_URL = f"https://{HOST}/action/issues/list"
MONORAIL_URL = "https://bugs.chromium.org/p/chromium/issues/detail?id={}"
TRACKER = "157"             # Chromium's tracker ID in the Google Issue Tracker
BATCH = 50                  # IDs per search request (the search returns at most 50)
# No wait between requests by default; any error backs off instead (approved
# by the user on 2026-11-08, after a clean first run at 2 s).
MIN_INTERVAL = 0.0
DEFAULT_INTERVAL = 0.0
# The Monorail stubs are tiny static redirects; the user approved up to 4 at
# once with no wait between them (2026-11-08).
MONORAIL_MAX_JOBS = 4
SHARED = os.path.expanduser("~/projects/shared/chromium")
from .approved import bug_footers_since  # noqa: E402
SINCE = bug_footers_since()  # config/approved.json; 2023-07-01, the start of the Gerrit analysis window
MONORAIL_MAX = 1_600_000    # IDs below this are Monorail-era (crbug.com/1234567; it ended near 1.53M)
MIN_ID = 100_000            # shorter numbers in footers are typos or other trackers
MAX_ID = 9_999_999_999
XSSI = b")]}'"

# google.devtools.issuetracker.v1 enums; see docs/bugs.md for confidence.
STATUS = {1: "New", 2: "Assigned", 3: "Accepted", 4: "Fixed", 5: "Verified",
          6: "Not reproducible", 7: "Intended behavior", 8: "Obsolete",
          9: "Infeasible", 10: "Duplicate"}
TYPE = {1: "Bug", 2: "Feature request", 3: "Customer issue", 4: "Internal cleanup",
        5: "Process", 6: "Vulnerability"}

# Custom fields with their own column, by name (names come from each issue's
# own field definitions, so a renumbering doesn't break this).
FIELD_COLUMNS = {
    "CVE": "cve",
    "Introduced In": "introduced_in",
    "Milestone": "milestone",
    "Security_Release": "security_release",
    "OS": "os",
    "Chromium Labels": "labels",
    "Component Tags": "component_path",
    "Fixed By Code Changes": "fixed_by_field",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS wanted (
  id            INTEGER PRIMARY KEY,   -- as written in the footer or release post
  bug_commits   INTEGER NOT NULL DEFAULT 0,  -- first-parent commits with it in Bug:
  fixed_commits INTEGER NOT NULL DEFAULT 0,  -- ... in Fixed:
  security      INTEGER NOT NULL DEFAULT 0,  -- in chrome_releases/security_fixes.json
  first_commit  TEXT,                  -- committer date of the first such commit
  last_commit   TEXT
) STRICT;

CREATE TABLE IF NOT EXISTS monorail_map (
  old_id      INTEGER PRIMARY KEY,
  new_id      INTEGER,               -- NULL when the stub named no issue
  http_status INTEGER NOT NULL,
  fetched_at  TEXT NOT NULL,
  request_seq INTEGER NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS requests (
  seq          INTEGER PRIMARY KEY,
  kind         TEXT NOT NULL,        -- 'list' | 'monorail'
  started_at   TEXT NOT NULL,
  elapsed_s    REAL NOT NULL,
  http_status  INTEGER NOT NULL,    -- -1: network error
  final_url    TEXT,
  headers      TEXT,                 -- response headers, JSON
  request_body TEXT,                 -- what we POSTed (the IDs asked)
  wire_bytes   INTEGER NOT NULL,
  body_bytes   INTEGER NOT NULL,
  file         TEXT,                 -- under bugs/raw/, gzip of the body as received
  n_asked      INTEGER,
  n_returned   INTEGER,
  outcome      TEXT NOT NULL         -- ok | http | shape | blocked | net
) STRICT;

CREATE TABLE IF NOT EXISTS asked (
  id          INTEGER PRIMARY KEY,   -- tracker ID asked for
  visible     INTEGER NOT NULL,      -- 1 returned, 0 not returned (restricted or absent)
  first_asked TEXT NOT NULL,
  last_asked  TEXT NOT NULL,
  times       INTEGER NOT NULL,
  request_seq INTEGER NOT NULL       -- the last request that asked
) STRICT;

CREATE TABLE IF NOT EXISTS bugs (
  id             INTEGER PRIMARY KEY,
  tracker        INTEGER,
  component_id   INTEGER,
  component_path TEXT,
  type           INTEGER,
  type_name      TEXT,
  status         INTEGER,
  status_name    TEXT,
  priority       TEXT,              -- P0..P4
  severity       TEXT,              -- S0..S4
  title          TEXT,              -- untrusted
  created        TEXT,
  modified       TEXT,
  resolved       TEXT,
  verified       TEXT,
  cve            TEXT,
  introduced_in  TEXT,
  milestone      TEXT,
  security_release TEXT,
  os             TEXT,
  labels         TEXT,              -- "Chromium Labels", comma-separated
  found_in       TEXT,              -- JSON list of milestones
  hotlists       TEXT,              -- JSON list of hotlist IDs
  fixed_by       TEXT,              -- JSON list of "host/project/change"
  fixed_by_field TEXT,
  regression     INTEGER,           -- heuristic, docs/bugs.md
  custom         TEXT,              -- JSON {field name: display value}, all custom fields
  raw_file       TEXT NOT NULL,
  fetched_at     TEXT NOT NULL
) STRICT;
"""


class Stop(Exception):
    """The fetch must stop now (blocked, rate-limited, or the API changed)."""


class Backoff(Stop):
    """A parallel run hit a rate limit, server error or network error: wait,
    then go on with the IDs not yet done."""


# ---------------------------------------------------------------- paths, db

def bugs_dir(data_dir=None):
    return os.path.join(data_dir or store.DATA_DIR, "bugs")


def open_db(data_dir=None):
    return store.connect(os.path.join(bugs_dir(data_dir), "bugs.sqlite"), SCHEMA)


@contextmanager
def fetch_lock(name="fetch.lock", data_dir=None):
    """Only one search fetch (fetch.lock) and one Monorail lookup
    (monorail.lock) at a time; the two talk to different hosts, so they may
    overlap. Not extract.lock: that one is for Gerrit."""
    d = bugs_dir(data_dir)
    os.makedirs(d, exist_ok=True)
    fh = open(os.path.join(d, name), "w")
    try:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit(f"another bug fetch holds data/private/bugs/{name}")
        fh.write(f"{os.getpid()}\n")
        fh.flush()
        yield
    finally:
        fh.close()


# ---------------------------------------------------------------- which IDs

_FOOTER_ID = re.compile(
    r"(?:chromium:|crbug(?:\.com)?/|https?://crbug\.com/|"
    r"https?://(?:g-)?issues\.chromium\.org/issues/|"
    r"https?://bugs\.chromium\.org/p/chromium/issues/detail\?id=)?(\d+)")


def footer_ids(value):
    """Chromium bug IDs in one Bug:/Fixed: footer value, and a count of the
    tokens skipped as other trackers (b:, v8:, skia:, URLs elsewhere ...)."""
    ids, skipped = [], 0
    for tok in re.split(r"[,;\s]+", value.strip()):
        tok = tok.rstrip(".)").lstrip("(")
        if not tok:
            continue
        m = _FOOTER_ID.fullmatch(tok)
        if m:
            n = int(m.group(1))
            if MIN_ID <= n <= MAX_ID:
                ids.append(n)
            else:
                skipped += 1
        elif re.search(r"\d", tok):
            skipped += 1          # b:123, v8:123, skia:123, issuetracker URLs ...
    return ids, skipped


def git_footers(repo=SHARED, since=SINCE):
    """Yield (committer date, key, value) for Bug:/Fixed: footers of first-parent
    commits on main. Streams; never fetches (GIT_NO_LAZY_FETCH)."""
    cmd = ["git", "-C", repo, "log", "main", "--first-parent", f"--since={since}",
           "--format=%cI%x1f%(trailers:key=Bug,key=Fixed,separator=%x1f)%x1e"]
    env = {**os.environ, "GIT_NO_LAZY_FETCH": "1"}
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, env=env, text=True,
                          errors="replace") as p:
        buf = ""
        for chunk in iter(lambda: p.stdout.read(1 << 20), ""):
            buf += chunk
            *recs, buf = buf.split("\x1e")
            for rec in recs:
                date, *trailers = rec.strip("\n").split("\x1f")
                for tr in trailers:
                    key, _, val = tr.partition(":")
                    key = key.strip()
                    if key in ("Bug", "Fixed"):
                        yield date, key, val
    if p.returncode:
        raise SystemExit(f"git log failed ({p.returncode})")


def build_wanted(db, footers, security_ids):
    """Replace the wanted table. Returns a dict of counts."""
    per = {}
    skipped = 0
    for date, key, val in footers:
        ids, sk = footer_ids(val)
        skipped += sk
        for i in set(ids):
            r = per.setdefault(i, [0, 0, 0, date, date])
            r[0 if key == "Bug" else 1] += 1
            r[3] = min(r[3], date)
            r[4] = max(r[4], date)
    for i in security_ids:
        if MIN_ID <= i <= MAX_ID:
            per.setdefault(i, [0, 0, 0, None, None])[2] = 1
    with db:
        db.execute("DELETE FROM wanted")
        db.executemany("INSERT INTO wanted VALUES (?,?,?,?,?,?)",
                       [(i, *r) for i, r in per.items()])
    return {
        "ids": len(per),
        "footer": sum(1 for r in per.values() if r[0] or r[1]),
        "bug_footer": sum(1 for r in per.values() if r[0]),
        "fixed_footer": sum(1 for r in per.values() if r[1]),
        "security": sum(1 for r in per.values() if r[2]),
        "security_only": sum(1 for r in per.values() if r[2] and not (r[0] or r[1])),
        "monorail_era": sum(1 for i in per if i < MONORAIL_MAX),
        "skipped_tokens": skipped,
    }


def security_ids(data_dir=None):
    path = os.path.join(data_dir or store.DATA_DIR, "chrome_releases", "security_fixes.json")
    with open(path) as f:
        return sorted({int(x["bug"]) for x in json.load(f) if x.get("bug")})


def to_ask(db, retry_missing=False, older_than_days=30):
    """Tracker IDs to ask for, newest first."""
    if retry_missing:
        cutoff = datetime.fromtimestamp(time.time() - older_than_days * 86400, timezone.utc)
        rows = db.execute("SELECT id FROM asked WHERE visible = 0 AND last_asked <= ? "
                          "ORDER BY id DESC", (cutoff.strftime("%Y-%m-%dT%H:%M:%SZ"),))
        return [r[0] for r in rows]
    rows = db.execute(f"""
        SELECT id FROM (SELECT id FROM wanted WHERE id >= {MONORAIL_MAX}
                        UNION SELECT new_id FROM monorail_map WHERE new_id IS NOT NULL)
        WHERE id NOT IN (SELECT id FROM asked) ORDER BY id DESC""")
    return [r[0] for r in rows]


# ---------------------------------------------------------------- parsing

def strip_xssi(body):
    """Decode a response body and drop the )]}' prefix line."""
    if not body.startswith(XSSI):
        raise ValueError("no XSSI prefix")
    text = body.decode("utf-8")
    return text[text.index("\n") + 1:]


def search_issues(body):
    """Issues (raw lists) in a search response, or raise ValueError on any
    unexpected shape."""
    d = json.loads(strip_xssi(body))
    if not (isinstance(d, list) and d and isinstance(d[0], list) and len(d[0]) > 6
            and d[0][0] == "b.IssueSearchResponse"):
        raise ValueError("not a b.IssueSearchResponse")
    res = d[0][6]
    if res is None:
        return []
    if not isinstance(res, list) or not res:
        raise ValueError("bad result block")
    issues = res[0] or []
    if not isinstance(issues, list):
        raise ValueError("bad issue list")
    for i in issues:
        if not (isinstance(i, list) and len(i) > 6 and isinstance(i[1], int)
                and isinstance(i[2], list) and len(i[2]) > 14):
            raise ValueError("bad issue entry")
    return issues


def _at(seq, *path):
    for k in path:
        if not isinstance(seq, list) or k >= len(seq) or seq[k] is None:
            return None
        seq = seq[k]
    return seq


def _ts(v):
    if not isinstance(v, list) or not v or not isinstance(v[0], int):
        return None
    return datetime.fromtimestamp(v[0], timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _level(prefix, n):
    return f"{prefix}{n - 1}" if isinstance(n, int) and 1 <= n <= 5 else None


def parse_issue(iss):
    """One raw issue list -> dict of bugs columns (without raw_file/fetched_at)."""
    core = iss[2]
    names = {}
    for fdef in _at(iss, 14) or []:
        if isinstance(fdef, list) and len(fdef) > 4 and isinstance(fdef[4], str):
            names[fdef[0]] = fdef[4]
    custom = {}
    for cf in _at(core, 14) or []:
        if not isinstance(cf, list) or not cf:
            continue
        name = names.get(cf[0], str(cf[0]))
        disp = _at(cf, 9)
        if disp is None:
            disp = json.dumps(cf[1:9])
        custom[name] = disp
    row = {
        "id": iss[1],
        "tracker": _at(iss, 41),
        "component_id": _at(core, 0),
        "type": _at(core, 1),
        "status": _at(core, 2),
        "priority": _level("P", _at(core, 3)),
        "severity": _level("S", _at(core, 4)),
        "title": _at(core, 5),
        "created": _ts(_at(iss, 4)),
        "modified": _ts(_at(iss, 5)),
        "resolved": _ts(_at(iss, 6)),
        "verified": _ts(_at(iss, 7)),
        "found_in": json.dumps(_at(core, 16)) if _at(core, 16) else None,
        "hotlists": json.dumps(_at(core, 13)) if _at(core, 13) else None,
        "fixed_by": None,
        "custom": json.dumps(custom, ensure_ascii=False, sort_keys=True),
    }
    row["type_name"] = TYPE.get(row["type"])
    row["status_name"] = STATUS.get(row["status"])
    fixes = [f"{c[0]}/{c[1]}/{c[2]}" for c in (_at(core, 34) or [])
             if isinstance(c, list) and len(c) > 2]
    if fixes:
        row["fixed_by"] = json.dumps(fixes)
    for name, col in FIELD_COLUMNS.items():
        row[col] = custom.get(name)
    labels = row["labels"] or ""
    row["regression"] = int(bool(re.search(r"regression", labels, re.I)
                                 or row["introduced_in"]))
    return row


BUG_COLS = ["id", "tracker", "component_id", "component_path", "type", "type_name",
            "status", "status_name", "priority", "severity", "title", "created",
            "modified", "resolved", "verified", "cve", "introduced_in", "milestone",
            "security_release", "os", "labels", "found_in", "hotlists", "fixed_by",
            "fixed_by_field", "regression", "custom", "raw_file", "fetched_at"]


def store_issues(db, issues, raw_file, fetched_at):
    rows = []
    for iss in issues:
        r = parse_issue(iss)
        r["raw_file"], r["fetched_at"] = raw_file, fetched_at
        rows.append([r[c] for c in BUG_COLS])
    db.executemany(f"INSERT OR REPLACE INTO bugs ({','.join(BUG_COLS)}) "
                   f"VALUES ({','.join('?' * len(BUG_COLS))})", rows)


_MONORAIL_TARGET = re.compile(rb'const url = "https://issues\.chromium\.org/(?:issues/)?(\d+)"')


def monorail_target(body):
    """The tracker ID the bugs.chromium.org stub redirects to, or None."""
    m = _MONORAIL_TARGET.search(body)
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------- HTTP

def _lower(headers):
    return {k.lower(): v for k, v in headers.items()}


def http(method, url, body=None, headers=None, timeout=120):
    """One request, no retries. Returns (status, headers, wire bytes, body, final url)."""
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            wire, h, st, final = r.read(), _lower(r.headers), r.status, r.geturl()
    except urllib.error.HTTPError as e:
        wire, h, st, final = e.read() or b"", _lower(e.headers), e.code, url
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        return -1, {}, b"", str(e).encode(), url
    body = gzip.decompress(wire) if h.get("content-encoding") == "gzip" and wire else wire
    return st, h, wire, body, final


def looks_blocked(kind, headers, body, final_url):
    """A captcha, sign-in or 'unusual traffic' page instead of the expected reply.
    Search replies must be JSON; we don't scan their text, since bug titles may
    contain any word."""
    host = re.sub(r"^https?://([^/]+).*", r"\1", final_url or "")
    if host and host not in (HOST, "bugs.chromium.org"):
        return True
    ctype = headers.get("content-type", "")
    if kind == "list":
        return "html" in ctype.lower()
    if monorail_target(body) is not None:
        return False
    low = body[:4000].lower()
    return any(s in low for s in (b"captcha", b"unusual traffic", b"accounts.google.com",
                                  b"/sorry/"))


class Fetcher:
    """Serial, polite client. Every response is written to raw/ and logged in
    requests before it is parsed."""

    def __init__(self, db, data_dir=None, interval=DEFAULT_INTERVAL, transport=http,
                 log=sys.stderr, sleep=time.sleep, clock=time.monotonic,
                 backoff=(300, 900, 1800), min_interval=MIN_INTERVAL):
        if interval < min_interval:
            raise SystemExit(f"--interval must be at least {min_interval} s")
        self.db, self.dir = db, bugs_dir(data_dir)
        self.interval, self.transport, self.log = interval, transport, log
        self.sleep, self.clock, self.backoff = sleep, clock, backoff
        self._last = None
        self.bad_shapes = 0
        from .contact import http_headers
        self.headers = {"Accept": "application/json", "Accept-Encoding": "gzip",
                        **http_headers()}

    def _pace(self):
        if self._last is not None:
            gap = self.clock() - self._last
            if gap < self.interval:
                self.sleep(self.interval - gap)

    def _save(self, kind, name, wire, body, headers):
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        rel = os.path.join("raw", kind, month, name)
        path = os.path.join(self.dir, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        data = wire if headers.get("content-encoding") == "gzip" else gzip.compress(body)
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
        return rel

    def send(self, method, url, body=None, extra_headers=None):
        """The HTTP part alone (safe to run on several threads at once)."""
        started = store.now_iso()
        t0 = self.clock()
        resp = self.transport(method, url, body, {**self.headers, **(extra_headers or {})})
        return started, round(self.clock() - t0, 3), resp

    def record(self, kind, body, sent):
        """Log one response and keep its body. The row's seq is assigned by
        SQLite on insert, so several processes can log at once. Returns
        (seq, status, headers, body, rel, started, outcome, final)."""
        started, elapsed, (st, h, wire, rbody, final) = sent
        blocked = looks_blocked(kind, h, rbody, final)
        outcome = ("blocked" if blocked else "net" if st == -1
                   else "ok" if st == 200 or (kind == "monorail" and st in (403, 404))
                   else "http")
        with self.db:
            seq = self.db.execute(
                "INSERT INTO requests (kind, started_at, elapsed_s, http_status, "
                "final_url, headers, request_body, wire_bytes, body_bytes, outcome) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (kind, started, elapsed, st, final, json.dumps(h),
                 body.decode() if body else None, len(wire), len(rbody), outcome)).lastrowid
        rel = None
        if wire or rbody:
            ext = "html.gz" if kind == "monorail" else "json.gz"
            rel = self._save(kind, f"{seq:07d}.{ext}", wire, rbody, h)
            with self.db:
                self.db.execute("UPDATE requests SET file=? WHERE seq=?", (rel, seq))
        return seq, st, h, rbody, rel, started, outcome, final

    def request(self, kind, method, url, body=None, extra_headers=None):
        """Send one request with the stop rules. Returns (seq, status, body, rel, started)."""
        for attempt in range(len(self.backoff) + 1):
            self._pace()
            sent = self.send(method, url, body, extra_headers)
            self._last = self.clock()
            seq, st, h, rbody, rel, started, outcome, final = self.record(kind, body, sent)
            blocked = outcome == "blocked"
            if blocked:
                raise Stop(f"request {seq}: HTTP {st} looks like a captcha or sign-in page "
                           f"({final}); stopping")
            if outcome == "ok":
                return seq, st, rbody, rel, started
            if st in (401, 403) and kind == "list":
                raise Stop(f"request {seq}: HTTP {st} on the search endpoint; stopping")
            if st == 400 or (400 < st < 500 and st != 429):
                raise Stop(f"request {seq}: HTTP {st}; the API may have changed; stopping")
            if attempt == len(self.backoff):
                break
            wait = self.backoff[attempt]
            print(f"request {seq}: HTTP {st}; backing off {wait} s "
                  f"({attempt + 1}/{len(self.backoff)})", file=self.log, flush=True)
            self.sleep(wait)
        raise Stop(f"request {seq}: HTTP {st} after {len(self.backoff)} back-offs; stopping")

    def fetch_batch(self, ids):
        """Ask for up to BATCH tracker IDs. Returns the number visible."""
        q = "id:(" + " | ".join(str(i) for i in ids) + ")"
        body = json.dumps([None, None, None, None, None, [TRACKER],
                           [q, None, BATCH, "start_index:0"]]).encode()
        seq, st, rbody, rel, started = self.request(
            "list", "POST", LIST_URL, body, {"Content-Type": "application/json"})
        try:
            issues = search_issues(rbody)
        except ValueError as e:
            self.bad_shapes += 1
            with self.db:
                self.db.execute("UPDATE requests SET outcome='shape' WHERE seq=?", (seq,))
            if self.bad_shapes >= 3:
                raise Stop(f"request {seq}: unexpected response shape ({e}) "
                           f"{self.bad_shapes} times; stopping")
            print(f"request {seq}: unexpected shape ({e}); IDs left unasked",
                  file=self.log, flush=True)
            return 0
        self.bad_shapes = 0
        got = {i[1] for i in issues}
        with self.db:
            store_issues(self.db, issues, rel, started)
            self.db.executemany(
                "INSERT INTO asked VALUES (?,?,?,?,1,?) ON CONFLICT(id) DO UPDATE SET "
                "visible=excluded.visible, last_asked=excluded.last_asked, "
                "times=times+1, request_seq=excluded.request_seq",
                [(i, int(i in got), started, started, seq) for i in ids])
            self.db.execute("UPDATE requests SET n_asked=?, n_returned=? WHERE seq=?",
                            (len(ids), len(issues), seq))
        extra = got - set(ids)
        if extra:
            print(f"request {seq}: {len(extra)} issues returned that weren't asked",
                  file=self.log, flush=True)
        return len(got & set(ids))

    def resolve_monorail(self, old_id):
        seq, st, rbody, rel, started = self.request("monorail", "GET",
                                                    MONORAIL_URL.format(old_id))
        return self._store_monorail(old_id, seq, st, rbody, started)

    def _store_monorail(self, old_id, seq, st, rbody, started):
        new = monorail_target(rbody) if st == 200 else None
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO monorail_map VALUES (?,?,?,?,?)",
                            (old_id, new, st, started, seq))
        return new

    def resolve_monorail_parallel(self, old_ids, jobs, progress=None):
        """Look up old IDs with up to `jobs` requests in flight, each worker
        waiting `interval` s between its own requests. Workers only do HTTP;
        this thread logs and stores every response, in order. There is no
        back-off here: the first reply that isn't a stub, 403 or 404 stops
        the run (rerun to resume, or go serial). Returns how many mapped."""
        from concurrent.futures import ThreadPoolExecutor
        if not 1 <= jobs <= MONORAIL_MAX_JOBS:
            raise SystemExit(f"--jobs must be 1..{MONORAIL_MAX_JOBS}")
        stop = threading.Event()

        def one(old):
            if stop.is_set():
                return None
            sent = self.send("GET", MONORAIL_URL.format(old))
            if sent[2][0] not in (200, 403, 404):
                stop.set()  # every worker stops at once, before main has logged it
            if self.interval:
                self.sleep(self.interval)
            return sent

        mapped = n = 0
        error = None
        ex = ThreadPoolExecutor(max_workers=jobs)
        try:
            # Every reply that arrived is logged and kept, also those after an
            # error; IDs a stopped worker skipped come back as None.
            for old, sent in zip(old_ids, ex.map(one, old_ids)):
                if sent is None:
                    continue
                seq, st, h, rbody, rel, started, outcome, final = self.record("monorail", None, sent)
                if outcome != "ok":
                    stop.set()
                    retry = outcome in ("http", "net") and (st in (-1, 429) or st >= 500)
                    if error is None or (isinstance(error, Backoff) and not retry):
                        error = (Backoff if retry else Stop)(
                            f"request {seq}: HTTP {st} ({outcome}) on a Monorail lookup")
                    continue
                mapped += self._store_monorail(old, seq, st, rbody, started) is not None
                n += 1
                if progress:
                    progress(n, mapped)
        finally:
            stop.set()
            ex.shutdown(wait=True, cancel_futures=True)
        if error:
            raise error
        return mapped


# ---------------------------------------------------------------- commands

def cmd_ids(args):
    db = open_db()
    counts = build_wanted(db, git_footers(), security_ids())
    for k, v in counts.items():
        print(f"{k:>16}: {v:,}")


def _eta(n_requests, interval):
    return n_requests * (interval + 0.8) / 3600


def cmd_fetch(args):
    db = open_db()
    ids = to_ask(db, args.retry_missing, args.older_than)
    if args.limit:
        ids = ids[:args.limit * BATCH]
    n_req = -(-len(ids) // BATCH)
    print(f"{len(ids):,} IDs to ask, {n_req:,} requests, about "
          f"{_eta(n_req, args.interval):.1f} h at {args.interval} s", flush=True)
    if not args.go:
        print("dry run; add --go to fetch")
        return
    with fetch_lock():
        f = Fetcher(db, interval=args.interval)
        asked = seen = 0
        t0 = time.monotonic()
        try:
            for k in range(0, len(ids), BATCH):
                batch = ids[k:k + BATCH]
                seen += f.fetch_batch(batch)
                asked += len(batch)
                n = k // BATCH + 1
                if n % 20 == 0 or n == n_req:
                    rate = (time.monotonic() - t0) / n
                    print(f"{store.now_iso()} {n:,}/{n_req:,} requests, {asked:,} asked, "
                          f"{seen:,} visible ({seen / asked:.0%}), "
                          f"{(n_req - n) * rate / 3600:.1f} h left", flush=True)
        except Stop as e:
            print(f"STOP: {e}", flush=True)
            sys.exit(2)
        except KeyboardInterrupt:
            print("interrupted; rerun to resume", flush=True)
            sys.exit(130)
    print(f"done: {asked:,} asked, {seen:,} visible", flush=True)


def mapped_already(db):
    return {r[0] for r in db.execute("SELECT old_id FROM monorail_map")}


def cmd_monorail(args):
    db = open_db()
    ids = [r[0] for r in db.execute(
        f"SELECT id FROM wanted WHERE id < {MONORAIL_MAX} "
        "AND id NOT IN (SELECT old_id FROM monorail_map) ORDER BY id DESC")]
    if args.limit:
        ids = ids[:args.limit]
    print(f"{len(ids):,} Monorail IDs to map, about "
          f"{_eta(len(ids), args.interval) / args.jobs:.1f} h at {args.interval} s, "
          f"{args.jobs} at once", flush=True)
    if not args.go:
        print("dry run; add --go to fetch")
        return
    with fetch_lock("monorail.lock"):
        f = Fetcher(db, interval=args.interval, min_interval=0)
        mapped = 0

        def progress(n, m):
            if n % 200 == 0 or n == len(ids):
                print(f"{store.now_iso()} {n:,}/{len(ids):,} looked up, {m:,} mapped", flush=True)
        try:
            if args.jobs > 1:
                done, attempt = 0, 0
                while True:
                    seen = mapped_already(db)
                    left = [i for i in ids if i not in seen]
                    try:
                        f.resolve_monorail_parallel(left, args.jobs,
                                                    lambda n, m: progress(done + n, m))
                        break
                    except Backoff as e:
                        seen = mapped_already(db)
                        now_left = sum(1 for i in ids if i not in seen)
                        if now_left < len(left):
                            attempt = 0  # progress since the last error
                        if attempt == len(f.backoff):
                            raise Stop(f"{e}; still failing after {attempt} back-offs")
                        done = len(ids) - now_left
                        print(f"{e}; backing off {f.backoff[attempt]} s "
                              f"({attempt + 1}/{len(f.backoff)})", flush=True)
                        f.sleep(f.backoff[attempt])
                        attempt += 1
            else:
                for n, old in enumerate(ids, 1):
                    mapped += f.resolve_monorail(old) is not None
                    progress(n, mapped)
        except Stop as e:
            print(f"STOP: {e}", flush=True)
            sys.exit(2)
    print("done; run fetch to ask for the mapped IDs", flush=True)


def cmd_parse(args):
    """Rebuild the bugs table from raw/ (offline)."""
    db = open_db()
    d = bugs_dir()
    rows = db.execute("SELECT seq, file, started_at FROM requests WHERE kind='list' "
                      "AND outcome='ok' AND file IS NOT NULL ORDER BY seq").fetchall()
    with db:
        db.execute("DELETE FROM bugs")
        for seq, rel, started in rows:
            with gzip.open(os.path.join(d, rel), "rb") as fh:
                store_issues(db, search_issues(fh.read()), rel, started)
    print(f"{db.execute('SELECT count(*) FROM bugs').fetchone()[0]:,} bugs from "
          f"{len(rows):,} responses")


def cmd_status(args):
    db = open_db()
    q = lambda s: db.execute(s).fetchone()
    print("wanted:", q("SELECT count(*), sum(bug_commits>0 OR fixed_commits>0), sum(security), "
                       f"sum(id < {MONORAIL_MAX}) FROM wanted"),
          "(all, footer, security, monorail-era)")
    print("monorail_map:", q("SELECT count(*), count(new_id) FROM monorail_map"),
          "(looked up, mapped)")
    print("asked:", q("SELECT count(*), sum(visible) FROM asked"), "(asked, visible)")
    print("still to ask:", len(to_ask(db)))
    print("requests:", q("SELECT count(*), sum(wire_bytes), sum(body_bytes), "
                         "round(sum(elapsed_s)), min(started_at), max(started_at) "
                         "FROM requests"),
          "(n, wire bytes, body bytes, s in flight, first, last)")
    print("outcomes:", db.execute("SELECT kind, outcome, http_status, count(*) FROM requests "
                                  "GROUP BY 1,2,3").fetchall())
    print("bugs:", q("SELECT count(*) FROM bugs"))
    for col in ("type_name", "status_name", "priority", "severity", "regression"):
        print(f"  {col}:", db.execute(f"SELECT {col}, count(*) FROM bugs GROUP BY 1 "
                                      "ORDER BY 2 DESC LIMIT 12").fetchall())


def main(argv=None):
    ap = argparse.ArgumentParser(prog="cosh.bugs", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ids").set_defaults(fn=cmd_ids)
    for name, fn in (("fetch", cmd_fetch), ("monorail", cmd_monorail)):
        p = sub.add_parser(name)
        p.add_argument("--go", action="store_true")
        p.add_argument("--interval", type=float, default=DEFAULT_INTERVAL)
        p.add_argument("--limit", type=int, help="at most this many requests")
        if name == "monorail":
            p.add_argument("--jobs", type=int, default=MONORAIL_MAX_JOBS,
                           help=f"lookups in flight at once, 1..{MONORAIL_MAX_JOBS}")
        if name == "fetch":
            p.add_argument("--retry-missing", action="store_true",
                           help="re-ask IDs that weren't visible")
            p.add_argument("--older-than", type=float, default=30,
                           help="with --retry-missing: last asked at least this many days ago")
        p.set_defaults(fn=fn)
    sub.add_parser("parse").set_defaults(fn=cmd_parse)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    args = ap.parse_args(argv)
    if getattr(args, "interval", 0) < MIN_INTERVAL:
        ap.error("--interval can't be negative")
    if args.cmd == "monorail":
        if not 1 <= args.jobs <= MONORAIL_MAX_JOBS:
            ap.error(f"--jobs must be 1..{MONORAIL_MAX_JOBS}")
    args.fn(args)


if __name__ == "__main__":
    main()
