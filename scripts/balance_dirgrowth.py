"""Growth by directory (docs/balance.md, section 6c): how hard it is to grow
expertise in each 2-level directory, and how open each one is to new
reviewers. Also the third_party/blink drill-down of section 2b.

Offline; reads balance*.sqlite through balance_growth. Prints aggregates
only (per directory and per tenure bin), never anything per person.

  COSH_DATA_DIR=<main>/data/private python3 scripts/balance_dirgrowth.py \
      --first-commit F --owners-added F --mech mech.jsonl [--min-cls 3000]

Measures, per directory d (the 2-level directory holding most of a commit's
lines):

- Directory tenure: time since the person's first commit whose main
  directory is d. git history starts in 2017, so anyone already in d then
  starts in 2017, which puts them in the top bin for 2023+ CLs anyway.
- Learning slope (difficulty): the review load index (reviewer threads ÷
  the 2023–24 mean for the CL's size and directory) of d's CLs in tenure
  bins, fitted as ln(index) against log2(directory tenure), weighted by CLs.
  exp(slope) is the factor per doubling of tenure: 0.80 means review need
  falls 20% each time tenure doubles. Nearer 1 = slower learning, so growth
  there is harder. Also the ratio of the < 1 year bin to the 4+ year bin.
- Promotion (openness): of people who joined the project in 2017 or later,
  started in d in 2017–2021 and landed
  5+ CLs there within 2 years, the share who gave 10+ approvals
  (Reviewed-by) on others' commits in d within 3 years of starting there,
  and the median years to that 10th approval among those who got there.
- New-reviewer share (openness now): the share of d's approvals given by
  approvers with under 3 years on the project (first commit over all
  history), by year. Directory tenure can't be used here: git history
  starts in 2017, so it can't tell veterans from newcomers before ~2021.
"""

import argparse
import math
import os
import statistics as st
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import balance_analysis as A  # noqa: E402
import balance_growth as G  # noqa: E402
from balance_report import mech_set  # noqa: E402

YEAR = G.YEAR
ERAS = {"pre": ("2023Q3", "2024Q4"), "now": ("2025Q4", "2026Q3")}
BINS = [(0, .5), (.5, 1), (1, 2), (2, 4), (4, 99)]
MIDS = [.25, .75, 1.5, 3, 6]
BLINK = "third_party/blink"


def ts(y, m=1):
    return datetime(y, m, 1, tzinfo=timezone.utc).timestamp()


def year_of(t):
    return datetime.fromtimestamp(t, timezone.utc).year


def bin_i(t):
    for i, (lo, hi) in enumerate(BINS):
        if lo <= t < hi:
            return i
    return None


def learning(rows):
    """rows: [(dir tenure years, threads, exp)] -> (factor per doubling, <1y ÷ 4y+, per-bin index, n)."""
    th, ex, n = [0.0] * 5, [0.0] * 5, [0] * 5
    for t, k, e in rows:
        i = bin_i(t)
        if i is not None:
            th[i] += k
            ex[i] += e
            n[i] += 1
    idx = [th[i] / ex[i] if ex[i] and n[i] >= 30 and th[i] > 0 else None for i in range(5)]
    pts = [(math.log2(MIDS[i]), math.log(idx[i]), n[i]) for i in range(5) if idx[i]]
    if len(pts) < 3:
        return None, None, idx, sum(n)
    w = sum(p[2] for p in pts)
    mx = sum(p[0] * p[2] for p in pts) / w
    my = sum(p[1] * p[2] for p in pts) / w
    b = sum(p[2] * (p[0] - mx) * (p[1] - my) for p in pts) / sum(p[2] * (p[0] - mx) ** 2 for p in pts)
    lo = (th[0] + th[1]) / (ex[0] + ex[1]) if ex[0] + ex[1] and n[0] + n[1] >= 30 else None
    return math.exp(b), (lo / idx[4] if lo and idx[4] else None), idx, sum(n)


def pct(xs, p):
    xs = sorted(x for x in xs if x is not None)
    return xs[min(len(xs) - 1, int(p * len(xs)))] if xs else None


