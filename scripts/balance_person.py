"""Private per-person balance reports (docs/balance-person.md).

For each person named, one self-contained HTML page comparing them with
peers of the same tenure in the same period, on the measures of the public
Review Balance page: authoring, reviewing, newcomer review, mentoring,
OWNERS, and (since mid-2023) feedback index, waits and rework on their CLs and
their own speed and thoroughness as a reviewer.

These pages name a person, so they are PRIVATE: they are written under
data/private/ and published only as private claude.ai artifacts. Nothing
here goes on the public site. Review tone is never included (ground rule 5).

  COSH_DATA_DIR=<main>/data/private python3 scripts/balance_person.py \\
      --first-commit F --owners-added F --ai-marked F --mech mech.jsonl \\
      --person blundell@chromium.org \\
      --person yoavweiss@chromium.org=yoav@yoav.ws,yoavweiss@google.com \\
      --out-dir <main>/data/private/balance_people

One load (about 1 minute and a few GB) serves every --person.
"""

import argparse
import html
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
import balance_report as R  # noqa: E402
from cosh import balance, store  # noqa: E402

YEAR = G.YEAR
DAY = 86400
NOW = datetime(2026, 11, 7, tzinfo=timezone.utc).timestamp()   # end of the git data used
YEARS = list(range(2017, 2027))
HALVES = [G.half(datetime(y, m, 15, tzinfo=timezone.utc).timestamp())
          for y in (2023, 2024, 2025, 2026) for m in (3, 9)][1:]      # 2023H2 .. 2026H2
BANDS = ["<2y", "2-5y", "5-10y", "10y+"]
BAND_NAME = {"<2y": "under 2 years", "2-5y": "2–5 years", "5-10y": "5–10 years", "10y+": "10+ years"}
MIN_AUTHOR_YEAR = 6        # commits + approvals in a year to count as an active peer
MIN_HALF_CLS = 5           # CLs in a half-year for author-side Gerrit measures
MIN_HALF_REVIEWS = 10      # CLs reviewed in a half-year for reviewer-side measures


def band(tenure):
    return None if tenure is None else "<2y" if tenure < 2 else "2-5y" if tenure < 5 else "5-10y" if tenure < 10 else "10y+"


def year_span(y):
    """Seconds of year y covered by the data (2026 runs to NOW)."""
    a = datetime(y, 1, 1, tzinfo=timezone.utc).timestamp()
    b = min(datetime(y + 1, 1, 1, tzinfo=timezone.utc).timestamp(), NOW)
    return max(1.0, b - a)


def months(y):
    return year_span(y) / (YEAR / 12)


def half_bounds(h):
    y, second = divmod(h, 2)
    a = datetime(y, 7 if second else 1, 1, tzinfo=timezone.utc).timestamp()
    b = datetime(y + 1, 1, 1, tzinfo=timezone.utc).timestamp() if second else datetime(y, 7, 1, tzinfo=timezone.utc).timestamp()
    return a, min(b, NOW)


def pcts(xs):
    xs = sorted(x for x in xs if x is not None and not (isinstance(x, float) and math.isnan(x)))
    if len(xs) < 10:
        return None
    q = lambda p: xs[min(len(xs) - 1, int(p * len(xs)))]
    return dict(p10=q(.1), p25=q(.25), p50=q(.5), p75=q(.75), p90=q(.9), n=len(xs))


def rank(xs, v):
    """Percentile of v among xs (0..100), or None."""
    xs = [x for x in xs if x is not None]
    if v is None or len(xs) < 10:
        return None
    below = sum(1 for x in xs if x < v) + 0.5 * sum(1 for x in xs if x == v)
    return round(100 * below / len(xs))


def med(xs):
    xs = [x for x in xs if x is not None]
    return st.median(xs) if xs else None


# ------------------------------------------------------------------ compute

