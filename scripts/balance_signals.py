"""Growth signals beyond review threads (docs/balance-signals.md).

  COSH_DATA_DIR=... python3 scripts/balance_signals.py report --first-commit F --out signals.json
      -1s and abandonment by tenure, balanced reviewer/author panels, matched cohorts.

Aggregates only: nothing per person is written to the output.
"""

import argparse
import json
import math
import os
import random
import statistics as st
import sys
import time
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cosh import balance, store  # noqa: E402

YEAR = 365.25 * 86400
FIRST_TS = 1687737600          # 2023-06-26 00:00 UTC: Monday of 2023-W26, the first Gerrit week
END_TS = 1793491200            # 2026-11-01 00:00 UTC: end of the data used (2026-W44)

# ------------------------------------------------------------------ report

import balance_analysis as A  # noqa: E402
import balance_growth as G  # noqa: E402
import balance_report as R  # noqa: E402

ERAS = [("2023H2-2024", 2023, 2024), ("2025", 2025, 2025), ("2026", 2026, 2026)]
TENURE = [(0, 3), (3, 6), (6, 12), (12, 24), (24, 60), (60, 120), (120, 9999)]
COHORT_MONTHS = [(0, 3), (3, 6), (6, 9), (9, 12), (12, 18), (18, 24)]
MONTH = YEAR / 12


def era_of(t):
    y = A.year(t)
    for name, lo, hi in ERAS:
        if lo <= y <= hi:
            return name
    return None


def bucket(m, buckets):
    for lo, hi in buckets:
        if lo <= m < hi:
            return f"{lo}-{hi}" if hi < 9999 else f"{lo}+"
    return None


def rate(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 4) if xs else None


def mean(xs, n=3):
    xs = [x for x in xs if x is not None]
    return round(st.mean(xs), n) if xs else None


def boot_ci(per_unit, reps=1000, seed=11):
    """Mean of per-unit differences and its 95% bootstrap interval over units."""
    xs = [x for x in per_unit if x is not None and not math.isnan(x)]
    if len(xs) < 10:
        return dict(n=len(xs), mean=None, lo=None, hi=None)
    rnd = random.Random(seed)
    ms = sorted(st.mean(rnd.choices(xs, k=len(xs))) for _ in range(reps))
    return dict(n=len(xs), mean=round(st.mean(xs), 4), lo=round(ms[int(.025 * reps)], 4),
                hi=round(ms[int(.975 * reps) - 1], 4))


def load(args):
    cls, commits, ids, first, owner_at, ai = G.load_all(args)
    mech = R.mech_set(args.mech)
    d = A.ro(os.path.join(store.DATA_DIR, store.DERIVED_FILE))
    emails = dict(d.execute("SELECT account_id, email FROM accounts"))
    bots = {a for a, in d.execute("SELECT account_id FROM accounts WHERE is_bot = 1")}
    acct_pid = {a: ids.find(e) for a, e in emails.items() if e and not A.is_bot_email(e) and a not in bots}
    # Code-Review votes (by non-owner humans, filtered below) and uploads
    # before the CL was sent for review (the author polishing alone).
    tl = A.ro(balance.db_path("timeline"))
    votes = defaultdict(list)
    for n, voter, value, at in tl.execute("SELECT change_number, voter, value, at FROM votes"):
        votes[n].append((voter, value, at))
    uploads = defaultdict(list)
    for n, at, who, kind in tl.execute("SELECT change_number, at, uploader, kind FROM uploads"):
        uploads[n].append((at, who, kind))
    top2, top3 = {}, {}
    dirs3 = A.commit_dirs(3)
    cid_of = {}
    for c in commits:
        dd = dirs3.get(c["cid"])
        if c["n"]:
            cid_of[c["n"]] = c["cid"]
            if dd:
                top2[c["n"]] = "/".join(dd[0].split("/")[:2])
                top3[c["n"]] = dd[0]
    # Familiarity: the author's earlier commits in the CL's main 3-level directory.
    fam = {}
    seen = Counter()
    for c in sorted(commits, key=lambda c: c["at"]):
        dd = dirs3.get(c["cid"])
        if not dd or c["is_revert"]:
            continue
        if c["n"]:
            fam[c["n"]] = seen[(c["pid"], dd[0])]
        seen[(c["pid"], dd[0])] += 1
    return dict(cls=cls, commits=commits, ids=ids, first=first, mech=mech, emails=emails, bots=bots,
                acct_pid=acct_pid, votes=votes, uploads=uploads, top2=top2, top3=top3, fam=fam, d=d)


