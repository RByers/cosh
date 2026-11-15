"""Per-person data for the Feedback Index page (web/feedback-index.html,
docs/review-feedback.md).

The addressed feedback rate (AFR) of a set of CLs is their addressed reviewer threads
per 100 new or changed lines; the feedback index (FI) is their addressed threads
over what their CLs would be expected to draw: everyone else's AFR at the same
experience, times each CL's reviewer factor from everyone else's CLs, over all
the data (`rate_model`, `own_factors`, `expected`).

Offline. Reads reviews.sqlite, commits.sqlite and addressed.sqlite (never
review tone or comment text) and writes, under --out (default
web/public/review-feedback/, committed):

  peers.json         global, loaded on opening: the experience bins, the
                     index's rate sums and scale, everyone's directory table,
                     the spread of AFR per bin and of everyone's FI per
                     period, and the methodology's charts
  reviewers.json     each reviewer's factor, by a short hash of the address

and, gzipped, under --people-out (default data/private/feedback-people/,
which `python3 -m cosh.r2 publish` uploads to the R2 bucket, docs/r2.md):

  u/<key>.json.gz       per person: first commit, usual org, which half-years
                     they have files for; for each other address of the same
                     person, {"see": key}
  <half>/<key>.json.gz  per person and half-year: their CLs, with lines per
                     directory and the files that drew reviewer threads
                     (`shard`; no comment ids or text)

<key> is a hash of the normalised address (`key` below; the page computes the
same), so the folder can't be browsed for names and the page can't offer
completions. Everything comes from public Gerrit and git data.

  COSH_DATA_DIR=<main>/data/private nice -n 5 python3 -m cosh.review_feedback [--out DIR] [--people-out DIR]
"""

import argparse
import bisect
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

from . import classify, r2, store
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
SALT = "cosh-review-feedback-v1:"
# A person's feedback index over a period counts among peers (the spread
# the page shows) with this many CLs. At 25 CLs its noise is about ±38%
# (docs/review-feedback.md).
MIN_CLS = 25
QS = [i / 20 for i in range(21)]
MIN_PEERS = 10                # fewer people than this get no percentiles
PATCHSET_LEVEL = "/PATCHSET_LEVEL"   # the path of a general comment's thread: not counted


def key(email):
    """The file name for an address: the page normalises and hashes the same way."""
    return hashlib.sha256((SALT + person(email.strip())).encode()).hexdigest()[:32]


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
    """Ten log-spaced size buckets: <4, <8, ..., <1024, 1024+ (new or changed lines)."""
    return min(9, max(0, int(math.log2(max(lines, 1))) - 1))


# ---------------------------------------------------------------- loading