def compute(args, people):
    cls, commits, ids, first, owner_at, ai = G.load_all(args)
    broad = {}
    if args.ai_broad and os.path.exists(args.ai_broad):
        for line in open(args.ai_broad):
            parts = line.split()
            if parts:
                broad[parts[0]] = parts[-1]
    for spec in people:                       # extra aliases the identity merge misses
        for a in spec["aliases"]:
            ids.union(spec["email"], a)
    # Re-resolve after the unions.
    for c in commits:
        c["pid"] = ids.find(c["email"])
        c["rbp"] = [ids.find(r) for r in c["rb"]]
    for c in cls:
        c["pid"] = ids.find(c["owner_email"]) if c["owner_email"] else None
    first2, owner2 = {}, {}
    for k, t in first.items():
        r = ids.find(k)
        first2[r] = min(t, first2.get(r, t))
    for k, t in owner_at.items():
        r = ids.find(k)
        owner2[r] = min(t, owner2.get(r, t))
    first, owner_at = first2, owner2
    tenure = lambda pid, t: (t - first[pid]) / YEAR if pid in first else None

    # ---- git, by calendar year
    authored = defaultdict(Counter)
    lines = defaultdict(lambda: defaultdict(list))
    dirs = defaultdict(lambda: defaultdict(set))
    given = defaultdict(Counter)
    given_new = defaultdict(Counter)
    ai_by = defaultdict(Counter)
    broad_by = defaultdict(Counter)
    dirs2 = A.commit_dirs(2)
    for c in commits:
        if not c["n"] or c["is_revert"]:
            continue
        y = A.year(c["at"])
        p = c["pid"]
        authored[p][y] += 1
        lines[p][y].append(c["lines"] or 0)
        d = dirs2.get(c["cid"])
        if d:
            dirs[p][y].add(d[0])
        if c["sha"] in ai:
            ai_by[p][y] += 1
        if c["sha"] in broad:
            broad_by[p][y] += 1
        newbie = tenure(p, c["at"]) is not None and tenure(p, c["at"]) < 1
        for r in set(c["rbp"]):
            if r != p:
                given[r][y] += 1
                given_new[r][y] += newbie
    regular_year = {p: min(y for y, n in g.items() if n >= 60) for p, g in given.items() if any(n >= 60 for n in g.values())}

    def git_metrics(p, y):
        a, g = authored[p][y], given[p][y]
        if a + g < MIN_AUTHOR_YEAR:
            return None
        m = months(y)
        return dict(commits=a / m, lines=med(lines[p][y]), approvals=g / m,
                    share=g / (a + g), newcomer=given_new[p][y] / m, dirs=len(dirs[p][y]))

    everyone = set(authored) | set(given)
    git_peers = {}           # (year, band) -> {metric: [values]}
    for y in YEARS:
        mid = datetime(y, 7, 1, tzinfo=timezone.utc).timestamp()
        for p in everyone:
            b = band(tenure(p, mid))
            if b is None:
                continue
            m = git_metrics(p, y)
            if not m:
                continue
            d = git_peers.setdefault((y, b), defaultdict(list))
            for k, v in m.items():
                d[k].append(v)

    # ---- mentorship: top-2 approvers of each person's first 10 CLs
    early = defaultdict(list)
    for c in sorted((c for c in commits if c["n"] and not c["is_revert"]), key=lambda c: c["at"]):
        if len(early[c["pid"]]) < 10:
            early[c["pid"]].append(c)
    mentees = defaultdict(list)
    for p, cs in early.items():
        if len(cs) < 5 or p not in first or A.year(first[p]) < 2017:
            continue
        cnt = Counter(r for c in cs for r in set(c["rbp"]) if r != p)
        for r, _ in cnt.most_common(2):
            mentees[r].append(p)

    # ---- Gerrit era: author side per half-year
    dirs3 = A.commit_dirs(3)
    top2 = {}
    for c in commits:
        d = dirs3.get(c["cid"])
        if c["n"] and d:
            top2[c["n"]] = "/".join(d[0].split("/")[:2])
    A.MECH_FILES = 10 ** 9
    mech = R.mech_set(args.mech)
    for c in cls:
        if c["change_number"] in mech:
            c["status"] = "MECH"
    use = G.cl_residuals(cls, top2)
    by_pid_half = defaultdict(list)
    for c in use:
        h = G.half(c["closed_at"])
        if h in HALVES:
            c["ftr"] = (c["first_review_at"] - c["sent_at"]) / 3600 \
                if c["first_review_at"] and c["sent_at"] and c["first_review_at"] >= c["sent_at"] else None
            by_pid_half[(c["pid"], h)].append(c)
    abandoned = Counter()
    for c in cls:
        if c["status"] == "ABANDONED" and c["closed_at"] and c["pid"] and c["first_review_at"]:
            h = G.half(c["closed_at"])
            if h in HALVES:
                abandoned[(c["pid"], h)] += 1

    def author_metrics(p, h):
        s = by_pid_half.get((p, h), [])
        if len(s) < MIN_HALF_CLS:
            return None
        rv = [c for c in s if c["first_review_at"]]
        idf = [c["lines_changed"] / c["lines_final"] for c in rv
               if c["interdiff_status"] == "ok" and c["lines_final"]]
        e = sum(c["exp24"] for c in s)
        return dict(cls=len(s), load=sum(c["threads"] for c in s) / e if e else None,
                    ftr=med([c["ftr"] for c in rv]), interdiff=med(idf),
                    rounds=st.mean(c["rounds"] or 0 for c in rv) if rv else None,
                    abandon=abandoned[(p, h)] / (abandoned[(p, h)] + len(rv)) if rv or abandoned[(p, h)] else None)

    author_peers = {}
    for (p, h) in list(by_pid_half):
        lo, hi = half_bounds(h)
        b = band(tenure(p, (lo + hi) / 2))
        m = author_metrics(p, h)
        if b and m:
            d = author_peers.setdefault((h, b), defaultdict(list))
            for k, v in m.items():
                d[k].append(v)

    # ---- Gerrit era: reviewer side per half-year (every reviewer, for peers)
    d = A.ro(os.path.join(store.DATA_DIR, store.DERIVED_FILE))
    emails = dict(d.execute("SELECT account_id, email FROM accounts"))
    bots = {a for a, in d.execute("SELECT account_id FROM accounts WHERE is_bot = 1")}
    acct_pid = {a: ids.find(e) for a, e in emails.items() if e and not A.is_bot_email(e)}
    cl_by_n = {c["change_number"]: c for c in use}
    first_c = {}
    for n, acct, at in d.execute("SELECT change_number, account_id, min(written_at) FROM comments "
                                 "WHERE after_close = 0 GROUP BY 1, 2"):
        if n in cl_by_n and acct not in bots and acct in acct_pid:
            first_c[(n, acct)] = balance.epoch(at)
    thr = Counter()
    for n, acct in d.execute("SELECT change_number, root_account FROM threads"):
        if n in cl_by_n:
            thr[(n, acct)] += 1
    tl = A.ro(balance.db_path("timeline"))
    added = {(n, a): s for n, a, s in tl.execute(
        "SELECT change_number, account_id, min(start_at) FROM attention GROUP BY 1, 2") if n in cl_by_n}
    rev = defaultdict(lambda: dict(cls=0, resp=[], threads=[], newcomer=0))
    for (n, acct), t0 in first_c.items():
        c = cl_by_n[n]
        if acct == c["owner"]:
            continue
        h = G.half(c["closed_at"])
        if h not in HALVES:
            continue
        x = rev[(acct_pid[acct], h)]
        x["cls"] += 1
        a = added.get((n, acct))
        if a and t0 >= a:
            x["resp"].append(balance.weekday_seconds(a, t0) / 3600)
        x["threads"].append(thr.get((n, acct), 0))
        ten = tenure(c["pid"], c["closed_at"])
        x["newcomer"] += ten is not None and ten < 1

    def reviewer_metrics(p, h):
        x = rev.get((p, h))
        if not x or x["cls"] < MIN_HALF_REVIEWS:
            return None
        lo, hi = half_bounds(h)
        return dict(reviewed=x["cls"] / ((hi - lo) / (YEAR / 12)), resp=med(x["resp"]),
                    threads=st.mean(x["threads"]), newcomer=x["newcomer"] / x["cls"])

    reviewer_peers = {}
    for (p, h) in list(rev):
        lo, hi = half_bounds(h)
        b = band(tenure(p, (lo + hi) / 2))
        m = reviewer_metrics(p, h)
        if b and m:
            dd = reviewer_peers.setdefault((h, b), defaultdict(list))
            for k, v in m.items():
                dd[k].append(v)

    # ---- clusters (optional, from scripts/balance_clusters.py)
    clusters = {}
    cpath = os.path.join(store.DATA_DIR, "balance_clusters", "people.json")
    if os.path.exists(cpath):
        try:
            clusters = json.load(open(cpath))
        except ValueError:
            clusters = {}

    # ---- per person
    out = []
    for spec in people:
        p = ids.find(spec["email"])
        if p not in first and not authored.get(p):
            print(f"{spec['email']}: no commits found", file=sys.stderr)
        rows_git = []
        for y in YEARS:
            mid = datetime(y, 7, 1, tzinfo=timezone.utc).timestamp()
            b = band(tenure(p, mid))
            m = git_metrics(p, y)
            peers = git_peers.get((y, b), {}) if b else {}
            rows_git.append(dict(period=str(y), band=b, me=m,
                                 peers={k: pcts(v) for k, v in peers.items()},
                                 rank={k: rank(peers.get(k, []), (m or {}).get(k)) for k in peers},
                                 raw=dict(authored=authored[p][y], approvals=given[p][y],
                                          newcomer=given_new[p][y], ai=ai_by[p][y], ai_broad=broad_by[p][y])))
        rows_half = []
        for h in HALVES:
            lo, hi = half_bounds(h)
            b = band(tenure(p, (lo + hi) / 2))
            am, rm = author_metrics(p, h), reviewer_metrics(p, h)
            ap = author_peers.get((h, b), {}) if b else {}
            rp = reviewer_peers.get((h, b), {}) if b else {}
            rows_half.append(dict(period=G.half_name(h), band=b, author=am, reviewer=rm,
                                  author_peers={k: pcts(v) for k, v in ap.items()},
                                  reviewer_peers={k: pcts(v) for k, v in rp.items()},
                                  author_rank={k: rank(ap.get(k, []), (am or {}).get(k)) for k in ap},
                                  reviewer_rank={k: rank(rp.get(k, []), (rm or {}).get(k)) for k in rp}))
        ms = mentees.get(p, [])
        mentee_rows = Counter(A.year(first[m]) for m in ms if m in first)
        out.append(dict(
            email=spec["email"], aliases=sorted({e for e, r in ids.p.items() if ids.find(e) == p} - {spec["email"]}),
            first=first.get(p), owner=owner_at.get(p), regular=regular_year.get(p),
            cohort=A.year(first[p]) if p in first else None,
            git=rows_git, half=rows_half,
            mentees=dict(total=len(ms), by_year=dict(sorted(mentee_rows.items())),
                         became_regular=sum(1 for m in ms if m in regular_year),
                         became_owner=sum(1 for m in ms if m in owner_at),
                         became_mentor=sum(1 for m in ms if mentees.get(m))),
            clusters=next((clusters[k] for k in [p, A.person(spec["email"])] +
                           sorted(e for e, rr in ids.p.items() if ids.find(e) == p) if k in clusters), None),
        ))
    return out


