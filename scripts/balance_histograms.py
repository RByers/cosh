"""Add the "Waiting for review" histograms to summaries/balance.json (the
Review Balance page): hours to first substantive review, and reviewers'
weekday hours in the attention set, for the latest year against the pre-AI
baseline the page's other era charts use (2023 H2 – 2024).

Offline; reads balance.sqlite (read-only) and the mechanical-CL list that
balance_report.py takes (--mech, one JSON line per CL). Writes shares of CLs
per bin only: nothing per person or per CL.

  COSH_DATA_DIR=<main>/data/private python3 scripts/balance_histograms.py \
      --mech mech.jsonl [summaries/balance.json]

The CLs are those of the quarterly charts: merged, with a known owner, not
mechanical, and with a substantive review.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import balance_analysis as A  # noqa: E402
from balance_report import mech_set  # noqa: E402
from cosh import balance  # noqa: E402

# The latest whole year, and the pre-AI baseline (the "2023H2-2024" era).
NOW = ("2025Q4", "2026Q3")
THEN = ("2023Q3", "2024Q4")

# Bin upper edges in hours; the last bin is open-ended.
EDGES = [1, 2, 4, 8, 16, 24, 48, 96, 168, 336]


def bin_of(h):
    for i, e in enumerate(EDGES):
        if h < e:
            return i
    return len(EDGES)


def histogram(cls, field, lo, hi):
    counts = [0] * (len(EDGES) + 1)
    for c in cls:
        if lo <= c["q"] <= hi and c[field] is not None:
            counts[bin_of(c[field])] += 1
    n = sum(counts)
    return n, [round(k / n, 4) for k in counts]


def datasets(cls):
    out = {}
    for name, field in (("ftr_hist", "ftr"), ("wait_hist", "reviewer_wait_wd_h")):
        n_now, now = histogram(cls, field, *NOW)
        n_then, then = histogram(cls, field, *THEN)
        out[name] = [dict(bin=i, lo=([0] + EDGES)[i], hi=(EDGES + [None])[i], now=now[i], then=then[i])
                     for i in range(len(EDGES) + 1)]
        out[name + "_summary"] = [dict(now_from=NOW[0], now_to=NOW[1], then_from=THEN[0], then_to=THEN[1],
                                       now_cls=n_now, then_cls=n_then)]
    return out


def load(mech_path):
    mech = mech_set(mech_path)
    db = A.ro(balance.db_path("cl"))
    rows = db.execute("SELECT change_number, closed_at, sent_at, first_review_at, reviewer_wait_wd_h FROM cl "
                      "WHERE status = 'MERGED' AND closed_at IS NOT NULL AND owner_email IS NOT NULL "
                      "AND first_review_at IS NOT NULL").fetchall()
    out = []
    for n, closed, sent, first, wait in rows:
        if n in mech:
            continue
        out.append(dict(q=A.quarter(closed), reviewer_wait_wd_h=wait,
                        ftr=(first - sent) / 3600 if sent and first >= sent else None))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default="summaries/balance.json")
    ap.add_argument("--mech", required=True)
    args = ap.parse_args()
    data = json.load(open(args.path))
    new = datasets(load(args.mech))
    for k, v in new.items():
        print(f"{k}: {v if k.endswith('summary') else len(v)}", file=sys.stderr)
        data["datasets"][k] = v
    json.dump(data, open(args.path, "w"), separators=(",", ":"))
    open(args.path, "a").write("\n")


if __name__ == "__main__":
    main()
