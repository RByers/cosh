"""Does the feedback index predict who goes on to own code and review others?
For the Review Balance page's "Learning to need less review feedback" section
(docs/balance.md, section 4c).

The unit is a person-half: an author with MIN_CLS or more merged,
non-mechanical CLs in a base half-year (2023 H2, 2024 H1, 2024 H2). Their
feedback index is reviewer threads ÷ the 2023–24 norm for each CL's size and
directory, summed over those CLs, then divided by the median of their tenure
band in the same half-year (so 1.0 is typical for their tenure and era).

Outcomes, all after the base half-year ends:

- **OWNERS:** first added to any OWNERS file within 18 months (people not
  yet in one when the half-year ends);
- **review share** over the next 12 months: approvals given ÷ (approvals
  + CLs landed), git `Reviewed-by`, people still active (6 or more of
  either);
- **feedback given** over the next 12 months: review threads started on
  other people's merged CLs, per month.

Each is compared by fifth of the relative feedback index, then fitted with
the CLs landed in the half-year, tenure band, half-year and the same
measure during the half-year as controls (logistic for OWNERS, least squares
for the other two, standard errors clustered by person). The OWNERS fit
also reports how much the feedback index adds to the controls' ability to
rank who is added (AUC).

Offline; writes aggregates only (rates, medians and coefficients per
group), never anything per person.

  COSH_DATA_DIR=<main>/data/private python3 scripts/balance_feedback_predicts.py \
      [--cache P] [--out datasets.json]

The page's copy comes from `python3 -m cosh.balance_publish` (compute()).
"""

import argparse
import math
import os
import pickle
import statistics as st
import sys
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import balance_analysis as A  # noqa: E402
import balance_growth as G  # noqa: E402
from balance_report import mech_set  # noqa: E402
from cosh.balance_publish import LAST_QUARTER, quarter_end, show  # noqa: E402

YEAR = G.YEAR
MONTH = YEAR / 12
BASE = ("2023H2", "2024H1", "2024H2")      # every outcome window closes by 2026-06-30
GERRIT_END = quarter_end(LAST_QUARTER).timestamp()
OWNER_MONTHS = 18
NEXT_MONTHS = 12
MIN_CLS = 6                     # merged, non-mechanical CLs in the half-year
MIN_EXPECTED = 3.0              # their summed 2023–24 norm, so the index isn't a ratio of tiny numbers
MIN_ACTIVE = 6                  # approvals + CLs landed in the next 12 months, for review share
TENURE = [(0, 12, "under 1 year"), (12, 24, "1-2 years"), (24, 48, "2-4 years"),
          (48, 96, "4-8 years"), (96, 10 ** 9, "8+ years")]        # months since first commit
MIN_PEOPLE = 20                 # per published point


def half_bounds(h):
    y, k = int(h[:4]), int(h[-1])
    a = datetime(y, 1 if k == 1 else 7, 1, tzinfo=timezone.utc).timestamp()
    b = datetime(y if k == 1 else y + 1, 7 if k == 1 else 1, 1, tzinfo=timezone.utc).timestamp()
    return a, b


def band_of(months):
    for lo, hi, name in TENURE:
        if lo <= months < hi:
            return name
    return None


# ------------------------------------------------------------------- load

def load(args):
    cls, commits, ids, first, owner_at, _ = G.load_all(args)
    mech = mech_set(args.mech)
    authored, given = defaultdict(list), defaultdict(list)       # pid -> [time]
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
    fb = defaultdict(list)          # (pid, half) -> [(threads, expected)]
    for c in use:
        if c["closed_at"] < GERRIT_END:
            fb[(c["pid"], G.half(c["closed_at"]))].append((c["threads"], c["exp24"]))
    # Review threads each person started on other people's merged CLs, dated by the CL's close.
    from cosh import store
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


def count(ts, a, b):
    return sum(a <= t < b for t in ts)


# ------------------------------------------------------------------- rows

