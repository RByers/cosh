"""Review-comment sentiment, in aggregate (docs/sentiment.md).

Every human comment written in a week, or a deterministic sample of them,
gets a score from -1 (very angry or upset) through 0 (neutral) to +1 (very
positive or grateful), plus a flag for anger or frustration about AI in code
review. Scores come from Claude Haiku via headless `claude -p` (prompt tuned
against a sample labelled by Claude Opus, docs/sentiment.md) and are stored in
data/private/sentiment.sqlite, which, like labels.sqlite, costs Max usage to
remake.

Nothing here names people for negative tone or gives orgs tone figures
(docs/plan.md, ground rule 5). Comment rows carry no identities; `praise`
attaches them only to comments scored as praise. `summary` writes the
public monthly trend and `praise` the praise leaderboard.

Each comment has a role (the CL owner's or a reviewer's) and a target kind:
  - "person": a reply to a human, or a reviewer's thread-starting comment
    (aimed at the CL owner);
  - "ai": a reply to an AI reviewer or to agent-written text, or a comment
    addressed "to <agent>: ...";
  - None: the owner's own thread-starting comments.

The owner's notes to self (target None: a thread starter, or a reply in a
thread nobody else has joined) are left out of every analysis
(`is_self_note`, 2026-11-10): only comments to someone else count.
"""

import hashlib
import json
import math
import os
import re
import sqlite3
import sys
import time
from collections import defaultdict
from datetime import date

from . import store
from .bots import is_bot_account
from .derive import human_text, is_ai_comment, load_comments, prefetch_notedb

SENTIMENT_FILE = "sentiment.sqlite"
OUT_DIR = "sentiment"
CTX_CHARS, TEXT_CHARS, MAX_CTX = 500, 1500, 4


def week_bounds(week):
    """'2026-W44' -> ('2026-10-26 00:00:00', '2026-11-02 00:00:00')."""
    y, w = week.split("-W")
    mon = date.fromisocalendar(int(y), int(w), 1)
    sun_next = date.fromordinal(mon.toordinal() + 7)
    return f"{mon} 00:00:00", f"{sun_next} 00:00:00"


def weeks_in(spec):
    """'2026-W37:2026-W44' (or one week) -> ['2026-W37', ..., '2026-W44']."""
    a, _, b = spec.partition(":")
    b = b or a
    out, d = [], date.fromisocalendar(int(a[:4]), int(a[6:]), 1)
    end = date.fromisocalendar(int(b[:4]), int(b[6:]), 1)
    while d <= end:
        y, w, _ = d.isocalendar()
        out.append(f"{y}-W{w:02d}")
        d = date.fromordinal(d.toordinal() + 7)
    return out


def in_sample(cid, frac):
    """Deterministic sample of comment ids ('<cl>/<uuid>'): the same ids at any
    rate below are kept at every larger rate, and reruns pick the same ones."""
    return int(hashlib.sha256(cid.encode()).hexdigest()[:8], 16) < frac * 2 ** 32


def collect(week, data_dir=store.DATA_DIR, start=None, end=None, keep=None, annotate=None):
    """[comment dict] for every comment by a human account written in `week`
    (or in [start, end)) on a human-owned CL, with thread context, role and
    target kind. keep(id) filters comments before they are built (for
    samples). annotate(row, ids), if given, may add fields to each row; ids
    holds the host, day and account ids behind the role and target. Rows
    carry no identities otherwise."""
    if week:
        start, end = week_bounds(week)
    db = sqlite3.connect(f"file:{os.path.join(data_dir, store.DERIVED_FILE)}?mode=ro", uri=True)
    accounts = {(h, a): dict(email=e, is_bot=b) for h, a, e, b in
                db.execute("SELECT host, account_id, email, is_bot FROM accounts")}
    cls = db.execute("""SELECT host, project, change_number, owner_account, subject, status FROM changes
                        WHERE updated_at >= ? AND created_at < ? AND is_bot_owned = 0""",
                     (start, end)).fetchall()
    raw = store.open_raw_ro(data_dir)
    repos, out = {}, []
    for b in range(0, len(cls), 400):
        chunk = cls[b:b + 400]
        notes = prefetch_notedb(repos, [(h, p, n) for h, p, n, *_ in chunk], "auto")
        for host, project, number, owner, subject, status in chunk:
            comments, _ = load_comments(raw, repos, host, project, number, "auto", notes)
            out.extend(_cl_comments(host, project, number, owner, subject, status, comments or {},
                                    accounts, start, end, keep, annotate))
    return out


# Text an AI agent posted under a human account ("[Claude] nit: ...",
# "[Kaizen Chrome] Understood.", "[AI-generated] Done"): not human sentiment.
AI_WRITTEN = re.compile(r"^\s*(\[(ai|ai[- ]generated|ai experiment|claude|opus|gemini|kaizen[\w ]*|agent[\w-]*|"
                        r"jules|copilot|maestro[\w ]*)\]|maestro ai\s*:|ai\s*:)", re.I)
# A human addressing an agent: "to kaizen bot: this looks like overkill".
TO_AGENT = re.compile(r"^\s*to [\w ]{1,20}\b(bot|agent|ai)\s*:", re.I)


def _ai_text(c):
    return bool(AI_WRITTEN.match(c.get("message") or ""))


def _is_bot(accounts, host, aid, c=None):
    """A bot account, an account with no email, or AI-written text."""
    a = accounts.get((host, aid)) or {}
    return bool(a.get("is_bot")) or (c is not None and (is_ai_comment(c) or _ai_text(c))) or not a.get("email")


