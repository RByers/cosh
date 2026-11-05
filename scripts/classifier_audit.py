"""Audit of the production addressed-comment classifier against Opus.

docs/comment-classifier.md, "Production audit". Three steps:

  sample  a seeded simple random sample of production-decided threads: in
          scope, reviewer-started, owner replied, root comment in the given
          weeks, decided by the regex or by a current model label (pending
          threads are skipped). Each is rendered exactly as `cosh classify`
          renders it (cosh/classify.py, render), so the judge sees what Haiku
          saw. Writes sample.jsonl.
  judge   Opus labels every sampled thread via headless `claude -p`, blind to
          the production label, with a short reason and a confidence.
          Writes judge.jsonl (resumable: ids already judged are skipped).
  score   precision and recall of production against the gold labels: the
          Opus label, overridden by adjudicated.json ({id: {"done": bool,
          "ambiguous": bool, "note": str}}) where a disagreement or
          low-confidence label was reviewed. Ambiguous threads are reported
          both ways.

The sample holds Gerrit comment text (public data); keep it in a scratch
directory, not in git.

  COSH_DATA_DIR=<main>/data/private python3 scripts/classifier_audit.py sample $T --n 800 \
      --weeks 2026-W33:2026-W44
  TMPDIR=$T python3 scripts/classifier_audit.py judge $T
  python3 scripts/classifier_audit.py disagreements $T     # what to adjudicate
  python3 scripts/classifier_audit.py score $T
"""

import argparse
import json
import math
import os
import random
import sqlite3
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from cosh import classify, store  # noqa: E402
from cosh.paths import load_scope, place  # noqa: E402
from cosh.summarize import SCOPE_JOINS, SCOPE_WHERE, load_labels, reviewer_anchors  # noqa: E402

JUDGE_SCHEMA = {"type": "object", "properties": {"labels": {"type": "array", "items": {
    "type": "object", "properties": {
        "id": {"type": "string"}, "done": {"type": "boolean"},
        "confident": {"type": "boolean"}, "reason": {"type": "string"}},
    "required": ["id", "done", "confident", "reason"]}}}, "required": ["labels"]}

JUDGE_INSTRUCTIONS = """\
You are auditing labels, so take care with every item: read each thread to the
end, since later replies can settle it either way. For each item give done
(true/false), confident (false if a careful reader could reasonably label it
either way, or the text doesn't say enough), and a reason of at most 20 words
quoting the decisive words. Return JSON only:
{"labels": [{"id": "A0", "done": true, "confident": true, "reason": "..."}, ...]}
with one entry per item."""


def weeks_between(spec):
    a, b = spec.split(":")
    ya, wa = map(int, a.split("-W"))
    yb, wb = map(int, b.split("-W"))
    import datetime
    d = datetime.date.fromisocalendar(ya, wa, 1)
    end = datetime.date.fromisocalendar(yb, wb, 1)
    out = []
    while d <= end:
        y, w, _ = d.isocalendar()
        out.append(f"{y}-W{w:02d}")
        d += datetime.timedelta(days=7)
    return out


def population(db, weeks):
    """[(week, host, cl, root_uuid, decided_by, prod_done)] for every
    production-decided, in-scope thread rooted in `weeks` (the same scope as
    summarize.thread_breakdown)."""
    scope = load_scope()
    own = reviewer_anchors(db)
    inline_authors = {(host, aid) for host, _, aid in own}
    weeks = set(weeks)
    cache = {}
    out = []
    for week, host, cl, aid, path, root, no_reply, regex, label in db.execute(f"""
            SELECT x.iso_week, x.host, x.change_number, x.account_id, x.path, t.root_uuid,
                   t.last_owner_reply_at IS NULL, t.regex_addressed, l.addressed
            FROM threads t
            CROSS JOIN comments x ON x.host = t.host AND x.change_number = t.change_number
                 AND x.comment_id = t.root_uuid
            {SCOPE_JOINS}
            LEFT JOIN temp.lab l ON l.change_number = t.change_number AND l.root_uuid = t.root_uuid
                 AND l.input_hash = t.input_hash
            {SCOPE_WHERE}"""):
        if week not in weeks or no_reply or (host, aid) not in inline_authors:
            continue
        key = (path, own.get((host, cl, aid)))
        if key not in cache:
            cache[key] = scope.includes(place(*key))
        if not cache[key]:
            continue
        if regex:
            out.append((week, host, cl, root, "regex", True))
        elif label is not None:
            out.append((week, host, cl, root, "model", bool(label)))
    out.sort()
    return out


