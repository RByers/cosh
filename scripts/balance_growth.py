"""Growth, burden-sharing and AI-era analyses for the balance page
(docs/balance.md). Offline; reads data/private/balance*.sqlite and
derived.sqlite. No comment text. Per-person values are computed only to be
aggregated; nothing here prints anyone's identity.

  COSH_DATA_DIR=<main>/data/private python3 scripts/balance_growth.py \
      --first-commit F --owners-added F --ai-marked F [growth|burden|ai|all]
"""

import argparse
import bisect
import math
import os
import random
import sqlite3
import statistics as st
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import balance_analysis as A  # noqa: E402
from cosh import balance, store  # noqa: E402

DAY = 86400
YEAR = 365.25 * DAY
CENSOR = datetime(2026, 11, 1, tzinfo=timezone.utc).timestamp()   # end of data


def half(t):
    d = datetime.fromtimestamp(t, timezone.utc)
    return d.year * 2 + (d.month > 6)          # e.g. 2025H2 -> 4051


def half_name(h):
    return f"{h // 2}H{h % 2 + 1}"


def size10(lines):
    """Ten log-spaced size buckets: <4, <8, ..., <1024, 1024+ (changed lines)."""
    return min(9, max(0, int(math.log2(max(lines, 1))) - 1))


# --------------------------------------------------------------- identities

class Ids:
    """Union-find over emails: Chromium's two domains and SVN-era emails merge
    by A.person(); Gerrit owner email and landed-commit author email of the
    same CL merge too (people who switched addresses)."""

    def __init__(self):
        self.p = {}

    def find(self, e):
        e = A.person(e)
        self.p.setdefault(e, e)
        while self.p[e] != e:
            self.p[e] = self.p[self.p[e]]
            e = self.p[e]
        return e

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)


def alias_pairs(cls, commits, min_cls=3, min_share=0.5):
    """(owner email, git author email) pairs to treat as one person: the git
    author's CLs are mostly (>= min_share, >= min_cls) owned in Gerrit by
    that address. A single CL whose owner differs from its author (someone
    landing another person's CL, a copybara import) is not evidence: merging
    on those once chained ~400 people into one identity (2026-11-08)."""
    by_n = {c["n"]: c for c in commits if c["n"]}
    own = defaultdict(Counter)
    for c in cls:
        g = by_n.get(c["change_number"])
        if g and c["owner_email"] and not A.is_bot_email(c["owner_email"]):
            own[A.person(g["email"])][A.person(c["owner_email"])] += 1
    out = []
    for b, cnt in own.items():
        tot = sum(cnt.values())
        for a, n in cnt.items():
            if a != b and n >= min_cls and n / tot >= min_share:
                out.append((a, b))
    return out


def load_all(args):
    cls = A.load_cl()
    commits = A.load_commits()
    ids = Ids()
    for a, b in alias_pairs(cls, commits):
        ids.union(a, b)
    for c in commits:
        c["pid"] = ids.find(c["email"])
        c["rbp"] = [ids.find(r) for r in c["rb"]]
    for c in cls:
        c["pid"] = ids.find(c["owner_email"]) if c["owner_email"] else None
    first = {}
    for e, t in A.load_first(args.first_commit).items():
        k = ids.find(e)
        first[k] = min(t, first.get(k, t))
    owner_at = {}
    for line in open(args.owners_added):
        t, e, path = line.rstrip("\n").split(" ", 2)
        if path.count("/") > 3:       # first addition at depth <= 3 (team moves into tiny subdirs aside)
            pass
        k = ids.find(e)
        owner_at[k] = min(int(t), owner_at.get(k, int(t)))
    ai = set(open(args.ai_marked).read().split()) if args.ai_marked else set()
    print(f"loaded {len(cls):,} CLs, {len(commits):,} commits, {len(first):,} people", file=sys.stderr)
    return cls, commits, ids, first, owner_at, ai


# ------------------------------------------------------------- CL residuals

def mechanical_flag(c):
    return (c["files"] or 0) >= A.MECH_FILES and c["threads"] == 0


