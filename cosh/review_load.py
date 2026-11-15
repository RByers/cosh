"""The Review Load page's data (web/review-load.html, docs/review-load.md):
how much review work lands on Chromium's reviewers, how long changes wait
for them, and where.

Offline: reads commits.sqlite, reviews.sqlite and review-timeline.sqlite,
read-only, and fetches nothing. No comment text is read.

  nice -n 5 python3 -m cosh.review_load [--out DIR] [--people-out DIR] [--no-people]

Writes web/public/review-load/all.json (committed): every quarter's figures
and the directory table. Under data/private/review-load-people/, gzipped,
which `python3 -m cosh.r2 publish` uploads to the R2 bucket (docs/r2.md):
  <year>/<hash>.json.gz         one reviewer's figures for that year's quarters
  dirs/<quarter>/<hash>.json.gz their directories, for the table's four quarters
<hash> is the Feedback Index's (cosh.review_feedback.key: a salted SHA-256
of the address), so the page finds a person only when their address is typed.

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

People are one identity per address across chromium.org and google.com
(cosh.people.person).
"""

import argparse
import json
import os
import re
import shutil
import sqlite3
import statistics
from collections import defaultdict
from datetime import datetime, timezone

from . import commits as C
from . import r2, review_timeline, store
from .cl_facts import epoch
from .people import is_bot_email, person
from .review_feedback import key
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


def mean_median(xs):
    return (round(statistics.fmean(xs), 2), round(statistics.median(xs), 2), len(xs)) if xs else (None, None, 0)


def dir_levels(d):
    """A 3-level directory and its parents: 'a/b/c/' -> ['a/', 'a/b/', 'a/b/c/']."""
    parts = d.rstrip("/").split("/")
    return ["/".join(parts[:i]) + "/" for i in range(1, len(parts) + 1)]


def load_commits(gdb, start, end):
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
        author = person(email)
        who = sorted({person(x) for x in json.loads(rb) if not is_bot_email(x)} - {author})
        if who:
            reviewed[cid] = dict(at=at, n=n, reviewers=who)
    return landed, reviewed


def commit_dir_lines(gdb, ids):
    """{commit_id: {3-level directory: lines}} of the commits in `ids`, in
    today's directories, a renamed file counted by the lines changed."""
    current, moved = C.current_paths(gdb), C.moved_lines(gdb)
    dirs = {pid: C.dir_of(current.get(p, p), 3) for pid, p in gdb.execute("SELECT path_id, path FROM paths")}
    out = defaultdict(lambda: defaultdict(int))
    for cid, pid, ins, dels in gdb.execute("SELECT commit_id, path_id, ins, dels FROM commit_files WHERE commit_id > 0"):
        if cid in ids:
            ins, dels = moved.get((cid, pid), (ins, dels))
            out[cid][dirs[pid]] += max(ins, 0) + max(dels, 0)
    return out


