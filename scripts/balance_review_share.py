"""Add the "From author to reviewer" histogram to summaries/balance.json (the
Review Balance page): how review share, approvals given ÷ (approvals + CLs
authored), is spread across people at each year since joining.

Same people and definition as `git_cohorts` in balance_report.py: everyone
whose first commit on main fell in 2017–2025, in each calendar year where
they authored or approved 6 or more CLs (reverts and mechanical commits
aside), with all join years pooled. Writes shares of people per bin only:
nothing per person.

  COSH_DATA_DIR=<main>/data/private python3 scripts/balance_review_share.py \
      --first-commit F --owners-added F [summaries/balance.json]
"""

import argparse
import json
import os
import statistics as st
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import balance_analysis as A  # noqa: E402
import balance_growth as G  # noqa: E402

COHORTS = range(2017, 2026)
LAST_YEAR = 2026
YEARS = range(1, 10)          # years since joining, as in git_cohorts
MIN_COHORT = 20               # people a cohort needs for its median to count


def bin_of(share):
    """0: no approvals at all; 1–10: tenths of review share (1.0 in the top bin)."""
    return 0 if share == 0 else 1 + min(int(share * 10), 9)


def datasets(shares):
    """shares: {(cohort, year since joining): [review share per person]}."""
    hist, summary = [], []
    for k in YEARS:
        xs = [x for (fy, kk), v in shares.items() if kk == k for x in v]
        if not xs:
            continue
        counts = Counter(bin_of(x) for x in xs)
        for b in range(11):
            hist.append(dict(year=k, bin=b, lo=0 if b == 0 else (b - 1) / 10, hi=0 if b == 0 else b / 10,
                             people=counts[b], share=round(counts[b] / len(xs), 4)))
        meds = [st.median(v) for (fy, kk), v in shares.items() if kk == k and len(v) >= MIN_COHORT]
        summary.append(dict(year=k, people=len(xs), none=round(counts[0] / len(xs), 4),
                            half=round(sum(x >= 0.5 for x in xs) / len(xs), 4),
                            p50=round(st.median(xs), 2),
                            cohorts=len(meds), cohort_p50_min=round(min(meds), 2) if meds else None,
                            cohort_p50_max=round(max(meds), 2) if meds else None))
    return dict(review_share_hist=hist, review_share_years=summary)


def load(args):
    cls, commits, ids, first, owner_at, ai = G.load_all(args)
    del cls
    authored = defaultdict(Counter)
    given = defaultdict(Counter)
    for c in commits:
        if not c["n"] or c["is_revert"]:
            continue
        y = A.year(c["at"])
        authored[c["pid"]][y] += 1
        for rv in c["rbp"]:
            if rv != c["pid"]:
                given[rv][y] += 1
    shares = defaultdict(list)
    for p, t in first.items():
        fy = A.year(t)
        if fy not in COHORTS:
            continue
        for k in YEARS:
            y = fy + k - 1
            if y > LAST_YEAR:
                break
            a, g = authored[p][y], given[p][y]
            if a + g >= 6:
                shares[(fy, k)].append(g / (a + g))
    return shares


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default="summaries/balance.json")
    ap.add_argument("--first-commit", help="default: commits.sqlite")
    ap.add_argument("--owners-added", help="default: commits.sqlite")
    ap.add_argument("--ai-marked", help="default: commits.sqlite")
    args = ap.parse_args()
    data = json.load(open(args.path))
    new = datasets(load(args))
    for r in new["review_share_years"]:
        print(r, file=sys.stderr)
    data["datasets"].update(new)
    json.dump(data, open(args.path, "w"), separators=(",", ":"))
    open(args.path, "a").write("\n")


if __name__ == "__main__":
    main()
