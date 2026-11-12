"""Review ROI, Part 1: does deeper or more expert review lower the revert
rate, after normalizing for difficulty? Designs D1-D8 of docs/review-roi.md;
findings in docs/review-roi-part1.md.

Reads the per-CL table from scripts/review_roi_table.py (and, for D8, the
revert-reason classes from the revert study). Offline and standard library
only; prints the tables and writes a JSON summary of aggregates (no
identities).

  export COSH_DATA_DIR=/home/rbagent/projects/cosh/data/private
  S=data/private/scratch/review_roi/part1
  nice -n 5 python3 scripts/review_roi_part1.py --table $S/cl_table.sqlite \
      --json $S/part1_results.json [--reasons $S/../reverts/revert_reasons.tsv] \
      [--designs D1,D2,D3,D4,D5,D6,D7,D8] [--frac 0.15] [--reps 200] [--check] > $S/part1_report.txt
  python3 scripts/review_roi_part1.py --json $S/part1_report.json --summary $S/part1_results.json

The run used for docs/review-roi-part1.md: --frac 1 --reps 200 --check
--reasons $S/../reverts/revert_reasons.tsv, --json $S/part1_report.json
(about 40 minutes).

The logistic models (D3, D4, D7, D8) are fitted on a case-control sample:
every CL with the outcome, and the CLs without it among a fixed random
fraction (--frac, seed 1) of the unit. Slopes are unbiased under this
sampling; the intercept is corrected by log(frac) for predicted rates.
Standard errors are clustered by author (sandwich, as cluster_cov in
scripts/balance_feedback_predicts.py; the sparse Newton solver here is
checked against that script's `logit` at start-up with --check).
D8 runs only with --reasons. About 30 minutes for everything.
"""

import argparse
import json
import math
import os
import random
import sqlite3
import statistics as st
import sys
import time
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    import balance_feedback_predicts as F  # noqa: E402
except ImportError:          # worktrees branched before the script landed on main
    sys.path.insert(0, "/home/rbagent/projects/cosh/scripts")
    import balance_feedback_predicts as F  # noqa: E402

T0 = time.time()
OUT = {}
DAYS30 = "rev30"


def log(msg):
    print(f"[{time.time() - T0:6.0f}s] {msg}", file=sys.stderr, flush=True)


def say(*a):
    print(*a, flush=True)


# ------------------------------------------------------------------ data

COLS = ["change_number", "author_id", "landed_at", "half", "era", "weekday", "hour", "lines", "files", "size10",
        "dir2", "dir3", "test_share", "author_tenure_m", "tenure_censored", "tenure_band", "practice_band",
        "author_practice3", "threads", "addressed", "comments", "chars", "commenters", "rounds", "rework_after",
        "interdiff_share", "attn_h", "reviewer_wait_h", "first_review_h", "review_total_h", "exp24",
        "feedback_index", "resid_threads", "n_approvers", "approver_source", "rubber_stamp", "appr_auth3_max",
        "appr_auth2_max", "appr_appr3_max", "appr_appr2_max", "appr_owner_cover_any", "appr_owner_near_any",
        "appr_tenure_y_max", "first_approver_id", "first_auth3", "first_appr3", "first_owner_cover",
        "first_tenure_y", "habit_first", "habit_first_n", "habit_idx_first", "habit_max", "habrev_first",
        "habrev_max", "habit_log_first", "habit_log_max", "rev7", "rev30", "rev90", "revert_days", "sha", "revert_sha"]


def load(path):
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    have = {r[1] for r in db.execute("PRAGMA table_info(cl)")}
    cols = [c for c in COLS if c in have]
    data = {c: [] for c in cols}
    for r in db.execute(f"SELECT {', '.join(cols)} FROM cl ORDER BY change_number"):
        for c, v in zip(cols, r):
            data[c].append(v)
    meta = {k: json.loads(v) for k, v in db.execute("SELECT k, v FROM meta")}
    n = len(data["change_number"])
    rv = data["revert_days"]
    data["rev8_30"] = [None if r7 else int(d is not None and 7 < d <= 30) for r7, d in zip(data["rev7"], rv)]
    data["unaddressed"] = [t - a for t, a in zip(data["threads"], data["addressed"])]
    data["addr_share"] = [a / t if t else None for t, a in zip(data["threads"], data["addressed"])]
    return data, meta, n


# --------------------------------------------------------------- exposures

# name -> (column, kind, label). kind: "log" = log2(1 + x) (effect per doubling of 1 + x),
# "bin" = 0/1, "lin" = linear (effect per standard deviation).
EXPOSURES = {
    "threads": ("threads", "log", "reviewer-started threads"),
    "feedback_index": ("feedback_index", "log", "feedback index (threads / 2023-24 norm)"),
    "addressed": ("addressed", "log", "addressed threads"),
    "comments": ("comments", "log", "reviewer comments"),
    "commenters": ("commenters", "log", "distinct non-owner commenters"),
    "rounds": ("rounds", "log", "review rounds"),
    "interdiff_share": ("interdiff_share", "log", "interdiff share"),
    "attn_h": ("attn_h", "log", "reviewer attention hours (sum over reviewers)"),
    "first_review_h": ("first_review_h", "log", "hours sent -> first substantive review"),
    "n_approvers": ("n_approvers", "log", "approvers"),
    "rubber_stamp": ("rubber_stamp", "bin", "rubber stamp (approved, no thread)"),
    "appr_appr3": ("appr_appr3_max", "log", "approver's prior approvals in dir3 (max)"),
    "appr_auth3": ("appr_auth3_max", "log", "approver's prior commits in dir3 (max)"),
    "appr_appr2": ("appr_appr2_max", "log", "approver's prior approvals in dir2 (max)"),
    "appr_owner": ("appr_owner_cover_any", "bin", "an approver was an OWNER covering the CL"),
    "appr_tenure": ("appr_tenure_y_max", "log", "approver tenure, years (max)"),
    "habit_first": ("habit_first", "lin", "first approver's habitual thoroughness (LOO residual threads)"),
    "habit_max": ("habit_max", "lin", "most thorough approver's habit (LOO residual threads)"),
    "habit_log_first": ("habit_log_first", "lin", "first approver's habit, log scale (LOO residual log1p threads)"),
    "habit_log_max": ("habit_log_max", "lin", "most thorough approver's habit, log scale"),
    "habit_idx_first": ("habit_idx_first", "log", "first approver's habitual feedback index (LOO)"),
    "habrev_first": ("habrev_first", "lin", "first approver's LOO revert rate (descriptive)"),
}
D3_SET = ["threads", "feedback_index", "addressed", "comments", "commenters", "rounds", "interdiff_share", "attn_h",
          "first_review_h", "n_approvers", "rubber_stamp"]
