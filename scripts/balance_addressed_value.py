"""Is the addressed index a better predictor of review value than the feedback index?
(docs/balance-addressed.md)

The balance work measures review received by the *feedback index*: reviewer
threads on a CL ÷ the 2023–24 mean for its size and 2-level directory. The
Value Exchange classifier (`cosh classify`: regex plus Haiku) also says
which of those threads the author *addressed* (changed something). This
script builds the *addressed index* the same way (addressed threads ÷ the
2023–24 mean addressed threads for the size and directory), and an
*unaddressed index* for the rest, and races them against the feedback index
on every outcome of review value the data has:

`cl` (per CL, from the review-ROI table, `scripts/review_roi_table.py`):

- learning gradients: each index by author tenure and by practice in the
  directory (2023 H2–2024, and 2026), with the newcomer ÷ veteran ratio and
  an author-clustered bootstrap interval;
- direct value: lines changed after the first review (interdiff share),
  rounds, and 30-day reverts, within size × dir2 × half-year strata,
  per doubling of threads, of addressed threads, and of both split.

`blame` (reuses the review-ROI blame pilots' samples, `scripts/review_roi_blame.py`):

- CLs whose lines a later bug fix rewrote (SZZ), against their stratum;
- share of a CL's added lines still alive a year later.

`people` (per author half-year, as in `scripts/balance_feedback_predicts.py`):

- split-half reliability of each index;
- the next half-year's feedback index (persistence or learning);
- first OWNERS addition within 18 months, review share and threads given
  over the next 12 months.

Offline; prints aggregates and coefficients only, never anything per person.

  export COSH_DATA_DIR=/home/rbagent/projects/cosh/data/private
  python3 scripts/balance_addressed_value.py cl --table cl_table.sqlite [--out cl.json]
  python3 scripts/balance_addressed_value.py blame --table cl_table.sqlite --blame-dir S [--out blame.json]
  python3 scripts/balance_addressed_value.py people --first-commit F --owners-added O --mech M \
      [--cache P] [--out people.json]
"""

import argparse
import json
import math
import os
import pickle
import random
import sqlite3
import statistics as st
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import balance_feedback_predicts as FP  # noqa: E402
import balance_growth as G  # noqa: E402

FLOOR = 1 / 16
BOOT = 200
MIN_NORM_N = 30


def log2f(x):
    return math.log2(max(x, FLOOR))


def norms(rows, key, ref):
    """2023–24 mean of `key` per (size10, dir2) with >= 30 CLs, else per size10."""
    g, b = defaultdict(lambda: [0, 0.0]), defaultdict(lambda: [0, 0.0])
    for r in rows:
        if ref(r):
            for d, k in ((g, (r["size10"], r["dir2"])), (b, r["size10"])):
                d[k][0] += 1
                d[k][1] += r[key]
    for r in rows:
        x = g.get((r["size10"], r["dir2"]))
        if not x or x[0] < MIN_NORM_N:
            x = b.get(r["size10"])
        r["exp_" + key] = x[1] / x[0] if x and x[0] else 0.0


# ======================================================================= cl

def load_table(path):
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    rows = [dict(r) for r in db.execute(
        "SELECT change_number, author_id, half, era, size10, dir2, tenure_band, practice_band, author_tenure_m, "
        "author_prior_commits, author_practice3, threads, addressed, exp24, rounds, interdiff_share, rev30 FROM cl")]
    for r in rows:
        r["unaddressed"] = r["threads"] - r["addressed"]
    ref = lambda r: r["half"] in ("2023H2", "2024H1", "2024H2")
    norms(rows, "addressed", ref)
    norms(rows, "unaddressed", ref)
    return rows


TEN = [(0, 3, "0-3 mo"), (3, 6, "3-6 mo"), (6, 12, "6-12 mo"), (12, 24, "1-2 y"), (24, 60, "2-5 y"),
       (60, 120, "5-10 y"), (120, 10 ** 9, "10+ y")]