def idx(xs):
    return sum(t for t, _ in xs) / sum(e for _, e in xs)


def rows_of(first, owner_at, fb, authored, given, thr):
    out = []
    for (p, h), xs in fb.items():
        h = G.half_name(h)
        if h not in BASE or p not in first or len(xs) < MIN_CLS or sum(e for _, e in xs) < MIN_EXPECTED:
            continue
        a, b = half_bounds(h)
        band = band_of((a - first[p]) / MONTH)
        if band is None:
            continue
        nxt = b + NEXT_MONTHS * MONTH
        la, ga = authored.get(p, []), given.get(p, [])
        land_h, give_h = count(la, a, b), count(ga, a, b)
        land_n, give_n = count(la, b, nxt), count(ga, b, nxt)
        o = owner_at.get(p)
        out.append(dict(
            p=p, h=h, band=band, fi=idx(xs), n=len(xs),
            fi_odd=idx(xs[0::2]) if sum(e for _, e in xs[0::2]) > 0 else None,
            fi_even=idx(xs[1::2]) if sum(e for _, e in xs[1::2]) > 0 else None,
            owner_before=o is not None and o < b,
            owner=o is not None and b <= o < b + OWNER_MONTHS * MONTH,
            share_h=give_h / (give_h + land_h) if give_h + land_h else 0.0,
            share_next=give_n / (give_n + land_n) if give_n + land_n >= MIN_ACTIVE else None,
            thr_h=count(thr.get(p, []), a, b) / 6,
            thr_next=count(thr.get(p, []), b, nxt) / NEXT_MONTHS,
        ))
    med = defaultdict(list)
    for r in out:
        med[(r["h"], r["band"])].append(r["fi"])
    med = {k: st.median(v) for k, v in med.items()}
    for r in out:
        r["rel"] = r["fi"] / med[(r["h"], r["band"])]
        r["lrel"] = math.log2(max(r["rel"], 1 / 16))
    # Fifths of the relative index within each half-year and band.
    grp = defaultdict(list)
    for r in out:
        grp[(r["h"], r["band"])].append(r)
    for g in grp.values():
        g.sort(key=lambda r: r["rel"])
        for i, r in enumerate(g):
            r["q"] = 1 + i * 5 // len(g)
    return out


# --------------------------------------------------------------- models

def solve(m, v):
    """Gaussian elimination with partial pivoting: m x = v."""
    k = len(v)
    a = [row[:] + [v[i]] for i, row in enumerate(m)]
    for i in range(k):
        j = max(range(i, k), key=lambda r: abs(a[r][i]))
        a[i], a[j] = a[j], a[i]
        if abs(a[i][i]) < 1e-12:
            raise ValueError("singular")
        for r in range(k):
            if r != i:
                f = a[r][i] / a[i][i]
                if f:
                    a[r] = [x - f * y for x, y in zip(a[r], a[i])]
    return [a[i][k] / a[i][i] for i in range(k)]


def inverse(m):
    k = len(m)
    cols = [solve(m, [1.0 if i == j else 0.0 for i in range(k)]) for j in range(k)]
    return [[cols[j][i] for j in range(k)] for i in range(k)]


def xtwx(X, w):
    k = len(X[0])
    m = [[0.0] * k for _ in range(k)]
    for x, wi in zip(X, w):
        if not wi:
            continue
        for i in range(k):
            xi = x[i] * wi
            if xi:
                row = m[i]
                for j in range(i, k):
                    row[j] += xi * x[j]
    for i in range(k):
        for j in range(i):
            m[i][j] = m[j][i]
    return m


