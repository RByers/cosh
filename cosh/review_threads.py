"""A person's review threads of the past year, in full, for the Feedback
Index's download and its reviewer rows (web/feedback-index.html,
docs/review-feedback.md, "Downloading your comments").

For every person in the Feedback Index's CL index
(data/private/feedback-cls.json.gz, the CLs behind each person's
published file, by half-year; `cosh.review_feedback` writes it), writes
data/private/review-threads/<name>.json.gz: every thread a human reviewer
other than the owner started on their CLs that landed in the 52 weeks up
to the data's end, with the full text of every comment in it. One file
per person, and only the past year (docs/plan.md, 2026-11-14): all years
back to 2017, a file per half-year, was 33,015 files and 407 MB; this is
about 2,600 files and 45 MB. CLs without such a thread are left out, and a
person without any gets no file (the page reads a missing file as "no
comments"). `cosh.r2 publish` puts the files in the R2 bucket, where the
page fetches a person's file when they download their comments or open a
reviewer. Same names as the Feedback Index's (the normalised address); the
bucket can't be listed, so they can be found only by typing the person's
address (docs/plan.md, ground rule 5).

Format (v 4), JSON:

  {"v": 4, "from": "YYYY-MM-DD", "to": "YYYY-MM-DD",   the CLs' landing days, inclusive
   "people": [name, ...],             names (else addresses), indexed below
   "reviewers": [approver or null, ...]  per person, same order: the
                                      approver, as the person's file
                                      names approvers (`revs`), that
                                      this Gerrit account is: one whose
                                      address belongs to that approver's
                                      exact identity (people.exact_identities,
                                      the Feedback Index's)
   "cls": [{"n": change number, "half": the half-year the Feedback Index
            counts it in ("2026H1"), "project": ..., "subject": ...,
            "landed": "YYYY-MM-DD", "lines": Gerrit's insertions,
            "owner": people index,
            "threads": [{"id": root comment uuid, "path": file,
                         "/COMMIT_MSG" or "/PATCHSET_LEVEL", "line": n or null,
                         "ps": patch set, "addressed": true/false/null
                         (null: CL-level, or no label yet), "resolved": bool,
                         "dir": the 3-level directory the Feedback Index
                         counts it in (null for CL-level threads),
                         "comments": [[people index, "YYYY-MM-DDTHH:MMZ",
                                       text], ...]}, ...]}, ...]}

CLs oldest first, threads by their first comment. Offline: reads the
Feedback Index's CL index, reviews.sqlite, addressed.sqlite, commits.sqlite
and review-timeline.sqlite (for people.exact_identities) and the NoteDb
repos. Files are written byte for byte the same when nothing changed, so
`cosh.r2 sync` uploads only what did: each week, the files of people with
a CL landing in or leaving the window, or a new comment or label.

  COSH_DATA_DIR=<main>/data/private nice -n 5 python3 -m cosh.review_threads
"""

import argparse
import datetime as dt
import gzip
import json
import os
import sqlite3
import sys
import time

from . import classify, r2, store
from . import commits as C
from . import review_timeline
from .people import exact_identities
from .derive import DELETED_USER, prefetch_notedb

HOST = "chromium-review.googlesource.com"
PATCHSET_LEVEL = "/PATCHSET_LEVEL"
VERSION = 4
WEEKS = 52


def out_dir(data_dir=None):
    return r2.local_dir("review-threads", data_dir)


def read_index(path):
    """The Feedback Index's CL index (cosh.review_feedback `cl_index`):
    {name: {half: [(change number, approvers, {thread root: directory})]}}."""
    with gzip.open(path, "rt") as f:
        doc = json.load(f)
    dirs = doc["dirs"]
    return {k: {h: [(n, revs, {r: dirs[i] for r, i in td.items()}) for n, revs, td in cls]
                for h, cls in by_half.items()}
            for k, by_half in doc["people"].items()}


def ro(path):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def minute(ts):
    """'2026-01-02 10:11:12.000000000' or ISO -> '2026-01-02T10:11Z'."""
    return ts[:10] + "T" + ts[11:16] + "Z" if ts else ""