def early_commits(before=SINCE, current=None):
    """Main's first-parent commits that landed before `before`, where
    the per-CL window starts (commit_id > 0 in commits.sqlite): [(author email, unix time landed,
    frozenset of 3-level directories)], reverts left out (`is_revert`: SVN-era
    reverts may name no sha). With `current` (commits.current_paths),
    directories are today's names.
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
            cur[3].add(C.dir_of(current.get(path, path) if current else path, 3))
    if cur:
        out.append((cur[1], cur[2], frozenset(cur[3])))
    return out


def move_free_ins(gdb):
    """{change_number: insertions of its landed commit with each renamed file
    counted by the lines changed between its names (commits.moved_lines)},
    for the CLs since 2017 whose landed commit renamed files."""
    return dict(gdb.execute(
        "SELECT c.change_number, max(c.ins - sum(max(f.ins, 0) - max(r.ins, 0)), 0) FROM renames r "
        "JOIN commits c USING (commit_id) JOIN commit_files f ON f.commit_id = r.commit_id AND f.path_id = r.new_path_id "
        "WHERE r.commit_id > 0 AND r.ins IS NOT NULL AND c.change_number IS NOT NULL GROUP BY r.commit_id"))


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




# ---------------------------------------------------------------- AFR and index
# The addressed feedback rate (AFR) of a set of CLs: their addressed reviewer threads per
# 100 new or changed lines (Gerrit's insertions), pooled. Experience is the
# owner's CLs landed on main counting the CL itself (earlier commits + 1), in
# power-of-two bins named by their top, so each bin is one doubling: "8" is 8
# or fewer, "16" is 9–16, ..., "4k" is 2,049–4,096, ">4k" more. The top bin
# stops at 4k because only one person has passed 8k (2026-11-14).
BIN_EDGES = [8 * 2 ** k for k in range(10)]         # 8, 16, ..., 4096
BIN_LABELS = ["8", "16", "32", "64", "128", "256", "512", "1k", "2k", "4k", ">4k"]
MIN_BIN_CLS = 5           # a person's AFR in one experience bin counts with this many CLs there
FR_FLOOR = 0.1            # FRs below this count as this in the growth fit (log scale)
MIN_GROWTH_BINS = 3       # a growth rate needs FRs in this many bins
# "How it's changing": the AFR over people's CLs in one experience bin, by the
# year of their first commit on main, from COHORT_FROM (Gerrit data starts mid-2017).
COHORT_FROM = 2018
MIN_CELL_CLS = 10         # a person counts in a size, directory or org bar with this many CLs there
CHART_DIRS, CHART_ORGS = 12, 10
# The methodology's comparison of peer groups only (`method_compare`): a
# directory (3 levels, 2 or 1) has its own AFR at an experience bin with this
# many CLs' worth there without the person's own; elsewhere its parent's
# counts. 50 predicted other people's addressed threads best
# (docs/review-feedback-drift.md).
MIN_RATE_CLS = 50
# Reviewer and author factors (`two_way`): each is shrunk toward 1 with this
# many expected addressed threads, and the two are fitted in turn this many
# times. A reviewer is an approver in the landed commit's Reviewed-by trailers
# (docs/review-feedback-reviewers.md).
FACTOR_SHRINK = 50
FACTOR_ITERS = 10
# A reviewer counts in a directory on the methodology's chart of reviewers
# within directories (`dir_reviewers`) with this many expected threads there.
MIN_SPREAD_EXP = 50
# A directory gets its own row in everyone's directory table with this many CLs.
MIN_DIR_CLS = 100
# The growth chart: a smoothed distribution of people's growth rates, on a
# grid of log2 of the change per doubling.
GROWTH_GRID = [round(-2 + 0.05 * i, 2) for i in range(71)]
GROWTH_BW = 0.12
# The feedback index's chart: everyone's index, smoothed the same way, on a grid of log2 of the index (1/8 .. 5.7).
FI_GRID = [round(-3 + 0.05 * i, 2) for i in range(111)]
FI_BW = 0.15
SIZE_LABELS = ["<4", "4–7", "8–15", "16–31", "32–63", "64–127", "128–255", "256–511", "512–1k", "1k+"]

# revs: the CL's approvers (addresses as identities), sorted; () when it has none.
Row = namedtuple("Row", "pid at lines prior bin org addr units main revs", defaults=((),))


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


def unit_fracs(lines):
    """Each directory's fraction of a CL's lines, from the lines there (the
    landed commit's insertions, `units`): by lines, or equally where the
    landed commit inserted none."""
    s = sum(lines)
    return [x / s if s > 0 else 1 / len(lines) for x in lines]


def unit_order(units):
    """A CL's directories, most lines first (then by name): the order the
    half-year files list them in; the first takes the threads outside every
    unit (the commit message, files the landed commit didn't touch)."""
    return sorted(units.items(), key=lambda kv: (-kv[1], kv[0]))


def fr_row(c):
    """A CL as the rate measures need it. units: [(3-level directory,
    fraction of the CL's lines, addressed threads there, reviewer threads
    there)], in `unit_order`."""
    order = unit_order(c["units"])
    per = Counter(t[4] for t in c["thr"] if t[3])
    every = Counter(t[4] for t in c["thr"])
    fr_ = unit_fracs([x for _, x in order])
    return Row(c["pid"], c["closed_at"], c["lines"], c["prior"], xbin(c["prior"]), c["org"], c["addressed"],
               [(d, f, per[d], every[d]) for (d, _), f in zip(order, fr_)], order[0][0], tuple(c.get("revs", ())))


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
    """A person's growth rate: the % change in their AFR per doubling of changes
    landed, from a least-squares line through log2 AFR (floored at FR_FLOOR)
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
    """Per experience bin, every person's AFR there (MIN_BIN_CLS CLs or more)."""
    out = [[] for _ in BIN_LABELS]
    for rs in by_pid.values():
        for b, (n, a, lines) in person_cells(rs).items():
            if n >= MIN_BIN_CLS and lines > 0:
                out[b].append(fr(a, lines))
    return out


def fr_bins(by_pid):
    """The main chart: per experience bin, the spread of people's AFR there."""
    return [dict(n=len(xs), q=quantiles(xs) if len(xs) >= MIN_PEERS else None) for xs in bin_frs(by_pid)]


def dir_levels(d):
    """A 3-level directory and its parents, deepest first, then "" (all of them):
    where `peer_rate` looks for a rate."""
    p = [x for x in d.split("/") if x]
    return ["/".join(p[:k]) + "/" for k in range(min(3, len(p)), 0, -1)] + [""]


def cell_rate(rates, own, k, b, need=True):
    """The AFR of everyone's lines in directory `k` at experience bin `b`,
    without the person's own (`own`, from `rate_cells` of their rows), where
    that leaves MIN_RATE_CLS CLs' worth (always, without `need`). None where
    it doesn't, or nothing is left."""
    v = rates.get(k)
    x = v[b] if v else None
    if x is None:
        return None
    n, lines, a = x
    o = own.get(k) if own else None
    if o:
        n, lines, a = n - o[b][0], lines - o[b][1], a - o[b][2]
    return 100 * a / lines if (n >= MIN_RATE_CLS or not need) and lines > 0 else None


def peer_rate(rates, own, d, b):
    """For `method_compare`: the peers' AFR for lines in directory `d` at
    experience bin `b`, the person's own lines left out: the directory's
    pooled AFR over all the data, else its parent's, up to everyone's."""
    for k in dir_levels(d)[:-1]:
        v = cell_rate(rates, own, k, b)
        if v is not None:
            return v
    v = cell_rate(rates, own, "", b, need=False)
    return v if v is not None else 0.0


def rate_cells(rows):
    """{directory (3 levels, 2, 1, or "" for all): per experience bin, [CLs'
    worth, lines, addressed threads]}, each CL's lines and threads split over
    its directories by lines."""
    cells = defaultdict(lambda: [[0.0, 0.0, 0] for _ in BIN_LABELS])
    for r in rows:
        for d, f, a, _ in r.units:
            for k in dir_levels(d):
                x = cells[k][r.bin]
                x[0] += f
                x[1] += r.lines * f
                x[2] += a
    return cells


def rev_factor(r, f, none):
    """A CL's reviewer factor: the mean of its approvers' factors (`f`), in
    their order, or `none` for a CL without approvers."""
    return sum(f[v] for v in r.revs) / len(r.revs) if r.revs else none


def two_way(rows, base):
    """Author and reviewer factors fitted together: a CL is expected to draw
    base × its author's factor × its reviewers' mean factor addressed
    threads, so a reviewer's factor doesn't take on the authors they review,
    nor an author's the reviewers they pick. Each factor is (observed +
    FACTOR_SHRINK) / (expected + FACTOR_SHRINK) given the other; a CL with
    several approvers counts a share in each, and CLs without approvers form
    the group "". Returns ({author: factor}, {reviewer: factor})."""
    fa, fr_ = defaultdict(lambda: 1.0), defaultdict(lambda: 1.0)
    for _ in range(FACTOR_ITERS):
        obs, exp = defaultdict(float), defaultdict(float)
        for r, e in zip(rows, base):
            obs[r.pid] += r.addr
            exp[r.pid] += e * rev_factor(r, fr_, fr_[""])
        fa = defaultdict(lambda: 1.0, {p: (obs[p] + FACTOR_SHRINK) / (exp[p] + FACTOR_SHRINK) for p in obs})
        obs, exp = defaultdict(float), defaultdict(float)
        for r, e in zip(rows, base):
            vs = r.revs or ("",)
            for v in vs:
                obs[v] += r.addr / len(vs)
                exp[v] += e * fa[r.pid] / len(vs)
        fr_ = defaultdict(lambda: 1.0, {v: (obs[v] + FACTOR_SHRINK) / (exp[v] + FACTOR_SHRINK) for v in obs})
    return fa, fr_


def rate_model(rows):
    """What the feedback index compares with: everyone's pooled AFR per
    experience bin (`rate_bin`) times the CL's reviewer factor (its
    approvers' mean factor from `two_way`, `rev_factors`; CLs without
    approvers take `rev_none`). Factors are scaled so that, over all CLs,
    they leave the expected threads' total unchanged: 1.0 is the typical
    reviewer. A person's own CLs are compared with everyone else's: their
    rates and their reviewers' factors with the person's own CLs left out
    (`_own`, from `own_factors`). scale: multiplies the expected threads so
    that the median person's index (people with MIN_CLS CLs) is 1. ref_bin
    (the median AFR per experience bin, the main chart's line) and ref_all
    (everyone's median) are for the page's comparisons. All rounded, as the
    page uses them. rate_sums: per experience bin, [lines, addressed
    threads], from which the page takes away the person's own. Keys
    starting with "_" aren't published here: `_ue` holds each row's expected
    threads per unit before scaling, `_fa` the author factors, `_rev_cls`
    each reviewer's CLs, `_norm`, `_rev_sums` and `_own` are from
    `own_model` (the first two go in reviewers.json)."""
    by_pid = defaultdict(list)
    for r in rows:
        by_pid[r.pid].append(r)
    ref_bin = [median_or_none(xs) for xs in bin_frs(by_pid)]
    alls = []
    for rs in by_pid.values():
        lines = sum(r.lines for r in rs)
        if len(rs) >= MIN_CLS and lines > 0:
            alls.append(fr(sum(r.addr for r in rs), lines))
    cells = [[0, 0] for _ in BIN_LABELS]
    for r in rows:
        cells[r.bin][0] += r.lines
        cells[r.bin][1] += r.addr
    rate_bin = [r3(fr(a, lines)) if lines else 0.0 for lines, a in cells]
    base = [r.lines / 100 * rate_bin[r.bin] for r in rows]
    fa, raw = two_way(rows, base)
    # 1.0 is the typical reviewer: over all CLs the factors leave the total unchanged.
    norm = sum(e * rev_factor(r, raw, raw[""]) for r, e in zip(rows, base)) / sum(base)
    rev_none = r3(raw[""] / norm)
    rev_factors = {v: r3(x / norm) for v, x in raw.items() if v}
    rev_cls = Counter(v for r in rows for v in r.revs)
    norm = round(norm, 4)
    rate_sums = [[lines, a] for lines, a in cells]
    rev_sums, own = own_model(rows, rate_sums, rate_bin, rev_factors, rev_none, norm)
    ue = {}
    for r in rows:
        o = own[r.pid]
        g = rev_factor(r, o["f"], o["rev_none"])
        ue[id(r)] = [r.lines * f / 100 * o["rate_bin"][r.bin] * g for _, f, _, _ in r.units]
    m = dict(ref_bin=ref_bin, ref_all=r3(st.median(alls)), rate_bin=rate_bin, rate_sums=rate_sums,
             rev_none=rev_none, scale=1.0, _ue=ue, _fa=fa, _rev_factors=rev_factors, _rev_cls=rev_cls,
             _norm=norm, _rev_sums=rev_sums, _own=own)
    # Pooled rates aren't the typical person's (big CLs draw less per line),
    # so the expected threads are scaled to make the median person's index 1.
    xs = []
    for rs in by_pid.values():
        if len(rs) >= MIN_CLS:
            e = sum(expected(r, m) for r in rs)
            if e > 0:
                xs.append(sum(r.addr for r in rs) / e)
    m["scale"] = round(st.median(xs), 4)
    return m


def author_factor(rs, rate_bin, f, none, norm):
    """A person's author factor as the page can compute it from the
    published rates and factors: (their addressed threads + FACTOR_SHRINK)
    / (what experience and their reviewers expect + FACTOR_SHRINK), the
    factors unscaled (× norm), as in `two_way`."""
    e = sum(r.lines / 100 * rate_bin[r.bin] * rev_factor(r, f, none) * norm for r in rs)
    return (sum(r.addr for r in rs) + FACTOR_SHRINK) / (e + FACTOR_SHRINK)


def own_factors(rs, rate_sums, rate_bin, rev_sums, f, none, norm):
    """What one person's CLs (`rs`) are compared with, their own CLs left
    out: {rate_bin: everyone else's pooled AFR per experience bin
    (everyone's where only they have lines), f: {reviewer: factor} for the
    reviewers of their CLs, rev_none}. A reviewer's factor is `two_way`'s
    last step without the person's CLs: (observed - theirs +
    FACTOR_SHRINK) / (expected - theirs + FACTOR_SHRINK) / norm, from
    `rev_sums`, so a reviewer who approved only this person's CLs gets 1 /
    norm, the typical reviewer, and the person's CLs with them are compared
    by experience alone. The page computes the same from the published
    sums (`leaveOut` in web/src/feedback.ts); unrounded, like the page."""
    mine = [[0, 0] for _ in BIN_LABELS]
    for r in rs:
        mine[r.bin][0] += r.lines
        mine[r.bin][1] += r.addr
    rb = [fr(a - ma, lines - ml) if lines - ml > 0 else rate_bin[b]
          for b, ((lines, a), (ml, ma)) in enumerate(zip(rate_sums, mine))]
    fa = author_factor(rs, rate_bin, f, none, norm)
    pobs, pexp = defaultdict(float), defaultdict(float)
    for r in rs:
        vs = r.revs or ("",)
        for v in vs:
            pobs[v] += r.addr / len(vs)
            pexp[v] += r.lines / 100 * rate_bin[r.bin] * fa / len(vs)
    own = {}
    for v in pobs:
        o, e = rev_sums.get(v, (0, 0))
        own[v] = (max(o - pobs[v], 0) + FACTOR_SHRINK) / (max(e - pexp[v], 0) + FACTOR_SHRINK) / norm
    o, e = rev_sums[""]
    none_own = own.pop("", (o + FACTOR_SHRINK) / (e + FACTOR_SHRINK) / norm)
    return dict(rate_bin=rb, f=own, rev_none=none_own)


def own_model(rows, rate_sums, rate_bin, f, none, norm):
    """Each reviewer's observed and expected addressed threads (`two_way`'s
    last step, from the published rates and factors: each author's factor
    from `author_factor`), rounded as published in reviewers.json:
    {reviewer ("" for no approver): [observed, expected]}; and each
    person's comparison without their own CLs ({person: `own_factors`})."""
    by_pid = defaultdict(list)
    for r in rows:
        by_pid[r.pid].append(r)
    obs, exp = defaultdict(float), defaultdict(float)
    for rs in by_pid.values():
        fa = author_factor(rs, rate_bin, f, none, norm)
        for r in rs:
            vs = r.revs or ("",)
            for v in vs:
                obs[v] += r.addr / len(vs)
                exp[v] += r.lines / 100 * rate_bin[r.bin] * fa / len(vs)
    rev_sums = {v: [round(obs[v], 2), round(exp[v], 2)] for v in obs}
    rev_sums.setdefault("", [0, 0])
    return rev_sums, {p: own_factors(rs, rate_sums, rate_bin, rev_sums, f, none, norm) for p, rs in by_pid.items()}


def unit_expected(r, m):
    """The addressed threads each unit of a CL would draw: its lines / 100 ×
    everyone else's AFR at the CL's experience × the CL's reviewer factor
    from everyone else's CLs × the scale (the owner's CLs left out of both,
    `own_factors`)."""
    return [x * m["scale"] for x in m["_ue"][id(r)]]


def expected(r, m):
    """The addressed threads a CL would draw, given its experience and reviewers."""
    return sum(unit_expected(r, m))


def size_deviance(rows, ex):
    """Poisson deviance of each CL's addressed threads against `ex`, after a
    factor per size bucket (powers of two of lines) so that size, which no
    model here has, doesn't swamp the rest."""
    sb = [min(int(math.log2(max(r.lines, 1))), 10) for r in rows]
    oa, oe = defaultdict(float), defaultdict(float)
    for b, r, e in zip(sb, rows, ex):
        oa[b] += r.addr
        oe[b] += e
    d = 0.0
    for b, r, e in zip(sb, rows, ex):
        mu = max(e * oa[b] / oe[b], 1e-9) if oe[b] > 0 else 1e-9
        d += 2 * ((r.addr * math.log(r.addr / mu) if r.addr > 0 else 0) - (r.addr - mu))
    return d


def method_compare(rows):
    """The methodology's comparison of peer groups: how well each predicts the
    addressed threads other people's CLs drew. Every CL is predicted from
    other people's CLs (its owner's own left out of every rate and factor),
    and scored by `size_deviance`. Models: everyone's AFR by experience
    ("e"); by directory and experience ("d", MIN_RATE_CLS); "e" × the
    approvers' factor ("r"); "d" × the approvers' factor ("dr"); "d" × the
    approvers' factor per 2-level directory, shrunk toward their overall one
    ("rd"). Reviewer factors here are each reviewer's addressed threads over
    the model's expected on their CLs, without the owner's, shrunk toward 1
    with FACTOR_SHRINK. Returns [[model, deviance, % of "e"'s deviance
    removed], ...]."""
    by_pid = defaultdict(list)
    for r in rows:
        by_pid[r.pid].append(r)
    rates = {k: [[n, lines, a] for n, lines, a in v] for k, v in rate_cells(rows).items()}

    def unit_exp(dirs):
        out = {}
        for rs in by_pid.values():
            own = rate_cells(rs)
            memo = {}
            for r in rs:
                us = []
                for d, f, _, _ in r.units:
                    k = (d if dirs else "", r.bin)
                    if k not in memo:
                        memo[k] = peer_rate(rates, own, k[0], r.bin)
                    us.append(r.lines * f / 100 * memo[k])
                out[id(r)] = us
        return out

    def with_reviewers(ue, by_dir=False):
        o, e, op, ep = defaultdict(float), defaultdict(float), defaultdict(float), defaultdict(float)
        for r in rows:
            for v in r.revs:
                for (d, _, a, _), x in zip(r.units, ue[id(r)]):
                    for k in ((v,), (v, dir2(d))) if by_dir else ((v,),):
                        o[k] += a
                        e[k] += x
                        op[k + (r.pid,)] += a
                        ep[k + (r.pid,)] += x
        ex = []
        for r in rows:
            us = ue[id(r)]
            if not r.revs:
                ex.append(sum(us))
                continue
            tot = 0.0
            for v in r.revs:
                k = (v,)
                g = (o[k] - op[k + (r.pid,)] + FACTOR_SHRINK) / (e[k] - ep[k + (r.pid,)] + FACTOR_SHRINK)
                if by_dir:
                    for (d, _, _, _), x in zip(r.units, us):
                        kd = (v, dir2(d))
                        od, ed = o[kd] - op[kd + (r.pid,)], e[kd] - ep[kd + (r.pid,)]
                        tot += x * (od + 2 * FACTOR_SHRINK * g) / (ed + 2 * FACTOR_SHRINK)
                else:
                    tot += sum(us) * g
            ex.append(tot / len(r.revs))
        return ex

    ue_e, ue_d = unit_exp(False), unit_exp(True)
    devs = dict(e=size_deviance(rows, [sum(ue_e[id(r)]) for r in rows]),
                d=size_deviance(rows, [sum(ue_d[id(r)]) for r in rows]),
                r=size_deviance(rows, with_reviewers(ue_e)),
                dr=size_deviance(rows, with_reviewers(ue_d)),
                rd=size_deviance(rows, with_reviewers(ue_d, by_dir=True)))
    return [[k, round(v), round(100 * (1 - v / devs["e"]), 2)] for k, v in devs.items()]


def dir_reviewers(rows):
    """The methodology's view of reviewers within directories: for the
    CHART_DIRS 2-level directories with the most CLs (and MIN_PEERS reviewers
    there or more), [directory, its factor, reviewers, the 10th, 25th, 50th,
    75th and 90th percentiles of its reviewers' factors there]. A factor is
    addressed threads over what everyone's AFR by experience expects, not
    shrunk (a few expected threads shrunk toward 1 would lift reviewers in
    directories that draw almost nothing); a reviewer counts in a directory
    where their approved CLs there expect MIN_SPREAD_EXP threads or more (a
    CL with several approvers counts a share for each)."""
    cells = [[0, 0] for _ in BIN_LABELS]
    for r in rows:
        cells[r.bin][0] += r.lines
        cells[r.bin][1] += r.addr
    rate = [fr(a, lines) or 0 for lines, a in cells]
    od, ed, orv, erv, n = defaultdict(float), defaultdict(float), defaultdict(float), defaultdict(float), Counter()
    for r in rows:
        for d, f, a, _ in r.units:
            k = dir2(d)
            x = r.lines * f / 100 * rate[r.bin]
            od[k] += a
            ed[k] += x
            n[k] += f
            for v in r.revs:
                orv[(k, v)] += a / len(r.revs)
                erv[(k, v)] += x / len(r.revs)
    by_dir = defaultdict(list)
    for (k, v), e in erv.items():
        if e >= MIN_SPREAD_EXP:
            by_dir[k].append(orv[(k, v)] / e)
    out = []
    for k, _ in n.most_common():
        xs = by_dir.get(k, [])
        if len(xs) < MIN_PEERS:
            continue
        q = quantiles(xs)
        out.append([k, r3(od[k] / ed[k]), len(xs), [q[i] for i in (2, 5, 10, 15, 18)]])
        if len(out) == CHART_DIRS:
            break
    return out


def drift_series(rows, m):
    """Per half-year: [half-year, CLs, everyone's addressed threads over what
    experience and size expect, the same over what experience, size, the
    reviewers' factors and the authors' factors expect]. 1.0 is no drift;
    the second shows what is left once reviewers and authors are accounted
    for. Size is a factor per size bucket (powers of two of lines), fitted
    over all the data, so a few huge CLs don't swing a half-year."""
    sb = [min(int(math.log2(max(r.lines, 1))), 10) for r in rows]

    def sized(ex):
        oa, oe = defaultdict(float), defaultdict(float)
        for b, r, e in zip(sb, rows, ex):
            oa[b] += r.addr
            oe[b] += e
        return [e * oa[b] / oe[b] for b, e in zip(sb, ex)]
    base = [r.lines / 100 * m["rate_bin"][r.bin] for r in rows]
    full = sized([e * rev_factor(r, m["_rev_factors"], m["rev_none"]) * m["_fa"][r.pid] for r, e in zip(rows, base)])
    base = sized(base)
    acc = defaultdict(lambda: [0, 0, 0.0, 0.0])
    for r, e0, e1 in zip(rows, base, full):
        x = acc[half(r.at)]
        x[0] += 1
        x[1] += r.addr
        x[2] += e0
        x[3] += e1
    return [[h, n, r3(a / e0), r3(a / e1)] for h, (n, a, e0, e1) in sorted(acc.items())]


def dir_table(rows):
    """Everyone's directory table on the page: [path, kind, lines, reviewer
    threads, addressed threads(, entries)], each CL's lines and threads split
    over its directories by lines. Kind 0 is a directory (1, 2 or 3 levels)
    with MIN_DIR_CLS CLs or more whose parent is listed too; 1 the files
    directly in a listed directory that also has subdirectories ("rest of");
    2 the smaller entries under a listed directory, or "" for the top
    level, pooled into one "Other" row, with how many there are."""
    node = defaultdict(lambda: [0, 0.0, 0, 0])      # CLs, lines, threads, addressed
    own = defaultdict(lambda: [0.0, 0, 0])
    for r in rows:
        seen = set()
        for d, f, a, t in r.units:
            for k in dir_levels(d)[:-1]:
                x = node[k]
                if k not in seen:
                    seen.add(k)
                    x[0] += 1
                x[1] += r.lines * f
                x[2] += t
                x[3] += a
            o = own[d]
            o[0] += r.lines * f
            o[1] += t
            o[2] += a
    kids = defaultdict(list)
    for k in node:
        kids[dir_levels(k)[1]].append(k)
    out = []

    def walk(parent):
        small = [0.0, 0, 0, 0]
        for k in sorted(kids.get(parent, ()), key=lambda k: (-node[k][1], k)):
            n, lines, t, a = node[k]
            if n >= MIN_DIR_CLS:
                out.append([k, 0, round(lines), t, a])
                if kids.get(k) and own.get(k):
                    o = own[k]
                    out.append([k, 1, round(o[0]), o[1], o[2]])
                walk(k)
            else:
                small[0] += lines
                small[1] += t
                small[2] += a
                small[3] += 1
        if small[3]:
            out.append([parent, 2, round(small[0]), small[1], small[2], small[3]])
    walk("")
    return out


def cohorts(by_pid, first_year):
    """Per experience bin, per year of first commit on main from COHORT_FROM:
    [year, people, p10, p25, median, p75, p90] of the AFR over their CLs in
    that bin (MIN_BIN_CLS of them or more)."""
    ys = [defaultdict(list) for _ in BIN_LABELS]
    for pid, rs in by_pid.items():
        y = first_year.get(pid)
        if y is None or y < COHORT_FROM:
            continue
        cell = defaultdict(lambda: [0, 0, 0])
        for r in rs:
            x = cell[r.bin]
            x[0] += 1
            x[1] += r.addr
            x[2] += r.lines
        for b, (n, a, lines) in cell.items():
            if n >= MIN_BIN_CLS and lines > 0:
                ys[b][y].append(fr(a, lines))
    out = []
    for by_year in ys:
        rows = []
        for y in sorted(by_year):
            q = quantiles(by_year[y])
            rows.append([y, len(by_year[y])] + ([q[2], q[5], q[10], q[15], q[18]] if len(by_year[y]) >= MIN_PEERS else [None] * 5))
        out.append(rows)
    return out


def cell_medians(by_pid, key_of):
    """{key: (median of people's AFR, median of their addressed threads per CL,
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
    """Per size bucket (SIZE_LABELS): [median AFR, median addressed threads per CL, people]."""
    m = cell_medians(by_pid, lambda r: size10(r.lines))
    return [list(m.get(b, (None, None, 0))) for b in range(len(SIZE_LABELS))]


def by_dir(by_pid):
    """The CHART_DIRS two-level directories with the most people (each CL by
    its main directory), highest median AFR first: [directory, median AFR, people]."""
    m = cell_medians(by_pid, lambda r: dir2(r.main))
    top = sorted(m.items(), key=lambda kv: (-kv[1][2], kv[0]))[:CHART_DIRS]
    return [[k, v[0], v[2]] for k, v in sorted(top, key=lambda kv: (-kv[1][0], kv[0]))]


def by_org(by_pid):
    """The CHART_ORGS orgs with the most people: [org, median AFR, people], highest first."""
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
    ap.add_argument("--out", default=OUT, help="peers.json and reviewers.json (committed)")
    ap.add_argument("--people-out", help="the per-person files, published to R2 (default <data>/feedback-people)")
    ap.add_argument("--check", help="also write some people's per-period values here, to compare with the page's")
    ap.add_argument("--fi-dump", help="also write each person's index over all CLs and over their odd and even CLs "
                                      "(MIN_CLS CLs or more) here, to compare methods: their spread and split-half "
                                      "consistency (in data/private/scratch/)")
    args = ap.parse_args()

    cls, commits, ids, first, raw_email, by_cid = load(args)
    mech = C.left_out(git_db(), cls)       # mechanical and large-scale-change CLs
    # Every path under its name at main's tip, so a directory's history
    # follows it across renames (third_party/WebKit/Source is
    # third_party/blink/renderer).
    current = C.current_paths(git_db())
    print(f"{len(current):,} paths named as they are today", file=sys.stderr, flush=True)
    # A renamed file counts by the lines changed between its names, as
    # Gerrit's line counts (each CL's total) do, not as wholly new.
    moved = C.moved_lines(git_db())
    # Earlier commits per person, for experience (reverts left out).
    own_times = defaultdict(list)
    for c in commits:
        if not c["is_revert"]:
            own_times[c["pid"]].append(c["at"])
    # The per-CL window starts in 2017: earlier commits come from the rest of commits.sqlite.
    early = 0
    for email, at, _ in early_commits(current=current):
        if is_bot_email(person(email)):
            continue
        own_times[ids.find(email)].append(at)
        early += 1
    print(f"{early:,} human commits before {SINCE} counted as earlier commits", file=sys.stderr, flush=True)
    for v in own_times.values():
        v.sort()
    landed_at = {c["n"]: c["at"] for c in commits if c["n"]}
    emails_of = defaultdict(set)         # pid -> normalised addresses
    for c in commits:
        emails_of[c["pid"]].add(c["email"])
    for c in cls:
        if c["pid"]:
            emails_of[c["pid"]].add(c["owner_email"])
    del commits

    ddb = ro(os.path.join(store.DATA_DIR, store.DERIVED_FILE))
    bots = {a for a, in ddb.execute("SELECT account_id FROM accounts WHERE is_bot = 1")}

    # Merged, human-owned CLs, neither mechanical nor LSC (the review-ROI analyses' rule).
    for c in cls:
        if c["change_number"] in mech:
            c["status"] = "MECH"
    # Lines are insertions alone: deletions draw almost no addressed feedback
    # (docs/review-feedback.md, "Why deletions don't count"), so CLs that only
    # delete are left out.
    # Moved files count by the lines changed, not as new: Gerrit's counts
    # mostly do that already, and where they don't (Gerrit missed the move),
    # the landed commit's count with renamed files by their edits is the cap.
    # CLs that only move files are left out with those that only delete.
    cap = move_free_ins(git_db())
    for c in cls:
        n = c["change_number"]
        c["lines"] = min(c["ins"], cap[n]) if c["ins"] is not None and n in cap else c["ins"]
    use = [c for c in cls if c["status"] == "MERGED" and c["closed_at"] and c["pid"]
           and not is_bot_email(c["owner_email"]) and (c["lines"] or 0) > 0]
    del cap

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
    thr = defaultdict(list)          # change number -> [root, path, day, addressed, needs a label]
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
    del use_n, labels
    START, END = data_range(use)
    use = [c for c in use if START <= c["closed_at"] < END]
    by_n = {c["change_number"]: c for c in use}
    print(f"{len(use):,} CLs in range {day_str(START)} .. {day_str(END - DAY)}", file=sys.stderr, flush=True)

    # Each thread's file under today's name ("/COMMIT_MSG" for the commit
    # message); the landed commit's lines per 3-level directory, and per file
    # for the files that drew threads.
    want = defaultdict(dict)
    for n, ts in thr.items():
        if n in by_n:
            for t in ts:
                t[1] = current.get(t[1], t[1]) if t[1] and not t[1].startswith("/") else t[1] or "/COMMIT_MSG"
                if not t[1].startswith("/"):
                    want[n][t[1]] = None
    cl_dirs = defaultdict(dict)       # by CL, then directory
    for (n, d), (_, lines) in sorted(F.cl_dirs(git_db(), by_cid, by_n, dels=False, current=current,
                                               files=want, moved=moved).items()):
        cl_dirs[n][d] = lines
    # Each CL's reviewers: the approvers in its landed commit's Reviewed-by
    # trailers (those who voted Code-Review), as identities, the owner left out.
    for cid, rb in git_db().execute("SELECT commit_id, reviewed_by FROM commits "
                                    "WHERE commit_id > 0 AND reviewed_by IS NOT NULL"):
        c = by_n.get(by_cid.get(cid))
        if c is not None:
            c["revs"] = sorted({ids.find(e) for e in json.loads(rb)} - {c["pid"]})
    print(f"CLs with approvers: {sum(1 for c in use if c.get('revs')):,}", file=sys.stderr, flush=True)
    del by_cid, current, moved
    orgs = OrgResolver()
    for c in use:
        n = c["change_number"]
        day = datetime.fromtimestamp(c["closed_at"], timezone.utc).strftime("%Y-%m-%d")
        c["org"] = orgs(raw_email.get(n), day)
        c["units"] = cl_dirs.get(n) or {"(root)/": c["lines"]}
        c["main"] = unit_order(c["units"])[0][0]
        c["prior"] = bisect.bisect_left(own_times.get(c["pid"], ()), landed_at.get(n, c["closed_at"]))
        c["flines"] = want.get(n, {})
    del cl_dirs, want, own_times

    # Each thread goes to the directory of its file when the landed commit
    # changed lines there; commit-message threads and the rest to the CL's
    # main directory.
    need, have = defaultdict(int), defaultdict(int)      # week start -> threads needing a label, labelled
    for c in use:
        c["thr"] = []
        for root, path, at, addressed, needs_label in thr.get(c["change_number"], ()):
            if needs_label:
                w = monday(c["closed_at"])
                need[w] += 1
                have[w] += addressed is not None
            c["thr"].append([root, path, at, addressed, page_dir(path, c["units"], c["main"])])
    del thr
    print(f"threads: {sum(c['threads'] for c in use):,}", file=sys.stderr, flush=True)
    # The addressed measure covers only the CLs with labels.
    ADDR_START = trim_start(addressed_start(need, have, START, END))
    for c in use:
        c["acov"] = c["closed_at"] >= ADDR_START
    print(f"addressed from {day_str(ADDR_START)}", file=sys.stderr, flush=True)

    # ------------------------------------------------ AFR and index
    # Only the labelled CLs count (from ADDR_START, which is START once every
    # week is labelled): the AFR is addressed threads per 100 lines.
    people = defaultdict(list)
    for c in use:
        people[c["pid"]].append(c)
    rows = [fr_row(c) for c in use if c["acov"]]
    model = rate_model(rows)
    print(f"AFR by experience: " + " ".join(f"{l}={v}" for l, v in zip(BIN_LABELS, model["ref_bin"]))
          + f"; everyone {model['ref_all']}; scale {model['scale']}; {len(model['_rev_factors']):,} reviewers, "
          f"no approver {model['rev_none']}", file=sys.stderr, flush=True)
    method = method_compare(rows)
    print("peer groups (deviance, % removed): " + ", ".join(f"{k} {d:,} {p}%" for k, d, p in method),
          file=sys.stderr, flush=True)
    drift = drift_series(rows, model)
    print("drift (experience only, with reviewers and authors): "
          + " ".join(f"{h[2:]}:{a}/{b}" for h, _, a, b in drift), file=sys.stderr, flush=True)
    by_pid = defaultdict(list)
    for r in rows:
        by_pid[r.pid].append(r)
    allp = sorted({p for r in rows for p in periods_of(r.at)}, key=lambda p: (p != "all", p))
    fi_vals = defaultdict(list)
    growths = {}
    check_vals = {}
    dump = {}
    for pid, rs in by_pid.items():
        if args.fi_dump and len(rs) >= MIN_CLS:
            ex = [expected(r, model) for r in rs]

            def fi_of(ix):
                e = sum(ex[i] for i in ix)
                return sum(rs[i].addr for i in ix) / e if e > 0 else None
            order = sorted(range(len(rs)), key=lambda i: rs[i].at)
            dump[key(pid)] = [fi_of(order), fi_of(order[0::2]), fi_of(order[1::2]), len(rs)]
        byp = defaultdict(list)
        for r in rs:
            e = expected(r, model)
            for p in periods_of(r.at):
                byp[p].append((r, e))
        g = growth(person_cells(rs))
        if g is not None:
            growths[pid] = g
        vals = {}
        for p, pr in byp.items():
            n, a, lines = len(pr), sum(r.addr for r, _ in pr), sum(r.lines for r, _ in pr)
            e = sum(x for _, x in pr)
            if n >= MIN_CLS and e > 0:
                fi_vals[p].append(a / e)
            vals[p] = dict(cls=n, addressed=a, lines=lines, fr=r3(fr(a, lines)) if lines else None,
                           fi=r3(a / e) if e > 0 else None)
        if args.check and len(check_vals) < 300:
            check_vals[key(pid)] = dict(periods=vals, growth=g)

    if args.fi_dump:
        with open(args.fi_dump, "w") as f:
            json.dump(dump, f)
        del dump

    # ------------------------------------------------ peers
    dist = lambda xs: dict(n=len(xs), q=quantiles(xs) if len(xs) >= MIN_PEERS else None)
    first_year = {pid: datetime.fromtimestamp(t, timezone.utc).year for pid, t in first.items()}
    peers = dict(v=12, generated=datetime.now(timezone.utc).strftime("%Y-%m-%d"), periods=allp,
                 start=epoch_day(START), end=epoch_day(END), addr_start=epoch_day(ADDR_START),
                 min_peers=MIN_PEERS, min_cls=MIN_CLS, min_bin_cls=MIN_BIN_CLS, min_cell_cls=MIN_CELL_CLS,
                 min_growth_bins=MIN_GROWTH_BINS, fr_floor=FR_FLOOR, bins=BIN_LABELS, bin_edges=BIN_EDGES,
                 min_dir_cls=MIN_DIR_CLS, min_spread_exp=MIN_SPREAD_EXP,
                 **{k: v for k, v in model.items() if not k.startswith("_")},
                 method=method, dir_revs=dir_reviewers(rows), drift=drift,
                 dir_table=dir_table(rows), fr_bins=fr_bins(by_pid),
                 fi={p: dist(fi_vals.get(p, [])) for p in allp},
                 cohorts=cohorts(by_pid, first_year),
                 size_labels=SIZE_LABELS, by_size=by_size(by_pid), by_dir=by_dir(by_pid), by_org=by_org(by_pid),
                 growth=growth_dist(list(growths.values())), fi_dist=fi_dist(fi_vals.get("all", [])))
    q = peers["fi"]["all"]
    print(f"feedback index: {q['n']:,} people, quartiles "
          f"{[round(x, 2) for x in q['q'][5::5]] if q['q'] else None}", file=sys.stderr)
    gq = peers["growth"]
    print(f"growth per doubling: {gq['n']:,} people, median {gq['median']}%, "
          f"p10 {gq['q'][2]}% p90 {gq['q'][18]}%" if gq["q"] else "growth: none", file=sys.stderr)
    for b, crows in zip(BIN_LABELS, peers["cohorts"]):
        print(f"cohorts at {b}: " + " ".join(f"{y}={m}/{n}" for y, n, _, _, m, _, _ in crows), file=sys.stderr)
    print("by size: " + " ".join(f"{l} {v}" for l, v in zip(SIZE_LABELS, peers["by_size"])), file=sys.stderr)
    print("by directory: " + ", ".join(f"{d} {v}/{n}" for d, v, n in peers["by_dir"]), file=sys.stderr)
    print("by org: " + ", ".join(f"{d} {v}/{n}" for d, v, n in peers["by_org"]), file=sys.stderr, flush=True)

    # ------------------------------------------------ write
    # u/<key>.json.gz: who the person is and which half-years they have.
    # <half>/<key>.json.gz: that half-year's CLs, which later runs leave
    # byte for byte unchanged once the half-year is over, so the R2 sync
    # uploads them once.
    out = args.out
    if args.people_out is None:
        r2.hold()
    pout = args.people_out or r2.local_dir("feedback-people")
    os.makedirs(out, exist_ok=True)
    for name in os.listdir(out):       # per-person folders from before they moved to R2
        if name in ("u", "comments", "links") or HALF.match(name):
            shutil.rmtree(os.path.join(out, name))
    keep = set()
    with open(os.path.join(out, "peers.json"), "w") as f:
        json.dump(peers, f, separators=(",", ":"))
    # reviewers.json: each reviewer's factor, CLs approved, and observed and
    # expected addressed threads (from which the page takes away the
    # person's own: `own_factors`), by the first 12 hex digits of `key` of
    # their address, so the file lists no addresses; the page loads it with
    # a person and looks up their reviewers.
    revs = {}
    rs_ = model["_rev_sums"]
    for v, x in sorted(model["_rev_factors"].items()):
        k = key(v)[:12]
        if k in revs:
            print("reviewer key collision, kept the first", file=sys.stderr)
            continue
        revs[k] = [x, model["_rev_cls"][v], *rs_[v]]
    with open(os.path.join(out, "reviewers.json"), "w") as f:
        json.dump(dict(v=2, rev_none=model["rev_none"], none=rs_[""], norm=model["_norm"], shrink=FACTOR_SHRINK,
                       f=revs), f, separators=(",", ":"))
    written, stubs, size = 0, 0, 0
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
            p = os.path.join(pout, h, f"{k}.json.gz")
            size += r2.write_gz(p, json.dumps(shard(hcs), separators=(",", ":"), ensure_ascii=False))[0]
            keep.add(p)
        org = Counter(c["org"] for c in cs).most_common(1)
        top = dict(v=6, first=datetime.fromtimestamp(first[pid], timezone.utc).strftime("%Y-%m") if pid in first else None,
                   first_day=epoch_day(first[pid]) if pid in first else None, org=org[0][0] if org else None,
                   halves=sorted(by_half))
        p = os.path.join(pout, "u", f"{k}.json.gz")
        size += r2.write_gz(p, json.dumps(top, separators=(",", ":"), ensure_ascii=False))[0]
        keep.add(p)
        written += 1
    for pid in people:
        for e in emails_of.get(pid, ()):
            k = key(e)
            if k in taken:
                continue
            taken[k] = pid
            p = os.path.join(pout, "u", f"{k}.json.gz")
            r2.write_gz(p, json.dumps(dict(see=key(pid))))
            keep.add(p)
            stubs += 1
    removed = r2.prune(pout, keep)
    if args.check:
        with open(args.check, "w") as f:
            json.dump(check_vals, f)
    print(f"wrote {written:,} people ({size / 1e6:.1f} MB gzipped) and {stubs:,} other addresses to {pout}, "
          f"removed {removed:,} files", file=sys.stderr)


HALF = re.compile(r"^\d{4}H[12]$")


def page_dir(path, units, main):
    """A thread's directory, as the page works it out from its file: the
    file's 3-level directory when the landed commit changed lines there (one
    of `units`), else the CL's main directory."""
    dr = C.dir_of(path, 3) if path and not path.startswith("/") else None
    return dr if dr in units else main


def fb_files(c):
    """The files of a CL that drew reviewer threads, in name order: {path:
    [threads, addressed]}."""
    out = {}
    for _root, path, _at, addr, _ in c["thr"]:
        x = out.setdefault(path, [0, 0])
        x[0] += 1
        if addr:
            x[1] += 1
    return dict(sorted(out.items()))


def shard(cs):
    """One person's CLs of one half-year, oldest first, with directory and
    file names listed once (`dirs`, `files`). Each CL: [change number less
    the previous CL's (the first: itself), day landed less the previous
    CL's (the first: days since 1970), lines (Gerrit's insertions), the
    owner's earlier commits on main, units, reviewers(, files)].

    Units: the landed commit's inserted lines per 3-level directory, as
    [[directory, lines], ...] in `unit_order`, or the directory alone for a
    CL wholly in one directory. Reviewers: the approvers, as indexes in
    `revs` (their addresses), sorted by address; [] for none. Files: only those that drew reviewer threads,
    in name order, as [file, lines there (the landed commit's insertions; 0
    for the commit message or a file it didn't change), threads, addressed];
    left out when there are none. A file's threads count in its 3-level
    directory when that is one of the units, else in the first unit."""
    files, dirs, revs = {}, {}, {}

    def idx(table, x):
        return table.setdefault(x, len(table))
    rows = []
    pn = pd = 0
    for c in cs:
        n, d0 = c["change_number"], epoch_day(c["closed_at"])
        order = unit_order(c["units"])
        units = idx(dirs, order[0][0]) if len(order) == 1 else [[idx(dirs, d), x] for d, x in order]
        row = [n - pn, d0 - pd, c["lines"], c["prior"], units, [idx(revs, v) for v in c.get("revs", ())]]
        fb = fb_files(c)
        if fb:
            row.append([[idx(files, p), c["flines"].get(p) or 0, t, a] for p, (t, a) in fb.items()])
        rows.append(row)
        pn, pd = n, d0
    return dict(dirs=list(dirs), files=list(files), revs=list(revs), cls=rows)


if __name__ == "__main__":
    main()
