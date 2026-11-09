"""Review ROI, Part 1 follow-up (docs/review-roi-part1.md, "Follow-up"):

1. reverts review could plausibly prevent (crash/functional, perf/size) vs
   CI-type reverts (compile/link, test failure) as separate outcomes;
2. the first approver's weekly load as an outside source of review depth
   (first stage, reduced form, IV ratio, unrelated reverts as a control);
3. "glance" approvals (approved < 15 min after sent, no thread), votes on
   disk only;
4. the rubber-stamp result on CLs with votes on disk only.

Reads the table from scripts/review_roi_table.py (with the load columns)
and revert_reasons.tsv; reuses the models of scripts/review_roi_part1.py.

  export COSH_DATA_DIR=/home/rbagent/projects/cosh/data/private
  S=/home/rbagent/.claude/jobs/9e4a825c/tmp/scratch/part1
  nice -n 5 python3 scripts/review_roi_part1_followup.py --table $S/cl_table_f.sqlite \
      --reasons $S/../reverts/revert_reasons.tsv --json $S/followup.json > $S/followup.txt

About 10 minutes.
"""

import argparse
import json
import math
import sqlite3
import statistics as st
import sys
import os
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import review_roi_part1 as P  # noqa: E402

say, log = P.say, P.log
OUT = {}
PREVENT = {"crash_or_functional", "perf_or_size_regression"}
CI_TYPE = {"compile_or_link", "test_failure"}


def extra(path, D):
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    cols = ["lresid_threads", "sent_at", "first_appr_at", "load_cls_log2", "load_thr_log2", "load_active_weeks",
            "first_appr_threads"]
    for c in cols:
        D[c] = []
    for r in db.execute(f"SELECT {', '.join(cols)} FROM cl ORDER BY change_number"):
        for c, v in zip(cols, r):
            D[c].append(v)


def outcomes(D, n, path):
    cls_of = {}
    with open(path) as f:
        head = f.readline().rstrip("\n").split("\t")
        for line in f:
            r = dict(zip(head, line.rstrip("\n").split("\t")))
            cls_of[(r["reverted_sha"], r["revert_sha"])] = r["reason_class"]
    y = D["rev30"]
    rc = [cls_of.get((D["sha"][i], D["revert_sha"][i])) if y[i] else None for i in range(n)]
    D["rev30_prevent"] = [int(c in PREVENT) for c in rc]
    D["rev30_ci"] = [int(c in CI_TYPE) for c in rc]
    D["rev30_unrelated"] = [int(c in P.UNRELATED) for c in rc]


def eff(r):
    name = next(iter(r["effects"]))
    e = r["effects"][name]
    return dict(odds_ratio=e["odds_ratio"], ci=[e["or_lo"], e["or_hi"]], unit=e["unit"], sd=e["sd"],
                per_1000_p25_to_p75=round(1000 * e["rate_diff_p75_minus_p25"], 2),
                per_1000_ci=[round(1000 * e["rate_diff_lo"], 2), round(1000 * e["rate_diff_hi"], 2)],
                base_rate=r["base_rate"], cls=r["n_sample"], cases=r["cases"])


def row(lbl, r):
    e = eff(r)
    say(f"  {lbl:44} OR {e['odds_ratio']:.3f} ({e['ci'][0]:.3f}-{e['ci'][1]:.3f}) {e['unit']:>22}; "
        f"p25->p75 {e['per_1000_p25_to_p75']:+.2f} per 1,000 ({e['per_1000_ci'][0]:+.2f} to {e['per_1000_ci'][1]:+.2f}); "
        f"base {1000 * e['base_rate']:.2f}/1,000, {e['cases']:,} cases")
    return e


# --------------------------------------------------------------- item 1

def item1(Fi, D, n):
    say("\n## 1. Reverts review could plausibly prevent vs CI-type reverts")
    res = {}
    for outc, lab in (("rev30_prevent", "crash/functional + perf/size"), ("rev30_ci", "compile/link + test failure"),
                      ("rev30", "all 30-day reverts")):
        say(f"\noutcome: {lab} ({sum(D[outc]):,} reverts)")
        res[outc] = {}
        for ex in ("threads", "rubber_stamp", "habit_log_first", "habit_first"):
            res[outc][ex] = row(P.EXPOSURES[ex][2][:44], Fi.fit(outc, [ex]))
    OUT["1_outcome_by_reason"] = res