# ------------------------------------------------------------------- render

CSS = """
:root {
  /* Layout: one reading column; small-multiple charts in a two-up grid. */
  --bg: #f6f7f4; --panel: #ffffff; --fg: #1d221f; --muted: #5d665f; --line: #d9ddd6;
  --me: #1f6f5c; --peer: #7c8a83; --band: #c9d6cf; --band2: #e3ebe6; --warn: #8a5a00; --warn-bg: #fff4d6;
  --k0: #6f9fd8; --k1: #e39a5b; --k2: #73b98c; --k3: #b58bd1; --k4: #d6c35e; --k5: #d97f9a;
  --font-display: "Source Serif 4", Georgia, serif;
  --font-body: "IBM Plex Sans", system-ui, sans-serif;
  --font-data: "IBM Plex Mono", ui-monospace, monospace;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg: #121614; --panel: #1a201d; --fg: #e5ebe7; --muted: #9aa69f; --line: #2c3530;
  --me: #5fc7a8; --peer: #8f9c95; --band: #2f4a40; --band2: #22302a; --warn: #f2c25b; --warn-bg: #2d2412; --k0: #4f7fb8; --k1: #b8743a; --k2: #4f9468; --k3: #8d66a8; --k4: #a8963a; --k5: #b0607a; color-scheme: dark } }
:root[data-theme="dark"] {
  --bg: #121614; --panel: #1a201d; --fg: #e5ebe7; --muted: #9aa69f; --line: #2c3530;
  --me: #5fc7a8; --peer: #8f9c95; --band: #2f4a40; --band2: #22302a; --warn: #f2c25b; --warn-bg: #2d2412; --k0: #4f7fb8; --k1: #b8743a; --k2: #4f9468; --k3: #8d66a8; --k4: #a8963a; --k5: #b0607a; color-scheme: dark }
body { background: var(--bg); color: var(--fg); font-family: var(--font-body); font-size: 15px; line-height: 1.5;
  padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px));
  padding-block: 24px 48px; }
main { max-width: 64rem; margin: 0 auto; display: grid; gap: 28px; }
h1 { font-family: var(--font-display); font-weight: 600; font-size: 2rem; margin: 0; text-wrap: balance; }
h2 { font-family: var(--font-display); font-weight: 600; font-size: 1.35rem; margin: 0 0 4px; text-wrap: balance; }
h3 { font-size: 0.95rem; margin: 0 0 2px; }
p { margin: 0; max-width: 70ch; }
.muted, .note { color: var(--muted); }
.note { font-size: 0.85rem; }
.private { border: 1px solid var(--warn); background: var(--warn-bg); color: var(--fg); border-radius: 6px; padding: 10px 14px; font-size: 0.9rem; }
.private strong { color: var(--warn); }
.facts { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 11rem), 1fr)); gap: 10px; }
.fact { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px; display: grid; gap: 2px; }
.fact .k { font-size: 0.75rem; color: var(--muted); letter-spacing: 0.02em; text-transform: uppercase; }
.fact .v { font-family: var(--font-data); font-size: 1.05rem; font-variant-numeric: tabular-nums; }
section { display: grid; gap: 12px; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 22rem), 1fr)); gap: 14px; }
figure { margin: 0; background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 12px; min-width: 0; display: grid; gap: 6px; }
svg { width: 100%; height: auto; display: block; overflow: visible; }
svg text { fill: var(--muted); font-family: var(--font-data); font-size: 10px; }
.b1 { fill: var(--band2); } .b2 { fill: var(--band); }
.pm { stroke: var(--peer); stroke-width: 1.2; stroke-dasharray: 3 3; fill: none; }
.me { stroke: var(--me); stroke-width: 2.4; fill: none; } .med { fill: var(--me); }
.ax { stroke: var(--line); stroke-width: 1; }
.legend { display: flex; flex-wrap: wrap; gap: 4px 14px; font-size: 0.8rem; color: var(--muted); }
.legend i { display: inline-block; width: 14px; height: 8px; margin-right: 5px; vertical-align: middle; border-radius: 2px; }
.lg-me { background: var(--me); height: 3px !important; } .lg-b2 { background: var(--band); } .lg-b1 { background: var(--band2); }
.lg-pm { border-top: 1.5px dashed var(--peer); height: 0 !important; }
.tbl { overflow-x: auto; }
table { border-collapse: collapse; font-size: 0.82rem; font-variant-numeric: tabular-nums; min-width: 100%; }
th, td { padding: 4px 8px; border-bottom: 1px solid var(--line); text-align: right; white-space: nowrap; }
th:first-child, td:first-child { text-align: left; }
thead th { color: var(--muted); font-weight: 600; }
ul.sum { margin: 0; padding-left: 20px; display: grid; gap: 4px; max-width: 75ch; }
.strip { display: grid; grid-template-columns: repeat(auto-fill, minmax(2.6rem, 1fr)); gap: 3px; }
.strip-cell { height: 2.2rem; border-radius: 4px; display: flex; align-items: flex-end; justify-content: center; }
.strip-cell span { font-family: var(--font-data); font-size: 0.65rem; color: var(--fg); background: var(--panel); border-radius: 3px; padding: 0 3px; margin-bottom: 2px; }
.strip-cell.gap { background: var(--band2); }
.c0 { background: var(--k0); } .c1 { background: var(--k1); } .c2 { background: var(--k2); }
.c3 { background: var(--k3); } .c4 { background: var(--k4); } .c5 { background: var(--k5); }
.legend i.c0, .legend i.c1, .legend i.c2, .legend i.c3, .legend i.c4, .legend i.c5 { height: 10px; }
"""


