"""Exploratory: which review threads led to a code change? (docs/review-impact.md)

Offline only. Reads derived.sqlite (read-only) and the stored NoteDb meta refs;
fetches nothing. For each sampled CL it rebuilds:
  - the patch-set timeline from the meta ref's commits, with Gerrit's own
    change-kind note on each upload ("Uploaded patch set N." = rework;
    "... was rebased." / "same tree" / "Commit message was updated." = no
    code change);
  - the comment threads from the notes blobs (parentUuid chains), with each
    comment's unresolved flag, file, line range and text.

Writes one JSON line per reviewer-started thread to --out.

  COSH_DATA_DIR=... python3 scripts/review_impact.py --weeks 2026-W36:2026-W44 --out threads.jsonl
"""

import argparse
import json
import os
import random
import re
import sqlite3
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cosh import orgs, paths, store  # noqa: E402


class CatFile:
    """One persistent `git cat-file --batch` process."""

    def __init__(self, git_dir):
        self.p = subprocess.Popen(["git", "--git-dir", git_dir, "cat-file", "--batch"],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    def get(self, spec):
        self.p.stdin.write(spec.encode() + b"\n")
        self.p.stdin.flush()
        hdr = self.p.stdout.readline().split()
        if hdr[-1] == b"missing":
            return None, None
        size = int(hdr[2])
        data = self.p.stdout.read(size + 1)[:-1]
        return hdr[1].decode(), data


def tree_blobs(cf, sha):
    _, data = cf.get(sha)
    i, out = 0, []
    while data and i < len(data):
        sp = data.index(b" ", i)
        nul = data.index(b"\0", sp)
        mode, h = data[i:sp], data[nul + 1:nul + 21].hex()
        i = nul + 21
        out.extend(tree_blobs(cf, h) if mode == b"40000" else [h])
    return out


GERRIT_USER = re.compile(r"^Gerrit User (\d+) <")


def kind_of(upload_line):
    rest = upload_line.split(":", 1)[1] if ":" in upload_line else ""
    if "same tree, parent tree" in rest:
        return "no_change"
    if "was rebased" in rest:
        return "rebase"          # trivial rebase (Gerrit's TRIVIAL_REBASE)
    if "Commit message was updated" in rest:
        return "message_only"
    return "rework"              # code changed (REWORK or merge update)


def timeline(cf, n):
    """Patch-set uploads [(ps, iso_time, uploader_id, kind, description)] and
    the abandon time, from the meta ref's commits."""
    _, data = cf.get(f"refs/meta/{n}")
    if data is None:
        return None, None
    uploads, abandoned_at = [], None
    seen = 0
    while data is not None and seen < 5000:
        seen += 1
        head, _, body = data.decode("utf-8", "replace").partition("\n\n")
        parent = re.search(r"^parent (\w+)", head, re.M)
        author = re.search(r"^author Gerrit User (\d+) <[^>]*> (\d+)", head, re.M)
        first = body.split("\n", 1)[0]
        if (first == "Create change" or first.startswith("Create patch set")) and author:
            ps = re.search(r"^Patch-set: (\d+)", body, re.M)
            up = re.search(r"^Uploaded patch set \d+.*$", body, re.M)
            d = re.search(r"^Patch-set-description: (.*)$", body, re.M)
            kind = "initial" if first == "Create change" else kind_of(up.group(0) if up else "")
            uploads.append((int(ps.group(1)) if ps else 0, int(author.group(2)), int(author.group(1)),
                            kind, d.group(1) if d else ""))
        if re.search(r"^Status: abandoned", body, re.M) and abandoned_at is None and author:
            abandoned_at = int(author.group(2))
        if not parent:
            break
        _, data = cf.get(parent.group(1))
    uploads.sort()
    return uploads, abandoned_at


def epoch(iso):   # '2026-09-24T09:05:11Z'
    from datetime import datetime, timezone
    return int(datetime.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp())


def comments(cf, n):
    _, tree = cf.get(f"refs/meta/{n}^{{tree}}")
    if tree is None:
        return []
    out = []
    for h in tree_blobs(cf, f"refs/meta/{n}^{{tree}}"):
        _, blob = cf.get(h)
        try:
            doc = json.loads(blob)
        except (ValueError, TypeError):
            continue
        for c in doc.get("comments", []):
            k = c.get("key", {})
            out.append(dict(uuid=k.get("uuid"), parent=c.get("parentUuid"), ps=k.get("patchSetId"),
                            file=k.get("filename", ""), line=c.get("lineNbr", 0), range=c.get("range"),
                            author=c.get("author", {}).get("id"), t=epoch(c.get("writtenOn", "1970-01-01T00:00:00")),
                            unresolved=bool(c.get("unresolved")), msg=c.get("message", ""),
                            tag=c.get("tag", ""), is_ai=bool(c.get("isAi")),
                            fix=bool(c.get("fixSuggestions"))))
    out.sort(key=lambda c: (c["t"], c["uuid"]))
    return out


def threads(cs):
    by = {c["uuid"]: c for c in cs}

    def root(c):
        seen = set()
        while c["parent"] and c["parent"] in by and c["uuid"] not in seen:
            seen.add(c["uuid"])
            c = by[c["parent"]]
        return c["uuid"]
    th = {}
    for c in cs:
        th.setdefault(root(c), []).append(c)
    return th


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weeks", default="2026-W36:2026-W44", help="close-week range a:b")
    ap.add_argument("--sample", type=int, default=0, help="random sample of N CLs (0 = all)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    lo, hi = a.weeks.split(":")
    db = sqlite3.connect(f"file:{os.path.join(store.DATA_DIR, 'derived.sqlite')}?mode=ro", uri=True)
    accts = {aid: (email, bot) for aid, email, bot in db.execute("SELECT account_id, email, is_bot FROM accounts")}
    cls = db.execute("""SELECT change_number, owner_account, status, closed_at, anchor_path, subject,
                               insertions, deletions FROM changes
                        WHERE is_bot_owned=0 AND total_comment_count>0 AND close_week BETWEEN ? AND ?""",
                     (lo, hi)).fetchall()
    if a.sample:
        random.seed(a.seed)
        cls = random.sample(cls, min(a.sample, len(cls)))
    resolve, scope = orgs.OrgResolver(), paths.load_scope()
    cf = CatFile(os.path.join(store.DATA_DIR, "notedb", "chromium_src.git"))
    nthreads = 0
    with open(a.out, "w") as fh:
        for i, (n, owner, status, closed_at, anchor, subject, ins, dels) in enumerate(cls):
            uploads, abandoned_at = timeline(cf, n)
            if uploads is None:
                continue
            cs = comments(cf, n)
            for rid, th in threads(cs).items():
                r = th[0]
                email, bot = accts.get(r["author"], (None, 1))
                if r["author"] == owner or bot or r["tag"].startswith("autogenerated:"):
                    continue
                placed = paths.place(r["file"], anchor)
                rework_after = [u for u in uploads if u[1] > r["t"] and u[3] == "rework"]
                # owner side: the owner plus anyone who uploaded a patch set (co-authors)
                owner_side = {owner} | {u[2] for u in uploads}
                if r["author"] in owner_side:
                    continue
                owner_replies = [c for c in th[1:] if c["author"] in owner_side]
                fr = owner_replies[0] if owner_replies else None
                rec = dict(
                    cl=n, status=status, ins=ins, dels=dels, cl_patchsets=len(uploads),
                    reviewer=r["author"], org=resolve(email, closed_at), file=r["file"],
                    in_scope=bool(placed and scope.includes(placed)),
                    ps=r["ps"], cl_max_ps=max((u[0] for u in uploads), default=0),
                    root_unresolved=r["unresolved"], root_msg=r["msg"], root_fix=r["fix"],
                    root_ai=r["is_ai"], line=r["line"],
                    n_comments=len(th), n_reviewer_comments=sum(c["author"] == r["author"] for c in th),
                    final_unresolved=th[-1]["unresolved"],
                    owner_reply=fr["msg"] if fr else None,
                    owner_reply_dt=(fr["t"] - r["t"]) if fr else None,
                    owner_reply_ps=fr["ps"] if fr else None,
                    owner_replies=[c["msg"][:300] for c in owner_replies[:3]],
                    others=[(c["author"] in owner_side, c["msg"][:300]) for c in th[1:6]],
                    rework_after=len(rework_after),
                    next_rework_dt=(rework_after[0][1] - r["t"]) if rework_after else None,
                    next_rework_desc=rework_after[0][4] if rework_after else None,
                    # gap between the owner's first reply and the nearest rework upload
                    reply_upload_gap=(min(abs(u[1] - fr["t"]) for u in rework_after) if fr and rework_after else None),
                    abandoned_after=bool(abandoned_at and abandoned_at > r["t"]),
                    subject=subject,
                    owner=owner, owner_org=resolve(accts.get(owner, (None, 1))[0], closed_at),
                    root_t=r["t"], reply_t=fr["t"] if fr else None, range=r["range"],
                    # the rework upload nearest the owner's first reply (attribution round)
                    reply_upload_ps=(min(rework_after, key=lambda u: abs(u[1] - fr["t"]))[0]
                                     if fr and rework_after else None),
                    uploads=[(u[0], u[1], u[3]) for u in uploads],
                )
                fh.write(json.dumps(rec) + "\n")
                nthreads += 1
            if i % 2000 == 0:
                print(f"{i}/{len(cls)} CLs, {nthreads} threads", file=sys.stderr)
    print(f"{len(cls)} CLs, {nthreads} reviewer threads -> {a.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