def cmd_sample(a):
    data_dir = os.environ.get("COSH_DATA_DIR") or store.DATA_DIR
    db = sqlite3.connect(f"file:{os.path.join(data_dir, store.DERIVED_FILE)}?mode=ro", uri=True)
    model = load_labels(db, data_dir)
    pop = population(db, weeks_between(a.weeks))
    by = Counter((d, p) for *_, d, p in pop)
    print(f"population {len(pop)} threads (classifier {model}): " +
          ", ".join(f"{d}/{'done' if p else 'not'} {n}" for (d, p), n in sorted(by.items())), file=sys.stderr)
    pick = random.Random(a.seed).sample(pop, a.n)
    raw = store.open_raw_ro(data_dir)
    from cosh.derive import load_comments, prefetch_notedb
    repos = {}
    info = {}
    for _, host, cl, *_ in pick:
        info[(host, cl)] = db.execute("SELECT owner_account, project FROM changes WHERE host=? AND change_number=?",
                                      (host, cl)).fetchone()
    notes = prefetch_notedb(repos, sorted({(h, info[(h, n)][1], n) for _, h, n, *_ in pick}), "auto")
    os.makedirs(a.dir, exist_ok=True)
    stale = 0
    with open(os.path.join(a.dir, "sample.jsonl"), "w") as fh:
        for i, (week, host, cl, root, by_, prod) in enumerate(pick):
            owner, project = info[(host, cl)]
            comments, _ = load_comments(raw, repos, host, project, cl, "auto", notes)
            t = {x["root_id"]: x for x in classify.build_threads(comments, owner)}[root]
            text = classify.render(t, owner)
            h = db.execute("SELECT input_hash FROM threads WHERE host=? AND change_number=? AND root_uuid=?",
                           (host, cl, root)).fetchone()[0]
            stale += classify.input_hash(text) != h
            fh.write(json.dumps(dict(id=f"A{i:03d}", week=week, cl=cl, root=root, decided_by=by_,
                                     prod=prod, n_comments=len(t["items"]), text=text)) + "\n")
    print(f"wrote {a.n} threads to {a.dir}/sample.jsonl ({stale} rendered differently from derive)",
          file=sys.stderr)
    json.dump(dict(population=len(pop), strata={f"{d}/{p}": n for (d, p), n in by.items()},
                   weeks=a.weeks, seed=a.seed, n=a.n, classifier=model),
              open(os.path.join(a.dir, "population.json"), "w"), indent=1)


def load_jsonl(path):
    if not os.path.exists(path):
        return []
    return [json.loads(line) for line in open(path) if line.strip()]


def judge_call(model, items, cwd):
    import re
    import subprocess
    text = "\n\n".join(f"### {i}\n{t}" for i, t in items)
    prompt = classify.DEFINITION + "\n\n" + JUDGE_INSTRUCTIONS + "\n\n" + text
    cmd = ["claude", "-p", "--model", model, "--output-format", "json", "--tools", "",
           "--system-prompt", "You are a careful expert reviewer of code-review threads.",
           "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--disable-slash-commands",
           "--exclude-dynamic-system-prompt-sections", "--no-session-persistence",
           "--json-schema", json.dumps(JUDGE_SCHEMA)]
    p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=cwd)
    d = json.loads(p.stdout)
    if d.get("is_error"):
        raise RuntimeError(str(d.get("result"))[:500])
    out = d.get("structured_output") or {}
    if not out:
        m = re.search(r"\{.*\}", d.get("result") or "", re.S)
        out = json.loads(m.group(0)) if m else {}
    return out.get("labels", []), d.get("total_cost_usd") or 0, sorted(d.get("modelUsage", {}))