def _cl_comments(host, project, number, owner, subject, status, comments, accounts, start, end, keep=None,
                 annotate=None):
    flat = {}
    for path, cl in comments.items():
        for c in cl:
            aid = (c.get("author") or {}).get("_account_id")
            if aid is None or not c.get("id") or not c.get("updated"):
                continue
            flat[c["id"]] = (path, c, aid)
    out = []
    for cid, (path, c, aid) in flat.items():
        ts = c["updated"][:19]
        if not (start <= ts < end) or (keep and not keep(f"{number}/{cid}")):
            continue
        if _is_bot(accounts, host, aid, c):
            continue
        text = human_text(c.get("message"))
        if not text:
            continue
        # The chain of parents, oldest first, for context.
        chain, seen, p = [], {cid}, c.get("in_reply_to")
        while p and p in flat and p not in seen:
            seen.add(p)
            chain.append(flat[p])
            p = flat[p][1].get("in_reply_to")
        chain.reverse()
        parent = chain[-1] if chain else None
        if parent is not None:
            t_aid = parent[2]
            t_bot = _is_bot(accounts, host, t_aid, parent[1])
        elif aid != owner:
            t_aid = owner
            t_bot = _is_bot(accounts, host, owner)
        else:
            t_aid, t_bot = None, False
        if t_aid == aid:                 # a reply to oneself: aim it at the thread's other party
            t_aid, t_bot = None, False
            for _, pc, paid in reversed(chain):
                if paid != aid:
                    t_aid = paid
                    t_bot = _is_bot(accounts, host, paid, pc)
                    break
        if TO_AGENT.match(text) or (parent is not None and _ai_text(parent[1])):
            t_bot = True
            t_aid = t_aid or -1
        if aid == owner and not t_aid and not t_bot:
            continue                     # the owner's note to self (`is_self_note`)
        day = ts[:10]

        def role(x_aid, x_c=None):
            if x_c is not None and (is_ai_comment(x_c) or _ai_text(x_c)):
                return "AI"
            if x_aid == owner:
                return "AUTHOR"
            return "BOT" if _is_bot(accounts, host, x_aid) else "REVIEWER"
        ctx = [f"{role(paid, pc)}: {human_text(pc.get('message'))[:CTX_CHARS]}" for _, pc, paid in chain[-MAX_CTX:]]
        if len(chain) > MAX_CTX:
            ctx.insert(0, f"[{len(chain) - MAX_CTX} earlier comments not shown]")
        row = dict(
            id=f"{number}/{cid}", host=host, project=project, cl=number, uuid=cid, subject=subject,
            cl_status=status, path=path, written_at=ts, author_role="AUTHOR" if aid == owner else "REVIEWER",
            target_kind="ai" if t_bot else "person" if t_aid else None, text=text[:TEXT_CHARS], context=ctx,
            n_ai_in_thread=sum(1 for _, pc, _ in chain if is_ai_comment(pc)))
        if annotate:
            annotate(row, dict(host=host, day=day, owner=owner, author=aid, target=None if t_bot else t_aid))
        out.append(row)
    return out


def render(c):
    """The text the model sees for one comment."""
    me = "AUTHOR" if c["author_role"] == "AUTHOR" else "REVIEWER"
    lines = [f"File: {c['path']}"]
    if c["context"]:
        lines.append("Earlier in the thread:")
        lines += ["  " + x.replace("\n", "\n  ") for x in c["context"]]
    lines.append(f">>> {me} (the comment to score): {c['text']}")
    return "\n".join(lines)


# Bare acknowledgements and requests score 0 without a model call.
TRIVIAL = re.compile(r"^\W*(done|ack(nowledged)?|lgtm|ptal|fixed|resolved|marked as resolved|thanks?( you)?|"
                     r"ok(ay)?|sgtm|nit|\+1|will do|updated|lgtm,? thanks?( you)?|done,? thanks?( you)?|"
                     r"thanks?( you)?,? done)\W*$", re.I)

PROMPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "scripts", "sentiment_prompts")
PROMPT_VERSION = "v3"          # the prompt `score` uses; tuning: docs/sentiment.md
SYSTEM_PROMPT = "You rate the tone of code-review comments precisely and consistently."
WHY_CHARS = 80
SCHEMA = {"type": "object", "properties": {"scores": {"type": "array", "items": {
    "type": "object", "properties": {"id": {"type": "string"}, "s": {"type": "number", "minimum": -1, "maximum": 1},
                                     "ai": {"type": "boolean"},
                                     "why": {"type": "string", "maxLength": WHY_CHARS}},
    "required": ["id", "s", "ai"]}}}, "required": ["scores"]}
# The model's short reason is the one free-text field it can return
# (SECURITY.md, "Where untrusted text goes"): keep it to plain words and
# punctuation, no markup, URLs or control characters, and short.
_WHY_DROP = re.compile(r"[^\w\s.,;:'\"!?()/+%\-–—]")


def clean_why(why):
    if not isinstance(why, str):
        return ""
    why = re.sub(r"\S*://\S*", "", why)              # no URLs
    why = " ".join(_WHY_DROP.sub("", why).split())   # no markup, control chars or newlines
    return why[:WHY_CHARS]
OUTPUT_SPEC = ('Score every item below. Return JSON only: {"scores": [{"id": "C0", "s": 0.0, "ai": false}, ...]}, '
               'one entry per item, s rounded to one decimal. Add "why" (at most 8 words) only when |s| >= 0.5 '
               'or ai is true.')


def load_prompt(version=None):
    with open(os.path.join(PROMPT_DIR, f"{version or PROMPT_VERSION}.txt")) as f:
        return f.read().strip()


def prompt_sha(definition):
    return hashlib.sha256((SYSTEM_PROMPT + "\n" + definition + "\n" + OUTPUT_SPEC).encode()).hexdigest()


def input_hash(text):
    d = hashlib.sha256(text.encode()).digest()[:8]
    return int.from_bytes(d, "big", signed=True)


def claude_args(model, schema=None, system=None):
    """claude -p flags: no tools, MCP servers or slash commands, no transcript,
    one-line system prompt, reply constrained to SCHEMA (SECURITY.md, layer 1)."""
    return ["-p", "--model", model, "--output-format", "json", "--tools", "",
            "--system-prompt", system or SYSTEM_PROMPT,
            "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--disable-slash-commands",
            "--exclude-dynamic-system-prompt-sections", "--no-session-persistence",
            "--json-schema", json.dumps(schema or SCHEMA)]


