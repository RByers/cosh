"""Per-person data for the Review Feedback page (web/review-feedback.html,
docs/review-feedback.md).

Offline; reads balance*.sqlite, derived.sqlite, labels.sqlite,
sentiment.sqlite and the sentiment comment files. Writes, under --out
(default web/public/review-feedback/):

  peers.json       percentiles of every peer group, per period and measure
  u/<key>.json     one file per CL owner: their CLs, the reviewer threads on
                   them (with excerpts for the year that has comment text),
                   praise received, and their values per period and measure
  u/<key>.json     for each other address of the same person: {"see": key}

<key> is a hash of the normalised address (`key` below; the page computes the
same), so the folder can't be browsed for names and the page can't offer
completions. Everything comes from public Gerrit and git data. Review tone
appears only as praise (docs/plan.md, ground rule 5): nothing written here
marks a comment, a person or an org as negative, and orgs get no tone figures.

  COSH_DATA_DIR=<main>/data/private nice -n 5 python3 scripts/review_feedback.py \
      --first-commit first_commit.txt --mech mech.jsonl [--out DIR]
"""

import argparse
import bisect
import glob
import re
import hashlib
import json
import math
import os
import shutil
import sqlite3
import statistics as st
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import balance_analysis as A  # noqa: E402
from cosh import balance, classify, sentiment, store  # noqa: E402
from cosh.orgs import OrgResolver  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "web", "public", "review-feedback")
DAY = 86400
YEAR = 365.25 * DAY
START = datetime(2023, 7, 1, tzinfo=timezone.utc).timestamp()     # first whole half-year of Gerrit data
END = datetime(2026, 11, 2, tzinfo=timezone.utc).timestamp()      # end of 2026-W44, the last whole week
TONE_WEEKS = sentiment.weeks_in("2025-W45:2026-W44")             # the year with comment text and tone scores
SALT = "cosh-review-feedback-v1:"
EXCERPT = 200                 # characters of a comment kept for the drill-down
MIN_CLS, MIN_EXP = 6, 3.0     # a person-period counts among peers with this many CLs and expected threads
MIN_RECEIVED = 20             # ... and among tone peers with this many comments received
QS = [i / 20 for i in range(21)]
TENURE = ["<1y", "1-2y", "2-5y", "5-10y", "10y+"]
CHANGES = ["<50", "50-199", "200-499", "500-999", "1000+"]   # the author's earlier commits on main (from 2017)
XP = ["0", "1-4", "5-19", "20-99", "100+"]       # the author's earlier commits in the directory
# Peers are always the same tenure, by one of three measures: years since the
# first commit on main ("time"), earlier commits on main ("changes"), or
# experience in each directory ("dir"). Within that: all authors, Google, or
# everyone outside Google.
ORGS = {"all": lambda o: True, "google": lambda o: o == "google.com", "nongoogle": lambda o: o != "google.com"}
MIN_PEERS = 10                # fewer peers than this get no percentiles
# Measures: what counts (every reviewer thread, or only those the owner
# addressed) over what it is compared with (CLs, or the 2023-24 norm for CLs
# of that size, or of that size and top 2-level directory).
KINDS = ("t", "a")
CORR = ("n", "s", "d")
METRICS = [f"{k}{c}" for k in KINDS for c in CORR]
# The page's opening card: how feedback falls with tenure, per first-commit
# year, and how fast it falls for each person.
STEP = 0.5                    # tenure bins of the cohort curves, in years
MIN_COHORT = 20               # people per point of a cohort curve
MIN_TREND_HALVES = 3          # a person's yearly change needs this many counted half-years ...
MIN_TREND_SPAN = 1.0          # ... spanning this many years of tenure
FLOOR = 0.05                  # values below this count as this on the log scale of the trend
CHANGE_EDGES = list(range(-40, 81, 10))   # histogram bin edges, % less feedback per year


def key(email):
    """The file name for an address: the page normalises and hashes the same way."""
    return hashlib.sha256((SALT + A.person(email.strip())).encode()).hexdigest()[:32]