def compute(gdb, ddb, tdb):
    end = data_end(ddb, gdb)
    last = last_whole_quarter(end)
    qs = quarters(FIRST_QUARTER, last)
    if not qs:
        raise SystemExit(f"no whole quarter from {FIRST_QUARTER} in the data (it ends {quarter(end)})")
    qi = {q: i for i, q in enumerate(qs)}
    nq = len(qs)
    table_qs = qs[-(TABLE_QUARTERS + 1):]
    ti = {q: i for i, q in enumerate(table_qs)}
    landed, reviewed = load_commits(gdb, quarter_start(qs[0]), quarter_start(next_quarter(last)))
    print(f"review-load: {qs[0]}..{last}, {len(landed):,} commits, {len(reviewed):,} reviewed", flush=True)
    dir_lines = commit_dir_lines(gdb, reviewed.keys())

    n_commits, n_human = [0] * nq, [0] * nq
    for at, human in landed:
        i = qi[quarter(at)]
        n_commits[i] += 1
        n_human[i] += human
    # Git: lines reviewed, per quarter, person and directory.
    rev_lines, rev_commits = [0] * nq, [0] * nq
    per = defaultdict(lambda: defaultdict(lambda: [0, 0, 0.0, 0, 0.0, 0]))   # person -> quarter -> figures
    people_q = [set() for _ in qs]
    dirs = defaultdict(lambda: [[0] * len(table_qs), [0.0] * len(table_qs), [0.0] * len(table_qs)])
    pdirs = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: [0, 0.0, 0.0])))  # quarter -> person -> dir
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
        for p in c["reviewers"]:
            rev_lines[i] += lines
            people_q[i].add(p)
            x = per[p][q]
            x[0] += 1
            x[1] += lines
            if q in ti:
                for d, n in dl.items():
                    if n:
                        dirs[d][0][ti[q]] += n
                        if q != table_qs[0]:
                            pdirs[q][p][d][0] += n
    # Gerrit: the same commits' CLs.
    emails = dict(ddb.execute("SELECT account_id, email FROM accounts"))
    created = {n: epoch(t) for n, t in ddb.execute(
        "SELECT change_number, created_at FROM changes WHERE is_bot_owned = 0 AND status = 'MERGED'") if n in by_cl}
    first = defaultdict(lambda: None)
    first_h, reply_h = [[] for _ in qs], [[] for _ in qs]
    att_hours, att_turns, att_people = [0.0] * nq, [0] * nq, [set() for _ in qs]
    for n, acct, asked, responded, wd in tdb.execute(
            "SELECT change_number, account_id, asked_at, responded_at, attention_weekday_h FROM cl_reviewers"):
        c = by_cl.get(n)
        if c is None or n not in created or not emails.get(acct):
            continue
        q, p = c["q"], person(emails[acct])
        i = qi[q]
        if responded is not None and (first[n] is None or responded < first[n]):
            first[n] = responded
        x = per[p][q]
        if asked is not None and q >= ATTENTION_FROM:
            att_hours[i] += wd
            att_turns[i] += 1
            att_people[i].add(p)
            x[2] += wd
            x[3] += 1
            if responded is not None and responded >= asked:
                h = weekday_seconds(asked, responded) / 3600
                reply_h[i].append(h)
                x[4] += h
                x[5] += 1
            if q in ti and c["lines"]:
                for d, ln in c["dirs"].items():
                    if ln:
                        w = ln / c["lines"]
                        dirs[d][1][ti[q]] += wd * w
                        dirs[d][2][ti[q]] += w
                        if q != table_qs[0]:
                            y = pdirs[q][p][d]
                            y[1] += wd * w
                            y[2] += w
    for n, t in first.items():
        if t is not None:
            first_h[qi[by_cl[n]["q"]]].append(weekday_seconds(created[n], t) / 3600)

    def series(lists, since=qs[0]):
        mm = [mean_median(x) if q >= since else (None, None, 0) for q, x in zip(qs, lists)]
        return dict(mean=[m[0] for m in mm], median=[m[1] for m in mm], n=[m[2] for m in mm])
    att = [q >= ATTENTION_FROM for q in qs]
    # The directory tree: every level's sums; listed with MIN_DIR_LINES in the table's four quarters.
    tree = defaultdict(lambda: [[0] * len(table_qs), [0.0] * len(table_qs), [0.0] * len(table_qs)])
    for d, v in dirs.items():
        for level in dir_levels(d):
            t = tree[level]
            for k in range(3):
                for j in range(len(table_qs)):
                    t[k][j] += v[k][j]
    listed = sorted((d, v) for d, v in tree.items() if sum(v[0][1:]) >= MIN_DIR_LINES)
    data = dict(
        quarters=qs, attention_from=ATTENTION_FROM, min_dir_lines=MIN_DIR_LINES,
        commits=n_commits, human=n_human,
        reviewed=rev_commits, reviewed_lines=rev_lines, reviewers=[len(s) for s in people_q],
        first=series(first_h), reply=series(reply_h, ATTENTION_FROM),
        attention=dict(hours=[round(h) if a else None for h, a in zip(att_hours, att)],
                       turns=[t if a else None for t, a in zip(att_turns, att)],
                       reviewers=[len(s) if a else None for s, a in zip(att_people, att)]),
        table_quarters=table_qs,
        # [directory, lines reviewed per table quarter (5), attention weekday hours and turns per quarter (the last 4)]
        dirs=[[d, v[0], [r1(x) for x in v[1][1:]], [round(x, 2) for x in v[2][1:]]] for d, v in listed],
    )
    people = {}
    for p, byq in per.items():
        years = defaultdict(dict)
        for q, x in byq.items():
            if x[0] or x[3]:
                # [commits reviewed, lines reviewed, attention weekday hours, turns, asked-to-answer hours, answers]
                years[q[:4]][q[5]] = [x[0], x[1], r1(x[2]), x[3], r1(x[4]), x[5]]
        if years:
            people[p] = years
    person_dirs = {q: {p: sorted([d, v[0], r1(v[1]), round(v[2], 2)] for d, v in ds.items() if v[0] or v[2] >= 0.005)
                       for p, ds in byp.items()} for q, byp in pdirs.items()}
    return data, people, person_dirs


def dumps(x):
    return json.dumps(x, separators=(",", ":"), ensure_ascii=False, sort_keys=True)


def write(out, data, people, person_dirs, people_out=None):
    """Writes all.json to out and the per-reviewer files, gzipped, to
    people_out, removing the ones no longer written. Unchanged files keep
    their bytes, so the R2 sync uploads only what changed."""
    os.makedirs(out, exist_ok=True)
    for name in os.listdir(out):       # per-reviewer folders from before they moved to R2
        if re.fullmatch(r"\d{4}|dirs", name):
            shutil.rmtree(os.path.join(out, name))
    with open(os.path.join(out, "all.json"), "w") as f:
        f.write(dumps(data))
    pout = people_out or r2.local_dir("review-load-people")
    keep = set()
    for p, years in people.items():
        for y, q in years.items():
            path = os.path.join(pout, y, f"{key(p)}.json.gz")
            r2.write_gz(path, dumps(dict(q=q)))
            keep.add(path)
    for q, byp in person_dirs.items():
        for p, rows in byp.items():
            if rows:
                path = os.path.join(pout, "dirs", q, f"{key(p)}.json.gz")
                r2.write_gz(path, dumps(rows))
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
    data, people, person_dirs = compute(ro(C.db_path()), ro(os.path.join(store.DATA_DIR, store.DERIVED_FILE)),
                                        review_timeline.open_ro())
    if args.no_people:
        people, person_dirs = {}, {}
    files = write(args.out, data, people, person_dirs, args.people_out)
    print(f"review-load: wrote all.json ({len(data['dirs']):,} directories) to {args.out} and {files:,} files of "
          f"{len(people):,} reviewers to {args.people_out or r2.local_dir('review-load-people')}", flush=True)


if __name__ == "__main__":
    main()