CRASH_EXITS = (134, 139)   # SIGABRT, SIGSEGV as shell-style exit codes
CRASH_RETRIES = 2


def claude_scores(model, definition, items, sandbox):
    """Score [(key, text)] in one headless call: ({key: (s, ai, why)}, cost).

    The comment text is untrusted (SECURITY.md): claude gets no tools, its
    reply must match SCHEMA, `sandbox` (cosh.sandbox.Sandbox) runs it with a
    fresh HOME, a scrubbed env and, with bwrap, /home and the data hidden.
    Only ids that were sent are kept, scores are clamped to [-1, 1], and the
    short reason is reduced to plain text (clean_why)."""
    body = "\n\n".join(f"### {k}\n{t}" for k, t in items)
    prompt = definition + "\n\n" + OUTPUT_SPEC + "\n\n" + body
    sent = {k for k, _ in items}
    t0 = time.time()
    for attempt in range(CRASH_RETRIES + 1):
        p = sandbox.run(claude_args(model), prompt)
        # The CLI sometimes crashes (an abort or segfault: exit 134 or 139,
        # or killed by a signal) with nothing on stdout. Rerun those calls;
        # anything else, a usage limit say, fails as before.
        if p.stdout.strip() or (p.returncode not in CRASH_EXITS and p.returncode >= 0) or attempt == CRASH_RETRIES:
            break
        print(f"  claude -p crashed (exit {p.returncode}); retrying", file=sys.stderr)
        time.sleep(5)
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
    got = {}
    for x in out.get("scores", []):
        if isinstance(x, dict) and x.get("id") in sent and isinstance(x.get("s"), (int, float)) \
                and not isinstance(x.get("s"), bool) and math.isfinite(x["s"]):
            got[x["id"]] = (max(-1.0, min(1.0, float(x["s"]))), x.get("ai") is True, clean_why(x.get("why")))
    u = d.get("usage", {})
    models = sorted(d.get("modelUsage", {}))
    return got, dict(wall=wall, model=models[0] if models else model, usd=d.get("total_cost_usd") or 0,
                     tokens=sum(u.get(k, 0) or 0 for k in ("input_tokens", "cache_creation_input_tokens",
                                                           "cache_read_input_tokens", "output_tokens")))


def make_sandbox(mode="auto", data_dir=store.DATA_DIR):
    """A cosh.sandbox.Sandbox hiding the data and the code (SECURITY.md)."""
    from .sandbox import Sandbox
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    box = Sandbox(mode, hide=[data_dir, repo])
    print(f"sandbox: {box.describe()}", file=sys.stderr)
    return box


def score_items(rows, definition, model="haiku", batch=50, jobs=8, on_batch=None, sandbox="auto"):
    """{id: (s, ai, why)} for comment rows (TRIVIAL ones get (0, False, '')
    without a call). on_batch(got_by_id, cost) is called as batches finish.
    sandbox: a Sandbox, or a mode ('auto', 'bwrap', 'none') to make one."""
    from .classify import run_batches
    res = {r["id"]: (0.0, False, "") for r in rows if TRIVIAL.match(r["text"])}
    todo = [r for r in rows if r["id"] not in res]
    st = dict(calls=0, tokens=0, usd=0.0, n=0)
    if not todo:
        return res, st
    own = isinstance(sandbox, str)
    box = make_sandbox(sandbox) if own else sandbox

    def batches():
        for b in range(0, len(todo), batch):
            chunk = todo[b:b + batch]
            keys = {f"C{i}": r["id"] for i, r in enumerate(chunk)}
            yield [(k, render(r)) for k, r in zip(keys, chunk)], keys

    def save(keys, got, cost):
        mine = {keys[k]: v for k, v in got.items() if k in keys}
        res.update(mine)
        st["calls"] += 1
        st["tokens"] += cost["tokens"]
        st["usd"] += cost["usd"]
        st["n"] += len(mine)
        print(f"  batch {st['calls']}: {len(mine)}/{len(keys)} scored, {cost['wall']:.0f}s "
              f"({st['n']}/{len(todo)}, {st['tokens']} tokens, ${st['usd']:.2f})", file=sys.stderr)
        if on_batch:
            on_batch(mine, cost)

    try:
        run_batches(batches(), lambda items: claude_scores(model, definition, items, box), jobs, save)
    finally:
        if own:
            box.close()
    return res, st


# ---------------------------------------------------------------- sentiment.sqlite

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS prompts (
  prompt_id INTEGER PRIMARY KEY, version TEXT NOT NULL, sha256 TEXT NOT NULL, model TEXT NOT NULL,
  text TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE (sha256, model)) STRICT;
CREATE TABLE IF NOT EXISTS scores (
  id         TEXT NOT NULL,      -- '<change number>/<comment uuid>'
  prompt_id  INTEGER NOT NULL,   -- 0: TRIVIAL regex, no model
  input_hash INTEGER NOT NULL,
  score      REAL NOT NULL,
  ai         INTEGER NOT NULL,
  why        TEXT,
  PRIMARY KEY (id, prompt_id, input_hash)) STRICT, WITHOUT ROWID;
