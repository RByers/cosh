"""Exploratory: change complexity, review difficulty and rework per CL
(docs/balance.md).

Offline only; fetches nothing. Reads derived.sqlite and labels.sqlite
(read-only), the NoteDb meta refs, and the patch-set commits that the
2026-W44 pilot stored as refs/patchsets/<CL>/<ps> in the blob-less
chromium-src.git clone. Every git command runs with GIT_NO_LAZY_FETCH=1 and
reads only commits and trees (`diff-tree --no-renames` compares blob ids,
never contents), so nothing is fetched on demand.

For each merged, human-owned CL that closed in --week and has its patch sets
locally, writes one JSON line (no comment text) to --out, then prints
summary tables.

  COSH_DATA_DIR=<main>/data/private python3 scripts/balance_explore.py \
      --week 2026-W44 --out /tmp/.../balance.jsonl
"""

import argparse
import json
import os
import re
import sqlite3
import statistics as st
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cosh import classify, store  # noqa: E402
from scripts.review_impact import CatFile, timeline  # noqa: E402

ENV = {**os.environ, "GIT_NO_LAZY_FETCH": "1"}


def epoch(s):  # 'YYYY-MM-DD HH:MM:SS' or ISO with T/Z
    return int(datetime.strptime(s[:19].replace("T", " "), "%Y-%m-%d %H:%M:%S")
               .replace(tzinfo=timezone.utc).timestamp())


def patchset_refs(git_dir):
    out = subprocess.run(["git", "--git-dir", git_dir, "for-each-ref", "--format=%(objectname) %(refname)",
                          "refs/patchsets/"], capture_output=True, text=True, check=True, env=ENV).stdout
    refs = defaultdict(dict)
    for line in out.splitlines():
        sha, ref = line.split()
        _, _, n, ps = ref.split("/")
        if ps.isdigit():      # skip refs/patchsets/<CL>/robot-comments
            refs[int(n)][int(ps)] = sha
    return refs


def diff_trees(git_dir, shas):
    """{commit: {path: (old_blob, new_blob, status)}} against each commit's first
    parent, from one `git diff-tree --stdin` (trees only)."""
    p = subprocess.run(["git", "--git-dir", git_dir, "diff-tree", "--stdin", "-r", "--no-renames"],
                       input="\n".join(shas) + "\n", capture_output=True, text=True, env=ENV)
    if p.returncode:
        print("diff-tree:", p.stderr[-500:], file=sys.stderr)
    res, cur = {}, None
    for line in p.stdout.splitlines():
        if not line:
            continue
        if line[0] != ":":
            cur = res.setdefault(line.split()[0], {})
            continue
        meta, path = line.split("\t", 1)
        _, _, old, new, status = meta.split()
        cur[path] = (old, new, status)
    return res


# How a file of the final diff differs from the patch set first reviewed.
CHANGE_CODES = {0: "same", 1: "modified", 2: "modified, base moved (maybe only a rebase)", 3: "added"}


def change_code(p, modified, base_moved, added):
    return 3 if p in added else 2 if p in base_moved else 1 if p in modified else 0


def area(path, depth=3):
    """The directory a file is counted under: its first `depth` directory levels."""
    parts = path.split("/")[:-1]
    return "/".join(parts[:depth]) + "/" if parts else "(root)"