def tenure_band(years):
    return None if years is None else "<1y" if years < 1 else "1-2y" if years < 2 else "2-5y" if years < 5 \
        else "5-10y" if years < 10 else "10y+"


def changes_band(n):
    return None if n is None else "<50" if n < 50 else "50-199" if n < 200 else "200-499" if n < 500 \
        else "500-999" if n < 1000 else "1000+"


def xp_band(n):
    return 0 if n == 0 else 1 if n < 5 else 2 if n < 20 else 3 if n < 100 else 4


def half(t):
    d = datetime.fromtimestamp(t, timezone.utc)
    return f"{d.year}H{1 + (d.month > 6)}"


def periods_of(t):
    """The periods a CL closed at t belongs to: all, its year, its half-year."""
    h = half(t)
    return ("all", h[:4], h)


def quantiles(xs):
    xs = sorted(xs)
    if not xs:
        return None
    out = []
    for q in QS:
        i = q * (len(xs) - 1)
        lo = int(i)
        hi = min(lo + 1, len(xs) - 1)
        out.append(round(xs[lo] + (xs[hi] - xs[lo]) * (i - lo), 3))
    return out


def annual_change(points):
    """A person's yearly change in feedback: exp of the least-squares slope of
    ln(value) against tenure in years, minus 1 (-0.3 is 30% less feedback a
    year). points are (tenure, value); None without enough of them."""
    pts = [(t, math.log(max(v, FLOOR))) for t, v in points if t is not None and v is not None]
    if len(pts) < MIN_TREND_HALVES:
        return None
    ts = [t for t, _ in pts]
    if max(ts) - min(ts) < MIN_TREND_SPAN:
        return None
    mt = st.mean(ts)
    my = st.mean(y for _, y in pts)
    sxx = sum((t - mt) ** 2 for t in ts)
    return math.exp(sum((t - mt) * (y - my) for t, y in pts) / sxx) - 1


def histogram(xs, edges):
    """Counts per bin [edges[i], edges[i+1]), the first bin taking everything
    below edges[1] and the last everything from edges[-2] on."""
    out = [0] * (len(edges) - 1)
    for x in xs:
        out[min(max(bisect.bisect_right(edges, x) - 1, 0), len(out) - 1)] += 1
    return out


def tenure_trends(points, groups):
    """The opening card's data. points: per person, their counted half-years
    as (first-commit year, tenure, org, {metric: value}, {metric: value
    against directory experience}). groups: name -> test of an org; names
    starting "dir:" use the values against directory experience. Returns
    the cohort curves (median value per first-commit year and STEP-year
    tenure bin, MIN_COHORT people or more) and the histogram of people's
    yearly reduction in feedback, % (-100 * annual_change), per group and
    measure. A half-year counts for a group by its org; a person's change by
    the org of most of their half-years."""
    curves = {g: {m: defaultdict(lambda: defaultdict(list)) for m in METRICS} for g in groups}
    changes = {g: {m: [] for m in METRICS} for g in groups}
    for pts in points:
        org = Counter(p[2] for p in pts).most_common(1)[0][0]
        for g, f in groups.items():
            xk = 4 if g.startswith("dir:") else 3
            for m in METRICS:
                if f(org):
                    c = annual_change([(p[1], p[xk][m]) for p in pts])
                    if c is not None:
                        changes[g][m].append(-100 * c)
                for p in pts:
                    if f(p[2]) and p[1] is not None and p[xk][m] is not None:
                        curves[g][m][p[0]][math.floor(p[1] / STEP) * STEP].append(p[xk][m])
    cohorts = {g: {m: {str(y): [[b, r3(st.median(v)), len(v)] for b, v in sorted(bs.items()) if len(v) >= MIN_COHORT]
                       for y, bs in sorted(per_m.items())} for m, per_m in gm.items()} for g, gm in curves.items()}
    change = {g: {m: dict(n=len(xs), median=round(st.median(xs), 1) if xs else None,
                          counts=histogram(xs, CHANGE_EDGES)) for m, xs in gm.items()} for g, gm in changes.items()}
    return cohorts, change


