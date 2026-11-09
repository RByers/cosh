"""Who falls behind the typical growth trajectory, and is that changing?
For the Review Balance page's "Growth: the two trajectories" section
(docs/balance.md, section 0).

The page's two clearest growth patterns are the review load index falling
with tenure and review share (approvals ÷ (approvals + CLs authored)) rising
with years since joining. This script measures how often people who still
contribute significantly fall well behind those curves:

- **Review share** (git, 2017 onward): a person-year counts when the person
  joined in 2017 or later, is in year 3 to 9 since joining, and landed 24 or
  more CLs that calendar year (2 a month; 2026 is prorated to the months in
  the data). They are *behind* when their review share is under half the
  pooled median for their year since joining.
- **Review load** (Gerrit, 2023 H2 .. 2026 Q3): a person-half counts when the
  author has 2 or more years of tenure and 12 or more merged, non-mechanical
  CLs in the half-year. Their load index is reviewer threads ÷ the 2023–24
  norm for each CL's size and directory, summed over those CLs. They are
  *behind* when it is 1.5× or more the median for their tenure band, either
  the 2023 H2–2024 median (fixed) or the same half-year's (relative, which
  takes out the 2026 project-wide drop).

Persistence (behind again the next period) separates a lasting gap from
noise. Offline; writes aggregates only (shares and counts per year, half or
band), never anything per person.

  COSH_DATA_DIR=<main>/data/private python3 scripts/balance_behind.py \
      --first-commit F --owners-added F --mech mech.jsonl [--explore] [summaries/balance.json]
"""

import argparse
import json
import math
import os
import pickle
import random
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
MONTH = YEAR / 12

# Review share.
COHORTS = range(2017, 2026)
SHARE_YEARS = range(3, 10)        # years since joining that count
MIN_LANDED = 24                   # CLs landed in the calendar year (prorated for a partial year)
SHARE_FRACTION = 0.5              # behind: under this fraction of the pooled median for the year since joining

# Review load.
LOAD_TENURE = [(24, 48, "2-4 years"), (48, 96, "4-8 years"), (96, 10 ** 9, "8+ years")]   # months
MIN_CLS = 12                      # merged, non-mechanical CLs in the half-year
LOAD_FACTOR = 1.5                 # behind: this many times the band's median or more
REF_HALVES = ("2023H2", "2024H1", "2024H2")
GERRIT_END = datetime(2026, 10, 1, tzinfo=timezone.utc).timestamp()    # whole quarters only
PARTIAL = {"2026H2": 0.5}         # 2026 H2 is July–September: MIN_CLS is prorated
MIN_PEOPLE = 20                   # per published point


def half(t):
    d = datetime.fromtimestamp(t, timezone.utc)
    return f"{d.year}H{1 if d.month <= 6 else 2}"


def next_half(h):
    y, n = int(h[:4]), int(h[-1])
    return f"{y}H2" if n == 1 else f"{y + 1}H1"


def load(args):
    cls, commits, ids, first, owner_at, ai = G.load_all(args)
    mech = mech_set(args.mech)
    last = max(c["at"] for c in commits)
    # --- review share, per person and calendar year.
    authored, given = defaultdict(Counter), defaultdict(Counter)
    for c in commits:
        if not c["n"] or c["is_revert"]:
            continue
        y = A.year(c["at"])
        authored[c["pid"]][y] += 1
        for rv in c["rbp"]:
            if rv != c["pid"]:
                given[rv][y] += 1
    # --- review load, per person and half-year.
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
    load = defaultdict(list)        # (pid, half) -> [(threads, expected)] per CL
    for c in use:
        if c["closed_at"] < GERRIT_END:
            load[(c["pid"], half(c["closed_at"]))].append((c["threads"], c["exp24"]))
    return first, authored, given, load, last


# ------------------------------------------------------------- review share

def share_rows(first, authored, given, last):
    """[(person, calendar year, year since joining, join year, review share)] for counted person-years."""
    last_y = A.year(last)
    frac_last = (datetime.fromtimestamp(last, timezone.utc).month) / 12
    out = []
    for p, t in first.items():
        fy = A.year(t)
        if fy not in COHORTS:
            continue
        for k in SHARE_YEARS:
            y = fy + k - 1
            if y > last_y:
                break
            need = MIN_LANDED * (frac_last if y == last_y else 1)
            a, g = authored[p][y], given[p][y]
            if a >= need:
                out.append((p, y, k, fy, g / (a + g)))
    return out


