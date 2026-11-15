"""Full review threads per person and half-year, for the Feedback Index's
download (web/feedback-index.html, docs/review-feedback.md, "Downloading
your comments").

For every per-person half-year file the Feedback Index publishes
(data/private/feedback-people/<half>/<key>.json.gz, the person's merged CLs
of that half-year, which cosh.r2 publishes), writes data/private/review-threads/<half>/<key>.json.gz:
every thread a human reviewer other than the owner started on those CLs,
with the full text of every comment in it. The files are too big for git
(400 MB gzipped for all half-years, 2026-11-14), so `cosh.r2 sync` puts
them in the R2 bucket, where the page fetches them only when someone asks
to download their comments. Same keys as the Feedback Index, so they can be
found only by typing the person's address (docs/plan.md, ground rule 5).

Format (v 2), JSON:

  {"v": 2, "half": "2026H1",
   "people": [name, ...],             names (else addresses), indexed below
   "reviewers": [approver or null, ...]  per person, same order (v 2): the
                                      approver, as the person's half-year
                                      files name approvers (`revs`), that
                                      this Gerrit account is (`approver_of`)
   "cls": [{"n": change number, "project": ..., "subject": ...,
            "landed": "YYYY-MM-DD", "lines": Gerrit's insertions,
            "owner": people index,
            "threads": [{"id": root comment uuid, "path": file,
                         "/COMMIT_MSG" or "/PATCHSET_LEVEL", "line": n or null,
                         "ps": patch set, "addressed": true/false/null
                         (null: CL-level, or no label yet), "resolved": bool,
                         "comments": [[people index, "YYYY-MM-DDTHH:MMZ",
                                       text], ...]}, ...]}, ...]}

CLs oldest first, threads by their first comment. Offline: reads the
published half-year files, reviews.sqlite, addressed.sqlite, commits.sqlite
(Reviewed-by) and the NoteDb repos. Files are written byte for byte the same when nothing changed, so
`cosh.r2 sync` uploads only what did.

  COSH_DATA_DIR=<main>/data/private nice -n 5 python3 -m cosh.review_threads [--half 2026H2 ...]
"""

import argparse
import gzip
import json
import os
import re
import sqlite3
import sys
import time
from collections import defaultdict

from . import classify, r2, store
from . import commits as C
from .people import person
from .derive import prefetch_notedb

HOST = "chromium-review.googlesource.com"
PATCHSET_LEVEL = "/PATCHSET_LEVEL"
VERSION = 2
HALF = re.compile(r"^\d{4}H[12]$")
KEY = re.compile(r"^[0-9a-f]{32}\.json\.gz$")


def out_dir(data_dir=None):
    return r2.local_dir("review-threads", data_dir)


def shard_cls(shard):
    """The change numbers of a published half-year file (each row starts
    with its change number less the previous row's)."""
    n, out = 0, []
    for row in shard["cls"]:
        n += row[0]
        out.append(n)
    return out


def shard_revs(shard):
    """(change number, its approvers as the file names them) per CL of a
    published half-year file."""
    return [(n, [shard["revs"][i] for i in row[5]]) for n, row in zip(shard_cls(shard), shard["cls"])]