def r3(x):
    return round(x, 3)


def epoch_day(t):
    """Days since 1970-01-01 (UTC) of a unix time; the page turns them back into dates."""
    return int(t // DAY)


def day_of(s):
    """Days since 1970-01-01 of a 'YYYY-MM-DD...' date."""
    return int(datetime.strptime(s[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() // DAY)


def excerpt(text):
    t = " ".join((text or "").split())
    if len(t) <= EXCERPT:
        return t
    cut = t[:EXCERPT].rsplit(" ", 1)[0]
    return (cut if len(cut) > EXCERPT // 2 else t[:EXCERPT]) + "…"


# ---------------------------------------------------------------- loading

def load(args):
    import balance_growth as G
    cls = A.load_cl()
    commits = A.load_commits()
    ids = G.Ids()
    for a, b in G.alias_pairs(cls, commits):
        ids.union(a, b)
    for c in commits:
        c["pid"] = ids.find(c["email"])
    for c in cls:
        c["pid"] = ids.find(c["owner_email"]) if c["owner_email"] else None
    first = {}
    for e, t in A.load_first(args.first_commit).items():
        k = ids.find(e)
        first[k] = min(t, first.get(k, t))
    print(f"loaded {len(cls):,} CLs, {len(commits):,} commits", file=sys.stderr, flush=True)
    return cls, commits, ids, first


def mech_set(path):
    out = set()
    for line in open(path):
        n, files, threads, rep, lines = json.loads(line)
        if files >= 100 or (rep is not None and rep >= 0.8):
            out.add(n)
    return out


def norms(use):
    """The 2023-24 norms, as in balance_growth.cl_residuals: mean reviewer
    threads (and addressed threads) per merged CL by size bucket and top
    2-level directory (groups of 30 or more), else by size bucket alone."""
    ref = [c for c in use if A.year(c["closed_at"]) in (2023, 2024)]
    out = {}
    for k in ("threads", "addressed"):
        g, b = defaultdict(list), defaultdict(list)
        for c in ref:
            g[(c["sb"], c["d2"])].append(c[k])
            b[c["sb"]].append(c[k])
        gm = {x: st.mean(v) for x, v in g.items() if len(v) >= 30}
        bm = {x: st.mean(v) for x, v in b.items()}
        for c in use:
            s = bm.get(c["sb"], 1.0)
            c[f"exp_{k[0]}s"] = s
            c[f"exp_{k[0]}d"] = gm.get((c["sb"], c["d2"]), s)


# ---------------------------------------------------------------- building

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--first-commit", required=True)
    ap.add_argument("--mech", required=True)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--check", help="also write some people's per-period values here, to compare with the page's")
    args = ap.parse_args()
    import balance_growth as G

    cls, commits, ids, first = load(args)
    mech = mech_set(args.mech)
    dirs3 = A.commit_dirs(3)
    top2 = {}
    for c in commits:
        d = dirs3.get(c["cid"])
        if c["n"] and d:
            top2[c["n"]] = "/".join(d[0].split("/")[:2])
    # Earlier commits per (person, directory), for directory experience, and
    # per person, for tenure by changes (reverts left out of both).
    xp_times = defaultdict(list)
    own_times = defaultdict(list)
    for c in commits:
        if c["is_revert"]:
            continue
        own_times[c["pid"]].append(c["at"])
        d = dirs3.get(c["cid"])
        if d:
            for x in d[1]:
                xp_times[(c["pid"], x)].append(c["at"])
    for v in xp_times.values():
        v.sort()
    for v in own_times.values():
        v.sort()
    landed_at = {c["n"]: c["at"] for c in commits if c["n"]}
    del dirs3
    emails_of = defaultdict(set)         # pid -> normalised addresses
    for c in commits:
        emails_of[c["pid"]].add(c["email"])
    for c in cls:
        if c["pid"]:
            emails_of[c["pid"]].add(c["owner_email"])
    del commits

    # The same CLs as the Balance page's feedback index: merged, human-owned,
    # non-mechanical (balance_report.py's rule).
    for c in cls:
        if c["change_number"] in mech:
            c["status"] = "MECH"
    use = [c for c in cls if c["status"] == "MERGED" and c["closed_at"] and c["pid"]
           and not A.is_bot_email(c["owner_email"])]
    for c in use:
        c["lines"] = (c["ins"] or 0) + (c["dels"] or 0)
        c["sb"] = G.size10(c["lines"])
        c["d2"] = top2.get(c["change_number"])
    norms(use)
    use = [c for c in use if START <= c["closed_at"] < END]
    for c in use:           # the page sums the rounded values, so compute with them here too
        for k in ("exp_ts", "exp_td", "exp_as", "exp_ad"):
            c[k] = r3(c[k])
    by_n = {c["change_number"]: c for c in use}
    print(f"{len(use):,} CLs in range", file=sys.stderr, flush=True)

    db = A.ro(balance.db_path("cl"))
    raw_email = dict(db.execute("SELECT change_number, owner_email FROM cl"))
    cl_dirs = defaultdict(dict)
    for n, d, files, lines in db.execute("SELECT change_number, dir, files, lines FROM cl_dirs"):
        if n in by_n:
            cl_dirs[n][d] = lines + files
    orgs = OrgResolver()
    for c in use:
        n = c["change_number"]
        day = datetime.fromtimestamp(c["closed_at"], timezone.utc).strftime("%Y-%m-%d")
        c["org"] = orgs(raw_email.get(n), day)
        # Tenure in whole days, as the page computes it from the day numbers it has.
        c["ten"] = (epoch_day(c["closed_at"]) - epoch_day(first[c["pid"]])) / 365.25 if c["pid"] in first else None
        w = cl_dirs.get(n) or {"(root)/": 1}
        tot = sum(w.values())
        at = landed_at.get(n, c["closed_at"])
        c["units"] = {d: [r3(v / tot), bisect.bisect_left(xp_times.get((c["pid"], d), ()), at)]
                      for d, v in w.items()}
        c["main"] = max(w, key=w.get)
        c["prior"] = bisect.bisect_left(own_times.get(c["pid"], ()), at)
        c["thr"] = []
    del xp_times, cl_dirs

    # Reviewer threads (as `python3 -m cosh.balance cl` counts them).
    d = A.ro(os.path.join(store.DATA_DIR, store.DERIVED_FILE))
    bots = {a for a, in d.execute("SELECT account_id FROM accounts WHERE is_bot = 1")}
    acct_email = dict(d.execute("SELECT account_id, email FROM accounts WHERE host = "
                                "'chromium-review.googlesource.com'"))
    labels = {}
    ldb = sqlite3.connect(f"file:{classify.labels_path(store.DATA_DIR)}?mode=ro", uri=True)
    act = classify.active_classifier(ldb)
    if act:
        labels = {(n, rt, h): a for n, rt, h, a in ldb.execute(
            "SELECT change_number, root_uuid, input_hash, addressed FROM labels WHERE classifier_id = ?", (act[0],))}
    mism = 0
    for n, root, reply, rx, h, acct, at, path in d.execute(
            "SELECT t.change_number, t.root_uuid, t.last_owner_reply_at, t.regex_addressed, t.input_hash, "
            "t.root_account, c.written_at, c.path FROM threads t LEFT JOIN comments c ON c.host = t.host "
            "AND c.change_number = t.change_number AND c.comment_id = t.root_uuid "
            "WHERE t.host = 'chromium-review.googlesource.com'"):
        c = by_n.get(n)
        if c is None or acct in bots:
            continue
        addressed = 0 if reply is None else 1 if rx else labels.get((n, root, h))
        dr = A.dir_of(path, 3) if path and not path.startswith("/") else None
        c["thr"].append([root, path or "", (at or "")[:10], addressed, dr if dr in c["units"] else c["main"]])
    for c in use:
        if len(c["thr"]) != c["threads"]:
            mism += 1
        c["threads"] = len(c["thr"])
        c["addressed"] = sum(1 for t in c["thr"] if t[3])
    print(f"threads: {sum(c['threads'] for c in use):,} ({mism:,} CLs differ from the cl table)",
          file=sys.stderr, flush=True)

    # Tone: praise received, and comment text for the excerpts.
    scores = {}
    sdb = sentiment.open_scores(store.DATA_DIR)
    pr = sdb.execute("SELECT prompt_id FROM prompts WHERE sha256=? AND model='haiku'",
                     (sentiment.prompt_sha(sentiment.load_prompt()),)).fetchone()
    for i, s in sdb.execute("SELECT id, score FROM scores WHERE prompt_id IN (0, ?)", (pr[0] if pr else -1,)):
        scores[i] = s
    roots = {f"{n}/{t[0]}" for n, c in by_n.items() for t in c["thr"]}
    text = {}
    received = defaultdict(lambda: defaultdict(int))     # pid -> period -> comments to them on their CLs
    praise = defaultdict(list)                           # pid -> [(cl, uuid, day, text)]
    tone_pid = {}

    def pid_of(acct):
        if acct not in tone_pid:
            e = acct_email.get(acct)
            tone_pid[acct] = ids.find(e) if e and not A.is_bot_email(e) else None
        return tone_pid[acct]
    # Excerpts come from every week whose comment text has been collected, so a
    # half-year's file keeps them on later runs; praise only from the scored year.
    tone = set(TONE_WEEKS)
    for path in sorted(glob.glob(os.path.join(sentiment.out_dir(store.DATA_DIR), "comments-*-W*.jsonl"))):
        w = os.path.basename(path)[len("comments-"):-len(".jsonl")]
        with open(path) as f:
            for line in f:
                r = json.loads(line)
                i = r["id"]
                if i in roots:
                    text[i] = excerpt(r.get("text"))
                if w not in tone:
                    continue
                if sentiment.is_self_note(r) or i not in scores or sentiment._target_kind(r) != "person":
                    continue
                if r.get("target") != r.get("owner") or r.get("author") == r.get("owner"):
                    continue          # only comments to the CL owner from someone else
                p = pid_of(r["owner"])
                if not p:
                    continue
                received[p]["tone"] += 1
                if scores[i] >= sentiment.GLOWING:
                    praise[p].append((r["cl"], r["uuid"], r["written_at"][:10], excerpt(r.get("text"))))
                    received[p]["praise"] += 1
    print(f"tone: {len(received):,} people received comments, {sum(len(v) for v in praise.values()):,} praise",
          file=sys.stderr, flush=True)

    # ------------------------------------------------ per person and period
    people = defaultdict(list)
    for c in use:
        people[c["pid"]].append(c)
    zero = lambda: dict(cls=0, t=0, a=0, ts=0.0, td=0.0, as_=0.0, ad=0.0)

    def sums(cs):
        s = zero()
        for c in cs:
            s["cls"] += 1
            s["t"] += c["threads"]
            s["a"] += c["addressed"]
            s["ts"] += c["exp_ts"]
            s["td"] += c["exp_td"]
            s["as_"] += c["exp_as"]
            s["ad"] += c["exp_ad"]
        return s

    def value(s, m):
        num = s[m[0]]
        if m[1] == "n":
            den = s["cls"]
        elif m[0] == "t":
            den = s["ts"] if m[1] == "s" else s["td"]
        else:
            den = s["as_"] if m[1] == "s" else s["ad"]
        return num / den if den else None

    def unit_rows(cs):
        """(threads, addressed, CL share, band, c) per CL and directory."""
        for c in cs:
            per = defaultdict(lambda: [0, 0])
            for t in c["thr"]:
                per[t[4]][0] += 1
                per[t[4]][1] += 1 if t[3] else 0
            for dd, (w, prior) in c["units"].items():
                yield per[dd][0], per[dd][1], w, xp_band(prior), c

    def denom(m, c, w):
        if m[1] == "n":
            return w
        return w * c[f"exp_{m[0]}{m[1]}"]

    # Pooled rate per experience band, per period and measure (everyone).
    pool = defaultdict(lambda: [0.0, 0.0])
    for pid, cs in people.items():
        for o, a_, w, b, c in unit_rows(cs):
            for p in periods_of(c["closed_at"]):
                for m in METRICS:
                    pool[(p, m, b)][0] += o if m[0] == "t" else a_
                    pool[(p, m, b)][1] += denom(m, c, w)
    allp = sorted({p for c in use for p in periods_of(c["closed_at"])}, key=lambda p: (p != "all", p))
    rate = {(p, m, b): (v[0] / v[1] if v[1] else None) for (p, m, b), v in pool.items()}
    # Pooled overall rate, so a band's rate reads relative to everyone (1.0 = typical).
    overall = {}
    for p in allp:
        for m in METRICS:
            o = sum(pool[(p, m, b)][0] for b in range(5))
            e = sum(pool[(p, m, b)][1] for b in range(5))
            overall[(p, m)] = o / e if e else None

    def person_period(pid, cs, p):
        s = sums(cs)
        ten = [c["ten"] for c in cs if c["ten"] is not None]
        orgc = Counter(c["org"] for c in cs)
        out = dict(cls=s["cls"], threads=s["t"], addressed=s["a"],
                   ten=tenure_band(st.median(ten)) if ten else None,
                   chg=changes_band(st.median([c["prior"] for c in cs])), org=orgc.most_common(1)[0][0],
                   ok=s["cls"] >= MIN_CLS and s["td"] >= MIN_EXP, v={}, x={}, bands={})
        bo = defaultdict(lambda: [0.0, 0.0, 0.0])      # (m, band) -> obs, own denominator, CL share
        xe = defaultdict(float)
        for o, a_, w, b, c in unit_rows(cs):
            for m in METRICS:
                ob = o if m[0] == "t" else a_
                dn = denom(m, c, w)
                bo[(m, b)][0] += ob
                bo[(m, b)][1] += dn
                bo[(m, b)][2] += w
                rb, ov = rate.get((p, m, b)), overall.get((p, m))
                xe[m] += dn * (r3(rb / ov) if rb and ov else 1.0)     # peers.json's `rel`
        for m in METRICS:
            v = value(s, m)
            out["v"][m] = None if v is None else r3(v)
            num = s[m[0]]
            out["x"][m] = r3(num / xe[m]) if xe[m] else None
            out["bands"][m] = [[r3(bo[(m, b)][0]), r3(bo[(m, b)][1]), r3(bo[(m, b)][2])] for b in range(5)]
        return out

    per = {}
    for pid, cs in people.items():
        byp = defaultdict(list)
        for c in cs:
            for p in periods_of(c["closed_at"]):
                byp[p].append(c)
        per[pid] = {p: person_period(pid, v, p) for p, v in byp.items()}

    # ------------------------------------------------ the opening card
    trend_pts = []
    for pid, cs in people.items():
        if pid not in first:
            continue
        y0 = datetime.fromtimestamp(first[pid], timezone.utc).year
        byh = defaultdict(list)
        for c in cs:
            byh[half(c["closed_at"])].append(c["ten"])
        pts = [(y0, st.median(byh[h]), pp["org"], pp["v"], pp["x"])
               for h, pp in per[pid].items() if HALF.match(h) and pp["ok"]]
        if pts:
            trend_pts.append(pts)
    # The page's "Peers" choice, and the same against directory experience ("dir:").
    trend_groups = {**ORGS, **{f"dir:{o}": of for o, of in ORGS.items()}}
    cohorts, change = tenure_trends(trend_pts, trend_groups)
    print(f"opening card: {len(trend_pts):,} people, {change['all']['td']['n']:,} with a yearly change "
          f"(median {change['all']['td']['median']}% less a year)", file=sys.stderr, flush=True)

    # ------------------------------------------------ peers
    def tone_bands(pid):
        ten = (TONE_END_T - first[pid]) / YEAR if pid in first else None
        return dict(time=tenure_band(ten),
                    changes=changes_band(bisect.bisect_left(own_times.get(pid, ()), TONE_END_T)))

    def tone_share(pid):
        r = received.get(pid)
        if not r or r["tone"] < MIN_RECEIVED:
            return None
        return r["praise"] / r["tone"]

    # Groups: "<by>:<band>:<org>" for tenure in years ("time") or in earlier
    # commits ("changes"), and "dir:<org>", measured against directory experience.
    groups = {}
    for o, of in ORGS.items():
        for t in TENURE:
            groups[f"time:{t}:{o}"] = (lambda t, of: lambda pp: pp["ten"] == t and of(pp["org"]))(t, of)
        for t in CHANGES:
            groups[f"changes:{t}:{o}"] = (lambda t, of: lambda pp: pp["chg"] == t and of(pp["org"]))(t, of)
        groups[f"dir:{o}"] = (lambda of: lambda pp: of(pp["org"]))(of)
    peers = dict(generated=datetime.now(timezone.utc).strftime("%Y-%m-%d"), periods=allp, metrics=METRICS,
                 tenure=TENURE, changes=CHANGES, xp=XP, min_peers=MIN_PEERS, qs=len(QS), min_cls=MIN_CLS, min_exp=MIN_EXP, min_received=MIN_RECEIVED,
                 tone_weeks=[TONE_WEEKS[0], TONE_WEEKS[-1]], dist={}, bands={}, tone={},
                 cohort_step=STEP, min_cohort=MIN_COHORT, cohorts=cohorts,
                 change_edges=CHANGE_EDGES, change=change)
    for p in allp:
        rows = [(pid, pp[p]) for pid, pp in per.items() if p in pp and pp[p]["ok"]]
        dp = peers["dist"][p] = {}
        for g, f in groups.items():
            sel = [x for _, x in rows if f(x)]
            dp[g] = {}
            for m in METRICS:
                xs = [x["x" if g.startswith("dir:") else "v"][m] for x in sel]
                xs = [v for v in xs if v is not None]
                dp[g][m] = dict(n=len(xs), q=quantiles(xs) if len(xs) >= MIN_PEERS else None)
        # Per experience band: the pooled rate relative to everyone, and the spread of people
        # with enough CL share in the band (1.5 CLs' worth or more).
        bp = peers["bands"][p] = {}
        for m in METRICS:
            ov = overall.get((p, m))
            bp[m] = []
            for b in range(5):
                xs = [x["bands"][m][b][0] / x["bands"][m][b][1] for _, x in rows
                      if x["bands"][m][b][2] >= 1.5 and x["bands"][m][b][1] > 0]
                bp[m].append(dict(pooled=r3(rate[(p, m, b)]) if rate.get((p, m, b)) is not None else None,
                                  rel=r3(rate[(p, m, b)] / ov) if rate.get((p, m, b)) and ov else None,
                                  n=len(xs), q=quantiles(xs)))
    # Tone peers: praise share of comments received in the tone year, by tenure
    # in years or in earlier commits at its end (no orgs).
    tone_rows = []
    for pid in received:
        s = tone_share(pid)
        if s is not None:
            tone_rows.append((tone_bands(pid), s))
    peers["tone"]["all"] = dict(n=len(tone_rows), q=quantiles([s for _, s in tone_rows]))
    for by, names in (("time", TENURE), ("changes", CHANGES)):
        for t in names:
            xs = [s for b, s in tone_rows if b[by] == t]
            peers["tone"][f"{by}:{t}"] = dict(n=len(xs), q=quantiles(xs) if len(xs) >= MIN_PEERS else None)

    # ------------------------------------------------ write
    # u/<key>.json: who the person is, which half-years they have, and praise
    # (it changes on every run). <half>/<key>.json: that half-year's CLs, which
    # later runs leave unchanged once the half-year is over, so git stores them once.
    out = args.out
    for name in os.listdir(out) if os.path.isdir(out) else ():
        if name == "u" or HALF.match(name):
            shutil.rmtree(os.path.join(out, name))
    os.makedirs(os.path.join(out, "u"), exist_ok=True)
    with open(os.path.join(out, "peers.json"), "w") as f:
        json.dump(peers, f, separators=(",", ":"))
    written, stubs, size = 0, 0, 0
    taken = {}
    check = {}
    for pid, cs in people.items():
        k = key(pid)
        if k in taken:
            print("hash collision, skipped one person", file=sys.stderr)
            continue
        taken[k] = pid
        cs.sort(key=lambda c: (c["closed_at"], c["change_number"]))
        by_half = defaultdict(list)
        for c in cs:
            by_half[half(c["closed_at"])].append(c)
        for h, hcs in sorted(by_half.items()):
            data = json.dumps(shard(hcs, text), separators=(",", ":"), ensure_ascii=False)
            os.makedirs(os.path.join(out, h), exist_ok=True)
            with open(os.path.join(out, h, f"{k}.json"), "w") as f:
                f.write(data)
            size += len(data.encode())
        r = received.get(pid, {})
        top = dict(v=3, first=datetime.fromtimestamp(first[pid], timezone.utc).strftime("%Y-%m") if pid in first else None,
                   first_day=epoch_day(first[pid]) if pid in first else None, halves=sorted(by_half),
                   tone=dict(received=r.get("tone", 0), praise=r.get("praise", 0), share=tone_share(pid),
                             ten=tone_bands(pid)["time"], chg=tone_bands(pid)["changes"]),
                   praise=[[n, u, day_of(day), t] for n, u, day, t in sorted(praise.get(pid, []), key=lambda x: x[2],
                                                                            reverse=True)])
        data = json.dumps(top, separators=(",", ":"), ensure_ascii=False)
        with open(os.path.join(out, "u", f"{k}.json"), "w") as f:
            f.write(data)
        size += len(data.encode())
        written += 1
        if args.check and len(check) < 300:
            check[k] = {p: {x: v for x, v in pp.items() if x != "bands"} for p, pp in per[pid].items()}
    for pid in people:
        for e in emails_of.get(pid, ()):
            k = key(e)
            if k in taken:
                continue
            taken[k] = pid
            with open(os.path.join(out, "u", f"{k}.json"), "w") as f:
                f.write(json.dumps(dict(see=key(pid))))
            stubs += 1
    if args.check:
        with open(args.check, "w") as f:
            json.dump(check, f)
    print(f"wrote {written:,} people ({size / 1e6:.1f} MB) and {stubs:,} other addresses to {out}",
          file=sys.stderr)


HALF = re.compile(r"^\d{4}H[12]$")


def shard(cs, text):
    """One person's CLs of one half-year, oldest first: [change number, day
    landed, lines, expected threads by size, by size and directory, expected
    addressed by size, by size and directory, [[directory, line share,
    earlier commits]], [[comment uuid, file, days after landing, addressed,
    directory, excerpt]], org, the owner's earlier commits on main], with
    directory, file and org names listed
    once. A thread without an excerpt has an empty uuid: the page links its
    CL instead."""
    files, dirs, orgs = {}, {}, {}

    def idx(table, x):
        return table.setdefault(x, len(table))
    rows = []
    for c in cs:
        n = c["change_number"]
        d0 = epoch_day(c["closed_at"])
        units = [[idx(dirs, dd), w, prior]
                 for dd, (w, prior) in sorted(c["units"].items(), key=lambda kv: (-kv[1][0], kv[0]))]
        thr = []
        for root, path, at, addr, dd in sorted(c["thr"], key=lambda t: (t[2], t[0])):
            ex = text.get(f"{n}/{root}")
            t = [root if ex is not None else "", idx(files, path), (day_of(at) - d0) if at else None,
                 None if addr is None else int(bool(addr)), idx(dirs, dd)]
            if ex is not None:
                t.append(ex)
            thr.append(t)
        rows.append([n, d0, c["lines"], c["exp_ts"], c["exp_td"], c["exp_as"], c["exp_ad"], units, thr,
                     idx(orgs, c["org"]), c["prior"]])
    return dict(dirs=list(dirs), files=list(files), orgs=list(orgs), cls=rows)


TONE_END_T = END


if __name__ == "__main__":
    main()
