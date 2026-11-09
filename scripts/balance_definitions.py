"""Add the "Feedback index" definition data to summaries/balance.json (the
Review Balance page): for each decile of CL size, the share of CLs by the
number of reviewer threads they drew, over 2023–24, the years the feedback
index takes its norm from.

Offline; reads balance.sqlite (read-only) and the mechanical-CL list that
balance_report.py takes (--mech, one JSON line per CL). Writes shares of CLs
per bin only: nothing per person or per CL.

  COSH_DATA_DIR=<main>/data/private python3 scripts/balance_definitions.py \
      --mech mech.jsonl [summaries/balance.json]

The CLs are those the feedback index uses: merged, with a known owner, not
mechanical, closed in 2023 or 2024 (Gerrit data starts in July 2023).
"""

import argparse
import json
import os
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import balance_analysis as A  # noqa: E402
from balance_report import mech_set  # noqa: E402
from cosh import balance  # noqa: E402

REF = (2023, 2024)

# One bin per thread count up to MAX; the page doesn't draw the open-ended
# last bin (it would pile the long tail into one point) but its share is in
# feedback_def_deciles as over_max.
MAX = 20
BINS = list(range(MAX + 2))


def bin_of(t):
    for i in range(len(BINS) - 1, -1, -1):
        if t >= BINS[i]:
            return i
    return 0


def deciles(cls):
    """Ten groups of CLs by changed lines, cut at the deciles of size. CLs
    tied at a cut stay together, so a group can hold a little more or less
    than a tenth."""
    lines = sorted(c[0] for c in cls)
    cuts = [lines[int(len(lines) * k / 10)] for k in range(1, 10)]
    groups = [[] for _ in range(10)]
    for c in cls:
        g = sum(1 for x in cuts if c[0] >= x)
        groups[g].append(c)
    return groups


def datasets(cls):
    groups = deciles(cls)
    rows, summary = [], []
    total = len(cls)
    for d, g in enumerate(groups):
        if not g:
            continue
        counts = [0] * len(BINS)
        for _, t in g:
            counts[bin_of(t)] += 1
        lo, hi = min(c[0] for c in g), max(c[0] for c in g)
        mean = st.mean(t for _, t in g)
        summary.append(dict(decile=d + 1, lo=lo, hi=hi, cls=len(g), share=round(len(g) / total, 4),
                            mean_threads=round(mean, 2), median_threads=st.median(t for _, t in g),
                            no_thread=round(counts[0] / len(g), 4), over_max=round(counts[-1] / len(g), 4)))
        for i, k in enumerate(counts):
            rows.append(dict(decile=d + 1, bin=i, lo=BINS[i], hi=(BINS[i + 1] - 1) if i + 1 < len(BINS) else None,
                             share=round(k / len(g), 4)))
    return {"feedback_def_hist": rows, "feedback_def_deciles": summary,
            "feedback_def_summary": [dict(from_year=REF[0], to_year=REF[1], cls=total, max_threads=MAX)]}


def load(mech_path):
    mech = mech_set(mech_path)
    db = A.ro(balance.db_path("cl"))
    rows = db.execute("SELECT change_number, closed_at, ins, dels, threads FROM cl "
                      "WHERE status = 'MERGED' AND closed_at IS NOT NULL AND owner_email IS NOT NULL").fetchall()
    return [((ins or 0) + (dels or 0), threads or 0) for n, closed, ins, dels, threads in rows
            if n not in mech and REF[0] <= A.year(closed) <= REF[1]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default="summaries/balance.json")
    ap.add_argument("--mech", required=True)
    args = ap.parse_args()
    data = json.load(open(args.path))
    new = datasets(load(args.mech))
    for k, v in new.items():
        print(f"{k}: {v if k != 'feedback_def_hist' else len(v)}", file=sys.stderr)
        data["datasets"][k] = v
    json.dump(data, open(args.path, "w"), separators=(",", ":"))
    open(args.path, "a").write("\n")


if __name__ == "__main__":
    main()
