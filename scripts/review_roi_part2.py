"""Return on code review, part 2 (docs/review-roi.md, H2a–H2c): does review
today make later changes easier and safer? Findings in
docs/review-roi-part2.md.

- H2a/H2b, directory panels: dir3 × half-year cells (quarters as a check).
  Review depth in period t (mean feedback index, addressed threads per 100
  lines, rubber-stamp share) against outcomes in t+1 (and t+2): 30-day
  revert rate (H2a) and review cost (H2b: threads per 100 lines, rounds,
  interdiff share, median hours to first review, attention hours per CL).
  Directory fixed effects by within-transformation (demeaning by dir3) plus
  period dummies; controls: outcome(t), log CLs, log lines, share of CLs by
  authors under 1 year; standard errors clustered by dir3. Raw
  cross-sectional correlations are printed next to them.
  A placebo (lag -1) regresses the outcome one period *before* on depth(t)
  with the same controls: review cannot act backwards, so an estimate there
  measures the persistence and confounding the forward estimates carry.
- H2c, author dose-response: authors whose first commit is 2023-07 ..
  2025-09. Addressed and unaddressed threads received per CL in months 1–12
  (relative to the 2023–24 norm for size × dir2) against months 13–24:
  feedback index, 30-day revert rate, CLs landed, threads given. Errors
  clustered by author.

Unit CL: merged, human-owned (not a Bot-Commit, owner not a bot), not
mechanical, not a revert or reland, landed on main 2023-07-01 .. 2026-09-30.

Offline. Reads balance.sqlite, balance-git.sqlite and derived.sqlite
(threads' root accounts only, never comment text) read-only. Prints and
writes aggregates only; nothing per person or per CL is written.

  export COSH_DATA_DIR=/home/rbagent/projects/cosh/data/private
  I=data/private/review_feedback_inputs
  S=data/private/scratch/review_roi/part2
  nice -n 5 python3 scripts/review_roi_part2.py --first-commit $I/first_commit.txt \\
      --mech $I/mech.jsonl --out $S/part2_panels.json [--cache $S/part2_cache.pkl]

Without --first-commit, tenure starts at the first commit since 2017 in
balance-git.sqlite; without --mech, a CL with 50 or more files counts as
mechanical (the provisional rule). The output records which rules ran.
About 15 s to load (a warm --cache skips it), then about 15 s; both scripts call os.nice(5).
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
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
try:
    import balance_feedback_predicts as FP  # noqa: E402
except ImportError:          # this worktree predates it; the main checkout has it
    sys.path.append("/home/rbagent/projects/cosh/scripts")
    import balance_feedback_predicts as FP  # noqa: E402
import balance_analysis as A  # noqa: E402
import balance_growth as G  # noqa: E402
from cosh import balance, store  # noqa: E402

DAY = 86400
MONTH = 365.25 * DAY / 12
START = datetime(2023, 7, 1, tzinfo=timezone.utc).timestamp()
END = datetime(2026, 10, 1, tzinfo=timezone.utc).timestamp()      # landed before
REVERT_DAYS = 30
MIN_CELL = 30


def ts(y, m):
    return datetime(y, m, 1, tzinfo=timezone.utc).timestamp()


def period(t, kind):
    d = datetime.fromtimestamp(t, timezone.utc)
    return d.year * 2 + (d.month > 6) if kind == "half" else d.year * 4 + (d.month - 1) // 3


def pname(p, kind):
    return f"{p // 2}H{p % 2 + 1}" if kind == "half" else f"{p // 4}Q{p % 4 + 1}"


# ------------------------------------------------------------------ load

def load(args):
    t0 = time.time()
    bdb = A.ro(balance.db_path("cl"))
    gdb = A.ro(balance.db_path("git"))
    # Commits: author, landed time, approvers, flags.
    g_by_sha, first_git, n_email = {}, {}, {}
    for sha, email, at, n, bot, rb, rv, rl, files in gdb.execute(
            "SELECT sha, author_email, landed_at, change_number, is_bot, reviewed_by, reverts_sha, is_reland, files "
            "FROM gcommits"):
        human = not bot and not A.is_bot_email(email)
        if human:
            e = A.person(email)
            first_git[e] = min(at, first_git.get(e, at))
            if n:
                n_email[n] = e
        if at >= START - 400 * DAY:
            g_by_sha[sha] = (email, at, n, bot, rb, rv is not None, rl)
    print(f"  commits loaded {time.time() - t0:.0f}s", file=sys.stderr, flush=True)
    cols = ("change_number, owner, owner_email, status, closed_at, ins, dels, sha, files, is_revert, is_reland, "
            "reverted_at, threads, addressed, first_review_at, sent_at, rounds, reviewer_wait_h, lines_changed, "
            "lines_final")
    cls = []
    for r in bdb.execute(f"SELECT {cols} FROM cl WHERE status = 'MERGED' AND sha IS NOT NULL"):
        cls.append(r)
    # Identities: Chromium's two domains, plus owner/author aliases (balance_growth.alias_pairs).
    ids = G.Ids()
    own = defaultdict(Counter)
    for r in cls:
        e = n_email.get(r[0])
        if e and r[2] and not A.is_bot_email(r[2]):
            own[e][A.person(r[2])] += 1
    for b, cnt in own.items():
        tot = sum(cnt.values())
        for a, k in cnt.items():
            if a != b and k >= 3 and k / tot >= 0.5:
                ids.union(a, b)
    if args.first_commit and os.path.exists(args.first_commit):
        first = {}
        for e, t in A.load_first(args.first_commit).items():
            k = ids.find(e)
            first[k] = min(t, first.get(k, t))
        tenure_rule = "first_commit.txt (all history)"
    else:
        first = {}
        for e, t in first_git.items():
            k = ids.find(e)
            first[k] = min(t, first.get(k, t))
        tenure_rule = "first commit since 2017 in balance-git.sqlite (provisional)"
    if args.mech and os.path.exists(args.mech):
        mech = set()
        for line in open(args.mech):
            n, files, threads, rep, lines = json.loads(line)
            if files >= 100 or (rep is not None and rep >= 0.8):
                mech.add(n)
        mech_rule = "mech.jsonl: >= 100 files, or >= 10 files with repetition >= 0.8"
    else:
        mech = None
        mech_rule = "provisional: >= 50 files"
    print(f"  CLs loaded {time.time() - t0:.0f}s", file=sys.stderr, flush=True)
    units, other = [], {}
    for (n, owner, oe, status, closed, ins, dels, sha, files, isrev, isrel, rvat, thr, addr, fr, sent,
         rounds, att, lch, lfin) in cls:
        g = g_by_sha.get(sha)
        if not g or not oe or A.is_bot_email(oe):
            continue
        email, landed, gn, bot, rb, g_rev, g_rel = g
        if bot or isrev or isrel or g_rev or g_rel:
            continue
        pid = ids.find(oe)
        approvers = sorted({ids.find(x) for x in json.loads(rb)} - {pid}) if rb else []
        other[n] = (pid, landed)                       # for threads given (H2c)
        if not (START <= landed < END):
            continue
        if (mech is not None and n in mech) or (mech is None and (files or 0) >= 50):
            continue
        lines = (ins or 0) + (dels or 0)
        units.append(dict(
            n=n, pid=pid, at=landed, lines=lines, files=files or 0, sb=G.size10(lines),
            rev=1 if rvat and rvat - landed <= REVERT_DAYS * DAY else 0,
            threads=thr, addressed=addr,
            rounds=rounds, att=att,
            lat=(fr - sent) / 3600 if fr and sent and fr >= sent else None,
            ish=min(2.0, lch / lfin) if lch is not None and lfin else None,
            approvers=approvers))
    print(f"  {len(units):,} unit CLs {time.time() - t0:.0f}s", file=sys.stderr, flush=True)
    # Main 3-level directory: most lines (then files) in cl_dirs.
    want = {u["n"] for u in units}
    best = {}
    for n, d, f, ln in bdb.execute("SELECT change_number, dir, files, lines FROM cl_dirs"):
        if n in want:
            b = best.get(n)
            if b is None or (ln, f, d) > b[:3]:
                best[n] = (ln, f, d)
    for u in units:
        d = best.get(u["n"], (0, 0, "(root)/"))[2]
        u["d3"] = d
        u["d2"] = "/".join(d.split("/")[:2]) + "/" if d.count("/") >= 2 else d
    # Threads each person started on other people's merged CLs (H2c "threads given").
    ddb = A.ro(os.path.join(store.DATA_DIR, store.DERIVED_FILE))
    emails = dict(ddb.execute("SELECT account_id, email FROM accounts"))
    bots = {a for a, in ddb.execute("SELECT account_id FROM accounts WHERE is_bot = 1")}
    pid_of, given = {}, defaultdict(list)
    for n, acct in ddb.execute("SELECT change_number, root_account FROM threads"):
        o = other.get(n)
        if not o or acct in bots:
            continue
        e = emails.get(acct)
        if not e or A.is_bot_email(e):
            continue
        p = pid_of.get(acct)
        if p is None:
            p = pid_of[acct] = ids.find(e)
        if p != o[0]:
            given[p].append(o[1])
    print(f"  threads given loaded {time.time() - t0:.0f}s", file=sys.stderr, flush=True)
    return dict(units=units, first=first, given=dict(given), tenure_rule=tenure_rule, mech_rule=mech_rule)


def norms(units):
    """2023–24 means of threads and addressed threads per (size10, dir2), at least 30 CLs, else size10."""
    out = {}
    for key in ("threads", "addressed", "unaddr"):
        g, b = defaultdict(list), defaultdict(list)
        for u in units:
            if datetime.fromtimestamp(u["at"], timezone.utc).year in (2023, 2024):
                v = u[key] if key != "unaddr" else u["threads"] - u["addressed"]
                g[(u["sb"], u["d2"])].append(v)
                b[u["sb"]].append(v)
        gm = {k: st.mean(v) for k, v in g.items() if len(v) >= 30}
        bm = {k: st.mean(v) for k, v in b.items()}
        for u in units:
            u["exp_" + key] = gm.get((u["sb"], u["d2"]), bm.get(u["sb"], 1.0)) or 1e-3
    for u in units:
        u["fi"] = u["threads"] / u["exp_threads"]


# ------------------------------------------------------------------ panels

def cells(units, first, kind):
    by = defaultdict(list)
    for u in units:
        by[(u["d3"], period(u["at"], kind))].append(u)
    out = {}
    for (d, p), us in by.items():
        lines = sum(u["lines"] for u in us) or 1
        lat = [u["lat"] for u in us if u["lat"] is not None]
        rounds = [u["rounds"] for u in us if u["rounds"] is not None]
        ish = [u["ish"] for u in us if u["ish"] is not None]
        att = [u["att"] for u in us if u["att"] is not None]
        appr = Counter(a for u in us for a in u["approvers"])
        new = sum(1 for u in us if u["pid"] in first and u["at"] - first[u["pid"]] < 12 * MONTH)
        out[(d, p)] = dict(
            n=len(us), lines=lines,
            fi=st.mean(u["fi"] for u in us),
            addr100=100 * sum(u["addressed"] for u in us) / lines,
            stamp=sum(u["threads"] == 0 for u in us) / len(us),
            rev=100 * sum(u["rev"] for u in us) / len(us),
            thr100=100 * sum(u["threads"] for u in us) / lines,
            rounds=st.mean(rounds) if rounds else None,
            ish=st.mean(ish) if ish else None,
            lat=st.median(lat) if lat else None,
            att=st.mean(att) if att else None,
            approvers=len(appr), appr=appr,
            newshare=new / len(us))
    # Turnover: share of approvals in p by people who gave none in p-1 in the same directory.
    for (d, p), c in out.items():
        prev = out.get((d, p - 1))
        tot = sum(c["appr"].values())
        c["turnover"] = (sum(k for a, k in c["appr"].items() if a not in prev["appr"]) / tot) \
            if prev and tot and prev["n"] >= MIN_CELL else None
    for c in out.values():
        del c["appr"]
    return out


EXPOSURES = [("fi", "mean feedback index"), ("addr100", "addressed threads per 100 lines"),
             ("stamp", "rubber-stamp share")]
OUTCOMES = [("rev", "30-day revert rate (pp)"), ("thr100", "threads per 100 lines"), ("rounds", "mean rounds"),
            ("ish", "mean interdiff share"), ("lat", "median hours to first review"),
            ("att", "mean attention hours per CL"), ("fi", "mean feedback index (t+k)")]


def panel_rows(cs, lag, kind):
    rows = []
    for (d, p), c in cs.items():
        f = cs.get((d, p + lag))
        if c["n"] < MIN_CELL or not f or f["n"] < MIN_CELL:
            continue
        lo = period(START, kind)
        hi = period(END - 1, kind)
        if min(p, p + lag) < lo or max(p, p + lag) > hi:
            continue
        rows.append(dict(d=d, p=p, t=c, f=f))
    return rows


def demean(rows, cols):
    """Within-directory transformation of the columns (list of lists by row)."""
    by = defaultdict(list)
    for i, r in enumerate(rows):
        by[r["d"]].append(i)
    out = [list(c) for c in cols]
    for idx in by.values():
        for j in range(len(cols[0])):
            m = sum(cols[i][j] for i in idx) / len(idx)
            for i in idx:
                out[i][j] = cols[i][j] - m
    return out


def fit(rows, xk, yk, kind, fe=True, lagged=True, controls=True):
    """outcome(t+k) on depth(t). Returns coefficient per within-dir SD of the exposure and its CI."""
    rows = [r for r in rows if r["t"][xk] is not None and r["f"][yk] is not None and r["t"][yk] is not None
            and r["t"]["approvers"] is not None]
    if fe:
        cnt = Counter(r["d"] for r in rows)
        rows = [r for r in rows if cnt[r["d"]] >= 2]
    if len(rows) < 30:
        return None
    periods = sorted({r["p"] for r in rows})
    names = ["x"]
    X = []
    for r in rows:
        x = [r["t"][xk]]
        if lagged and yk != xk:
            x.append(r["t"][yk])
        if controls:
            x += [math.log(r["t"]["n"]), math.log(r["t"]["lines"]), r["t"]["newshare"]]
        x += [1.0 if r["p"] == p else 0.0 for p in periods[1:]]
        if not fe:
            x.append(1.0)
        X.append(x)
    y = [r["f"][yk] for r in rows]
    if fe:
        Z = demean(rows, [x + [yy] for x, yy in zip(X, y)])
        X = [z[:-1] for z in Z]
        y = [z[-1] for z in Z]
    sd = st.pstdev([x[0] for x in X]) if fe else st.pstdev([r["t"][xk] for r in rows])
    try:
        beta, se = FP.ols(X, y, [r["d"] for r in rows])
    except ValueError:
        return None
    b, s = beta[0] * sd, se[0] * sd
    return dict(b=b, lo=b - 1.96 * s, hi=b + 1.96 * s, n=len(rows), dirs=len({r["d"] for r in rows}),
                sd=sd, b_unit=beta[0], se_unit=se[0])


def corr(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    return sxy / math.sqrt(sxx * syy) if sxx and syy else None


def panels(units, first, kind):
    cs = cells(units, first, kind)
    res = dict(kind=kind, cells_total=len(cs), cells_ge_min=sum(c["n"] >= MIN_CELL for c in cs.values()))
    # -1: placebo, depth(t) against the outcome a period *earlier*; quarters also look 4 ahead (a year, as half lag 2)
    for lag in (1, 2, -1) + ((4,) if kind == "quarter" else ()):
        rows = panel_rows(cs, lag, kind)
        res[f"lag{lag}_pairs"] = len(rows)
        res[f"lag{lag}_dirs"] = len({r["d"] for r in rows})
        res[f"lag{lag}_cls_t"] = sum(r["t"]["n"] for r in rows)
        out = {}
        for xk, _ in EXPOSURES:
            for yk, _ in OUTCOMES:
                ok = [r for r in rows if r["t"][xk] is not None and r["f"][yk] is not None]
                out[f"{xk}->{yk}"] = dict(
                    raw_r=corr([r["t"][xk] for r in ok], [r["f"][yk] for r in ok]),
                    pooled=fit(rows, xk, yk, kind, fe=False),
                    fe_nolag=fit(rows, xk, yk, kind, fe=True, lagged=False),
                    fe=fit(rows, xk, yk, kind, fe=True))
        res[f"lag{lag}"] = out
    # H2b by approver turnover in t+1 (the reviewers changed vs stayed).
    rows = [r for r in panel_rows(cs, 1, kind) if r["f"]["turnover"] is not None]
    if rows:
        m = st.median(r["f"]["turnover"] for r in rows)
        res["turnover_median"] = m
        res["turnover"] = {}
        for grp, sub in (("low", [r for r in rows if r["f"]["turnover"] <= m]),
                         ("high", [r for r in rows if r["f"]["turnover"] > m])):
            res["turnover"][grp] = {f"{xk}->{yk}": fit(sub, xk, yk, kind)
                                    for xk in ("fi", "addr100") for yk, _ in OUTCOMES}
    # Descriptives of the cells used (lag 1).
    rows = panel_rows(cs, 1, kind)
    desc = {}
    for k in ("n", "lines", "fi", "addr100", "stamp", "rev", "thr100", "rounds", "ish", "lat", "att", "approvers",
              "turnover", "newshare"):
        v = sorted(r["t"][k] for r in rows if r["t"][k] is not None)
        if v:
            desc[k] = dict(p25=A.q(v, .25), p50=A.q(v, .5), p75=A.q(v, .75), mean=st.mean(v))
    res["describe"] = desc
    # How much of each variable is between directories (share of variance), for the reader.
    share = {}
    for k in ("fi", "addr100", "stamp", "rev", "thr100", "lat", "att"):
        v = [(r["d"], r["t"][k]) for r in rows if r["t"][k] is not None]
        tot = st.pvariance([x for _, x in v])
        by = defaultdict(list)
        for d, x in v:
            by[d].append(x)
        within = sum((x - st.mean(by[d])) ** 2 for d, x in v) / len(v)
        share[k] = 1 - within / tot if tot else None
    res["between_dir_share"] = share
    return res


# ------------------------------------------------------------------ H2c

def authors(units, first, given):
    lo, hi = ts(2023, 7), ts(2025, 10)
    by = defaultdict(list)
    for u in units:
        by[u["pid"]].append(u)
    rows, clrows = [], []
    for p, us in by.items():
        f = first.get(p)
        if f is None or not (lo <= f < hi):
            continue
        y1 = [u for u in us if u["at"] < f + 12 * MONTH]
        y2 = [u for u in us if f + 12 * MONTH <= u["at"] < f + 24 * MONTH]
        obs2 = (min(END, f + 24 * MONTH) - (f + 12 * MONTH)) / MONTH       # months of year 2 observed
        if len(y1) < 5 or sum(u["exp_threads"] for u in y1) < 2 or obs2 < 3:
            continue
        ea = sum(u["exp_addressed"] for u in y1)
        eu = sum(u["exp_unaddr"] for u in y1)
        a_rel = sum(u["addressed"] for u in y1) / ea
        u_rel = sum(u["threads"] - u["addressed"] for u in y1) / eu
        fi1 = sum(u["threads"] for u in y1) / sum(u["exp_threads"] for u in y1)
        d2 = Counter(u["d2"] for u in y1)
        g = given.get(p, [])
        r = dict(
            p=p, cohort=period(f, "half"), full=obs2 >= 11.99,
            la=math.log2(max(a_rel, 1 / 16)), lu=math.log2(max(u_rel, 1 / 16)), lfi1=math.log2(max(fi1, 1 / 16)),
            a_rel=a_rel, u_rel=u_rel, fi1=fi1,
            lcls1=math.log2(len(y1)), llines1=math.log2(max(1, st.mean(u["lines"] for u in y1))),
            top2=d2.most_common(1)[0][1] / len(y1),
            rev1=sum(u["rev"] for u in y1) / len(y1),
            n2=len(y2), obs2=obs2,
            lcls2=math.log2(1 + len(y2) / obs2 * 12),
            lgiven1=math.log2(1 + sum(f <= t < f + 12 * MONTH for t in g)),
            lgiven2=math.log2(1 + sum(f + 12 * MONTH <= t < f + 24 * MONTH for t in g) / obs2 * 12))
        if len(y2) >= 3 and sum(u["exp_threads"] for u in y2) >= 1:
            r["lfi2"] = math.log2(max(sum(u["threads"] for u in y2) / sum(u["exp_threads"] for u in y2), 1 / 16))
        rows.append(r)
        for u in y2:
            clrows.append((r, u))
    return rows, clrows


def h2c(units, first, given):
    rows, clrows = authors(units, first, given)
    cohorts = sorted({r["cohort"] for r in rows})
    base_rev = defaultdict(list)
    for u in units:
        base_rev[(min(u["sb"], 7), u["d2"])].append(u["rev"])
    base_rev = {k: (sum(v) + 0.5) / (len(v) + 15) for k, v in base_rev.items()}

    def X_of(r, expo, sample):
        cs = cohorts if sample == "all" else [c for c in cohorts if c <= period(ts(2024, 9), "half")]
        x = [1.0] + expo + [r["lcls1"], r["llines1"], r["top2"]]
        return x + [1.0 if r["cohort"] == c else 0.0 for c in cs[1:]]

    specs = {"split": lambda r: [r["la"], r["lu"]], "total": lambda r: [r["lfi1"]]}
    res = dict(authors=len(rows), authors_full_year2=sum(r["full"] for r in rows),
               cohorts=[pname(c, "half") for c in cohorts], cls_year2=len(clrows))
    out = {}
    for spec, ex in specs.items():
        for yk, extra in (("lfi2", []), ("lcls2", ["lcls1"]), ("lgiven2", ["lgiven1"])):
            for sample in ("all", "full"):
                rr = [r for r in rows if yk in r and (sample == "all" or r["full"])]
                X = [X_of(r, ex(r), sample) + ([r["lgiven1"]] if yk == "lgiven2" else []) for r in rr]
                y = [r[yk] for r in rr]
                try:
                    beta, se = FP.ols(X, y, [r["p"] for r in rr])
                except ValueError:
                    continue
                k = len(ex(rr[0]))
                out[f"{spec}:{yk}:{sample}"] = dict(
                    n=len(rr), coefs=[dict(b=beta[1 + i], lo=beta[1 + i] - 1.96 * se[1 + i],
                                           hi=beta[1 + i] + 1.96 * se[1 + i]) for i in range(k)],
                    lcls1=dict(b=beta[1 + k], lo=beta[1 + k] - 1.96 * se[1 + k], hi=beta[1 + k] + 1.96 * se[1 + k]))
        # Revert in year 2, per CL (logit), errors clustered by author.
        for sample in ("all", "full"):
            cr = [(r, u) for r, u in clrows if sample == "all" or r["full"]]
            X, y, g = [], [], []
            for r, u in cr:
                b = base_rev[(min(u["sb"], 7), u["d2"])]
                X.append(X_of(r, ex(r), sample) + [math.log(b / (1 - b)), r["rev1"]])
                y.append(u["rev"])
                g.append(r["p"])
            beta, se, _ = FP.logit(X, y, g)
            k = len(ex(cr[0][0]))
            out[f"{spec}:rev2:{sample}"] = dict(
                n=len(cr), authors=len(set(g)), events=sum(y),
                coefs=[dict(or_=math.exp(beta[1 + i]), lo=math.exp(beta[1 + i] - 1.96 * se[1 + i]),
                            hi=math.exp(beta[1 + i] + 1.96 * se[1 + i])) for i in range(k)])
    res["fits"] = out
    # Descriptive: by fifth of first-year addressed (relative), within cohort.
    grp = defaultdict(list)
    for r in rows:
        grp[r["cohort"]].append(r)
    for g in grp.values():
        g.sort(key=lambda r: (r["a_rel"], r["p"]))
        for i, r in enumerate(g):
            r["q"] = 1 + i * 5 // len(g)
    rev2 = defaultdict(lambda: [0, 0])
    for r, u in clrows:
        rev2[r["q"]][0] += u["rev"]
        rev2[r["q"]][1] += 1
    fifths = []
    for q in range(1, 6):
        rr = [r for r in rows if r["q"] == q]
        fifths.append(dict(
            q=q, authors=len(rr), a_rel=st.median(r["a_rel"] for r in rr), u_rel=st.median(r["u_rel"] for r in rr),
            cls1=st.median(2 ** r["lcls1"] for r in rr),
            fi2=st.median(2 ** r["lfi2"] for r in rr if "lfi2" in r),
            rev2=100 * rev2[q][0] / rev2[q][1] if rev2[q][1] else None,
            cls2_per_year=st.median(2 ** r["lcls2"] - 1 for r in rr),
            given2_per_year=st.median(2 ** r["lgiven2"] - 1 for r in rr)))
    res["fifths"] = fifths
    return res


# ------------------------------------------------------------------ report

def fmt(f):
    if not f:
        return "—"
    return f"{f['b']:+.3f} [{f['lo']:+.3f}, {f['hi']:+.3f}]"


def show(res):
    for kind in ("half", "quarter"):
        r = res["panels"][kind]
        print(f"\n== {kind}: cells {r['cells_total']:,}, with >= {MIN_CELL} CLs {r['cells_ge_min']:,}; "
              f"lag-1 pairs {r['lag1_pairs']:,} in {r['lag1_dirs']} dirs ({r['lag1_cls_t']:,} CLs in t); "
              f"lag-2 pairs {r['lag2_pairs']:,}")
        for lag in (1, 2, -1) + ((4,) if kind == "quarter" else ()):
            print(f"-- lag {lag}: outcome(t+{lag}) per 1 SD of depth(t)   raw r | pooled | FE no lag | FE + lag")
            for k, v in r[f"lag{lag}"].items():
                rr = f"{v['raw_r']:+.2f}" if v["raw_r"] is not None else "—"
                print(f"  {k:20s} {rr:>6s} | {fmt(v['pooled'])} | {fmt(v['fe_nolag'])} | {fmt(v['fe'])}")
        if "turnover" in r:
            print(f"-- by approver turnover in t+1 (median {r['turnover_median']:.2f}): low | high")
            for k in r["turnover"]["low"]:
                print(f"  {k:20s} {fmt(r['turnover']['low'][k])} | {fmt(r['turnover']['high'][k])}")
        print("-- between-directory share of variance:",
              {k: round(v, 2) for k, v in r["between_dir_share"].items() if v is not None})
    h = res["h2c"]
    print(f"\n== H2c: {h['authors']:,} authors ({h['authors_full_year2']:,} with a full year 2), "
          f"{h['cls_year2']:,} year-2 CLs")
    for k, v in h["fits"].items():
        print(f"  {k:24s} n={v['n']:,} ", "  ".join(
            (f"{c['b']:+.3f} [{c['lo']:+.3f}, {c['hi']:+.3f}]" if "b" in c else
             f"OR {c['or_']:.3f} [{c['lo']:.3f}, {c['hi']:.3f}]") for c in v["coefs"]))
    for f in h["fifths"]:
        print("  ", {k: (round(v, 3) if isinstance(v, float) else v) for k, v in f.items()})


def main():
    os.nice(5)              # same as `nice -n 5`: blame and the loads yield to interactive work
    ap = argparse.ArgumentParser()
    ap.add_argument("--first-commit")
    ap.add_argument("--mech")
    ap.add_argument("--cache")
    ap.add_argument("--out")
    args = ap.parse_args()
    t0 = time.time()
    if args.cache and os.path.exists(args.cache):
        L = pickle.load(open(args.cache, "rb"))
        if L.get("args") != (args.first_commit and os.path.exists(args.first_commit),
                             args.mech and os.path.exists(args.mech)):
            L = None
    else:
        L = None
    if L is None:
        L = load(args)
        L["args"] = (args.first_commit and os.path.exists(args.first_commit), args.mech and os.path.exists(args.mech))
        if args.cache:
            pickle.dump(L, open(args.cache, "wb"))
    units = L["units"]
    norms(units)
    res = dict(tenure_rule=L["tenure_rule"], mech_rule=L["mech_rule"], unit_cls=len(units),
               panels={k: panels(units, L["first"], k) for k in ("half", "quarter")})
    res["h2c"] = h2c(units, L["first"], L["given"])
    res["runtime_s"] = round(time.time() - t0)
    show(res)
    if args.out:
        json.dump(res, open(args.out, "w"), indent=1, default=str)
        print("wrote", args.out, file=sys.stderr)


if __name__ == "__main__":
    main()