"""


def open_scores(data_dir=store.DATA_DIR):
    return store.connect(os.path.join(data_dir, SENTIMENT_FILE), SCHEMA_SQL)


def score_week(week, data_dir=store.DATA_DIR, version=None, model="haiku", batch=50, jobs=8, limit=None,
               sandbox="auto"):
    """Score every comment of `week` not yet scored with the current prompt,
    saving each batch as it lands (so a stopped run resumes)."""
    rows = comment_rows(os.path.join(out_dir(data_dir), f"comments-{week}.jsonl"))
    definition = load_prompt(version)
    sha = prompt_sha(definition)
    db = open_scores(data_dir)
    hashes = {r["id"]: input_hash(render(r)) for r in rows}
    with db:
        db.execute("INSERT OR IGNORE INTO prompts(version, sha256, model, text, created_at) VALUES (?,?,?,?,?)",
                   (version or PROMPT_VERSION, sha, model, definition, store.now_iso()))
    pid = db.execute("SELECT prompt_id FROM prompts WHERE sha256=? AND model=?", (sha, model)).fetchone()[0]
    have = {i for (i,) in db.execute("SELECT id FROM scores WHERE prompt_id IN (0, ?)", (pid,))}
    todo = [r for r in rows if r["id"] not in have]
    if limit:
        todo = todo[:limit]
    triv = [r for r in todo if TRIVIAL.match(r["text"])]
    with db:
        db.executemany("INSERT OR REPLACE INTO scores VALUES (?,0,?,0,0,NULL)", [(r["id"], hashes[r["id"]]) for r in triv])
    todo = [r for r in todo if not TRIVIAL.match(r["text"])]
    print(f"{week}: {len(rows)} comments, {len(have)} already scored, {len(triv)} trivial, "
          f"{len(todo)} to score ({-(-len(todo) // batch)} calls, {jobs} at a time)", file=sys.stderr)

    def save(got, cost):
        with db:
            db.executemany("INSERT OR REPLACE INTO scores VALUES (?,?,?,?,?,?)",
                           [(i, pid, hashes[i], s, int(ai), why or None) for i, (s, ai, why) in got.items()])
    box = make_sandbox(sandbox, data_dir) if isinstance(sandbox, str) and todo else sandbox
    try:
        _, st = score_items(todo, definition, model, batch, jobs, save, sandbox=box)
    finally:
        if box is not sandbox:
            box.close()
    return st


def load_scores(week, data_dir=store.DATA_DIR, version=None, model="haiku"):
    """{id: (score, ai, why)} for a week's comments under the given prompt."""
    definition = load_prompt(version)
    db = open_scores(data_dir)
    row = db.execute("SELECT prompt_id FROM prompts WHERE sha256=? AND model=?",
                     (prompt_sha(definition), model)).fetchone()
    pid = row[0] if row else -1
    return {i: (s, bool(ai), why) for i, s, ai, why in
            db.execute("SELECT id, score, ai, why FROM scores WHERE prompt_id IN (0, ?)", (pid,))}


def write_jsonl(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def read_jsonl(path):
    with open(path) as f:
        return [json.loads(l) for l in f if l.strip()]


def is_self_note(r):
    """The CL owner's comment that answers nobody else (a thread starter, or
    a reply in a thread only the owner has written in). Not part of any
    analysis: `collect` skips them, and `comment_rows` drops those in comment
    files collected before 2026-11-10."""
    return r.get("author_role") == "AUTHOR" and _target_kind(r) is None


def comment_rows(path):
    """A comments-*.jsonl file's rows, without the owner's notes to self."""
    return [r for r in read_jsonl(path) if not is_self_note(r)]


def out_dir(data_dir=store.DATA_DIR):
    return os.path.join(data_dir, OUT_DIR)


# ---------------------------------------------------------------- whose comments

# Every public output comes in three versions, by the writer of each comment:
# Chromium committers (the default, which the page shows first), everyone, or
# everyone else. Spam and drive-by comments come from non-committers.
AUTHORS = ("committers", "everyone", "noncommitters")
DEFAULT_AUTHORS = "committers"


def authors_path(path, authors):
    """x.json for the default writers (committers), else x.<authors>.json."""
    if authors == DEFAULT_AUTHORS:
        return path
    base, ext = os.path.splitext(path)
    return f"{base}.{authors}{ext}"


def committer_accounts(data_dir=store.DATA_DIR):
    """{(host, account id)} of committers: accounts Gerrit let vote Code-Review
    when the listings were fetched (derived.sqlite `committers`,
    docs/committers.md). Today's status stands in for the status when a
    comment was written."""
    db = sqlite3.connect(f"file:{os.path.join(data_dir, store.DERIVED_FILE)}?mode=ro", uri=True)
    try:
        if not store.has_table(db, "committers"):
            raise SystemExit("derived.sqlite has no committers table: rerun `python3 -m cosh derive`")
        return {(h, a) for h, a in db.execute("SELECT host, account_id FROM committers WHERE is_committer = 1")}
    finally:
        db.close()


def committer_rows(rows, data_dir=store.DATA_DIR, committers=None):
    """The ids of the rows written by a committer. The writer is the row's
    `author` (rows collected with identities) or is looked up in
    derived.sqlite: the CL owner for the owner's comments, else the
    comment's own account. A writer we can't place isn't a committer."""
    committers = committer_accounts(data_dir) if committers is None else committers
    out, need = set(), []
    for r in rows:
        if r.get("author") is not None:
            if (r["host"], r["author"]) in committers:
                out.add(r["id"])
        else:
            need.append(r)
    if need:
        db = sqlite3.connect(f"file:{os.path.join(data_dir, store.DERIVED_FILE)}?mode=ro", uri=True)
        cls = {(r["host"], r["cl"]) for r in need}
        owners = {(h, n): o for h, n, o in db.execute("SELECT host, change_number, owner_account FROM changes")
                  if (h, n) in cls}
        lo, hi = min(r["written_at"] for r in need), max(r["written_at"] for r in need)
        writers = {(h, n, c): a for h, n, c, a in db.execute(
            "SELECT host, change_number, comment_id, account_id FROM comments WHERE written_at BETWEEN ? AND ?",
            (lo, hi)) if (h, n) in cls}
        db.close()
        for r in need:
            a = owners.get((r["host"], r["cl"])) if r["author_role"] == "AUTHOR" else \
                writers.get((r["host"], r["cl"], r["uuid"]))
            if a is not None and (r["host"], a) in committers:
                out.add(r["id"])
    return out


def by_authors(rows, authors, data_dir=store.DATA_DIR, committers=None):
    """The rows written by `authors` (one of AUTHORS)."""
    if authors == "everyone":
        return list(rows)
    if authors not in AUTHORS:
        raise ValueError(f"authors must be one of {AUTHORS}, not {authors!r}")
    ids = committer_rows(rows, data_dir, committers)
    want = authors == "committers"
    return [r for r in rows if (r["id"] in ids) == want]


# ---------------------------------------------------------------- the public aggregate

GLOWING, ANGRY = 0.4, -0.3   # thresholds for "glowing" / "angry" comments
ROLL = 3                     # months pooled per trend point (centred rolling window)
MIN_MONTH = 0.5              # share of the median month's sampled comments to keep a month (drops partial months)
SUMMARY = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "summaries",
                       "sentiment_monthly.json")