def cl_residuals(cls, top2):
    """Per merged, non-mechanical CL with a known owner: standardized
    residuals of log1p(threads), interdiff share and rounds against
    (size10, dir2, quarter) means (calendar-adjusted, for growth), and
    the threads residual against a fixed 2023-24 norm (for era comparisons)."""
    use = [c for c in cls if c["status"] == "MERGED" and c["closed_at"] and c["pid"] and not mechanical_flag(c)]
    for c in use:
        c["lines"] = (c["ins"] or 0) + (c["dels"] or 0)
        c["sb"] = size10(c["lines"])
        c["d2"] = top2.get(c["change_number"])
        c["qt"] = A.quarter(c["closed_at"])
        c["lt"] = math.log1p(c["threads"])
        c["ish"] = min(2.0, c["lines_changed"] / c["lines_final"]) \
            if c["lines_changed"] is not None and c["lines_final"] else None

    def fit(key, val, keys):
        g = [defaultdict(list) for _ in keys]
        for c in use:
            v = val(c)
            if v is None:
                continue
            for i, k in enumerate(keys):
                g[i][k(c)].append(v)
        means = [{k: st.mean(v) for k, v in gi.items() if len(v) >= 30} for gi in g]
        sd = defaultdict(list)
        for c in use:
            v = val(c)
            if v is None:
                c[key] = None
                continue
            for i, k in enumerate(keys):
                m = means[i].get(k(c))
                if m is not None:
                    c[key] = v - m
                    sd[c["sb"]].append(v - m)
                    break
            else:
                c[key] = None
        sds = {k: st.pstdev(v) or 1 for k, v in sd.items()}
        for c in use:
            if c[key] is not None:
                c[key] /= sds[c["sb"]]

    cal = [lambda c: (c["sb"], c["d2"], c["qt"]), lambda c: (c["sb"], c["qt"])]
    fit("r_threads", lambda c: c["lt"], cal)
    fit("r_ish", lambda c: c["ish"], cal)
    fit("r_rounds", lambda c: c["rounds"], cal)
    ref = [c for c in use if A.year(c["closed_at"]) in (2023, 2024)]
    g, b = defaultdict(list), defaultdict(list)
    for c in ref:
        g[(c["sb"], c["d2"])].append(c["threads"])
        b[c["sb"]].append(c["threads"])
    gm = {k: st.mean(v) for k, v in g.items() if len(v) >= 30}
    bm = {k: st.mean(v) for k, v in b.items()}
    for c in use:
        c["exp24"] = gm.get((c["sb"], c["d2"]), bm.get(c["sb"], 1.0))
    return use


# ------------------------------------------------------------------- growth

WINDOWS = {"2017-18": (2017, 2018), "2019-20": (2019, 2020), "2021-22": (2021, 2022), "2023-24": (2023, 2024), "2025-26": (2025, 2026)}