PRAC = [(0, 1, "0"), (1, 5, "1-4"), (5, 20, "5-19"), (20, 100, "20-99"), (100, 10 ** 9, "100+")]


def binof(v, bins):
    if v is None:
        return None
    for lo, hi, name in bins:
        if lo <= v < hi:
            return name
    return None


IDX = (("feedback", "threads", "exp24"), ("addressed", "addressed", "exp_addressed"),
       ("unaddressed", "unaddressed", "exp_unaddressed"))


def ratios(rs):
    out = {}
    for name, k, e in IDX:
        se = sum(r[e] for r in rs)
        out[name] = sum(r[k] for r in rs) / se if se else None
    t = sum(r["threads"] for r in rs)
    out["addressed_share"] = sum(r["addressed"] for r in rs) / t if t else None
    return out


def gradients(rows, era_halves, var, bins, label):
    rs = [r for r in rows if r["half"] in era_halves]
    by = defaultdict(list)
    for r in rs:
        b = binof(r[var], bins)
        if b:
            by[b].append(r)
    names = [n for _, _, n in bins if n in by]
    table = []
    for n in names:
        table.append(dict(gradient=label, bin=n, cls=len(by[n]),
                          **{k: round(v, 3) if v is not None else None for k, v in ratios(by[n]).items()}))
    first, last = names[0], names[-1]

    def steep(cells):
        a, b = ratios(cells[first]), ratios(cells[last])
        return {k: a[k] / b[k] for k in ("feedback", "addressed", "unaddressed")}

    point = steep(by)
    # Author-clustered bootstrap of the first ÷ last ratio, and of addressed ÷ feedback steepness.
    auth = defaultdict(lambda: defaultdict(list))
    for n in (first, last):
        for r in by[n]:
            auth[r["author_id"]][n].append(r)
    keys = list(auth)
    rnd = random.Random(7)
    boots = []
    for _ in range(BOOT):
        cells = defaultdict(list)
        for a in (rnd.choice(keys) for _ in keys):
            for n, xs in auth[a].items():
                cells[n].extend(xs)
        if cells[first] and cells[last]:
            s = steep(cells)
            s["a_over_f"] = s["addressed"] / s["feedback"]
            boots.append(s)

    def ci(k):
        v = sorted(b[k] for b in boots)
        return [round(v[int(0.025 * len(v))], 3), round(v[int(0.975 * len(v)) - 1], 3)]

    steepness = dict(gradient=label, first=first, last=last,
                     **{k: round(v, 3) for k, v in point.items()},
                     **{k + "_ci": ci(k) for k in ("feedback", "addressed", "unaddressed")},
                     a_over_f=round(point["addressed"] / point["feedback"], 3), a_over_f_ci=ci("a_over_f"))
    return table, steepness


def demean(rows, cols, stratum):
    """Within-stratum deviations of each column (fixed effects)."""
    s = defaultdict(lambda: [0, [0.0] * len(cols)])
    for r in rows:
        x = s[stratum(r)]
        x[0] += 1
        for i, c in enumerate(cols):
            x[1][i] += r[c]
    out = []
    for r in rows:
        x = s[stratum(r)]
        out.append([r[c] - x[1][i] / x[0] for i, c in enumerate(cols)])
    return out


def within_fit(rows, y, xs, stratum):
    """OLS on within-stratum deviations; author-clustered SEs; within R²."""
    d = demean(rows, [y] + xs, stratum)
    Y = [v[0] for v in d]
    X = [v[1:] for v in d]
    beta, se = FP.ols(X, Y, [r["author_id"] for r in rows])
    sst = sum(v * v for v in Y)
    ssr = sum((yi - sum(b * xi for b, xi in zip(beta, x))) ** 2 for x, yi in zip(X, Y))
    return dict(beta=[round(b, 5) for b in beta], ci=[[round(b - 1.96 * s, 5), round(b + 1.96 * s, 5)]
                                                       for b, s in zip(beta, se)],
                within_r2=round(1 - ssr / sst, 5) if sst else None)