def _wilson(k, n, z=1.96):
    if not n:
        return [0, 0]
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0, c - h), 5), round(c + h, 5)]


def _point(v):
    """Mean (95% CI) and shares glowing, angry and AI friction (Wilson 95%
    CIs) of [(score, ai, weight), ...]. A sampled comment weighs 1/rate, so
    a window that pools sampled and complete months counts each month at its
    true size; the intervals use the effective size (sum w)^2 / sum w^2,
    which is just n when the weights are equal."""
    n = len(v)
    tw = sum(x[2] for x in v)
    n_eff = tw * tw / sum(x[2] * x[2] for x in v)
    mean = sum(x[0] * x[2] for x in v) / tw
    sd = math.sqrt(sum(x[2] * (x[0] - mean) ** 2 for x in v) / tw * n_eff / max(1, n_eff - 1))
    share = lambda f: sum(x[2] for x in v if f(x)) / tw
    g, a, ai = share(lambda x: x[0] >= GLOWING), share(lambda x: x[0] <= ANGRY), share(lambda x: x[1])
    h = 1.96 * sd / math.sqrt(n_eff)
    return dict(n=n, mean=round(mean, 4), lo=round(mean - h, 4), hi=round(mean + h, 4),
                glowing=round(g, 4), glowing_ci=_wilson(g * n_eff, n_eff), angry=round(a, 4),
                angry_ci=_wilson(a * n_eff, n_eff), ai=round(ai, 4), ai_ci=_wilson(ai * n_eff, n_eff))


def full_months(weeks):
    """The calendar months ('2026-10') that lie wholly inside `weeks` (ISO
    weeks, oldest first)."""
    if not weeks:
        return set()
    start, end = week_bounds(weeks[0])[0], week_bounds(weeks[-1])[1]
    out, y, m = set(), int(start[:4]), int(start[5:7])
    while f"{y:04d}-{m:02d}" <= end[:7]:
        nxt = f"{y + m // 12:04d}-{m % 12 + 1:02d}-01 00:00:00"
        if f"{y:04d}-{m:02d}-01 00:00:00" >= start and nxt <= end:
            out.add(f"{y:04d}-{m:02d}")
        y, m = y + m // 12, m % 12 + 1
    return out