def cmd_judge(a):
    sample = load_jsonl(os.path.join(a.dir, "sample.jsonl"))
    path = os.path.join(a.dir, "judge.jsonl")
    have = {r["id"] for r in load_jsonl(path)}
    todo = [s for s in sample if s["id"] not in have]
    batches = [todo[i:i + a.batch] for i in range(0, len(todo), a.batch)]
    print(f"{len(todo)} threads to judge in {len(batches)} calls", file=sys.stderr)
    cwd = os.environ.get("TMPDIR") or "/tmp"
    usd = 0.0
    with ThreadPoolExecutor(max_workers=a.jobs) as pool, open(path, "a") as fh:
        futs = [pool.submit(judge_call, a.model, [(s["id"], s["text"]) for s in b], cwd) for b in batches]
        for b, f in zip(batches, futs):
            labels, cost, models = f.result()
            usd += cost
            ids = {s["id"] for s in b}
            for x in labels:
                if x.get("id") in ids:
                    fh.write(json.dumps(dict(x, model=models[0] if models else a.model)) + "\n")
                    ids.discard(x["id"])
            fh.flush()
            print(f"  batch of {len(b)}: {len(b) - len(ids)} labelled, ${cost:.2f}", file=sys.stderr)
    print(f"done, ${usd:.2f} API-equivalent", file=sys.stderr)


def gold(a):
    sample = {s["id"]: s for s in load_jsonl(os.path.join(a.dir, "sample.jsonl"))}
    judge = {}
    for r in load_jsonl(os.path.join(a.dir, "judge.jsonl")):
        judge[r["id"]] = r
    adj_path = os.path.join(a.dir, "adjudicated.json")
    adj = json.load(open(adj_path)) if os.path.exists(adj_path) else {}
    return sample, judge, adj


def cmd_disagreements(a):
    sample, judge, adj = gold(a)
    if a.spot:      # a random sample of confident agreements, to bound errors shared by both models
        agree = [i for i, s in sample.items() if i in judge and judge[i]["done"] == s["prod"]
                 and judge[i]["confident"]]
        keep = set(random.Random(a.seed).sample(agree, a.spot))
        sample = {i: s for i, s in sample.items() if i in keep}
        a.only = "all"
    for i, s in sample.items():
        j = judge.get(i)
        if j is None:
            print(f"{i}: not judged")
            continue
        disagree = j["done"] != s["prod"]
        if a.only == "disagree" and not disagree or a.only == "unsure" and (disagree or j["confident"]):
            continue
        if not disagree and j["confident"] and a.only != "all":
            continue
        mark = "ADJ " + json.dumps(adj[i]) if i in adj else ""
        print(f"==== {i} prod={'done' if s['prod'] else 'not'} ({s['decided_by']}) "
              f"opus={'done' if j['done'] else 'not'}{'' if j['confident'] else ' (unsure)'} {mark}\n"
              f"opus: {j['reason']}\nhttps://chromium-review.googlesource.com/c/{s['cl']}\n{s['text']}\n")


def wilson(k, n, z=1.96):
    if n == 0:
        return (float("nan"),) * 3
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return p, c - h, c + h


def metrics(rows):
    """rows: [(prod, gold)] -> dict of counts and rates."""
    tp = sum(p and g for p, g in rows)
    fp = sum(p and not g for p, g in rows)
    fn = sum(g and not p for p, g in rows)
    tn = sum(not p and not g for p, g in rows)
    return dict(n=len(rows), tp=tp, fp=fp, fn=fn, tn=tn, precision=wilson(tp, tp + fp),
                recall=wilson(tp, tp + fn), accuracy=wilson(tp + tn, len(rows)))


def fmt(m):
    def r(x):
        return f"{x[0]:.3f} [{x[1]:.3f}, {x[2]:.3f}]"
    return (f"n={m['n']} tp={m['tp']} fp={m['fp']} fn={m['fn']} tn={m['tn']}  precision {r(m['precision'])}  "
            f"recall {r(m['recall'])}  accuracy {r(m['accuracy'])}")


