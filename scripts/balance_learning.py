"""Learning by practice or by time? For the Review Balance page's "Learning
to need less review feedback" section (docs/balance.md, section 4b).

Compares two measures of experience as predictors of the feedback index
(reviewer threads ÷ the 2023–24 mean for the CL's size and directory):
months since the author's first commit (tenure), and the commits the author
had landed on main before the CL (practice). Then splits authors by how fast
they landed CLs in their first year, prolific against average, and draws
each group's curve against both measures.

Offline; reads balance*.sqlite and derived.sqlite through balance_growth.
Writes aggregates only (feedback index and counts per bin), never anything per
person.

  COSH_DATA_DIR=<main>/data/private python3 scripts/balance_learning.py \
      --first-commit F --owners-added F --mech mech.jsonl [--explore] [summaries/balance.json]

Only authors whose first commit is on or after 2017-01-01 are used, since
gcommits starts then and earlier commits are not counted here. CLs are
merged and non-mechanical, closed 2023Q3 .. 2024Q4 (the pre-AI baseline the
page's other era charts use) unless --era says otherwise.
"""

import argparse
import bisect
import json
import math
import os
import statistics as st
import sys
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import balance_analysis as A  # noqa: E402
import balance_growth as G  # noqa: E402
from balance_report import mech_set  # noqa: E402

YEAR = G.YEAR
MONTH = YEAR / 12
GIT_START = datetime(2017, 1, 1, tzinfo=timezone.utc).timestamp()
ERAS = {"then": ("2023Q3", "2024Q4"), "now": ("2025Q4", "2026Q3")}

TENURE = [(0, 3), (3, 6), (6, 12), (12, 24), (24, 48), (48, 10 ** 9)]          # months
PRACTICE = [(0, 10), (10, 30), (30, 100), (100, 300), (300, 1000), (1000, 10 ** 9)]   # prior commits
# Prolific: the top fifth by commits landed in the first 12 months; average: the middle fifth (40th–60th
# percentile), the typical contributor. Measured over each person's first year, so a person's group never
# depends on the CLs it is compared on after that year.
GROUPS = [("prolific", 0.8, 1.0), ("average", 0.4, 0.6)]
MIN_CLS, MIN_PEOPLE = 200, 20       # per published point


def label(lo, hi):
    return f"{lo}+" if hi >= 10 ** 9 else f"{lo}-{hi}"


def bin_of(bins, v):
    for lo, hi in bins:
        if lo <= v < hi:
            return label(lo, hi)
    return None


def load(args):
    cls, commits, ids, first, owner_at, ai = G.load_all(args)
    mech = mech_set(args.mech)
    dirs3 = A.commit_dirs(3)
    top2 = {}
    for c in commits:
        d = dirs3.get(c["cid"])
        if c["n"] and d:
            top2[c["n"]] = "/".join(d[0].split("/")[:2])
    A.MECH_FILES = 10 ** 9
    for c in cls:
        if c["change_number"] in mech:
            c["status"] = "MECH"
    use = G.cl_residuals(cls, top2)
    # Landed commits per person, in order (reverts included: they're work landed too).
    landed = defaultdict(list)
    for c in commits:
        landed[c["pid"]].append(c["at"])
    for v in landed.values():
        v.sort()
    return use, first, landed


def first_year_rate(first, landed):
    """Commits landed in each post-2017 joiner's first 12 months, for joiners whose first year is in the
    data (joined before 2025-10)."""
    end = datetime(2025, 10, 1, tzinfo=timezone.utc).timestamp()
    out = {}
    for p, t in first.items():
        if GIT_START <= t < end:
            out[p] = bisect.bisect_left(landed.get(p, []), t + YEAR)
    return out


def groups_of(rate):
    xs = sorted(rate.values())
    q = lambda f: xs[min(len(xs) - 1, int(f * len(xs)))]
    cuts = {g: (q(lo), q(hi) if hi < 1 else 10 ** 9) for g, lo, hi in GROUPS}
    out = {}
    for p, n in rate.items():
        for g, (lo, hi) in cuts.items():
            if lo <= n < hi or (hi == 10 ** 9 and n >= lo):
                out[p] = g
    return out, cuts


def rows(use, first, landed, era):
    lo, hi = ERAS[era]
    out = []
    for c in use:
        p = c["pid"]
        t0 = first.get(p)
        if t0 is None or t0 < GIT_START or not (lo <= A.quarter(c["closed_at"]) <= hi):
            continue
        months = (c["closed_at"] - t0) / MONTH
        if months < 0:
            continue
        prior = bisect.bisect_left(landed.get(p, []), c["closed_at"] - 60)   # its own commit lands ~at close
        out.append(dict(pid=p, months=months, prior=prior, threads=c["threads"], exp=c["exp24"],
                        r=c["r_threads"]))
    return out


def index(s):
    e = sum(c["exp"] for c in s)
    return round(sum(c["threads"] for c in s) / e, 2) if e else None