def fnum(v, kind):
    if v is None:
        return "–"
    if kind == "pct":
        return f"{100 * v:.0f}%"
    if kind == "h":
        return f"{v:.1f} h"
    if kind == "x":
        return f"{v:.2f}×"
    if kind == "int":
        return f"{v:,.0f}"
    return f"{v:,.1f}" if abs(v) < 100 else f"{v:,.0f}"


def tick(v, kind):
    """An axis label: whole numbers without decimals."""
    if kind in ("n", "int") and abs(v - round(v)) < 1e-9:
        return f"{round(v):,}"
    if kind == "x" and abs(v * 4 - round(v * 4)) < 1e-9:
        return f"{v:g}×"
    return fnum(v, kind)


def chart(periods, peers, me, kind, w=420, h=170):
    """Peers' 10–90 and 25–75 percentile bands, their median dashed, and the
    person's line on top. peers: list of pcts dicts or None; me: values."""
    L, Rr, T, B = 44, 10, 8, 22
    vals = [v for v in me if v is not None] + [p["p90"] for p in peers if p]
    if not vals:
        return '<p class="note">Not enough activity to chart.</p>'
    top = max(vals) * 1.05 or 1
    if kind == "pct":
        top = min(top, 1.0)
    # A round tick step, four or five ticks.
    raw = top / 4
    mag = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1
    stepv = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    top = stepv * math.ceil(top / stepv - 1e-9)
    ticks = int(round(top / stepv))
    n = len(periods)
    x = lambda i: L + (w - L - Rr) * (i + 0.5) / n
    y = lambda v: T + (h - T - B) * (1 - min(v, top) / top)
    parts = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="Person against peers of the same tenure">']
    for k in range(ticks + 1):
        v = stepv * k
        parts.append(f'<line class="ax" x1="{L}" x2="{w - Rr}" y1="{y(v):.1f}" y2="{y(v):.1f}"/>'
                     f'<text x="{L - 4}" y="{y(v) + 3:.1f}" text-anchor="end">{html.escape(tick(v, kind))}</text>')
    step = max(1, math.ceil(n / 8))
    for i, p in enumerate(periods):
        if i % step == 0 or i == n - 1:
            parts.append(f'<text x="{x(i):.1f}" y="{h - 6}" text-anchor="middle">{html.escape(p)}</text>')

    def band_poly(lo, hi, cls):
        segs, cur = [], []
        for i, pp in enumerate(peers):
            if pp:
                cur.append((i, pp[lo], pp[hi]))
            elif cur:
                segs.append(cur)
                cur = []
        if cur:
            segs.append(cur)
        for s in segs:
            if len(s) == 1:
                i, a, b2 = s[0]
                parts.append(f'<rect class="{cls}" x="{x(i) - 6:.1f}" width="12" y="{y(b2):.1f}" height="{max(1, y(a) - y(b2)):.1f}"/>')
                continue
            pts = [f"{x(i):.1f},{y(b2):.1f}" for i, a, b2 in s] + [f"{x(i):.1f},{y(a):.1f}" for i, a, b2 in reversed(s)]
            parts.append(f'<polygon class="{cls}" points="{" ".join(pts)}"/>')
    band_poly("p10", "p90", "b1")
    band_poly("p25", "p75", "b2")
    pm = [f"{x(i):.1f},{y(pp['p50']):.1f}" for i, pp in enumerate(peers) if pp]
    if len(pm) > 1:
        parts.append(f'<polyline class="pm" points="{" ".join(pm)}"/>')
    run = []
    for i, v in enumerate(me + [None]):
        if v is not None:
            run.append((i, v))
        elif run:
            if len(run) > 1:
                parts.append(f'<polyline class="me" points="{" ".join(f"{x(j):.1f},{y(u):.1f}" for j, u in run)}"/>')
            run = []
    for i, v in enumerate(me):
        if v is not None:
            parts.append(f'<circle class="med" cx="{x(i):.1f}" cy="{y(v):.1f}" r="3"><title>{html.escape(periods[i])}: '
                         f'{html.escape(fnum(v, kind))}</title></circle>')
    parts.append("</svg>")
    return "".join(parts)


