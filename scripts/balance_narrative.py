"""Datasets for the narrative restructure of the Review Balance page
("Chromium Code Review Load Analysis", web/balance.html): who carries
review, how organisations and tenure shape feedback, how new reviewers grow,
how AI-marked CLs are reviewed, and how review capacity grew and stalled.

Offline: reads balance*.sqlite, derived.sqlite, labels.sqlite,
ai_marked_broad.txt and ai_predict/scores.sqlite, all read-only, plus the
report inputs of docs/balance.md. No comment text is read; only counts.
Writes aggregates only (no names, e-mails or IDs); cells under MIN_PEOPLE
people or MIN_CLS CLs are dropped or pooled into "Other".

  COSH_DATA_DIR=<main>/data/private nice -n 5 python3 scripts/balance_narrative.py \
      --first-commit F --owners-added O --mech M [--cache P] [summaries/balance.json]

--cache P pickles the loaded inputs to P (first run) and reads them back
(later runs), which cuts a rerun from ~6 min to ~1 min. Delete P when any
input changes. Output is deterministic (fixed seeds).

Population (as balance_report.py): merged, human-owned, non-mechanical CLs
(mech list) closed 2023Q3..2026Q3; people merged across e-mail addresses
(balance_growth.Ids); tenure from the first commit on main (first_commit.txt).
A "review" is one (CL, reviewer) pair: a non-bot account other than the
owner that wrote at least one comment before close, whose person has a first
commit (so a tenure), exactly as `reviewer_quarters`/`reviewers_by_tenure`.
Threads are the reviewer threads they started; "addressed" is the
regex-or-Haiku label (labels.sqlite; every week in range is classified).
Git datasets use human, non-revert commits on main with a Gerrit CL, and
Reviewed-by footers (people other than the author) as approvals.

Datasets (summaries/balance.json `datasets`):
- reviewer_burden: per quarter, the spread across commenting reviewers of
  CLs commented on (cls), changed lines of those CLs (lines), comments
  written (comments: individual comments, replies included) and weekday
  attention-set hours on those CLs (hours): p50/p75/p90/p95/p99/mean.
- approver_burden: per quarter since 2017Q3 from git: approvals given per
  approver (cls) and lines of the commits approved (lines).
- org_feedback: author org x era x tenure band -> feedback index.
- org_feedback_fit: per org and era, the feedback index adjusted for
  tenure mix (indirect standardisation), its ratio to all orgs, and a
  95% interval from a bootstrap over the org's authors.
- org_reviewing: review share (approvals / (approvals + CLs)) by org and
  year since joining, git, join years 2017-2025 pooled.
- org_review_value: per reviewer org, Gerrit reviews 2023Q3..2026Q3:
  threads and addressed threads per review.
- new_reviewer_growth: reviews, threads, addressed per review and the
  addressed share by the reviewer's years since first commit, two eras.
- ai_quarters / ai_reviewer_load / ai_summary: AI-marked CLs (broad marker,
  ai_marked_broad.txt) and Haiku-predicted CLs (p >= 0.5, unmarked) vs others.
- capacity_years, capacity_tenure, capacity_orgs: git review capacity by
  calendar year 2017 (Jul-Dec) .. 2026 (Jan-Sep).
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
import balance_report as R  # noqa: E402
from cosh import balance, classify, orgs, store  # noqa: E402

YEAR = G.YEAR
DAY = 86400
Q = list(R.quarters("2023Q3", "2026Q3"))
MIN_PEOPLE, MIN_CLS = 20, 200
PCTS = (.5, .75, .9, .95, .99)
GIT_START = datetime(2017, 7, 1, tzinfo=timezone.utc).timestamp()     # Reviewed-by footers start
GIT_END = datetime(2026, 10, 1, tzinfo=timezone.utc).timestamp()      # whole quarters only
AI_P = 0.5           # Haiku cutoff for "predicted" (99% precision, docs/balance-ai-predict.md §5)
AI_MODEL = ("haiku", "3dd3ca1ff755")
SEED = 20261109


def ts(y, m=1, d=1):
    return datetime(y, m, d, tzinfo=timezone.utc).timestamp()


def r(x, n=2):
    return R.r(x, n)


def pct(xs, p):
    return R.pct(xs, p)


def dist(name, xs):
    xs = list(xs)
    out = {f"{name}_p{int(round(p * 100))}": pct(xs, p) for p in PCTS}
    out[f"{name}_mean"] = r(st.mean(xs)) if xs else None
    return out


def gini(xs):
    xs = sorted(xs)
    n, s = len(xs), sum(xs)
    if not n or not s:
        return None
    return sum((2 * i - n + 1) * x for i, x in enumerate(xs)) / (n * s)


def concentration(counts):
    v = sorted(counts, reverse=True)
    tot = sum(v)
    return dict(top10_share=sum(v[:max(1, len(v) // 10)]) / tot, top1pct_share=sum(v[:max(1, len(v) // 100)]) / tot,
                gini=gini(v))


def tband(t):
    return None if t is None else "lt2" if t < 2 else "y2_5" if t < 5 else "y5_10" if t < 10 else "y10p"


# ======================================================================= loading

def load(args):
    cls, commits, ids, first, owner_at, _ = G.load_all(args)
    mech = R.mech_set(args.mech)
    dirs3 = A.commit_dirs(3)
    top2 = {}
    for c in commits:
        d = dirs3.get(c["cid"])
        if c["n"] and d:
            top2[c["n"]] = "/".join(d[0].split("/")[:2])
    del dirs3
    A.MECH_FILES = 10 ** 9
    for c in cls:
        if c["change_number"] in mech:
            c["status"] = "MECH"
    use = G.cl_residuals(cls, top2)
    del cls
    raw_owner = dict(A.ro(balance.db_path("cl")).execute("SELECT change_number, owner_email FROM cl"))
    by_n = {c["n"]: c for c in commits if c["n"]}
    resolve = orgs.OrgResolver()
    keep = ("change_number", "pid", "owner", "closed_at", "lines", "threads", "addressed", "exp24",
            "first_review_at", "reviewer_wait_wd_h", "rounds", "lines_changed", "lines_final", "interdiff_status",
            "sb", "d2")
    L = []
    for c in use:
        q = A.quarter(c["closed_at"])
        x = {k: c[k] for k in keep}
        x["q"] = q
        x["ten"] = (c["closed_at"] - first[c["pid"]]) / YEAR if c["pid"] in first else None
        x["ftr"] = (c["first_review_at"] - c["sent_at"]) / 3600 \
            if c["first_review_at"] and c["sent_at"] and c["first_review_at"] >= c["sent_at"] else None
        x["rev30"] = bool(c["reverted_at"] and c["reverted_at"] - c["closed_at"] < 30 * DAY)
        g = by_n.get(c["change_number"])
        x["sha"] = g["sha"] if g else None
        e = raw_owner.get(c["change_number"])
        x["org"] = resolve(e, datetime.fromtimestamp(c["closed_at"], timezone.utc).strftime("%Y-%m-%d")) if e else None
        L.append(x)
    del use
    cl_by_n = {c["change_number"]: c for c in L}
    print(f"{len(L):,} CLs in the population", file=sys.stderr, flush=True)

    # ---- reviewer side (Gerrit), as balance_report.py
    d = A.ro(os.path.join(store.DATA_DIR, store.DERIVED_FILE))
    emails = dict(d.execute("SELECT account_id, email FROM accounts"))
    bots = {a for a, in d.execute("SELECT account_id FROM accounts WHERE is_bot = 1")}
    ncom = Counter()
    for n, acct, k in d.execute("SELECT change_number, account_id, count(*) FROM comments "
                                "WHERE after_close = 0 GROUP BY 1, 2"):
        if n in cl_by_n and acct not in bots:
            ncom[(n, acct)] = k
    lp = classify.labels_path(store.DATA_DIR)
    ldb = A.ro(lp)
    act = classify.active_classifier(ldb)
    labels = {(n, rt, h): a for n, rt, h, a in ldb.execute(
        "SELECT change_number, root_uuid, input_hash, addressed FROM labels WHERE classifier_id = ?", (act[0],))} \
        if act else {}
    thr = defaultdict(lambda: [0, 0])
    for n, rt, reply, rx, h, acct in d.execute("SELECT change_number, root_uuid, last_owner_reply_at, "
                                               "regex_addressed, input_hash, root_account FROM threads"):
        if n in cl_by_n and acct not in bots:
            t = thr[(n, acct)]
            t[0] += 1
            t[1] += (0 if reply is None else 1 if rx else labels.get((n, rt, h)) or 0)
    del labels
    hours = {}
    for n, acct, wd in A.ro(balance.db_path("cl")).execute(
            "SELECT change_number, account_id, weekday_hours FROM cl_attention"):
        if n in cl_by_n:
            hours[(n, acct)] = wd
    pairs = []      # (n, person, tenure, comments, threads, addressed, hours, org)
    pid_of = {}
    for (n, acct), k in ncom.items():
        c = cl_by_n[n]
        if acct == c["owner"]:
            continue
        e = emails.get(acct)
        if not e or A.is_bot_email(e):
            continue
        if acct not in pid_of:
            pid_of[acct] = ids.find(e)
        p = pid_of[acct]
        if p not in first:
            continue
        t = thr.get((n, acct), (0, 0))
        org = resolve(e, datetime.fromtimestamp(c["closed_at"], timezone.utc).strftime("%Y-%m-%d"))
        pairs.append((n, p, (c["closed_at"] - first[p]) / YEAR, k, t[0], t[1], hours.get((n, acct), 0.0), org, acct))
    print(f"{len(pairs):,} reviews", file=sys.stderr, flush=True)

    # ---- git, light
    graw = dict(A.ro(balance.db_path("git")).execute("SELECT commit_id, author_email FROM gcommits"))
    G_ = []
    for c in commits:
        if not c["n"] or c["is_revert"]:
            continue
        e = graw.get(c["cid"])
        G_.append(dict(pid=c["pid"], at=c["at"], n=c["n"], rbp=[x for x in c["rbp"] if x != c["pid"]],
                       lines=c["lines"], org=resolve(e, datetime.fromtimestamp(c["at"], timezone.utc)
                                                       .strftime("%Y-%m-%d"))))
    return dict(cls=L, pairs=pairs, commits=G_, first=first, owner_at=owner_at)


# ============================================================ 1. reviewer burden

def reviewer_burden(S):
    cl = {c["change_number"]: c for c in S["cls"]}
    per = defaultdict(lambda: defaultdict(lambda: [0, 0, 0, 0.0]))
    per_acct = defaultdict(Counter)        # the account-keyed count reviewer_quarters uses, for a check
    for n, p, ten, k, th, ad, h, org, acct in S["pairs"]:
        c = cl[n]
        x = per[c["q"]][p]
        x[0] += 1
        x[1] += c["lines"]
        x[2] += k
        x[3] += h
        per_acct[c["q"]][acct] += 1
    out = []
    for q in Q:
        v = per[q].values()
        out.append(dict(q=q, reviewers=len(v), **dist("cls", (x[0] for x in v)), **dist("lines", (x[1] for x in v)),
                        **dist("comments", (x[2] for x in v)), **dist("hours", (x[3] for x in v))))
        print(f"  {q}: {len(v)} reviewers (people), {len(per_acct[q])} accounts; account-keyed CLs p50/p90 "
              f"{pct(per_acct[q].values(), .5)}/{pct(per_acct[q].values(), .9)}", file=sys.stderr)
    return out


def approver_burden(S):
    per = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for c in S["commits"]:
        if not (GIT_START <= c["at"] < GIT_END):
            continue
        q = A.quarter(c["at"])
        for a in set(c["rbp"]):
            x = per[q][a]
            x[0] += 1
            x[1] += c["lines"]
    out = []
    for q in R.quarters("2017Q3", "2026Q3"):
        v = per[q].values()
        if v:
            d = dict(q=q, approvers=len(v), **dist("cls", (x[0] for x in v)), **dist("lines", (x[1] for x in v)))
            out.append(d)
    return out


# ============================================================ 2. org feedback

ERAS = {"pre": (ts(2023, 7), ts(2025)), "now": (ts(2025, 10), ts(2026, 10))}
BANDS = (("<1y", 0, 1), ("1-2y", 1, 2), ("2-5y", 2, 5), ("5y+", 5, 999))


def era_of(t):
    return next((e for e, (a, b) in ERAS.items() if a <= t < b), None)


def band_of(ten):
    return next(b for b, lo, hi in BANDS if lo <= max(0.0, ten) < hi)


def org_feedback(S):
    rows = [c for c in S["cls"] if c["ten"] is not None and era_of(c["closed_at"]) and c["org"]]
    for c in rows:
        c["era"] = era_of(c["closed_at"])
        c["band"] = band_of(c["ten"])
    # orgs big enough in both eras
    size = defaultdict(lambda: [0, set()])
    for c in rows:
        s = size[(c["org"], c["era"])]
        s[0] += 1
        s[1].add(c["pid"])
    big = [o for o in {o for o, _ in size}
           if all(size[(o, e)][0] >= MIN_CLS and len(size[(o, e)][1]) >= MIN_PEOPLE for e in ERAS)]
    big.sort(key=lambda o: -(size[(o, "pre")][0] + size[(o, "now")][0]))
    big = big[:12]
    name = lambda o: o if o in big else "Other"
    cells = defaultdict(lambda: [0.0, 0.0, 0, set()])
    for c in rows:
        for o in (name(c["org"]), "All"):
            for b in (c["band"], "all"):
                x = cells[(o, c["era"], b)]
                x[0] += c["threads"]
                x[1] += c["exp24"]
                x[2] += 1
                x[3].add(c["pid"])
    out = []
    for o in big + ["Other", "All"]:
        for e in ERAS:
            for b in [b for b, _, _ in BANDS] + ["all"]:
                x = cells.get((o, e, b))
                if not x or x[2] < MIN_CLS or len(x[3]) < MIN_PEOPLE:
                    continue
                out.append(dict(org=o, era=e, band=b, cls=x[2], people=len(x[3]), feedback_index=r(x[0] / x[1])))
    # tenure-adjusted: observed threads / threads expected from size, area AND the all-org tenure-band index
    fit = []
    rng = random.Random(SEED)
    for e in ERAS:
        bidx = {b: cells[("All", e, b)][0] / cells[("All", e, b)][1] for b, _, _ in BANDS}
        allx = cells[("All", e, "all")][0] / cells[("All", e, "all")][1]
        for o in big + ["Other"]:
            per = defaultdict(lambda: [0.0, 0.0, 0.0])      # person -> threads, exp24, tenure-expected
            for c in rows:
                if c["era"] == e and name(c["org"]) == o:
                    x = per[c["pid"]]
                    x[0] += c["threads"]
                    x[1] += c["exp24"]
                    x[2] += c["exp24"] * bidx[c["band"]]
            v = list(per.values())
            obs, exp, texp = (sum(x[i] for x in v) for i in range(3))
            boots = []
            for _ in range(500):
                s = [v[rng.randrange(len(v))] for _ in v]
                boots.append(sum(x[0] for x in s) / sum(x[2] for x in s))
            boots.sort()
            ratio = obs / texp
            mix = Counter(c["band"] for c in rows if c["era"] == e and name(c["org"]) == o)
            tot = sum(mix.values())
            fit.append(dict(org=o, era=e, cls=tot, people=len(v), feedback_index=r(obs / exp),
                            adjusted_index=r(ratio * allx), ratio=r(ratio, 3),
                            ratio_lo=r(boots[12], 3), ratio_hi=r(boots[487], 3), all_index=r(allx),
                            **{f"mix_{b}": r(mix[b] / tot, 3) for b, _, _ in BANDS}))
    return out, fit


# ============================================================ 3. org reviewing

def person_org_year(S):
    cnt = defaultdict(lambda: defaultdict(Counter))
    for c in S["commits"]:
        cnt[c["pid"]][A.year(c["at"])][c["org"]] += 1
    out = {}
    for p, ys in cnt.items():
        yrs = sorted(ys)
        for y in range(2017, 2027):
            near = min(yrs, key=lambda k: (abs(k - y), -k))
            out[(p, y)] = ys[near].most_common(1)[0][0]
    return out


def org_reviewing(S, poy):
    authored, given = defaultdict(Counter), defaultdict(Counter)
    for c in S["commits"]:
        y = A.year(c["at"])
        authored[c["pid"]][y] += 1
        for a in c["rbp"]:
            given[a][y] += 1
    cells = defaultdict(list)
    for p, t in S["first"].items():
        fy = A.year(t)
        if not 2017 <= fy <= 2025:
            continue
        for k in range(1, 9):
            y = fy + k - 1
            if y > 2026:
                break
            a, g = authored[p][y], given[p][y]
            if a + g >= 6 and (p, y) in poy:
                cells[(poy[(p, y)], k)].append(g / (a + g))
    tot = Counter()
    for (o, k), v in cells.items():
        tot[o] += len(v)
    top = [o for o, _ in tot.most_common() if all(len(cells.get((o, k), [])) >= MIN_PEOPLE for k in (1, 2, 3))][:8]
    pooled = defaultdict(list)
    for (o, k), v in cells.items():
        pooled[(o if o in top else "Other", k)] += v
        pooled[("All", k)] += v
    out = []
    for o in top + ["Other", "All"]:
        for k in range(1, 9):
            v = pooled.get((o, k), [])
            if len(v) >= MIN_PEOPLE:
                out.append(dict(org=o, year=k, people=len(v), review_share_p50=r(st.median(v)),
                                gives_any=r(sum(x > 0 for x in v) / len(v), 3)))
    return out


def org_review_value(S):
    cl = {c["change_number"]: c for c in S["cls"]}
    g = defaultdict(lambda: [set(), 0, 0, 0, 0])
    for n, p, ten, k, th, ad, h, org, acct in S["pairs"]:
        if cl[n]["q"] not in Q:
            continue
        for o in (org, "All"):
            x = g[o]
            x[0].add(p)
            x[1] += 1
            x[2] += th
            x[3] += ad
            x[4] += k
    big = [o for o, x in sorted(g.items(), key=lambda kv: -kv[1][1]) if o != "All" and len(x[0]) >= MIN_PEOPLE][:12]
    other = [set(), 0, 0, 0, 0]
    for o, x in g.items():
        if o not in big and o != "All":
            other[0] |= x[0]
            for i in range(1, 5):
                other[i] += x[i]
    g["Other"] = other
    return [dict(org=o, reviewers=len(x[0]), reviews=x[1], threads_per_review=r(x[2] / x[1]),
                 addressed_per_review=r(x[3] / x[1]), addressed_share=r(x[3] / max(1, x[2]), 3),
                 comments_per_review=r(x[4] / x[1]))
            for o in big + ["Other", "All"] for x in [g[o]] if x[1]]


# ============================================================ 4. new reviewer growth

YBINS = (("1", 0, 1), ("2", 1, 2), ("3", 2, 3), ("4", 3, 4), ("5", 4, 5), ("6-7", 5, 7), ("8-10", 7, 10),
         ("11+", 10, 999))


def new_reviewer_growth(S):
    cl = {c["change_number"]: c for c in S["cls"]}
    era = lambda q: "pre" if "2023Q3" <= q <= "2025Q2" else "now" if "2025Q3" <= q <= "2026Q3" else None
    g = defaultdict(lambda: [set(), set(), 0, 0, 0])
    for n, p, ten, k, th, ad, h, org, acct in S["pairs"]:
        q = cl[n]["q"]
        e = era(q)
        if not e:
            continue
        y = next(b for b, lo, hi in YBINS if lo <= max(0.0, ten) < hi)
        x = g[(y, e)]
        x[0].add(p)
        x[1].add((p, q))
        x[2] += 1
        x[3] += th
        x[4] += ad
    out = []
    for y, _, _ in YBINS:
        for e in ("pre", "now"):
            x = g.get((y, e))
            if x and len(x[0]) >= MIN_PEOPLE:
                out.append(dict(year=y, era=e, reviewers=len(x[0]), reviews=x[2],
                                reviews_per_reviewer_quarter=r(x[2] / len(x[1])),
                                threads_per_review=r(x[3] / x[2]), addressed_per_review=r(x[4] / x[2]),
                                addressed_share=r(x[4] / max(1, x[3]), 3)))
    return out


# ============================================================ 5. AI

def ai_kinds(S):
    p = os.path.join(store.DATA_DIR, "ai_marked_broad.txt")
    marked = set(line.split()[0] for line in open(p))
    sdb = A.ro(os.path.join(store.DATA_DIR, "ai_predict", "scores.sqlite"))
    pred, scored = set(), set()
    for sha, pv in sdb.execute("SELECT sha, p FROM scores WHERE model = ? AND prompt = ?", AI_MODEL):
        scored.add(sha)
        if pv >= AI_P:
            pred.add(sha)
    for c in S["cls"]:
        c["marked"] = c["sha"] in marked
        c["pred"] = c["sha"] in pred and not c["marked"]
        c["scored"] = c["sha"] in scored
    return len(scored)


def ai_quarters(S):
    by = defaultdict(list)
    for c in S["cls"]:
        if c["q"] in Q:
            by[(c["q"], "marked" if c["marked"] else "other")].append(c)
            if c["pred"]:
                by[(c["q"], "predicted")].append(c)
    out = []
    for q in Q:
        if len(by[(q, "marked")]) < MIN_CLS:
            continue
        for k in ("marked", "predicted", "other"):
            s = by[(q, k)]
            if len(s) < MIN_CLS:
                continue
            rv = [c for c in s if c["first_review_at"]]
            idf = [c for c in rv if c["interdiff_status"] == "ok" and c["lines_final"]]
            big = [c for c in s if c["lines"] >= 10]
            out.append(dict(q=q, kind=k, cls=len(s), authors=len({c["pid"] for c in s}),
                            median_lines=st.median(c["lines"] for c in s),
                            threads_per_cl=r(st.mean(c["threads"] for c in s)),
                            threads_per_100=r(st.mean(100 * c["threads"] / c["lines"] for c in big)),
                            feedback_index=r(sum(c["threads"] for c in s) / sum(c["exp24"] for c in s)),
                            ftr_p50=pct([c["ftr"] for c in rv], .5),
                            review_time_p50=pct([c["reviewer_wait_wd_h"] for c in rv], .5),
                            rounds=r(st.mean(c["rounds"] or 0 for c in rv)) if rv else None,
                            interdiff_p50=pct([c["lines_changed"] / c["lines_final"] for c in idf], .5),
                            reverted=r(sum(c["rev30"] for c in s) / len(s), 4)))
    return out


def ai_reviewer_load(S):
    cl = {c["change_number"]: c for c in S["cls"]}
    qs = sorted({c["q"] for c in S["cls"] if c["marked"] and c["q"] in Q})
    lo = next(q for q in qs if sum(1 for c in S["cls"] if c["marked"] and c["q"] == q) >= MIN_CLS)
    period = [q for q in Q if q >= lo]
    by_cl = defaultdict(list)
    for n, p, ten, k, th, ad, h, org, acct in S["pairs"]:
        if cl[n]["q"] in period:
            by_cl[n].append((p, tband(ten)))
    groups = {"marked": [], "predicted": [], "other": []}
    for c in S["cls"]:
        if c["q"] in period:
            groups["marked" if c["marked"] else "other"].append(c["change_number"])
            if c["pred"]:
                groups["predicted"].append(c["change_number"])

    def stats(ns):
        per, mix = Counter(), Counter()
        for n in ns:
            for p, b in by_cl.get(n, ()):
                per[p] += 1
                mix[b] += 1
        tot = sum(per.values())
        return dict(reviewers=len(per), cls=len(ns), reviews=tot, reviews_per_cl=tot / len(ns),
                    **concentration(per.values()), **{b: mix[b] / tot for b in ("lt2", "y2_5", "y5_10", "y10p")})
    out = []
    for k, ns in groups.items():
        out.append(dict(kind=k, **{a: (r(b, 3) if isinstance(b, float) else b) for a, b in stats(ns).items()}))
    # other CLs sampled to the marked set's size, quarter by quarter
    rng = random.Random(SEED)
    oq = defaultdict(list)
    for n in groups["other"]:
        oq[cl[n]["q"]].append(n)
    want = Counter(cl[n]["q"] for n in groups["marked"])
    acc = defaultdict(list)
    for _ in range(200):
        ns = [n for q, k in want.items() for n in rng.sample(oq[q], k)]
        for a, b in stats(ns).items():
            acc[a].append(b)
    out.append(dict(kind="other_matched", draws=200, **{a: r(st.mean(v), 3) for a, v in acc.items()},
                    **{f"{a}_lo": r(sorted(v)[5], 3) for a, v in acc.items() if a in ("top10_share", "gini")},
                    **{f"{a}_hi": r(sorted(v)[194], 3) for a, v in acc.items() if a in ("top10_share", "gini")}))
    for x in out:
        x["period"] = f"{period[0]}..{period[-1]}"
    return out


def ai_summary(S, paired):
    s = [c for c in S["cls"] if c["q"] in Q]
    period = sorted({c["q"] for c in s if c["marked"]})
    first_q = next(q for q in Q if sum(1 for c in s if c["marked"] and c["q"] == q) >= MIN_CLS)
    win = [c for c in s if c["q"] >= first_q]
    m = [c for c in win if c["marked"]]
    o = [c for c in win if not c["marked"]]
    last = [c for c in s if c["q"] == Q[-1]]
    top = lambda c: (c["d2"] or "?").split("/")[0]
    strata = defaultdict(lambda: [[], []])
    for c in win:
        strata[(A.size_bucket(c["lines"]), top(c), c["q"])][0 if c["marked"] else 1].append(c)
    # Standardised to the marked CLs' strata (other rate re-weighted to marked mix)
    def std_diff(groups):
        num = den = var = 0.0
        for key, (mm, oo) in groups.items():
            if not mm or len(oo) < 20:
                continue
            pm = sum(c["rev30"] for c in mm) / len(mm)
            po = sum(c["rev30"] for c in oo) / len(oo)
            w = len(mm)
            num += w * (pm - po)
            den += w
            var += w * w * (pm * (1 - pm) / len(mm) + po * (1 - po) / len(oo))
        return num / den, math.sqrt(var) / den, den
    d, se, covered = std_diff(strata)
    # author-cluster bootstrap of the marked side (marked CLs come from few authors)
    rng = random.Random(SEED)
    by_author = defaultdict(list)
    for c in m:
        by_author[c["pid"]].append(c)
    authors = sorted(by_author)
    orate = {k: sum(c["rev30"] for c in oo) / len(oo) for k, (mm, oo) in strata.items() if len(oo) >= 20}
    keyf = lambda c: (A.size_bucket(c["lines"]), top(c), c["q"])
    boots = []
    for _ in range(1000):
        num = den = 0
        for _ in authors:
            for c in by_author[authors[rng.randrange(len(authors))]]:
                k = keyf(c)
                if k in orate:
                    num += c["rev30"] - orate[k]
                    den += 1
        boots.append(num / den)
    boots.sort()
    pr = next((x for x in paired if x["metric"].startswith("reverted")), None)
    pred = [c for c in win if c["pred"]]
    return [dict(period=f"{first_q}..{Q[-1]}", marked_first=period[0] if period else None,
                 marked_cls=len(m), marked_authors=len(by_author), other_cls=len(o),
                 predicted_cls=len(pred), predicted_cutoff=AI_P,
                 latest_q=Q[-1], latest_marked_share=r(sum(c["marked"] for c in last) / len(last), 4),
                 latest_predicted_share=r(sum(c["pred"] or c["marked"] for c in last if c["scored"])
                                          / max(1, sum(c["scored"] for c in last)), 4),
                 revert_marked=r(sum(c["rev30"] for c in m) / len(m), 4),
                 revert_other=r(sum(c["rev30"] for c in o) / len(o), 4),
                 revert_predicted=r(sum(c["rev30"] for c in pred) / len(pred), 4) if pred else None,
                 revert_std_diff=r(100 * d, 2), revert_std_lo=r(100 * (d - 1.96 * se), 2),
                 revert_std_hi=r(100 * (d + 1.96 * se), 2),
                 revert_std_boot_lo=r(100 * boots[25], 2), revert_std_boot_hi=r(100 * boots[974], 2),
                 revert_std_covered=r(covered / len(m), 3),
                 revert_paired_diff=r(100 * pr["diff"], 2) if pr else None,
                 revert_paired_lo=r(100 * pr["lo"], 2) if pr else None,
                 revert_paired_hi=r(100 * pr["hi"], 2) if pr else None,
                 revert_paired_n=pr["n"] if pr else None)]


# ============================================================ 6. capacity

def capacity(S, poy):
    first, owner_at = S["first"], S["owner_at"]
    C = [c for c in S["commits"] if GIT_START <= c["at"] < GIT_END]
    authored, given = defaultdict(Counter), defaultdict(Counter)
    for c in S["commits"]:                      # whole history (since 2017-01) for "first ever"
        y = A.year(c["at"])
        authored[c["pid"]][y] += 1
        for a in c["rbp"]:
            given[a][y] += 1
    first_appr = {}
    for c in sorted(C, key=lambda c: c["at"]):
        for a in c["rbp"]:
            first_appr.setdefault(a, A.year(c["at"]))
    regular = {p: min(y for y, n in g.items() if n >= 60) for p, g in given.items()
               if any(n >= 60 for n in g.values()) and p in first}
    by_y = defaultdict(list)
    for c in C:
        by_y[A.year(c["at"])].append(c)
    rows, ten_rows, org_rows = [], [], []
    prev = None
    for y in range(2017, 2027):
        s = by_y[y]
        months = 6 if y == 2017 else 9 if y == 2026 else 12
        mid = ts(y, 10) if y == 2017 else ts(y, 5, 15) if y == 2026 else ts(y, 7)
        au = Counter(c["pid"] for c in s)
        ap = Counter(a for c in s for a in c["rbp"])
        ten = lambda p: (mid - first[p]) / YEAR if p in first else None
        mix_p, mix_a = Counter(), Counter()
        for p, n in ap.items():
            b = tband(ten(p)) or "unknown"
            mix_p[b] += 1
            mix_a[b] += n
        appr_n = sum(ap.values())
        row = dict(year=y, months=months, commits=len(s), commits_per_month=r(len(s) / months, 0),
                   authors=len(au), approvers=len(ap), approvals=appr_n,
                   approvals_per_month=r(appr_n / months, 0),
                   approvals_per_approver_month=r(appr_n / len(ap) / months),
                   commits_per_author_month=r(len(s) / len(au) / months),
                   approvers_per_author=r(len(ap) / len(au), 3),
                   authors_who_approve=r(len(set(au) & set(ap)) / len(au), 3),
                   new_authors=sum(1 for p in au if p in first and A.year(first[p]) == y),
                   new_authors_5=sum(1 for p, t in first.items() if A.year(t) == y and authored[p][y] >= 5),
                   new_approvers=None if y == 2017 else sum(1 for p in ap if first_appr.get(p) == y),
                   new_regular_reviewers=sum(1 for p, yy in regular.items() if yy == y),
                   new_owners=sum(1 for p, t in owner_at.items() if p in first and A.year(t) == y),
                   left_approvers=None if prev is None else len(set(prev) - set(ap)),
                   left_approvers_for_good=None if prev is None else
                   sum(1 for p in set(prev) - set(ap) if not any(given[p][k] for k in range(y, 2027))),
                   left_authors=None if y == 2017 else
                   sum(1 for p in {c["pid"] for c in by_y[y - 1]} if not any(authored[p][k] for k in range(y, 2027))),
                   net_approvers=None if prev is None else len(ap) - len(prev),
                   **{f"appr_{b}": r(mix_p[b] / len(ap), 3) for b in ("lt2", "y2_5", "y5_10", "y10p")},
                   **{f"approvals_{b}": r(mix_a[b] / appr_n, 3) for b in ("lt2", "y2_5", "y5_10", "y10p")},
                   approver_tenure_p50=r(st.median(t for p in ap if (t := ten(p)) is not None), 1),
                   author_tenure_p50=r(st.median(t for p in au if (t := ten(p)) is not None), 1),
                   lines_per_approval=r(sum(c["lines"] * len(c["rbp"]) for c in s) / max(1, appr_n), 0),
                   google_author_share=r(sum(1 for p in au if poy.get((p, y)) == "google.com") / len(au), 3))
        rows.append(row)
        prev = ap
        # by author tenure band: who authors, and how many of them also approve
        tb = defaultdict(lambda: [set(), set(), 0, 0])
        for p, n in au.items():
            b = tband(ten(p)) or "unknown"
            tb[b][0].add(p)
            tb[b][2] += n
            if p in ap:
                tb[b][1].add(p)
        for p, n in ap.items():
            tb[tband(ten(p)) or "unknown"][3] += n
        for b in ("lt2", "y2_5", "y5_10", "y10p"):
            x = tb[b]
            if len(x[0]) >= MIN_PEOPLE:
                ten_rows.append(dict(year=y, band=b, authors=len(x[0]), authors_who_approve=r(len(x[1]) / len(x[0]), 3),
                                     commits_share=r(x[2] / len(s), 3), approvals_share=r(x[3] / appr_n, 3),
                                     approvals_per_author_month=r(x[3] / len(x[0]) / months)))
        # Google vs the rest (org of the person's commits that year)
        og = defaultdict(lambda: [set(), set(), 0, 0, 0])
        for p, n in au.items():
            g = "google" if poy.get((p, y)) == "google.com" else "other"
            og[g][0].add(p)
            og[g][2] += n
            og[g][4] += p in first and A.year(first[p]) == y
        for p, n in ap.items():
            g = "google" if poy.get((p, y)) == "google.com" else "other"
            og[g][1].add(p)
            og[g][3] += n
        for g in ("google", "other"):
            x = og[g]
            org_rows.append(dict(year=y, org=g, authors=len(x[0]), approvers=len(x[1]), commits=x[2], approvals=x[3],
                                 new_authors=x[4], approvers_per_author=r(len(x[1]) / max(1, len(x[0])), 3),
                                 approvals_per_approver_month=r(x[3] / max(1, len(x[1])) / months)))
    return rows, ten_rows, org_rows


# ======================================================================= main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default="summaries/balance.json")
    ap.add_argument("--first-commit", required=True)
    ap.add_argument("--owners-added", required=True)
    ap.add_argument("--mech", required=True)
    ap.add_argument("--ai-marked")
    ap.add_argument("--cache")
    args = ap.parse_args()
    if args.cache and os.path.exists(args.cache):
        S = pickle.load(open(args.cache, "rb"))
    else:
        S = load(args)
        if args.cache:
            with open(args.cache + ".tmp", "wb") as f:
                pickle.dump(S, f, protocol=pickle.HIGHEST_PROTOCOL)
            os.replace(args.cache + ".tmp", args.cache)
    data = json.load(open(args.path))
    ds = data["datasets"]
    new = {}
    new["reviewer_burden"] = reviewer_burden(S)
    new["approver_burden"] = approver_burden(S)
    new["org_feedback"], new["org_feedback_fit"] = org_feedback(S)
    poy = person_org_year(S)
    new["org_reviewing"] = org_reviewing(S, poy)
    new["org_review_value"] = org_review_value(S)
    new["new_reviewer_growth"] = new_reviewer_growth(S)
    ai_kinds(S)
    new["ai_quarters"] = ai_quarters(S)
    new["ai_reviewer_load"] = ai_reviewer_load(S)
    new["ai_summary"] = ai_summary(S, ds.get("ai_paired", []))
    new["capacity_years"], new["capacity_tenure"], new["capacity_orgs"] = capacity(S, poy)
    for k, v in new.items():
        print(f"{k}: {len(v)} rows", file=sys.stderr)
        ds[k] = v
    tmp = args.path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, separators=(",", ":"))
        f.write("\n")
    os.replace(tmp, args.path)


if __name__ == "__main__":
    main()
