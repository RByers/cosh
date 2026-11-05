"""Addressed-comment classification (docs/comment-classifier.md).

A *thread* is a reviewer's top-level comment plus every reply to it (Gerrit
`in_reply_to` chains). A thread is *addressed* if the reviewer's feedback led
the CL's owner to change the CL itself. Each non-owner comment in an addressed
thread, written no later than the owner's last reply in it, scores one point
for its author (summarize, `addressed_comments`).

Two classifiers decide threads:
  - a free regex, computed by `derive` for every thread: the owner's first
    reply starts with a Done-type word ("Done", "Fixed", "Fix applied." ...);
  - Claude Haiku via headless `claude -p`, run by `cosh classify` for the
    threads the regex doesn't settle. Its labels go to labels.sqlite, which
    is never deleted (they cost Max usage to make) and keyed by each
    thread's input hash, so a thread that grows is relabelled.

Threads the owner never replied to, or started by the owner, score nothing
and need no label.
"""

import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from collections import defaultdict
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from . import store

DEF_VERSION = 1
LABELS_FILE = "labels.sqlite"
LOCK_FILE = "classify.lock"

DEFINITION = """\
Each item is a Gerrit code-review thread on a Chromium CL. REVIEWER wrote the
first comment; OWNER is the CL's author; OTHER is anyone else. Decide whether
the feedback in the thread led the owner to change the CL itself, in this CL:

done = the owner changed something in response: code, tests, code comments,
  build files or the commit message, including partly adopting the
  suggestion, or making a different/better change than the one suggested
  because of it. "Done", "Fixed", "Updated", "Removed", "Fix applied." and
  free-text descriptions of a change all count. Adding a TODO or a comment
  in the code in response counts. Moving code out of this CL (into another
  CL) because of the comment counts as a change to this CL.
not = no change in this CL: the owner answered a question, explained, pushed
  back, the reviewer withdrew or accepted the explanation, the comment was an
  approval/thanks/FYI, or the work was done in or deferred to a separate or
  follow-up CL or bug. A bare "Acknowledged"/"Ack" with no sign of a change
  is "not". A "Done" in reply to something that isn't a request for a change
  (a reminder, a status note) is "not".

Judge the whole thread, including later replies. Judge only from the text."""

SYSTEM_PROMPT = "You are a precise classifier of code-review threads."
PROMPT_SHA = hashlib.sha256((SYSTEM_PROMPT + "\n" + DEFINITION).encode()).hexdigest()

# The owner's first reply starts with one of these: the thread is addressed,
# no model needed (precision 0.98 on the labelled set).
DONE = re.compile(r"^\W*(done|fixed|fix applied|fix(ed)? (it|this)|updated|removed|changed|added|renamed|moved|deleted|"
                  r"reverted|replaced|switched|applied|refactored|good (catch|call|point|idea)|nice catch|"
                  r"great (catch|point|idea)|thanks?( you)?[,.!]* *(done|fixed|updated)|"
                  r"ok[,.!]* *(done|fixed|updated))\b", re.I)

ROLE = {"R": "REVIEWER", "O": "OWNER", "X": "OTHER"}
ROOT_CHARS, REPLY_CHARS, MAX_REPLIES = 2000, 1200, 30


def _ts(c):
    return (c.get("updated") or "")[:19]


def build_threads(comments, owner_id, include_owner=False):
    """Reviewer-started threads of one CL from its comments ({path: [REST
    comment]}); with include_owner, the owner's threads too. Each is a dict
    with root_id, root_account, path and `items`: [(comment id, account id,
    written_at, message)] in time order. Comments whose parent is missing
    start their own thread."""
    flat = []
    for path, cl in (comments or {}).items():
        for c in cl:
            aid = (c.get("author") or {}).get("_account_id")
            if aid is None or not c.get("updated") or not c.get("id"):
                continue
            flat.append((path, c, aid))
    by_id = {c["id"]: (path, c, aid) for path, c, aid in flat}
    roots = {}

    def root_of(cid):
        seen = set()
        while True:
            parent = by_id[cid][1].get("in_reply_to")
            if not parent or parent not in by_id or cid in seen:
                return cid
            seen.add(cid)
            cid = parent
    groups = defaultdict(list)
    for path, c, aid in flat:
        r = roots.get(c["id"]) or root_of(c["id"])
        roots[c["id"]] = r
        groups[r].append((_ts(c), c["id"], aid, c.get("message") or ""))
    out = []
    for rid, items in groups.items():
        items.sort()
        root_account = by_id[rid][2]
        if root_account == owner_id and not include_owner:
            continue
        out.append(dict(root_id=rid, root_account=root_account, path=by_id[rid][0],
                        items=[(cid, aid, ts, msg) for ts, cid, aid, msg in items]))
    return out


