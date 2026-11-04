"""Was a review thread addressed (did the feedback lead to a change)?
Builds a labelled dataset and compares classifiers (docs/comment-classifier.md).

  python3 scripts/comment_classifier.py dataset threads.jsonl DIR [--n 400]
  python3 scripts/comment_classifier.py predict DIR {regex,rules,nb}
  python3 scripts/comment_classifier.py llm DIR MODEL [--batch 50] [--effort low]
  python3 scripts/comment_classifier.py score DIR [--gold gold.jsonl]

DIR holds dataset.jsonl, batch_NN.txt (for labelling), labels_*.jsonl and
pred_<method>.jsonl ({"id", "done": bool}) plus cost_<method>.json.
`threads.jsonl` comes from scripts/review_impact.py. Comment text is public
Gerrit data, but keep DIR outside the repo: it is large and rebuildable.
"""

import argparse
import collections
import glob
import json
import math
import os
import random
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from review_impact_stats import DONE  # noqa: E402

ROLE = {"R": "REVIEWER", "O": "OWNER", "X": "OTHER"}

DEFINITION = """\
Each item is a Gerrit code-review thread on a Chromium CL. REVIEWER wrote the
first comment; OWNER is the CL's author (or a co-author who uploaded patch
sets); OTHER is anyone else. Decide whether the REVIEWER's feedback led the
owner to change the CL itself, in this CL:

done = the owner changed something in response: code, tests, code comments,
  build files or the commit message, including partly adopting the
  suggestion, or making a different/better change than the one suggested
  because of it. "Done", "Fixed", "Updated", "Removed", "Fix applied." and
  free-text descriptions of a change all count. Adding a TODO or a comment
  in the code in response counts.
not = no change in this CL: the owner answered a question, explained, pushed
  back, the reviewer withdrew or accepted the explanation, the comment was an
  approval/thanks/FYI, or the work was deferred to a separate or follow-up CL
  or bug. A bare "Acknowledged"/"Ack" with no sign of a change is "not".

Judge only from the text. If unsure, pick the more likely label and mark
conf "low"."""


def render(item):
    lines = [f"### {item['id']}", f"REVIEWER: {item['root'][:1500]}"]
    for role, msg in item["thread"]:
        lines.append(f"{ROLE[role]}: {msg[:800]}")
    return "\n".join(lines)


def load(path):
    return [json.loads(line) for line in open(path)]


