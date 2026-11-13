"""Per-CL facts from derived.sqlite and commits.sqlite alone: owner, status,
times, Gerrit size, and for a merged CL its landed commit and the lines and
files it changed per 3-level directory. The Feedback Index (cosh/feedback.py)
reads them, and the balance stage `cl` (cosh/balance.py) builds its `cl` and
`cl_dirs` tables from them, so the two can't drift."""

from collections import defaultdict
from datetime import datetime, timezone

# commits.sqlite's gcommits (commit_id > 0) start here.
SINCE = "2017-01-01"


def epoch(s):
    return int(datetime.strptime(s[:19].replace("T", " "), "%Y-%m-%d %H:%M:%S")
               .replace(tzinfo=timezone.utc).timestamp())


def dir3(path):
    parts = path.split("/")[:-1]
    return "/".join(parts[:3]) + "/" if parts else "(root)/"


CL_FACTS = ("change_number", "owner", "owner_email", "status", "created_at", "closed_at", "close_week",
            "ins", "dels", "patchsets", "sha", "files", "git_lines", "is_revert", "is_reland", "reverted_at")


def cl_facts(ddb, gdb):
    """The first columns of `cl`, CL_FACTS: those that come from
    derived.sqlite (`ddb`) and commits.sqlite (`gdb`) alone. Tuples in
    change-number order, one per human-owned chromium/src `main` CL: the
    owner's address as Gerrit has it, times in unix seconds, and for a merged
    CL its landed commit. Also {commit_id: change_number} of the landed
    commits, for cl_dirs. The Feedback Index (cosh/feedback.py) reads them, and
    the balance stage `cl` builds on them."""
    emails = dict(ddb.execute("SELECT account_id, email FROM accounts"))
    cls = ddb.execute("""SELECT change_number, owner_account, status, created_at, closed_at, close_week,
                                insertions, deletions, patchsets FROM changes
                         WHERE is_bot_owned = 0 AND project = 'chromium/src' AND branch = 'main'""").fetchall()
    landed = {}
    for cid, n, sha, files, ins, dels, rv, rl in gdb.execute(
            "SELECT commit_id, change_number, sha, files, ins, dels, reverts_sha IS NOT NULL, is_reland "
            "FROM gcommits WHERE change_number IS NOT NULL"):
        landed[n] = (cid, sha, files, ins + dels, rv, rl)
    reverted = {}
    for target, at in gdb.execute("SELECT reverts_sha, landed_at FROM gcommits WHERE reverts_sha IS NOT NULL"):
        reverted[target] = min(at, reverted.get(target, at))
    rows = []
    for n, owner, status, created, closed, cweek, ins, dels, nps in sorted(cls):
        lg = landed.get(n) if status == "MERGED" else None
        rows.append((n, owner, emails.get(owner), status, epoch(created), epoch(closed) if closed else None,
                     cweek, ins, dels, nps, *(lg[1:] if lg else (None,) * 5),
                     reverted.get(lg[1]) if lg else None))
    return rows, {v[0]: n for n, v in landed.items()}


def cl_dirs(gdb, by_cid, numbers=None):
    """The cl_dirs table: {(change_number, 3-level directory): [files, lines]}
    of the landed commits in `by_cid` (from cl_facts), only for the CLs in
    `numbers` if given."""
    paths = dict(gdb.execute("SELECT path_id, path FROM paths"))
    agg = defaultdict(lambda: [0, 0])
    for cid, pid, ins, dels in gdb.execute("SELECT commit_id, path_id, ins, dels FROM gfiles"):
        n = by_cid.get(cid)
        if n is None or (numbers is not None and n not in numbers):
            continue
        g = agg[(n, dir3(paths[pid]))]
        g[0] += 1
        g[1] += max(ins, 0) + max(dels, 0)
    return agg
