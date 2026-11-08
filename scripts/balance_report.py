"""Datasets for the author/reviewer balance report (docs/balance.md).

Offline; reads balance*.sqlite, derived.sqlite and labels.sqlite. Writes one
JSON file of aggregates (no identities, no comment text).

  COSH_DATA_DIR=<main>/data/private python3 scripts/balance_report.py \
      --first-commit F --owners-added F --ai-marked F --mech mech.jsonl --out report.json
"""

import argparse
import json
import math
import os
import sqlite3
import statistics as st
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import balance_analysis as A  # noqa: E402
import balance_growth as G  # noqa: E402
from cosh import balance, classify, store  # noqa: E402

YEAR = G.YEAR
DAY = 86400
FIRST_Q, LAST_Q = "2023Q3", "2026Q3"      # whole quarters of Gerrit data


def pct(xs, p):
    xs = sorted(x for x in xs if x is not None)
    return round(xs[min(len(xs) - 1, int(p * len(xs)))], 2) if xs else None


def r(x, n=2):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(x, n)


def mech_set(path):
    out = set()
    for line in open(path):
        n, files, threads, rep, lines = json.loads(line)
        if files >= 100 or (rep is not None and rep >= 0.8):
            out.add(n)
    return out


def quarters(lo, hi):
    y, q = int(lo[:4]), int(lo[-1])
    while f"{y}Q{q}" <= hi:
        yield f"{y}Q{q}"
        q += 1
        if q == 5:
            y, q = y + 1, 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--first-commit", required=True)
    ap.add_argument("--owners-added", required=True)
    ap.add_argument("--ai-marked")
    ap.add_argument("--mech", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    cls, commits, ids, first, owner_at, ai = G.load_all(args)
    mech = mech_set(args.mech)
    dirs3 = A.commit_dirs(3)
    top2 = {}
    for c in commits:
        d = dirs3.get(c["cid"])
        if c["n"] and d:
            top2[c["n"]] = "/".join(d[0].split("/")[:2])
    A.MECH_FILES = 10 ** 9          # cl_residuals' provisional rule off; use the repetition rule
    for c in cls:
        if c["change_number"] in mech:
            c["status"] = "MECH"     # dropped by every MERGED filter below
    out = {"generated": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "mechanical_cls": len(mech)}
    use = G.cl_residuals(cls, top2)            # merged, non-mechanical, with residuals and exp24
    for c in use:
        c["q"] = A.quarter(c["closed_at"])
        c["ten"] = (c["closed_at"] - first[c["pid"]]) / YEAR if c["pid"] in first else None
        c["ftr"] = (c["first_review_at"] - c["sent_at"]) / 3600 \
            if c["first_review_at"] and c["sent_at"] and c["first_review_at"] >= c["sent_at"] else None
    byq = defaultdict(list)
    for c in use:
        byq[c["q"]].append(c)
    Q = list(quarters(FIRST_Q, LAST_Q))

    # ---------------------------------------------------------- the exchange
    ex = []
    for q in Q:
        s = byq[q]
        rv = [c for c in s if c["first_review_at"]]
        idf = [c for c in rv if c["interdiff_status"] == "ok" and c["lines_final"]]
        authors = len({c["pid"] for c in s})
        ex.append(dict(
            q=q, cls=len(s), authors=authors, cls_per_author=r(len(s) / authors),
            median_lines=st.median(c["lines"] for c in s), p90_lines=pct([c["lines"] for c in s], .9),
            threads_per_cl=r(st.mean(c["threads"] for c in s)),
            threads_per_100=r(st.mean(100 * c["threads"] / c["lines"] for c in s if c["lines"] >= 10)),
            addressed_per_cl=r(st.mean(c["addressed"] for c in s)),
            load_index=r(sum(c["threads"] for c in s) / sum(c["exp24"] for c in s)),
            no_substantive=r(1 - len(rv) / len(s), 3),
            interdiff_share=r(sum(c["lines_changed"] for c in idf) / sum(c["lines_final"] for c in idf)),
            interdiff_p50=pct([c["lines_changed"] / c["lines_final"] for c in idf], .5),
            rounds=r(st.mean(c["rounds"] or 0 for c in rv)),
            reverted=r(sum(1 for c in s if c["reverted_at"] and c["reverted_at"] - c["closed_at"] < 30 * DAY)
                       / len(s), 4),
            ftr=[pct([c["ftr"] for c in rv], p) for p in (.25, .5, .75, .9)],
            reviewer_wait_p50=pct([c["reviewer_wait_h"] for c in rv], .5),
            reviewer_wait_wd_p50=pct([c["reviewer_wait_wd_h"] for c in rv], .5),
            owner_wait_p50=pct([c["owner_wait_h"] for c in rv], .5),
            ai_marked=sum(1 for c in s if c.get("sha") in ai)))
    out["exchange"] = ex

    # Git: long series, with reviewer concentration from Reviewed-by.
    gq = defaultdict(list)
    for c in commits:
        if c["n"]:
            gq[A.quarter(c["at"])].append(c)
    gl = []
    for q in quarters("2017Q3", LAST_Q):
        s = [c for c in gq[q] if not c["is_revert"]]
        if not s:
            continue
        authors = Counter(c["pid"] for c in s)
        appr = Counter(rv for c in s for rv in c["rbp"] if rv != c["pid"])
        top = sorted(appr.values(), reverse=True)
        k = max(1, len(top) // 10)
        both = set(authors) & set(appr)
        gl.append(dict(
            q=q, commits=len(s), authors=len(authors), approvers=len(appr),
            per_author_month=r(len(s) / len(authors) / 3), median_lines=st.median(c["lines"] for c in s),
            approvals_per_approver_month=r(sum(top) / max(1, len(top)) / 3),
            top10_share=r(sum(top[:k]) / max(1, sum(top)), 3),
            approvers_per_author=r(len(appr) / len(authors), 3),
            authors_who_review=r(len(both) / len(authors), 3),
            reverted=r(sum(1 for c in s if c["reverted_at"] and c["reverted_at"] - c["at"] < 30 * DAY) / len(s), 4)))
    out["git_quarters"] = gl

    # ------------------------------------------- reviewer-side, per (CL, reviewer)
    d = A.ro(os.path.join(store.DATA_DIR, store.DERIVED_FILE))
    emails = dict(d.execute("SELECT account_id, email FROM accounts"))
    bots = {a for a, in d.execute("SELECT account_id FROM accounts WHERE is_bot = 1")}
    cl_by_n = {c["change_number"]: c for c in use}
    first_c = {}
    for n, acct, at in d.execute("SELECT change_number, account_id, min(written_at) FROM comments "
                                 "WHERE after_close = 0 GROUP BY 1, 2"):
        if n in cl_by_n and acct not in bots:
            first_c[(n, acct)] = balance.epoch(at)
    labels = {}
    lp = classify.labels_path(store.DATA_DIR)
    ldb = sqlite3.connect(f"file:{lp}?mode=ro", uri=True)
    act = classify.active_classifier(ldb)
    if act:
        labels = {(n, rt, h): a for n, rt, h, a in ldb.execute(
            "SELECT change_number, root_uuid, input_hash, addressed FROM labels WHERE classifier_id = ?", (act[0],))}
    thr = defaultdict(lambda: [0, 0])
    for n, rt, reply, rx, h, acct in d.execute("SELECT change_number, root_uuid, last_owner_reply_at, "
                                               "regex_addressed, input_hash, root_account FROM threads"):
        if n in cl_by_n and acct not in bots:
            t = thr[(n, acct)]
            t[0] += 1
            t[1] += (0 if reply is None else 1 if rx else labels.get((n, rt, h)) or 0)
    tl = A.ro(balance.db_path("timeline"))
    added = {}
    for n, acct, s in tl.execute("SELECT change_number, account_id, min(start_at) FROM attention GROUP BY 1, 2"):
        if n in cl_by_n:
            added[(n, acct)] = s

    def rten(acct, t):
        e = emails.get(acct)
        if not e or A.is_bot_email(e):
            return None
        p = ids.find(e)
        return (t - first[p]) / YEAR if p in first else None

    band = lambda t: None if t is None else "<2y" if t < 2 else "2-5y" if t < 5 else "5-10y" if t < 10 else "10y+"
    rv_rows = defaultdict(lambda: dict(resp=[], threads=[], addressed=[], newcomer=[]))
    per_reviewer_q = defaultdict(Counter)
    for (n, acct), t0 in first_c.items():
        c = cl_by_n[n]
        if acct == c["owner"]:
            continue
        tb = band(rten(acct, c["closed_at"]))
        if tb is None:
            continue
        h = G.half_name(G.half(c["closed_at"]))
        x = rv_rows[(h, tb)]
        a = added.get((n, acct))
        if a and t0 >= a:
            x["resp"].append(
                             balance.weekday_seconds(a, t0) / 3600)
        t = thr.get((n, acct), [0, 0])
        x["threads"].append(t[0])
        x["addressed"].append(t[1])
        x["newcomer"].append(c["ten"] is not None and c["ten"] < 1)
        per_reviewer_q[(acct, c["q"])]["cls"] += 1
        per_reviewer_q[(acct, c["q"])]["threads"] += t[0]
    halves = sorted({h for h, _ in rv_rows})
    out["reviewers_by_tenure"] = [
        dict(half=h, band=b, reviews=len(x["threads"]),
             resp_p50=pct(x["resp"], .5), resp_p75=pct(x["resp"], .75),
             threads_per_review=r(st.mean(x["threads"])), addressed_per_review=r(st.mean(x["addressed"])),
             newcomer_share=r(st.mean(x["newcomer"]), 3))
        for h in halves for b in ("<2y", "2-5y", "5-10y", "10y+") for x in [rv_rows.get((h, b))] if x]
    # Commenting reviewers per quarter, and how concentrated reviewer threads are.
    rq = []
    for q in Q:
        rs = [(a, v) for (a, qq), v in per_reviewer_q.items() if qq == q]
        th = sorted((v["threads"] for _, v in rs), reverse=True)
        k = max(1, len(th) // 10)
        authors = len({c["pid"] for c in byq[q]})
        rq.append(dict(q=q, reviewers=len(rs), authors=authors, reviewers_per_author=r(len(rs) / authors, 3),
                       cls_per_reviewer=r(len(byq[q]) / max(1, len(rs))),
                       threads_top10_share=r(sum(th[:k]) / max(1, sum(th)), 3),
                       reviewer_hours_per_cl=r(sum(c["reviewer_wait_wd_h"] or 0 for c in byq[q]) / len(byq[q]))))
    out["reviewer_quarters"] = rq

    # -------------------------------------------------------------- by area
    def era(c):
        y = A.year(c["closed_at"])
        if y == 2024:
            return "2024"
        if c["closed_at"] >= datetime(2025, 10, 1, tzinfo=timezone.utc).timestamp() and c["q"] <= LAST_Q:
            return "recent"       # 2025Q4 .. 2026Q3
        return None
    ar = defaultdict(lambda: defaultdict(list))
    for c in use:
        e = era(c)
        if e and c["d2"]:
            ar[c["d2"]][e].append(c)
    areas = []
    for a, es in ar.items():
        if len(es["2024"]) < 400 or len(es["recent"]) < 400:
            continue
        row = dict(area=a)
        for e, s in es.items():
            rv = [c for c in s if c["first_review_at"]]
            idf = [c for c in rv if c["interdiff_status"] == "ok" and c["lines_final"]]
            row[e] = dict(
                cls=len(s), authors=len({c["pid"] for c in s}), median_lines=st.median(c["lines"] for c in s),
                threads_per_100=r(st.mean(100 * c["threads"] / c["lines"] for c in s if c["lines"] >= 10)),
                load_index=r(sum(c["threads"] for c in s) / sum(c["exp24"] for c in s)),
                ftr_p50=pct([c["ftr"] for c in rv], .5),
                interdiff_share=r(sum(c["lines_changed"] for c in idf) / max(1, sum(c["lines_final"] for c in idf))),
                newcomer_share=r(sum(1 for c in s if c["ten"] is not None and c["ten"] < 1) / len(s), 3),
                reverted=r(sum(1 for c in s if c["reverted_at"] and c["reverted_at"] - c["closed_at"] < 30 * DAY)
                           / len(s), 4))
        areas.append(row)
    areas.sort(key=lambda x: -(x["2024"]["cls"] + x["recent"]["cls"]))
    out["areas"] = areas[:30]

    # ---------------------------------------------- cohort curves (Gerrit era)
    def cohort(pid):
        if pid not in first:
            return None
        t = first[pid]
        if datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp() <= t < datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp():
            return "joined 2023"
        if datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp() <= t < datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp():
            return "joined 2025"
        if datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() <= t < datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp():
            return "joined 2024"
        return None
    mb = [(0, 3), (3, 6), (6, 9), (9, 12), (12, 18), (18, 24), (24, 36)]
    fam = G.familiarity(commits, dirs3)
    cc = defaultdict(lambda: defaultdict(lambda: dict(t=0.0, e=0.0, n=0, lines=[], months=Counter(), new=0,
                                                     ish=[], people=set())))
    for c in use:
        k = cohort(c["pid"])
        if not k:
            continue
        m = (c["closed_at"] - first[c["pid"]]) / (YEAR / 12)
        for lo, hi in mb:
            if lo <= m < hi:
                x = cc[k][f"{lo}-{hi}"]
                x["t"] += c["threads"]
                x["e"] += c["exp24"]
                x["n"] += 1
                x["lines"].append(c["lines"])
                x["people"].add(c["pid"])
                x["new"] += fam.get(c["change_number"]) == "0"
                if c["ish"] is not None:
                    x["ish"].append(c["ish"])
    # reviewing done by the cohort, by months since joining (Gerrit threads started on others' CLs)
    rc = defaultdict(lambda: defaultdict(lambda: dict(cls=0, threads=0, people=set())))
    for (n, acct), _ in first_c.items():
        c = cl_by_n[n]
        e = emails.get(acct)
        if not e or acct == c["owner"]:
            continue
        p = ids.find(e)
        k = cohort(p)
        if not k:
            continue
        m = (c["closed_at"] - first[p]) / (YEAR / 12)
        for lo, hi in mb:
            if lo <= m < hi:
                y = rc[k][f"{lo}-{hi}"]
                y["cls"] += 1
                y["threads"] += thr.get((n, acct), [0, 0])[0]
                y["people"].add(p)
    curves = []
    for k in ("joined 2023", "joined 2024", "joined 2025"):
        for lo, hi in mb:
            x = cc[k].get(f"{lo}-{hi}")
            if not x or x["n"] < 200:
                continue
            ppl = len(x["people"])
            y = rc[k].get(f"{lo}-{hi}", dict(cls=0, threads=0, people=set()))
            curves.append(dict(cohort=k, months=f"{lo}-{hi}", cls=x["n"], people=ppl,
                               load_index=r(x["t"] / x["e"]), median_lines=st.median(x["lines"]),
                               cls_per_person_month=r(x["n"] / ppl / (hi - lo)),
                               new_dir_share=r(x["new"] / x["n"], 3),
                               interdiff_p50=pct(x["ish"], .5),
                               reviews_per_person_month=r(y["cls"] / ppl / (hi - lo)),
                               review_threads_per_person_month=r(y["threads"] / ppl / (hi - lo))))
    out["cohort_curves"] = curves

    # ---------------------------------------------- long git cohorts: velocity, size, review share
    lc = []
    authored = defaultdict(Counter)
    given = defaultdict(Counter)
    lines = defaultdict(lambda: defaultdict(list))
    for c in commits:
        if not c["n"] or c["is_revert"]:
            continue
        y = A.year(c["at"])
        authored[c["pid"]][y] += 1
        lines[c["pid"]][y].append(c["lines"])
        for rv in c["rbp"]:
            if rv != c["pid"]:
                given[rv][y] += 1
    for fy in range(2017, 2026):
        ppl = [p for p, t in first.items() if A.year(t) == fy]
        for k in range(1, 10):
            y = fy + k - 1
            if y > 2026:
                break
            act = [p for p in ppl if authored[p][y] + given[p][y] >= 6]
            if len(act) < 20:
                continue
            lc.append(dict(cohort=fy, year=k, cal=y, people=len(act),
                           review_share=r(st.median(given[p][y] / (given[p][y] + authored[p][y]) for p in act)),
                           cls_per_year=st.median(authored[p][y] for p in act),
                           approvals_per_year=st.median(given[p][y] for p in act),
                           median_lines=st.median(st.median(lines[p][y]) for p in act if lines[p][y])))
    out["git_cohorts"] = lc

    # -------------------------------------------------- learning curves by era
    lcv = defaultdict(lambda: [0.0, 0.0, 0])
    for c in use:
        if c["ten"] is None or c["q"] > LAST_Q:
            continue
        e = "2023H2-2024" if A.year(c["closed_at"]) <= 2024 else ("2025" if A.year(c["closed_at"]) == 2025
                                                                 else "2026 (to Sep)")
        m = c["ten"] * 12
        b = next((f"{lo}-{hi}" for lo, hi in [(0, 3), (3, 6), (6, 12), (12, 24), (24, 60), (60, 120), (120, 999)]
                  if lo <= m < hi), None)
        x = lcv[(e, b)]
        x[0] += c["threads"]
        x[1] += c["exp24"]
        x[2] += 1
        f = fam.get(c["change_number"])
        if f:
            y = lcv[(e, "fam " + f)]
            y[0] += c["threads"]
            y[1] += c["exp24"]
            y[2] += 1
    out["learning"] = [dict(era=e, bucket=b, load_index=r(v[0] / v[1]), cls=v[2]) for (e, b), v in lcv.items()]

    with open(args.out, "w") as f:
        json.dump(out, f, indent=1)
    print(f"wrote {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
