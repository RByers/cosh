"""Review Timezones: how working-hours overlap between authors and reviewers
shapes the wait authors see, and which OWNERS directories lack an owner in
their authors' hours (docs/review-timezones.md).

  nice -n 5 python3 -m cosh.review_timezones [--out web/public/review-timezones]

Reads commits.sqlite (which CLs landed as reviewed commits, and their lines
per file), reviews.sqlite (CL owners, accounts), review-timeline.sqlite
(cl_turns with their working hours, work_windows) and the OWNERS files in
the shared clone at the end of the last quarter shown. Writes all.json,
which holds only aggregates: no file names a person or their hours.
"""

import argparse
import json
import os
import sqlite3
from collections import Counter, defaultdict

from . import commits as C
from . import data_span, owners, review_timeline, store
from . import review_load as RL
from . import work_hours as WH
from .people import exact_identities

OUT = os.path.join(RL.ROOT, "web", "public", "review-timezones")
QUARTERS = 4                      # the last whole quarters shown
MIN_DIR_TURNS = 400               # an OWNERS directory is listed with this many turns in them
MIN_GROUP_TURNS = 30              # a directory's covered or uncovered turns need this many for a median
COVER_H = 4                       # an author is covered by an owner whose window shares this many hours with theirs
OVERLAP_BINS = ((0, 0), (1, 2), (3, 4), (5, 6), (7, 8))


def pcts(xs):
    """[10th, 25th, 50th, 75th, 90th percentile] of xs, rounded, and their count."""
    s = RL.spread([xs])
    return [s[k][0] for k in ("p10", "p25", "p50", "p75", "p90")], len(xs)


