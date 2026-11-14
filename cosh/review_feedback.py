"""Per-person data for the Feedback Index page (web/feedback-index.html,
docs/review-feedback.md).

The feedback rate (FR) of a set of CLs is their addressed reviewer threads
per 100 changed lines; the feedback index (FI) is a person's FR over their
peers' (the median FR at the same experience, adjusted for directories and,
optionally, org: `rate_model`, `expected`).

Offline; reads reviews.sqlite, commits.sqlite, addressed.sqlite,
sentiment.sqlite and the sentiment comment files. Writes, under --out
(default web/public/review-feedback/):

  peers.json         the experience bins, the index's typical rates and
                     factors, the spread of FR per bin and of everyone's FI
                     per norm and period, and the methodology's charts
  u/<key>.json       one per CL owner: first commit, which half-years they
                     have files for, praise received
  u/<key>.json       for each other address of the same person: {"see": key}
  <half>/<key>.json  that half-year's CLs, with directory splits and the
                     reviewer threads (excerpts where comment text exists)

<key> is a hash of the normalised address (`key` below; the page computes the
same), so the folder can't be browsed for names and the page can't offer
completions. Everything comes from public Gerrit and git data. Review tone
appears only as praise (docs/plan.md, ground rule 5): nothing written here
marks a comment, a person or an org as negative, and orgs get no tone figures.

  COSH_DATA_DIR=<main>/data/private nice -n 5 python3 -m cosh.review_feedback [--out DIR]
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
from collections import Counter, defaultdict, namedtuple
from datetime import datetime, timezone

from . import classify, sentiment, store
from . import commits as C
from . import cl_facts as F
from .cl_facts import CL_FACTS, SINCE, cl_facts
from .orgs import OrgResolver
from .people import Ids, alias_pairs, is_bot_email, person

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "web", "public", "review-feedback")
DAY = 86400
YEAR = 365.25 * DAY
WEEK = 7 * DAY
ADDR_COVER = 0.95             # the addressed measure starts where every later week has labels for this share
TONE_WEEKS = []              # the year with comment text and tone scores: set by main (--tone-weeks)
SALT = "cosh-review-feedback-v1:"
EXCERPT = 200                 # characters of a comment kept for the drill-down
# A person's feedback index over a period counts among peers (the spread
# the page shows) with this many CLs. At 25 CLs its noise is about ±38%
# (docs/review-feedback.md).
MIN_CLS = 25
MIN_RECEIVED = 20             # ... and among tone peers with this many comments received
QS = [i / 20 for i in range(21)]
TENURE = ["<1y", "1-2y", "2-5y", "5-10y", "10y+"]
CHANGES = ["<50", "50-199", "200-499", "500-999", "1000+"]   # the author's earlier commits on main (all of its history)
MIN_PEERS = 10                # fewer people than this get no percentiles
PATCHSET_LEVEL = "/PATCHSET_LEVEL"   # the path of a general comment's thread: not counted


def key(email):
    """The file name for an address: the page normalises and hashes the same way."""
    return hashlib.sha256((SALT + person(email.strip())).encode()).hexdigest()[:32]


def tenure_band(years):
    return None if years is None else "<1y" if years < 1 else "1-2y" if years < 2 else "2-5y" if years < 5 \
        else "5-10y" if years < 10 else "10y+"


def changes_band(n):
    return None if n is None else "<50" if n < 50 else "50-199" if n < 200 else "200-499" if n < 500 \
        else "500-999" if n < 1000 else "1000+"


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
    fetched, no earlier than the oldest usable CL's week, trimmed to months."""
    d = ro(os.path.join(store.DATA_DIR, store.DERIVED_FILE))
    row = d.execute("SELECT v FROM meta WHERE k = 'fetched_weeks'").fetchone()
    weeks = sorted(json.loads(row[0])) if row else []
    if not weeks:
        raise SystemExit("reviews.sqlite records no fetched weeks")
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


def half_span(h):
    """Unix times [from, to) of half-year 'YYYYH1' or 'YYYYH2'."""
    y, h2 = int(h[:4]), h.endswith("H2")
    a = datetime(y, 7 if h2 else 1, 1, tzinfo=timezone.utc)
    b = datetime(y + 1, 1, 1, tzinfo=timezone.utc) if h2 else datetime(y, 7, 1, tzinfo=timezone.utc)
    return a.timestamp(), b.timestamp()