def cluster_cov(X, resid, groups, bread):
    """Cluster-robust (by person) covariance: bread · Σ_g (X_g'e_g)(X_g'e_g)' · bread."""
    k = len(X[0])
    sg = defaultdict(lambda: [0.0] * k)
    for x, e, g in zip(X, resid, groups):
        s = sg[g]
        for i in range(k):
            s[i] += x[i] * e
    meat = [[0.0] * k for _ in range(k)]
    for s in sg.values():
        for i in range(k):
            for j in range(k):
                meat[i][j] += s[i] * s[j]
    G_, n = len(sg), len(X)
    c = G_ / (G_ - 1) * (n - 1) / (n - k) if G_ > 1 and n > k else 1.0
    bm = [[sum(bread[i][a] * meat[a][j] for a in range(k)) for j in range(k)] for i in range(k)]
    return [[c * sum(bm[i][a] * bread[a][j] for a in range(k)) for j in range(k)] for i in range(k)]


def ols(X, y, groups):
    m = xtwx(X, [1.0] * len(X))
    v = [sum(x[i] * yi for x, yi in zip(X, y)) for i in range(len(X[0]))]
    beta = solve(m, v)
    resid = [yi - sum(b * xi for b, xi in zip(beta, x)) for x, yi in zip(X, y)]
    cov = cluster_cov(X, resid, groups, inverse(m))
    return beta, [math.sqrt(cov[i][i]) for i in range(len(beta))]


def logit(X, y, groups, iters=25):
    k = len(X[0])
    beta = [0.0] * k
    for _ in range(iters):
        p = [1 / (1 + math.exp(-max(-30, min(30, sum(b * xi for b, xi in zip(beta, x)))))) for x in X]
        w = [pi * (1 - pi) for pi in p]
        m = xtwx(X, w)
        for i in range(k):
            m[i][i] += 1e-9
        g = [sum(x[i] * (yi - pi) for x, yi, pi in zip(X, y, p)) for i in range(k)]
        step = solve(m, g)
        beta = [b + s for b, s in zip(beta, step)]
        if max(abs(s) for s in step) < 1e-8:
            break
    p = [1 / (1 + math.exp(-max(-30, min(30, sum(b * xi for b, xi in zip(beta, x)))))) for x in X]
    m = xtwx(X, [pi * (1 - pi) for pi in p])
    cov = cluster_cov(X, [yi - pi for yi, pi in zip(y, p)], groups, inverse(m))
    return beta, [math.sqrt(cov[i][i]) for i in range(k)], p


def auc(scores, y):
    """Probability that a random positive outranks a random negative (ties count half)."""
    order = sorted(range(len(y)), key=lambda i: scores[i])
    ranks = [0.0] * len(y)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        for t in range(i, j + 1):
            ranks[order[t]] = (i + j) / 2 + 1
        i = j + 1
    pos = sum(y)
    neg = len(y) - pos
    return (sum(r for r, yi in zip(ranks, y) if yi) - pos * (pos + 1) / 2) / (pos * neg)


BANDS = [b for _, _, b in TENURE]


def design(rows, extra, with_fi=True, bands=True):
    """Columns: intercept, log2 relative index, log2 CLs, band dummies, half dummies, extra controls."""
    names = ["const"] + (["log2_fi"] if with_fi else []) + ["log2_cls"]
    use_bands = sorted({r["band"] for r in rows}, key=BANDS.index) if bands else []
    names += [f"band:{b}" for b in use_bands[1:]]
    names += [f"half:{h}" for h in BASE[1:]]
    names += [e for e, _ in extra]
    X = []
    for r in rows:
        x = [1.0] + ([r["lrel"]] if with_fi else []) + [math.log2(r["n"])]
        x += [1.0 if r["band"] == b else 0.0 for b in use_bands[1:]]
        x += [1.0 if r["h"] == h else 0.0 for h in BASE[1:]]
        x += [f(r) for _, f in extra]
        X.append(x)
    return names, X