def direct(rows):
    for r in rows:
        r["lt"] = math.log2(1 + r["threads"])
        r["la"] = math.log2(1 + r["addressed"])
        r["lu"] = math.log2(1 + r["unaddressed"])
        r["ashare"] = r["addressed"] / r["threads"] if r["threads"] else 0.0
        r["ish"] = min(2.0, r["interdiff_share"]) if r["interdiff_share"] is not None else None
        r["rev"] = 100.0 * r["rev30"]          # points
    stratum = lambda r: (r["size10"], r["dir2"], r["half"])
    out = []
    for outcome, sel, unit in (("ish", lambda r: r["ish"] is not None, "share of final lines"),
                               ("rounds", lambda r: r["rounds"] is not None, "rounds"),
                               ("rev", lambda r: True, "points of 30-day revert rate")):
        for sub, cond in (("all", lambda r: True), ("1+ thread", lambda r: r["threads"] > 0)):
            rs = [r for r in rows if sel(r) and cond(r)]
            res = dict(outcome=outcome, unit=unit, subset=sub, n=len(rs),
                       mean=round(st.mean(r[outcome] for r in rs), 4))
            for name, xs in (("threads", ["lt"]), ("addressed", ["la"]), ("unaddressed", ["lu"]),
                             ("addressed+unaddressed", ["la", "lu"]),
                             ("threads+addressed share", ["lt", "ashare"])):
                res[name] = within_fit(rs, outcome, xs, stratum)
            out.append(res)
            print(f"  direct {outcome} {sub}: {json.dumps(res)}", file=sys.stderr, flush=True)
    return out


def run_cl(args):
    rows = load_table(args.table)
    print(f"cl: {len(rows):,} unit CLs", file=sys.stderr)
    base = ("2023H2", "2024H1", "2024H2")
    now = ("2026H1", "2026H2")
    tables, steeps = [], []
    for era, hs in (("2023H2-2024", base), ("2026", now)):
        for var, bins, label in (("author_tenure_m", TEN, "tenure"), ("author_practice3", PRAC, "practice")):
            t, s = gradients(rows, hs, var, bins, label)
            for x in t + [s]:
                x["era"] = era
            tables += t
            steeps.append(s)
            print(f"  steepness {era} {label}: {s}", file=sys.stderr, flush=True)
    res = dict(gradient_bins=tables, gradient_steepness=steeps, direct=direct(rows),
               totals=dict(cls=len(rows), threads=sum(r["threads"] for r in rows),
                           addressed=sum(r["addressed"] for r in rows),
                           with_thread=sum(r["threads"] > 0 for r in rows),
                           with_addressed=sum(r["addressed"] > 0 for r in rows)))
    return res


# ==================================================================== blame