def write_jsonl(path, rows):
    with open(path, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


# ---------------------------------------------------------------- dataset

def cmd_dataset(a):
    rs = [r for r in load(a.threads) if any(role == "O" for role, _ in r["thread"])]
    random.seed(a.seed)
    sample = random.sample(rs, a.n)
    items = []
    for i, r in enumerate(sample):
        items.append(dict(id=f"T{i:03d}", cl=r["cl"], org=r["org"], root=r["root_msg"],
                          root_unresolved=r["root_unresolved"], file=r["file"],
                          thread=[(role, m) for role, m in r["thread"]],
                          reply_upload_gap=r["reply_upload_gap"], final_unresolved=r["final_unresolved"]))
    os.makedirs(a.dir, exist_ok=True)
    write_jsonl(os.path.join(a.dir, "dataset.jsonl"), items)
    for b in range(0, len(items), a.batch):
        with open(os.path.join(a.dir, f"batch_{b // a.batch:02d}.txt"), "w") as fh:
            fh.write("\n\n".join(render(x) for x in items[b:b + a.batch]) + "\n")
    print(f"{len(items)} items from {len(rs)} threads with an owner reply -> {a.dir}")


# ---------------------------------------------------------------- mechanisms

def owner_msgs(item):
    return [m for role, m in item["thread"] if role == "O"]


def regex_done(item):
    """The simple regex: the owner's first reply starts with a Done-type word."""
    o = owner_msgs(item)
    return bool(o and DONE.match(o[0].strip()))


# Richer patterns over every owner reply. Tuned by reading the dev half
# (even ids) only; scored on the odd half.
CHANGE_VERB = re.compile(
    r"\b(done|fixed|updated|removed|changed|added|renamed|moved|deleted|reverted|replaced|switched|"
    r"applied|refactored|rewrote|rewritten|reworded|rephrased|simplified|dropped|extracted|inlined|"
    r"split|merged|converted|restored|cleaned up|made (it|this|them|the)|now (uses?|use|calls?|checks?|"
    r"returns?|takes?|has|is)|went with|switched to|addressed|implemented|adjusted|tweaked|"
    r"clarified|documented|reverted)\b", re.I)
WILL = re.compile(r"\b(will (do|fix|update|change|add|remove)|i'll (do|fix|update|change|add|remove)|"
                  r"good (catch|call|point|idea|suggestion)|nice catch|great (catch|point|idea)|"
                  r"you're right|you are right|agreed?\b)", re.I)
NEGATIVE = re.compile(
    r"\b(follow[- ]?up|separate cl|future cl|another cl|next cl|later cl|in a later|"
    r"i'?d rather not|prefer to keep|keep (it|this) as|intentional(ly)?|on purpose|not needed|"
    r"no need|won'?t|will not|isn'?t necessary|not necessary|out of scope|leave (it|this) as|"
    r"as is\b|not (going|planning) to|not in this cl|already (handled|covered|done|the case))\b", re.I)
ACK_ONLY = re.compile(r"^\W*(ack|acknowledged|noted|ok|okay|sure|thanks?( you)?|ty|thank you!?)\W*$", re.I)
APPROVAL = re.compile(r"^\W*(lgtm|looks good|thanks|thank you|nice|great)\b", re.I)


def rules_done(item):
    o = owner_msgs(item)
    if not o:
        return False
    first = o[0].strip()
    if DONE.match(first):
        return True
    text = " ".join(o)
    if APPROVAL.match(item["root"]) and item["file"] == "/PATCHSET_LEVEL":
        return False
    if all(ACK_ONLY.match(m.strip()) for m in o):
        return False
    neg = bool(NEGATIVE.search(text))
    pos = bool(CHANGE_VERB.search(text))
    if pos and not neg:
        return True
    if pos and neg:
        # "Done" later in the thread after a discussion still wins
        return any(DONE.match(m.strip()) for m in o[1:])
    if WILL.search(text) and not neg:
        return True
    return False


# v2, refined after reading the rules' errors on the dev half (even ids).
LEAD_PREFIX = r"^\W*((thanks?( you)?|ty|ack(nowledged)?|ok(ay)?|sure|yes|yeah|yep|right|agreed?|good (catch|call|point|idea)|" \
              r"nice catch|great (catch|point|idea)|you'?re right|oops|ah|oh|indeed|makes sense|sgtm)\b[\s,.!:;-]*)*"
LEAD_VERB = re.compile(LEAD_PREFIX + r"(i('ve| have)? )?(just |now )?(done|fixed|updated|removed|changed|added|renamed|moved|"
                       r"deleted|reverted|replaced|switched|applied|refactored|rewrote|rewritten|reworded|rephrased|"
                       r"simplified|dropped|extracted|inlined|split|merged|converted|restored|used|formatted|"
                       r"implemented|adjusted|tweaked|clarified|documented|went with|made)\b", re.I)
OTHER_CL = re.compile(r"\b(cl/\d+|crrev\.com/c/\d+|other cl|separate cl|follow[- ]?up cl|another cl|"
                      r"previous cl|parent cl|next cl|in the follow[- ]?up|bug description)\b", re.I)
AGREE = re.compile(r"^\W*(sgtm|sounds good|will do|ok,? will do|good idea|let'?s do (it|that)|we can just)\b", re.I)


def rules2_done(item):
    o = owner_msgs(item)
    if not o:
        return False
    first = o[0].strip()
    if APPROVAL.match(item["root"]) and item["file"] == "/PATCHSET_LEVEL":
        return False
    text = " ".join(o)
    if LEAD_VERB.match(first) and not OTHER_CL.search(first):
        return True
    if any(DONE.match(m.strip()) for m in o) and not OTHER_CL.search(text):
        return True
    if all(ACK_ONLY.match(m.strip()) for m in o):
        return False
    if OTHER_CL.search(text):
        return False
    neg = bool(NEGATIVE.search(text))
    if AGREE.match(first) and not neg:
        return True
    pos = bool(CHANGE_VERB.search(text))
    if pos and not neg:
        return True
    if WILL.search(text) and not neg:
        return True
    return False


TOKEN = re.compile(r"[a-z']+|[!?]")


def nb_features(item):
    o = owner_msgs(item)
    f = []
    for j, m in enumerate(o[:3]):
        toks = TOKEN.findall(m.lower())[:60]
        f += [f"o:{t}" for t in toks]
        f += [f"o2:{x}_{y}" for x, y in zip(toks, toks[1:])]
        if j == 0:
            f += [f"f:{t}" for t in toks[:3]] + [f"flen:{min(len(toks), 20) // 5}"]
    rtoks = TOKEN.findall(item["root"].lower())[:30]
    f += [f"r:{t}" for t in rtoks[:3]]
    f.append(f"pl:{item['file'] == '/PATCHSET_LEVEL'}")
    f.append(f"unres:{item['root_unresolved']}")
    return f


def nb_train(items, labels):
    cnt = {True: collections.Counter(), False: collections.Counter()}
    prior = collections.Counter()
    for it in items:
        y = labels[it["id"]]
        prior[y] += 1
        cnt[y].update(set(nb_features(it)))
    vocab = set(cnt[True]) | set(cnt[False])
    return cnt, prior, {y: sum(cnt[y].values()) for y in cnt}, len(vocab)


def nb_predict(model, item):
    """Multinomial naive Bayes with add-one smoothing; unseen features are ignored."""
    cnt, prior, total, v = model
    feats = [f for f in set(nb_features(item)) if f in cnt[True] or f in cnt[False]]
    score = {}
    for y in (True, False):
        s = math.log(prior[y] / (prior[True] + prior[False]))
        for f in feats:
            s += math.log((cnt[y][f] + 1) / (total[y] + v))
        score[y] = s
    return score[True] > score[False]


def cmd_predict(a):
    items = load(os.path.join(a.dir, "dataset.jsonl"))
    t0 = time.perf_counter()
    if a.method == "regex":
        pred = {it["id"]: regex_done(it) for it in items}
    elif a.method == "rules":
        pred = {it["id"]: rules_done(it) for it in items}
    elif a.method == "rules2":
        pred = {it["id"]: rules2_done(it) for it in items}
    elif a.method == "nb":       # 10-fold cross-validation against the gold labels
        gold = gold_labels(a.dir, a.gold)
        items = [it for it in items if it["id"] in gold]
        random.seed(0)
        order = items[:]
        random.shuffle(order)
        pred = {}
        for k in range(10):
            test = order[k::10]
            train = [x for x in order if x not in test]
            m = nb_train(train, gold)
            pred.update({it["id"]: nb_predict(m, it) for it in test})
    dt = time.perf_counter() - t0
    write_jsonl(os.path.join(a.dir, f"pred_{a.method}.jsonl"), [{"id": k, "done": v} for k, v in pred.items()])
    json.dump({"seconds": dt, "items": len(pred), "tokens": 0},
              open(os.path.join(a.dir, f"cost_{a.method}.json"), "w"))
    print(f"{a.method}: {len(pred)} items in {dt * 1000:.1f} ms")


# ---------------------------------------------------------------- LLM via `claude -p`

SCHEMA = {"type": "object", "properties": {"labels": {"type": "array", "items": {
    "type": "object", "properties": {"id": {"type": "string"}, "done": {"type": "boolean"}},
    "required": ["id", "done"]}}}, "required": ["labels"]}


def claude_batch(model, text, effort):
    prompt = (DEFINITION + "\n\nClassify every item below. Return JSON only: "
              '{"labels": [{"id": "T000", "done": true}, ...]} with one entry per item.\n\n' + text)
    cmd = ["claude", "-p", "--model", model, "--output-format", "json", "--tools", "",
           "--system-prompt", "You are a precise classifier of code-review threads.",
           "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--disable-slash-commands",
           "--exclude-dynamic-system-prompt-sections", "--no-session-persistence",
           "--json-schema", json.dumps(SCHEMA)]
    if effort:
        cmd += ["--effort", effort]
    t0 = time.time()
    p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=os.environ.get("TMPDIR", "/tmp"))
    wall = time.time() - t0
    d = json.loads(p.stdout)
    out = d.get("structured_output") or {}
    if not out:
        m = re.search(r"\{.*\}", d.get("result", ""), re.S)
        out = json.loads(m.group(0)) if m else {}
    u = d.get("usage", {})
    return out.get("labels", []), dict(
        wall=wall, input=u.get("input_tokens", 0), cache_create=u.get("cache_creation_input_tokens", 0),
        cache_read=u.get("cache_read_input_tokens", 0), output=u.get("output_tokens", 0),
        usd=d.get("total_cost_usd", 0))