def cmd_score(a):
    sample, judge, adj = gold(a)
    policy = {k: dict(done=True, lean=None).get(v, False) for k, v in (x.split("=") for x in a.as_ or [])}
    unjudged = [i for i in sample if i not in judge]
    if unjudged:
        print(f"warning: {len(unjudged)} threads not judged, left out", file=sys.stderr)
    rows, out = [], []
    for i, s in sample.items():
        if i not in judge:
            continue
        r = adj.get(i, {})
        g = r.get("done", judge[i]["done"])
        amb = r.get("ambiguous", False)
        if amb and r.get("cls") in policy:     # a decided policy for this class of ambiguity
            g, amb = (r["done"] if policy[r["cls"]] is None else policy[r["cls"]]), False
        rows.append((s, g, amb))
        if a.write:
            out.append(dict(id=i, week=s["week"], cl=s["cl"], root=s["root"], decided_by=s["decided_by"],
                            prod=s["prod"], opus=judge[i]["done"], opus_confident=judge[i]["confident"],
                            opus_reason=judge[i]["reason"], gold=None if amb else g, ambiguous=amb,
                            reviewed=i in adj, cls=r.get("cls"), note=r.get("note")))
    pending_review = [i for i, s in sample.items() if i in judge and i not in adj and
                      (judge[i]["done"] != s["prod"] or not judge[i]["confident"])]
    print(f"{len(adj)} adjudicated, {len(pending_review)} disagreements or unsure labels not yet adjudicated")
    print(f"ambiguous: {sum(amb for *_, amb in rows)}")
    for name, sel in [("pipeline (regex, then Haiku)", lambda s: True),
                      ("Haiku only (threads the regex left)", lambda s: s["decided_by"] == "model"),
                      ("regex only (threads it settled)", lambda s: s["decided_by"] == "regex")]:
        sub = [(s, g, amb) for s, g, amb in rows if sel(s)]
        print(f"\n{name}")
        print("  gold as labelled:      " + fmt(metrics([(s["prod"], g) for s, g, _ in sub])))
        print("  ambiguous excluded:    " + fmt(metrics([(s["prod"], g) for s, g, amb in sub if not amb])))
        print("  ambiguous as agreeing: " + fmt(metrics([(s["prod"], s["prod"] if amb else g) for s, g, amb in sub])))
    if a.write:     # per-thread record, no comment text (it can be re-rendered from cl + root)
        with open(a.write, "w") as fh:
            fh.write(json.dumps(dict(population=json.load(open(os.path.join(a.dir, "population.json"))),
                                     policy=a.as_ or [])) + "\n")
            for r in out:
                fh.write(json.dumps(r) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("sample")
    p.add_argument("dir")
    p.add_argument("--n", type=int, default=800)
    p.add_argument("--weeks", default="2026-W33:2026-W44")
    p.add_argument("--seed", type=int, default=20261104)
    p = sp.add_parser("judge")
    p.add_argument("dir")
    p.add_argument("--model", default="opus")
    p.add_argument("--batch", type=int, default=25)
    p.add_argument("--jobs", type=int, default=4)
    p = sp.add_parser("disagreements")
    p.add_argument("dir")
    p.add_argument("--only", choices=["disagree", "unsure", "all"],
                   help="only disagreements, only unsure agreements, or every thread")
    p.add_argument("--spot", type=int, help="instead, N random confident agreements")
    p.add_argument("--seed", type=int, default=7)
    p = sp.add_parser("score")
    p.add_argument("dir")
    p.add_argument("--as", dest="as_", action="append", metavar="CLASS=done|not|lean",
                   help="decide an adjudicated ambiguity class (promise, resolved, one-off) one way, "
                        "or by the adjudicator's lean per thread")
    p.add_argument("--write", metavar="PATH", help="also write the per-thread record (JSON lines, no text)")
    a = ap.parse_args()
    dict(sample=cmd_sample, judge=cmd_judge, disagreements=cmd_disagreements, score=cmd_score)[a.cmd](a)


if __name__ == "__main__":
    main()