def render(thread, owner_id):
    """The text the model sees (and input_hash covers)."""
    root_aid = thread["root_account"]
    lines = []
    for i, (_, aid, _, msg) in enumerate(thread["items"][:MAX_REPLIES + 1]):
        if i == 0:
            lines.append(f"REVIEWER: {msg[:ROOT_CHARS]}")
            continue
        role = "O" if aid == owner_id else "R" if aid == root_aid else "X"
        lines.append(f"{ROLE[role]}: {msg[:REPLY_CHARS]}")
    if len(thread["items"]) > MAX_REPLIES + 1:
        lines.append(f"[{len(thread['items']) - MAX_REPLIES - 1} more replies not shown]")
    return "\n".join(lines)


def input_hash(text):
    """First 8 bytes of sha256(definition version + text), as a signed int64."""
    d = hashlib.sha256(f"{DEF_VERSION}\n{text}".encode()).digest()[:8]
    return int.from_bytes(d, "big", signed=True)


def thread_row(thread, owner_id):
    """Columns of derived.threads for one thread."""
    owner_replies = [(ts, msg) for _, aid, ts, msg in thread["items"][1:] if aid == owner_id]
    return dict(root_uuid=thread["root_id"], root_account=thread["root_account"],
                n_comments=len(thread["items"]),
                last_owner_reply_at=owner_replies[-1][0] if owner_replies else None,
                input_hash=input_hash(render(thread, owner_id)),
                regex_addressed=int(bool(owner_replies) and bool(DONE.match(owner_replies[0][1].strip()))))


# ---------------------------------------------------------------- labels.sqlite

LABELS_SCHEMA = """
CREATE TABLE IF NOT EXISTS classifiers (
  classifier_id      INTEGER PRIMARY KEY,
  model              TEXT NOT NULL,        -- resolved model id, e.g. claude-haiku-5-5
  definition_version INTEGER NOT NULL,
  prompt_sha256      TEXT NOT NULL,
  created_at         TEXT NOT NULL,
  UNIQUE (model, definition_version, prompt_sha256)
) STRICT;
CREATE TABLE IF NOT EXISTS runs (
  run_id INTEGER PRIMARY KEY, classifier_id INTEGER, started_at TEXT NOT NULL, finished_at TEXT,
  weeks TEXT, threads INTEGER, calls INTEGER, tokens INTEGER, usd_equiv REAL, seconds REAL
) STRICT;
-- One row per (thread, classifier, input): integer ids and an 8-byte hash keep
-- a row near 40 bytes (docs/comment-classifier.md, "Size and speed").
CREATE TABLE IF NOT EXISTS labels (
  change_number INTEGER NOT NULL,
  root_uuid     TEXT    NOT NULL,
  classifier_id INTEGER NOT NULL,
  input_hash    INTEGER NOT NULL,
  addressed     INTEGER NOT NULL,
  run_id        INTEGER NOT NULL,
  PRIMARY KEY (change_number, root_uuid, classifier_id, input_hash)
) STRICT, WITHOUT ROWID;
"""


def labels_path(data_dir=store.DATA_DIR):
    return os.path.join(data_dir, LABELS_FILE)


def open_labels(data_dir=store.DATA_DIR, path=None):
    return store.connect(path or labels_path(data_dir), LABELS_SCHEMA)


def active_classifier(labels_db):
    """The newest classifier for the current definition and prompt, or None."""
    row = labels_db.execute("""SELECT classifier_id, model FROM classifiers
                               WHERE definition_version = ? AND prompt_sha256 = ?
                               ORDER BY classifier_id DESC LIMIT 1""", (DEF_VERSION, PROMPT_SHA)).fetchone()
    return row


# ---------------------------------------------------------------- claude -p

SCHEMA = {"type": "object", "properties": {"labels": {"type": "array", "items": {
    "type": "object", "properties": {"id": {"type": "string"}, "done": {"type": "boolean"}},
    "required": ["id", "done"]}}}, "required": ["labels"]}