LEGEND = ('<div class="legend"><span><i class="lg-me"></i>This person</span><span><i class="lg-pm"></i>Peers\' median</span>'
          '<span><i class="lg-b2"></i>Peers\' middle half</span><span><i class="lg-b1"></i>Peers\' 10th–90th percentile</span></div>')


def fig(title, note, periods, peers, me, kind):
    return (f'<figure><h3>{html.escape(title)}</h3><p class="note">{html.escape(note)}</p>'
            f'{chart(periods, peers, me, kind)}</figure>')


def date(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%-d %b %Y") if t else "–"


def summary_points(r):
    """A few neutral, factual observations from the data."""
    pts = []
    g = [x for x in r["git"] if x["me"]]
    if g:
        last = g[-1]
        b = BAND_NAME.get(last["band"], "")
        for k, label in (("commits", "commits a month"), ("approvals", "approvals given a month"),
                         ("newcomer", "approvals of newcomers' CLs a month")):
            rk = last["rank"].get(k)
            if rk is not None:
                pts.append(f"In {last['period']}: {fnum(last['me'][k], 'n')} {label}, the {ordinal(rk)} percentile "
                           f"among active people with {b} tenure.")
        sh = [(x["period"], x["me"]["share"]) for x in g]
        if len(sh) >= 3:
            pts.append(f"Review share (approvals ÷ approvals + commits) went from {fnum(sh[0][1], 'pct')} in {sh[0][0]} "
                       f"to {fnum(sh[-1][1], 'pct')} in {sh[-1][0]}.")
    hs = [x for x in r["half"] if x["author"]]
    if hs:
        a = hs[-1]
        rk = a["author_rank"].get("load")
        if rk is not None and a["author"]["load"] is not None:
            pts.append(f"In {a['period']} their CLs drew a feedback index of {fnum(a['author']['load'], 'x')} "
                       f"(1.0 is the 2023–24 norm for the CL's size and directory), the {ordinal(rk)} percentile among peers.")
    rs = [x for x in r["half"] if x["reviewer"]]
    if rs:
        a = rs[-1]
        rk = a["reviewer_rank"].get("resp")
        if a["reviewer"]["resp"] is not None and rk is not None:
            pts.append(f"As a reviewer in {a['period']}: median first response {fnum(a['reviewer']['resp'], 'h')} (weekday hours), "
                       f"faster than {100 - rk}% of peers; {fnum(a['reviewer']['threads'], 'n')} threads per CL reviewed.")
    m = r["mentees"]
    if m["total"]:
        pts.append(f"Among the top two approvers of the first CLs of {m['total']} people who joined since 2017; "
                   f"{m['became_regular']} of them became regular reviewers and {m['became_owner']} OWNERS.")
    return pts


def ordinal(n):
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def render(r):
    periods_y = [x["period"] for x in r["git"]]
    periods_h = [x["period"] for x in r["half"]]
    gp = lambda k: [x["peers"].get(k) for x in r["git"]]
    gm = lambda k: [(x["me"] or {}).get(k) for x in r["git"]]
    ap = lambda k: [x["author_peers"].get(k) for x in r["half"]]
    am = lambda k: [(x["author"] or {}).get(k) for x in r["half"]]
    rp = lambda k: [x["reviewer_peers"].get(k) for x in r["half"]]
    rmm = lambda k: [(x["reviewer"] or {}).get(k) for x in r["half"]]
    name = r["email"]
    tenure_now = (NOW - r["first"]) / YEAR if r["first"] else None
    facts = [
        ("First commit on main", date(r["first"])),
        ("Tenure", f"{tenure_now:.1f} years" if tenure_now else "–"),
        ("First OWNERS file", date(r["owner"])),
        ("First year with 60+ approvals", str(r["regular"]) if r["regular"] else "–"),
        ("Newcomers mentored", str(r["mentees"]["total"])),
        ("AI-marked commits (broad)", str(sum(x["raw"]["ai_broad"] for x in r["git"]))),
    ]
    cl = r.get("clusters")
    cluster_html = ""
    if cl and cl.get("halves"):
        names = sorted({h.get("git_cluster") for h in cl["halves"].values() if h.get("git_cluster")})
        idx = {n: i for i, n in enumerate(names)}
        cells = "".join(
            f'<div class="strip-cell c{idx[h["git_cluster"]]}" title="{html.escape(k)}: {html.escape(h["git_cluster"])}">'
            f'<span>{html.escape(k[2:])}</span></div>' if h.get("git_cluster") else
            f'<div class="strip-cell gap" title="{html.escape(k)}: not active"><span>{html.escape(k[2:])}</span></div>'
            for k, h in sorted(cl["halves"].items()) if k >= "2017H1")
        key = "".join(f'<span><i class="c{idx[n]}"></i>{html.escape(n)}</span>' for n in names)
        cluster_html = (
            '<section><h2>Pattern over time</h2>'
            f'<p>Trajectory: <strong>{html.escape(cl.get("trajectory") or "–")}</strong>. Each cell is a half-year, '
            'coloured by the activity pattern that best fits it (docs/balance-clusters.md).</p>'
            f'<div class="strip">{cells}</div><div class="legend">{key}</div>'
            '<p class="note">Patterns are regions of a continuum found by clustering everyone\'s activity, scored '
            'against everyone active in the same half-year. They describe what someone did, not how well.</p></section>')
    rows = "".join(
        f"<tr><td>{x['period']}</td><td>{BAND_NAME.get(x['band'], '–')}</td><td>{x['raw']['authored']:,}</td>"
        f"<td>{x['raw']['approvals']:,}</td><td>{x['raw']['newcomer']:,}</td>"
        f"<td>{fnum((x['me'] or {}).get('share'), 'pct')}</td><td>{x['rank'].get('commits') if x['me'] else '–'}</td>"
        f"<td>{x['rank'].get('approvals') if x['me'] else '–'}</td><td>{x['raw']['ai_broad']}</td></tr>" for x in r["git"])
    pts = "".join(f"<li>{html.escape(p)}</li>" for p in summary_points(r))
    return f"""<title>{html.escape(name.split("@")[0])} review profile</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;600&family=Source+Serif+4:opsz,wght@8..60,600&display=swap">
<style>{CSS}</style>
<main>
  <header style="display:grid;gap:10px">
    <p class="note">Chromium review balance · individual profile</p>
    <h1>{html.escape(name)}</h1>
    <p class="muted">Also as: {html.escape(", ".join(r["aliases"]) or "no other addresses")}</p>
    <div class="private"><strong>Private.</strong> This profile names one person and compares them with peers. It is not
      part of the public dashboard and should not be shared without their consent. Peers are everyone active in the same
      period with the same tenure band; percentiles describe activity, not quality or worth.</div>
  </header>
  <section class="facts">{"".join(f'<div class="fact"><span class="k">{html.escape(k)}</span><span class="v">{html.escape(v)}</span></div>' for k, v in facts)}</section>
  <section><h2>In brief</h2><ul class="sum">{pts}</ul></section>
  {cluster_html}
  <section>
    <h2>Authoring and reviewing, 2017–2026</h2>
    <p class="note">From chromium/src git history: commits with a CL, and approvals from Reviewed-by footers. Rates are per
      month of the year covered (2026 runs to early November). Peers: people with 6+ commits and approvals that year in the
      same tenure band.</p>
    {LEGEND}
    <div class="grid">
      {fig("Commits per month", "Commits landed, per month.", periods_y, gp("commits"), gm("commits"), "n")}
      {fig("Approvals given per month", "Others' CLs approved, per month.", periods_y, gp("approvals"), gm("approvals"), "n")}
      {fig("Review share", "Approvals ÷ (approvals + commits).", periods_y, gp("share"), gm("share"), "pct")}
      {fig("Approvals of newcomers' CLs per month", "CLs by authors in their first year.", periods_y, gp("newcomer"), gm("newcomer"), "n")}
      {fig("Median lines per commit", "Changed lines.", periods_y, gp("lines"), gm("lines"), "n")}
      {fig("Directories touched", "Distinct 2-level directories committed to in the year.", periods_y, gp("dirs"), gm("dirs"), "n")}
    </div>
  </section>
  <section>
    <h2>Since mid-2023: their CLs in review</h2>
    <p class="note">From Gerrit, per half-year, for merged non-mechanical CLs they owned (5+ in the half-year). Peers: owners
      in the same tenure band.</p>
    {LEGEND}
    <div class="grid">
      {fig("Feedback index", "Reviewer threads ÷ the 2023–24 average for the CL's size and directory.", periods_h, ap("load"), am("load"), "x")}
      {fig("Hours to first substantive review", "Median, clock hours.", periods_h, ap("ftr"), am("ftr"), "h")}
      {fig("Lines changed after first review", "Median share per reviewed CL.", periods_h, ap("interdiff"), am("interdiff"), "pct")}
      {fig("Abandoned after review", "Share of their reviewed CLs abandoned.", periods_h, ap("abandon"), am("abandon"), "pct")}
    </div>
  </section>
  <section>
    <h2>Since mid-2023: as a reviewer</h2>
    <p class="note">Others' CLs they commented on (10+ in the half-year). Response: weekday hours from being added to the
      attention set to their first comment. Peers: reviewers in the same tenure band.</p>
    {LEGEND}
    <div class="grid">
      {fig("CLs reviewed per month", "Others' merged CLs they commented on.", periods_h, rp("reviewed"), rmm("reviewed"), "n")}
      {fig("Median first response", "Weekday hours.", periods_h, rp("resp"), rmm("resp"), "h")}
      {fig("Threads per CL reviewed", "Review threads they started.", periods_h, rp("threads"), rmm("threads"), "n")}
      {fig("Newcomer share of their reviews", "CLs whose author was in their first year.", periods_h, rp("newcomer"), rmm("newcomer"), "pct")}
    </div>
  </section>
  <section>
    <h2>Year by year</h2>
    <div class="tbl"><table><thead><tr><th>Year</th><th>Tenure band</th><th>Commits</th><th>Approvals</th><th>Of newcomers</th>
      <th>Review share</th><th>Commits pctile</th><th>Approvals pctile</th><th>AI-marked</th></tr></thead><tbody>{rows}</tbody></table></div>
    <p class="note">Mentoring: among the top two approvers of the first ten CLs of {r["mentees"]["total"]} people who joined
      since 2017 (by start year: {html.escape(", ".join(f"{k}: {v}" for k, v in r["mentees"]["by_year"].items()) or "none")});
      {r["mentees"]["became_regular"]} became regular reviewers, {r["mentees"]["became_owner"]} were added to OWNERS and
      {r["mentees"]["became_mentor"]} went on to mentor others.</p>
  </section>
  <section>
    <h2>How this is made</h2>
    <p class="note">scripts/balance_person.py, from public Chromium Gerrit and git data (docs/balance-person.md). Measures and
      definitions follow the public Review Balance page. Identity merges a person's addresses across domains and the Gerrit
      owner and git author of the same CL; extra aliases were given by hand. Generated {datetime.now(timezone.utc):%-d %b %Y}.</p>
  </section>
</main>
"""


def rerender(out_dir):
    """Rebuild every page from its saved JSON (no data load)."""
    for f in sorted(os.listdir(out_dir)):
        if f.endswith(".json"):
            r = json.load(open(os.path.join(out_dir, f)))
            open(os.path.join(out_dir, f[:-5] + ".html"), "w").write(render(r))


def main():
    if sys.argv[1:2] == ["--rerender"]:
        rerender(sys.argv[2] if len(sys.argv) > 2 else os.path.join(store.DATA_DIR, "balance_people"))
        return
    ap = argparse.ArgumentParser()
    S = os.environ.get("BALANCE_SCRATCH", ".")
    ap.add_argument("--first-commit", default=os.path.join(S, "first_commit.txt"))
    ap.add_argument("--owners-added", default=os.path.join(S, "owners_added.txt"))
    ap.add_argument("--ai-marked", default=os.path.join(S, "ai_marked.txt"))
    ap.add_argument("--ai-broad", default=os.path.join(store.DATA_DIR, "ai_marked_broad.txt"))
    ap.add_argument("--mech", default=os.path.join(S, "mech.jsonl"))
    ap.add_argument("--person", action="append", required=True,
                    help="email, optionally =alias,alias for addresses the identity merge misses")
    ap.add_argument("--out-dir", default=os.path.join(store.DATA_DIR, "balance_people"))
    args = ap.parse_args()
    people = []
    for s in args.person:
        e, _, al = s.partition("=")
        people.append(dict(email=e.lower(), aliases=[a.lower() for a in al.split(",") if a]))
    os.makedirs(args.out_dir, exist_ok=True)
    for r in compute(args, people):
        base = os.path.join(args.out_dir, r["email"].split("@")[0])
        json.dump(r, open(base + ".json", "w"), indent=1, default=str)
        open(base + ".html", "w").write(render(r))
        print(f"wrote {base}.html", file=sys.stderr)


if __name__ == "__main__":
    main()