def annotate(L):
    """Per CL in the Gerrit window: size, tenure, negative votes, outcome."""
    first, votes, bots = L["first"], L["votes"], L["bots"]
    use = []
    for c in L["cls"]:
        if c["change_number"] in L["mech"] or not c["pid"] or c["status"] not in ("MERGED", "ABANDONED"):
            continue
        if not c["closed_at"] or not FIRST_TS <= c["closed_at"] < END_TS:
            continue
        c["lines"] = (c["ins"] or 0) + (c["dels"] or 0)
        c["sb"] = G.size10(c["lines"])
        c["era"] = era_of(c["closed_at"])
        t0 = first.get(c["pid"])
        c["months"] = (c["created_at"] - t0) / MONTH if t0 is not None and c["created_at"] >= t0 - 30 * 86400 else None
        if c["months"] is not None:
            c["months"] = max(0.0, c["months"])
        vs = [(voter, value, at) for voter, value, at in votes.get(c["change_number"], [])
              if voter != c["owner"] and voter not in bots]
        negs = [at for voter, value, at in vs if value < 0]
        c["neg"] = len(negs)
        c["first_neg"] = min(negs) if negs else None
        c["reviewed"] = bool(c["first_review_at"])
        c["abandoned"] = c["status"] == "ABANDONED"
        ups = L["uploads"].get(c["change_number"], [])
        sent = c["sent_at"] or c["created_at"]
        c["pre_send"] = sum(1 for at, who, kind in ups if who == c["owner"] and kind == "rework" and at < sent)
        c["rework_after_neg"] = c["first_neg"] is not None and any(
            who == c["owner"] and kind == "rework" and at > c["first_neg"] for at, who, kind in ups)
        c["d2"] = L["top2"].get(c["change_number"])
        c["fam"] = L["fam"].get(c["change_number"])
        c["reverted30"] = bool(c["reverted_at"] and c["closed_at"] and c["reverted_at"] - c["closed_at"] < 30 * 86400)
        c["ish"] = min(2.0, c["lines_changed"] / c["lines_final"]) \
            if c["status"] == "MERGED" and c["lines_changed"] is not None and c["lines_final"] else None
        use.append(c)
    # Size-only expectation for 2023-24 (every status: abandoned CLs have no landed directory).
    norm = defaultdict(lambda: [0, 0, 0])
    for c in use:
        if c["era"] == "2023H2-2024" and c["reviewed"]:
            x = norm[c["sb"]]
            x[0] += 1
            x[1] += c["neg"] > 0
            x[2] += c["abandoned"]
    for c in use:
        x = norm.get(c["sb"])
        c["exp_neg"] = x[1] / x[0] if x and x[0] else None
        c["exp_aband"] = x[2] / x[0] if x and x[0] else None
    return use