def claude_batch(model, items, cwd):
    """Classify [(id, text)] in one headless call. Returns ({id: bool}, cost)."""
    text = "\n\n".join(f"### {i}\n{t}" for i, t in items)
    prompt = (DEFINITION + "\n\nClassify every item below. Return JSON only: "
              '{"labels": [{"id": "T0", "done": true}, ...]} with one entry per item.\n\n' + text)
    cmd = ["claude", "-p", "--model", model, "--output-format", "json", "--tools", "",
           "--system-prompt", SYSTEM_PROMPT,
           "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--disable-slash-commands",
           "--exclude-dynamic-system-prompt-sections", "--no-session-persistence",
           "--json-schema", json.dumps(SCHEMA)]
    t0 = time.time()
    p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=cwd)
    wall = time.time() - t0
    try:
        d = json.loads(p.stdout)
    except ValueError:
        raise RuntimeError(f"claude -p failed (exit {p.returncode}): {(p.stderr or p.stdout)[:500]}")
    if d.get("is_error"):
        raise RuntimeError(f"claude -p error: {str(d.get('result'))[:500]}")
    out = d.get("structured_output") or {}
    if not out:
        m = re.search(r"\{.*\}", d.get("result") or "", re.S)
        out = json.loads(m.group(0)) if m else {}
    u = d.get("usage", {})
    models = sorted(d.get("modelUsage", {}))
    got = {x["id"]: bool(x["done"]) for x in out.get("labels", [])
           if isinstance(x, dict) and "id" in x and "done" in x}
    return got, dict(wall=wall, model=models[0] if models else model, usd=d.get("total_cost_usd") or 0,
                     tokens=sum(u.get(k, 0) or 0 for k in ("input_tokens", "cache_creation_input_tokens",
                                                           "cache_read_input_tokens", "output_tokens")))


def run_batches(batches, call, jobs, save):
    """Runs call(items) for each (items, ctx) from the `batches` iterator, up to
    `jobs` at once, and save(ctx, got, cost) for each in completion order. Only
    `call` runs off the calling thread: `batches` is drawn and `save` called on
    it, so neither needs to be thread-safe, and at most `jobs` batches are
    prepared ahead. If a call fails, no more are started; the ones in flight
    finish and are saved, then the first error is raised."""
    batches = iter(batches)
    error = None
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        running = {}
        while True:
            while error is None and len(running) < jobs:
                nxt = next(batches, None)
                if nxt is None:
                    break
                running[pool.submit(call, nxt[0])] = nxt[1]
            if not running:
                break
            finished, _ = wait(running, return_when=FIRST_COMPLETED)
            for f in finished:
                ctx = running.pop(f)
                try:
                    got, cost = f.result()
                except Exception as e:      # keep the others' labels, then fail
                    error = error or e
                    continue
                save(ctx, got, cost)
    if error is not None:
        raise error


# ---------------------------------------------------------------- the classify step

def pending_threads(db, labels_db, weeks):
    """[(change_number, root_uuid, input_hash, owner_account, host, project)] that need a
    model label: a human-started thread on a human-owned main CL, with an
    owner reply, not settled by the regex, with a comment written in `weeks`
    (all weeks if None), and no label yet for its current input."""
    cid = active_classifier(labels_db)
    have = set()
    if cid:
        have = {(n, r, h) for n, r, h in labels_db.execute(
            "SELECT change_number, root_uuid, input_hash FROM labels WHERE classifier_id = ?", (cid[0],))}
    week_filter = ""
    args = []
    if weeks:
        week_filter = f"AND EXISTS (SELECT 1 FROM comments x WHERE x.host = t.host AND x.change_number = t.change_number " \
                      f"AND x.root_uuid = t.root_uuid AND x.iso_week IN ({','.join('?' * len(weeks))}))"
        args = list(weeks)
    rows = db.execute(f"""
        SELECT t.change_number, t.root_uuid, t.input_hash, c.owner_account, t.host, c.project FROM threads t
        CROSS JOIN changes c ON c.host = t.host AND c.change_number = t.change_number
        CROSS JOIN accounts a ON a.host = t.host AND a.account_id = t.root_account
        WHERE t.last_owner_reply_at IS NOT NULL AND t.regex_addressed = 0
          AND a.is_bot = 0 AND c.is_bot_owned = 0 AND c.branch = 'main' {week_filter}
        ORDER BY t.change_number, t.root_uuid""", args).fetchall()
    return [r for r in rows if (r[0], r[1], r[2]) not in have]


