"""Score a sentiment prompt against the gold set (docs/sentiment.md).

  COSH_DATA_DIR=<main>/data/private python3 scripts/sentiment_tune.py v3 [--runs 2] [--gold PATH]

Prints MAE, Pearson r, 3-class agreement (neg < -0.2 <= neutral <= 0.2 < pos),
AI-flag precision/recall and the largest errors. Results are saved in
data/private/sentiment/ as tune-<version>-<n>.json so versions can be compared.
The gold labels ({"id", "score", "ai"} per line, no comment text) are kept
in data/private/sentiment/gold.jsonl, not in git: a list of specific
comments labelled hostile would point fingers (docs/plan.md, ground rule 5).
"""
import argparse
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from cosh import sentiment as S  # noqa: E402


def cls(x):
    return -1 if x < -0.2 else 1 if x > 0.2 else 0


def metrics(gold, pred):
    ids = [i for i in gold if i in pred]
    g = [gold[i]["score"] for i in ids]
    p = [pred[i][0] for i in ids]
    n = len(ids)
    mae = sum(abs(a - b) for a, b in zip(g, p)) / n
    mg, mp = sum(g) / n, sum(p) / n
    cov = sum((a - mg) * (b - mp) for a, b in zip(g, p))
    r = cov / math.sqrt(sum((a - mg) ** 2 for a in g) * sum((b - mp) ** 2 for b in p) or 1)
    agree = sum(cls(a) == cls(b) for a, b in zip(g, p)) / n
    tp = sum(1 for i in ids if gold[i]["ai"] and pred[i][1])
    fp = sum(1 for i in ids if not gold[i]["ai"] and pred[i][1])
    fn = sum(1 for i in ids if gold[i]["ai"] and not pred[i][1])
    # Error on the extremes matters most for outlier reports.
    ext = [abs(gold[i]["score"] - pred[i][0]) for i in ids if abs(gold[i]["score"]) >= 0.5]
    return dict(n=n, missing=len(gold) - n, mae=round(mae, 3), r=round(r, 3), agree3=round(agree, 3),
                mae_extremes=round(sum(ext) / len(ext), 3) if ext else None,
                ai_tp=tp, ai_fp=fp, ai_fn=fn)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("version")
    ap.add_argument("--gold", default=os.path.join(S.out_dir(), "gold.jsonl"))
    ap.add_argument("--comments", default=os.path.join(S.out_dir(), "comments-2026-W44.jsonl"))
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--batch", type=int, default=50)
    ap.add_argument("--show", type=int, default=15,
                    help="largest errors to print, with 160 chars of comment text each. Keep it small when an "
                         "agent runs this: comment text is untrusted (SECURITY.md)")
    ap.add_argument("--sandbox", choices=["auto", "bwrap", "none"], default="auto")
    a = ap.parse_args()
    gold = {g["id"]: g for g in S.read_jsonl(a.gold)}
    rows = [r for r in S.read_jsonl(a.comments) if r["id"] in gold]
    definition = S.load_prompt(a.version)
    box = S.make_sandbox(a.sandbox, S.store.DATA_DIR)
    for run in range(a.runs):
        pred, st = S.score_items(rows, definition, a.model, a.batch, jobs=4, sandbox=box)
        m = metrics(gold, pred)
        m.update(version=a.version, run=run, tokens=st["tokens"], usd=round(st["usd"], 3))
        print(json.dumps(m))
        out = os.path.join(S.out_dir(), f"tune-{a.version}-{run}.json")
        with open(out, "w") as f:
            json.dump(dict(metrics=m, pred={i: list(v) for i, v in pred.items()}), f)
        errs = sorted((abs(gold[i]["score"] - pred[i][0]), i) for i in gold if i in pred)[::-1]
        for e, i in errs[:a.show]:
            t = next(r for r in rows if r["id"] == i)["text"][:160].replace("\n", " ")
            print(f"  {e:.2f} gold {gold[i]['score']:+.1f} pred {pred[i][0]:+.1f} ai {gold[i]['ai']}/{pred[i][1]} "
                  f"{i}: {t}")
        for i in gold:
            if i in pred and gold[i]["ai"] != pred[i][1]:
                t = next(r for r in rows if r["id"] == i)["text"][:160].replace("\n", " ")
                print(f"  AI-flag gold {gold[i]['ai']} pred {pred[i][1]} {i}: {t}")
    box.close()


if __name__ == "__main__":
    main()