def last_whole_half(start, end):
    """The latest half-year that lies wholly within [start, end), or None."""
    h = half(end - DAY)
    if half_span(h)[1] > end:
        h = half(half_span(h)[0] - DAY)          # the one before
    return h if half_span(h)[0] >= start else None


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



def ro(path):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


_GIT_DB = None


def git_db():
    """commits.sqlite, read-only, opened once."""
    global _GIT_DB
    if _GIT_DB is None:
        _GIT_DB = ro(C.db_path())
    return _GIT_DB


def year(t):
    return datetime.fromtimestamp(t, timezone.utc).year


def size10(lines):
    """Ten log-spaced size buckets: <4, <8, ..., <1024, 1024+ (changed lines)."""
    return min(9, max(0, int(math.log2(max(lines, 1))) - 1))


# ---------------------------------------------------------------- loading

def early_commits(before=SINCE):
    """Main's first-parent commits that landed before `before`, where
    gcommits starts (commits.sqlite): [(author email, unix time landed,
    frozenset of 3-level directories)], reverts left out (`is_revert`: SVN-era
    reverts may name no sha).
    With them, earlier commits count from the start of main's history
    (2008), not from 2017."""
    cut = datetime.fromisoformat(before).replace(tzinfo=timezone.utc).timestamp()
    out, cur = [], None
    for cid, email, at, path in git_db().execute(
            "SELECT c.commit_id, c.author_email, c.landed_at, p.path FROM commits c "
            "LEFT JOIN commit_files f USING (commit_id) LEFT JOIN paths p USING (path_id) "
            "WHERE c.landed_at < ? AND NOT c.is_revert ORDER BY c.commit_id", (cut,)):
        if cur is None or cur[0] != cid:
            if cur:
                out.append((cur[1], cur[2], frozenset(cur[3])))
            cur = (cid, email, at, set())
        if path is not None:
            cur[3].add(C.dir_of(path, 3))
    if cur:
        out.append((cur[1], cur[2], frozenset(cur[3])))
    return out


def load(args):
    """The CLs, with the columns reviews.sqlite and commits.sqlite give
    (cosh.cl_facts), owners' addresses normalised; human commits;
    identities; first commits. Also the CLs' raw owner addresses and
    {commit_id: change_number} of their landed commits."""
    facts, by_cid = cl_facts(ro(os.path.join(store.DATA_DIR, store.DERIVED_FILE)), git_db())
    raw_email = {f[0]: f[2] for f in facts}
    cls = [dict(zip(CL_FACTS, f)) for f in facts]
    del facts
    for c in cls:
        c["owner_email"] = person(c["owner_email"]) if c["owner_email"] else None
    commits = C.human_commits(git_db())
    ids = Ids()
    for a, b in alias_pairs(cls, commits):
        ids.union(a, b)
    for c in commits:
        c["pid"] = ids.find(c["email"])
    for c in cls:
        c["pid"] = ids.find(c["owner_email"]) if c["owner_email"] else None
    first = {}
    for e, t in C.first_people(git_db()).items():
        k = ids.find(e)
        first[k] = min(t, first.get(k, t))
    print(f"loaded {len(cls):,} CLs, {len(commits):,} commits", file=sys.stderr, flush=True)
    return cls, commits, ids, first, raw_email, by_cid




def norms(use, also=()):
    """The 2023-24 norms, as in the review-ROI analysis: mean reviewer
    threads (and addressed threads) per merged CL by size bucket and top
    2-level directory (groups of 30 or more), else by size bucket alone.
    Computed from `use`, and set on `use` and `also` (older CLs)."""
    ref = [c for c in use if year(c["closed_at"]) in (2023, 2024)]
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