D4_SET = ["habit_log_first", "habit_log_max", "habit_first", "habit_max", "habit_idx_first", "appr_appr3", "appr_auth3", "appr_appr2", "appr_owner",
          "appr_tenure", "habrev_first"]
D1_SET = ["threads", "feedback_index", "attn_h", "addressed", "rubber_stamp", "appr_appr3", "appr_auth3",
          "appr_owner", "appr_tenure", "habit_log_first", "habit_first", "habit_idx_first", "habrev_first"]


def tx(kind, x):
    if x is None:
        return None
    return math.log2(1 + max(0.0, x)) if kind == "log" else float(x)


def q(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p * len(xs)))] if xs else None


# ------------------------------------------------------------- strata

def stratum_keys(D, n, with_half=True):
    return [(D["size10"][i], D["dir2"][i], D["practice_band"][i]) + ((D["half"][i],) if with_half else ())
            for i in range(n)]


def expected_rate(D, n, y, k=20):
    """Smoothed stratum revert rate (size10 x dir2 x practice), shrunk towards size10 x practice."""
    s, p = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
    keys = stratum_keys(D, n, with_half=False)
    for i in range(n):
        if y[i] is None:
            continue
        s[keys[i]][0] += 1
        s[keys[i]][1] += y[i]
        pk = (D["size10"][i], D["practice_band"][i])
        p[pk][0] += 1
        p[pk][1] += y[i]
    out = []
    for i in range(n):
        a = s[keys[i]]
        b = p[(D["size10"][i], D["practice_band"][i])]
        prior = b[1] / b[0] if b[0] else 0.0
        out.append((a[1] + k * prior) / (a[0] + k))
    return out


# ----------------------------------------------------------------- D1

def bins_for(vals, nb=10):
    """Cutpoints at the deciles, merged where ties make them equal."""
    xs = sorted(vals)
    cuts = sorted({xs[int(len(xs) * j / nb)] for j in range(1, nb)})
    return cuts


def which_bin(x, cuts):
    lo, hi = 0, len(cuts)
    while lo < hi:
        m = (lo + hi) // 2
        if x >= cuts[m]:
            lo = m + 1
        else:
            hi = m
    return lo


def d1(D, n, E):
    say("\n## D1. 30-day revert rate by decile of each measure: raw and indirectly standardized")
    say("(adjusted = observed / expected x overall rate; expected from the size10 x dir2 x practice-band stratum rate)")
    y = D[DAYS30]
    overall = sum(y) / n
    res = {}
    for name in D1_SET:
        col, kind, label = EXPOSURES[name]
        idx = [i for i in range(n) if D[col][i] is not None]
        if kind == "bin":
            cuts = [1]
        else:
            cuts = bins_for([D[col][i] for i in idx])
        acc = defaultdict(lambda: [0, 0, 0.0, []])
        for i in idx:
            b = which_bin(D[col][i], cuts)
            a = acc[b]
            a[0] += 1
            a[1] += y[i]
            a[2] += E[i]
        rows = []
        say(f"\n{label} (n={len(idx):,})")
        say(f"{'bin':>22} {'CLs':>8} {'raw %':>7} {'adj %':>7} {'O/E':>6}")
        for b in sorted(acc):
            a = acc[b]
            lo = cuts[b - 1] if b > 0 else None
            hi = cuts[b] if b < len(cuts) else None
            lab = f"[{fmt(lo)}, {fmt(hi)})" if kind != "bin" else ("yes" if b else "no")
            oe = a[1] / a[2] if a[2] else None
            rows.append(dict(bin=lab, cls=a[0], raw=round(a[1] / a[0], 4), adjusted=round(oe * overall, 4), o_e=round(oe, 3)))
            say(f"{lab:>22} {a[0]:>8,} {100 * a[1] / a[0]:>7.2f} {100 * oe * overall:>7.2f} {oe:>6.2f}")
        res[name] = rows
    OUT["D1"] = dict(overall_rev30=round(overall, 4), tables=res)


def fmt(x):
    if x is None:
        return ""
    if isinstance(x, float) and not x.is_integer():
        return f"{x:.3g}"
    return str(int(x))


# ----------------------------------------------------------------- D2

def mh(cells):
    """cells: list of (a, b, c, d) per stratum. Mantel-Haenszel OR and its
    Robins-Breslow-Greenland 95% CI."""
    R = S = PR = PSQR = QS = 0.0
    for a, b, c, d in cells:
        t = a + b + c + d
        if t < 2:
            continue
        r, s = a * d / t, b * c / t
        P, Q = (a + d) / t, (b + c) / t
        R += r
        S += s
        PR += P * r
        PSQR += P * s + Q * r
        QS += Q * s
    if R == 0 or S == 0:
        return None, None, None
    orr = R / S
    v = PR / (2 * R * R) + PSQR / (2 * R * S) + QS / (2 * S * S)
    se = math.sqrt(v)
    return orr, orr * math.exp(-1.96 * se), orr * math.exp(1.96 * se)


def mh_boot(rows, reps, seed=7):
    """rows: (author, stratum, exposed, case). MH OR with an author-clustered bootstrap CI."""
    cells = defaultdict(lambda: [0, 0, 0, 0])
    for a, s, e, y in rows:
        cells[(a, s)][(0 if e else 2) + (0 if y else 1)] += 1
    per_s = defaultdict(lambda: [0, 0, 0, 0])
    for (a, s), v in cells.items():
        for j in range(4):
            per_s[s][j] += v[j]
    point = mh(list(per_s.values()))
    # Only strata with a case and both exposure levels contribute.
    useful = {s for s, v in per_s.items() if (v[0] + v[2]) > 0 and (v[0] + v[1]) > 0 and (v[2] + v[3]) > 0}
    by_s = defaultdict(list)
    authors = set()
    for (a, s), v in cells.items():
        if s in useful:
            by_s[s].append((a, v))
        authors.add(a)
    authors = sorted(authors)
    rnd = random.Random(seed)
    ors = []
    for _ in range(reps):
        m = Counter(rnd.choices(authors, k=len(authors)))
        cl = []
        for s, lst in by_s.items():
            acc = [0, 0, 0, 0]
            for a, v in lst:
                k = m.get(a)
                if k:
                    for j in range(4):
                        acc[j] += k * v[j]
            cl.append(acc)
        o = mh(cl)[0]
        if o:
            ors.append(o)
    ors.sort()
    lo = ors[int(0.025 * len(ors))] if ors else None
    hi = ors[int(0.975 * len(ors)) - 1] if ors else None
    return point[0], lo, hi, len(useful)


