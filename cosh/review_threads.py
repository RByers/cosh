"""Full review threads per person and half-year, for the Feedback Index's
download (web/feedback-index.html, docs/review-feedback.md, "Downloading
your comments").

For every per-person half-year file the Feedback Index publishes
(web/public/review-feedback/<half>/<key>.json, the person's merged CLs of
that half-year), writes data/private/review-threads/<half>/<key>.json.gz:
every thread a human reviewer other than the owner started on those CLs,
with the full text of every comment in it. The files are too big for git
(400 MB gzipped for all half-years, 2026-11-14), so `cosh.r2 sync` puts
them in the R2 bucket, where the page fetches them only when someone asks
to download their comments. Same keys as the Feedback Index, so they can be
found only by typing the person's address (docs/plan.md, ground rule 5).

Format (v 1), JSON:

  {"v": 1, "half": "2026H1",
   "people": [name, ...],             names (else addresses), indexed below
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
published half-year files, reviews.sqlite, addressed.sqlite and the NoteDb
repos. Files are written byte for byte the same when nothing changed, so
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

from . import classify, store
from .derive import prefetch_notedb

HOST = "chromium-review.googlesource.com"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHARDS = os.path.join(ROOT, "web", "public", "review-feedback")
PATCHSET_LEVEL = "/PATCHSET_LEVEL"
VERSION = 1
HALF = re.compile(r"^\d{4}H[12]$")
KEY = re.compile(r"^[0-9a-f]{32}\.json$")


def out_dir(data_dir=None):
    return os.path.join(data_dir or store.DATA_DIR, "review-threads")


def shard_cls(shard):
    """The change numbers of a published half-year file (each row starts
    with its change number less the previous row's)."""
    n, out = 0, []
    for row in shard["cls"]:
        n += row[0]
        out.append(n)
    return out


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
    data = gzip.compress(json.dumps(doc, separators=(",", ":"), ensure_ascii=False).encode(), mtime=0)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    old = None
    if os.path.exists(path):
        with open(path, "rb") as f:
            old = f.read()
    if old != data:
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    return len(data), old != data


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--half", action="append", help="only these half-years (default: all)")
    ap.add_argument("--shards", default=SHARDS, help="the Feedback Index's published files")
    ap.add_argument("--out", help="default <data>/review-threads")
    a = ap.parse_args(argv)
    out = a.out or out_dir()

    ddb = ro(os.path.join(store.DATA_DIR, store.DERIVED_FILE))
    ldb = ro(classify.labels_path(store.DATA_DIR))
    act = classify.active_classifier(ldb)
    labels = {}
    if act:
        labels = {(n, r, h): x for n, r, h, x in ldb.execute(
            "SELECT change_number, root_uuid, input_hash, addressed FROM labels WHERE classifier_id = ?", (act[0],))}
    accounts = {aid: (name or email or f"account {aid}", bool(bot)) for aid, name, email, bot in ddb.execute(
        "SELECT account_id, name, email, is_bot FROM accounts WHERE host = ?", (HOST,))}
    bots = {aid for aid, (_, bot) in accounts.items() if bot}

    halves = sorted(h for h in os.listdir(a.shards) if HALF.match(h) and (not a.half or h in a.half))
    repos = {}
    keep = set()
    t0 = time.time()
    files = changed = size = threads = 0
    for h in halves:
        todo = {}
        for name in sorted(os.listdir(os.path.join(a.shards, h))):
            if KEY.match(name):
                with open(os.path.join(a.shards, h, name)) as f:
                    todo[name[:-5]] = shard_cls(json.load(f))
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
            people, idx = [], {}

            def who(aid):
                if aid not in idx:
                    idx[aid] = len(people)
                    people.append(accounts.get(aid, (f"account {aid}", False))[0])
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
            n_bytes, did = write(path, dict(v=VERSION, half=h, people=people, cls=doc_cls))
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