def neg_abandon_tables(use):
    out = {}
    rows = []
    for era, _, _ in ERAS:
        for lo, hi in TENURE:
            b = bucket(lo, TENURE)
            s = [c for c in use if c["era"] == era and c["reviewed"] and c["months"] is not None
                 and bucket(c["months"], TENURE) == b]
            if len(s) < 100:
                continue
            negd = [c for c in s if c["neg"]]
            rows.append(dict(
                era=era, tenure_months=b, cls=len(s),
                abandon_rate=rate(c["abandoned"] for c in s),
                abandon_index=round(sum(c["abandoned"] for c in s) / sum(c["exp_aband"] for c in s), 3),
                neg_share=rate(c["neg"] > 0 for c in s),
                neg_index=round(sum(c["neg"] > 0 for c in s) / sum(c["exp_neg"] for c in s), 3),
                negs_per_cl=mean((c["neg"] for c in s), 3),
                h_to_first_neg_p50=R.pct([(c["first_neg"] - (c["sent_at"] or c["created_at"])) / 3600
                                          for c in negd if c["first_neg"] >= (c["sent_at"] or c["created_at"])], .5),
                after_neg_abandoned=rate(c["abandoned"] for c in negd),
                after_neg_landed_reworked=rate((not c["abandoned"]) and c["rework_after_neg"] for c in negd),
                after_neg_landed_unchanged=rate((not c["abandoned"]) and not c["rework_after_neg"] for c in negd),
            ))
    out["by_tenure"] = rows
    fb = [(0, 1), (1, 5), (5, 20), (20, 100), (100, 10 ** 9)]
    rows = []
    for era, _, _ in ERAS:
        for lo, hi in fb:
            s = [c for c in use if c["era"] == era and c["reviewed"] and c["status"] == "MERGED"
                 and c["fam"] is not None and lo <= c["fam"] < hi]
            if len(s) < 100:
                continue
            rows.append(dict(era=era, prior_commits_in_dir=f"{lo}-{hi - 1}" if hi < 10 ** 9 else f"{lo}+", cls=len(s),
                             neg_share=rate(c["neg"] > 0 for c in s),
                             neg_index=round(sum(c["neg"] > 0 for c in s) / sum(c["exp_neg"] for c in s), 3)))
    out["by_familiarity_merged"] = rows
    rows = []
    for y in (2023, 2024, 2025):
        for lo, hi in COHORT_MONTHS:
            s = [c for c in use if c["reviewed"] and c["months"] is not None and lo <= c["months"] < hi
                 and A.year(c["created_at"] - c["months"] * MONTH) == y]
            if len(s) < 50:
                continue
            rows.append(dict(cohort=f"joined {y}", months=f"{lo}-{hi}", cls=len(s), people=len({c["pid"] for c in s}),
                             abandon_rate=rate(c["abandoned"] for c in s),
                             abandon_index=round(sum(c["abandoned"] for c in s) / sum(c["exp_aband"] for c in s), 3),
                             neg_share=rate(c["neg"] > 0 for c in s),
                             neg_index=round(sum(c["neg"] > 0 for c in s) / sum(c["exp_neg"] for c in s), 3)))
    out["cohorts"] = rows
    # Era totals.
    out["by_era"] = [dict(era=era, cls=len(s), abandon_rate=rate(c["abandoned"] for c in s),
                          neg_share=rate(c["neg"] > 0 for c in s),
                          after_neg_abandoned=rate(c["abandoned"] for c in s if c["neg"]))
                     for era, _, _ in ERAS for s in [[c for c in use if c["era"] == era and c["reviewed"]]]]
    return out


def reviewer_pairs(L, use):
    """(CL, reviewer) pairs: the reviewer commented on someone else's CL."""
    d, bots, acct_pid = L["d"], L["bots"], L["acct_pid"]
    by_n = {c["change_number"]: c for c in use}
    threads = Counter()
    for n, acct in d.execute("SELECT change_number, root_account FROM threads"):
        if n in by_n:
            threads[(n, acct)] += 1
    pairs = []
    for n, acct in d.execute("SELECT DISTINCT change_number, account_id FROM comments WHERE after_close = 0"):
        c = by_n.get(n)
        if c is None or acct == c["owner"] or acct in bots or acct not in acct_pid:
            continue
        neg = any(voter == acct and value < 0 for voter, value, _ in L["votes"].get(n, []))
        pairs.append(dict(n=n, acct=acct, year=A.year(c["closed_at"]), sb=c["sb"], d2=c["d2"],
                          tb=bucket(c["months"], TENURE) if c["months"] is not None else "?",
                          threads=threads[(n, acct)], neg=neg))
    return pairs


