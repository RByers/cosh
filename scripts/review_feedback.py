"""Per-person data for the Review Feedback page (web/feedback-index.html,
docs/review-feedback.md).

Offline; reads balance*.sqlite, derived.sqlite, labels.sqlite,
sentiment.sqlite and the sentiment comment files. Writes, under --out
(default web/public/review-feedback/):

  peers.json       percentiles of every peer group, per period and measure,
                   and of its CLs landed and reviewer threads
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
WEEK = 7 * DAY
ADDR_COVER = 0.95             # the addressed measure starts where every later week has labels for this share
# The opening card's cohort curves reach back to 2018 (the first whole year of
# Gerrit data; reviews before mid-2017 were on Rietveld), all threads only.
HISTORY_ISO = "2018-01-01"
TONE_WEEKS = sentiment.weeks_in("2025-W45:2026-W44")             # the year with comment text and tone scores
SALT = "cosh-review-feedback-v1:"
EXCERPT = 200                 # characters of a comment kept for the drill-down
# Any one person's figure that is ranked among peers or goes into the
# histogram rests on at least this many CLs and expected threads, whatever its
# period (half-year, year or all the data): a figure's noise depends on how
# many CLs it has, not how long the period is. At 25 CLs it is about ±38%
# (docs/review-feedback.md).
MIN_CLS, MIN_EXP = 25, 12.0
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
# A person's half-year counts towards a cohort curve with fewer CLs: noise
# barely moves a median, and a higher bar would keep only the most prolific
# newcomers in the early points.
MIN_COHORT_CLS, MIN_COHORT_EXP = 6, 3.0
# The histogram: one value per contributor and pair of consecutive calendar
# years both counted (MIN_CLS), the ratio of the later year's value to the
# earlier's, in bins of equal width on a ratio scale (steps of ×2^(1/3), so
# halved and doubled are edges): noise spreads evenly both ways and bar
# heights compare.
CHANGE_RATIOS = [2 ** (k / 3) for k in range(-4, 5)]
PATCHSET_LEVEL = "/PATCHSET_LEVEL"   # the path of a general comment's thread: not counted
FLOOR = 0.05                  # values below this count as this in a ratio


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


def week_start(w):
    """Unix time of the Monday (UTC) that starts ISO week 'YYYY-Www'."""
    y, n = w.split("-W")
    return datetime.fromisocalendar(int(y), int(n), 1).replace(tzinfo=timezone.utc).timestamp()


def monday(t):
    """Unix time of the Monday (UTC) of the week containing t."""
    d = epoch_day(t)
    return (d - (d + 3) % 7) * DAY       # 1970-01-01 was a Thursday


def month_start(t):
    d = datetime.fromtimestamp(t, timezone.utc)
    return datetime(d.year, d.month, 1, tzinfo=timezone.utc).timestamp()


def trim_start(t):
    """A start that spills a few days into the month before moves to the next
    month's 1st (Monday 2023-06-26 becomes 2023-07-01), so the page names the
    dates by month without a sliver of a half-year; one in a month's first
    week stays (2017-07-03)."""
    return max(t, month_start(t + 6 * DAY))


def trim_end(t):
    """An end (exclusive) a week or less into a month moves back to its 1st
    (Monday 2026-11-02 becomes 2026-11-01)."""
    m = month_start(t - DAY)
    return m if t - m <= WEEK else t


def data_range(use):
    """The dates the page covers, from the data: the weeks `derive` recorded as
    fetched, no earlier than the oldest usable CL's week (balance.sqlite may
    not have caught up with an older backfill yet), trimmed to months."""
    d = A.ro(os.path.join(store.DATA_DIR, store.DERIVED_FILE))
    row = d.execute("SELECT v FROM meta WHERE k = 'fetched_weeks'").fetchone()
    weeks = sorted(json.loads(row[0])) if row else []
    if not weeks:
        raise SystemExit("derived.sqlite records no fetched weeks")
    first_cl = min(c["closed_at"] for c in use)
    return trim_start(max(week_start(weeks[0]), monday(first_cl))), trim_end(week_start(weeks[-1]) + WEEK)


def addressed_start(need, have, start, end):
    """The first week from which every week up to `end` has an addressed label
    for at least ADDR_COVER of the threads that need one (the owner replied,
    and no "Done"-style regex match); `end` if even the last week hasn't.
    Weeks are the ones the CLs closed in."""
    t = monday(end - DAY) + WEEK
    while t - WEEK >= monday(start):
        w = t - WEEK
        if need.get(w, 0) and have.get(w, 0) < ADDR_COVER * need[w]:
            break
        t = w
    return min(max(t, start), end)


def half(t):
    d = datetime.fromtimestamp(t, timezone.utc)
    return f"{d.year}H{1 + (d.month > 6)}"


def periods_of(t):
    """The periods a CL closed at t belongs to: all (the page's figures) and
    its half-year (the over-time chart)."""
    return ("all", half(t))


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


def yearly_changes(years, groups):
    """The histogram of year-over-year change. years: per person, {calendar
    year: (org, {metric: value or None}, {metric: value against directory
    experience or None})}, None where the year doesn't count for that
    measure. groups: name -> test of an org ("dir:" names use the second
    dict). Each pair of consecutive counted years gives one ratio, later /
    earlier (values under FLOOR counted as FLOOR), in the group of the later
    year's org. Returns {group: {metric: {n, people, median (% less feedback
    than the year before, from the median ratio), counts (per CHANGE_RATIOS
    bin, smallest ratio first)}}}."""
    xs = {g: {m: [] for m in METRICS} for g in groups}
    who = {g: {m: set() for m in METRICS} for g in groups}
    for pid, ys in years.items():
        for y in sorted(ys):
            if y + 1 not in ys:
                continue
            (_, v0, x0), (org, v1, x1) = ys[y], ys[y + 1]
            for g, f in groups.items():
                if not f(org):
                    continue
                a, b = (x0, x1) if g.startswith("dir:") else (v0, v1)
                for m in METRICS:
                    if a[m] is None or b[m] is None:
                        continue
                    xs[g][m].append(max(b[m], FLOOR) / max(a[m], FLOOR))
                    who[g][m].add(pid)
    return {g: {m: dict(n=len(v), people=len(who[g][m]),
                        median=round(-100 * (st.median(v) - 1), 1) if v else None,
                        counts=histogram(v, CHANGE_RATIOS)) for m, v in gm.items()} for g, gm in xs.items()}


def histogram(xs, edges):
    """Counts per bin between sorted edges: below edges[0], [edges[i],
    edges[i+1]), and from edges[-1] on (len(edges) + 1 bins)."""
    out = [0] * (len(edges) + 1)
    for x in xs:
        out[bisect.bisect_right(edges, x)] += 1
    return out


def tenure_trends(points, groups):
    """The opening card's data. points: per person, their counted half-years
    as (first-commit year, tenure, org, {metric: value}, {metric: value
    against directory experience}). groups: name -> test of an org; names
    starting "dir:" use the values against directory experience. Returns
    the cohort curves (median value per first-commit year and STEP-year
    tenure bin, MIN_COHORT people or more), per group and measure. A
    half-year counts for a group by its org."""
    curves = {g: {m: defaultdict(lambda: defaultdict(list)) for m in METRICS} for g in groups}
    for pts in points:
        for g, f in groups.items():
            xk = 4 if g.startswith("dir:") else 3
            for m in METRICS:
                for p in pts:
                    if f(p[2]) and p[1] is not None and p[xk][m] is not None:
                        curves[g][m][p[0]][math.floor(p[1] / STEP) * STEP].append(p[xk][m])
    return {g: {m: {str(y): [[b, r3(st.median(v)), len(v)] for b, v in sorted(bs.items()) if len(v) >= MIN_COHORT]
                    for y, bs in sorted(per_m.items())} for m, per_m in gm.items()} for g, gm in curves.items()}


def r3(x):
    return round(x, 3)


def epoch_day(t):
    """Days since 1970-01-01 (UTC) of a unix time; the page turns them back into dates."""
    return int(t // DAY)


def day_str(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")


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


def norms(use, also=()):
    """The 2023-24 norms, as in balance_growth.cl_residuals: mean reviewer
    threads (and addressed threads) per merged CL by size bucket and top
    2-level directory (groups of 30 or more), else by size bucket alone.
    Computed from `use`, and set on `use` and `also` (older CLs)."""
    ref = [c for c in use if A.year(c["closed_at"]) in (2023, 2024)]
    for k in ("threads", "addressed"):
        g, b = defaultdict(list), defaultdict(list)
        for c in ref:
            g[(c["sb"], c["d2"])].append(c[k])
            b[c["sb"]].append(c[k])
        gm = {x: st.mean(v) for x, v in g.items() if len(v) >= 30}
        bm = {x: st.mean(v) for x, v in b.items()}
        for c in list(use) + list(also):
            s = bm.get(c["sb"], 1.0)
            c[f"exp_{k[0]}s"] = s
            c[f"exp_{k[0]}d"] = gm.get((c["sb"], c["d2"]), s)
        # How much of the CL-to-CL spread each norm accounts for (R², 2023-24),
        # against a directory-only norm (top 2-level directory, groups of 30+).
        dg = defaultdict(list)
        for c in ref:
            dg[c["d2"]].append(c[k])
        dm = {x: st.mean(v) for x, v in dg.items() if len(v) >= 30}
        mean = st.mean(c[k] for c in ref)
        tss = sum((c[k] - mean) ** 2 for c in ref) or 1
        r2 = lambda f: 1 - sum((c[k] - f(c)) ** 2 for c in ref) / tss
        print(f"norm fit ({k}, {len(ref):,} CLs of 2023-24, R²): size {r2(lambda c: bm[c['sb']]):.3f}, "
              f"directory {r2(lambda c: dm.get(c['d2'], mean)):.3f}, "
              f"size and directory {r2(lambda c: gm.get((c['sb'], c['d2']), bm[c['sb']])):.3f}",
              file=sys.stderr, flush=True)


# The opening card's size chart: the buckets of balance_growth.size10 (changed lines).
SIZE_LABELS = ["<4", "4–7", "8–15", "16–31", "32–63", "64–127", "128–255", "256–511", "512–1,023", "1,024+"]


# A cell (an author's CLs of one size, or their share of one directory) counts
# toward a bar's median with this many CLs and expected threads.
MIN_CELL_CLS, MIN_CELL_EXP = 10, 3.0
# A top-level directory with more than this share of all reviewer threads is
# split into its second-level directories for the directory chart.
SPLIT_SHARE = 0.10
TOP_DIRS = 10


def chart_dirs(cs):
    """The directory chart's directories: first-level ones, those holding more
    than SPLIT_SHARE of all reviewer threads split into their second level,
    the TOP_DIRS with the most threads. Returns (names, key of a 3-level path)."""
    def parts(path):
        p = [x for x in path.split("/") if x]
        return p[0] + "/", (p[0] + "/" + p[1] + "/") if len(p) > 1 else None
    l1, l2 = Counter(), Counter()
    for c in cs:
        for t in c["thr"]:
            a, b = parts(t[4])
            l1[a] += 1
            if b:
                l2[b] += 1
    total = sum(l1.values()) or 1
    split = {d for d, n in l1.items() if n / total > SPLIT_SHARE}
    vol = Counter({d: n for d, n in l1.items() if d not in split})
    vol.update({d: n for d, n in l2.items() if parts(d)[0] in split})
    names = [d for d, _ in vol.most_common(TOP_DIRS)]
    chosen = set(names)

    def key(path):
        a, b = parts(path)
        k = b if a in split else a
        return k if k in chosen else None
    return names, key


def median_breakdowns(cs, size10):
    """The opening card's bar charts: the median author's feedback index by CL
    size bucket (whole CLs) and by directory (each CL's share in it, and the
    threads on its files), per "Peers" org group and measure. An author counts
    in a bar with MIN_CELL_CLS CLs there and MIN_CELL_EXP expected threads
    (size and directory norm); a bar needs MIN_PEERS authors. Addressed
    measures count only CLs with labels. Returns (by_size, dir names, by_dir),
    each bar as [median or None, authors]."""
    names, dkey = chart_dirs(cs)
    # (org, chart, bar, pid, kind) -> [CLs, threads, den n, den s, den d]
    cell = defaultdict(lambda: [0, 0.0, 0.0, 0.0, 0.0])

    def add(c, chart, bar, w, t, a):
        for o, of in ORGS.items():
            if not of(c["org"]):
                continue
            for k, x in (("t", t), ("a", a)):
                if k == "a" and not c["acov"]:
                    continue
                v = cell[(o, chart, bar, c["pid"], k)]
                v[0] += 1
                v[1] += x
                v[2] += w
                v[3] += w * c[f"exp_{k}s"]
                v[4] += w * c[f"exp_{k}d"]

    for c in cs:
        add(c, "size", size10(c["lines"]), 1, c["threads"], c["addressed"])
        per = defaultdict(lambda: [0, 0])
        for t in c["thr"]:
            per[t[4]][0] += 1
            per[t[4]][1] += 1 if t[3] else 0
        by = defaultdict(lambda: [0.0, 0, 0])
        for d, (w, _) in c["units"].items():
            k = dkey(d)
            if k is not None:
                by[k][0] += w
                by[k][1] += per[d][0]
                by[k][2] += per[d][1]
        for k, (w, t, a) in by.items():
            add(c, "dir", k, w, t, a)
    vals = defaultdict(list)       # (org, chart, bar, metric) -> authors' values
    for (o, chart, bar, pid, k), (n, x, dn, ds, dd) in cell.items():
        if n < MIN_CELL_CLS or dd < MIN_CELL_EXP:
            continue
        for corr, den in (("n", dn), ("s", ds), ("d", dd)):
            if den:
                vals[(o, chart, bar, k + corr)].append(x / den)

    def bar(o, chart, b, m):
        xs = vals.get((o, chart, b, m), [])
        return [r3(st.median(xs)) if len(xs) >= MIN_PEERS else None, len(xs)]
    by_size = {o: {m: [bar(o, "size", b, m) for b in range(len(SIZE_LABELS))] for m in METRICS} for o in ORGS}
    by_dir = {o: {m: [bar(o, "dir", d, m) for d in names] for m in METRICS} for o in ORGS}
    return by_size, names, by_dir


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
    big = {c["n"] for c in commits if c["n"] and (c["files"] or 0) >= 100}
    del commits

    # Older merged CLs (HISTORY_ISO up to the CLs balance.sqlite has), for the
    # opening card's cohort curves only: all reviewer threads against the same
    # 2023-24 norms. Addressed labels and directory experience exist only from
    # START on.
    ddb = A.ro(os.path.join(store.DATA_DIR, store.DERIVED_FILE))
    bots = {a for a, in ddb.execute("SELECT account_id FROM accounts WHERE is_bot = 1")}
    acct_email = dict(ddb.execute("SELECT account_id, email FROM accounts WHERE host = "
                                "'chromium-review.googlesource.com'"))
    balance_from = datetime.fromtimestamp(min(c["closed_at"] for c in cls if c["closed_at"]), timezone.utc)
    old = []
    for n, acct, closed, ins, dels in ddb.execute(
            "SELECT change_number, owner_account, closed_at, insertions, deletions FROM changes "
            "WHERE host = 'chromium-review.googlesource.com' AND project = 'chromium/src' "
            "AND branch IN ('main', 'master') AND status = 'MERGED' AND NOT is_bot_owned "
            "AND closed_at >= ? AND closed_at < ?", (HISTORY_ISO, balance_from.strftime("%Y-%m-%d %H:%M:%S"))):
        e = acct_email.get(acct)
        if not e or acct in bots or A.is_bot_email(A.person(e)) or n in big or n in mech:
            continue
        t = datetime.strptime(closed[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
        lines = (ins or 0) + (dels or 0)
        old.append(dict(change_number=n, pid=ids.find(A.person(e)), email=e, closed_at=t, lines=lines,
                        sb=G.size10(lines), d2=top2.get(n), threads=0, addressed=0))

    # Merged, human-owned, non-mechanical CLs (balance_report.py's rule).
    for c in cls:
        if c["change_number"] in mech:
            c["status"] = "MECH"
    use = [c for c in cls if c["status"] == "MERGED" and c["closed_at"] and c["pid"]
           and not A.is_bot_email(c["owner_email"])]
    for c in use:
        c["lines"] = (c["ins"] or 0) + (c["dels"] or 0)
        c["sb"] = G.size10(c["lines"])
        c["d2"] = top2.get(c["change_number"])

    # Reviewer threads: threads not started by a bot, on a file or the commit
    # message. Patch-set-level threads are left out: Gerrit has recorded
    # general comments as threads only since July 2020, they can't be tied to
    # a directory, and few lead to a change in the code.
    labels = {}
    ldb = sqlite3.connect(f"file:{classify.labels_path(store.DATA_DIR)}?mode=ro", uri=True)
    act = classify.active_classifier(ldb)
    if act:
        labels = {(n, rt, h): a for n, rt, h, a in ldb.execute(
            "SELECT change_number, root_uuid, input_hash, addressed FROM labels WHERE classifier_id = ?", (act[0],))}
    use_n = {c["change_number"]: c for c in use}
    old_n = {c["change_number"]: c for c in old}
    thr = defaultdict(list)          # change number -> [root, path, day, addressed]
    for c in use:
        c["threads"] = c["addressed"] = 0
    for n, root, reply, rx, h, acct, at, path in ddb.execute(
            "SELECT t.change_number, t.root_uuid, t.last_owner_reply_at, t.regex_addressed, t.input_hash, "
            "t.root_account, c.written_at, c.path FROM threads t LEFT JOIN comments c ON c.host = t.host "
            "AND c.change_number = t.change_number AND c.comment_id = t.root_uuid "
            "WHERE t.host = 'chromium-review.googlesource.com'"):
        if acct in bots or path == PATCHSET_LEVEL:
            continue
        if n in old_n:
            old_n[n]["threads"] += 1
        elif n in use_n:
            addressed = 0 if reply is None else 1 if rx else labels.get((n, root, h))
            thr[n].append([root, path or "", (at or "")[:10], addressed, reply is not None and not rx])
            use_n[n]["threads"] += 1
            use_n[n]["addressed"] += 1 if addressed else 0
    del use_n, old_n
    norms(use, old)
    START, END = data_range(use)
    old = [c for c in old if c["closed_at"] < START]
    print(f"{len(old):,} older CLs for the cohort curves", file=sys.stderr, flush=True)
    use = [c for c in use if START <= c["closed_at"] < END]
    for c in use:           # the page sums the rounded values, so compute with them here too
        for k in ("exp_ts", "exp_td", "exp_as", "exp_ad"):
            c[k] = r3(c[k])
    by_n = {c["change_number"]: c for c in use}
    print(f"{len(use):,} CLs in range {day_str(START)} .. {day_str(END - DAY)}", file=sys.stderr, flush=True)

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
    del xp_times, cl_dirs

    # Each thread goes to the directory of its file; commit-message threads to
    # the CL's main directory.
    need, have = defaultdict(int), defaultdict(int)      # week start -> threads needing a label, labelled
    for c in use:
        c["thr"] = []
        for root, path, at, addressed, needs_label in thr.get(c["change_number"], ()):
            if needs_label:
                w = monday(c["closed_at"])
                need[w] += 1
                have[w] += addressed is not None
            dr = A.dir_of(path, 3) if path and not path.startswith("/") else None
            c["thr"].append([root, path, at, addressed, dr if dr in c["units"] else c["main"]])
    del thr
    print(f"threads: {sum(c['threads'] for c in use):,}", file=sys.stderr, flush=True)
    # The addressed measure covers only the CLs with labels.
    ADDR_START = trim_start(addressed_start(need, have, START, END))
    for c in use:
        c["acov"] = c["closed_at"] >= ADDR_START
    print(f"addressed from {day_str(ADDR_START)}", file=sys.stderr, flush=True)
    if ADDR_START > max(START, datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp()):
        print("warning: 2023-24 isn't all labelled, so the addressed norms are too low", file=sys.stderr)

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
                    if m[0] == "a" and not c["acov"]:
                        continue
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
        sa = sums([c for c in cs if c["acov"]])          # the addressed measures' CLs
        ten = [c["ten"] for c in cs if c["ten"] is not None]
        orgc = Counter(c["org"] for c in cs)
        out = dict(cls=s["cls"], threads=s["t"], acls=sa["cls"], addressed=sa["a"],
                   ten=tenure_band(st.median(ten)) if ten else None,
                   chg=changes_band(st.median([c["prior"] for c in cs])), org=orgc.most_common(1)[0][0],
                   ok=s["cls"] >= MIN_CLS and s["td"] >= MIN_EXP,
                   ok_a=sa["cls"] >= MIN_CLS and sa["td"] >= MIN_EXP, v={}, x={}, bands={},
                   # The lower bar for a cohort curve's medians (not on the page).
                   curve=s["cls"] >= MIN_COHORT_CLS and s["td"] >= MIN_COHORT_EXP,
                   curve_a=sa["cls"] >= MIN_COHORT_CLS and sa["td"] >= MIN_COHORT_EXP)
        bo = defaultdict(lambda: [0.0, 0.0, 0.0])      # (m, band) -> obs, own denominator, CL share
        xe = defaultdict(float)
        for o, a_, w, b, c in unit_rows(cs):
            for m in METRICS:
                if m[0] == "a" and not c["acov"]:
                    continue
                ob = o if m[0] == "t" else a_
                dn = denom(m, c, w)
                bo[(m, b)][0] += ob
                bo[(m, b)][1] += dn
                bo[(m, b)][2] += w
                rb, ov = rate.get((p, m, b)), overall.get((p, m))
                xe[m] += dn * (r3(rb / ov) if rb and ov else 1.0)     # peers.json's `rel`
        for m in METRICS:
            sm = s if m[0] == "t" else sa
            v = value(sm, m)
            out["v"][m] = None if v is None else r3(v)
            num = sm[m[0]]
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
    # Older half-years: all reviewer threads only, counted like the recent ones.
    old_pts = defaultdict(list)
    old_by = defaultdict(lambda: defaultdict(list))
    for c in old:
        c["org"] = orgs(c["email"], day_str(c["closed_at"]))
        if c["pid"] in first:
            old_by[c["pid"]][half(c["closed_at"])].append(c)
    for pid, byh in old_by.items():
        for h, cs in byh.items():
            ts, td = sum(r3(c["exp_ts"]) for c in cs), sum(r3(c["exp_td"]) for c in cs)
            if len(cs) < MIN_COHORT_CLS or td < MIN_COHORT_EXP:
                continue
            t = sum(c["threads"] for c in cs)
            v = {m: None for m in METRICS}
            v.update(tn=r3(t / len(cs)), ts=r3(t / ts) if ts else None, td=r3(t / td) if td else None)
            ten = st.median((epoch_day(c["closed_at"]) - epoch_day(first[pid])) / 365.25 for c in cs)
            orgc = Counter(c["org"] for c in cs)
            old_pts[pid].append((datetime.fromtimestamp(first[pid], timezone.utc).year, ten,
                                 orgc.most_common(1)[0][0], v, {m: None for m in METRICS}, True))
    trend_pts = []
    for pid in set(people) | set(old_pts):
        if pid not in first:
            continue
        y0 = datetime.fromtimestamp(first[pid], timezone.utc).year
        byh = defaultdict(list)
        for c in people.get(pid, ()):
            byh[half(c["closed_at"])].append(c["ten"])
        # A half-year counts for the addressed measures only with enough labelled CLs.
        def counted(vals, pp):
            return {m: v if m[0] == "t" or pp["curve_a"] else None for m, v in vals.items()}
        pts = old_pts.get(pid, []) + [(y0, st.median(byh[h]), pp["org"], counted(pp["v"], pp), counted(pp["x"], pp))
                                      for h, pp in per.get(pid, {}).items() if HALF.match(h) and pp["curve"]]
        if pts:
            trend_pts.append(pts)
    # The page's "Peers" choice, and the same against directory experience ("dir:").
    trend_groups = {**ORGS, **{f"dir:{o}": of for o, of in ORGS.items()}}
    cohorts = tenure_trends(trend_pts, trend_groups)

    # Person-years for the histogram. All reviewer threads: every CL of the
    # calendar year, older and recent. Addressed and directory experience:
    # whole years from their start (ADDR_START, START) only.
    years = defaultdict(dict)
    by_year = defaultdict(list)
    for c in old + use:
        by_year[(c["pid"], int(day_str(c["closed_at"])[:4]))].append(c)
    none = {m: None for m in METRICS}
    for (pid, y), cs in by_year.items():
        s = sums(cs)
        ok = s["cls"] >= MIN_CLS and s["td"] >= MIN_EXP
        v = dict(none)
        if ok:
            v.update(tn=r3(s["t"] / s["cls"]), ts=r3(s["t"] / s["ts"]) if s["ts"] else None,
                     td=r3(s["t"] / s["td"]) if s["td"] else None)
        x = dict(none)
        # Whole years in range: the same values the page's periods have, against
        # the rates of all the data ("all").
        jan1 = datetime(y, 1, 1, tzinfo=timezone.utc).timestamp()
        recent = [c for c in cs if "thr" in c]
        pp = person_period(pid, recent, "all") if jan1 >= START and recent else None
        if pp and ok:
            ok_a = jan1 >= ADDR_START and pp["ok_a"]
            for m in METRICS:
                if m[0] == "a" and ok_a:
                    v[m] = pp["v"][m]
                if jan1 >= START and (m[0] == "t" or ok_a):
                    x[m] = pp["x"][m]
        years[pid][y] = (Counter(c["org"] for c in cs).most_common(1)[0][0], v, x)
    change = yearly_changes(years, trend_groups)
    by_size, dir_names, by_dir = median_breakdowns(use, G.size10)
    for m in ("tn", "ts", "td", "ad"):
        print(f"median by size ({m}): " + " ".join(f"{v}/{n}" for v, n in by_size["all"][m]), file=sys.stderr)
        print(f"median by directory ({m}): " + ", ".join(f"{d} {v}/{n}" for d, (v, n) in zip(dir_names, by_dir["all"][m])),
              file=sys.stderr, flush=True)
    print(f"opening card: {len(trend_pts):,} people; {change['all']['td']['n']:,} year-over-year changes from "
          f"{change['all']['td']['people']:,} people (median {change['all']['td']['median']}% less), "
          f"{change['all']['ad']['n']:,} addressed", file=sys.stderr, flush=True)

    # ------------------------------------------------ peers
    tone_end = week_start(TONE_WEEKS[-1]) + WEEK

    def tone_bands(pid):
        ten = (tone_end - first[pid]) / YEAR if pid in first else None
        return dict(time=tenure_band(ten),
                    changes=changes_band(bisect.bisect_left(own_times.get(pid, ()), tone_end)))

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
                 start=epoch_day(START), end=epoch_day(END), addr_start=epoch_day(ADDR_START),
                 tenure=TENURE, changes=CHANGES, xp=XP, min_peers=MIN_PEERS, qs=len(QS), min_cls=MIN_CLS, min_exp=MIN_EXP, min_received=MIN_RECEIVED,
                 tone_weeks=[TONE_WEEKS[0], TONE_WEEKS[-1]], dist={}, counts={}, bands={}, tone={},
                 cohort_step=STEP, cohort_from=int(HISTORY_ISO[:4]), min_cohort=MIN_COHORT, cohorts=cohorts,
                 change_ratios=[round(r, 4) for r in CHANGE_RATIOS], change=change, min_cohort_cls=MIN_COHORT_CLS,
                 size_labels=SIZE_LABELS, by_size=by_size, dir_names=dir_names, by_dir=by_dir,
                 min_cell_cls=MIN_CELL_CLS)
    for p in allp:
        # Peers per kind: the addressed measures count people by their labelled CLs.
        rows = {k: [(pid, pp[p]) for pid, pp in per.items() if p in pp and pp[p][ok]]
                for k, ok in (("t", "ok"), ("a", "ok_a"))}
        dp = peers["dist"][p] = {}
        for g, f in groups.items():
            dp[g] = {}
            for m in METRICS:
                xs = [x["x" if g.startswith("dir:") else "v"][m] for _, x in rows[m[0]] if f(x)]
                xs = [v for v in xs if v is not None]
                dp[g][m] = dict(n=len(xs), q=quantiles(xs) if len(xs) >= MIN_PEERS else None)
        # The same peers' counts: CLs landed and reviewer threads on them (for the
        # addressed measures, labelled CLs and addressed threads).
        cp = peers["counts"][p] = {}
        for g, f in groups.items():
            cp[g] = {}
            for k, fields in (("t", ("cls", "threads")), ("a", ("acls", "addressed"))):
                for fld in fields:
                    xs = [x[fld] for _, x in rows[k] if f(x)]
                    cp[g][fld] = dict(n=len(xs), q=quantiles(xs) if len(xs) >= MIN_PEERS else None)
        # Per experience band: the pooled rate relative to everyone, and the spread of people
        # with enough CL share in the band (1.5 CLs' worth or more).
        bp = peers["bands"][p] = {}
        for m in METRICS:
            ov = overall.get((p, m))
            bp[m] = []
            for b in range(5):
                xs = [x["bands"][m][b][0] / x["bands"][m][b][1] for _, x in rows[m[0]]
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
            check[k] = {p: {x: v for x, v in pp.items() if x not in ("bands", "curve", "curve_a")} for p, pp in per[pid].items()}
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


if __name__ == "__main__":
    main()