def cl_threads(comments, owner, bots, addressed_of):
    """The reviewer threads of one CL as file entries (without people
    indexes: comments carry account ids, mapped by the caller)."""
    by_id = {c["id"]: c for cs in (comments or {}).values() for c in cs if c.get("id")}
    out = []
    for th in classify.build_threads(comments, owner):
        if th["root_account"] in bots:
            continue
        root = by_id[th["root_id"]]
        if root.get("is_ai"):
            continue
        last = by_id[th["items"][-1][0]]
        path = th["path"] or "/COMMIT_MSG"
        out.append(dict(
            id=th["root_id"], path=path, line=root.get("line"), ps=root.get("patch_set"),
            addressed=None if path == PATCHSET_LEVEL else addressed_of(th["root_id"]),
            resolved=not last.get("unresolved", False),
            comments=[[aid, minute(ts), msg] for _, aid, ts, msg in th["items"]]))
    out.sort(key=lambda t: (t["comments"][0][1], t["id"]))
    return out


def addressed_lookup(ddb, labels, n):
    """root uuid -> True/False/None (None: owner replied, no label yet), as
    the Feedback Index counts it: no owner reply is not addressed, the
    Done-type regex is, else the active Haiku label. labels(n) gives the
    CL's labels as {(root uuid, input hash): addressed}."""
    got = {}
    labels = labels(n)
    for root, reply, rx, h in ddb.execute(
            "SELECT root_uuid, last_owner_reply_at, regex_addressed, input_hash FROM threads "
            "WHERE host = ? AND change_number = ?", (HOST, n)):
        if reply is None:
            got[root] = False
        elif rx:
            got[root] = True
        else:
            a = labels.get((root, h))
            got[root] = None if a is None else bool(a)
    return lambda root: got.get(root)


def write(path, doc):
    """Writes gzipped JSON, byte for byte the same for the same doc."""
    return r2.write_gz(path, json.dumps(doc, separators=(",", ":"), ensure_ascii=False))


def window(end, weeks=WEEKS):
    """The first landing day of the <weeks> weeks that end on day <end>."""
    return (dt.date.fromisoformat(end) - dt.timedelta(days=weeks * 7 - 1)).isoformat()


def person_doc(cls, info, per_cl, accounts, ident, mine, start, end):
    """One person's file: their CLs `cls` ([(half, change number, {thread
    root: directory})]) that landed from <start> to <end> and have reviewer
    threads (`per_cl`, from cl_threads). None when there are none."""
    people, revs, idx = [], [], {}

    def who(aid):
        if aid not in idx:
            idx[aid] = len(people)
            people.append(accounts.get(aid, (f"account {aid}", False, None))[0])
            r = ident.get(aid)
            revs.append(r if r in mine else None)
        return idx[aid]
    rows = sorted((info[n][3][:10], n, h, tdirs) for h, n, tdirs in cls
                  if n in info and start <= (info[n][3] or "")[:10] <= end and per_cl.get(n))
    doc_cls = []
    for landed, n, h, tdirs in rows:
        project, subject, owner, _, ins = info[n]
        o = who(owner)
        ths = [dict(t, dir=tdirs.get(t["id"]), comments=[[who(aid), at, msg] for aid, at, msg in t["comments"]])
               for t in per_cl[n]]
        doc_cls.append(dict(n=n, half=h, project=project, subject=subject or "", landed=landed,
                            lines=ins, owner=o, threads=ths))
    if not doc_cls:
        return None
    return {"v": VERSION, "from": start, "to": end, "people": people, "reviewers": revs, "cls": doc_cls}