def run_blame(args):
    """Reuse the review-ROI blame pilots (scripts/review_roi_blame.py): CLs whose
    lines a later bug fix rewrote (SZZ), and share of added lines alive a year
    later. Each CL against the mean of unit CLs in its size × dir2 × half-year."""
    rows = load_table(args.table)
    for r in rows:
        r["lt"] = math.log2(1 + r["threads"])
        r["la"] = math.log2(1 + r["addressed"])
        r["lu"] = math.log2(1 + r["unaddressed"])
        r["fi"] = r["threads"] / r["exp24"] if r["exp24"] else None
        r["ai"] = r["addressed"] / r["exp_addressed"] if r["exp_addressed"] else None
    db = sqlite3.connect(f"file:{args.table}?mode=ro", uri=True)
    by_sha = {s: (n, at) for n, s, at in db.execute("SELECT change_number, sha, landed_at FROM cl")}
    by_n = {r["change_number"]: r for r in rows}
    stratum = lambda r: (r["size10"], r["dir2"], r["half"])
    cols = ("lt", "la", "lu", "fi", "ai")
    sm = defaultdict(lambda: defaultdict(list))
    for r in rows:
        for c in cols:
            if r[c] is not None:
                sm[stratum(r)][c].append(r[c])
    mean = {k: {c: (sum(v) / len(v), len(v)) for c, v in d.items()} for k, d in sm.items()}

    def dev(r, c):
        m, n = mean[stratum(r)].get(c, (None, 0))
        if r[c] is None or n < 2:
            return None
        return (r[c] - (m * n - r[c]) / (n - 1))          # leave this CL out of its stratum mean

    rnd = random.Random(11)
    out = {}
    induced = set()
    for line in open(os.path.join(args.blame_dir, "szz_items.jsonl")):
        x = json.loads(line)
        for sha in x["blamed"]:
            if sha in by_sha and by_sha[sha][1] < x["created"]:     # landed before the fix was written
                induced.add(by_sha[sha][0])
    ind = [by_n[n] for n in induced if n in by_n]
    res = dict(n=len(ind))
    for c in cols:
        d = [x for x in (dev(r, c) for r in ind) if x is not None]
        bs = sorted(st.mean(rnd.choices(d, k=len(d))) for _ in range(2000))
        res[c] = [round(st.mean(d), 3), round(bs[50], 3), round(bs[1949], 3), round(st.pstdev(d), 3)]
    out["szz_induced_minus_stratum"] = res
    surv = []
    for line in open(os.path.join(args.blame_dir, "survival_items.jsonl")):
        x = json.loads(line)
        r = by_n.get(x["n"])
        if r and x.get("added"):
            surv.append((r, x["alive"] / x["added"]))
    res = dict(n=len(surv))
    for c in cols:
        pr = [(dev(r, c), s) for r, s in surv if dev(r, c) is not None]
        a, b = zip(*pr)
        cc = st.correlation(a, b)
        idx = list(range(len(pr)))
        bs = []
        for _ in range(2000):
            k = rnd.choices(idx, k=len(idx))
            try:
                bs.append(st.correlation([a[i] for i in k], [b[i] for i in k]))
            except st.StatisticsError:
                pass
        bs.sort()
        res[c] = [round(cc, 3), round(bs[int(0.025 * len(bs))], 3), round(bs[int(0.975 * len(bs)) - 1], 3)]
    out["survival_corr_with_stratum_deviation"] = res
    print(json.dumps(out, indent=1), file=sys.stderr)
    return out


# =================================================================== people

def load(args):
    # A copy of FP.load that keeps addressed threads too (FP keeps (threads, exp24) only).
    import balance_analysis as A
    from balance_report import mech_set
    from cosh import store
    cls, commits, ids, first, owner_at, _ = G.load_all(args)
    mech = mech_set(args.mech)
    authored, given = defaultdict(list), defaultdict(list)
    for c in commits:
        if not c["n"] or c["is_revert"]:
            continue
        authored[c["pid"]].append(c["at"])
        for rv in set(c["rbp"]):
            if rv != c["pid"]:
                given[rv].append(c["at"])
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
    for c in use:
        c["size10"], c["dir2"] = c["sb"], c["d2"]
        c["addressed"] = c["addressed"] or 0
        c["unaddressed"] = c["threads"] - c["addressed"]
    ref = lambda c: A.year(c["closed_at"]) in (2023, 2024)
    norms(use, "addressed", ref)
    norms(use, "unaddressed", ref)
    fb = defaultdict(list)
    for c in sorted(use, key=lambda c: c["closed_at"]):
        if c["closed_at"] < FP.GERRIT_END:
            fb[(c["pid"], G.half(c["closed_at"]))].append(
                (c["threads"], c["exp24"], c["addressed"], c["exp_addressed"], c["unaddressed"],
                 c["exp_unaddressed"]))
    d = A.ro(os.path.join(store.DATA_DIR, store.DERIVED_FILE))
    emails = dict(d.execute("SELECT account_id, email FROM accounts"))
    bots = {a for a, in d.execute("SELECT account_id FROM accounts WHERE is_bot = 1")}
    by_n = {c["change_number"]: c for c in cls if c["status"] in ("MERGED", "MECH") and c["closed_at"]}
    pid_of, thr = {}, defaultdict(list)
    for n, acct in d.execute("SELECT change_number, root_account FROM threads"):
        c = by_n.get(n)
        if not c or acct in bots or acct == c["owner"]:
            continue
        e = emails.get(acct)
        if not e or A.is_bot_email(e):
            continue
        p = pid_of[acct] if acct in pid_of else pid_of.setdefault(acct, ids.find(A.person(e)))
        if p != c["pid"]:
            thr[p].append(c["closed_at"])
    return first, owner_at, dict(fb), dict(authored), dict(given), dict(thr)