def f2(x, n=2):
    return "–" if x is None else f"{x:.{n}f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--first-commit", required=True)
    ap.add_argument("--owners-added", required=True)
    ap.add_argument("--mech", required=True)
    ap.add_argument("--ai-marked")
    ap.add_argument("--min-cls", type=int, default=3000, help="CLs in the 'pre' era for a directory to be listed")
    args = ap.parse_args()
    cls, commits, ids, first, owner_at, ai = G.load_all(args)
    mech = mech_set(args.mech)
    dirs3 = A.commit_dirs(3)
    top2, cdir = {}, {}
    for c in commits:
        d = dirs3.get(c["cid"])
        if d:
            d2 = "/".join(d[0].split("/")[:2])
            cdir[c["cid"]] = d2
            if c["n"]:
                top2[c["n"]] = d2
    A.MECH_FILES = 10 ** 9
    for c in cls:
        if c["change_number"] in mech:
            c["status"] = "MECH"
    use = G.cl_residuals(cls, top2)

    # Directory start per person, authored commits in d by time, approvals in d.
    start = {}
    authored = defaultdict(list)
    approvals = defaultdict(list)          # (pid, d) -> [t]
    appr_by_year = defaultdict(lambda: defaultdict(list))   # d -> year -> [approver dir tenure or None]
    by_n = {}
    for c in sorted(commits, key=lambda c: c["at"]):
        d = cdir.get(c["cid"])
        if not d:
            continue
        k = (c["pid"], d)
        start.setdefault(k, c["at"])
        authored[k].append(c["at"])
        if c["n"]:
            by_n[c["n"]] = c
        for r in set(c["rbp"]):
            if r == c["pid"]:
                continue
            approvals[(r, d)].append(c["at"])
            f = first.get(r)
            appr_by_year[d][year_of(c["at"])].append((c["at"] - f) / YEAR if f is not None else None)

    # ---------------------------------------------------------- learning slope
    rows = {e: defaultdict(list) for e in ERAS}
    cnt = Counter()
    for c in use:
        d, q = c["d2"], A.quarter(c["closed_at"])
        s = start.get((c["pid"], d))
        if not d or s is None:
            continue
        t = max(0.0, (c["closed_at"] - s) / YEAR)
        for e, (lo, hi) in ERAS.items():
            if lo <= q <= hi:
                rows[e][d].append((t, c["threads"], c["exp24"]))
                if e == "pre":
                    cnt[d] += 1
    dirs = [d for d, n in cnt.most_common() if n >= args.min_cls]
    if BLINK not in dirs:
        dirs.append(BLINK)

    # ---------------------------------------------------------- promotion
    promo = defaultdict(lambda: defaultdict(lambda: [0, 0, []]))   # d -> cohort -> [eligible, promoted, years]
    for (p, d), s in start.items():
        y = year_of(s)
        if not (2017 <= y <= 2021) or first.get(p, 0) < ts(2017):   # joined the project in git's window
            continue
        if sum(1 for t in authored[(p, d)] if t < s + 2 * YEAR) < 5:
            continue
        coh = "2017-19" if y <= 2019 else "2020-21"
        rec = promo[d][coh]
        rec[0] += 1
        ap_ = sorted(approvals.get((p, d), []))
        if len(ap_) >= 10 and ap_[9] < s + 3 * YEAR:
            rec[1] += 1
            rec[2].append((ap_[9] - s) / YEAR)

    def new_share(d, y):
        xs = appr_by_year[d][y]
        known = [x for x in xs if x is not None]
        return (sum(1 for x in known if x < 3) / len(xs) if xs else None), len(xs)

    print("== Directory growth (pre = 2023Q3–2024Q4, now = 2025Q4–2026Q3)")
    print("dir | CLs pre | factor/doubling pre, now | <1y÷4y+ pre, now | promoted ≤3y 2017-19, 2020-21 (n) | "
          "median y to 10th approval | approvals by approvers <3y on the project 2019, 2022, 2024, 2026 | 2026 approvals with unknown tenure")
    out = []
    for d in dirs:
        fp, rp, _, n = learning(rows["pre"][d])
        fn, rn, _, _ = learning(rows["now"][d])
        pr = promo[d]
        sh = [new_share(d, y)[0] for y in (2019, 2022, 2024, 2026)]
        xs = appr_by_year[d][2026]
        outside = sum(1 for x in xs if x is None) / len(xs) if xs else None
        p1 = pr["2017-19"][1] / pr["2017-19"][0] if pr["2017-19"][0] >= 10 else None
        p2 = pr["2020-21"][1] / pr["2020-21"][0] if pr["2020-21"][0] >= 10 else None
        yrs = pr["2017-19"][2] + pr["2020-21"][2]
        out.append((d, n, fp, fn, rp, rn, p1, p2, pr["2017-19"][0] + pr["2020-21"][0], pct(yrs, .5), sh, outside))
        print(f"{d} | {n} | {f2(fp)}, {f2(fn)} | {f2(rp)}, {f2(rn)} | {f2(p1)}, {f2(p2)} ({pr['2017-19'][0]}+{pr['2020-21'][0]}) | "
              f"{f2(pct(yrs, .5), 1)} | {', '.join(f2(x) for x in sh)} | {f2(outside)}")

    # First-review wait per directory, A = 2024Q1–2025Q2 against B = 2026Q2–Q4, and how it relates to
    # the growth measures across directories.
    wa, wb = defaultdict(list), defaultdict(list)
    for c in use:
        q = A.quarter(c["closed_at"])
        if c["first_review_at"] and c["sent_at"] and c["first_review_at"] >= c["sent_at"]:
            w = (c["first_review_at"] - c["sent_at"]) / 3600
            if "2024Q1" <= q <= "2025Q2":
                wa[c["d2"]].append(w)
            elif "2026Q2" <= q <= "2026Q4":
                wb[c["d2"]].append(w)
    print("\ndir | wait p50 A -> B (h) | ratio | new-reviewer share 2024 -> 2026")
    ratio = {}
    for o in out:
        d = o[0]
        a, b = pct(wa[d], .5), pct(wb[d], .5)
        ratio[d] = b / a if a and b else None
        print(f"{d} | {f2(a, 1)} -> {f2(b, 1)} | {f2(ratio[d])} | {f2(o[10][2])} -> {f2(o[10][3])}")

    # ranks
    def rank(col, rev=False):
        v = [(o[col], o[0]) for o in out if o[col] is not None]
        v.sort(reverse=rev)
        return {dd: i + 1 for i, (_, dd) in enumerate(v)}, len(v)
    for name, col, rev in (("factor/doubling pre (1 = flattest)", 2, True), ("factor/doubling now", 3, True),
                           ("promoted 2020-21 (1 = least open)", 7, False), ("new-reviewer share 2026 (1 = lowest)", None, False)):
        if col is None:
            v = sorted((o[10][3], o[0]) for o in out if o[10][3] is not None)
            rk = {dd: i + 1 for i, (_, dd) in enumerate(v)}
            print(f"blink rank on {name}: {rk.get(BLINK)} of {len(v)}")
        else:
            rk, nn = rank(col, rev)
            print(f"blink rank on {name}: {rk.get(BLINK)} of {nn}")
    # correlations across directories
    def corr(a, b):
        pts = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
        if len(pts) < 5:
            return None
        mx = st.mean(p[0] for p in pts)
        my = st.mean(p[1] for p in pts)
        sxy = sum((p[0] - mx) * (p[1] - my) for p in pts)
        sx = math.sqrt(sum((p[0] - mx) ** 2 for p in pts))
        sy = math.sqrt(sum((p[1] - my) ** 2 for p in pts))
        return sxy / sx / sy if sx and sy else None
    print("corr(factor pre, promoted 2020-21):", f2(corr([o[2] for o in out], [o[7] for o in out])))
    print("corr(factor pre, new-reviewer share 2026):", f2(corr([o[2] for o in out], [o[10][3] for o in out])))
    rl = [math.log(ratio[o[0]]) if ratio[o[0]] else None for o in out]
    print("corr(log wait ratio, factor pre):", f2(corr(rl, [o[2] for o in out])))
    print("corr(log wait ratio, <1y÷4y+ pre):", f2(corr(rl, [o[4] for o in out])))
    print("corr(log wait ratio, promoted 2020-21):", f2(corr(rl, [o[7] for o in out])))
    print("corr(log wait ratio, new-reviewer share 2026):", f2(corr(rl, [o[10][3] for o in out])))
    print("corr(log wait ratio, change in new-reviewer share 2024->26):",
          f2(corr(rl, [o[10][3] - o[10][2] if o[10][3] is not None and o[10][2] is not None else None for o in out])))

    # ---------------------------------------------------------- blink drill-down
    print("\n== third_party/blink by year")
    print("year | approvals | approver <3y on project | 3-8y | 8y+ | unknown | distinct approvers (≥10) | top-10 share | "
          "new regular approvers (first year ≥ 25 approvals)")
    per = defaultdict(Counter)
    for (p, d), ts_ in approvals.items():
        if d == BLINK:
            for t in ts_:
                per[year_of(t)][p] += 1
    seen = set()
    for y in range(2018, 2027):
        xs = appr_by_year[BLINK][y]
        known = [x for x in xs if x is not None]
        c = per[y]
        newreg = sum(1 for p, k in c.items() if k >= 25 and p not in seen)
        seen |= {p for p, k in c.items() if k >= 25}
        tot = sum(c.values())
        print(f"{y} | {len(xs)} | {f2(sum(x < 3 for x in known) / len(xs))} | {f2(sum(3 <= x < 8 for x in known) / len(xs))} | "
              f"{f2(sum(x >= 8 for x in known) / len(xs))} | {f2((len(xs) - len(known)) / len(xs))} | "
              f"{sum(1 for k in c.values() if k >= 10)} | {f2(sum(k for _, k in c.most_common(10)) / tot)} | {newreg}")

    # learning curve in blink, by era
    for e in ERAS:
        f, r_, idx, n = learning(rows[e][BLINK])
        print(f"blink {e}: index by dir tenure {[f2(x) for x in idx]} factor {f2(f)} n {n}")

    # First-review wait by the approver's directory tenure and by author's directory tenure, for blink CLs
    # with one non-owner approver.
    def wait(c):
        return (c["first_review_at"] - c["sent_at"]) / 3600 \
            if c["first_review_at"] and c["sent_at"] and c["first_review_at"] >= c["sent_at"] else None
    per_q = defaultdict(lambda: defaultdict(list))
    auth_q = defaultdict(lambda: defaultdict(list))
    mix = defaultdict(Counter)
    load = defaultdict(Counter)           # (period, approver) -> blink approvals that period
    P = {"A": ("2024Q1", "2025Q2"), "B": ("2026Q2", "2026Q4")}

    def period(q):
        for k, (lo, hi) in P.items():
            if lo <= q <= hi:
                return k
    for c in use:
        if c["d2"] != BLINK:
            continue
        pe = period(A.quarter(c["closed_at"]))
        g = by_n.get(c["change_number"])
        if not pe or not g:
            continue
        rv = [r for r in set(g["rbp"]) if r != c["pid"]]
        for r in rv:
            load[pe][r] += 1
        w = wait(c)
        s = start.get((c["pid"], BLINK))
        at = (c["closed_at"] - s) / YEAR if s else None
        ab = "<1y" if at is not None and at < 1 else "1-4y" if at is not None and at < 4 else "4y+"
        if w is not None:
            auth_q[pe][ab].append(w)
        if len(rv) != 1:
            continue
        f = first.get(rv[0])
        t = (c["closed_at"] - f) / YEAR if f else None
        b = "unknown" if t is None else "<3y" if t < 3 else "3-8y" if t < 8 else "8y+"
        mix[pe][b] += 1
        if w is not None:
            per_q[pe][b].append((w, rv[0]))
    print("\nblink, one approver: share of CLs and median first-review wait (h), A = 2024Q1–2025Q2, B = 2026Q2–Q4")
    for b in ("<3y", "3-8y", "8y+", "unknown"):
        na, nb = sum(mix["A"].values()), sum(mix["B"].values())
        print(f"approver {b}: share {f2(mix['A'][b] / na)} -> {f2(mix['B'][b] / nb)}, "
              f"wait p50 {f2(pct([w for w, _ in per_q['A'][b]], .5), 1)} -> {f2(pct([w for w, _ in per_q['B'][b]], .5), 1)}")
    for b in ("<1y", "1-4y", "4y+"):
        na, nb = sum(map(len, auth_q["A"].values())), sum(map(len, auth_q["B"].values()))
        print(f"author {b} in blink: share {f2(len(auth_q['A'][b]) / na)} -> {f2(len(auth_q['B'][b]) / nb)}, "
              f"wait p50 {f2(pct(auth_q['A'][b], .5), 1)} -> {f2(pct(auth_q['B'][b], .5), 1)}")
    # Wait by the approver's blink approval volume that period (per quarter), pooled.
    qn = {"A": 6, "B": 2.4}
    print("by approver's blink approvals per quarter that period:")
    for lo, hi in ((0, 10), (10, 30), (30, 60), (60, 10 ** 9)):
        for pe in ("A", "B"):
            ws = [w for b in per_q[pe] for w, r in per_q[pe][b] if lo <= load[pe][r] / qn[pe] < hi]
            print(f"  {lo}-{hi if hi < 10 ** 9 else '+'} {pe}: n {len(ws)} p50 {f2(pct(ws, .5), 1)}", end="")
        print()
    # Mix-adjusted: B's single-approver CLs given A's waits for the same approver-tenure bin.
    import random
    random.seed(1)
    sim = []
    for b, k in mix["B"].items():
        pool = [w for w, _ in per_q["A"][b]]
        if pool:
            sim += [random.choice(pool) for _ in range(k)]
    allA = [w for b in per_q["A"] for w, _ in per_q["A"][b]]
    allB = [w for b in per_q["B"] for w, _ in per_q["B"][b]]
    print(f"one-approver wait p50 A {f2(pct(allA, .5), 1)}; B with A's waits per approver-tenure bin "
          f"{f2(pct(sim, .5), 1)}; B actual {f2(pct(allB, .5), 1)}")


if __name__ == "__main__":
    main()