# --------------------------------------------------------------- item 2

def sparse_ols(X, y, k):
    H = [[0.0] * k for _ in range(k)]
    g = [0.0] * k
    for (ix, vx), yi in zip(X, y):
        m = len(ix)
        for a in range(m):
            ja, va = ix[a], vx[a]
            g[ja] += va * yi
            Hr = H[ja]
            for b in range(a, m):
                Hr[ix[b]] += va * vx[b]
    for i in range(k):
        for j in range(i):
            H[i][j] = H[j][i]
        H[i][i] += 1e-9
    return P.F.solve(H, g), H


def ols_infl(X, y, groups, k, j):
    """OLS coefficient j and its per-cluster influence sums (bread row . sum x e)."""
    beta, H = sparse_ols(X, y, k)
    bj = P.F.solve(H, [1.0 if i == j else 0.0 for i in range(k)])
    infl = defaultdict(float)
    for (ix, vx), yi, gi in zip(X, y, groups):
        e = yi - sum(beta[t] * v for t, v in zip(ix, vx))
        infl[gi] += e * sum(bj[t] * v for t, v in zip(ix, vx))
    G, nn = len(infl), len(X)
    c = G / (G - 1) * (nn - 1) / (nn - k)
    return beta[j], infl, c


def item2(Fi, D, n):
    say("\n## 2. The first approver's weekly load as an outside source of review depth")
    des = Fi.des
    keep = [i for i in range(n) if D["load_cls_log2"][i] is not None and (D["load_active_weeks"][i] or 0) >= 4
            and D["habit_log_first"][i] is not None]
    grp = defaultdict(list)
    for i in keep:
        grp[(D["first_approver_id"][i], D["half"][i])].append(i)
    res = dict(cls=len(keep), approver_halves=len(grp))
    say(f"CLs with a first approver active in 4+ weeks of the half-year: {len(keep):,}; approver-halves {len(grp):,}")
    for lname, col in (("CLs approved that week", "load_cls_log2"), ("threads written that week (other CLs)", "load_thr_log2")):
        dm = [None] * n
        for g, idx in grp.items():
            m = st.mean(D[col][i] for i in idx)
            for i in idx:
                dm[i] = D[col][i] - m
        D["load_dm"] = dm
        sd = st.pstdev([dm[i] for i in keep])
        q25, q75 = P.q([dm[i] for i in keep], .25), P.q([dm[i] for i in keep], .75)
        say(f"\n### load = log2(this week's {lname} / the approver's median active week), demeaned within "
            f"approver x half-year; SD {sd:.3f}, p25 {q25:.3f}, p75 {q75:.3f}")
        k0 = des.k
        X = [(des.rows[i][0] + [k0], des.rows[i][1] + [dm[i]]) for i in keep]
        groups = [D["first_approver_id"][i] for i in keep]
        r = dict(sd=sd, p25=q25, p75=q75)
        # First stage (OLS, approver-clustered): this CL's review on load.
        fs = {}
        for yname, yv in (("residual log1p threads", [D["lresid_threads"][i] for i in keep]),
                          ("log1p threads by the first approver", [math.log1p(D["first_appr_threads"][i] or 0) for i in keep]),
                          ("rubber stamp", [D["rubber_stamp"][i] for i in keep])):
            b, infl, c = ols_infl(X, yv, groups, k0 + 1, k0)
            se = math.sqrt(c * sum(v * v for v in infl.values()))
            fs[yname] = dict(coef=b, se=se, t=b / se, F=(b / se) ** 2, infl=infl, c=c)
            say(f"  first stage, {yname:40} per doubling of load: {b:+.4f} (SE {se:.4f}), F = {(b / se) ** 2:.1f}")
        # Reduced form: LPM and logistic.
        rf = {}
        for outc in ("rev30", "rev30_prevent", "rev30_ci", "rev30_unrelated"):
            yv = [D[outc][i] for i in keep]
            b, infl, c = ols_infl(X, yv, groups, k0 + 1, k0)
            se = math.sqrt(c * sum(v * v for v in infl.values()))
            lg = Fi.fit(outc, [("load_dm", "load_dm", "lin", "load (demeaned log2)")], subset=lambda i: dm[i] is not None
                        and (D["load_active_weeks"][i] or 0) >= 4 and D["habit_log_first"][i] is not None,
                        cluster="first_approver_id")
            e = lg["effects"]["load_dm"]
            rf[outc] = dict(lpm_per_1000_per_doubling=round(1000 * b, 3), lpm_ci=[round(1000 * (b - 1.96 * se), 3),
                                                                                  round(1000 * (b + 1.96 * se), 3)],
                            logit_or_per_sd=e["odds_ratio"], logit_ci=[e["or_lo"], e["or_hi"]])
            say(f"  reduced form, {outc:16} LPM {1000 * b:+.3f} per 1,000 per doubling of load "
                f"({1000 * (b - 1.96 * se):+.3f} to {1000 * (b + 1.96 * se):+.3f}); logistic OR per SD {e['odds_ratio']:.3f} "
                f"({e['or_lo']:.3f}-{e['or_hi']:.3f})")
            # IV (Wald) with the residual-threads first stage, delta-method SE from the cluster influences.
            f1 = fs["residual log1p threads"]
            a, bb = b, f1["coef"]
            va = c * sum(v * v for v in infl.values())
            vb = f1["c"] * sum(v * v for v in f1["infl"].values())
            cab = math.sqrt(c * f1["c"]) * sum(infl.get(g, 0.0) * f1["infl"].get(g, 0.0) for g in set(infl) | set(f1["infl"]))
            iv = a / bb
            ivse = math.sqrt(va / bb ** 2 + a * a * vb / bb ** 4 - 2 * a * cab / bb ** 3)
            rf[outc]["iv_per_1000_per_log1p_thread"] = round(1000 * iv, 2)
            rf[outc]["iv_ci"] = [round(1000 * (iv - 1.96 * ivse), 2), round(1000 * (iv + 1.96 * ivse), 2)]
            say(f"      IV (reduced form / first stage on residual log1p threads): {1000 * iv:+.2f} reverts per 1,000 "
                f"per +1 log1p thread ({1000 * (iv - 1.96 * ivse):+.2f} to {1000 * (iv + 1.96 * ivse):+.2f})")
        r["first_stage"] = {k: {kk: round(vv, 5) for kk, vv in v.items() if kk not in ("infl", "c")} for k, v in fs.items()}
        r["reduced_form"] = rf
        res[col] = r
        log(f"item 2 {col}")
    OUT["2_weekly_load"] = res