# ---------------------------------------------------------------- feedback rate and index
# The feedback rate (FR) of a set of CLs: their addressed reviewer threads per
# 100 changed lines (insertions plus deletions), pooled. Experience is the
# owner's CLs landed on main counting the CL itself (earlier commits + 1), in
# power-of-two bins named by their top, so each bin is one doubling: "8" is 8
# or fewer, "16" is 9–16, ..., "2k" is 1,025–2,048, ">2k" more.
BIN_EDGES = [8 * 2 ** k for k in range(9)]          # 8, 16, ..., 2048
BIN_LABELS = ["8", "16", "32", "64", "128", "256", "512", "1k", "2k", ">2k"]
MIN_BIN_CLS = 5           # a person's FR in one experience bin counts with this many CLs there
FR_FLOOR = 0.1            # FRs below this count as this in the growth fit (log scale)
MIN_GROWTH_BINS = 3       # a growth rate needs FRs in this many bins
# "How it's changing": the FR over a newcomer's first NEWCOMER_CLS changes, by
# the year of their first commit on main, from NEWCOMER_FROM.
NEWCOMER_CLS, NEWCOMER_FROM = 10, 2018
MIN_CELL_CLS = 10         # a person counts in a size, directory or org bar with this many CLs there
CHART_DIRS, CHART_ORGS = 12, 10
# A directory (two levels, else one) or org gets its own factor in the
# feedback index with this many CLs' worth; others get 1 (directories) or the
# pooled factor of all smaller orgs ("*").
MIN_FACTOR_CLS = 300
# What the feedback index sets a person's FR against: the median FR of people
# at the same experience ("e"; else everyone's median), adjusted for how much
# feedback the directory ("d") and the org ("o") draw. Every combination.
NORMS = ["", "e", "d", "ed", "o", "eo", "do", "edo"]
# The growth chart: a smoothed distribution of people's growth rates, on a
# grid of log2 of the change per doubling.
GROWTH_GRID = [round(-2 + 0.05 * i, 2) for i in range(71)]
GROWTH_BW = 0.12
# The feedback index's chart: everyone's index (experience and directories),
# smoothed the same way, on a grid of log2 of the index (1/8 .. 5.7).
FI_NORM = "ed"
FI_GRID = [round(-3 + 0.05 * i, 2) for i in range(111)]
FI_BW = 0.15
SIZE_LABELS = ["<4", "4–7", "8–15", "16–31", "32–63", "64–127", "128–255", "256–511", "512–1k", "1k+"]

Row = namedtuple("Row", "pid at lines prior bin org addr units main")


def xbin(n):
    """The experience bin (index in BIN_LABELS) of n earlier commits."""
    return bisect.bisect_right(BIN_EDGES, n)


def fr(addressed, lines):
    return 100 * addressed / lines if lines > 0 else None


def dir2(d):
    """A 3-level directory's first two levels ("chrome/browser/")."""
    p = [x for x in d.split("/") if x]
    return "/".join(p[:2]) + "/" if p else d


def dir1(d):
    p = [x for x in d.split("/") if x]
    return p[0] + "/" if p else d


def unit_fracs(units):
    """Each directory's fraction of a CL's lines, from [(share, lines there)]:
    by lines, or by share where the landed commit changed no lines."""
    s = sum(lines for _, lines in units)
    return [lines / s if s > 0 else w for w, lines in units]


def fr_row(c):
    """A CL as the rate measures need it. units: [(3-level directory,
    fraction of the CL's lines, addressed threads there)], largest share first."""
    order = sorted(c["units"].items(), key=lambda kv: (-kv[1][0], kv[0]))
    per = Counter(t[4] for t in c["thr"] if t[3])
    fr_ = unit_fracs([(u[0], u[2]) for _, u in order])
    return Row(c["pid"], c["closed_at"], c["lines"], c["prior"], xbin(c["prior"]), c["org"], c["addressed"],
               [(d, f, per[d]) for (d, _), f in zip(order, fr_)], order[0][0])


def person_cells(rows):
    """{experience bin: [CLs, addressed threads, lines]} of one person's rows."""
    out = defaultdict(lambda: [0, 0, 0])
    for r in rows:
        x = out[r.bin]
        x[0] += 1
        x[1] += r.addr
        x[2] += r.lines
    return dict(out)


def growth(cells):
    """A person's growth rate: the % change in their FR per doubling of changes
    landed, from a least-squares line through log2 FR (floored at FR_FLOOR)
    by experience bin, each bin weighted by its CLs. Needs MIN_GROWTH_BINS
    bins with MIN_BIN_CLS CLs. None otherwise."""
    pts = [(b, math.log2(max(fr(a, lines), FR_FLOOR)), n) for b, (n, a, lines) in cells.items()
           if n >= MIN_BIN_CLS and lines > 0]
    if len(pts) < MIN_GROWTH_BINS:
        return None
    w = sum(n for _, _, n in pts)
    mx = sum(b * n for b, _, n in pts) / w
    my = sum(y * n for _, y, n in pts) / w
    sxx = sum(n * (b - mx) ** 2 for b, _, n in pts)
    sxy = sum(n * (b - mx) * (y - my) for b, y, n in pts)
    return round(100 * (2 ** (sxy / sxx) - 1), 1)