def ix(xs, i):
    e = sum(x[i + 1] for x in xs)
    return sum(x[i] for x in xs) / e if e > 0 else None


def person_rows(first, owner_at, fb, authored, given, thr):
    # FP.rows_of on (threads, exp24) gives the base rows; add the other indices to each.
    slim = {k: [(x[0], x[1]) for x in v] for k, v in fb.items()}
    rows = FP.rows_of(first, owner_at, slim, authored, given, thr)
    halves = {(p, G.half_name(h)): h for p, h in fb}
    med = defaultdict(lambda: defaultdict(list))
    for r in rows:
        xs = fb[(r["p"], halves[(r["p"], r["h"])])]
        r["ai"], r["ui"] = ix(xs, 2), ix(xs, 4)
        t = sum(x[0] for x in xs)
        r["ash"] = sum(x[2] for x in xs) / t if t else None
        for k, i in (("ai", 2), ("ui", 4), ("fi", 0)):
            r[k + "_odd"], r[k + "_even"] = ix(xs[0::2], i), ix(xs[1::2], i)
        nxt = fb.get((r["p"], halves[(r["p"], r["h"])] + 1), [])
        en = sum(x[1] for x in nxt)
        r["fi_next"] = ix(nxt, 0) if len(nxt) >= 3 and en >= 1.5 else None
        r["ai_next"] = ix(nxt, 2) if len(nxt) >= 3 and en >= 1.5 else None
        for k in ("ai", "ui"):
            med[k][(r["h"], r["band"])].append(r[k] or 0.0)
    for k in ("ai", "ui"):
        m = {g: st.median(v) for g, v in med[k].items()}
        for r in rows:
            r["l" + k] = log2f((r[k] or 0.0) / max(m[(r["h"], r["band"])], 1e-9))
    for r in rows:
        r["lfi"] = r["lrel"]
    return rows


def reliability(rows):
    out = {}
    for k in ("fi", "ai", "ui"):
        pr = [(log2f(r[k + "_odd"]), log2f(r[k + "_even"])) for r in rows
              if r[k + "_odd"] is not None and r[k + "_even"] is not None]
        c = st.correlation(*zip(*pr))
        out[k] = dict(pairs=len(pr), r=round(c, 3), spearman_brown=round(2 * c / (1 + c), 3))
    return out


MODELS = (("feedback", ["lfi"]), ("addressed", ["lai"]), ("addressed+unaddressed", ["lai", "lui"]))