def panels(L, use):
    out = {}
    # ---- reviewer side
    pairs = reviewer_pairs(L, use)
    base = [p for p in pairs if p["year"] == 2024]

    def expect(rows, key, keys):
        g = [defaultdict(list) for _ in keys]
        for p in rows:
            for i, k in enumerate(keys):
                g[i][k(p)].append(key(p))
        return [{k: st.mean(v) for k, v in gi.items() if len(v) >= 30} for gi in g]

    def resid(p, means, keys, key):
        for m, k in zip(means, keys):
            if k(p) in m:
                return key(p) - m[k(p)]
        return None

    keys = [lambda p: (p["sb"], p["d2"], p["tb"]), lambda p: (p["sb"], p["tb"]), lambda p: p["sb"]]
    for name, key in (("log1p_threads", lambda p: math.log1p(p["threads"])), ("neg_vote", lambda p: float(p["neg"]))):
        means = expect(base, key, keys)
        per = defaultdict(lambda: defaultdict(list))
        for p in pairs:
            if p["year"] in (2024, 2026):
                r = resid(p, means, keys, key)
                if r is not None:
                    per[p["acct"]][p["year"]].append(r)
        diffs = [st.mean(v[2026]) - st.mean(v[2024]) for v in per.values()
                 if len(v[2024]) >= 20 and len(v[2026]) >= 20]
        out[f"reviewer_{name}"] = boot_ci(diffs)
    # Raw panel figures, for the plain-language table.
    cnt = defaultdict(Counter)
    for p in pairs:
        cnt[p["acct"]][p["year"]] += 1
    panel = {a for a, c in cnt.items() if c[2024] >= 20 and c[2026] >= 20}
    for y in (2024, 2026):
        s = [p for p in pairs if p["acct"] in panel and p["year"] == y]
        out[f"reviewer_panel_{y}"] = dict(reviewers=len(panel), reviews=len(s),
                                          threads_per_review=mean((p["threads"] for p in s), 3),
                                          neg_vote_rate=rate(p["neg"] for p in s))

    # ---- author side: the same authors, signals the reviewer doesn't set
    akeys = [lambda c: (c["sb"], c["tbx"]), lambda c: c["sb"]]
    for c in use:
        c["tbx"] = bucket(c["months"], TENURE) if c["months"] is not None else "?"
    rv = [c for c in use if c["reviewed"]]
    base = [c for c in rv if A.year(c["closed_at"]) == 2024]
    metrics = {
        "interdiff_share": (lambda c: c["ish"], lambda c: c["ish"] is not None),
        "rounds": (lambda c: float(c["rounds"] or 0), lambda c: c["status"] == "MERGED"),
        "pre_send_uploads": (lambda c: float(c["pre_send"]), lambda c: True),
        "reverted_30d": (lambda c: float(c["reverted30"]), lambda c: c["status"] == "MERGED"),
        "abandoned": (lambda c: float(c["abandoned"]), lambda c: True),
        "neg_received": (lambda c: float(c["neg"] > 0), lambda c: True),
        "log1p_threads_received": (lambda c: math.log1p(c["threads"]), lambda c: True),
    }
    cnt = defaultdict(Counter)
    for c in rv:
        cnt[c["pid"]][A.year(c["closed_at"])] += 1
    apanel = {a for a, k in cnt.items() if k[2024] >= 10 and k[2026] >= 10}
    out["author_panel_size"] = len(apanel)
    for name, (val, ok) in metrics.items():
        rows = [c for c in base if ok(c)]
        means = expect(rows, val, akeys)
        per = defaultdict(lambda: defaultdict(list))
        for c in rv:
            y = A.year(c["closed_at"])
            if c["pid"] in apanel and y in (2024, 2026) and ok(c):
                r = resid(c, means, akeys, val)
                if r is not None:
                    per[c["pid"]][y].append(r)
        diffs = [st.mean(v[2026]) - st.mean(v[2024]) for v in per.values() if v[2024] and v[2026]]
        out[f"author_{name}"] = boot_ci(diffs)
        raw = {y: mean((val(c) for c in rv if c["pid"] in apanel and A.year(c["closed_at"]) == y and ok(c)), 4)
               for y in (2024, 2026)}
        out[f"author_{name}"]["raw_2024"], out[f"author_{name}"]["raw_2026"] = raw[2024], raw[2026]
    return out