def approver_of(person_cls, reviewed_by, by_email):
    """Gerrit account id -> approver, for one person's changes: an account
    is the approver whose Reviewed-by address on one of those changes is
    exactly its Gerrit address (Gerrit writes the voter's preferred address
    there). `person_cls`: [(change number, approvers as the half-year files
    name them)]; `reviewed_by`: change number -> its raw Reviewed-by
    addresses; `by_email`: lowercased Gerrit address -> account ids.

    The half-year files name approvers by the Feedback Index's identities,
    which `people.person` folds across chromium.org and google.com; an
    address is tied to the approver it folds to, on that change only, so
    the link to the account stays exact. An account tied to two approvers
    is left out."""
    out = {}
    for n, revs in person_cls:
        for e in reviewed_by.get(n, ()):
            rev = person(e)
            if rev not in revs:
                continue
            for aid in by_email.get(e.lower(), ()):
                out[aid] = rev if out.get(aid, rev) == rev else None
    return {aid: rev for aid, rev in out.items() if rev is not None}


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
    Done-type regex is, else the active Haiku label."""
    got = {}
    for root, reply, rx, h in ddb.execute(
            "SELECT root_uuid, last_owner_reply_at, regex_addressed, input_hash FROM threads "
            "WHERE host = ? AND change_number = ?", (HOST, n)):
        if reply is None:
            got[root] = False
        elif rx:
            got[root] = True
        else:
            a = labels.get((n, root, h))
            got[root] = None if a is None else bool(a)
    return lambda root: got.get(root)


def write(path, doc):
    """Writes gzipped JSON, byte for byte the same for the same doc."""
    return r2.write_gz(path, json.dumps(doc, separators=(",", ":"), ensure_ascii=False))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--half", action="append", help="only these half-years (default: all)")
    ap.add_argument("--shards", help="the Feedback Index's per-person files (default <data>/feedback-people)")
    ap.add_argument("--out", help="default <data>/review-threads")
    a = ap.parse_args(argv)
    if a.out is None:
        r2.hold()
    out = a.out or out_dir()
    a.shards = a.shards or r2.local_dir("feedback-people")

    ddb = ro(os.path.join(store.DATA_DIR, store.DERIVED_FILE))
    ldb = ro(classify.labels_path(store.DATA_DIR))
    act = classify.active_classifier(ldb)
    labels = {}
    if act:
        labels = {(n, r, h): x for n, r, h, x in ldb.execute(
            "SELECT change_number, root_uuid, input_hash, addressed FROM labels WHERE classifier_id = ?", (act[0],))}
    accounts = {aid: (name or email or f"account {aid}", bool(bot), email or None) for aid, name, email, bot in ddb.execute(
        "SELECT account_id, name, email, is_bot FROM accounts WHERE host = ?", (HOST,))}
    bots = {aid for aid, (_, bot, _) in accounts.items() if bot}
    by_email = defaultdict(list)
    for aid, (_, _, email) in accounts.items():
        if email:
            by_email[email.lower()].append(aid)

    # Each person's approvers over all their half-years, tied to Gerrit
    # accounts through the Reviewed-by addresses (`approver_of`).
    person_cls = defaultdict(list)
    for h in sorted(x for x in os.listdir(a.shards) if HALF.match(x)):
        for name in sorted(os.listdir(os.path.join(a.shards, h))):
            if KEY.match(name):
                with gzip.open(os.path.join(a.shards, h, name), "rt") as f:
                    person_cls[name[:-8]].extend(x for x in shard_revs(json.load(f)) if x[1])
    want = {n for cls in person_cls.values() for n, _ in cls}
    reviewed_by = {}
    for n, rb in ro(C.db_path()).execute("SELECT change_number, reviewed_by FROM commits "
                                         "WHERE change_number IS NOT NULL AND reviewed_by IS NOT NULL"):
        if n in want:
            reviewed_by[n] = json.loads(rb)

    halves = sorted(h for h in os.listdir(a.shards) if HALF.match(h) and (not a.half or h in a.half))
    repos = {}
    keep = set()
    t0 = time.time()
    files = changed = size = threads = 0
    for h in halves:
        todo = {}
        for name in sorted(os.listdir(os.path.join(a.shards, h))):
            if KEY.match(name):
                with gzip.open(os.path.join(a.shards, h, name), "rt") as f:
                    todo[name[:-8]] = shard_cls(json.load(f))
        info = {}
        ns = sorted({n for cls in todo.values() for n in cls})
        for i in range(0, len(ns), 900):
            part = ns[i:i + 900]
            for row in ddb.execute(
                    f"SELECT change_number, project, subject, owner_account, closed_at, insertions FROM changes "
                    f"WHERE host = ? AND change_number IN ({','.join('?' * len(part))})", (HOST, *part)):
                info[row[0]] = row[1:]
        # Comments, a few hundred CLs per NoteDb batch.
        per_cl = {}
        for i in range(0, len(ns), 300):
            part = [n for n in ns[i:i + 300] if n in info]
            notes = prefetch_notedb(repos, [(HOST, info[n][0], n) for n in part], "notedb")
            for n in part:
                project, _, owner, _, _ = info[n]
                per_cl[n] = cl_threads(notes.get(n), owner, bots, addressed_lookup(ddb, labels, n))
        for k, cls in todo.items():
            people, revs, idx = [], [], {}
            approvers = approver_of(person_cls.get(k, ()), reviewed_by, by_email)

            def who(aid):
                if aid not in idx:
                    idx[aid] = len(people)
                    people.append(accounts.get(aid, (f"account {aid}", False, None))[0])
                    revs.append(approvers.get(aid))
                return idx[aid]
            doc_cls = []
            for n in cls:
                if n not in info:
                    continue
                project, subject, owner, closed, ins = info[n]
                ths = [dict(t, comments=[[who(aid), at, msg] for aid, at, msg in t["comments"]])
                       for t in per_cl.get(n, [])]
                threads += len(ths)
                doc_cls.append(dict(n=n, project=project, subject=subject or "", landed=(closed or "")[:10],
                                    lines=ins, owner=who(owner), threads=ths))
            path = os.path.join(out, h, f"{k}.json.gz")
            keep.add(path)
            n_bytes, did = write(path, dict(v=VERSION, half=h, people=people, reviewers=revs, cls=doc_cls))
            files += 1
            changed += did
            size += n_bytes
        print(f"{h}: {len(todo):,} people, {len(ns):,} CLs; {files:,} files so far, {size / 1e6:.0f} MB gzipped, "
              f"{time.time() - t0:.0f}s", file=sys.stderr, flush=True)
    # Files of people or half-years no longer published go.
    removed = 0
    for h in halves:
        d = os.path.join(out, h)
        for name in os.listdir(d) if os.path.isdir(d) else ():
            p = os.path.join(d, name)
            if p not in keep:
                os.remove(p)
                removed += 1
    print(f"wrote {files:,} files ({changed:,} changed, {removed:,} removed), {threads:,} threads, "
          f"{size / 1e6:.0f} MB gzipped, to {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