def slope(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None, None
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    res = sum((y - my - b * (x - mx)) ** 2 for x, y in zip(xs, ys))
    se2 = res / (n - 2) / sxx if n > 2 else float("inf")
    return b, se2


def growth(cls, commits, ids, first, owner_at, top2, dirs3):
    use = cl_residuals(cls, top2)
    # Person x half-year panels, git 2017+ (velocity, size, breadth, reviewing)
    # and Gerrit 2023+ (independence: minus the residuals).
    rnd = random.Random(7)
    ph = defaultdict(lambda: dict(n=0, months=set(), lines=[], dirsamp=[], reviews=0, rmonths=set()))
    for c in commits:
        if c["is_revert"] or not c["n"]:
            continue
        h = half(c["at"])
        m = datetime.fromtimestamp(c["at"], timezone.utc).month
        r = ph[(c["pid"], h)]
        r["n"] += 1
        r["months"].add(m)
        r["lines"].append(c["lines"])
        d = dirs3.get(c["cid"])
        if d:
            r["dirsamp"].append(d[0])
        for rv in c["rbp"]:
            if rv != c["pid"]:
                x = ph[(rv, h)]
                x["reviews"] += 1
                x["rmonths"].add(m)
    indep = defaultdict(lambda: defaultdict(list))
    for c in use:
        h = half(c["closed_at"])
        for k in ("r_threads", "r_ish", "r_rounds"):
            if c[k] is not None:
                indep[k][(c["pid"], h)].append(-c[k])

    def dims(pid, h):
        r = ph.get((pid, h))
        out = {}
        if r and r["n"] >= 6:
            out["velocity"] = math.log(r["n"] / len(r["months"]))
            out["size"] = math.log1p(st.median(r["lines"]))
            if len(r["dirsamp"]) >= 20:
                out["breadth"] = len(set(rnd.sample(r["dirsamp"], 20)))
        if r and (r["n"] >= 6 or r["reviews"] >= 6):
            active = len(r["months"] | r["rmonths"])
            out["reviewing"] = math.log1p(r["reviews"] / active)
        for k in ("r_threads", "r_ish", "r_rounds"):
            v = indep[k].get((pid, h))
            if v and len(v) >= 5:
                out["indep_" + k[2:]] = st.mean(v)
        return out

    keys = ["velocity", "size", "breadth", "reviewing", "indep_threads", "indep_ish", "indep_rounds"]
    # Calendar effect: the population median of each dimension per half-year,
    # subtracted so a person's slope is growth relative to their peers.
    panel = {}
    people = {p for p, _ in ph} | {p for k in indep for p, _ in indep[k]}
    for pid in people:
        if pid not in first:
            continue
        for h in range(2017 * 2, 2026 * 2 + 2):
            d = dims(pid, h)
            if d:
                panel[(pid, h)] = d
    cal = {}
    for h in range(2017 * 2, 2026 * 2 + 2):
        for k in keys:
            vs = [d[k] for (p, hh), d in panel.items() if hh == h and k in d]
            if len(vs) >= 30:
                cal[(h, k)] = st.median(vs)

    def person_slopes(pid, lo, hi, order=None):
        pts = defaultdict(list)
        for h in range(lo * 2, hi * 2 + 2):
            d = panel.get((pid, h))
            if not d:
                continue
            for k, v in d.items():
                if (h, k) in cal:
                    pts[k].append((h / 2, v - cal[(h, k)]))
        out = {}
        for k, xy in pts.items():
            if len(xy) >= 3:
                xs = [x for x, _ in xy]
                ys = [y for _, y in xy]
                if order is not None:
                    order.shuffle(ys)
                b, se2 = slope(xs, ys)
                if b is not None:
                    out[k] = (b, se2)
        return out

    print("\n== Growth: per-person slopes per half-year, relative to peers, in three equal windows")
    print("Shrunk slope = slope * var_between / (var_between + se^2). 'Improving' on a dimension = shrunk")
    print("slope above the shuffled-order null's 80th percentile for that window and dimension.")
    bands = ["0-2y", "2-5y", "5y+"]

    def band(pid, lo):
        t = (datetime(lo, 1, 1, tzinfo=timezone.utc).timestamp() - first[pid]) / YEAR
        return "new" if t < 0 else bands[0] if t < 2 else bands[1] if t < 5 else bands[2]

    summary = {}
    for wname, (lo, hi) in WINDOWS.items():
        real = {pid: person_slopes(pid, lo, hi) for pid in first}
        real = {p: s for p, s in real.items() if s}
        rng = random.Random(11)
        null = {p: person_slopes(p, lo, hi, order=rng) for p in real}
        shr = {}
        for k in keys:
            bs = [s[k] for s in real.values() if k in s]
            if len(bs) < 50:
                continue
            vb = max(1e-9, st.pvariance([b for b, _ in bs]) - st.mean([se for _, se in bs if se != float("inf")]))
            f = lambda b, se: b * vb / (vb + se)
            rs = {p: f(*s[k]) for p, s in real.items() if k in s}
            ns = sorted(f(*s[k]) for s in null.values() if k in s)
            thr = ns[int(0.8 * len(ns))]
            shr[k] = (rs, thr, vb, len(rs))
        CORE = ("velocity", "size", "breadth", "reviewing")
        rows = defaultdict(lambda: [0, 0, Counter(), Counter(), 0, 0])
        for p, s in real.items():
            b = band(p, lo)
            ks = [k for k in s if k in shr]
            if not ks:
                continue
            imp = [k for k in ks if shr[k][0][p] > shr[k][1]]
            core = [k for k in ks if k in CORE]
            for bb in (b, "all"):
                r = rows[bb]
                r[0] += 1
                r[1] += not imp
                if core:
                    r[4] += 1
                    r[5] += not [k for k in imp if k in CORE]
                for k in ks:
                    r[3][k] += 1
                    r[2][k] += k in imp
        print(f"\n{wname}: people with >= 3 measured half-years on some dimension")
        print(f"{'tenure at start':16} {'people':>7} {'improving on none':>18} {'none of core 4':>15} "
              + "".join(f"{k:>15}" for k in keys))
        for b in bands + ["new", "all"]:
            n, low, imp, den, n4, low4 = rows[b]
            if n:
                print(f"{b:16} {n:>7,} {low / n:>18.0%} {low4 / max(1, n4):>15.0%} " + "".join(
                    f"{imp[k] / den[k]:>9.0%} ({den[k]:>4})" if den[k] else f"{'':>15}" for k in keys))
        summary[wname] = {k: v[3] for k, v in shr.items()}
    print("\n(By construction about 20% of people would 'improve' on each dimension by chance; the excess")
    print(" over 20% is growth. 'Improving on none' under pure chance is ~0.8^d for d dimensions measured.)")

    # Split-half reliability of slopes: even vs odd half-years can't give a
    # slope each, so use two disjoint random halves of each person's CLs for
    # the independence residuals (CL level) instead.
    print("\n== Learning curves (pre-AI vs AI era): threads vs the 2023-24 norm by tenure and familiarity")
    fam = familiarity(commits, dirs3)
    era = lambda t: "2023H2-2024" if A.year(t) <= 2024 else str(A.year(t))
    tab, tabf = defaultdict(lambda: [0.0, 0.0, 0]), defaultdict(lambda: [0.0, 0.0, 0])
    for c in use:
        if c["pid"] not in first:
            continue
        ten = (c["closed_at"] - first[c["pid"]]) / YEAR
        tb = "<0.5y" if ten < .5 else "0.5-1y" if ten < 1 else "1-2y" if ten < 2 else "2-5y" if ten < 5 else "5y+"
        for t, key in ((tab, tb), (tabf, fam.get(c["change_number"]))):
            if key is None:
                continue
            x = t[(era(c["closed_at"]), key)]
            x[0] += c["threads"]
            x[1] += c["exp24"]
            x[2] += 1
    eras = ["2023H2-2024", "2025", "2026"]
    print(f"{'tenure':10}" + "".join(f"{e:>22}" for e in eras))
    for tb in ["<0.5y", "0.5-1y", "1-2y", "2-5y", "5y+"]:
        print(f"{tb:10}" + "".join(f"{tab[(e, tb)][0] / max(1e-9, tab[(e, tb)][1]):>12.2f} ({tab[(e, tb)][2]:>6,})"
                                   for e in eras))
    print("prior commits in the CL's main dir3")
    for fb in ["0", "1-4", "5-19", "20-99", "100+"]:
        print(f"{fb:10}" + "".join(f"{tabf[(e, fb)][0] / max(1e-9, tabf[(e, fb)][1]):>12.2f} "
                                   f"({tabf[(e, fb)][2]:>6,})" for e in eras))
    return summary


def familiarity(commits, dirs3):
    prior = defaultdict(Counter)
    fam = {}
    for c in sorted(commits, key=lambda c: c["at"]):
        d = dirs3.get(c["cid"])
        if not d:
            continue
        if c["n"]:
            f = prior[c["pid"]][d[0]]
            fam[c["n"]] = "0" if f == 0 else "1-4" if f < 5 else "5-19" if f < 20 else "20-99" if f < 100 else "100+"
        for x in d[1]:
            prior[c["pid"]][x] += 1
    return fam


# ------------------------------------------------------------------- burden

def km(times, censored):
    """Kaplan-Meier: share reached by each whole year, from (years, reached)."""
    ev = sorted(zip(times, censored))
    at_risk, surv, out = len(ev), 1.0, {}
    i = 0
    for y in range(1, 10):
        while i < len(ev) and ev[i][0] <= y:
            t, cens = ev[i]
            if not cens:
                surv *= 1 - 1 / at_risk
            at_risk -= 1
            i += 1
        out[y] = 1 - surv
    return out


def burden(cls, commits, ids, first, owner_at):
    org = lambda pid: pid.split("@")[-1]
    authored = defaultdict(Counter)
    given = defaultdict(Counter)
    given_new = defaultdict(Counter)
    cross = defaultdict(lambda: [0, 0])
    for c in commits:
        if not c["n"] or c["is_revert"]:
            continue
        y = A.year(c["at"])
        authored[c["pid"]][y] += 1
        newbie = c["pid"] in first and (c["at"] - first[c["pid"]]) < YEAR
        for r in c["rbp"]:
            if r == c["pid"]:
                continue
            given[r][y] += 1
            given_new[r][y] += newbie
            cross[y][0] += 1
            cross[y][1] += org(r) != org(c["pid"])
    print("\n== Review share by start cohort and tenure year: median of reviews / (reviews + CLs) among")
    print("   people active that year (>= 6 CLs or reviews)")
    print(f"{'cohort':7}" + "".join(f"{'y' + str(k):>8}" for k in range(1, 10)))
    for fy in range(2012, 2026):
        cells = []
        for k in range(1, 10):
            y = fy + k - 1
            if y > 2026:
                cells.append(f"{'':>8}")
                continue
            vs = [given[p][y] / (given[p][y] + authored[p][y]) for p, t in first.items() if A.year(t) == fy
                  and given[p][y] + authored[p][y] >= 6]
            cells.append(f"{med(vs):>8.2f}" if len(vs) >= 20 else f"{'':>8}")
        print(f"{fy:<7}" + "".join(cells))

    print("\n== Who carries newcomer review: reviews (Reviewed-by) of first-year authors' CLs by reviewer tenure")
    print("year | newcomer-CL reviews | by reviewers <2y | 2-5y | 5-10y | 10y+ | distinct reviewers | "
          "reviews per reviewer | share of all reviews | cross-org share of all reviews")
    for y in range(2017, 2027):
        rs = [(r, n) for r, g in given_new.items() for yy, n in g.items() if yy == y and n]
        tot = sum(n for _, n in rs)
        if not tot:
            continue
        b = Counter()
        for r, n in rs:
            t = (datetime(y, 7, 1, tzinfo=timezone.utc).timestamp() - first.get(r, 1e18)) / YEAR
            b["<2" if t < 2 else "2-5" if t < 5 else "5-10" if t < 10 else "10+"] += n
        allrev = sum(g[y] for g in given.values())
        print(f"{y} {tot:>7,} " + " ".join(f"{b[k] / tot:>6.0%}" for k in ["<2", "2-5", "5-10", "10+"]) +
              f" {len(rs):>6,} {tot / len(rs):>6.1f} {tot / allrev:>6.1%} {cross[y][1] / cross[y][0]:>6.1%}")

    print("\n== Kaplan-Meier: share of each start cohort (>= 20 CLs ever) that has become a regular reviewer")
    print("   (>= 60 reviews in a calendar year) / been added to an OWNERS file, by years since first commit")
    regular = {p: min(datetime(y, 12, 31, tzinfo=timezone.utc).timestamp() for y, n in g.items() if n >= 60)
               for p, g in given.items() if any(n >= 60 for n in g.values())}
    print(f"{'cohort':7} {'people':>7}" + "".join(f"{str(k) + 'y':>13}" for k in (1, 2, 3, 5, 8)))
    for fy in range(2012, 2026):
        ppl = [p for p, t in first.items() if A.year(t) == fy and sum(authored[p].values()) >= 20]
        if len(ppl) < 30:
            continue
        cells = []
        res = []
        for ev in ((regular if fy >= 2017 else {}), owner_at):   # Reviewed-by starts mid-2017
            tt, cc = [], []
            for p in ppl:
                if p in ev and ev[p] >= first[p]:
                    tt.append((ev[p] - first[p]) / YEAR)
                    cc.append(False)
                elif p in ev:              # an OWNER before their first main commit: count at 0
                    tt.append(0.0)
                    cc.append(False)
                else:
                    tt.append((CENSOR - first[p]) / YEAR)
                    cc.append(True)
            res.append(km(tt, cc))
        for k in (1, 2, 3, 5, 8):
            horizon = (CENSOR - datetime(fy, 7, 1, tzinfo=timezone.utc).timestamp()) / YEAR
            rv = f"{res[0][k]:>5.0%}" if fy >= 2017 else f"{'-':>5}"
            cells.append(f"{rv} /{res[1][k]:>4.0%} " if k <= horizon else f"{'':>13}")
        print(f"{fy:<7} {len(ppl):>7,}" + "".join(cells))

    print("\n== Mentorship lineage: mentors = top 2 Reviewed-by reviewers of a person's first 10 CLs")
    early = defaultdict(list)
    for c in sorted(commits, key=lambda c: c["at"]):
        if c["n"] and len(early[c["pid"]]) < 10:
            early[c["pid"]].append(c)
    mentors = {}
    for p, cs in early.items():
        if len(cs) < 10 or p not in first or A.year(first[p]) < 2017:
            continue
        cnt = Counter(r for c in cs for r in c["rbp"] if r != p)
        mentors[p] = {r for r, _ in cnt.most_common(2)}
        mentors[p + "#t"] = cs[-1]["at"]
    mentees = defaultdict(list)
    for p, ms in mentors.items():
        if p.endswith("#t"):
            continue
        for m in ms:
            mentees[m].append(p)
    print("cohort | mentees | share who within 4 years mentor >= 2 people of their own | mentors per year: "
          "distinct people mentoring that year's newcomers, median mentees each")
    for fy in range(2017, 2025):
        ps = [p for p in mentors if not p.endswith("#t") and A.year(first[p]) == fy]
        if not ps:
            continue
        horizon = first and (lambda p: first[p] + 4 * YEAR)
        became = sum(1 for p in ps if sum(1 for q in mentees.get(p, []) if first[q] <= horizon(p)) >= 2)
        print(f"{fy} {len(ps):>6,} {became / len(ps):>6.0%}" + (" (window open)" if fy + 4 > 2026 else ""))
    for y in range(2017, 2027):
        ms = Counter(m for p, s in mentors.items() if not p.endswith("#t") and A.year(first[p]) == y for m in s)
        if ms:
            print(f"  {y}: {len(ms):>5,} mentors, median {med(list(ms.values())):.0f} mentees, "
                  f"top 10% of mentors take {sum(sorted(ms.values())[-max(1, len(ms) // 10):]) / sum(ms.values()):.0%}")


def med(xs):
    return st.median(xs) if xs else float("nan")


def timeliness(cls, ids, first):
    """Weekday attention hours per reviewer per CL, by reviewer tenure band and half-year."""
    db = A.ro(os.environ.get("BALANCE_CL") or balance.db_path("cl"))
    emails = dict(A.ro(os.path.join(store.DATA_DIR, store.DERIVED_FILE)).execute(
        "SELECT account_id, email FROM accounts"))
    closed = {c["change_number"]: c["closed_at"] for c in cls if c["status"] == "MERGED" and c["closed_at"]}
    g = defaultdict(list)
    for n, acct, hrs, wd in db.execute("SELECT change_number, account_id, hours, weekday_hours FROM cl_attention"):
        t = closed.get(n)
        e = emails.get(acct)
        if not t or not e or A.is_bot_email(e):
            continue
        p = ids.find(e)
        ten = (t - first[p]) / YEAR if p in first else None
        tb = "unknown" if ten is None else "<2y" if ten < 2 else "2-5y" if ten < 5 else "5-10y" if ten < 10 else "10y+"
        g[(half(t), tb)].append(wd)
    print("\n== Timeliness given: weekday hours a reviewer spends in the attention set per CL (p50 / p75)")
    bands = ["<2y", "2-5y", "5-10y", "10y+"]
    print(f"{'half':8}" + "".join(f"{b:>16}" for b in bands))
    for h in sorted({h for h, _ in g}):
        print(f"{half_name(h):8}" + "".join(
            f"{A.q(g[(h, b)], .5):>7.1f} /{A.q(g[(h, b)], .75):>6.1f}" if len(g[(h, b)]) >= 50 else f"{'':>16}"
            for b in bands))


# ----------------------------------------------------------------------- AI

def ai_effects(cls, commits, first, top2, ai):
    use = cl_residuals(cls, top2)
    by_n = {c["n"]: c for c in commits if c["n"]}
    for c in use:
        g = by_n.get(c["change_number"])
        c["ai"] = bool(g and g["sha"] in ai)
        ten = (c["closed_at"] - first[c["pid"]]) / YEAR if c["pid"] in first else 99
        c["tb"] = "<1y" if ten < 1 else "1-3y" if ten < 3 else "3-8y" if ten < 8 else "8y+"
        c["ftr"] = (c["first_review_at"] - c["sent_at"]) / 3600 \
            if c["first_review_at"] and c["sent_at"] and c["first_review_at"] >= c["sent_at"] else None
    print("\n== Direct standardization: each half-year re-weighted to the 2024 mix of tenure band x size bucket x dir2")
    cell = lambda c: (c["tb"], c["sb"], c["d2"])
    w24 = Counter(cell(c) for c in use if A.year(c["closed_at"]) == 2024)
    tot = sum(w24.values())
    byh = defaultdict(lambda: defaultdict(list))
    for c in use:
        byh[half(c["closed_at"])][cell(c)].append(c)
    print("half | raw threads/CL | standardized | raw lines/CL (median) | raw p50 h to first review | standardized mean of "
          "log h to first review")
    for h in sorted(byh):
        cells = byh[h]
        flat = [c for v in cells.values() for c in v]
        num = den = num2 = den2 = 0
        for k, wt in w24.items():
            v = cells.get(k)
            if not v:
                continue
            num += wt * st.mean(c["threads"] for c in v)
            den += wt
            f = [math.log1p(c["ftr"]) for c in v if c["ftr"] is not None]
            if f:
                num2 += wt * st.mean(f)
                den2 += wt
        ft = [c["ftr"] for c in flat if c["ftr"] is not None]
        print(f"{half_name(h)} {st.mean(c['threads'] for c in flat):>6.2f} {num / max(1, den):>6.2f} "
              f"{st.median(c['lines'] for c in flat):>6.0f} {A.q(ft, .5):>6.1f} {math.expm1(num2 / max(1, den2)):>6.1f}"
              f"  (cover {den / tot:.0%})")
    print("\n== Same author, same quarter: AI-marked vs unmarked CLs (paired means of the differences)")
    grp = defaultdict(lambda: ([], []))
    for c in use:
        grp[(c["pid"], c["qt"])][0 if c["ai"] else 1].append(c)
    pairs = [(a, b) for a, b in grp.values() if a and b]
    print(f"{len(pairs)} author-quarters with both; {sum(len(a) for a, _ in pairs)} marked CLs")
    mets = {"lines": lambda c: math.log1p(c["lines"]), "threads": lambda c: c["threads"],
            "threads/100 lines": lambda c: 100 * c["threads"] / max(10, c["lines"]),
            "interdiff share": lambda c: c["ish"], "rounds": lambda c: c["rounds"],
            "h to first review": lambda c: c["ftr"],
            "reverted<30d": lambda c: float(bool(c["reverted_at"] and c["reverted_at"] - c["closed_at"] < 30 * DAY))}
    for name, f in mets.items():
        ds = []
        for a, b in pairs:
            va = [f(c) for c in a if f(c) is not None]
            vb = [f(c) for c in b if f(c) is not None]
            if va and vb:
                ds.append(st.mean(va) - st.mean(vb))
        if len(ds) >= 10:
            m = st.mean(ds)
            se = st.stdev(ds) / math.sqrt(len(ds))
            print(f"  {name:20} marked - unmarked = {m:+.3f} (95% CI {m - 1.96 * se:+.3f} .. {m + 1.96 * se:+.3f}, "
                  f"n={len(ds)})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("what", nargs="?", default="all", choices=["growth", "burden", "ai", "all"])
    ap.add_argument("--first-commit", required=True)
    ap.add_argument("--owners-added", required=True)
    ap.add_argument("--ai-marked")
    args = ap.parse_args()
    cls, commits, ids, first, owner_at, ai = load_all(args)
    dirs3 = A.commit_dirs(3)
    top2 = {}
    for c in commits:
        d = dirs3.get(c["cid"])
        if c["n"] and d:
            top2[c["n"]] = "/".join(d[0].split("/")[:2])
    if args.what in ("burden", "all"):
        burden(cls, commits, ids, first, owner_at)
        timeliness(cls, ids, first)
    if args.what in ("ai", "all"):
        ai_effects(cls, commits, first, top2, ai)
    if args.what in ("growth", "all"):
        growth(cls, commits, ids, first, owner_at, top2, dirs3)


if __name__ == "__main__":
    main()