def r2(xs, key):
    """Share of the variance in the calendar-adjusted thread residual explained by bin means."""
    xs = [c for c in xs if c["r"] is not None and key(c) is not None]
    m = st.mean(c["r"] for c in xs)
    tot = sum((c["r"] - m) ** 2 for c in xs)
    g = defaultdict(list)
    for c in xs:
        g[key(c)].append(c["r"])
    gm = {k: st.mean(v) for k, v in g.items()}
    res = sum((c["r"] - gm[key(c)]) ** 2 for c in xs)
    return 1 - res / tot


def spearman(xs, a, b):
    def ranks(v):
        o = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(o):
            j = i
            while j + 1 < len(o) and v[o[j + 1]] == v[o[i]]:
                j += 1
            for k in range(i, j + 1):
                r[o[k]] = (i + j) / 2
            i = j + 1
        return r
    xs = [c for c in xs if c["r"] is not None]
    ra, rb = ranks([a(c) for c in xs]), ranks([b(c) for c in xs])
    ma, mb = st.mean(ra), st.mean(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    return num / math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))


def datasets(rs, grp, cuts):
    ten = lambda c: bin_of(TENURE, c["months"])
    pra = lambda c: bin_of(PRACTICE, c["prior"])
    out = {}
    # Each group's curve against tenure and against practice.
    curve = []
    for by, key, bins in (("tenure", ten, TENURE), ("practice", pra, PRACTICE)):
        for g, _, _ in GROUPS:
            for lo, hi in bins:
                b = label(lo, hi)
                s = [c for c in rs if grp.get(c["pid"]) == g and key(c) == b]
                if len(s) < MIN_CLS or len({c["pid"] for c in s}) < MIN_PEOPLE:
                    continue
                curve.append(dict(by=by, group=g, bucket=b, feedback_index=index(s), cls=len(s),
                                  people=len({c["pid"] for c in s}),
                                  median_prior=st.median(c["prior"] for c in s),
                                  median_months=round(st.median(c["months"] for c in s), 1)))
    out["learning_practice"] = curve
    # Which measure predicts better: variance of the calendar-adjusted residual explained by each one's
    # bins, and by both together.
    out["learning_practice_fit"] = [dict(
        cls=len(rs), people=len({c["pid"] for c in rs}),
        r2_tenure=round(r2(rs, ten), 4), r2_practice=round(r2(rs, pra), 4),
        r2_both=round(r2(rs, lambda c: (ten(c), pra(c))), 4),
        rho_tenure=round(spearman(rs, lambda c: c["months"], lambda c: c["r"]), 3),
        rho_practice=round(spearman(rs, lambda c: c["prior"], lambda c: c["r"]), 3),
        prolific_min=cuts["prolific"][0], average_min=cuts["average"][0], average_max=cuts["average"][1] - 1)]
    return out


def explore(rs, grp):
    ten = lambda c: bin_of(TENURE, c["months"])
    pra = lambda c: bin_of(PRACTICE, c["prior"])
    print("\nfeedback index, tenure (rows) x prior commits (cols); n in brackets")
    pl = [label(*b) for b in PRACTICE]
    print("tenure".ljust(8) + "".join(x.rjust(16) for x in pl))
    for b in TENURE:
        t = label(*b)
        line = t.ljust(8)
        for p in pl:
            s = [c for c in rs if ten(c) == t and pra(c) == p]
            line += (f"{index(s)} [{len(s)}]" if len(s) >= 100 else "").rjust(16)
        print(line)
    # Within-tenure correlation of practice with feedback and within-practice correlation of tenure.
    for name, outer, inner in (("practice | tenure", ten, lambda c: c["prior"]),
                               ("tenure | practice", pra, lambda c: c["months"])):
        out = []
        for b in sorted({outer(c) for c in rs}, key=str):
            s = [c for c in rs if outer(c) == b]
            if len(s) > 2000:
                out.append(f"{b}: {spearman(s, inner, lambda c: c['r']):.3f}")
        print(name, " ".join(out))
    for g, _, _ in GROUPS:
        s = [c for c in rs if grp.get(c["pid"]) == g]
        print(g, len(s), "CLs", len({c["pid"] for c in s}), "people")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default="summaries/balance.json")
    ap.add_argument("--first-commit", help="default: commits.sqlite")
    ap.add_argument("--owners-added", help="default: commits.sqlite")
    ap.add_argument("--mech", help="default: commits.sqlite")
    ap.add_argument("--era", choices=sorted(ERAS), default="then")
    ap.add_argument("--explore", action="store_true", help="print tables; don't write")
    args = ap.parse_args()
    args.ai_marked = None
    use, first, landed = load(args)
    rate = first_year_rate(first, landed)
    grp, cuts = groups_of(rate)
    print("first-year commits cuts", cuts, file=sys.stderr)
    rs = rows(use, first, landed, args.era)
    new = datasets(rs, grp, cuts)
    for x in new["learning_practice_fit"]:
        print(x, file=sys.stderr)
    for x in new["learning_practice"]:
        print(x, file=sys.stderr)
    if args.explore:
        explore(rs, grp)
        return
    data = json.load(open(args.path))
    data["datasets"].update(new)
    json.dump(data, open(args.path, "w"), separators=(",", ":"))
    open(args.path, "a").write("\n")


if __name__ == "__main__":
    main()
