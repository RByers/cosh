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
                     (`reviewer_key`), so the committed file lists no one

and, gzipped, under --people-out (default data/private/feedback-people/,
which `python3 -m cosh.r2 publish` uploads to the R2 bucket, docs/r2.md):

  <name>.json.gz     per person, one file: first commit, usual org, when
                     they reached each experience bin, and per half-year
                     their lines, threads and addressed threads by
                     experience bin, directory and approvers
                     (`person_doc`, `half_cells`; no CLs, no comment ids or
                     text); for each other address of the same person,
                     {"see": name}

and, gzipped and private, <data>/feedback-cls.json.gz (--cls-out): each
person's CLs per half-year, with their approvers and the directory each
thread counts in (`cl_index`), from which cosh.review_threads writes the
comment files.

<name> is the address as typed, lower case (`file_name` below; the page
computes the same). No domains are merged: a person is an exact identity
(`people.exact_identities`), and each of their other addresses gets a
{"see": name} file. The bucket can't be listed, so a person is found only by typing their
address and the page offers no completions. Everything comes from public
Gerrit and git data.

  COSH_DATA_DIR=<main>/data/private nice -n 5 python3 -m cosh.review_feedback [--out DIR] [--people-out DIR]
"""

import argparse
import bisect
from array import array
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

from . import classify, memcap, r2, review_timeline, store
from . import commits as C
from . import cl_facts as F
from .cl_facts import SINCE, iter_cl_facts
from .orgs import OrgResolver
from .people import address, exact_identities, is_bot_email

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


FILE_SAFE = frozenset("abcdefghijklmnopqrstuvwxyz0123456789._@-")


def file_name(email):
    """The per-person file's name for an address (without .json.gz): the
    normalised address, each byte of any other character written as ~xx, so
    it is safe in a file name and a URL. The page computes the same
    (web/src/feedback.ts `personFile`)."""
    return "".join(c if c in FILE_SAFE else "".join(f"~{b:02x}" for b in c.encode())
                   for c in address(email))


def reviewer_key(email):
    """A reviewer's key in the committed reviewers.json: a salted hash of the
    normalised address, so the file in git lists no addresses. The page
    hashes the same way (web/src/feedback.ts `reviewerKey`)."""
    return hashlib.sha256((SALT + address(email)).encode()).hexdigest()[:12]


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
    first_cl = min(c.at for c in use)
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

def early_commits(before=SINCE):
    """Main's first-parent commits that landed before `before`, where
    the per-CL window starts (commit_id > 0 in commits.sqlite): [(author
    email, unix time landed)], reverts left out (`is_revert`: SVN-era
    reverts may name no sha). With them, earlier commits count from the
    start of main's history (2008), not from 2017."""
    cut = datetime.fromisoformat(before).replace(tzinfo=timezone.utc).timestamp()
    return git_db().execute("SELECT author_email, landed_at FROM commits WHERE landed_at < ? AND NOT is_revert "
                            "ORDER BY commit_id", (cut,)).fetchall()


def human_commit_times(db):
    """What the Feedback Index needs of `commits.human_commits` (the same
    commits, in the same order): (address, unix time landed, change number
    or None, is a revert)."""
    for email, at, n, bot, rv in db.execute("SELECT author_email, landed_at, change_number, is_bot, "
                                            "reverts_sha IS NOT NULL FROM commits WHERE commit_id > 0"):
        if not (bot or is_bot_email(email)):
            yield address(email), at, n, rv


class Cand:
    """A CL while it is being loaded, before it becomes a `Row`: change
    number, owner (identity), when it closed, Gerrit's insertions, the
    owner's address as Gerrit has it, when its commit landed, its approvers;
    then its directories in `unit_order` with their lines, and per directory
    its reviewer and addressed threads, and its threads' roots with the
    index of the directory each counts in."""
    __slots__ = ("n", "pid", "at", "ins", "raw", "landed", "revs", "dirs", "ulines",
                 "uthr", "uaddr", "roots", "rdir")

    def __init__(self, n, pid, at, ins, raw):
        self.n, self.pid, self.at, self.ins, self.raw = n, pid, at, ins, raw
        self.landed, self.revs, self.dirs = None, (), None


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

