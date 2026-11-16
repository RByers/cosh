"""The Review Load page's data (web/review-load.html, docs/review-load.md):
how much review work lands on Chromium's reviewers, how long changes wait
for them, and where.

Offline: reads commits.sqlite, reviews.sqlite and review-timeline.sqlite,
read-only, and fetches nothing. No comment text is read.

  nice -n 5 python3 -m cosh.review_load [--out DIR] [--people-out DIR] [--no-people]

Writes web/public/review-load/all.json (committed): every quarter's figures
and the directory table. Under data/private/review-load-people/, gzipped,
which `python3 -m cosh.r2 publish` uploads to the R2 bucket (docs/r2.md),
one file per reviewer, <name>.json.gz:
  {"v": 2, "years": {year: {"q": {quarter of the year: figures}}},
   "dirs": {quarter: their directories, for the table's four quarters}}
and {"see": <name>} for each other address of a reviewer, so typing any of
them finds them. <name> is the Feedback Index's (cosh.review_feedback.file_name:
the address as typed, lower case). The bucket can't be listed, so the page
finds a person only when their address is typed.

Whole quarters only: the last one is the newest that both the fetched Gerrit
weeks and main's history cover, so a week of new data changes nothing until
it completes a quarter (docs/goals.md, goals 3 and 4).

Population. Commits: main's first-parent history from 2017-07-01. "Reviewed"
commits: by a person (not a bot), not a revert, not part of a large-scale
change, and not mechanical (100+ files, or 10+ files with a repetition ratio
of 0.8+), with a Reviewed-by footer naming someone other than the author.
Each such reviewer reviewed the commit's lines (insertions plus deletions; a
renamed file counts by the lines changed, binary files 0), so a commit with
two reviewers counts its lines twice: the page measures review work.
Gerrit figures cover the same commits' CLs, by the quarter they landed.

People are exact identities (cosh.people.exact_identities), the same as the
Feedback Index's: addresses merge only on evidence, never by domain.
"""

import argparse
import functools
import json
import os
import re
import shutil
import sqlite3
import statistics
from collections import defaultdict
from datetime import datetime, timezone

from . import commits as C
from . import data_span, owners, r2, review_timeline, store
from .people import exact_identities, is_bot_email
from .review_feedback import file_name
from .review_timeline import weekday_seconds

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "web", "public", "review-load")
FIRST_QUARTER = "2017Q3"       # Gerrit and Reviewed-by footers start mid-2017
ATTENTION_FROM = "2021Q1"      # Chromium's Gerrit got the attention set in late 2020
TABLE_QUARTERS = 4             # the directory table's quarters (plus one before, for the first change)
MIN_DIR_LINES = 5_000          # a directory is listed with this many reviewed lines in the table's quarters
MECH_FILES, MECH_REP_FILES, MECH_REP = 100, 10, 0.8      # as commits.mechanical
WEEK = 7 * 86400


def quarter(t):
    d = datetime.fromtimestamp(t, timezone.utc)
    return f"{d.year}Q{(d.month - 1) // 3 + 1}"


def quarter_start(q):
    return int(datetime(int(q[:4]), (int(q[5]) - 1) * 3 + 1, 1, tzinfo=timezone.utc).timestamp())


def next_quarter(q):
    y, n = int(q[:4]), int(q[5])
    return f"{y + 1}Q1" if n == 4 else f"{y}Q{n + 1}"


def quarters(first, last):
    out = [first]
    while out[-1] < last:
        out.append(next_quarter(out[-1]))
    return out if first <= last else []


def last_whole_quarter(end):
    """The newest quarter that ends at or before `end` (unix seconds)."""
    q = quarter(end)
    y, n = int(q[:4]), int(q[5])
    return f"{y - 1}Q4" if n == 1 else f"{y}Q{n - 1}"


def data_end(ddb, gdb):
    """Where both sources end: the Monday after the last fetched Gerrit week,
    and the newest commit on main."""
    row = ddb.execute("SELECT v FROM meta WHERE k = 'fetched_weeks'").fetchone()
    weeks = sorted(json.loads(row[0])) if row and row[0] else []
    if not weeks:
        raise SystemExit("reviews.sqlite records no fetched weeks")
    y, w = weeks[-1].split("-W")
    gerrit = int(datetime.fromisocalendar(int(y), int(w), 1).replace(tzinfo=timezone.utc).timestamp()) + WEEK
    return min(gerrit, gdb.execute("SELECT max(landed_at) FROM commits").fetchone()[0])


