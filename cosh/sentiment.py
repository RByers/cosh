"""Review-comment sentiment, in aggregate (docs/sentiment.md).

Every human comment written in a week, or a deterministic sample of them,
gets a score from -1 (very angry or upset) through 0 (neutral) to +1 (very
positive or grateful), plus a flag for anger or frustration about AI in code
review. Scores come from Claude Haiku via headless `claude -p` (prompt tuned
against a hand-labelled sample, docs/sentiment.md) and are stored in
data/private/sentiment.sqlite, which, like labels.sqlite, costs Max usage to
remake.

Sentiment is published only in aggregate: nothing here ranks, lists or
groups people or organizations by tone, and comment rows carry no
identities (docs/plan.md, ground rule 5). `summary` writes the public
monthly trend.

Each comment has a role (the CL owner's or a reviewer's) and a target kind:
  - "person": a reply to a human, or a reviewer's thread-starting comment
    (aimed at the CL owner);
  - "ai": a reply to an AI reviewer or to agent-written text, or a comment
    addressed "to <agent>: ...";
  - None: the owner's own thread-starting comments.
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


def claude_args(model):
    """claude -p flags: no tools, MCP servers or slash commands, no transcript,
    one-line system prompt, reply constrained to SCHEMA (SECURITY.md, layer 1)."""
    return ["-p", "--model", model, "--output-format", "json", "--tools", "",
            "--system-prompt", SYSTEM_PROMPT,
            "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--disable-slash-commands",
            "--exclude-dynamic-system-prompt-sections", "--no-session-persistence",
            "--json-schema", json.dumps(SCHEMA)]


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
    p = sandbox.run(claude_args(model), prompt)
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
    rows = read_jsonl(os.path.join(out_dir(data_dir), f"comments-{week}.jsonl"))
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


def out_dir(data_dir=store.DATA_DIR):
    return os.path.join(data_dir, OUT_DIR)


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
    CIs) of [(score, ai), ...]."""
    n = len(v)
    s = [x[0] for x in v]
    mean = sum(s) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in s) / max(1, n - 1))
    g, a, ai = sum(x >= GLOWING for x in s), sum(x <= ANGRY for x in s), sum(1 for x in v if x[1])
    h = 1.96 * sd / math.sqrt(n)
    return dict(n=n, mean=round(mean, 4), lo=round(mean - h, 4), hi=round(mean + h, 4),
                glowing=round(g / n, 4), glowing_ci=_wilson(g, n), angry=round(a / n, 4), angry_ci=_wilson(a, n),
                ai=round(ai / n, 4), ai_ci=_wilson(ai, n))


def trend(rows, scores, window=ROLL):
    """The monthly trend of a sample: for each whole month, its own figures
    and those of a centred `window` of months (two at the ends), substantive
    comments only. Aggregate only: nothing is broken down by person or org."""
    by = defaultdict(list)
    n_trivial = 0
    for r in rows:
        if r["id"] not in scores:
            continue
        if TRIVIAL.match(r["text"]):
            n_trivial += 1
            continue
        s = scores[r["id"]]
        by[r["written_at"][:7]].append((s[0], s[1]))
    sizes = sorted(len(v) for v in by.values())
    cut = MIN_MONTH * sizes[len(sizes) // 2] if sizes else 0
    months = [m for m in sorted(by) if len(by[m]) >= cut]
    h = window // 2
    out = []
    for i, m in enumerate(months):
        span = months[max(0, i - h):i + h + 1]
        out.append(dict(m=m, month=_point(by[m]), span=[span[0], span[-1]],
                        rolling=_point([x for k in span for x in by[k]])))
    return dict(window=window, months=out, n=sum(len(by[m]) for m in months), n_trivial=n_trivial,
                missing=sum(1 for r in rows if r["id"] not in scores))


def write_summary(name, data_dir=store.DATA_DIR, version=None, out=None):
    """summaries/sentiment_monthly.json from a scored sample set."""
    rows = read_jsonl(os.path.join(out_dir(data_dir), f"comments-{name}.jsonl"))
    t = trend(rows, load_scores(None, data_dir, version))
    m = re.search(r"(\d+(?:\.\d+)?)pct", name)
    doc = dict(generated_at=store.now_iso(), prompt=version or PROMPT_VERSION, model="haiku", sample=name,
               rate=float(m.group(1)) / 100 if m else None, thresholds=dict(glowing=GLOWING, angry=ANGRY), **t)
    out = out or SUMMARY
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        json.dump(doc, f, indent=1)
        f.write("\n")
    return out, doc


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="python3 -m cosh.sentiment")
    ap.add_argument("step", choices=["collect", "score", "summary"])
    ap.add_argument("--week", default="2026-W44", help="a week or a range, e.g. 2026-W37:2026-W44")
    ap.add_argument("--sample", type=float, default=None,
                    help="collect: a deterministic sample at this rate over --week's range, written as "
                         "comments-<name>.jsonl; score/summary: use with --name")
    ap.add_argument("--name", default=None, help="name of a sample set, e.g. sample-5pct")
    ap.add_argument("--prompt", default=None, help=f"prompt version (default {PROMPT_VERSION})")
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--sandbox", choices=["auto", "bwrap", "none"], default="auto",
                    help="jail for claude -p (SECURITY.md): auto = bubblewrap if it works here")
    ap.add_argument("--batch", type=int, default=50)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
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
    else:
        if not a.name:
            ap.error("summary needs --name (a scored sample set)")
        p, doc = write_summary(a.name, version=a.prompt, out=a.out)
        print(f"{len(doc['months'])} months, {doc['n']} substantive comments, {doc['missing']} unscored -> {p}",
              file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1:])