def median_or_none(xs):
    return r3(st.median(xs)) if len(xs) >= MIN_PEERS else None


def bin_frs(by_pid):
    """Per experience bin, every person's FR there (MIN_BIN_CLS CLs or more)."""
    out = [[] for _ in BIN_LABELS]
    for rs in by_pid.values():
        for b, (n, a, lines) in person_cells(rs).items():
            if n >= MIN_BIN_CLS and lines > 0:
                out[b].append(fr(a, lines))
    return out


def fr_bins(by_pid):
    """The main chart: per experience bin, the spread of people's FR there."""
    return [dict(n=len(xs), q=quantiles(xs) if len(xs) >= MIN_PEERS else None) for xs in bin_frs(by_pid)]


def rate_model(rows):
    """What the feedback index compares with. ref_bin: the median FR per
    experience bin (the main chart's line); ref_all: the median FR of everyone
    with MIN_CLS CLs over all of theirs. f_dir[e]: per directory (two levels,
    and one level as the fallback), how much more feedback per line it draws
    than its CLs' experience predicts (e "e") or than everyone's median
    (e ""), relative to all directories. f_org[norm without o]: the same per
    org, on top of the directory factor when "d" is in it; "*" pools the orgs
    under MIN_FACTOR_CLS. All rounded, as the page uses them."""
    by_pid = defaultdict(list)
    for r in rows:
        by_pid[r.pid].append(r)
    ref_bin = [median_or_none(xs) for xs in bin_frs(by_pid)]
    alls = []
    for rs in by_pid.values():
        lines = sum(r.lines for r in rs)
        if len(rs) >= MIN_CLS and lines > 0:
            alls.append(fr(sum(r.addr for r in rs), lines))
    m = dict(ref_bin=ref_bin, ref_all=r3(st.median(alls)), f_dir={}, f_org={"": {"*": 1.0}, "e": {"*": 1.0},
                                                                       "d": {"*": 1.0}, "ed": {"*": 1.0}})

    big = [rs for rs in by_pid.values() if len(rs) >= MIN_CLS]

    def median_fi(norm):
        xs = []
        for rs in big:
            e = sum(expected(r, norm, m) for r in rs)
            if e > 0:
                xs.append(sum(r.addr for r in rs) / e)
        return st.median(xs)

    def rescale(t, norm, target):
        """Scales a factor table so the median person's index under `norm`
        is what it is without that adjustment: the factors are pooled by
        lines, so only their spread, not their level, is meant."""
        s = median_fi(norm) / target
        for k in t:
            t[k] = r3(t[k] * s)

    for e in ("", "e"):
        obs, exp, n = defaultdict(float), defaultdict(float), defaultdict(float)
        for r in rows:
            b = (m["ref_bin"][r.bin] or m["ref_all"]) if e else m["ref_all"]
            for d, f, a in r.units:
                x = r.lines / 100 * b * f
                for k in {dir2(d), dir1(d)}:
                    obs[k] += a
                    exp[k] += x
                    n[k] += f
        m["f_dir"][e] = {k: obs[k] / exp[k] for k in sorted(obs) if n[k] >= MIN_FACTOR_CLS and exp[k] > 0}
        rescale(m["f_dir"][e], e + "d" if e else "d", median_fi(e))
    for nm in ("", "e", "d", "ed"):
        obs, exp, n = defaultdict(float), defaultdict(float), Counter()
        for r in rows:
            obs[r.org] += r.addr
            exp[r.org] += expected(r, nm, m)
            n[r.org] += 1
        big_o = {o for o in n if n[o] >= MIN_FACTOR_CLS and exp[o] > 0}
        so = sum(v for o, v in obs.items() if o not in big_o)
        se = sum(v for o, v in exp.items() if o not in big_o)
        t = {o: obs[o] / exp[o] for o in sorted(big_o)}
        t["*"] = so / se if se > 0 else 1.0
        m["f_org"][nm] = t
        rescale(t, nm.replace("d", "do") if "d" in nm else nm + "o", median_fi(nm))
    return m


def expected(r, norm, m):
    """The addressed threads a CL would draw at its peers' FR, under norm (see NORMS)."""
    base = (m["ref_bin"][r.bin] or m["ref_all"]) if "e" in norm else m["ref_all"]
    fo = 1.0
    if "o" in norm:
        t = m["f_org"][norm.replace("o", "")]
        fo = t.get(r.org, t["*"])
    if "d" in norm:
        t = m["f_dir"]["e" if "e" in norm else ""]
        share = sum(f * t.get(dir2(d), t.get(dir1(d), 1.0)) for d, f, _ in r.units)
    else:
        share = 1.0
    return r.lines / 100 * base * fo * share