def matched_cohorts(L, use, seed=5):
    """Pair each 2025 joiner with a 2024 joiner on first-quarter size, top-level
    directory, domain group and prior Gerrit activity; compare months 0-12."""
    first, acct_pid, d = L["first"], L["acct_pid"], L["d"]
    by_pid = defaultdict(list)
    for c in use:
        by_pid[c["pid"]].append(c)
    # Prior Gerrit activity: comments (anywhere) before the first commit on main.
    first_comment = {}
    for acct, t in d.execute("SELECT account_id, min(written_at) FROM comments GROUP BY 1"):
        p = acct_pid.get(acct)
        if p:
            tt = balance.epoch(t)
            first_comment[p] = min(tt, first_comment.get(p, tt))
    reviews = defaultdict(list)    # pid -> times they commented on someone else's CL
    owner_of = {c["change_number"]: c["owner"] for c in L["cls"]}
    for n, acct, t in d.execute("SELECT change_number, account_id, min(written_at) FROM comments "
                                "WHERE after_close = 0 GROUP BY 1, 2"):
        p = acct_pid.get(acct)
        if p and owner_of.get(n) not in (None, acct):
            reviews[p].append(balance.epoch(t))

    def profile(p):
        t0 = first[p]
        early = [c for c in by_pid[p] if c["months"] is not None and c["months"] < 3]
        if not early:
            return None
        size = st.median(c["lines"] for c in early)
        dirs = Counter((c["d2"] or "?").split("/")[0] for c in early)
        email = next((c["owner_email"] for c in early if c["owner_email"]), "") or ""
        dom = "google" if email.endswith(("@google.com", "@chromium.org")) else "other"
        prior = p in first_comment and first_comment[p] < t0 - 14 * 86400
        return (0 if size < 20 else 1 if size < 100 else 2, dirs.most_common(1)[0][0], dom, prior)

    arms = {2024: [], 2025: []}
    for p, t0 in first.items():
        y = A.year(t0)
        if y in arms and t0 >= FIRST_TS and p in by_pid:
            pr = profile(p)
            if pr:
                arms[y].append((p, pr))
    cells = defaultdict(lambda: {2024: [], 2025: []})
    for y, lst in arms.items():
        for p, pr in lst:
            cells[pr][y].append(p)
    rnd = random.Random(seed)
    pairs = []
    for pr, cell in cells.items():
        a, b = cell[2025][:], cell[2024][:]
        rnd.shuffle(a)
        rnd.shuffle(b)
        pairs += [(x, y, pr) for x, y in zip(a, b)]
    out = dict(joiners_2025=len(arms[2025]), joiners_2024=len(arms[2024]), matched_pairs=len(pairs),
               prior_activity_share_2025=rate(pr[3] for _, pr in arms[2025]),
               prior_activity_share_2024=rate(pr[3] for _, pr in arms[2024]),
               google_share_2025=rate(pr[2] == "google" for _, pr in arms[2025]),
               google_share_2024=rate(pr[2] == "google" for _, pr in arms[2024]))
    rows = []
    for lo, hi in COHORT_MONTHS[:4]:
        for arm in (2025, 2024):
            people = [x if arm == 2025 else y for x, y, _ in pairs]
            # Only people whose window [lo, hi) months is fully observed.
            people = [p for p in people if first[p] + hi * MONTH <= END_TS]
            cs = [c for p in people for c in by_pid[p] if c["months"] is not None and lo <= c["months"] < hi]
            active = {c["pid"] for c in cs}
            merged = [c for c in cs if c["status"] == "MERGED" and c["reviewed"]]
            rv = [c for c in cs if c["reviewed"]]
            given = sum(1 for p in active for t in reviews[p] if first[p] + lo * MONTH <= t < first[p] + hi * MONTH)
            exp = sum(c["exp24"] for c in merged if c.get("exp24"))
            rows.append(dict(
                months=f"{lo}-{hi}", arm=f"joined {arm}", people=len(people), active=len(active),
                still_active=rate(p in active for p in people),
                cls_per_active_month=round(sum(1 for c in cs if c["status"] == "MERGED") / max(1, len(active)) / (hi - lo), 2),
                reviews_given_per_active_month=round(given / max(1, len(active)) / (hi - lo), 2),
                feedback_index=round(sum(c["threads"] for c in merged if c.get("exp24")) / exp, 3) if exp else None,
                threads_resid=mean((c.get("r_threads") for c in merged), 3),
                interdiff_p50=R.pct([c["ish"] for c in merged if c["ish"] is not None], .5),
                rounds=mean((c["rounds"] or 0 for c in merged), 3),
                neg_share=rate(c["neg"] > 0 for c in rv),
                abandon_rate=rate(c["abandoned"] for c in rv),
            ))
    out["months"] = rows
    return out


def report(args):
    L = load(args)
    use = annotate(L)
    # The feedback index's expectation (exp24) and calendar-adjusted thread residual, merged CLs.
    A.MECH_FILES = 10 ** 9      # the repetition rule (mech) applies instead of the provisional one
    merged = G.cl_residuals([c for c in L["cls"] if c["change_number"] not in L["mech"]], L["top2"])
    res = {c["change_number"]: c for c in merged}
    for c in use:
        m = res.get(c["change_number"])
        c["exp24"] = m["exp24"] if m else None
        c["r_threads"] = m["r_threads"] if m else None
    out = dict(generated=time.strftime("%Y-%m-%d"), window="2023-W26 .. 2026-W44 (closed CLs)",
               cls=len(use), votes_cls=len(L["votes"]))
    out.update(neg_abandon_tables(use))
    out["panels"] = panels(L, use)
    out["matched"] = matched_cohorts(L, use)
    with open(args.out, "w") as f:
        json.dump(out, f, indent=1)
    print(f"wrote {args.out}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["report"])
    ap.add_argument("--first-commit", help="default: commits.sqlite")
    ap.add_argument("--owners-added", help="default: commits.sqlite")
    ap.add_argument("--ai-marked", help="default: commits.sqlite")
    ap.add_argument("--mech", help="default: commits.sqlite")
    ap.add_argument("--out")
    args = ap.parse_args()
    report(args)


if __name__ == "__main__":
    main()