def load_review(db, week):
    """Per CL: reviewer comments, chars, reviewers, inline comments per file,
    and reviewer-started threads with their addressed point."""
    lab = {}
    lpath = classify.labels_path(store.DATA_DIR)
    if os.path.exists(lpath):
        ldb = sqlite3.connect(f"file:{lpath}?mode=ro", uri=True)
        active = classify.active_classifier(ldb)
        if active:
            for n, r, h, a in ldb.execute("SELECT change_number, root_uuid, input_hash, addressed FROM labels "
                                          "WHERE classifier_id = ?", (active[0],)):
                lab[(n, r, h)] = a
    rev = defaultdict(lambda: dict(comments=0, chars=0, reviewers=set(), first_at=None, files=defaultdict(int),
                                   threads=0, addressed=0, pending=0, thread_files=defaultdict(lambda: [0, 0])))
    q = """SELECT c.change_number, c.account_id, c.written_at, c.path, c.chars, c.root_uuid
           FROM comments c JOIN changes ch USING (host, change_number)
           JOIN accounts a ON a.host = c.host AND a.account_id = c.account_id
           WHERE ch.close_week = ? AND ch.status = 'MERGED' AND ch.is_bot_owned = 0 AND a.is_bot = 0
             AND c.after_close = 0"""
    root_path = {}
    for n, acct, at, path, chars, root in db.execute(q, (week,)):
        r = rev[n]
        r["comments"] += 1
        r["chars"] += chars
        r["reviewers"].add(acct)
        r["first_at"] = min(r["first_at"] or at, at)
        if not path.startswith("/"):
            r["files"][path] += 1
        root_path[(n, root)] = path
    q = """SELECT t.change_number, t.root_uuid, t.last_owner_reply_at, t.regex_addressed, t.input_hash, a.is_bot
           FROM threads t JOIN changes ch USING (host, change_number)
           JOIN accounts a ON a.host = t.host AND a.account_id = t.root_account
           WHERE ch.close_week = ? AND ch.status = 'MERGED' AND ch.is_bot_owned = 0"""
    for n, root, reply_at, rx, h, bot in db.execute(q, (week,)):
        if bot:
            continue
        r = rev[n]
        r["threads"] += 1
        point = 0 if reply_at is None else 1 if rx else lab.get((n, root, h))
        if point is None:
            r["pending"] += 1
        r["addressed"] += point or 0
        path = root_path.get((n, root), "/")
        if not path.startswith("/"):
            tf = r["thread_files"][path]
            tf[0] += 1
            tf[1] += point or 0
    return rev


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", default="2026-W44")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    git_dir = os.path.join(store.DATA_DIR, "git", "chromium-src.git")
    notedb = os.path.join(store.DATA_DIR, "notedb", "chromium_src.git")
    db = sqlite3.connect(f"file:{os.path.join(store.DATA_DIR, store.DERIVED_FILE)}?mode=ro", uri=True)

    refs = patchset_refs(git_dir)
    cls = db.execute("""SELECT change_number, owner_account, created_at, submitted_at, insertions, deletions,
                               patchsets FROM changes
                        WHERE close_week = ? AND status = 'MERGED' AND is_bot_owned = 0
                          AND project = 'chromium/src' AND branch = 'main'""", (args.week,)).fetchall()
    have = [c for c in cls if c[0] in refs]
    print(f"{len(cls)} merged human-owned CLs in {args.week}; {len(have)} with patch sets locally")
    rev = load_review(db, args.week)
    diffs = diff_trees(git_dir, [sha for c in have for sha in refs[c[0]].values()])
    cf = CatFile(notedb)

    rows = []
    for n, owner, created, submitted, ins, dels, nps in have:
        uploads, _ = timeline(cf, n)
        pss = refs[n]
        final = max(pss)
        r = rev.get(n)
        first = epoch(r["first_at"]) if r and r["first_at"] else None
        # The patch set the first reviewer comment was written on: the newest
        # one uploaded before it (ps 1 when the CL had no review comment).
        up_at = {ps: t for ps, t, *_ in uploads or []}
        seen = max([ps for ps in pss if up_at.get(ps, 0) <= (first or 0)] or [min(pss)])
        d0, d1 = diffs.get(pss[seen], {}), diffs.get(pss[final], {})
        modified = [p for p in d0.keys() & d1.keys() if d0[p][1] != d1[p][1]]
        base_moved = [p for p in modified if d0[p][0] != d1[p][0]]
        added = sorted(d1.keys() - d0.keys())
        dropped = sorted(d0.keys() - d1.keys())
        kinds = [k for ps, t, _, k, _ in uploads or [] if ps > seen]
        row = dict(
            n=n, owner=owner, ins=ins, dels=dels, lines=(ins or 0) + (dels or 0), patchsets=nps,
            files=len(d1), files_seen=len(d0), seen_ps=seen, final_ps=final,
            rework_uploads=kinds.count("rework"), rebase_uploads=kinds.count("rebase"),
            files_modified=len(modified), files_modified_clean=len(modified) - len(base_moved),
            files_added=len(added), files_dropped=len(dropped),
            hours_to_first_review=round((first - epoch(created)) / 3600, 1) if first else None,
            hours_review_to_submit=round((epoch(submitted) - first) / 3600, 1) if first and submitted else None,
            comments=r["comments"] if r else 0, chars=r["chars"] if r else 0,
            reviewers=len(r["reviewers"]) if r else 0, threads=r["threads"] if r else 0,
            addressed=r["addressed"] if r else 0, pending=r["pending"] if r else 0,
            # Per file of the final diff: (path, inline comments, threads, addressed, CHANGE_CODES)
            per_file=[(p, (r["files"].get(p, 0) if r else 0),
                       *((r["thread_files"][p] if r and p in r["thread_files"] else [0, 0])),
                       change_code(p, modified, base_moved, added)) for p in sorted(d1)],
        )
        rows.append(row)
    with open(args.out, "w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    report(rows)


def ranks(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    rk = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            rk[order[k]] = (i + j) / 2
        i = j + 1
    return rk


def spearman(a, b):
    return st.correlation(ranks(a), ranks(b)) if len(a) > 2 else float("nan")


def q(xs, *ps):
    xs = sorted(xs)
    return [xs[min(len(xs) - 1, int(p * len(xs)))] for p in ps] if xs else [None] * len(ps)


def report(rows):
    reviewed = [r for r in rows if r["comments"]]
    print(f"\n{len(rows)} CLs; {len(reviewed)} with at least one reviewer comment\n")
    cols = ["lines", "files", "patchsets", "rework_uploads", "comments", "threads", "addressed", "reviewers",
            "files_modified", "files_modified_clean", "files_added", "hours_to_first_review",
            "hours_review_to_submit"]
    print(f"{'measure':24} {'p25':>7} {'p50':>7} {'p75':>7} {'p90':>7} {'p99':>7}")
    for c in cols:
        xs = [r[c] for r in rows if r[c] is not None]
        print(f"{c:24} " + " ".join(f"{v:>7}" for v in q(xs, .25, .5, .75, .9, .99)))
    print("\nSpearman correlations over all CLs:")
    pairs = [("lines", "files"), ("lines", "threads"), ("files", "threads"), ("lines", "addressed"),
             ("threads", "addressed"), ("addressed", "rework_uploads"), ("addressed", "files_modified_clean"),
             ("lines", "files_modified_clean"), ("threads", "files_modified_clean"),
             ("lines", "hours_review_to_submit"), ("threads", "hours_review_to_submit")]
    for a, b in pairs:
        sub = [r for r in rows if r[a] is not None and r[b] is not None]
        print(f"  {a:>14} ~ {b:<24} {spearman([r[a] for r in sub], [r[b] for r in sub]):+.2f}  (n={len(sub)})")
    # Rework share among reviewed CLs.
    chg = [r for r in reviewed if r["files_modified"] or r["files_added"] or r["files_dropped"]]
    print(f"\nReviewed CLs whose files changed after the first review: {len(chg)}/{len(reviewed)} "
          f"({len(chg) / max(1, len(reviewed)):.0%})")
    share = [(r["files_modified"] + r["files_added"]) / r["files"] for r in reviewed if r["files"]]
    print("Share of final files changed after first review (reviewed CLs) p25/p50/p75/p90:",
          [round(x, 2) for x in q(share, .25, .5, .75, .9)])
    # Per-area baselines: per file occurrence.
    by = defaultdict(lambda: [0, 0, 0, 0, 0, set()])
    for r in reviewed:
        for p, inline, th, ad, changed in r["per_file"]:
            a = by[area(p, 2)]
            a[0] += 1
            a[1] += inline
            a[2] += th
            a[3] += ad
            a[4] += changed in (1, 3)
            a[5].add(r["n"])
    print(f"\n{'area (2 levels)':40} {'files':>6} {'CLs':>5} {'inline/f':>8} {'thr/f':>6} {'addr/f':>6} {'chg%':>5}")
    for k, (nf, inline, th, ad, changed, ns) in sorted(by.items(), key=lambda kv: -kv[1][0])[:30]:
        print(f"{k:40} {nf:>6} {len(ns):>5} {inline / nf:>8.2f} {th / nf:>6.2f} {ad / nf:>6.2f} "
              f"{changed / nf:>5.0%}")


if __name__ == "__main__":
    main()