def median(xs):
    xs = sorted(xs)
    return round(xs[len(xs) // 2], 2) if xs else None


def owners_dir(own, d):
    """The nearest directory at or above `d` ("a/b", "" for the root) with an OWNERS file."""
    while d and d not in own.direct:
        d = os.path.dirname(d)
    return d


def file_dir_lines(gdb, cids):
    """{commit_id: {file's directory (today's name): lines}} of the commits in `cids`."""
    current, moved = C.current_paths(gdb), C.moved_lines(gdb)
    path_dir = {}
    out = defaultdict(lambda: defaultdict(int))
    for cid, pid, ins, dels in gdb.execute("SELECT commit_id, path_id, ins, dels FROM commit_files WHERE commit_id > 0"):
        if cid in cids:
            if pid not in path_dir:
                path, = gdb.execute("SELECT path FROM paths WHERE path_id = ?", (pid,)).fetchone()
                path_dir[pid] = os.path.dirname(current.get(path, path))
            ins, dels = moved.get((cid, pid), (ins, dels))
            out[cid][path_dir[pid]] += max(ins, 0) + max(dels, 0)
    return out


def owner_windows(own, ddb, tdb, ids, last_q):
    """{OWNERS directory: [window start of each owner listed in it who was active in `last_q`]}:
    the addresses in the directory's own OWNERS file (and the files it includes), not those
    inherited from above; an owner is active with a window fitted to that quarter."""
    acct_person = {a: ids.find(e) for a, e in ddb.execute("SELECT account_id, email FROM accounts") if e}
    best = {}                                   # person -> (events, start) of their busiest account
    for a, start, events in tdb.execute(
            "SELECT account_id, start_h, events FROM work_windows WHERE quarter = ? AND basis = 'quarter'", (last_q,)):
        p = acct_person.get(a)
        if p is not None and events > best.get(p, (0, None))[0]:
            best[p] = (events, start)
    return {d: [best[p][1] for p in {ids.find(e) for e in addrs} if p in best]
            for d, (addrs, _, _) in own.direct.items()}


def compute(gdb, ddb, tdb, owners_at):
    end = RL.data_end(ddb, gdb)
    last = RL.last_whole_quarter(end)
    qs = RL.quarters(RL.FIRST_QUARTER, last)[-QUARTERS:]
    if len(qs) < QUARTERS or qs[0] < RL.ATTENTION_FROM:
        raise SystemExit(f"need {QUARTERS} whole quarters from {RL.ATTENTION_FROM} (data ends {RL.quarter(end)})")
    lo, hi = RL.quarter_start(qs[0]), RL.quarter_start(RL.next_quarter(last))
    ids = exact_identities(ddb, gdb, tdb)
    _, reviewed = RL.load_commits(gdb, lo, hi, ids)
    by_cl = {c["n"]: cid for cid, c in reviewed.items() if c["n"] is not None}
    print(f"review-timezones: {qs[0]}..{last}, {len(reviewed):,} reviewed commits", flush=True)
    sha, = gdb.execute("SELECT sha FROM commits WHERE landed_at < ? ORDER BY landed_at DESC LIMIT 1", (hi,)).fetchone()
    own = owners_at(sha)
    lines = file_dir_lines(gdb, set(reviewed))
    cl_dir = {}
    for n, cid in by_cl.items():
        per = Counter()
        for d, ln in lines.get(cid, {}).items():
            per[owners_dir(own, d)] += ln
        if per:
            cl_dir[n] = per.most_common(1)[0][0]
    merged = {n: o for n, o in ddb.execute(
        "SELECT change_number, owner_account FROM changes WHERE status = 'MERGED' AND is_bot_owned = 0") if n in by_cl}
    win = defaultdict(dict)                     # quarter -> account -> window start
    for a, q, s in tdb.execute("SELECT account_id, quarter, start_h FROM work_windows WHERE quarter <= ?", (last,)):
        win[q][a] = s
    owner_win = owner_windows(own, ddb, tdb, ids, last)

    by_overlap = [[] for _ in OVERLAP_BINS]
    pair = defaultdict(list)                    # (author region, reviewer region) -> waits
    dirs = defaultdict(lambda: ([], [], Counter()))     # dir -> (covered waits, uncovered waits, uncovered regions)
    for n, acct, s, wait in tdb.execute("SELECT change_number, account_id, start_at, owner_work_h FROM cl_turns"):
        if n not in merged or wait is None:
            continue
        w = win.get(WH.quarter(s), {})
        ow = w.get(merged[n])
        rw = w.get(acct, ow)
        if ow is None:
            continue
        ov = WH.overlap_h(ow, rw)
        by_overlap[next(i for i, (a, b) in enumerate(OVERLAP_BINS) if a <= ov <= b)].append(wait)
        pair[WH.region(ow), WH.region(rw)].append(wait)
        d = cl_dir.get(n)
        if d is not None:
            covered = any(WH.overlap_h(ow, o) >= COVER_H for o in owner_win.get(d, ()))
            g = dirs[d]
            g[0 if covered else 1].append(wait)
            if not covered:
                g[2][WH.region(ow)] += 1
    total = sum(len(x) for x in by_overlap)
    overlap = []
    for (a, b), xs in zip(OVERLAP_BINS, by_overlap):
        p, k = pcts(xs)
        overlap.append(dict(lo=a, hi=b, n=k, p=p))
    regions = {}
    for ar in WH.REGIONS:
        n_a = sum(len(pair[ar, rr]) for rr in WH.REGIONS)
        regions[ar] = dict(n=n_a, wait=pcts([x for rr in WH.REGIONS for x in pair[ar, rr]])[0][2],
                           by=[[len(pair[ar, rr]), median(pair[ar, rr])] for rr in WH.REGIONS])
    bots = {a for (a,) in ddb.execute("SELECT account_id FROM accounts WHERE is_bot = 1")}
    people = Counter(WH.region(s) for a, s in tdb.execute(
        "SELECT account_id, start_h FROM work_windows WHERE quarter = ? AND basis = 'quarter'", (last,)) if a not in bots)
    rows = []
    for d, (cov, unc, reg) in dirs.items():
        n = len(cov) + len(unc)
        if n < MIN_DIR_TURNS:
            continue
        oreg = Counter(WH.region(s) for s in owner_win.get(d, ()))
        mc, mu = (median(x) if len(x) >= MIN_GROUP_TURNS else None for x in (cov, unc))
        extra = round(len(unc) * (mu - mc)) if mc is not None and mu is not None and mu > mc else 0
        rows.append(dict(d=d + "/" if d else "/", n=n, listed=len(own.direct[d][0]),
                         owners=[oreg[r] for r in WH.REGIONS], unc=len(unc),
                         reg=reg.most_common(1)[0][0] if reg else None, mu=mu, mc=mc, extra=extra))
    rows.sort(key=lambda r: (-r["extra"], -r["unc"], r["d"]))
    y, q = int(last[:4]), int(last[5])
    return dict(
        quarters=qs, regions=list(WH.REGIONS), turns=total, cover_h=COVER_H, min_dir_turns=MIN_DIR_TURNS,
        overlap=overlap, by_region=regions, people=[people[r] for r in WH.REGIONS], dirs=rows,
        data_span=data_span.of_data(first=f"{qs[0][:4]}-{(int(qs[0][5]) - 1) * 3 + 1:02d}-01",
                                    end=f"{y + q // 4}-{q % 4 * 3 + 1:02d}-01", ddb=ddb, cdb=gdb))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="cosh.review_timezones")
    ap.add_argument("--out", default=OUT, help="the folder of all.json (committed)")
    args = ap.parse_args(argv)
    ro = lambda p: sqlite3.connect(f"file:{p}?mode=ro", uri=True)   # noqa: E731
    data = compute(ro(C.db_path()), ro(os.path.join(store.DATA_DIR, store.DERIVED_FILE)), review_timeline.open_ro(),
                   lambda sha: owners.Owners(owners.read(C.repo_path(), sha)))
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "all.json"), "w") as f:
        f.write(RL.dumps(data))
    print(f"review-timezones: wrote all.json ({len(data['dirs'])} directories, {data['turns']:,} turns) to {args.out}",
          flush=True)


if __name__ == "__main__":
    main()