def share_datasets(rows):
    med = {k: st.median(r[4] for r in rows if r[2] == k) for k in SHARE_YEARS}
    cut = {k: SHARE_FRACTION * m for k, m in med.items()}
    behind = {(r[0], r[1]): r[4] < cut[r[2]] for r in rows}
    mix = Counter(r[2] for r in rows)
    tot = sum(mix.values())
    by_year = []
    for y in sorted({r[1] for r in rows}):
        s = [r for r in rows if r[1] == y]
        # Standardized to the pooled mix of years since joining, so a shift in tenure mix doesn't count.
        rate_k = {k: [behind[(r[0], r[1])] for r in s if r[2] == k] for k in SHARE_YEARS}
        std = sum(mix[k] / tot * (sum(v) / len(v)) for k, v in rate_k.items() if v)
        wt = sum(mix[k] / tot for k, v in rate_k.items() if v)
        prev = [behind[(r[0], y - 1)] for r in s if (r[0], y - 1) in behind and behind[(r[0], r[1])]]
        none = sum(r[4] == 0 for r in s)
        k = sum(behind[(r[0], r[1])] for r in s)
        lo, hi = interval(k, len(s))
        early = [behind[(r[0], r[1])] for r in s if r[2] <= 4]
        late = [behind[(r[0], r[1])] for r in s if r[2] >= 5]
        by_year.append(dict(year=y, people=len(s), behind=round(k / len(s), 4), lo=lo, hi=hi,
                            y3_4=round(sum(early) / len(early), 4) if len(early) >= MIN_PEOPLE else None,
                            y3_4_n=len(early),
                            y5_9=round(sum(late) / len(late), 4) if len(late) >= MIN_PEOPLE else None,
                            y5_9_n=len(late),
                            behind_std=round(std / wt, 4) if wt else None, none=round(none / len(s), 4),
                            p50=round(st.median(r[4] for r in s), 3)))
    # Persistence: behind in year y, still counted in y+1: share behind again, against the base rate.
    stay, base = [], []
    for (p, y), b in behind.items():
        if (p, y + 1) in behind:
            base.append(behind[(p, y + 1)])
            if b:
                stay.append(behind[(p, y + 1)])
    by_k = [dict(year=k, people=mix[k], median=round(med[k], 3), cut=round(cut[k], 3),
                 behind=round(sum(behind[(r[0], r[1])] for r in rows if r[2] == k) / mix[k], 4))
            for k in SHARE_YEARS]
    by_cohort = []
    for fy in COHORTS:
        for k in (3, 5):
            s = [r for r in rows if r[3] == fy and r[2] == k]
            if len(s) >= MIN_PEOPLE:
                by_cohort.append(dict(cohort=fy, year=k, people=len(s),
                                      behind=round(sum(behind[(r[0], r[1])] for r in s) / len(s), 4)))
    # Ever behind, and behind for three counted years in a row, among people counted 3+ years.
    seq = defaultdict(list)
    for (p, y), b in sorted(behind.items()):
        seq[p].append((y, b))
    long_ = [v for v in seq.values() if len(v) >= 3]
    run3 = 0
    for v in long_:
        run = best = 0
        for i, (y, b) in enumerate(v):
            run = 0 if not b else run + 1 if i and y == v[i - 1][0] + 1 else 1
            best = max(best, run)
        run3 += best >= 3
    summary = dict(person_years=len(rows), people=len(seq), behind=round(sum(behind.values()) / len(behind), 4),
                   stay=round(sum(stay) / len(stay), 4), stay_n=len(stay), base=round(sum(base) / len(base), 4),
                   ever=round(sum(any(b for _, b in v) for v in long_) / len(long_), 4),
                   run3=round(run3 / len(long_), 4), long_people=len(long_))
    return dict(behind_share_years=by_k, behind_share_by_year=by_year, behind_share_cohorts=by_cohort,
                behind_share_summary=[summary])


# -------------------------------------------------------------- review load

def band_of(months):
    for lo, hi, name in LOAD_TENURE:
        if lo <= months < hi:
            return name
    return None


