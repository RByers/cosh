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
- Learning slope (difficulty): the feedback index (reviewer threads ÷
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
import json
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


PAGE_DIRS = ["third_party/blink", "content/browser", "chrome/browser", "chrome/android", "ios/chrome"]
HALF = 182.6 * 86400


def rnd(x, n=2):
    return None if x is None else round(x, n)


def half_of(t):
    d = datetime.fromtimestamp(t, timezone.utc)
    return f"{d.year}H{1 if d.month <= 6 else 2}"


A_PERIOD = ("2024Q1", "2025Q2")       # "then" on the page's queue section
B_PERIOD = ("2026Q2", "2026Q4")       # "since April 2026"; 2026Q4 is partial
QUARTER_DAYS = 365.25 / 4


def load_attention():
    """{change_number: [account_id]} of every non-owner human in a CL's attention set, from balance.sqlite."""
    import sqlite3
    from cosh import balance
    db = sqlite3.connect(f"file:{balance.db_path('cl')}?mode=ro", uri=True)
    att = defaultdict(list)
    for n, a in db.execute("SELECT change_number, account_id FROM cl_attention"):
        att[n].append(a)
    return att


def wait_h(c):
    """Clock hours from being sent for review to the first substantive review, or None."""
    if c["first_review_at"] and c["sent_at"] and c["first_review_at"] >= c["sent_at"]:
        return (c["first_review_at"] - c["sent_at"]) / 3600
    return None


def period_of(q):
    if A_PERIOD[0] <= q <= A_PERIOD[1]:
        return "a"
    if B_PERIOD[0] <= q <= B_PERIOD[1]:
        return "b"
    return None


def period_quarters(use):
    """Quarters in each period, the last one pro rata to the data's last CL, so per-quarter rates compare."""
    last = max(c["closed_at"] for c in use)
    start_b = ts(2026, 4)
    return {"a": 6.0, "b": max(0.5, (last - start_b) / 86400 / QUARTER_DAYS)}


def reviewers_of(c, att):
    return {a for a in att.get(c["change_number"], []) if a != c["owner"]}


def active_per_quarter(cls, att):
    """Mean over the quarters of {quarter: reviewers in the attention set of 5+ of these CLs}, and the set of
    people who were such a reviewer in any quarter."""
    per = defaultdict(Counter)
    for c in cls:
        for a in reviewers_of(c, att):
            per[A.quarter(c["closed_at"])][a] += 1
    counts = [sum(1 for k in x.values() if k >= 5) for x in per.values()]
    people = {a for x in per.values() for a, k in x.items() if k >= 5}
    return (st.mean(counts) if counts else 0), people


def queue_quarters(use, att):
    """Per page directory (and all of Chromium) and quarter: merged CLs, the median first-review wait, and
    reviewers in the attention set of 5+ of the directory's CLs, from balance.sqlite's cl_attention."""
    groups = defaultdict(list)
    for c in use:
        q = A.quarter(c["closed_at"])
        if not ("2023Q3" <= q <= "2026Q3"):
            continue
        groups[("all", q)].append(c)
        if c["d2"] in PAGE_DIRS:
            groups[(c["d2"], q)].append(c)
    out = []
    for (d, q), s in sorted(groups.items()):
        w = [wait_h(c) for c in s]
        rv = Counter(a for c in s for a in reviewers_of(c, att))
        reviewers = sum(1 for k in rv.values() if k >= 5)
        out.append(dict(dir=d, q=q, cls=len(s), ftr_p50=rnd(pct(w, .5)), ftr_p75=rnd(pct(w, .75)), reviewers=reviewers,
                        cls_per_reviewer=rnd(len(s) / reviewers, 1) if reviewers else None,
                        feedback_index=rnd(sum(c["threads"] for c in s) / sum(c["exp24"] for c in s))))
    base = defaultdict(list)
    for o in out:
        if o["q"].startswith("2024"):
            base[o["dir"]].append(o["cls"])
    for o in out:
        o["cls_index"] = rnd(o["cls"] / st.mean(base[o["dir"]]))
    return out


def queue_months(use):
    """All of Chromium by month, 2023-07 to the last complete month: merged CLs, reviewed CLs, and the median
    and upper-quartile first-review wait."""
    last = max(c["closed_at"] for c in use)
    ld = datetime.fromtimestamp(last, timezone.utc)
    last_m = f"{ld.year}-{ld.month:02d}"
    complete = ld.day >= 28            # the data's last month counts only when it is (nearly) complete
    months = defaultdict(list)
    for c in use:
        d = datetime.fromtimestamp(c["closed_at"], timezone.utc)
        m = f"{d.year}-{d.month:02d}"
        if m >= "2023-07" and (m < last_m or complete):
            months[m].append(c)
    out = []
    for m, s in sorted(months.items()):
        w = [wait_h(c) for c in s]
        w = [x for x in w if x is not None]
        out.append(dict(m=m, cls=len(s), reviewed=len(w), ftr_p50=rnd(pct(w, .5)), ftr_p75=rnd(pct(w, .75)),
                        lines_p50=pct([c["lines"] for c in s], .5)))
    return out


def queue_hours(use):
    """All of Chromium: by the UTC hour the CL was sent for review, each period's share of reviewed CLs and
    median wait."""
    by = {"a": defaultdict(list), "b": defaultdict(list)}
    for c in use:
        p = period_of(A.quarter(c["closed_at"]))
        w = wait_h(c)
        if p and w is not None:
            by[p][datetime.fromtimestamp(c["sent_at"], timezone.utc).hour].append(w)
    n = {p: sum(len(v) for v in by[p].values()) for p in by}
    return [dict(hour=h, share_a=rnd(len(by["a"][h]) / n["a"], 4), share_b=rnd(len(by["b"][h]) / n["b"], 4),
                 wait_a=rnd(pct(by["a"][h], .5)), wait_b=rnd(pct(by["b"][h], .5))) for h in range(24)]


def queue_dirs(use, att, min_cls=800):
    """Per 2-level directory with min_cls+ CLs in period A, and all of Chromium: CLs per quarter, median
    wait, active reviewers per quarter (5+ of the directory's CLs in the quarter), CLs per active reviewer,
    the share of B's active reviewers who weren't active there in A (renewal), and the median CL size."""
    nq = period_quarters(use)
    by = defaultdict(lambda: {"a": [], "b": []})
    for c in use:
        p = period_of(A.quarter(c["closed_at"]))
        if p:
            by["all"][p].append(c)
            if c["d2"]:
                by[c["d2"]][p].append(c)
    out = []
    for d, ps in by.items():
        if len(ps["a"]) < min_cls or not ps["b"]:
            continue
        row = dict(dir=d)
        act = {}
        for p in ("a", "b"):
            s = ps[p]
            w = [wait_h(c) for c in s]
            act[p] = active_per_quarter(s, att)
            row[f"cls_q_{p}"] = rnd(len(s) / nq[p], 0)
            row[f"wait_{p}"] = rnd(pct(w, .5))
            row[f"reviewers_{p}"] = rnd(act[p][0], 0)
            row[f"per_reviewer_{p}"] = rnd(len(s) / nq[p] / act[p][0], 1) if act[p][0] else None
            row[f"lines_{p}"] = pct([c["lines"] for c in s], .5)
        row["renewal"] = rnd(len(act["b"][1] - act["a"][1]) / len(act["a"][1]), 3) if act["a"][1] else None
        out.append(row)
    out.sort(key=lambda r: -(r["wait_b"] / r["wait_a"]) if r["wait_a"] and r["wait_b"] else 0)
    return out


def queue_shift(use, att):
    """What the reviewers who were active in a directory in A (5+ of its CLs in some quarter) and still
    reviewed anywhere in B did per quarter in each period: CLs reviewed in the directory, CLs reviewed
    elsewhere, and CLs of their own landed (means per person). dir=all: everyone active as a reviewer in A."""
    nq = period_quarters(use)
    dq = defaultdict(lambda: defaultdict(Counter))       # (period, dir) -> account -> quarter -> CLs
    load = defaultdict(lambda: defaultdict(Counter))     # period -> account -> dir -> CLs
    authored = defaultdict(Counter)
    for c in use:
        p = period_of(A.quarter(c["closed_at"]))
        if not p:
            continue
        authored[p][c["owner"]] += 1
        q = A.quarter(c["closed_at"])
        for a in reviewers_of(c, att):
            load[p][a][c["d2"]] += 1
            dq[(p, c["d2"])][a][q] += 1
            dq[(p, "all")][a][q] += 1
    out = []
    for d in PAGE_DIRS + ["all"]:
        active_a = {a for a, qs in dq[("a", d)].items() if any(k >= 5 for k in qs.values())}
        stay = [a for a in active_a if load["b"].get(a)]
        for p in ("a", "b"):
            tot = [sum(load[p][a].values()) / nq[p] for a in stay]
            ind = [load[p][a][d] / nq[p] for a in stay] if d != "all" else [0.0] * len(stay)
            au = [authored[p][a] / nq[p] for a in stay]
            out.append(dict(dir=d, period=p, people=len(stay), active_a=len(active_a),
                            in_dir=rnd(st.mean(ind), 1), elsewhere=rnd(st.mean(t - i for t, i in zip(tot, ind)), 1),
                            reviewed=rnd(st.mean(tot), 1), reviewed_p50=rnd(pct(tot, .5), 1),
                            authored=rnd(st.mean(au), 1), authored_p50=rnd(pct(au, .5), 1)))
    return out


def queue_mix(use, att):
    """All of Chromium: B's reviewed CLs given A's waits for CLs of the same size band, hour band sent,
    reviewers in the attention set and owner org group (Google or not), and for size alone."""
    import random
    from cosh import orgs
    resolve = orgs.OrgResolver()

    def size_band(l):
        return 0 if l < 10 else 1 if l < 50 else 2 if l < 200 else 3 if l < 1000 else 4

    def hour_band(t):
        d = datetime.fromtimestamp(t, timezone.utc)
        return "wknd" if d.weekday() >= 5 else "us" if 14 <= d.hour < 22 else "eu" if 6 <= d.hour < 14 else "night"

    def google(c):
        day = datetime.fromtimestamp(c["closed_at"], timezone.utc).strftime("%Y-%m-%d")
        return resolve(c["owner_email"], day) == "google.com"

    keys = {"size": lambda c: size_band(c["lines"]),
            "mix": lambda c: (size_band(c["lines"]), hour_band(c["sent_at"]), min(len(reviewers_of(c, att)), 3), google(c))}
    random.seed(1)
    row = {}
    for name, kf in keys.items():
        pool, ks = defaultdict(list), []
        for c in use:
            p = period_of(A.quarter(c["closed_at"]))
            w = wait_h(c)
            if not p or w is None:
                continue
            if p == "a":
                pool[kf(c)].append(w)
            else:
                ks.append(kf(c))
        sim = [random.choice(pool[k]) for k in ks if pool.get(k)]
        row[f"wait_b_{name}"] = rnd(pct(sim, .5))
        row[f"matched_{name}"] = rnd(len(sim) / len(ks), 3)
    wa = [wait_h(c) for c in use if period_of(A.quarter(c["closed_at"])) == "a"]
    wb = [wait_h(c) for c in use if period_of(A.quarter(c["closed_at"])) == "b"]
    row["wait_a"] = rnd(pct(wa, .5))
    row["wait_b"] = rnd(pct(wb, .5))
    # Owner org groups: share of reviewed CLs and median wait.
    g = {"a": defaultdict(list), "b": defaultdict(list)}
    for c in use:
        p = period_of(A.quarter(c["closed_at"]))
        w = wait_h(c)
        if p and w is not None:
            g[p]["google" if google(c) else "other"].append(w)
    for p in ("a", "b"):
        n = sum(len(v) for v in g[p].values())
        for k in ("google", "other"):
            row[f"share_{k}_{p}"] = rnd(len(g[p][k]) / n, 3)
            row[f"wait_{k}_{p}"] = rnd(pct(g[p][k], .5))
    return [row]


def queue_summary(quarters):
    """One row for the page's tiles: 2024's quarterly average against 2026Q3 for all of Chromium, with the
    change as a log ratio (the page formats it as a percentage)."""
    rows = [r for r in quarters if r["dir"] == "all"]
    then = [r for r in rows if r["q"].startswith("2024")]
    now = next(r for r in rows if r["q"] == "2026Q3")
    out = {}
    for f in ("cls", "reviewers", "cls_per_reviewer", "ftr_p50", "feedback_index"):
        a = st.mean(r[f] for r in then)
        out[f"{f}_then"] = rnd(a, 2 if f in ("feedback_index", "ftr_p50") else 0)
        out[f"{f}_now"] = now[f]
        out[f"{f}_rel"] = rnd(math.log(now[f] / a), 4)
    return [out]


def inflow(commits, cdir, first, authored, start):
    """Per directory and half-year: people arriving (first commit there, and 3+ commits there within 120
    days), split into new to Chromium (first commit anywhere within the half-year before) and moving in
    from elsewhere, against active authors (3+ commits there that half). Also for Googlers only: the org
    of the arriving commit's author email (cosh.orgs: chromium.org counts as Google unless the
    affiliations file says otherwise)."""
    import sqlite3
    from cosh import balance, orgs
    resolve = orgs.OrgResolver()
    db = sqlite3.connect(f"file:{balance.db_path('git')}?mode=ro", uri=True)
    raw = dict(db.execute("SELECT commit_id, author_email FROM gcommits"))
    ats = {}
    active = defaultdict(lambda: defaultdict(Counter))     # d -> half -> pid -> commits
    goog_half = {}
    for c in sorted(commits, key=lambda c: c["at"]):
        d = cdir.get(c["cid"])
        if d not in PAGE_DIRS:
            continue
        h = half_of(c["at"])
        active[d][h][c["pid"]] += 1
        k = (d, h, c["pid"])
        if k not in goog_half:
            day = datetime.fromtimestamp(c["at"], timezone.utc).strftime("%Y-%m-%d")
            goog_half[k] = resolve(raw.get(c["cid"]), day) == "google.com"
            if (c["pid"], d) not in ats:
                ats[(c["pid"], d)] = goog_half[k]
    rows = defaultdict(Counter)
    for (p, d), s in start.items():
        if d not in PAGE_DIRS or s < ts(2017, 7):
            continue
        if sum(1 for t in authored[(p, d)] if t < s + 120 * 86400) < 3:
            continue
        h = half_of(s)
        new = first.get(p, 0) >= s - HALF
        g = ats.get((p, d), False)
        rows[(d, h)]["arrivals"] += 1
        rows[(d, h)]["arrivals_new"] += new
        rows[(d, h)]["g_arrivals"] += g
        rows[(d, h)]["g_arrivals_new"] += g and new
    out = []
    for d in PAGE_DIRS:
        for y in range(2018, 2027):
            for hh in (1, 2):
                h = f"{y}H{hh}"
                if h > "2026H1":
                    continue
                act = [p for p, k in active[d][h].items() if k >= 3]
                g_act = [p for p in act if goog_half.get((d, h, p))]
                x = rows[(d, h)]
                out.append(dict(dir=d, half=h, active=len(act), g_active=len(g_act), **{k: x[k] for k in (
                    "arrivals", "arrivals_new", "g_arrivals", "g_arrivals_new")},
                    rate=rnd(x["arrivals"] / len(act), 3) if act else None,
                    rate_new=rnd(x["arrivals_new"] / len(act), 3) if act else None,
                    g_rate=rnd(x["g_arrivals"] / len(g_act), 3) if g_act else None,
                    g_rate_new=rnd(x["g_arrivals_new"] / len(g_act), 3) if g_act else None))
    return out


def inflow_periods(rows):
    """queue_inflow summed over 2020–22, 2023–24 and 2025 to 2026 H1: rates are arrivals per half-year per
    100 active authors."""
    by = defaultdict(Counter)
    for o in rows:
        h = o["half"]
        per = "2020-22" if "2020" <= h < "2023" else "2023-24" if "2023" <= h < "2025" else "2025-26" if h >= "2025" else None
        if per:
            for k in ("active", "g_active", "arrivals", "arrivals_new", "g_arrivals", "g_arrivals_new"):
                by[(o["dir"], per)][k] += o[k]
    return [dict(dir=d, period=per, arrivals=x["arrivals"], non_google=rnd(1 - x["g_arrivals"] / x["arrivals"], 3),
                 google_active=rnd(x["g_active"] / x["active"], 3),
                 rate=rnd(x["arrivals"] / x["active"], 3), rate_new=rnd(x["arrivals_new"] / x["active"], 3),
                 g_rate=rnd(x["g_arrivals"] / x["g_active"], 3), g_rate_new=rnd(x["g_arrivals_new"] / x["g_active"], 3))
            for (d, per), x in sorted(by.items())]


def print_queues(new):
    print("\n== Queue summary (2024 average -> 2026Q3):", new["queue_summary"][0])
    print("== Mix-adjusted wait:", new["queue_mix"][0])
    print("== Months: m, CLs, reviewed, p50, p75, lines p50")
    for r in new["queue_months"]:
        print(f"  {r['m']} {r['cls']} {r['reviewed']} {f2(r['ftr_p50'])} {f2(r['ftr_p75'], 1)} {r['lines_p50']}")
    print("== Hours (UTC): share a, b; wait a, b")
    for r in new["queue_hours"]:
        print(f"  {r['hour']:02d} {r['share_a']:.3f} {r['share_b']:.3f} {f2(r['wait_a'])} {f2(r['wait_b'])}")
    print("== Directories: CLs/q a, b; wait a, b; reviewers/q a, b; per reviewer a, b; renewal; lines a, b")
    for r in new["queue_dirs"]:
        print(f"  {r['dir']:26s} {r['cls_q_a']:6.0f} {r['cls_q_b']:6.0f}  {f2(r['wait_a'], 1)} {f2(r['wait_b'], 1)}  "
              f"{r['reviewers_a']:5.0f} {r['reviewers_b']:5.0f}  {f2(r['per_reviewer_a'], 1)} {f2(r['per_reviewer_b'], 1)}  "
              f"{f2(r['renewal'])}  {r['lines_a']} {r['lines_b']}")
    print("== Stayers per quarter: dir, period, people, in dir, elsewhere, reviewed (median), authored (median)")
    for r in new["queue_shift"]:
        print(f"  {r['dir']:26s} {r['period']} {r['people']:4d}/{r['active_a']:4d}  {r['in_dir']:5.1f} {r['elsewhere']:5.1f}  "
              f"{r['reviewed']:5.1f} ({r['reviewed_p50']:.1f})  {r['authored']:5.1f} ({r['authored_p50']:.1f})")


def print_inflow(rows):
    print("\n== Arrivals per 100 active authors, by year (all | Google), new to Chromium in brackets")
    by = defaultdict(lambda: defaultdict(Counter))
    for o in rows:
        y = o["half"][:4]
        for k in ("active", "g_active", "arrivals", "arrivals_new", "g_arrivals", "g_arrivals_new"):
            by[o["dir"]][y][k] += o[k]
    for d, ys in by.items():
        cells = []
        for y, x in sorted(ys.items()):
            a = x["active"] or 1
            ga = x["g_active"] or 1
            cells.append(f"{y}: {100 * x['arrivals'] / a:.0f} ({100 * x['arrivals_new'] / a:.0f}) | "
                         f"{100 * x['g_arrivals'] / ga:.0f} ({100 * x['g_arrivals_new'] / ga:.0f}) n{x['active']}")
        print(d, "\n  " + "\n  ".join(cells))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", help="summaries/balance.json to add the page's datasets to")
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

    # ---------------------------------------------------------- the page's datasets
    new = {}
    new["queue_learning"] = [
        dict(dir=d, era=e, bin=i, feedback_index=rnd(learning(rows[e][d])[2][i]))
        for d in PAGE_DIRS for e in ERAS for i in range(len(BINS))]
    new["queue_growth"] = []
    for o in out:
        if o[0] in PAGE_DIRS:
            new["queue_growth"].append(dict(dir=o[0], factor_pre=rnd(o[2]), factor_now=rnd(o[3]), ratio_pre=rnd(o[4]),
                                            ratio_now=rnd(o[5]), promoted_1719=rnd(o[6]), promoted_2021=rnd(o[7]),
                                            wait_a=rnd(pct(wa[o[0]], .5)), wait_b=rnd(pct(wb[o[0]], .5))))
    new["queue_openness"] = []
    for d in PAGE_DIRS:
        for y in range(2018, 2027):
            sh, n = new_share(d, y)
            new["queue_openness"].append(dict(dir=d, year=y, new_reviewer_share=rnd(sh, 3), approvals=n))
    new["queue_approver"] = []
    for b in ("<3y", "3-8y", "8y+"):
        row = dict(bin=b)
        for pe in ("A", "B"):
            row[f"share_{pe.lower()}"] = rnd(mix[pe][b] / sum(mix[pe].values()), 3)
            row[f"wait_{pe.lower()}"] = rnd(pct([w for w, _ in per_q[pe][b]], .5))
        new["queue_approver"].append(row)
    new["queue_blink"] = [dict(wait_a=rnd(pct(allA, .5)), wait_b=rnd(pct(allB, .5)), wait_b_mix=rnd(pct(sim, .5)))]
    att = load_attention()
    new["queue_quarters"] = queue_quarters(use, att)
    new["queue_summary"] = queue_summary(new["queue_quarters"])
    new["queue_months"] = queue_months(use)
    new["queue_hours"] = queue_hours(use)
    new["queue_dirs"] = queue_dirs(use, att, min_cls=800)
    new["queue_shift"] = queue_shift(use, att)
    new["queue_mix"] = queue_mix(use, att)
    print_queues(new)
    new["queue_inflow"] = inflow(commits, cdir, first, authored, start)
    new["queue_inflow_periods"] = inflow_periods(new["queue_inflow"])
    print_inflow(new["queue_inflow"])
    if args.path:
        data = json.load(open(args.path))
        data["datasets"].update(new)
        json.dump(data, open(args.path, "w"), separators=(",", ":"))
        open(args.path, "a").write("\n")


if __name__ == "__main__":
    main()