def fits(rows):
    out = []
    groups = {"all": rows, "under 2 years": [r for r in rows if r["band"] in BANDS[:2]],
              "2+ years": [r for r in rows if r["band"] in BANDS[2:]]}
    for gname, rs in groups.items():
        # OWNERS within 18 months, among people not yet in an OWNERS file.
        o = [r for r in rs if not r["owner_before"]]
        y = [1.0 if r["owner"] else 0.0 for r in o]
        ex = [("share_h", lambda r: r["share_h"]), ("log2_thr_h", lambda r: math.log2(1 + r["thr_h"]))]
        names, X = design(o, ex)
        beta, se, p = logit(X, y, [r["p"] for r in o])
        i, j = names.index("log2_fi"), names.index("log2_cls")
        _, X0 = design(o, ex, with_fi=False)
        _, _, p0 = logit(X0, y, [r["p"] for r in o])
        _, Xf = design(o, [], bands=True)
        Xf = [[x[0], x[1]] for x in Xf]       # the index alone
        _, _, pf = logit(Xf, y, [r["p"] for r in o])
        _, Xv = design(o, [])
        bv, sv, _ = logit(Xv, y, [r["p"] for r in o])
        vol = dict(vol_effect=round(math.exp(bv[1]), 3), vol_lo=round(math.exp(bv[1] - 1.96 * sv[1]), 3),
                   vol_hi=round(math.exp(bv[1] + 1.96 * sv[1]), 3))
        out.append(dict(**vol, group=gname, outcome="owners", n=len(o), people=len({r["p"] for r in o}),
                        base_rate=round(sum(y) / len(y), 4),
                        effect=round(math.exp(beta[i]), 3), lo=round(math.exp(beta[i] - 1.96 * se[i]), 3),
                        hi=round(math.exp(beta[i] + 1.96 * se[i]), 3),
                        cls_effect=round(math.exp(beta[j]), 3),
                        cls_lo=round(math.exp(beta[j] - 1.96 * se[j]), 3),
                        cls_hi=round(math.exp(beta[j] + 1.96 * se[j]), 3),
                        auc_fi=round(auc(pf, y), 3), auc_controls=round(auc(p0, y), 3),
                        auc_both=round(auc(p, y), 3)))
        # Review share over the next 12 months, people still active.
        s = [r for r in rs if r["share_next"] is not None]
        names, X = design(s, [("share_h", lambda r: r["share_h"])])
        beta, se = ols(X, [r["share_next"] for r in s], [r["p"] for r in s])
        i, j = names.index("log2_fi"), names.index("log2_cls")
        _, Xv = design(s, [])
        bv, sv = ols(Xv, [r["share_next"] for r in s], [r["p"] for r in s])
        vol = dict(vol_effect=round(bv[1], 4), vol_lo=round(bv[1] - 1.96 * sv[1], 4),
                   vol_hi=round(bv[1] + 1.96 * sv[1], 4))
        out.append(dict(**vol, group=gname, outcome="review_share", n=len(s), people=len({r["p"] for r in s}),
                        base_rate=round(st.mean(r["share_next"] for r in s), 4),
                        effect=round(beta[i], 4), lo=round(beta[i] - 1.96 * se[i], 4),
                        hi=round(beta[i] + 1.96 * se[i], 4),
                        cls_effect=round(beta[j], 4), cls_lo=round(beta[j] - 1.96 * se[j], 4),
                        cls_hi=round(beta[j] + 1.96 * se[j], 4)))
        # Feedback given: log2(1 + threads a month) over the next 12 months, so the effect is a ratio.
        names, X = design(rs, [("log2_thr_h", lambda r: math.log2(1 + r["thr_h"]))])
        beta, se = ols(X, [math.log2(1 + r["thr_next"]) for r in rs], [r["p"] for r in rs])
        i, j = names.index("log2_fi"), names.index("log2_cls")
        _, Xv = design(rs, [])
        bv, sv = ols(Xv, [math.log2(1 + r["thr_next"]) for r in rs], [r["p"] for r in rs])
        vol = dict(vol_effect=round(2 ** bv[1], 3), vol_lo=round(2 ** (bv[1] - 1.96 * sv[1]), 3),
                   vol_hi=round(2 ** (bv[1] + 1.96 * sv[1]), 3))
        out.append(dict(**vol, group=gname, outcome="threads_given", n=len(rs), people=len({r["p"] for r in rs}),
                        base_rate=round(st.median(r["thr_next"] for r in rs), 3),
                        effect=round(2 ** beta[i], 3), lo=round(2 ** (beta[i] - 1.96 * se[i]), 3),
                        hi=round(2 ** (beta[i] + 1.96 * se[i]), 3),
                        cls_effect=round(2 ** beta[j], 3), cls_lo=round(2 ** (beta[j] - 1.96 * se[j]), 3),
                        cls_hi=round(2 ** (beta[j] + 1.96 * se[j]), 3)))
    return out