def r1(x):
    return round(x, 1)


def table_rows(d, listed, parents):
    """The keys of the table rows a 3-level directory's turns count in, as the page's tree has them:
    "d:<dir>" for each listed directory it is in; "o:<dir>" for the "Other" of the deepest one when that
    has listed children (files directly in it count there too); "o:" when none is listed (shown only
    for a looked-up reviewer)."""
    up = [x for x in dir_levels(d) if x in listed]
    if not up:
        return ("o:",)
    return (*(f"d:{x}" for x in up), *((f"o:{up[-1]}",) if up[-1] in parents else ()))


PCTS = (0.5, 0.75, 0.9)


def weighted_pcts(hw, fs=PCTS):
    """The weighted percentiles `fs` of [(hours, weight)], rounded; None without any."""
    hw = sorted(x for x in hw if x[1] > 0)
    if not hw:
        return None
    tot, out, acc, k = sum(w for _, w in hw), [], 0.0, 0
    for f in fs:
        while k < len(hw) - 1 and acc + hw[k][1] < f * tot - 1e-9:
            acc += hw[k][1]
            k += 1
        out.append(r1(hw[k][0]))
    return out


def spread(lists, shown=None):
    """Percentiles (10th, 25th, 50th, 75th, 90th), mean and count of each quarter's values (all
    None where `shown` is false)."""
    shown = shown or [True] * len(lists)
    out = {k: [] for k in ("p10", "p25", "p50", "p75", "p90", "mean", "n")}
    for xs, ok in zip(lists, shown):
        qs = (statistics.quantiles(xs, n=20, method="inclusive") if len(xs) > 1 else xs * 19) if ok and xs else None
        for k, i in (("p10", 1), ("p25", 4), ("p50", 9), ("p75", 14), ("p90", 17)):
            out[k].append(round(qs[i], 2) if qs else None)
        out["mean"].append(round(statistics.fmean(xs), 2) if ok and xs else None)
        out["n"].append(len(xs) if ok else 0)
    return out


def dir_levels(d):
    """A 3-level directory and its parents: 'a/b/c/' -> ['a/', 'a/b/', 'a/b/c/']."""
    parts = d.rstrip("/").split("/")
    return ["/".join(parts[:i]) + "/" for i in range(1, len(parts) + 1)]


def load_commits(gdb, start, end, ids):
    """(every commit's (landed_at, by a person), the reviewed commits
    {commit_id: dict(at, n, reviewers)}) of [start, end)."""
    rep = dict(gdb.execute("SELECT commit_id, ratio FROM repetition"))
    landed, reviewed = [], {}
    for cid, email, at, n, bot, rb, revert, files, lsc in gdb.execute(
            "SELECT commit_id, author_email, landed_at, change_number, is_bot, reviewed_by, "
            "is_revert OR reverts_sha IS NOT NULL, files, is_lsc FROM commits "
            "WHERE commit_id > 0 AND landed_at >= ? AND landed_at < ?", (start, end)):
        human = not bot and not is_bot_email(email)
        landed.append((at, human))
        if not human or revert or lsc or not rb or files >= MECH_FILES \
                or (files >= MECH_REP_FILES and (rep.get(cid) or 0) >= MECH_REP):
            continue
        author = ids.find(email)
        who = sorted({ids.find(x) for x in json.loads(rb) if not is_bot_email(x)} - {author})
        if who:
            reviewed[cid] = dict(at=at, n=n, reviewers=who, author=author)
    return landed, reviewed