def newcomers(by_pid, first_year):
    """Per year of first commit on main from NEWCOMER_FROM: [year, people,
    p10, p25, median, p75, p90] of the FR over their CLs with fewer than
    NEWCOMER_CLS earlier commits (MIN_BIN_CLS of them or more)."""
    ys = defaultdict(list)
    for pid, rs in by_pid.items():
        y = first_year.get(pid)
        if y is None or y < NEWCOMER_FROM:
            continue
        cs = [r for r in rs if r.prior < NEWCOMER_CLS]
        lines = sum(r.lines for r in cs)
        if len(cs) >= MIN_BIN_CLS and lines > 0:
            ys[y].append(fr(sum(r.addr for r in cs), lines))
    out = []
    for y in sorted(ys):
        q = quantiles(ys[y])
        out.append([y, len(ys[y])] + ([q[2], q[5], q[10], q[15], q[18]] if len(ys[y]) >= MIN_PEERS else [None] * 5))
    return out


def cell_medians(by_pid, key_of):
    """{key: (median of people's FR, median of their addressed threads per CL,
    people)} over people with MIN_CELL_CLS CLs under one key; MIN_PEERS people
    or more."""
    vals = defaultdict(list)
    for rs in by_pid.values():
        cell = defaultdict(lambda: [0, 0, 0])
        for r in rs:
            x = cell[key_of(r)]
            x[0] += 1
            x[1] += r.addr
            x[2] += r.lines
        for k, (n, a, lines) in cell.items():
            if k is not None and n >= MIN_CELL_CLS and lines > 0:
                vals[k].append((fr(a, lines), a / n))
    return {k: (r3(st.median(v[0] for v in xs)), r3(st.median(v[1] for v in xs)), len(xs))
            for k, xs in vals.items() if len(xs) >= MIN_PEERS}


def by_size(by_pid):
    """Per size bucket (SIZE_LABELS): [median FR, median addressed threads per CL, people]."""
    m = cell_medians(by_pid, lambda r: size10(r.lines))
    return [list(m.get(b, (None, None, 0))) for b in range(len(SIZE_LABELS))]


def by_dir(by_pid):
    """The CHART_DIRS two-level directories with the most people (each CL by
    its main directory), highest median FR first: [directory, median FR, people]."""
    m = cell_medians(by_pid, lambda r: dir2(r.main))
    top = sorted(m.items(), key=lambda kv: (-kv[1][2], kv[0]))[:CHART_DIRS]
    return [[k, v[0], v[2]] for k, v in sorted(top, key=lambda kv: (-kv[1][0], kv[0]))]


def by_org(by_pid):
    """The CHART_ORGS orgs with the most people: [org, median FR, people], highest first."""
    m = cell_medians(by_pid, lambda r: r.org)
    top = sorted(m.items(), key=lambda kv: (-kv[1][2], kv[0]))[:CHART_ORGS]
    return [[k, v[0], v[2]] for k, v in sorted(top, key=lambda kv: (-kv[1][0], kv[0]))]


def kde(ls, grid, bw):
    """A Gaussian kernel density of the log2 values `ls` on `grid`, as % of
    them per 0.1 of log2."""
    k = 1 / (len(ls) * bw * math.sqrt(2 * math.pi))
    return [round(10 * k * sum(math.exp(-0.5 * ((x - v) / bw) ** 2) for v in ls), 3) for x in grid]


def growth_dist(gs):
    """People's growth rates: how many, the median and quantiles (% per
    doubling), and a smoothed curve: [% change per doubling, % of people per
    0.1 of log2] on GROWTH_GRID (a Gaussian kernel of GROWTH_BW in log2)."""
    if not gs:
        return dict(n=0, median=None, q=None, curve=[])
    ys = kde([math.log2(1 + g / 100) for g in gs], GROWTH_GRID, GROWTH_BW)
    curve = [[round(100 * (2 ** x - 1), 1), y] for x, y in zip(GROWTH_GRID, ys)]
    return dict(n=len(gs), median=round(st.median(gs), 1), q=quantiles(gs), curve=curve)