def load_rows(first, load):
    """[(person, half, tenure band, person's load index, [(threads, expected)])] for counted person-halves."""
    out = []
    for (p, h), xs in load.items():
        t0 = first.get(p)
        if t0 is None or len(xs) < MIN_CLS * PARTIAL.get(h, 1):
            continue
        y, k = int(h[:4]), int(h[-1])
        mid = datetime(y, 4 if k == 1 else 10, 1, tzinfo=timezone.utc).timestamp()
        b = band_of((mid - t0) / MONTH)
        if b:
            out.append((p, h, b, idx(xs), xs))
    return out


def idx(xs):
    return sum(t for t, _ in xs) / sum(e for _, e in xs)


def null_rate(rows, reps=20, seed=1):
    """Share behind (relative) if each person's CLs were a random draw from their half and tenure band:
    the rate that CL-to-CL noise alone gives."""
    rng = random.Random(seed)
    groups = defaultdict(list)
    for r in rows:
        groups[(r[1], r[2])].append(r)
    hits, tot = Counter(), Counter()
    for _ in range(reps):
        for (h, b), g in groups.items():
            pool = [x for r in g for x in r[4]]
            rng.shuffle(pool)
            i, vals = 0, []
            for r in g:
                n = len(r[4])
                vals.append(idx(pool[i:i + n]))
                i += n
            m = st.median(vals)
            hits[h] += sum(v >= LOAD_FACTOR * m for v in vals)
            tot[h] += len(vals)
    out = {h: hits[h] / tot[h] for h in tot}
    out["all"] = sum(hits.values()) / sum(tot.values())
    return out


def interval(k, n):
    """95% Wilson interval of k / n."""
    if not n:
        return None, None
    z, p = 1.96, k / n
    c = (p + z * z / (2 * n)) / (1 + z * z / n)
    w = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return round(c - w, 4), round(c + w, 4)


def load_datasets(rows):
    null = null_rate(rows)
    ref = {b: st.median(r[3] for r in rows if r[2] == b and r[1] in REF_HALVES) for _, _, b in LOAD_TENURE}
    halves = sorted({r[1] for r in rows})
    same = {(h, b): st.median(r[3] for r in rows if r[1] == h and r[2] == b)
            for h in halves for _, _, b in LOAD_TENURE if any(r[1] == h and r[2] == b for r in rows)}
    fixed = {(r[0], r[1]): r[3] >= LOAD_FACTOR * ref[r[2]] for r in rows}
    rel = {(r[0], r[1]): r[3] >= LOAD_FACTOR * same[(r[1], r[2])] for r in rows}
    out = []
    for h in halves:
        for _, _, b in LOAD_TENURE + [(0, 0, "all")]:
            s = [r for r in rows if r[1] == h and (b == "all" or r[2] == b)]
            if len(s) < MIN_PEOPLE:
                continue
            k = sum(rel[(r[0], r[1])] for r in s)
            lo, hi = interval(k, len(s))
            out.append(dict(half=h, band=b, people=len(s), rel_lo=lo, rel_hi=hi,
                            null=round(null[h], 4) if b == "all" else None,
                            median=round(st.median(r[3] for r in s), 3),
                            behind_fixed=round(sum(fixed[(r[0], r[1])] for r in s) / len(s), 4),
                            behind_rel=round(sum(rel[(r[0], r[1])] for r in s) / len(s), 4)))
    stay, base = [], []
    for (p, h), b in rel.items():
        n = (p, next_half(h))
        if n in rel:
            base.append(rel[n])
            if b:
                stay.append(rel[n])
    summary = dict(person_halves=len(rows), people=len({r[0] for r in rows}),
                   ref_2_4=round(ref["2-4 years"], 3), ref_4_8=round(ref["4-8 years"], 3),
                   ref_8=round(ref["8+ years"], 3),
                   stay=round(sum(stay) / len(stay), 4), stay_n=len(stay), base=round(sum(base) / len(base), 4),
                   behind_rel=round(sum(rel.values()) / len(rel), 4), null=round(null["all"], 4))
    return dict(behind_load=out, behind_load_summary=[summary]), rel