class Row:
    """A merged CL as every measure and file needs it. pid: its owner (an
    identity); at: when it closed; lines: the landed commit's inserted
    lines; prior: the owner's earlier commits; bin: `xbin(prior)`; org;
    addr: its addressed reviewer threads; units: [(3-level directory,
    fraction of the CL's lines, addressed threads there, reviewer threads
    there)] in `unit_order`; main: the first unit's directory; revs: its
    approvers (identities), sorted, () when it has none. For the per-person
    files also n (change number), ulines (each unit's lines), acov (in the
    addressed measure's range) and its threads: roots, and rdir, the index
    in units of the directory each counts in. ui: set by `rate_model`, where
    the CL's expected threads start in its `_ue`. Slots, not a dict, to keep
    the ~900k of them small (docs/review-feedback.md, "Memory")."""
    __slots__ = ("pid", "at", "lines", "prior", "bin", "org", "addr", "units", "main", "revs",
                 "n", "ulines", "acov", "roots", "rdir", "ui")

    def __init__(self, pid, at, lines, prior, bin, org, addr, units, main, revs=(), n=None, ulines=None,
                 acov=True, roots=(), rdir=()):
        self.pid, self.at, self.lines, self.prior, self.bin, self.org = pid, at, lines, prior, bin, org
        self.addr, self.units, self.main, self.revs = addr, units, main, revs
        self.n, self.ulines, self.acov, self.roots, self.rdir = n, ulines, acov, roots, rdir


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
    starting with "_" aren't published here: `_ue` holds every row's expected
    threads per unit before scaling, in one flat array (a row's start is
    its `ui`), `_fa` the author factors, `_rev_cls`
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
    ue = array("d")                  # every unit's expected threads, row after row (`unit_expected`)
    for r in rows:
        o = own[r.pid]
        g = rev_factor(r, o["f"], o["rev_none"])
        r.ui = len(ue)
        ue.extend(r.lines * f / 100 * o["rate_bin"][r.bin] * g for _, f, _, _ in r.units)
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
    return [x * m["scale"] for x in m["_ue"][r.ui:r.ui + len(r.units)]]


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
    by_pid = defaultdict(list)       # person -> indexes of their rows
    for i, r in enumerate(rows):
        by_pid[r.pid].append(i)
    rates = {k: [[n, lines, a] for n, lines, a in v] for k, v in rate_cells(rows).items()}
    # Each model's expected threads per unit sit in one flat array, row
    # after row: row i's units are at off[i]:off[i + 1].
    off = array("q", [0])
    for r in rows:
        off.append(off[-1] + len(r.units))

    def unit_exp(dirs):
        out = array("d", bytes(8 * off[-1]))
        for ix in by_pid.values():
            own = rate_cells([rows[i] for i in ix])
            memo = {}
            for i in ix:
                r = rows[i]
                for j, (d, f, _, _) in enumerate(r.units):
                    k = (d if dirs else "", r.bin)
                    if k not in memo:
                        memo[k] = peer_rate(rates, own, k[0], r.bin)
                    out[off[i] + j] = r.lines * f / 100 * memo[k]
        return out

    def with_reviewers(ue, by_dir=False):
        # Everyone's sums per reviewer (and directory), then one person at a
        # time: their own sums, taken away from everyone's for their rows.
        def keys(v, d):
            return ((v,), (v, dir2(d))) if by_dir else ((v,),)
        o, e = defaultdict(float), defaultdict(float)
        for i, r in enumerate(rows):
            for v in r.revs:
                for (d, _, a, _), x in zip(r.units, ue[off[i]:off[i + 1]]):
                    for k in keys(v, d):
                        o[k] += a
                        e[k] += x
        ex = array("d", bytes(8 * len(rows)))
        for ix in by_pid.values():
            op, ep = defaultdict(float), defaultdict(float)
            for i in ix:
                r = rows[i]
                for v in r.revs:
                    for (d, _, a, _), x in zip(r.units, ue[off[i]:off[i + 1]]):
                        for k in keys(v, d):
                            op[k] += a
                            ep[k] += x
            for i in ix:
                r = rows[i]
                us = ue[off[i]:off[i + 1]]
                if not r.revs:
                    ex[i] = sum(us)
                    continue
                tot = 0.0
                for v in r.revs:
                    k = (v,)
                    g = (o[k] - op[k] + FACTOR_SHRINK) / (e[k] - ep[k] + FACTOR_SHRINK)
                    if by_dir:
                        for (d, _, _, _), x in zip(r.units, us):
                            kd = (v, dir2(d))
                            od, ed = o[kd] - op[kd], e[kd] - ep[kd]
                            tot += x * (od + 2 * FACTOR_SHRINK * g) / (ed + 2 * FACTOR_SHRINK)
                    else:
                        tot += sum(us) * g
                ex[i] = tot / len(r.revs)
        return ex

    def totals(ue):
        return [sum(ue[off[i]:off[i + 1]]) for i in range(len(rows))]

    ue_e, ue_d = unit_exp(False), unit_exp(True)
    devs = dict(e=size_deviance(rows, totals(ue_e)),
                d=size_deviance(rows, totals(ue_d)),
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
    ap.add_argument("--cls-out", help="each person's CLs and their threads' directories, for cosh.review_threads "
                                      f"(private; default <data>/{CLS_INDEX})")
    ap.add_argument("--check", help="also write some people's per-period values here, to compare with the page's")
    ap.add_argument("--fi-dump", help="also write each person's index over all CLs and over their odd and even CLs "
                                      "(MIN_CLS CLs or more) here, to compare methods: their spread and split-half "
                                      "consistency (in data/private/scratch/)")
    args = ap.parse_args()

    # Over a GB while loading, so the process first joins the shared memory
    # budget (cosh.memcap), before it allocates any of it.
    memcap.join()
    ddb = ro(os.path.join(store.DATA_DIR, store.DERIVED_FILE))
    gdb = git_db()
    # Exact identities (people.exact_identities): addresses merge only on
    # evidence, never by domain, the same way as Review Load's.
    ids = exact_identities(ddb, gdb, ro(review_timeline.db_path()))
    emails_of = defaultdict(set)         # pid -> addresses (people.address)
    for pid, es in ids.groups().items():
        emails_of[pid] |= es
    # Merged, human-owned CLs that inserted lines (`Cand`), read one at a
    # time (cosh.cl_facts) so that only what they need stays in memory.
    # Lines are the landed commit's insertions (set below, with its lines per
    # directory): deletions draw almost no addressed feedback
    # (docs/review-feedback.md, "Why deletions don't count"), and renamed
    # files count by the lines changed between their names. CLs that only
    # delete or only move files are left out.
    facts, by_cid = iter_cl_facts(ddb, gdb)
    cands, big, n_cls = {}, [], 0
    for n, _, raw, status, _, closed, _, ins, _, _, sha, files, *_ in facts:
        n_cls += 1
        e = address(raw) if raw else None
        pid = ids.find(e) if e else None
        if pid:
            emails_of[pid].add(e)
        if status != "MERGED":
            continue
        if files is not None and files >= 10:     # may be mechanical (commits.mechanical)
            big.append(dict(change_number=n, status=status, sha=sha, files=files))
        if closed and pid and not is_bot_email(e) and (ins or 0) > 0:
            cands[n] = Cand(n, pid, closed, ins, raw)
    del facts
    # Neither mechanical nor LSC (the review-ROI analyses' rule).
    for n in C.left_out(gdb, big):
        cands.pop(n, None)
    del big
    # Earlier commits per person, for experience (reverts left out), and
    # when each CL's commit landed.
    own_times = defaultdict(list)
    n_commits = 0
    for e, at, n, rv in human_commit_times(gdb):
        n_commits += 1
        pid = ids.find(e)
        emails_of[pid].add(e)
        if not rv:
            own_times[pid].append(at)
        if n and n in cands:
            cands[n].landed = at
    first = {}
    for e, t in C.first_people(gdb, norm=address).items():
        k = ids.find(e)
        first[k] = min(t, first.get(k, t))
    print(f"loaded {n_cls:,} CLs, {n_commits:,} commits", file=sys.stderr, flush=True)
    # Every path under its name at main's tip, so a directory's history
    # follows it across renames (third_party/WebKit/Source is
    # third_party/blink/renderer).
    current = C.current_paths(gdb)
    print(f"{len(current):,} paths named as they are today", file=sys.stderr, flush=True)
    # A renamed file counts by the lines changed between its names, as
    # Gerrit's line counts (each CL's total) do, not as wholly new.
    moved = C.moved_lines(gdb)
    # The per-CL window starts in 2017: earlier commits come from the rest of commits.sqlite.
    early = 0
    for email, at in early_commits():
        if is_bot_email(address(email)):
            continue
        own_times[ids.find(email)].append(at)
        early += 1
    print(f"{early:,} human commits before {SINCE} counted as earlier commits", file=sys.stderr, flush=True)
    for v in own_times.values():
        v.sort()
    bots = {a for a, in ddb.execute("SELECT account_id FROM accounts WHERE is_bot = 1")}

    START, END = data_range(cands.values())
    by_n = {n: c for n, c in cands.items() if START <= c.at < END}      # in change-number order
    del cands
    print(f"{len(by_n):,} CLs in range {day_str(START)} .. {day_str(END - DAY)}", file=sys.stderr, flush=True)

    # The landed commit's lines per 3-level directory, under today's names.
    for (n, d), (_, lines) in F.cl_dirs(gdb, by_cid, by_n, dels=False, current=current, moved=moved).items():
        c = by_n[n]
        if c.dirs is None:
            c.dirs = {}
        c.dirs[d] = lines
    # Each CL's reviewers: the approvers in its landed commit's Reviewed-by
    # trailers (those who voted Code-Review), as identities, the owner left out.
    for cid, rb in gdb.execute("SELECT commit_id, reviewed_by FROM commits "
                               "WHERE commit_id > 0 AND reviewed_by IS NOT NULL"):
        c = by_n.get(by_cid.get(cid))
        if c is not None:
            c.revs = tuple(sorted({ids.find(e) for e in json.loads(rb)} - {c.pid}))
    print(f"CLs with approvers: {sum(1 for c in by_n.values() if c.revs):,}", file=sys.stderr, flush=True)
    del by_cid, moved
    for c in by_n.values():
        # Gerrit's count where the commit isn't known.
        order = unit_order(c.dirs or {"(root)/": c.ins})
        c.dirs, c.ulines = tuple(d for d, _ in order), tuple(x for _, x in order)
        c.uthr, c.uaddr, c.roots, c.rdir = [0] * len(order), [0] * len(order), [], []
    by_n = {n: c for n, c in by_n.items() if sum(c.ulines) > 0}

    # Reviewer threads: threads not started by a bot, on a file or the commit
    # message. Patch-set-level threads are left out: Gerrit has recorded
    # general comments as threads only since July 2020, they can't be tied to
    # a directory, and few lead to a change in the code. Each goes to the
    # directory of its file (under today's name) when the landed commit
    # changed lines there; commit-message threads and the rest to the CL's
    # main directory (`page_dir`). Addressed labels come from
    # addressed.sqlite, joined in SQLite rather than held in a dict.
    lpath = classify.labels_path(store.DATA_DIR)
    ldb = sqlite3.connect(f"file:{lpath}?mode=ro", uri=True)
    act = classify.active_classifier(ldb)
    ldb.close()
    ddb.execute("ATTACH DATABASE ? AS lab", (f"file:{lpath}?mode=ro",))
    need, have = defaultdict(int), defaultdict(int)      # week start -> threads needing a label, labelled
    n_thr = 0
    for n, root, replied, rx, acct, path, label in ddb.execute(
            "SELECT t.change_number, t.root_uuid, t.last_owner_reply_at IS NOT NULL, t.regex_addressed, "
            "t.root_account, c.path, l.addressed FROM threads t LEFT JOIN comments c ON c.host = t.host "
            "AND c.change_number = t.change_number AND c.comment_id = t.root_uuid "
            "LEFT JOIN lab.labels l ON l.change_number = t.change_number AND l.root_uuid = t.root_uuid "
            "AND l.classifier_id = ? AND l.input_hash = t.input_hash "
            "WHERE t.host = 'chromium-review.googlesource.com'", (act[0] if act else -1,)):
        if acct in bots or path == PATCHSET_LEVEL:
            continue
        c = by_n.get(n)
        if c is None:
            continue
        n_thr += 1
        addressed = 0 if not replied else 1 if rx else label
        path = current.get(path, path) if path and not path.startswith("/") else path or "/COMMIT_MSG"
        i = c.dirs.index(page_dir(path, c.dirs, c.dirs[0]))
        c.roots.append(root)
        c.rdir.append(i)
        c.uthr[i] += 1
        if addressed:
            c.uaddr[i] += 1
        if replied and not rx:
            w = monday(c.at)
            need[w] += 1
            have[w] += addressed is not None
    ddb.execute("DETACH DATABASE lab")
    del current
    print(f"threads: {n_thr:,}", file=sys.stderr, flush=True)
    # The addressed measure covers only the CLs with labels.
    ADDR_START = trim_start(addressed_start(need, have, START, END))
    print(f"addressed from {day_str(ADDR_START)}", file=sys.stderr, flush=True)

    # Each CL as a `Row`, the loading state dropped as it goes.
    orgs, names = OrgResolver(), {}
    use = []
    for n in list(by_n):
        c = by_n.pop(n)
        day = datetime.fromtimestamp(c.at, timezone.utc).strftime("%Y-%m-%d")
        org = orgs(c.raw, day)
        prior = bisect.bisect_left(own_times.get(c.pid, ()), c.landed if c.landed is not None else c.at)
        use.append(Row(c.pid, c.at, sum(c.ulines), prior, xbin(prior), names.setdefault(org, org), sum(c.uaddr),
                       tuple(zip(c.dirs, unit_fracs(c.ulines), c.uaddr, c.uthr)), c.dirs[0], c.revs,
                       n=c.n, ulines=c.ulines, acov=c.at >= ADDR_START, roots=tuple(c.roots), rdir=tuple(c.rdir)))
    del by_n, own_times

    # ------------------------------------------------ AFR and index
    # Only the labelled CLs count (from ADDR_START, which is START once every
    # week is labelled): the AFR is addressed threads per 100 lines.
    people = defaultdict(list)
    for r in use:
        people[r.pid].append(r)
    rows = [r for r in use if r.acov]
    del use
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
            dump[file_name(pid)] = [fi_of(order), fi_of(order[0::2]), fi_of(order[1::2]), len(rs)]
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
            check_vals[file_name(pid)] = dict(periods=vals, growth=g)

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
    # <name>.json.gz: who the person is and their CLs, one file per person
    # so the page makes one request. Each weekly run rewrites the files of
    # people with CLs in the current half-year; the R2 sync uploads only those.
    out = args.out
    if args.people_out is None:
        r2.hold()
    pout = args.people_out or r2.local_dir("feedback-people")
    cls_out = args.cls_out or os.path.join(store.DATA_DIR, CLS_INDEX)
    os.makedirs(out, exist_ok=True)
    for name in os.listdir(out):       # per-person folders from before they moved to R2
        if name in ("u", "comments", "links") or HALF.match(name):
            shutil.rmtree(os.path.join(out, name))
    keep = set()
    with open(os.path.join(out, "peers.json"), "w") as f:
        json.dump(peers, f, separators=(",", ":"))
    # reviewers.json: each reviewer's factor, CLs approved, and observed and
    # expected addressed threads (from which the page takes away the
    # person's own: `own_factors`), by `reviewer_key` of their address, so
    # the committed file lists no addresses; the page loads it with a
    # person and looks up their reviewers.
    revs = {}
    rs_ = model["_rev_sums"]
    for v, x in sorted(model["_rev_factors"].items()):
        k = reviewer_key(v)
        if k in revs:
            print("reviewer key collision, kept the first", file=sys.stderr)
            continue
        revs[k] = [x, model["_rev_cls"][v], *rs_[v]]
    with open(os.path.join(out, "reviewers.json"), "w") as f:
        json.dump(dict(v=2, rev_none=model["rev_none"], none=rs_[""], norm=model["_norm"], shrink=FACTOR_SHRINK,
                       f=revs), f, separators=(",", ":"))
    written, stubs, size = 0, 0, 0
    taken = {}
    index, idirs = {}, {}
    for pid, cs in people.items():
        k = file_name(pid)
        if k in taken:
            print("two people with one file name, skipped one", file=sys.stderr)
            continue
        taken[k] = pid
        cs.sort(key=lambda c: (c.at, c.n))
        org = Counter(c.org for c in cs).most_common(1)
        doc = person_doc(cs, first.get(pid), org[0][0] if org else None)
        p = os.path.join(pout, f"{k}.json.gz")
        size += r2.write_gz(p, json.dumps(doc, separators=(",", ":"), ensure_ascii=False))[0]
        keep.add(p)
        written += 1
        index[k] = cl_index(cs, idirs)
    for pid in people:
        for e in emails_of.get(pid, ()):
            k = file_name(e)
            if k in taken:
                continue
            taken[k] = pid
            p = os.path.join(pout, f"{k}.json.gz")
            r2.write_gz(p, json.dumps(dict(see=file_name(pid))))
            keep.add(p)
            stubs += 1
    removed = r2.prune(pout, keep)
    # The CLs behind each person's file, for cosh.review_threads (private).
    r2.write_gz(cls_out, json.dumps(dict(v=1, dirs=list(idirs), people=index), separators=(",", ":"),
                                    ensure_ascii=False))
    if args.check:
        with open(args.check, "w") as f:
            json.dump(check_vals, f)
    print(f"wrote {written:,} people ({size / 1e6:.1f} MB gzipped) and {stubs:,} other addresses to {pout}, "
          f"removed {removed:,} files", file=sys.stderr)


HALF = re.compile(r"^\d{4}H[12]$")
CLS_INDEX = "feedback-cls.json.gz"


def cl_index(cs, dirs):
    """One person's CLs for cosh.review_threads, by half-year: [[change
    number, approvers (as the person's file names them), {thread root:
    directory it counts in, as an index in `dirs`}], ...], oldest first. The
    page filters a reviewer's comments to a directory by these
    directories."""
    out = defaultdict(list)
    for c in cs:
        out[half(c.at)].append([c.n, list(c.revs),
                                {t: dirs.setdefault(c.units[i][0], len(dirs)) for t, i in zip(c.roots, c.rdir)}])
    return dict(out)


def page_dir(path, units, main):
    """A thread's directory, as the page works it out from its file: the
    file's 3-level directory when the landed commit changed lines there (one
    of `units`), else the CL's main directory."""
    dr = C.dir_of(path, 3) if path and not path.startswith("/") else None
    return dr if dr in units else main


def milli_fracs(lines):
    """`unit_fracs` in thousandths that add up to exactly 1,000 (largest
    remainders first), so a person's CLs add up to whole numbers however
    their cells are summed."""
    fr_ = unit_fracs(lines)
    base = [int(f * 1000) for f in fr_]
    left = 1000 - sum(base)
    for i in sorted(range(len(fr_)), key=lambda i: (base[i] - fr_[i] * 1000, i))[:left]:
        base[i] += 1
    return base


def half_cells(cs):
    """One person's labelled CLs of one half-year as cells, with directory
    and approver names listed once (`dirs`, `revs`, approvers sorted by
    address). A cell is every CL's share in one experience bin, 3-level
    directory and set of approvers: [bin, directory, [approvers], CLs in
    thousandths (each CL split over its directories by lines,
    `milli_fracs`), the landed commit's inserted lines there, reviewer
    threads there, addressed threads there]. A thread counts in its file's
    directory when the CL inserted lines there, else in the CL's main
    directory (`page_dir`). Cells are sorted, so the file stays the same
    when the CLs do."""
    dirs = sorted({u[0] for c in cs for u in c.units})
    revs = sorted({v for c in cs for v in c.revs})
    di, ri = {d: i for i, d in enumerate(dirs)}, {v: i for i, v in enumerate(revs)}
    agg = defaultdict(lambda: [0, 0, 0, 0])
    for c in cs:
        vs = tuple(sorted(ri[v] for v in c.revs))
        for (d, _, a, t), lines, m in zip(c.units, c.ulines, milli_fracs(list(c.ulines))):
            x = agg[(c.bin, di[d], vs)]
            x[0] += m
            x[1] += lines
            x[2] += t
            x[3] += a
    return dict(dirs=dirs, revs=revs, cells=[[b, d, list(vs), *x] for (b, d, vs), x in sorted(agg.items())])


def bins_reached(cs, first_day):
    """When the person reached each experience bin, as [day, exact] (null:
    no CL of theirs in it): the first bin on their first commit on main, the
    others when their first CL in the bin landed, exact when that CL was
    the bin's first commit (otherwise they got there by that day, through
    commits outside the data). `cs`: their CLs, oldest first."""
    out = [None] * len(BIN_LABELS)
    for c in cs:
        b = c.bin
        if out[b] is None:
            out[b] = ([first_day, True] if b == 0 and first_day is not None
                      else [epoch_day(c.at), c.prior == (BIN_EDGES[b - 1] if b else 0)])
    return out


def person_doc(cs, first_t, org):
    """One person's file: who they are, when they reached each experience
    bin, the days of their first and last labelled CL, and per half-year
    their labelled CLs as cells (`half_cells`). `cs`: all their CLs,
    oldest first."""
    first_day = epoch_day(first_t) if first_t is not None else None
    lab = [c for c in cs if c.acov]
    by_half = defaultdict(list)
    for c in lab:
        by_half[half(c.at)].append(c)
    return dict(v=8, first=datetime.fromtimestamp(first_t, timezone.utc).strftime("%Y-%m") if first_t is not None else None,
                first_day=first_day, org=org, reached=bins_reached(cs, first_day),
                days=[epoch_day(lab[0].at), epoch_day(lab[-1].at)] if lab else None,
                halves={h: half_cells(hcs) for h, hcs in sorted(by_half.items())})


if __name__ == "__main__":
    main()