def prune(root, keep):
    """Removes the .json.gz files under root that aren't in keep (the files
    of people no longer published, and the half-year folders of the format
    before v 4), and folders left empty."""
    removed = 0
    for d, _, names in os.walk(root, topdown=False):
        for name in names:
            p = os.path.join(d, name)
            if name.endswith(".json.gz") and p not in keep:
                os.remove(p)
                removed += 1
        if d != root and not os.listdir(d):
            os.rmdir(d)
    return removed


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--end", help="the window's last day, YYYY-MM-DD (default: the newest CL's landing day)")
    ap.add_argument("--cls", help="the Feedback Index's CL index (default <data>/feedback-cls.json.gz)")
    ap.add_argument("--out", help="default <data>/review-threads")
    ap.add_argument("--weeks", type=int, default=WEEKS, help=f"the window's length (default {WEEKS})")
    a = ap.parse_args(argv)
    if a.out is None:
        r2.hold()
    out = a.out or out_dir()
    a.cls = a.cls or os.path.join(store.DATA_DIR, "feedback-cls.json.gz")

    ddb = ro(os.path.join(store.DATA_DIR, store.DERIVED_FILE))
    ldb = ro(classify.labels_path(store.DATA_DIR))
    act = classify.active_classifier(ldb)
    def labels(n):           # one CL's at a time, not all million
        return {(r, h): x for r, h, x in ldb.execute(
            "SELECT root_uuid, input_hash, addressed FROM labels WHERE change_number = ? AND classifier_id = ?",
            (n, act[0]))} if act else {}
    accounts = {aid: (name or email or f"account {aid}", bool(bot), email or None) for aid, name, email, bot in ddb.execute(
        "SELECT account_id, name, email, is_bot FROM accounts WHERE host = ?", (HOST,))}
    # Each account's exact identity, the Feedback Index's (people.exact_identities),
    # and each person's approvers over all their half-years. An account Gerrit shows
    # with no address (a deleted one) but tied to a person's address is that person,
    # not a bot, and is called by their name there when Gerrit gives none.
    ids = exact_identities(ddb, ro(C.db_path()), ro(review_timeline.db_path()))
    for aid in ids.linked:
        name = accounts.get(aid, (None,))[0]
        e = ids.accounts[aid]
        accounts[aid] = (ids.find(e) if name in (None, DELETED_USER, f"account {aid}") else name, False, e)
    bots = {aid for aid, (_, bot, _) in accounts.items() if bot}
    ident = {aid: ids.find(email) for aid, (_, _, email) in accounts.items() if email}
    shards = read_index(a.cls)
    person_revs = {k: {r for cls in by_half.values() for _, revs, _ in cls for r in revs}
                   for k, by_half in shards.items()}

    # The window spans at most weeks / 26 + 2 half-years: only their CLs can be in it.
    recent = sorted({h for by_half in shards.values() for h in by_half})[-(a.weeks // 26 + 2):]
    cand = {k: [(h, n, tdirs) for h in recent for n, _, tdirs in by_half.get(h, ())] for k, by_half in shards.items()}
    info = {}
    ns = sorted({n for cls in cand.values() for _, n, _ in cls})
    for i in range(0, len(ns), 900):
        part = ns[i:i + 900]
        for row in ddb.execute(
                f"SELECT change_number, project, subject, owner_account, closed_at, insertions FROM changes "
                f"WHERE host = ? AND change_number IN ({','.join('?' * len(part))})", (HOST, *part)):
            info[row[0]] = row[1:]
    end = a.end or max((v[3] or "")[:10] for v in info.values())
    start = window(end, a.weeks)
    todo = {k: [c for c in cls if c[1] in info and start <= (info[c[1]][3] or "")[:10] <= end] for k, cls in cand.items()}
    todo = {k: cls for k, cls in todo.items() if cls}
    print(f"CLs landed {start} .. {end}: {len(todo):,} people, {sum(map(len, todo.values())):,} CLs",
          file=sys.stderr, flush=True)

    repos = {}
    keep = set()
    t0 = time.time()
    files = changed = size = threads = 0
    names = sorted(todo)
    # A few thousand CLs' comments in memory at a time.
    batch, batches = [], []
    for k in names:
        batch.append(k)
        if sum(len(todo[x]) for x in batch) >= 3000:
            batches.append(batch)
            batch = []
    if batch:
        batches.append(batch)
    for bi, batch in enumerate(batches):
        ns = sorted({n for k in batch for _, n, _ in todo[k]})
        per_cl = {}
        # Comments, a few hundred CLs per NoteDb batch.
        for i in range(0, len(ns), 300):
            part = ns[i:i + 300]
            notes = prefetch_notedb(repos, [(HOST, info[n][0], n) for n in part], "notedb")
            for n in part:
                per_cl[n] = cl_threads(notes.get(n), info[n][2], bots, addressed_lookup(ddb, labels, n))
        for k in batch:
            doc = person_doc(todo[k], info, per_cl, accounts, ident, person_revs.get(k, set()), start, end)
            if doc is None:
                continue
            path = os.path.join(out, f"{k}.json.gz")
            keep.add(path)
            n_bytes, did = write(path, doc)
            files += 1
            changed += did
            size += n_bytes
            threads += sum(len(c["threads"]) for c in doc["cls"])
        if bi % 10 == 9 or bi == len(batches) - 1:
            print(f"{bi + 1}/{len(batches)} batches: {files:,} files so far, {size / 1e6:.0f} MB gzipped, "
                  f"{time.time() - t0:.0f}s", file=sys.stderr, flush=True)
    removed = prune(out, keep) if os.path.isdir(out) else 0
    print(f"wrote {files:,} files ({changed:,} changed, {removed:,} removed), {threads:,} threads, "
          f"{size / 1e6:.0f} MB gzipped, to {out}", file=sys.stderr)


if __name__ == "__main__":
    from cosh import memcap
    memcap.join()   # about 1.1 GB: take turns in the shared cap (AGENTS.md)
    main()