def cmd_llm(a):
    items = load(os.path.join(a.dir, "dataset.jsonl"))
    name = f"llm-{a.model}" + (f"-{a.effort}" if a.effort else "") + f"-b{a.batch}"
    pred, costs = {}, []
    for b in range(0, len(items), a.batch):
        chunk = items[b:b + a.batch]
        labels, cost = claude_batch(a.model, "\n\n".join(render(x) for x in chunk), a.effort)
        got = {x["id"]: bool(x["done"]) for x in labels if isinstance(x, dict) and "id" in x}
        missing = [x["id"] for x in chunk if x["id"] not in got]
        cost["missing"] = len(missing)
        costs.append(cost)
        pred.update(got)
        print(f"{name}: batch {b // a.batch} {len(got)}/{len(chunk)} labelled, {cost['wall']:.0f}s, "
              f"in {cost['input'] + cost['cache_create'] + cost['cache_read']} out {cost['output']}", file=sys.stderr)
    write_jsonl(os.path.join(a.dir, f"pred_{name}.jsonl"), [{"id": k, "done": v} for k, v in pred.items()])
    tot = {k: sum(c[k] for c in costs) for k in costs[0]}
    tot.update(items=len(items), calls=len(costs), seconds=tot["wall"],
               tokens=tot["input"] + tot["cache_create"] + tot["cache_read"] + tot["output"])
    json.dump(tot, open(os.path.join(a.dir, f"cost_{name}.json"), "w"))
    print(json.dumps(tot))