def explore(first, authored, given, rows_load):
    """Checks behind the published figures: thresholds, what moved, and whether the two groups overlap."""
    global MIN_LANDED, SHARE_FRACTION
    keep = MIN_LANDED, SHARE_FRACTION
    print("\nreview share, behind by calendar year (standardized), under other thresholds")
    for ml, fr in ((12, 0.5), (48, 0.5), (24, 1 / 3), (24, 0.75)):
        MIN_LANDED, SHARE_FRACTION = ml, fr
        d = share_datasets(share_rows(first, authored, given, LAST))
        print(f"  landed>={ml} frac={fr:.2f}:", " ".join(f"{r['year']}:{r['behind_std']:.3f}" for r in d["behind_share_by_year"]))
    MIN_LANDED, SHARE_FRACTION = keep
    rows = share_rows(first, authored, given, LAST)
    print("\nreview share, counted person-years: median CLs landed, approvals given, by calendar year and volume")
    for y in sorted({r[1] for r in rows}):
        s = [r for r in rows if r[1] == y]
        a = [authored[r[0]][y] for r in s]
        g = [given[r[0]][y] for r in s]
        big = [r for r in s if authored[r[0]][y] >= 60 * (LAST_FRAC if y == LAST_Y else 1)]
        print(f"  {y}: n={len(s)} landed p50={st.median(a)} given p50={st.median(g)}"
              f" | 60+ landed: n={len(big)} share p50={st.median(r[4] for r in big) if big else '-'}")
    d = share_datasets(rows)
    med = {r["year"]: r["cut"] for r in d["behind_share_years"]}
    beh = {(r[0], r[1]) for r in rows if r[4] < med[r[2]]}
    by_py = defaultdict(list)
    for r in rows_load:
        by_py[(r[0], int(r[1][:4]))].append(r)
    print("\noverlap, 2024–2026: share-behind person-years that also have a load-behind half (relative)")
    same = {}
    for h in {r[1] for r in rows_load}:
        for _, _, b in LOAD_TENURE:
            v = [r[3] for r in rows_load if r[1] == h and r[2] == b]
            if v:
                same[(h, b)] = st.median(v)
    lb = {(r[0], int(r[1][:4])) for r in rows_load if r[3] >= LOAD_FACTOR * same[(r[1], r[2])]}
    for y in (2024, 2025, 2026):
        s = [r for r in rows if r[1] == y and (r[0], y) in by_py]
        b1 = [r for r in s if (r[0], y) in beh]
        b0 = [r for r in s if (r[0], y) not in beh]
        f = lambda xs: sum((r[0], y) in lb for r in xs) / len(xs) if xs else float("nan")
        print(f"  {y}: in both data n={len(s)}; load-behind among share-behind {f(b1):.3f} (n={len(b1)}),"
              f" among others {f(b0):.3f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default="summaries/balance.json")
    ap.add_argument("--first-commit", required=True)
    ap.add_argument("--owners-added", required=True)
    ap.add_argument("--mech", required=True)
    ap.add_argument("--cache", help="pickle of the loaded data, to rerun quickly")
    ap.add_argument("--explore", action="store_true", help="print tables; don't write")
    args = ap.parse_args()
    args.ai_marked = None
    if args.cache and os.path.exists(args.cache):
        first, authored, given, per_half, last = pickle.load(open(args.cache, "rb"))
    else:
        first, authored, given, per_half, last = load(args)
        if args.cache:
            pickle.dump((first, dict(authored), dict(given), dict(per_half), last), open(args.cache, "wb"))
    authored, given = defaultdict(Counter, authored), defaultdict(Counter, given)
    global LAST, LAST_Y, LAST_FRAC
    LAST, LAST_Y = last, A.year(last)
    LAST_FRAC = datetime.fromtimestamp(last, timezone.utc).month / 12
    new = share_datasets(share_rows(first, authored, given, last))
    rows_load = load_rows(first, per_half)
    ld, rel = load_datasets(rows_load)
    new.update(ld)
    for k, v in new.items():
        print(f"\n{k}", file=sys.stderr)
        for r in v:
            print(" ", r, file=sys.stderr)
    if args.explore:
        explore(first, authored, given, rows_load)
        return
    data = json.load(open(args.path))
    data["datasets"].update(new)
    json.dump(data, open(args.path, "w"), separators=(",", ":"))
    open(args.path, "a").write("\n")


if __name__ == "__main__":
    main()