def commit_dir_lines(gdb, ids, detail=()):
    """{commit_id: {3-level directory: lines}} of the commits in `ids`, in
    today's directories, a renamed file counted by the lines changed; and,
    for the commits in `detail`, {commit_id: {file's directory: lines}}."""
    current, moved = C.current_paths(gdb), C.moved_lines(gdb)
    dirs = {pid: C.dir_of(current.get(p, p), 3) for pid, p in gdb.execute("SELECT path_id, path FROM paths")}
    full = {}
    out, files = defaultdict(lambda: defaultdict(int)), defaultdict(lambda: defaultdict(int))
    for cid, pid, ins, dels in gdb.execute("SELECT commit_id, path_id, ins, dels FROM commit_files WHERE commit_id > 0"):
        if cid in ids:
            ins, dels = moved.get((cid, pid), (ins, dels))
            out[cid][dirs[pid]] += max(ins, 0) + max(dels, 0)
            if cid in detail:
                if pid not in full:
                    path, = gdb.execute("SELECT path FROM paths WHERE path_id = ?", (pid,)).fetchone()
                    full[pid] = os.path.dirname(current.get(path, path))
                files[cid][full[pid]] += max(ins, 0) + max(dels, 0)
    return out, files


def committer_since(tdb, emails, ids, reviewed):
    """{person: when they could first be seen to approve changes}: their
    first Code-Review vote, or their first commit that landed with a single
    reviewer (a non-committer's needs two). Before that, and for people with
    neither, they count as not yet a committer."""
    since = {}
    for table in ("votes", "listing_votes"):
        for acct, t in tdb.execute(f"SELECT voter, min(at) FROM {table} WHERE value != 0 GROUP BY voter"):
            if emails.get(acct):
                p = ids.find(emails[acct])
                since[p] = min(t, since.get(p, t))
    for c in reviewed.values():
        if len(c["reviewers"]) == 1:
            since[c["author"]] = min(c["at"], since.get(c["author"], c["at"]))
    return since


def half_by(lines):
    """How many of the biggest values make up half the total."""
    need, n = sum(lines) / 2, 0
    for v in sorted(lines, reverse=True):
        if need <= 0:
            break
        need -= v
        n += 1
    return n


def owner_figures(commits, files, own, ids, since):
    """Who reviewed `commits` (the table's four quarters), against the OWNERS
    files `own`: per directory level and "" for everything,
    [reviewers, how many of them did half the review, people listed in an
    OWNERS file there or below, how many of those reviewed there, lines
    reviewed by an owner of the file, lines of changes by people not yet
    committers (two approvals needed), those lines that two owners approved]."""
    people = {}

    def owns(p, d):
        if d not in people:
            addresses, anyone = own.of(d)
            people[d] = ({ids.find(e) for e in addresses}, anyone)
        return people[d][1] or p in people[d][0]
    by = defaultdict(lambda: defaultdict(int))        # 3-level directory -> reviewer -> lines
    sums = defaultdict(lambda: [0, 0, 0])             # 3-level directory -> [by an owner, non-committers', two owners]
    for cid, c in commits.items():
        two = len(c["reviewers"]) >= 2 and since.get(c["author"], float("inf")) > c["at"]
        for d, n in files.get(cid, {}).items():
            if not n:
                continue
            d3 = C.dir_of(d + "/x" if d else "x", 3)
            owners = [p for p in c["reviewers"] if owns(p, d)]
            for p in c["reviewers"]:
                by[d3][p] += n
            s = sums[d3]
            s[0] += n * len(owners)
            if two:
                s[1] += n
                s[2] += n * (len(owners) >= 2)
    listed = defaultdict(set)
    for d, (addresses, _, _) in own.direct.items():
        who = {ids.find(e) for e in addresses}
        listed[""] |= who
        if d:
            for level in dir_levels(C.dir_of(d + "/x", 3)):
                listed[level] |= who
    tree_by, tree = defaultdict(lambda: defaultdict(int)), defaultdict(lambda: [0, 0, 0])
    for d3, ps in by.items():
        for level in [""] + dir_levels(d3):
            for p, n in ps.items():
                tree_by[level][p] += n
            for k in range(3):
                tree[level][k] += sums[d3][k]
    return {level: [len(ps), half_by(ps.values()), len(listed[level]), len(listed[level] & ps.keys()), *tree[level]]
            for level, ps in tree_by.items()}