def fifths(rows):
    out = []
    for gname, sel in (("all", lambda r: True), ("under 2 years", lambda r: r["band"] in BANDS[:2]),
                       ("2+ years", lambda r: r["band"] in BANDS[2:])):
        for q in range(1, 6):
            s = [r for r in rows if r["q"] == q and sel(r)]
            o = [r for r in s if not r["owner_before"]]
            sh = [r["share_next"] for r in s if r["share_next"] is not None]
            if len(s) < MIN_PEOPLE:
                continue
            out.append(dict(group=gname, fifth=q, n=len(s), people=len({r["p"] for r in s}),
                            fi=round(st.median(r["rel"] for r in s), 3),
                            cls=round(st.median(r["n"] for r in s), 1),
                            owners=round(sum(r["owner"] for r in o) / len(o), 4) if len(o) >= MIN_PEOPLE else None,
                            owners_n=len(o),
                            share=round(st.median(sh), 4) if len(sh) >= MIN_PEOPLE else None,
                            share_n=len(sh),
                            threads=round(st.mean(r["thr_next"] for r in s), 3),
                            threads_p50=round(st.median(r["thr_next"] for r in s), 3),
                            gives=round(sum(r["thr_next"] >= 1 for r in s) / len(s), 4)))
    return out


def reliability(rows):
    """Split-half reliability of log2 index (alternate CLs), Spearman–Brown corrected."""
    pr = [(math.log2(max(r["fi_odd"], 1 / 16)), math.log2(max(r["fi_even"], 1 / 16)))
          for r in rows if r["fi_odd"] and r["fi_even"]]
    a, b = zip(*pr)
    r = st.correlation(a, b)
    return round(2 * r / (1 + r), 3), len(pr)


def summary(rows):
    rel, n = reliability(rows)
    o = [r for r in rows if not r["owner_before"]]
    return dict(person_halves=len(rows), people=len({r["p"] for r in rows}),
                owner_eligible=len(o), owner_before=round(sum(r["owner_before"] for r in rows) / len(rows), 4),
                reliability=rel, reliability_n=n,
                median_cls=st.median(r["n"] for r in rows))


def compute(args):
    args.ai_marked = None
    if getattr(args, "cache", None) and os.path.exists(args.cache):
        loaded = pickle.load(open(args.cache, "rb"))
    else:
        loaded = load(args)
        if getattr(args, "cache", None):
            pickle.dump(loaded, open(args.cache, "wb"))
    rows = rows_of(*loaded)
    f = fits(rows)
    return dict(fb_predict_fifths=fifths(rows), fb_predict_fit=f, fb_predict_summary=[summary(rows)])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--first-commit", help="default: commits.sqlite")
    ap.add_argument("--owners-added", help="default: commits.sqlite")
    ap.add_argument("--mech", help="default: commits.sqlite")
    ap.add_argument("--cache", help="pickle of the loaded data, to rerun quickly")
    ap.add_argument("--out", help="write the datasets here as JSON")
    args = ap.parse_args()
    new = compute(args)
    for k, v in new.items():
        print(f"\n{k}", file=sys.stderr)
        for r in v:
            print(" ", r, file=sys.stderr)
    show(new, args.out)


if __name__ == "__main__":
    main()