def crude_or(rows):
    a = b = c = d = 0
    for _, _, e, y in rows:
        if e and y:
            a += 1
        elif e:
            b += 1
        elif y:
            c += 1
        else:
            d += 1
    if not (a and b and c and d):
        return None, None, None
    o = a * d / (b * c)
    se = math.sqrt(1 / a + 1 / b + 1 / c + 1 / d)
    return o, o * math.exp(-1.96 * se), o * math.exp(1.96 * se)


def d2(D, n, reps):
    say("\n## D2. Odds ratios: exposure above vs at-or-below the median, raw vs Mantel-Haenszel")
    say("strata = size10 x dir2 x author practice band x half-year; MH CI: author-clustered bootstrap")
    y = D[DAYS30]
    keys = stratum_keys(D, n)
    res = {}
    say(f"{'measure':>48} {'raw OR (95% CI)':>22} {'stratified OR (95% CI)':>24} {'strata':>7} {'n':>8}")
    for name in D1_SET + ["comments", "commenters", "rounds", "interdiff_share", "first_review_h", "n_approvers",
                          "habit_max", "appr_appr2"]:
        col, kind, label = EXPOSURES[name]
        idx = [i for i in range(n) if D[col][i] is not None]
        if kind == "bin":
            ex = {i: D[col][i] > 0 for i in idx}
            gex = ex
        else:
            byk = defaultdict(list)
            for i in idx:
                byk[keys[i]].append(D[col][i])
            med = {k: st.median(v) for k, v in byk.items()}
            ex = {i: D[col][i] > med[keys[i]] for i in idx}
            gm = st.median([D[col][i] for i in idx])
            gex = {i: D[col][i] > gm for i in idx}
        rows = [(D["author_id"][i], keys[i], ex[i], y[i]) for i in idx]
        raw = crude_or([(0, 0, gex[i], y[i]) for i in idx])
        o, lo, hi, ns = mh_boot(rows, reps)
        # By global quintile of the measure, MH vs the bottom fifth (RGB CIs).
        quint = None
        if kind != "bin":
            vals = sorted(D[col][i] for i in idx)
            cuts = sorted({vals[int(len(vals) * j / 5)] for j in range(1, 5)})
            qi = {i: which_bin(D[col][i], cuts) for i in idx}
            levels = sorted(set(qi.values()))
            quint = []
            for qq in levels[1:]:
                cells = defaultdict(lambda: [0, 0, 0, 0])
                for i in idx:
                    if qi[i] in (levels[0], qq):
                        cells[keys[i]][(0 if qi[i] == qq else 2) + (0 if y[i] else 1)] += 1
                mo, ml, mhh = mh(list(cells.values()))
                quint.append(dict(fifth=levels.index(qq) + 1, or_=r3(mo), lo=r3(ml), hi=r3(mhh)))
        res[name] = dict(label=label, n=len(idx), raw_or=r3(raw[0]), raw_lo=r3(raw[1]), raw_hi=r3(raw[2]),
                         mh_or=r3(o), mh_lo=r3(lo), mh_hi=r3(hi), informative_strata=ns, by_fifth_vs_bottom=quint)
        say(f"{label[:48]:>48} {ci(raw[0], raw[1], raw[2]):>22} {ci(o, lo, hi):>24} {ns:>7,} {len(idx):>8,}")
        if quint:
            say(f"{'':>48}   by fifth vs bottom (MH): " + ", ".join(f"Q{d['fifth']} {d['or_']}" for d in quint))
    OUT["D2"] = res


def r3(x):
    return None if x is None else round(x, 3)


def ci(o, lo, hi):
    if o is None:
        return "n/a"
    return f"{o:.2f} ({lo:.2f}-{hi:.2f})" if lo is not None else f"{o:.2f}"


# ------------------------------------------------------- sparse logistic