def compute(gdb, ddb, tdb, owners_at=None):
    """`owners_at(sha)` gives the cosh.owners.Owners of that commit's tree;
    without it the OWNERS figures are left out."""
    end = data_end(ddb, gdb)
    last = last_whole_quarter(end)
    qs = quarters(FIRST_QUARTER, last)
    if not qs:
        raise SystemExit(f"no whole quarter from {FIRST_QUARTER} in the data (it ends {quarter(end)})")
    qi = {q: i for i, q in enumerate(qs)}
    nq = len(qs)
    table_qs = qs[-(TABLE_QUARTERS + 1):]
    ti = {q: i for i, q in enumerate(table_qs)}
    ids = exact_identities(ddb, gdb, tdb)
    landed, reviewed = load_commits(gdb, quarter_start(qs[0]), quarter_start(next_quarter(last)), ids)
    print(f"review-load: {qs[0]}..{last}, {len(landed):,} commits, {len(reviewed):,} reviewed", flush=True)
    table_commits = {cid: c for cid, c in reviewed.items() if quarter(c["at"]) in table_qs[1:]} if owners_at else {}
    dir_lines, file_lines = commit_dir_lines(gdb, reviewed.keys(), table_commits.keys())

    n_commits, n_human = [0] * nq, [0] * nq
    for at, human in landed:
        i = qi[quarter(at)]
        n_commits[i] += 1
        n_human[i] += human
    # Git: lines reviewed, per quarter, person and directory.
    rev_lines, rev_commits = [0] * nq, [0] * nq
    commit_lines, reviews, multi = [0] * nq, [0] * nq, [0] * nq   # reviewed commits' own lines, reviewers, 2+ reviewers
    per = defaultdict(lambda: defaultdict(lambda: [0, 0, 0.0, 0, 0.0, 0]))   # person -> quarter -> figures
    people_q = [set() for _ in qs]
    dirs = defaultdict(lambda: [0] * len(table_qs))           # 3-level directory -> lines per table quarter
    pdirs = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))  # quarter -> person -> directory -> lines
    by_cl = {}
    for cid, c in reviewed.items():
        q = quarter(c["at"])
        i = qi[q]
        dl = dir_lines.get(cid, {})
        lines = sum(dl.values())
        c["lines"], c["q"], c["dirs"] = lines, q, dl
        if c["n"] is not None:
            by_cl[c["n"]] = c
        rev_commits[i] += 1
        commit_lines[i] += lines
        reviews[i] += len(c["reviewers"])
        multi[i] += len(c["reviewers"]) > 1
        for p in c["reviewers"]:
            rev_lines[i] += lines
            people_q[i].add(p)
            x = per[p][q]
            x[0] += 1
            x[1] += lines
            if q in ti:
                for d, n in dl.items():
                    if n:
                        dirs[d][ti[q]] += n
                        if q != table_qs[0]:
                            pdirs[q][p][d] += n
    # The directory tree: every level's lines; listed with MIN_DIR_LINES in the table's four quarters.
    tree = defaultdict(lambda: [0] * len(table_qs))
    for d, v in dirs.items():
        for level in dir_levels(d):
            for j in range(len(table_qs)):
                tree[level][j] += v[j]
    listed = {d for d, v in tree.items() if sum(v[1:]) >= MIN_DIR_LINES}
    parents = {dir_levels(d)[-2] for d in listed if len(dir_levels(d)) > 1} & listed
    rows_of = functools.lru_cache(maxsize=None)(lambda d: table_rows(d, listed, parents))
    # Gerrit: the same commits' CLs.
    emails = ids.accounts          # with the addresses found for accounts Gerrit shows without one
    merged = {n for (n,) in ddb.execute(
        "SELECT change_number FROM changes WHERE is_bot_owned = 0 AND status = 'MERGED'") if n in by_cl}
    reply_h = [[] for _ in qs]
    for n, acct, asked, responded, wd in tdb.execute(
            "SELECT change_number, account_id, asked_at, responded_at, attention_weekday_h FROM cl_reviewers"):
        c = by_cl.get(n)
        if c is None or n not in merged or not emails.get(acct):
            continue
        q, p = c["q"], ids.find(emails[acct])
        x = per[p][q]
        if asked is not None and q >= ATTENTION_FROM:
            x[2] += wd
            x[3] += 1
            if responded is not None and responded >= asked:
                h = weekday_seconds(asked, responded) / 3600
                reply_h[qi[q]].append(h)
                x[4] += h
                x[5] += 1
    # Reviewers' turns: every one per quarter; in the table, per row and quarter, weighted by the CL's
    # share of lines there.
    turn_h = [[] for _ in qs]
    pturns = defaultdict(lambda: defaultdict(list))                       # person -> quarter -> hours
    ntq = len(table_qs) - 1
    row_t = defaultdict(lambda: [[] for _ in range(ntq)])                 # row -> table quarter -> [(hours, weight)]
    prow_t = defaultdict(lambda: defaultdict(list))                       # person -> row -> [(hours, weight)]
    for n, acct, h in tdb.execute("SELECT change_number, account_id, weekday_h FROM cl_turns"):
        c = by_cl.get(n)
        if c is None or n not in merged or not emails.get(acct) or c["q"] < ATTENTION_FROM:
            continue
        q, p = c["q"], ids.find(emails[acct])
        turn_h[qi[q]].append(h)
        pturns[p][q].append(h)
        if q in ti and q != table_qs[0] and c["lines"]:
            ws = defaultdict(float)
            for d, ln in c["dirs"].items():
                for k in rows_of(d) if ln else ():
                    ws[k] += ln / c["lines"]
            for k, w in ws.items():
                if k != "o:":
                    row_t[k][ti[q] - 1].append((h, w))
                prow_t[p][k].append((h, w))

    def row(k):
        """A table row's percentiles per quarter, its turns per quarter, and its percentiles over the four."""
        t = row_t.get(k, [[] for _ in range(ntq)])
        return [weighted_pcts(x) for x in t], [round(sum(w for _, w in x), 2) for x in t], weighted_pcts(sum(t, []))
    # OWNERS as they stood at the last quarter's last commit, so the figures move only with a new quarter.
    own, own_at = {}, None
    if owners_at:
        sha, own_at = gdb.execute("SELECT sha, landed_at FROM commits WHERE landed_at < ? ORDER BY landed_at DESC, "
                                  "commit_id DESC LIMIT 1", (quarter_start(next_quarter(last)),)).fetchone()
        own = owner_figures(table_commits, file_lines, owners_at(sha), ids, committer_since(tdb, emails, ids, reviewed))
    y, n = int(last[:4]), int(last[-1])
    data = dict(
        # cosh.data_span: Gerrit's first week to the end of the last whole quarter
        data_span=data_span.of_data(end=f"{y + n // 4}-{n % 4 * 3 + 1:02d}-01", ddb=ddb, cdb=gdb),
        quarters=qs, attention_from=ATTENTION_FROM, min_dir_lines=MIN_DIR_LINES,
        commits=n_commits, human=n_human,
        reviewed=rev_commits, reviewed_lines=rev_lines, reviewers=[len(s) for s in people_q],
        # Reviewers per reviewed commit: its lines once, its reviewers, and the commits with two or more.
        reviewers_per_commit=dict(lines=commit_lines, reviews=reviews, multi=multi),
        # Lines reviewed per reviewer: the spread over the people who reviewed anything in the quarter.
        reviewer_lines=spread([[byq[q][1] for byq in per.values() if q in byq and byq[q][0]] for q in qs]),
        # A reviewer's turn to first answer and every turn's hours: their spread per quarter.
        reply=spread(reply_h, [q >= ATTENTION_FROM for q in qs]),
        # Reviewers' turns: percentiles, mean and count per quarter.
        turns=spread(turn_h, [q >= ATTENTION_FROM for q in qs]),
        table_quarters=table_qs,
        # [directory, lines reviewed per table quarter (5), its turns' [50th, 75th, 90th percentile] hours per
        #  quarter (the last 4; null without turns), turns per quarter, the percentiles over the four quarters,
        #  with OWNERS: owner_figures' seven over the last 4]
        dirs=[[d, tree[d], *row(f"d:{d}"), *([own[d]] if d in own else [])] for d in sorted(listed)],
        # Each listed directory with listed children: its "Other" row's [directory, percentiles per quarter,
        # turns per quarter, percentiles over the four].
        others=[[d, *row(f"o:{d}")] for d in sorted(parents)],
        # The OWNERS figures of everything, and the day of the OWNERS files read.
        owners=dict(at=datetime.fromtimestamp(own_at, timezone.utc).strftime("%Y-%m-%d"), all=own[""]) if own else None,
    )
    people = {}
    for p, byq in per.items():
        years = defaultdict(dict)
        for q, x in byq.items():
            if x[0] or x[3]:
                # [commits reviewed, lines reviewed, attention weekday hours, CLs counted in them,
                #  asked-to-answer hours, answers]
                years[q[:4]][q[5]] = [x[0], x[1], r1(x[2]), x[3], r1(x[4]), x[5]]
        if years:
            people[p] = years
    person_dirs = {q: {p: sorted([d, v] for d, v in ds.items() if v) for p, ds in byp.items()}
                   for q, byp in pdirs.items()}
    # Each reviewer's turns: {quarter: [median hours, turns]}; and their table rows over the four
    # quarters: {row key: [50th, 75th, 90th percentile, turns]}.
    person_more = defaultdict(dict)
    for p, byq in pturns.items():
        person_more[p]["turns"] = {q: [r1(statistics.median(t)), len(t)] for q, t in sorted(byq.items())}
    for p, rs in prow_t.items():
        person_more[p]["rows"] = {k: [*weighted_pcts(x), round(sum(w for _, w in x), 2)] for k, x in sorted(rs.items())}
    # Each reviewer's other addresses, for the page's lookup stubs (never in all.json).
    aliases = {e: p for p, es in ids.groups().items() if p in people for e in es if e != p}
    return data, people, person_dirs, aliases, dict(person_more)