def fi_dist(xs):
    """Everyone's feedback index: how many, quantiles, and a smoothed curve
    [index, % of people per 0.1 of log2] on FI_GRID (indexes under 1/8 count
    as 1/8)."""
    if not xs:
        return dict(n=0, q=None, curve=[])
    ys = kde([math.log2(max(x, 0.125)) for x in xs], FI_GRID, FI_BW)
    return dict(n=len(xs), q=quantiles(xs), curve=[[round(2 ** x, 3), y] for x, y in zip(FI_GRID, ys)])


# ---------------------------------------------------------------- building

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--check", help="also write some people's per-period values here, to compare with the page's")
    ap.add_argument("--tone-weeks", help="the weeks with comment text and tone scores, e.g. 2025-W45:2026-W44 "
                                         "(default: the newest year of fully scored weeks, as Review Tone)")
    args = ap.parse_args()
    TONE_WEEKS[:] = sentiment.weeks_in(args.tone_weeks or sentiment.scored_weeks())
    print(f"tone weeks {TONE_WEEKS[0]} .. {TONE_WEEKS[-1]}", file=sys.stderr, flush=True)

    cls, commits, ids, first, raw_email, by_cid = load(args)
    mech = C.left_out(git_db(), cls)       # mechanical and large-scale-change CLs
    dirs3 = C.commit_dirs(git_db(), 3)
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
    # gcommits starts in 2017: earlier commits come from the rest of commits.sqlite.
    early = 0
    for email, at, ds in early_commits():
        if is_bot_email(person(email)):
            continue
        pid = ids.find(email)
        own_times[pid].append(at)
        for x in ds:
            xp_times[(pid, x)].append(at)
        early += 1
    print(f"{early:,} human commits before {SINCE} counted as earlier commits", file=sys.stderr, flush=True)
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

    ddb = ro(os.path.join(store.DATA_DIR, store.DERIVED_FILE))
    bots = {a for a, in ddb.execute("SELECT account_id FROM accounts WHERE is_bot = 1")}
    acct_email = dict(ddb.execute("SELECT account_id, email FROM accounts WHERE host = "
                                "'chromium-review.googlesource.com'"))

    # Merged, human-owned CLs, neither mechanical nor LSC (the review-ROI analyses' rule).
    for c in cls:
        if c["change_number"] in mech:
            c["status"] = "MECH"
    use = [c for c in cls if c["status"] == "MERGED" and c["closed_at"] and c["pid"]
           and not is_bot_email(c["owner_email"])]
    for c in use:
        c["lines"] = (c["ins"] or 0) + (c["dels"] or 0)
        c["sb"] = size10(c["lines"])
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
        if n in use_n:
            addressed = 0 if reply is None else 1 if rx else labels.get((n, root, h))
            thr[n].append([root, path or "", (at or "")[:10], addressed, reply is not None and not rx])
            use_n[n]["threads"] += 1
            use_n[n]["addressed"] += 1 if addressed else 0
    del use_n
    norms(use)
    START, END = data_range(use)
    use = [c for c in use if START <= c["closed_at"] < END]
    for c in use:           # the page sums the rounded values, so compute with them here too
        for k in ("exp_ts", "exp_td", "exp_as", "exp_ad"):
            c[k] = r3(c[k])
    by_n = {c["change_number"]: c for c in use}
    print(f"{len(use):,} CLs in range {day_str(START)} .. {day_str(END - DAY)}", file=sys.stderr, flush=True)

    cl_dirs = defaultdict(dict)       # by CL, then directory
    for (n, d), (files, lines) in sorted(F.cl_dirs(git_db(), by_cid, by_n).items()):
        cl_dirs[n][d] = (lines + files, lines)
    del by_cid
    orgs = OrgResolver()
    for c in use:
        n = c["change_number"]
        day = datetime.fromtimestamp(c["closed_at"], timezone.utc).strftime("%Y-%m-%d")
        c["org"] = orgs(raw_email.get(n), day)
        # Tenure in whole days, as the page computes it from the day numbers it has.
        c["ten"] = (epoch_day(c["closed_at"]) - epoch_day(first[c["pid"]])) / 365.25 if c["pid"] in first else None
        # Each directory's weight is its lines plus files; the page also shows its lines.
        w = cl_dirs.get(n) or {"(root)/": (1, c["lines"])}
        tot = sum(v for v, _ in w.values())
        at = landed_at.get(n, c["closed_at"])
        c["units"] = {d: [r3(v / tot), bisect.bisect_left(xp_times.get((c["pid"], d), ()), at), lines]
                      for d, (v, lines) in w.items()}
        # The first unit in the files' order (largest rounded share, then name):
        # the page takes it as the directory of threads outside every unit.
        c["main"] = min(c["units"], key=lambda d: (-c["units"][d][0], d))
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
            dr = C.dir_of(path, 3) if path and not path.startswith("/") else None
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
            tone_pid[acct] = ids.find(e) if e and not is_bot_email(e) else None
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

    # ------------------------------------------------ feedback rate and index
    # Only the labelled CLs count (from ADDR_START, which is START once every
    # week is labelled): the feedback rate is addressed threads per 100 lines.
    people = defaultdict(list)
    for c in use:
        people[c["pid"]].append(c)
    rows = [fr_row(c) for c in use if c["acov"]]
    model = rate_model(rows)
    print(f"feedback rate by experience: " + " ".join(f"{l}={v}" for l, v in zip(BIN_LABELS, model["ref_bin"]))
          + f"; everyone {model['ref_all']}", file=sys.stderr, flush=True)
    by_pid = defaultdict(list)
    for r in rows:
        by_pid[r.pid].append(r)
    allp = sorted({p for r in rows for p in periods_of(r.at)}, key=lambda p: (p != "all", p))
    fi_vals = {nm: defaultdict(list) for nm in NORMS}
    growths = {}
    check_vals = {}
    for pid, rs in by_pid.items():
        exps = [[expected(r, nm, model) for nm in NORMS] for r in rs]
        byp = defaultdict(list)
        for r, e in zip(rs, exps):
            for p in periods_of(r.at):
                byp[p].append((r, e))
        g = growth(person_cells(rs))
        if g is not None:
            growths[pid] = g
        vals = {}
        for p, pr in byp.items():
            n, a, lines = len(pr), sum(r.addr for r, _ in pr), sum(r.lines for r, _ in pr)
            fis = {}
            for i, nm in enumerate(NORMS):
                e = sum(x[i] for _, x in pr)
                fis[nm] = r3(a / e) if e > 0 else None
                if n >= MIN_CLS and e > 0:
                    fi_vals[nm][p].append(a / e)
            vals[p] = dict(cls=n, addressed=a, lines=lines, fr=r3(fr(a, lines)) if lines else None, fi=fis)
        if args.check and len(check_vals) < 300:
            check_vals[key(pid)] = dict(periods=vals, growth=g)

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

    dist = lambda xs: dict(n=len(xs), q=quantiles(xs) if len(xs) >= MIN_PEERS else None)
    first_year = {pid: datetime.fromtimestamp(t, timezone.utc).year for pid, t in first.items()}
    peers = dict(v=5, generated=datetime.now(timezone.utc).strftime("%Y-%m-%d"), periods=allp,
                 start=epoch_day(START), end=epoch_day(END), addr_start=epoch_day(ADDR_START),
                 min_peers=MIN_PEERS, min_cls=MIN_CLS, min_bin_cls=MIN_BIN_CLS, min_cell_cls=MIN_CELL_CLS,
                 min_growth_bins=MIN_GROWTH_BINS, fr_floor=FR_FLOOR, bins=BIN_LABELS, bin_edges=BIN_EDGES,
                 norms=NORMS, **model,
                 fr_bins=fr_bins(by_pid),
                 fi={nm: {p: dist(v.get(p, [])) for p in allp} for nm, v in fi_vals.items()},
                 newcomer_cls=NEWCOMER_CLS, newcomers=newcomers(by_pid, first_year),
                 size_labels=SIZE_LABELS, by_size=by_size(by_pid), by_dir=by_dir(by_pid), by_org=by_org(by_pid),
                 growth=growth_dist(list(growths.values())), fi_norm=FI_NORM,
                 fi_dist=fi_dist(fi_vals[FI_NORM].get("all", [])),
                 tenure=TENURE, changes=CHANGES, min_received=MIN_RECEIVED,
                 tone_weeks=[TONE_WEEKS[0], TONE_WEEKS[-1]], tone={})
    for nm in ("ed", "e", ""):
        q = peers["fi"][nm]["all"]
        print(f"feedback index ({nm or 'none'}): {q['n']:,} people, quartiles "
              f"{[round(x, 2) for x in q['q'][5::5]] if q['q'] else None}", file=sys.stderr)
    gq = peers["growth"]
    print(f"growth per doubling: {gq['n']:,} people, median {gq['median']}%, "
          f"p10 {gq['q'][2]}% p90 {gq['q'][18]}%" if gq["q"] else "growth: none", file=sys.stderr)
    print("newcomers: " + " ".join(f"{y}={m}/{n}" for y, n, _, _, m, _, _ in peers["newcomers"]), file=sys.stderr)
    print("by size: " + " ".join(f"{l} {v}" for l, v in zip(SIZE_LABELS, peers["by_size"])), file=sys.stderr)
    print("by directory: " + ", ".join(f"{d} {v}/{n}" for d, v, n in peers["by_dir"]), file=sys.stderr)
    print("by org: " + ", ".join(f"{d} {v}/{n}" for d, v, n in peers["by_org"]), file=sys.stderr, flush=True)
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
    # Half-years that reach into the year with comment text keep each thread;
    # older ones keep counts per directory.
    tone_start = week_start(TONE_WEEKS[0])
    taken = {}
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
            data = json.dumps(shard(hcs, text, half_end(h) > tone_start), separators=(",", ":"), ensure_ascii=False)
            os.makedirs(os.path.join(out, h), exist_ok=True)
            with open(os.path.join(out, h, f"{k}.json"), "w") as f:
                f.write(data)
            size += len(data.encode())
        r = received.get(pid, {})
        top = dict(v=4, first=datetime.fromtimestamp(first[pid], timezone.utc).strftime("%Y-%m") if pid in first else None,
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
            json.dump(check_vals, f)
    print(f"wrote {written:,} people ({size / 1e6:.1f} MB) and {stubs:,} other addresses to {out}",
          file=sys.stderr)


HALF = re.compile(r"^\d{4}H[12]$")


def half_end(h):
    """The timestamp a half-year ("2025H2") ends at."""
    y, second = int(h[:4]), h[5] == "2"
    return datetime(y + second, 1 if second else 7, 1, tzinfo=timezone.utc).timestamp()


def shard(cs, text, threads):
    """One person's CLs of one half-year, oldest first: [change number, day
    landed, lines, expected threads by size and directory, expected addressed
    by size and directory, units, threads, org, the owner's earlier commits on
    main], with directory, file and org names listed once. The expected
    values by size alone are left out: they depend only on the size bucket,
    and peers.json's `size_norm` lists them.

    Units, largest share first: [directory, line share, earlier commits there,
    lines changed there], or [directory, earlier commits there] for a CL
    wholly in one directory (share 1, all of its lines).

    With `threads` (half-years that reach into the year with comment text),
    each reviewer thread: [comment uuid, file, days after landing, addressed,
    excerpt]. The uuid is empty for a thread without an excerpt (the page
    links its CL instead). A thread's directory is its file's (3 levels) when
    that is one of the CL's units, else the first unit's. Without `threads`
    the shard has `counts`: 1 and each CL has [threads, addressed] per unit,
    in the units' order, or [] when it has no reviewer threads."""
    files, dirs, orgs = {}, {}, {}

    def idx(table, x):
        return table.setdefault(x, len(table))
    rows = []
    for c in cs:
        n = c["change_number"]
        d0 = epoch_day(c["closed_at"])
        order = sorted(c["units"].items(), key=lambda kv: (-kv[1][0], kv[0]))
        assert order[0][0] == c["main"], n
        (d1, (w1, prior1, lines1)), = order[:1]
        if len(order) == 1 and w1 == 1 and lines1 == c["lines"]:
            units = [[idx(dirs, d1), prior1]]
        else:
            units = [[idx(dirs, dd), w, prior, lines] for dd, (w, prior, lines) in order]
        thr = []
        if threads:
            for root, path, at, addr, dd in sorted(c["thr"], key=lambda t: (t[2], t[0])):
                ex = text.get(f"{n}/{root}")
                t = [root if ex is not None else "", idx(files, path), (day_of(at) - d0) if at else None,
                     None if addr is None else int(bool(addr))]
                if ex is not None:
                    t.append(ex)
                thr.append(t)
        elif c["thr"]:
            per = {dd: [0, 0] for dd, _ in order}
            for _, _, _, addr, dd in c["thr"]:
                per[dd][0] += 1
                per[dd][1] += 1 if addr else 0
            thr = [per[dd] for dd, _ in order]
        rows.append([n, d0, c["lines"], c["exp_td"], c["exp_ad"], units, thr, idx(orgs, c["org"]), c["prior"]])
    out = dict(dirs=list(dirs), files=list(files), orgs=list(orgs), cls=rows)
    if not threads:
        out["counts"] = 1
    return out


if __name__ == "__main__":
    main()