def trend(rows, scores, window=ROLL, rate=1.0, full_rows=(), full=frozenset()):
    """The monthly trend: for each whole month, its own figures and those of
    a centred `window` of months (two at the ends), substantive comments
    only. `rows` are a sample at `rate`; the months in `full` use every
    comment (`full_rows`) instead, and are marked `full`. Aggregate only:
    nothing is broken down by person or org."""
    by = defaultdict(list)
    n_trivial = missing = 0
    used = [(r, 1 / rate) for r in rows if r["written_at"][:7] not in full] + \
           [(r, 1.0) for r in full_rows if r["written_at"][:7] in full]
    for r, w in used:
        if r["id"] not in scores:
            missing += 1
            continue
        if TRIVIAL.match(r["text"]):
            n_trivial += 1
            continue
        s = scores[r["id"]]
        by[r["written_at"][:7]].append((s[0], s[1], w))
    sizes = sorted(sum(x[2] for x in v) for v in by.values())
    cut = MIN_MONTH * sizes[len(sizes) // 2] if sizes else 0
    months = [m for m in sorted(by) if sum(x[2] for x in by[m]) >= cut]
    h = window // 2
    out = []
    for i, m in enumerate(months):
        span = months[max(0, i - h):i + h + 1]
        out.append(dict(m=m, full=m in full, month=_point(by[m]), span=[span[0], span[-1]],
                        rolling=dict(_point([x for k in span for x in by[k]]), full=all(k in full for k in span))))
    return dict(window=window, months=out, n=sum(len(by[m]) for m in months), n_trivial=n_trivial,
                missing=missing)


def trend_rows(name, weeks=(), data_dir=store.DATA_DIR):
    """The rows behind the trend: the sample set `name`, and every comment
    of `weeks` (fully scored weeks) for the months they wholly cover."""
    sample = comment_rows(os.path.join(out_dir(data_dir), f"comments-{name}.jsonl"))
    months = full_months(list(weeks))
    rows = [r for w in weeks for r in comment_rows(os.path.join(out_dir(data_dir), f"comments-{w}.jsonl"))
            if r["written_at"][:7] in months]
    return sample, rows, months


def write_summary(name, data_dir=store.DATA_DIR, version=None, out=None, authors=DEFAULT_AUTHORS,
                  weeks=(), loaded=None, scores=None):
    """summaries/sentiment_monthly.json (or its .<authors> version) from a
    scored sample set, with every comment for the months that `weeks` (fully
    scored) wholly cover, counting only comments written by `authors`."""
    sample, rows, months = loaded or trend_rows(name, weeks, data_dir)
    m = re.search(r"(\d+(?:\.\d+)?)pct", name)
    rate = float(m.group(1)) / 100 if m else None
    committers = None if authors == "everyone" else committer_accounts(data_dir)
    t = trend(by_authors(sample, authors, data_dir, committers), scores or load_scores(None, data_dir, version),
              rate=rate or 1.0, full_rows=by_authors(rows, authors, data_dir, committers), full=months)
    doc = dict(generated_at=store.now_iso(), prompt=version or PROMPT_VERSION, model="haiku", sample=name,
               rate=rate, full_weeks=[weeks[0], weeks[-1]] if weeks else None, authors=authors,
               thresholds=dict(glowing=GLOWING, angry=ANGRY), **t)
    out = out or authors_path(SUMMARY, authors)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        json.dump(doc, f, indent=1)
        f.write("\n")
    return out, doc


# ---------------------------------------------------------------- the praise leaderboard

PRAISE_SUMMARY = os.path.join(os.path.dirname(SUMMARY), "sentiment_praise.json")


def is_praise(row, scores):
    """A glowing comment (score >= GLOWING, specific appreciation or
    stronger). The model's score alone decides: a word list missed about 8%
    of glowing comments ("I really like this", "Nifty!", emoji), so it was
    dropped on 2026-11-07."""
    s = scores.get(row["id"])
    return s is not None and s[0] >= GLOWING


NET_SCALE = 5.0      # a net praise total this large gets the full pill colour on the page


def periods(weeks):
    """The page's date choices over `weeks` (ISO weeks, oldest first): "all",
    each calendar year ("2026") and each calendar month ("2026-10"). A week
    belongs to the month and year of its Thursday, as on the page. Each maps to
    its weeks, oldest first."""
    out = {"all": list(weeks)}
    for w in weeks:
        y, n = w.split("-W")
        t = date.fromisocalendar(int(y), int(n), 4)
        out.setdefault(f"{t.year}", []).append(w)
        out.setdefault(f"{t.year}-{t.month:02d}", []).append(w)
    return out


def screen_first(pool, n, text, sandbox, cache, batch=30):
    """The first `n` ids of `pool` (in order) that `screen_identifying` passes.
    Ids not yet in `cache` are screened `batch` at a time, ahead of need;
    cache[id] is True when flagged, so a run can share it across periods and
    groups and never screen a comment twice. Returns (kept, how many of the
    ids looked at were flagged)."""
    kept, flagged = [], 0
    for k, i in enumerate(pool):
        if i not in cache:
            chunk = [x for x in pool[k:] if x not in cache][:batch]
            keys = {f"C{j}": x for j, x in enumerate(chunk)}
            hit = screen_identifying([(key, text(x)) for key, x in keys.items()], sandbox)
            for key, x in keys.items():
                cache[x] = key in hit
        if cache[i]:
            flagged += 1
        else:
            kept.append(i)
            if len(kept) >= n:
                break
    return kept, flagged


def net_praise(weeks, scores, data_dir=store.DATA_DIR, authors=DEFAULT_AUTHORS):
    """Net praise per person, over all `weeks`, each calendar year and each
    calendar month (`periods`): the
    scores of the praise comments they gave (or received), plus the scores of
    the grumpy ones (score <= ANGRY, so these subtract); neutral comments
    count for nothing. Human to human, written by `authors`.

    Ground rule 5 (2026-11-07): grumpiness may lower a net total, but only
    positive totals are published, summed per period, so no figure shows
    anyone's negative tone on its own. Each entry: email, name, score (the
    net total) and praise (how many praise comments)."""
    rows = []
    for w in weeks:
        for r in comment_rows(os.path.join(out_dir(data_dir), f"comments-{w}.jsonl")):
            if r["id"] in scores:
                r["week"] = w
                rows.append(r)
    if rows and "author" not in rows[0]:
        raise SystemExit("these comment files have no identities: collect them with "
                         "`python3 -m cosh.sentiment_people collect`")
    rows = by_authors(rows, authors, data_dir)
    out = {}
    for period, ws in periods(weeks).items():
        ws = set(ws)
        total = {k: defaultdict(float) for k in ("given", "received")}
        count = {k: defaultdict(int) for k in ("given", "received")}
        names = {}
        for r in rows:
            if r["week"] not in ws or _target_kind(r) != "person":
                continue
            writer, recipient = r.get("author_email"), r.get("target_email")
            if not writer or not recipient:
                continue
            sc = scores[r["id"]][0]
            praised = is_praise(r, scores)
            if not praised and sc > ANGRY:
                continue                      # neutral: counts for nothing
            names[writer] = r.get("author_name") or writer
            names[recipient] = r.get("target_name") or recipient
            for k, e in (("given", writer), ("received", recipient)):
                total[k][e] += sc
                count[k][e] += praised
        out[period] = {k: sorted((dict(email=e, name=names[e], score=round(v, 2), praise=count[k][e])
                                  for e, v in total[k].items() if round(v, 2) > 0),
                                 key=lambda x: (-x["score"], x["name"])) for k in total}
    return out


def praise(weeks, data_dir=store.DATA_DIR, version=None, authors=DEFAULT_AUTHORS):
    """Praise given and received per person and week, from human to human,
    counting only praise written by `authors`, plus the net praise boards
    (`net_praise`).

    Ground rule 5 allows naming people for praise, never for negative tone,
    so identities are attached here only to comments already scored glowing:
    collect's `keep` drops every other comment before its row is built."""
    scores = load_scores(None, data_dir, version)
    db = sqlite3.connect(f"file:{os.path.join(data_dir, store.DERIVED_FILE)}?mode=ro", uri=True)
    names = {(h, a): (e, n) for h, a, e, n in db.execute("SELECT host, account_id, email, name FROM accounts")}
    glowing = {i for i, s in scores.items() if s[0] >= GLOWING}
    committers = None if authors == "everyone" else committer_accounts(data_dir)
    rows, people, coverage = defaultdict(lambda: [0, 0]), {}, []
    for w in weeks:
        p = os.path.join(out_dir(data_dir), f"comments-{w}.jsonl")
        if not os.path.exists(p):
            raise SystemExit(f"{w}: collect and score the week first ({p} is missing)")
        unscored = sum(1 for r in comment_rows(p) if r["id"] not in scores and not TRIVIAL.match(r["text"]))
        coverage.append(dict(week=w, unscored=unscored))
        got = []
        collect(w, data_dir, keep=glowing.__contains__,
                annotate=lambda row, ids: got.append((row, ids)) if is_praise(row, scores) else None)
        for row, ids in got:
            if row["target_kind"] != "person":
                continue                     # praise for an AI, or an owner's own note
            if committers is not None and ((ids["host"], ids["author"]) in committers) != (authors == "committers"):
                continue
            for aid, k in ((ids["author"], 0), (ids["target"], 1)):
                email, name = names.get((ids["host"], aid), (None, None))
                if not email:
                    continue
                people[email] = name or email
                rows[(w, email)][k] += 1
    return dict(generated_at=store.now_iso(), prompt=version or PROMPT_VERSION, model="haiku",
                weeks=[weeks[0], weeks[-1]], authors=authors, threshold=GLOWING, angry=ANGRY, net_scale=NET_SCALE,
                coverage=coverage, people=people,
                weekly=[dict(week=w, email=e, given=g, received=r) for (w, e), (g, r) in sorted(rows.items())],
                net=net_praise(weeks, scores, data_dir, authors))


# ---------------------------------------------------------------- sample comments

SAMPLES_SUMMARY = os.path.join(os.path.dirname(SUMMARY), "sentiment_samples.json")
GERRIT = "https://chromium-review.googlesource.com"
PRAISE_SAMPLE, GRUMPY_SAMPLE = 0.5, -0.6   # score bounds for sample comments (+0.8 is rare: 3 in 8 weeks)
SAMPLE_CHARS = 400                          # longer comments aren't sampled
_LINKY = re.compile(r"https?://|www\.|@\w|\b\w+@\w")


def comment_url(project, number, uuid):
    """Gerrit link to a praise comment. Always https on GERRIT; the parts are
    percent-encoded, since the uuid comes from NoteDb (SECURITY.md)."""
    from urllib.parse import quote
    return f"{GERRIT}/c/{quote(project, safe='/')}/+/{int(number)}/comment/{quote(uuid, safe='')}/"


SCREEN_SYSTEM = "You check code-review comments for anything that identifies a person."
SCREEN_PROMPT = """Each item below is a code-review comment. List the ids of the items that
identify a person: a name or first name, a username, handle or email, or a
detail that points to who wrote or received the comment (a team, a company, a
named product owned by one person, a CL or bug number). Also list items that
accuse anyone of misconduct, dishonesty, fraud or bad faith, or that point at
a specific ticket, bug or report. Code identifiers (function, class, file and
flag names) don't count. When unsure, list it.
Return JSON only: {"flagged": ["C0", ...]}."""
SCREEN_SCHEMA = {"type": "object", "properties": {"flagged": {"type": "array", "items": {"type": "string"}}},
                 "required": ["flagged"]}


def screen_identifying(items, sandbox, model="haiku"):
    """The keys of [(key, text)] that identify a person, from one sandboxed,
    tool-less call (SECURITY.md). Only keys that were sent count; a reply that
    doesn't parse flags everything."""
    sent = {k for k, _ in items}
    prompt = SCREEN_PROMPT + "\n\n" + "\n\n".join(f"### {k}\n{t}" for k, t in items)
    p = sandbox.run(claude_args(model, SCREEN_SCHEMA, SCREEN_SYSTEM), prompt)
    try:
        d = json.loads(p.stdout)
        out = d.get("structured_output") or json.loads(re.search(r"\{.*\}", d.get("result") or "", re.S).group(0))
        return {k for k in out.get("flagged", []) if k in sent}
    except (ValueError, AttributeError, TypeError):
        return set(sent)


def _target_kind(r):
    """Rows written before target_kind existed (2026-11-05) have target_is_ai."""
    if "target_kind" in r:
        return r["target_kind"]
    return "ai" if r.get("target_is_ai") else "person" if r.get("target") else None


def _draw(ids, seed):
    """Deterministic shuffle of comment ids."""
    return sorted(ids, key=lambda i: hashlib.sha256(f"{seed}/{i}".encode()).hexdigest())


def samples(weeks, data_dir=store.DATA_DIR, version=None, n=10, seed="2026-11", sandbox="auto",
            authors=DEFAULT_AUTHORS, screened=None):
    """The most extreme praise (highest scores) and grumpy comments (lowest
    scores, not flagged as AI friction) written by `authors` in fully scored
    weeks, for each of the page's periods (`periods`). Ties are broken by a
    deterministic shuffle (`seed`), so reruns pick the same comments.
    `screened` is a `screen_first` cache to share between calls.

    Ground rule 5: praise comes with names and a Gerrit link; grumpy comments
    come with their text, score and month only, and only when a sandboxed
    screen finds nothing in them that identifies anyone."""
    scores = load_scores(None, data_dir, version)
    rows = {}
    for w in weeks:
        for r in comment_rows(os.path.join(out_dir(data_dir), f"comments-{w}.jsonl")):
            if r["id"] in scores and len(r["text"]) <= SAMPLE_CHARS:
                r["week"] = w
                rows[r["id"]] = r
    rows = {r["id"]: r for r in by_authors(rows.values(), authors, data_dir)}
    praise_all = sorted(_draw([i for i, r in rows.items() if scores[i][0] >= PRAISE_SAMPLE and is_praise(r, scores)
                               and _target_kind(r) == "person"], seed), key=lambda i: -scores[i][0])
    # AI-friction comments have their own section (cosh.sentiment_recent), so
    # the grumpy samples are the rest.
    grumpy_all = sorted(_draw([i for i, r in rows.items() if scores[i][0] <= GRUMPY_SAMPLE and not scores[i][1]
                               and not _LINKY.search(r["text"])], seed), key=lambda i: scores[i][0])
    cache = {} if screened is None else screened
    box = make_sandbox(sandbox, data_dir) if isinstance(sandbox, str) else sandbox
    picked = {}
    try:
        for key, ws in periods(weeks).items():
            ws = set(ws)
            grumpy, _ = screen_first([i for i in grumpy_all if rows[i]["week"] in ws], n,
                                     lambda i: rows[i]["text"], box, cache, 3 * n)
            picked[key] = ([i for i in praise_all if rows[i]["week"] in ws][:n], grumpy)
    finally:
        if box is not sandbox:
            box.close()

    # Names: from the week files' identities (`cosh.sentiment_people collect`),
    # else by collecting the praise comments' weeks again with only them kept.
    want = {i for p, _ in picked.values() for i in p}
    who = {i: rows[i] for i in want if rows[i].get("author_email")}
    if len(who) < len(want):
        db = sqlite3.connect(f"file:{os.path.join(data_dir, store.DERIVED_FILE)}?mode=ro", uri=True)
        names = {(h, a): (e, nm) for h, a, e, nm in db.execute("SELECT host, account_id, email, name FROM accounts")}
        ids = {}
        for w in sorted({rows[i]["week"] for i in want - set(who)}):
            collect(w, data_dir, keep=(want - set(who)).__contains__,
                    annotate=lambda row, x: ids.__setitem__(row["id"], x))
        for i, x in ids.items():
            a = names.get((x["host"], x["author"]), (None, None))
            t = names.get((x["host"], x["target"]), (None, None))
            who[i] = dict(author_email=a[0], author_name=a[1], target_email=t[0], target_name=t[1])

    def praise_item(i):
        r, x = rows[i], who[i]
        return dict(text=r["text"], score=scores[i][0], date=r["written_at"][:10],
                    writer=x.get("author_name") or x.get("author_email"),
                    recipient=x.get("target_name") or x.get("target_email"),
                    url=comment_url(r["project"], r["cl"], r["uuid"]))
    out = {key: dict(praise=[praise_item(i) for i in p if i in who],
                     grumpy=[dict(text=rows[i]["text"], score=scores[i][0], month=rows[i]["written_at"][:7]) for i in g])
           for key, (p, g) in picked.items()}
    return dict(generated_at=store.now_iso(), prompt=version or PROMPT_VERSION, weeks=[weeks[0], weeks[-1]],
                authors=authors, praise_min=PRAISE_SAMPLE, grumpy_max=GRUMPY_SAMPLE, periods=out)


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="python3 -m cosh.sentiment")
    ap.add_argument("step", choices=["collect", "score", "summary", "praise", "samples"])
    ap.add_argument("--week", default="2026-W44", help="a week or a range, e.g. 2026-W37:2026-W44")
    ap.add_argument("--sample", type=float, default=None,
                    help="collect: a deterministic sample at this rate over --week's range, written as "
                         "comments-<name>.jsonl; score/summary: use with --name")
    ap.add_argument("--name", default=None, help="name of a sample set, e.g. sample-5pct")
    ap.add_argument("--full-weeks", default=None,
                    help="summary: fully scored weeks, e.g. 2025-W45:2026-W44; the months they wholly cover "
                         "use every comment instead of the sample")
    ap.add_argument("--prompt", default=None, help=f"prompt version (default {PROMPT_VERSION})")
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--sandbox", choices=["auto", "bwrap", "none"], default="auto",
                    help="jail for claude -p (SECURITY.md): auto = bubblewrap if it works here")
    ap.add_argument("--batch", type=int, default=50)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--authors", choices=AUTHORS + ("all",), default="all",
                    help="summary, praise, samples: whose comments count; 'all' writes one file for each")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    if a.out and a.authors == "all":
        ap.error("--out needs one --authors group")
    groups = AUTHORS if a.authors == "all" else (a.authors,)
    t0 = time.time()
    weeks = weeks_in(a.week)
    if a.step == "collect":
        if a.sample:
            start, end = week_bounds(weeks[0])[0], week_bounds(weeks[-1])[1]
            rows = collect(None, start=start, end=end, keep=lambda i: in_sample(i, a.sample))
            sets = [(a.name or f"sample-{a.sample:g}", rows)]
        else:
            sets = [(w, collect(w)) for w in weeks]
        for name, rows in sets:
            p = os.path.join(out_dir(), f"comments-{name}.jsonl")
            write_jsonl(p, rows)
            print(f"{len(rows)} comments -> {p} ({time.time() - t0:.0f}s)", file=sys.stderr)
    elif a.step == "score":
        for name in ([a.name] if a.name else weeks):
            st = score_week(name, version=a.prompt, jobs=a.jobs, batch=a.batch, limit=a.limit, sandbox=a.sandbox)
            print(f"{name}: scored {st['n']} in {st['calls']} calls, {st['tokens']} tokens, ${st['usd']:.2f} "
                  f"API-equivalent, {time.time() - t0:.0f}s", file=sys.stderr)
    elif a.step == "samples":
        screened = {}
        for g in groups:
            doc = samples(weeks, version=a.prompt, sandbox=a.sandbox, authors=g, screened=screened)
            out = a.out or authors_path(SAMPLES_SUMMARY, g)
            with open(out, "w") as f:
                json.dump(doc, f, indent=1, ensure_ascii=False)
                f.write("\n")
            print(f"{g}: {len(doc['periods'])} periods, {len(screened)} comments screened so far -> {out}",
                  file=sys.stderr)
    elif a.step == "praise":
        for g in groups:
            doc = praise(weeks, version=a.prompt, authors=g)
            out = a.out or authors_path(PRAISE_SUMMARY, g)
            with open(out, "w") as f:
                json.dump(doc, f, indent=1, ensure_ascii=False)
                f.write("\n")
            gaps = [c for c in doc["coverage"] if c["unscored"]]
            print(f"{g}: {len(doc['people'])} people, {sum(r['given'] for r in doc['weekly'])} praise comments "
                  f"-> {out}" + (f"; NOT fully scored: {gaps}" if gaps else ""), file=sys.stderr)
    else:
        if not a.name:
            ap.error("summary needs --name (a scored sample set)")
        full = weeks_in(a.full_weeks) if a.full_weeks else []
        loaded, scores = trend_rows(a.name, full), load_scores(None, version=a.prompt)
        for g in groups:
            p, doc = write_summary(a.name, version=a.prompt, out=a.out, authors=g, weeks=full, loaded=loaded,
                                   scores=scores)
            print(f"{g}: {len(doc['months'])} months, {doc['n']} substantive comments, {doc['missing']} unscored "
                  f"-> {p}", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1:])