def people_fits(rows):
    """Each outcome, with the 'full' controls of FP.fits, under each index model."""
    out = []
    groups = {"all": rows, "under 2 years": [r for r in rows if r["band"] in FP.BANDS[:2]]}
    for gname, rs in groups.items():
        outcomes = [
            ("owners", [r for r in rs if not r["owner_before"]], lambda r: 1.0 if r["owner"] else 0.0, "logit",
             [("share_h", lambda r: r["share_h"]), ("log2_thr_h", lambda r: math.log2(1 + r["thr_h"]))]),
            ("review_share", [r for r in rs if r["share_next"] is not None], lambda r: r["share_next"], "ols",
             [("share_h", lambda r: r["share_h"])]),
            ("threads_given", rs, lambda r: math.log2(1 + r["thr_next"]), "ols",
             [("log2_thr_h", lambda r: math.log2(1 + r["thr_h"]))]),
            ("feedback_next", [r for r in rs if r["fi_next"] is not None], lambda r: log2f(r["fi_next"]), "ols", []),
            ("addressed_next", [r for r in rs if r["fi_next"] is not None], lambda r: log2f(r["ai_next"] or 0),
             "ols", []),
        ]
        for oname, sub, yf, kind, extra in outcomes:
            y = [yf(r) for r in sub]
            g = [r["p"] for r in sub]
            res = dict(group=gname, outcome=oname, n=len(sub), people=len(set(g)))
            _, X0 = FP.design(sub, extra, with_fi=False)
            if kind == "logit":
                _, _, p0 = FP.logit(X0, y, g)
                res["auc_controls"] = round(FP.auc(p0, y), 4)
            else:
                b0, _ = FP.ols(X0, y, g)
                res["r2_controls"] = round(r2(X0, y, b0), 4)
            for mname, cols in MODELS:
                X = [[x[0]] + [r[c] for c in cols] + x[1:] for x, r in zip(X0, sub)]
                if kind == "logit":
                    beta, se, p = FP.logit(X, y, g)
                    fx = lambda b: round(math.exp(b), 3)
                    m = dict(auc=round(FP.auc(p, y), 4))
                else:
                    beta, se = FP.ols(X, y, g)
                    fx = lambda b: round(b, 4)
                    m = dict(r2=round(r2(X, y, beta), 4))
                for i, c in enumerate(cols, 1):
                    m[c] = [fx(beta[i]), fx(beta[i] - 1.96 * se[i]), fx(beta[i] + 1.96 * se[i])]
                res[mname] = m
            out.append(res)
            print(f"  {gname} {oname}: {json.dumps(res)}", file=sys.stderr, flush=True)
    return out


def r2(X, y, beta):
    m = st.mean(y)
    sst = sum((v - m) ** 2 for v in y)
    ssr = sum((v - sum(b * xi for b, xi in zip(beta, x))) ** 2 for x, v in zip(X, y))
    return 1 - ssr / sst if sst else 0.0


def run_people(args):
    args.ai_marked = None
    if args.cache and os.path.exists(args.cache):
        loaded = pickle.load(open(args.cache, "rb"))
    else:
        loaded = load(args)
        if args.cache:
            pickle.dump(loaded, open(args.cache, "wb"))
    rows = person_rows(*loaded)
    corr = st.correlation([r["lfi"] for r in rows], [r["lai"] for r in rows])
    summ = dict(person_halves=len(rows), people=len({r["p"] for r in rows}),
                median_addressed_share=round(st.median(r["ash"] for r in rows if r["ash"] is not None), 3),
                corr_log_feedback_addressed=round(corr, 3),
                corr_log_addressed_unaddressed=round(st.correlation([r["lai"] for r in rows],
                                                                    [r["lui"] for r in rows]), 3))
    rel = reliability(rows)
    print(f"  summary {summ}\n  reliability {rel}", file=sys.stderr, flush=True)
    return dict(summary=summ, reliability=rel, fits=people_fits(rows))


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    a = sp.add_parser("cl")
    a.add_argument("--table", required=True, help="cl_table.sqlite from scripts/review_roi_table.py")
    a.add_argument("--out")
    c = sp.add_parser("blame")
    c.add_argument("--table", required=True)
    c.add_argument("--blame-dir", required=True, help="scratch dir of review_roi_blame.py (szz_items.jsonl, survival_items.jsonl)")
    c.add_argument("--out")
    b = sp.add_parser("people")
    b.add_argument("--first-commit", required=True)
    b.add_argument("--owners-added", required=True)
    b.add_argument("--mech", required=True)
    b.add_argument("--cache")
    b.add_argument("--out")
    args = ap.parse_args()
    res = dict(cl=run_cl, blame=run_blame, people=run_people)[args.cmd](args)
    if args.out:
        json.dump(res, open(args.out, "w"), indent=1)


if __name__ == "__main__":
    main()