def dumps(x):
    return json.dumps(x, separators=(",", ":"), ensure_ascii=False, sort_keys=True)


def write(out, data, people, person_dirs, people_out=None, aliases=None, person_more=None):
    """Writes all.json to out and the per-reviewer files, gzipped, to
    people_out, with a {"see": name} file for each other address of a
    reviewer (`aliases`: address -> identity), removing the ones no longer
    written. Unchanged files keep
    their bytes, so the R2 sync uploads only what changed."""
    os.makedirs(out, exist_ok=True)
    for name in os.listdir(out):       # per-reviewer folders from before they moved to R2
        if re.fullmatch(r"\d{4}|dirs", name):
            shutil.rmtree(os.path.join(out, name))
    with open(os.path.join(out, "all.json"), "w") as f:
        f.write(dumps(data))
    if people_out is None:
        r2.hold()
    pout = people_out or r2.local_dir("review-load-people")
    keep = set()
    person_more = person_more or {}
    for p in sorted(set(people) | {p for byp in person_dirs.values() for p, rows in byp.items() if rows} | set(person_more)):
        dirs = {q: byp[p] for q, byp in sorted(person_dirs.items()) if byp.get(p)}
        path = os.path.join(pout, f"{file_name(p)}.json.gz")
        r2.write_gz(path, dumps(dict(v=2, years={y: dict(q=q) for y, q in people.get(p, {}).items()}, dirs=dirs,
                                     **person_more.get(p, {}))))
        keep.add(path)
    for e, p in sorted((aliases or {}).items()):
        path = os.path.join(pout, f"{file_name(e)}.json.gz")
        if path not in keep:
            r2.write_gz(path, dumps(dict(see=file_name(p))))
            keep.add(path)
    os.makedirs(pout, exist_ok=True)
    r2.prune(pout, keep)
    return len(keep)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="cosh.review_load")
    ap.add_argument("--out", default=OUT, help="all.json (committed)")
    ap.add_argument("--people-out", help="the per-reviewer files, published to R2 (default <data>/review-load-people)")
    ap.add_argument("--no-people", action="store_true", help="write all.json only")
    args = ap.parse_args(argv)
    ro = lambda p: sqlite3.connect(f"file:{p}?mode=ro", uri=True)   # noqa: E731
    data, people, person_dirs, aliases, person_more = compute(
        ro(C.db_path()), ro(os.path.join(store.DATA_DIR, store.DERIVED_FILE)), review_timeline.open_ro(),
        lambda sha: owners.Owners(owners.read(C.repo_path(), sha)))
    if args.no_people:
        people, person_dirs, aliases, person_more = {}, {}, {}, {}
    files = write(args.out, data, people, person_dirs, args.people_out, aliases, person_more)
    print(f"review-load: wrote all.json ({len(data['dirs']):,} directories) to {args.out} and {files:,} files of "
          f"{len(people):,} reviewers to {args.people_out or r2.local_dir('review-load-people')}", flush=True)


if __name__ == "__main__":
    from cosh import memcap
    memcap.join()   # about 1.6 GB: take turns in the shared cap (AGENTS.md)
    main()