# --------------------------------------------------------------- items 3, 4

def item3(Fi, D, n):
    say("\n## 3. Glance approvals (votes on disk only)")
    vp = [D["approver_source"][i] == "votes" for i in range(n)]
    gl = [None] * n
    for i in range(n):
        if vp[i] and D["sent_at"][i] and D["first_appr_at"][i]:
            gl[i] = int(D["threads"][i] == 0 and D["first_appr_at"][i] - D["sent_at"][i] < 900)
    D["glance"] = gl
    idx = [i for i in range(n) if gl[i] is not None]
    ng = sum(gl[i] for i in idx)
    rate = lambda s: sum(D["rev30"][i] for i in s) / len(s)
    g1 = [i for i in idx if gl[i]]
    g0 = [i for i in idx if not gl[i]]
    rs0 = [i for i in idx if not gl[i] and D["threads"][i] == 0]
    say(f"votes-present CLs with sent and approval times: {len(idx):,} of {sum(vp):,}; glance {ng:,} ({100 * ng / len(idx):.1f}%); "
        f"30-day revert {100 * rate(g1):.2f}% vs {100 * rate(g0):.2f}% for the rest "
        f"(slower rubber stamps {100 * rate(rs0):.2f}%, n {len(rs0):,})")
    res = dict(cls=len(idx), glance=ng, rate_glance=round(rate(g1), 4), rate_rest=round(rate(g0), 4),
               rate_slow_rubber_stamp=round(rate(rs0), 4), slow_rubber_stamps=len(rs0))
    ex = ("glance", "glance", "bin", "glance approval (< 15 min, no thread)")
    res["logit_vs_rest"] = row("glance vs all other (D3 controls)", Fi.fit("rev30", [ex], subset=lambda i: gl[i] is not None))
    res["logit_vs_slow_rubber_stamps"] = row("glance vs slower rubber stamps", Fi.fit(
        "rev30", [ex], subset=lambda i: gl[i] is not None and D["threads"][i] == 0))
    # D5 style: author x dir3 x half x size10 sets with exactly one revert.
    sets = defaultdict(list)
    for i in idx:
        sets[(D["author_id"][i], D["dir3"][i], D["half"][i], D["size10"][i])].append(i)
    data, hi, lo = [], 0, 0
    for k, v in sets.items():
        if len(v) < 2 or sum(D["rev30"][i] for i in v) != 1 or len({gl[i] for i in v}) < 2:
            continue
        xs = [(float(gl[i]), D["rev30"][i]) for i in v]
        data.append((k[0], xs))
        xc = next(x for x, yy in xs if yy)
        mc = st.mean(x for x, yy in xs if not yy)
        hi += xc > mc
        lo += xc < mc
    b, se = P.clogit(data)
    res["matched_sets"] = dict(sets=len(data), cond_or=round(math.exp(b), 3), ci=[round(math.exp(b - 1.96 * se), 3),
                                                                              round(math.exp(b + 1.96 * se), 3)],
                               reverted_was_glance=hi, reverted_was_not=lo, sign_p=round(P.sign_p(hi, lo), 4))
    say(f"  matched sets (author x dir3 x half x size10, one revert, glance varies): {len(data):,}; conditional OR "
        f"{math.exp(b):.3f} ({math.exp(b - 1.96 * se):.3f}-{math.exp(b + 1.96 * se):.3f}); reverted CL was the glance one "
        f"{hi:,} vs not {lo:,}")
    OUT["3_glance"] = res