def classify(data_dir=store.DATA_DIR, db_path=None, weeks=None, model="haiku", batch=100,
             max_threads=None, dry_run=False, labels_db_path=None, jobs=8):
    from .derive import load_comments, prefetch_notedb
    path = db_path or os.path.join(data_dir, store.DERIVED_FILE)
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    if not store.has_table(db, "threads"):
        raise SystemExit(f"{path} has no threads table; rebuild it with python3 -m cosh derive")
    labels_db = open_labels(data_dir, labels_db_path)
    todo = pending_threads(db, labels_db, weeks)
    if max_threads is not None:
        todo = todo[:max_threads]
    calls = -(-len(todo) // batch)
    print(f"{len(todo)} threads need a model label ({calls} calls of up to {batch}, {jobs} at a time; "
          f"roughly {len(todo) * 230 / 1e6:.1f}M tokens)", file=sys.stderr)
    if dry_run or not todo:
        return len(todo)
    lock = open(os.path.join(data_dir, LOCK_FILE), "w")
    import fcntl
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit(f"another cosh classify holds {LOCK_FILE}")
    raw = store.open_raw_ro(data_dir)
    repos = {}
    cwd = os.environ.get("TMPDIR") or "/tmp"
    started = store.now_iso()
    with labels_db:
        run_id = labels_db.execute("INSERT INTO runs(started_at, weeks) VALUES (?, ?)",
                                   (started, json.dumps(sorted(weeks)) if weeks else None)).lastrowid
    st = dict(done=0, tokens=0, calls=0, stale=0, missing=0, usd=0.0, seconds=0.0, classifier_id=None)
    t_run = time.time()

    def prepare():
        """(items, keys) per batch of `todo`, with comments read from NoteDb."""
        for b in range(0, len(todo), batch):
            chunk = todo[b:b + batch]
            cls = sorted({(host, project, n) for n, _, _, _, host, project in chunk})
            notes = prefetch_notedb(repos, cls, "auto")
            items, keys = [], {}
            threads_by_cl = {}
            for n, root, h, owner, host, project in chunk:
                if n not in threads_by_cl:
                    comments, _ = load_comments(raw, repos, host, project, n, "auto", notes)
                    threads_by_cl[n] = {t["root_id"]: t for t in build_threads(comments, owner)}
                t = threads_by_cl[n].get(root)
                if t is None:
                    st["missing"] += 1
                    continue
                text = render(t, owner)
                if input_hash(text) != h:        # NoteDb changed since derive: rerun derive first
                    st["stale"] += 1
                    continue
                key = f"T{len(items)}"
                items.append((key, text))
                keys[key] = (n, root, h)
            if items:
                yield items, keys

    def save(keys, got, cost):
        st["calls"] += 1
        st["tokens"] += cost["tokens"]
        st["usd"] += cost["usd"]
        st["seconds"] += cost["wall"]
        with labels_db:
            if st["classifier_id"] is None:
                labels_db.execute("INSERT OR IGNORE INTO classifiers(model, definition_version, prompt_sha256, "
                                  "created_at) VALUES (?,?,?,?)", (cost["model"], DEF_VERSION, PROMPT_SHA,
                                                                   store.now_iso()))
                st["classifier_id"] = labels_db.execute(
                    "SELECT classifier_id FROM classifiers WHERE model=? AND definition_version=? AND "
                    "prompt_sha256=?", (cost["model"], DEF_VERSION, PROMPT_SHA)).fetchone()[0]
            rows = [(keys[k][0], keys[k][1], st["classifier_id"], keys[k][2], int(v), run_id)
                    for k, v in got.items() if k in keys]
            labels_db.executemany("INSERT OR REPLACE INTO labels VALUES (?,?,?,?,?,?)", rows)
            st["done"] += len(rows)
            labels_db.execute("UPDATE runs SET classifier_id=?, threads=?, calls=?, tokens=?, usd_equiv=?, "
                              "seconds=?, finished_at=? WHERE run_id=?",
                              (st["classifier_id"], st["done"], st["calls"], st["tokens"], st["usd"],
                               st["seconds"], store.now_iso(), run_id))
        print(f"  batch {st['calls']}/{calls}: {len(rows)}/{len(keys)} labelled, {cost['wall']:.0f}s, "
              f"{cost['tokens']} tokens ({st['done']}/{len(todo)} done)", file=sys.stderr)

    run_batches(prepare(), lambda items: claude_batch(model, items, cwd), jobs, save)
    print(f"labelled {st['done']} threads in {st['calls']} calls: {st['tokens']} tokens, "
          f"{time.time() - t_run:.0f}s wall ({st['seconds']:.0f}s of calls, {jobs} at a time), "
          f"${st['usd']:.2f} API-equivalent; {st['stale']} stale (rerun derive), "
          f"{st['missing']} not found in NoteDb", file=sys.stderr)
    lock.close()
    return st["done"]