class Design:
    """Sparse rows: control features (categoricals with the most common level
    as reference, plus a few continuous ones), then exposures appended."""

    def __init__(self, D, n, min_dir=400):
        self.names = ["(intercept)"]
        self.index = {}
        dcount = Counter(D["dir2"])
        self.dirs = {d for d, c in dcount.items() if c >= min_dir}
        cats = {
            "size10": D["size10"],
            "dir2": [d if d in self.dirs else "(other)" for d in D["dir2"]],
            "tenure": [t or "unknown" for t in D["tenure_band"]],
            "practice": D["practice_band"],
            "half": D["half"],
            "weekday": D["weekday"],
            "hour": [h // 6 for h in D["hour"]],
        }
        self.ref = {k: Counter(v).most_common(1)[0][0] for k, v in cats.items()}
        for k, v in cats.items():          # rare levels (< 200 CLs) join the reference level
            cnt = Counter(v)
            cats[k] = [x if cnt[x] >= 200 else self.ref[k] for x in v]
        self.cats = cats
        self.rows = []
        for i in range(n):
            ix, vx = [0], [1.0]
            for k, v in cats.items():
                if v[i] != self.ref[k]:
                    ix.append(self.feat(f"{k}={v[i]}"))
                    vx.append(1.0)
            ix.append(self.feat("log2 files"))
            vx.append(math.log2(max(1, D["files"][i] or 1)))
            ts = D["test_share"][i]
            ix.append(self.feat("test share"))
            vx.append(ts if ts is not None else 0.0)
            if D["tenure_censored"][i]:
                ix.append(self.feat("tenure censored"))
                vx.append(1.0)
            pairs = sorted(zip(ix, vx))          # sparse_logit fills the upper triangle: indices must ascend
            self.rows.append(([j for j, _ in pairs], [v for _, v in pairs]))
        self.k = len(self.names)

    def feat(self, name):
        j = self.index.get(name)
        if j is None:
            j = self.index[name] = len(self.names)
            self.names.append(name)
        return j


def sparse_logit(X, y, k, iters=30, beta=None):
    """Newton-Raphson on sparse rows [(idx, val)] with sorted idx. Returns
    beta and the Hessian X'WX at the solution."""
    beta = beta or [0.0] * k
    for it in range(iters):
        H = [[0.0] * k for _ in range(k)]
        g = [0.0] * k
        for (ix, vx), yi in zip(X, y):
            eta = 0.0
            for j, v in zip(ix, vx):
                eta += beta[j] * v
            p = 1 / (1 + math.exp(-max(-30.0, min(30.0, eta))))
            w, r = p * (1 - p), yi - p
            m = len(ix)
            for a in range(m):
                ja, va = ix[a], vx[a]
                g[ja] += va * r
                wa = w * va
                Hr = H[ja]
                for b in range(a, m):
                    Hr[ix[b]] += wa * vx[b]
        for i in range(k):
            for j in range(i):
                H[i][j] = H[j][i]
            H[i][i] += 1e-9
        step = F.solve(H, g)
        beta = [b + s for b, s in zip(beta, step)]
        if max(abs(s) for s in step) < 1e-7:
            break
    return beta, H, it + 1


def cluster_se(X, y, beta, H, groups, which):
    """Cluster-robust covariance of the coefficients in `which` (indices):
    bread rows by solving H b = e_j, then sum per cluster of r_i (b . x_i),
    with cluster_cov's small-sample factor."""
    k = len(beta)
    bread = {j: F.solve(H, [1.0 if i == j else 0.0 for i in range(k)]) for j in which}
    sums = defaultdict(lambda: [0.0] * len(which))
    for (ix, vx), yi, gi in zip(X, y, groups):
        eta = sum(beta[j] * v for j, v in zip(ix, vx))
        r = yi - 1 / (1 + math.exp(-max(-30.0, min(30.0, eta))))
        s = sums[gi]
        for a, j in enumerate(which):
            bj = bread[j]
            s[a] += r * sum(bj[t] * v for t, v in zip(ix, vx))
    G_, nn = len(sums), len(X)
    c = G_ / (G_ - 1) * (nn - 1) / (nn - k) if G_ > 1 and nn > k else 1.0
    m = len(which)
    cov = [[0.0] * m for _ in range(m)]
    for s in sums.values():
        for a in range(m):
            for b in range(m):
                cov[a][b] += s[a] * s[b]
    return [[c * v for v in row] for row in cov]


def check_solver(D, n):
    """Compare the sparse solver and its clustered SEs with
    balance_feedback_predicts.logit on a small dense problem."""
    rnd = random.Random(3)
    idx = rnd.sample(range(n), 4000)
    feats = lambda i: [1.0, math.log2(1 + D["threads"][i]), math.log2(max(1, D["files"][i] or 1)),
                       float(D["size10"][i]), D["test_share"][i] or 0.0]
    Xd = [feats(i) for i in idx]
    y = [D[DAYS30][i] for i in idx]
    g = [D["author_id"][i] for i in idx]
    b1, se1, _ = F.logit(Xd, y, g)
    Xs = [(list(range(5)), x) for x in Xd]
    b2, H, _ = sparse_logit(Xs, y, 5)
    cov = cluster_se(Xs, y, b2, H, g, list(range(5)))
    se2 = [math.sqrt(cov[i][i]) for i in range(5)]
    dif = max(max(abs(a - b) for a, b in zip(b1, b2)), max(abs(a - b) for a, b in zip(se1, se2)))
    say(f"\nsolver check against balance_feedback_predicts.logit (4,000 rows, 5 features): max |diff| = {dif:.2e}")
    OUT["solver_check_max_abs_diff"] = dif
    return dif


class Fitter:
    def __init__(self, D, n, des, frac, seed=1):
        self.D, self.n, self.des, self.frac = D, n, des, frac
        rnd = random.Random(seed)
        self.u = [rnd.random() for _ in range(n)]
        # The cohort sample used for averaging predictions over the control mix.
        self.cohort = [i for i in range(n) if self.u[i] < 60000 / n]

    def fit(self, outcome, exposures, subset=None, cluster="author_id", label=""):
        """exposures: list of names in EXPOSURES (or (name, col, kind) tuples). Returns a dict."""
        D, des = self.D, self.des
        y_all = D[outcome]
        ex = [EXPOSURES[e] if isinstance(e, str) else e[1:] for e in exposures]
        names = [e if isinstance(e, str) else e[0] for e in exposures]
        sd = []
        for col, kind, _ in ex:
            if kind == "lin":
                vals = [D[col][i] for i in range(self.n) if D[col][i] is not None and (subset is None or subset(i))]
                sd.append(st.pstdev(vals) or 1.0)
            else:
                sd.append(1.0)
        X, y, grp, rows = [], [], [], []
        k0 = des.k
        for i in range(self.n):
            yi = y_all[i]
            if yi is None or (subset is not None and not subset(i)):
                continue
            if not (yi or self.u[i] < self.frac):
                continue
            xs = [tx(kind, D[col][i]) for col, kind, _ in ex]
            if any(x is None for x in xs):
                continue
            ix, vx = des.rows[i]
            X.append((ix + [k0 + j for j in range(len(xs))], vx + [x / s for x, s in zip(xs, sd)]))
            y.append(yi)
            grp.append(D[cluster][i] if D[cluster][i] is not None else -i)
            rows.append(i)
        k = k0 + len(xs)
        # Drop features with no variation in the sample (empty dummies).
        used = sorted({j for ix, _ in X for j in ix})
        remap = {j: t for t, j in enumerate(used)}
        X = [([remap[j] for j in ix], vx) for ix, vx in X]
        kk = len(used)
        ncase = sum(y)
        t = time.time()
        beta, H, its = sparse_logit(X, y, kk)
        which = [remap[k0 + j] for j in range(len(xs))]
        cov = cluster_se(X, y, beta, H, grp, which)
        # Predicted rates at the 25th and 75th percentile of each exposure, over the cohort sample.
        full = [i for i in range(self.n) if y_all[i] is not None and (subset is None or subset(i))]
        base_rate = sum(y_all[i] for i in full) / len(full)
        coh = [i for i in self.cohort if y_all[i] is not None and (subset is None or subset(i))
               and all(D[col][i] is not None for col, _, _ in ex)]
        intercept_shift = math.log(self.frac) if self.frac < 1 else 0.0
        out = dict(label=label, outcome=outcome, n_sample=len(X), cases=ncase, n_unit=len(full),
                   base_rate=round(base_rate, 5), iterations=its, seconds=round(time.time() - t, 1), effects={})
        for a, (name, (col, kind, lab)) in enumerate(zip(names, ex)):
            j = which[a]
            b, se = beta[j], math.sqrt(cov[a][a])
            vals = [D[col][i] for i in full if D[col][i] is not None]
            if kind == "bin":
                lo_v, hi_v = 0.0, 1.0
            else:
                lo_v, hi_v = q(vals, 0.25), q(vals, 0.75)
            t_lo, t_hi = tx(kind, lo_v) / sd[a], tx(kind, hi_v) / sd[a]

            def diff(bb):
                tot = 0.0
                for i in coh:
                    ix, vx = des.rows[i]
                    eta = intercept_shift
                    for jj, v in zip(ix, vx):
                        if jj in remap:
                            eta += beta[remap[jj]] * v
                    for a2, (c2, k2, _) in enumerate(ex):
                        if a2 != a:
                            eta += beta[which[a2]] * tx(k2, D[c2][i]) / sd[a2]
                    p1 = 1 / (1 + math.exp(-max(-30.0, min(30.0, eta + bb * t_hi))))
                    p0 = 1 / (1 + math.exp(-max(-30.0, min(30.0, eta + bb * t_lo))))
                    tot += p1 - p0
                return tot / len(coh) if coh else None
            d0, dlo, dhi = diff(b), diff(b - 1.96 * se), diff(b + 1.96 * se)
            unit = "per doubling of (1 + x)" if kind == "log" else "per SD" if kind == "lin" else "yes vs no"
            out["effects"][name] = dict(
                label=lab, unit=unit, sd=r3(sd[a]) if kind == "lin" else None, coef=round(b, 4), se=round(se, 4),
                odds_ratio=round(math.exp(b), 3), or_lo=round(math.exp(b - 1.96 * se), 3),
                or_hi=round(math.exp(b + 1.96 * se), 3), z=round(b / se, 2) if se else None,
                p25=lo_v, p75=hi_v, rate_diff_p75_minus_p25=round(d0, 5),
                rate_diff_lo=round(min(dlo, dhi), 5), rate_diff_hi=round(max(dlo, dhi), 5),
                avoided_per_1000=round(-1000 * d0, 2),
                avoided_per_1000_lo=round(-1000 * max(dlo, dhi), 2), avoided_per_1000_hi=round(-1000 * min(dlo, dhi), 2))
        return out


def show_fit(r, title=None):
    if title:
        say(f"\n{title}")
    say(f"  outcome {r['outcome']}, base rate {100 * r['base_rate']:.2f}%, unit n {r['n_unit']:,}, "
        f"sample n {r['n_sample']:,} ({r['cases']:,} cases), {r['iterations']} iterations, {r['seconds']} s")
    for name, e in r["effects"].items():
        say(f"  {e['label'][:58]:58} OR {e['odds_ratio']:.3f} ({e['or_lo']:.3f}-{e['or_hi']:.3f}) {e['unit']:>24}; "
            f"p25 {fmt(e['p25'])} -> p75 {fmt(e['p75'])}: {1000 * e['rate_diff_p75_minus_p25']:+.2f} per 1,000 "
            f"({1000 * e['rate_diff_lo']:+.2f} to {1000 * e['rate_diff_hi']:+.2f})")


# ----------------------------------------------------------------- D3/D4

def d3(Fi):
    say("\n## D3. Logistic regression, 30-day revert on this CL's review depth, all controls, author-clustered SEs")
    res = {}
    for name in D3_SET:
        r = Fi.fit(DAYS30, [name], label=name)
        show_fit(r)
        res[name] = r
        log(f"D3 {name}")
    # Raw (intercept-only controls) for contrast: the same exposures without controls.
    OUT["D3"] = res


def d3_raw(D, n, Fi):
    """The D3 exposures with no controls at all, for the raw-vs-adjusted contrast."""
    say("\n### D3 without controls (raw slope), for contrast")
    res = {}
    empty = Design.__new__(Design)
    empty.names, empty.index, empty.k = ["(intercept)"], {}, 1
    empty.rows = [([0], [1.0])] * n
    F2 = Fitter.__new__(Fitter)
    F2.D, F2.n, F2.des, F2.frac, F2.u, F2.cohort = D, n, empty, Fi.frac, Fi.u, Fi.cohort
    for name in D3_SET + ["habit_log_first", "habit_first", "appr_appr3", "appr_owner"]:
        r = F2.fit(DAYS30, [name], label=name + " raw")
        e = r["effects"][name]
        say(f"  {e['label'][:58]:58} raw OR {e['odds_ratio']:.3f} ({e['or_lo']:.3f}-{e['or_hi']:.3f})  "
            f"p25->p75 {1000 * e['rate_diff_p75_minus_p25']:+.2f} per 1,000")
        res[name] = r
    OUT["D3_raw"] = res


def d4(Fi, D, n):
    say("\n## D4. Approver habit and expertise as exposures (no measure of this CL's own review), "
        "author-clustered SEs")
    res = {}
    for name in D4_SET:
        r = Fi.fit(DAYS30, [name], label=name)
        show_fit(r)
        res[name] = r
        log(f"D4 {name}")
    for hb in ("habit_log_first", "habit_first"):
        joint = [hb, "appr_appr3", "appr_auth3", "appr_owner", "appr_tenure"]
        r = Fi.fit(DAYS30, joint, label="joint")
        show_fit(r, f"D4 joint model ({hb} + approver expertise together)")
        res[f"joint_{hb}"] = r
        r = Fi.fit(DAYS30, [hb], cluster="first_approver_id", label="habit, approver-clustered")
        show_fit(r, f"D4 {hb}, SEs clustered by first approver instead of author")
        res[f"{hb}_approver_clustered"] = r
        r = Fi.fit(DAYS30, [hb], subset=lambda i: (D["habit_first_n"][i] or 0) >= 20,
                   label="habit, approver with 20+ other CLs in the half-year")
        show_fit(r, f"D4 {hb}, only approvers with 20+ other CLs in the half-year (less noise)")
        res[f"{hb}_20plus"] = r
        r = Fi.fit(DAYS30, [hb], subset=lambda i: D["approver_source"][i] == "votes",
                   label="habit, CLs whose approvers come from votes")
        show_fit(r, f"D4 {hb}, only CLs whose approvers come from Gerrit votes")
        res[f"{hb}_votes_only"] = r
    OUT["D4"] = res


# ----------------------------------------------------------------- D5

def d5(D, n):
    say("\n## D5. Within author x dir3 x half-year x size10 matched sets")
    y = D[DAYS30]
    sets = defaultdict(list)
    for i in range(n):
        sets[(D["author_id"][i], D["dir3"][i], D["half"][i], D["size10"][i])].append(i)
    multi = {k: v for k, v in sets.items() if len(v) >= 2}
    one_case = {k: v for k, v in multi.items() if sum(y[i] for i in v) == 1}
    say(f"sets with 2+ CLs: {len(multi):,} ({sum(len(v) for v in multi.values()):,} CLs); "
        f"with exactly one revert: {len(one_case):,}")
    res = dict(sets_2plus=len(multi), cls_in_sets=sum(len(v) for v in multi.values()), sets_one_case=len(one_case),
               measures={})
    say(f"{'measure':>48} {'cond. OR (95% CI)':>24} {'sets':>6} {'case higher':>12} {'case lower':>11} {'sign p':>7}")
    for name in ["threads", "feedback_index", "addressed", "attn_h", "rounds", "rubber_stamp", "habit_log_first", "habit_first",
                 "appr_appr3", "appr_owner"]:
        col, kind, label = EXPOSURES[name]
        data = []
        hi = lo = 0
        for k, v in one_case.items():
            xs = [(tx(kind, D[col][i]), y[i]) for i in v if D[col][i] is not None]
            if len(xs) < 2 or sum(yy for _, yy in xs) != 1 or len({x for x, _ in xs}) < 2:
                continue
            data.append((k[0], xs))
            xc = next(x for x, yy in xs if yy)
            mc = st.mean(x for x, yy in xs if not yy)
            hi += xc > mc
            lo += xc < mc
        b, se = clogit(data)
        sd = 1.0
        if kind == "lin":
            sd = st.pstdev([D[col][i] for i in range(n) if D[col][i] is not None]) or 1.0
            b, se = b * sd, se * sd
        pz = sign_p(hi, lo)
        unit = "per doubling" if kind == "log" else "per SD" if kind == "lin" else "yes vs no"
        res["measures"][name] = dict(label=label, unit=unit, sets=len(data), cond_or=r3(math.exp(b)),
                                     lo=r3(math.exp(b - 1.96 * se)), hi=r3(math.exp(b + 1.96 * se)),
                                     case_higher=hi, case_lower=lo, sign_p=r3(pz))
        say(f"{label[:48]:>48} {ci(math.exp(b), math.exp(b - 1.96 * se), math.exp(b + 1.96 * se)):>24} "
            f"{len(data):>6,} {hi:>12,} {lo:>11,} {pz:>7.3f}   ({unit})")
    OUT["D5"] = res


def clogit(data, iters=30):
    """Conditional logit, one case per set, one covariate; author-clustered sandwich SE."""
    b = 0.0
    for _ in range(iters):
        g = h = 0.0
        for _, xs in data:
            ws = [math.exp(b * x) for x, _ in xs]
            s = sum(ws)
            m = sum(w * x for w, (x, _) in zip(ws, xs)) / s
            v = sum(w * x * x for w, (x, _) in zip(ws, xs)) / s - m * m
            xc = next(x for x, yy in xs if yy)
            g += xc - m
            h += v
        if h <= 0:
            return 0.0, float("inf")
        step = g / h
        b += step
        if abs(step) < 1e-9:
            break
    sc = defaultdict(float)
    h = 0.0
    for a, xs in data:
        ws = [math.exp(b * x) for x, _ in xs]
        s = sum(ws)
        m = sum(w * x for w, (x, _) in zip(ws, xs)) / s
        v = sum(w * x * x for w, (x, _) in zip(ws, xs)) / s - m * m
        sc[a] += next(x for x, yy in xs if yy) - m
        h += v
    meat = sum(v * v for v in sc.values())
    return b, math.sqrt(meat) / h


def sign_p(a, b):
    nn = a + b
    if not nn:
        return 1.0
    z = (abs(a - b) - 1) / math.sqrt(nn)
    return math.erfc(max(0.0, z) / math.sqrt(2))


# ----------------------------------------------------------------- D6

def d6(D, n, Fi, reps):
    say("\n## D6. Addressed vs unaddressed review at equal threads")
    y = D[DAYS30]
    keys = stratum_keys(D, n)
    tb = lambda t: t if t <= 4 else 5 if t <= 6 else 7 if t <= 9 else 10
    res = {}
    # (a) among CLs with threads: addressed share above the median of its threads x size x dir2 x practice x half stratum
    idx = [i for i in range(n) if D["threads"][i] >= 1]
    byk = defaultdict(list)
    for i in idx:
        byk[(tb(D["threads"][i]),) + keys[i]].append(D["addr_share"][i])
    med = {k: st.median(v) for k, v in byk.items()}
    rows = [(D["author_id"][i], (tb(D["threads"][i]),) + keys[i],
             D["addr_share"][i] > med[(tb(D["threads"][i]),) + keys[i]], y[i]) for i in idx]
    o, lo, hi, ns = mh_boot(rows, reps)
    raw = crude_or([(0, 0, D["addr_share"][i] > 0.5, y[i]) for i in idx])
    say(f"(a) CLs with 1+ thread (n={len(idx):,}): addressed share above the stratum median "
        f"(strata add a threads band): raw OR (share > 0.5) {ci(*raw)}, MH OR {ci(o, lo, hi)}, {ns:,} strata")
    res["addressed_share_above_median"] = dict(n=len(idx), raw_or=r3(raw[0]), raw_lo=r3(raw[1]), raw_hi=r3(raw[2]),
                                               mh_or=r3(o), mh_lo=r3(lo), mh_hi=r3(hi), strata=ns)
    # (b) 0 threads vs exactly 1 addressed thread vs exactly 1 unaddressed thread.
    for lab, cond in (("one addressed thread", lambda i: D["threads"][i] == 1 and D["addressed"][i] == 1),
                      ("one unaddressed thread", lambda i: D["threads"][i] == 1 and D["addressed"][i] == 0)):
        sub = [i for i in range(n) if D["threads"][i] == 0 or cond(i)]
        rows = [(D["author_id"][i], keys[i], D["threads"][i] == 1, y[i]) for i in sub]
        o, lo, hi, ns = mh_boot(rows, reps)
        raw = crude_or(rows)
        r0 = [y[i] for i in sub if D["threads"][i] == 0]
        r1 = [y[i] for i in sub if D["threads"][i] == 1]
        say(f"(b) {lab} vs no thread: rates {100 * st.mean(r1):.2f}% vs {100 * st.mean(r0):.2f}% "
            f"(n {len(r1):,} / {len(r0):,}); raw OR {ci(*raw)}, MH OR {ci(o, lo, hi)}")
        res[lab.replace(" ", "_") + "_vs_none"] = dict(rate=round(st.mean(r1), 4), rate_none=round(st.mean(r0), 4),
                                                       n=len(r1), n_none=len(r0), raw_or=r3(raw[0]), mh_or=r3(o),
                                                       mh_lo=r3(lo), mh_hi=r3(hi))
    # (c) logit: threads and unaddressed threads together.
    r = Fi.fit(DAYS30, ["addressed", ("unaddressed", "unaddressed", "log", "unaddressed threads")], label="addr+unaddr")
    show_fit(r, "(c) logistic: addressed and unaddressed threads in one model, all controls")
    res["logit_addressed_and_unaddressed"] = r
    OUT["D6"] = res


# ----------------------------------------------------------------- D7

def d7(D, n, Fi):
    say("\n## D7. Heterogeneity (logistic, all controls): threads (this CL) and first approver's habit (log and linear)")
    y = D[DAYS30]
    # Directory base revert rate: dir2 rate over the unit, terciles of CLs.
    acc = defaultdict(lambda: [0, 0])
    for i in range(n):
        acc[D["dir2"][i]][0] += 1
        acc[D["dir2"][i]][1] += y[i]
    rate = {d: (v[1] + 20 * 0.03) / (v[0] + 20) for d, v in acc.items()}
    rs = sorted(rate[D["dir2"][i]] for i in range(n))
    t1, t2 = rs[n // 3], rs[2 * n // 3]
    terc = lambda i: 0 if rate[D["dir2"][i]] < t1 else 1 if rate[D["dir2"][i]] < t2 else 2
    groups = {
        "dir2 revert-rate tercile: low": lambda i: terc(i) == 0,
        "dir2 revert-rate tercile: middle": lambda i: terc(i) == 1,
        "dir2 revert-rate tercile: high": lambda i: terc(i) == 2,
        "size: < 32 lines": lambda i: D["size10"][i] <= 3,
        "size: 32-255 lines": lambda i: 4 <= D["size10"][i] <= 6,
        "size: 256+ lines": lambda i: D["size10"][i] >= 7,
        "author tenure < 2 years": lambda i: D["tenure_band"][i] in ("0-1y", "1-2y"),
        "author tenure 2-8 years": lambda i: D["tenure_band"][i] in ("2-4y", "4-8y"),
        "author tenure 8+ years": lambda i: D["tenure_band"][i] == "8y+",
        "era 2023-24": lambda i: D["era"][i] == "2023-24",
        "era 2025": lambda i: D["era"][i] == "2025",
        "era 2026": lambda i: D["era"][i] == "2026",
    }
    say(f"dir2 revert-rate tercile cut points: {100 * t1:.2f}%, {100 * t2:.2f}%")
    res = {}
    for g, f in groups.items():
        res[g] = {}
        for ex in ("threads", "habit_log_first", "habit_first"):
            r = Fi.fit(DAYS30, [ex], subset=f, label=f"{g} / {ex}")
            show_fit(r, f"{g} — {ex}")
            res[g][ex] = r
        log(f"D7 {g}")
    for outc in ("rev7", "rev8_30", "rev90"):
        res[outc] = {}
        for ex in ("threads", "feedback_index", "rubber_stamp", "habit_log_first", "habit_first", "appr_appr3"):
            r = Fi.fit(outc, [ex], label=f"{outc} / {ex}")
            show_fit(r, f"outcome {outc} — {ex}")
            res[outc][ex] = r
        log(f"D7 {outc}")
    OUT["D7"] = res


# ----------------------------------------------------------------- D8

UNRELATED = {"flaky_or_unrelated", "dependent_or_requested"}
RELATED = {"compile_or_link", "test_failure", "crash_or_functional", "perf_or_size_regression", "security"}


def d8(D, n, Fi, path):
    say("\n## D8. Negative control: reverts for reasons review cannot prevent")
    cls_of = {}
    with open(path) as f:
        head = f.readline().rstrip("\n").split("\t")
        for line in f:
            r = dict(zip(head, line.rstrip("\n").split("\t")))
            cls_of[(r["reverted_sha"], r["revert_sha"])] = r["reason_class"]
    y = D[DAYS30]
    for name, keep in (("rev30_unrelated", UNRELATED), ("rev30_related", RELATED)):
        D[name] = [int(bool(y[i]) and cls_of.get((D["sha"][i], D["revert_sha"][i])) in keep) for i in range(n)]
    D["rev30_other"] = [int(bool(y[i]) and cls_of.get((D["sha"][i], D["revert_sha"][i])) not in UNRELATED | RELATED)
                        for i in range(n)]
    matched = sum(1 for i in range(n) if y[i] and (D["sha"][i], D["revert_sha"][i]) in cls_of)
    dist = Counter(cls_of.get((D["sha"][i], D["revert_sha"][i]), "(not in file)") for i in range(n) if y[i])
    say(f"30-day reverts in the unit: {sum(y):,}; with a reason class: {matched:,}; classes: {dict(dist.most_common())}")
    res = dict(reverts=sum(y), matched=matched, classes=dict(dist), models={})
    for outc in ("rev30_related", "rev30_unrelated", "rev30_other"):
        res["models"][outc] = {}
        for ex in ("threads", "feedback_index", "attn_h", "rubber_stamp", "habit_log_first", "habit_first", "appr_appr3",
                   "appr_owner"):
            r = Fi.fit(outc, [ex], label=f"{outc} / {ex}")
            show_fit(r, f"outcome {outc} — {ex}")
            res["models"][outc][ex] = r
        log(f"D8 {outc}")
    OUT["D8"] = res


# -------------------------------------------------------------- summary

def eff(r, name):
    e = r["effects"][name]
    return dict(odds_ratio=e["odds_ratio"], odds_ratio_ci=[e["or_lo"], e["or_hi"]], unit=e["unit"],
                p25=e["p25"], p75=e["p75"], reverts_per_1000_change_p25_to_p75=round(1000 * e["rate_diff_p75_minus_p25"], 2),
                reverts_per_1000_change_ci=[round(1000 * e["rate_diff_lo"], 2), round(1000 * e["rate_diff_hi"], 2)],
                cls=r["n_sample"])


def summary(full):
    """Plain-named main numbers for the page (aggregates only)."""
    t = full["table"]
    m = t["meta"]
    out = dict(
        unit=dict(cls=t["unit_cls"], landed="2023-07-01 .. 2026-09-30", mechanical_rule=m["mech_rule"],
                  exclusions=m["counts"], reverted_within_7d=t["rev7"], reverted_within_30d=t["rev30"],
                  reverted_within_90d=t["rev90"], rubber_stamp_share=t["rubber_stamp_share"],
                  approvers_votes_vs_reviewed_by=m["approver_agreement_votes_vs_reviewed_by"],
                  habit_split_half=m.get("habit_split_half")),
        stratified_odds_ratios={k: dict(label=v["label"], raw=v["raw_or"], raw_ci=[v["raw_lo"], v["raw_hi"]],
                                        stratified=v["mh_or"], stratified_ci=[v["mh_lo"], v["mh_hi"]])
                                for k, v in full.get("D2", {}).items()},
        this_cl_review_logit={k: eff(r, k) for k, r in full.get("D3", {}).items()},
        this_cl_review_logit_no_controls={k: eff(r, k) for k, r in full.get("D3_raw", {}).items()},
        approver_habit_and_expertise_logit={k: eff(r, k) for k, r in full.get("D4", {}).items() if k in r["effects"]},
        approver_joint_models={k: {n: eff(r, n) for n in r["effects"]} for k, r in full.get("D4", {}).items()
                               if k.startswith("joint")},
        approver_habit_robustness={k: eff(r, next(iter(r["effects"]))) for k, r in full.get("D4", {}).items()
                                   if not k.startswith("joint") and k not in r["effects"]},
        within_author_matched_sets=full.get("D5"),
        addressed_vs_unaddressed={k: v for k, v in full.get("D6", {}).items() if not k.startswith("logit")},
        addressed_and_unaddressed_logit={n: eff(full["D6"]["logit_addressed_and_unaddressed"], n)
                                         for n in full.get("D6", {}).get("logit_addressed_and_unaddressed", {})
                                         .get("effects", {})},
        heterogeneity={g: {n: eff(r, n) for n, r in v.items()} for g, v in full.get("D7", {}).items()},
        negative_control={o: {n: eff(r, n) for n, r in v.items()} for o, v in full.get("D8", {}).get("models", {}).items()},
        negative_control_reason_counts=full.get("D8", {}).get("classes"),
    )
    return out


# ----------------------------------------------------------------- main

def describe(D, n, meta):
    say("# Review ROI, Part 1 — per-CL table")
    say(f"unit CLs: {n:,}; table built {meta.get('built_at')}; mechanical rule: {meta.get('mech_rule')}; "
        f"tenure: {meta.get('tenure_source')}; OWNERS: {meta.get('owners_source')}")
    say(f"exclusion counts: {json.dumps(meta.get('counts'))}")
    say(f"approvers, votes vs Reviewed-by: {json.dumps(meta.get('approver_agreement_votes_vs_reviewed_by'))}")
    say(f"habit split-half reliability: {json.dumps(meta.get('habit_split_half'))}")
    y30, y7 = D["rev30"], D["rev7"]
    y90 = [v for v in D["rev90"] if v is not None]
    say(f"revert rates: 7 d {100 * sum(y7) / n:.2f}%, 30 d {100 * sum(y30) / n:.2f}%, 90 d {100 * sum(y90) / len(y90):.2f}% "
        f"(n {len(y90):,} with 90 days observed)")
    cov = {c: sum(v is not None for v in D[c]) / n for c in ("attn_h", "habit_first", "appr_appr3_max",
                                                           "appr_owner_cover_any", "first_review_h", "interdiff_share")}
    say(f"coverage (non-null share): {json.dumps({k: round(v, 3) for k, v in cov.items()})}")
    src = Counter(D["approver_source"])
    say(f"approver source: {dict(src)}")
    OUT["table"] = dict(unit_cls=n, meta=meta, rev7=round(sum(y7) / n, 4), rev30=round(sum(y30) / n, 4),
                        rev90=round(sum(y90) / len(y90), 4), coverage={k: round(v, 3) for k, v in cov.items()},
                        approver_source=dict(src),
                        rubber_stamp_share=round(sum(D["rubber_stamp"]) / n, 4),
                        threads_mean=round(st.mean(D["threads"]), 3))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--table")
    ap.add_argument("--summary", help="write the plain-named summary of --json here and exit")
    ap.add_argument("--json", required=True)
    ap.add_argument("--reasons")
    ap.add_argument("--designs", default="D1,D2,D3,D4,D5,D6,D7,D8")
    ap.add_argument("--frac", type=float, default=0.15)
    ap.add_argument("--reps", type=int, default=200)
    ap.add_argument("--check", action="store_true", help="check the sparse solver against balance_feedback_predicts")
    args = ap.parse_args()
    if args.summary:
        with open(args.summary, "w") as f:
            json.dump(summary(json.load(open(args.json))), f, indent=1)
        return
    designs = set(args.designs.split(","))
    D, meta, n = load(args.table)
    log(f"loaded {n:,} CLs")
    describe(D, n, meta)
    if os.path.exists(args.json):
        try:
            prev = json.load(open(args.json))
            for k, v in prev.items():
                OUT.setdefault(k, v)
        except ValueError:
            pass

    def save():
        OUT["runtime_s"] = round(time.time() - T0)
        OUT["settings"] = dict(frac=args.frac, reps=args.reps, designs=sorted(designs))
        with open(args.json, "w") as f:
            json.dump(OUT, f, indent=1, default=str)
    if args.check:
        check_solver(D, n)
    if "D1" in designs:
        d1(D, n, expected_rate(D, n, D[DAYS30]))
        save()
        log("D1")
    if "D2" in designs:
        d2(D, n, args.reps)
        save()
        log("D2")
    need_fit = designs & {"D3", "D4", "D6", "D7", "D8"}
    if need_fit:
        des = Design(D, n)
        Fi = Fitter(D, n, des, args.frac)
        say(f"\ndesign: {des.k} control columns ({len(des.dirs)} dir2 levels with 400+ CLs, rest pooled)")
        log("design built")
    if "D3" in designs:
        d3(Fi)
        d3_raw(D, n, Fi)
        save()
    if "D4" in designs:
        d4(Fi, D, n)
        save()
    if "D5" in designs:
        d5(D, n)
        save()
        log("D5")
    if "D6" in designs:
        d6(D, n, Fi, args.reps)
        save()
        log("D6")
    if "D7" in designs:
        d7(D, n, Fi)
        save()
    if "D8" in designs:
        if args.reasons and os.path.exists(args.reasons):
            d8(D, n, Fi, args.reasons)
            save()
        else:
            say("\n## D8 skipped: no --reasons file")
    save()
    log("done")


if __name__ == "__main__":
    main()