def item4(Fi, D, n, reps):
    say("\n## 4. Rubber stamp, CLs with votes on disk only")
    vp = [i for i in range(n) if D["approver_source"][i] == "votes"]
    keys = P.stratum_keys(D, n)
    rows = [(D["author_id"][i], keys[i], D["rubber_stamp"][i] > 0, D["rev30"][i]) for i in vp]
    raw = P.crude_or(rows)
    o, lo, hi, ns = P.mh_boot(rows, reps)
    r1 = [D["rev30"][i] for i in vp if D["rubber_stamp"][i]]
    r0 = [D["rev30"][i] for i in vp if not D["rubber_stamp"][i]]
    say(f"votes-present CLs {len(vp):,}; rubber stamps {len(r1):,} ({100 * len(r1) / len(vp):.1f}%), revert "
        f"{100 * st.mean(r1):.2f}% vs {100 * st.mean(r0):.2f}%; raw OR {P.ci(*raw)}, MH OR {P.ci(o, lo, hi)} ({ns:,} strata)")
    res = dict(cls=len(vp), rubber_stamps=len(r1), rate_rs=round(st.mean(r1), 4), rate_rest=round(st.mean(r0), 4),
               raw_or=P.r3(raw[0]), raw_ci=[P.r3(raw[1]), P.r3(raw[2])], mh_or=P.r3(o), mh_ci=[P.r3(lo), P.r3(hi)])
    vps = set(vp)
    res["logit"] = row("rubber stamp (D3 controls), votes only", Fi.fit("rev30", ["rubber_stamp"], subset=lambda i: i in vps))
    OUT["4_rubber_stamp_votes_only"] = res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", required=True)
    ap.add_argument("--reasons", required=True)
    ap.add_argument("--json", required=True)
    ap.add_argument("--reps", type=int, default=200)
    args = ap.parse_args()
    D, meta, n = P.load(args.table)
    extra(args.table, D)
    outcomes(D, n, args.reasons)
    des = P.Design(D, n)
    Fi = P.Fitter(D, n, des, 1.0)
    log(f"loaded {n:,} CLs")

    def save():
        with open(args.json, "w") as f:
            json.dump(OUT, f, indent=1, default=str)
    item1(Fi, D, n)
    save()
    log("item 1")
    item4(Fi, D, n, args.reps)
    save()
    log("item 4")
    item3(Fi, D, n)
    save()
    log("item 3")
    item2(Fi, D, n)
    save()
    log("done")


if __name__ == "__main__":
    main()