# ---------------------------------------------------------------- evaluation

def gold_labels(d, gold=None):
    path = gold or os.path.join(d, "gold.jsonl")
    return {r["id"]: r["label"] == "done" for r in load(path)}


def cmd_score(a):
    gold = gold_labels(a.dir, a.gold)
    pos = sum(gold.values())
    print(f"gold: {len(gold)} items, {pos} done ({100 * pos / len(gold):.0f}%)")
    print(f"{'method':28s} {'prec':>6s} {'recall':>6s} {'F1':>5s} {'acc':>6s} {'n':>4s} "
          f"{'sec/1k':>8s} {'tok/1k':>9s}")
    for path in sorted(glob.glob(os.path.join(a.dir, "pred_*.jsonl"))):
        name = os.path.basename(path)[5:-6]
        pred = {r["id"]: r["done"] for r in load(path)}
        ids = [i for i in gold if i in pred]
        if a.half:
            ids = [i for i in ids if int(i[1:]) % 2 == (1 if a.half == "odd" else 0)]
        tp = sum(gold[i] and pred[i] for i in ids)
        fp = sum(not gold[i] and pred[i] for i in ids)
        fn = sum(gold[i] and not pred[i] for i in ids)
        acc = sum(gold[i] == pred[i] for i in ids) / len(ids)
        p = tp / (tp + fp) if tp + fp else 0
        r = tp / (tp + fn) if tp + fn else 0
        f1 = 2 * p * r / (p + r) if p + r else 0
        cost = {}
        cp = os.path.join(a.dir, f"cost_{name}.json")
        if os.path.exists(cp):
            cost = json.load(open(cp))
        per = 1000 / cost["items"] if cost.get("items") else 0
        print(f"{name:28s} {p:6.3f} {r:6.3f} {f1:5.3f} {acc:6.3f} {len(ids):4d} "
              f"{cost.get('seconds', 0) * per:8.1f} {cost.get('tokens', 0) * per:9.0f}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("dataset")
    s.add_argument("threads")
    s.add_argument("dir")
    s.add_argument("--n", type=int, default=400)
    s.add_argument("--batch", type=int, default=100)
    s.add_argument("--seed", type=int, default=42)
    s = sub.add_parser("predict")
    s.add_argument("dir")
    s.add_argument("method", choices=["regex", "rules", "rules2", "nb"])
    s.add_argument("--gold")
    s = sub.add_parser("llm")
    s.add_argument("dir")
    s.add_argument("model")
    s.add_argument("--batch", type=int, default=50)
    s.add_argument("--effort")
    s = sub.add_parser("score")
    s.add_argument("dir")
    s.add_argument("--gold")
    s.add_argument("--half", choices=["odd", "even"])
    a = ap.parse_args()
    {"dataset": cmd_dataset, "predict": cmd_predict, "llm": cmd_llm, "score": cmd_score}[a.cmd](a)


if __name__ == "__main__":
    main()
