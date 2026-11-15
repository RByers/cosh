"""Per-CL facts from reviews.sqlite and commits.sqlite alone: owner, status,
times, Gerrit size, and for a merged CL its landed commit and the lines and
files it changed per 3-level directory. The Feedback Index (cosh/review_feedback.py)
reads them, and the balance stage `cl` (cosh/balance.py) builds its `cl` and
`cl_dirs` tables from them, so the two can't drift."""

from collections import defaultdict
from datetime import datetime, timezone

from .commits import dir_of

# commits.sqlite's commit_id > 0 starts here.
SINCE = "2017-01-01"


def epoch(s):
    """Seconds since 1970 of 'YYYY-MM-DD HH:MM:SS' (or with a T), UTC; the
    rest of the string is ignored."""
    s = s[:19].replace("T", " ")
    if len(s) == 19 and s[4] == s[7] == "-" and s[13] == s[16] == ":" and s[10] == " " and s.isascii():
        try:                     # fromisoformat is much faster; same result for this form
            return int(datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp())
        except ValueError:
            pass
    return int(datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp())


CL_FACTS = ("change_number", "owner", "owner_email", "status", "created_at", "closed_at", "close_week",
            "ins", "dels", "patchsets", "sha", "files", "git_lines", "is_revert", "is_reland", "reverted_at")


def cl_facts(ddb, gdb):
    """The first columns of `cl`, CL_FACTS: those that come from
    reviews.sqlite (`ddb`) and commits.sqlite (`gdb`) alone. Tuples in
    change-number order, one per human-owned chromium/src `main` CL: the
    owner's address as Gerrit has it, times in unix seconds, and for a merged
    CL its landed commit. Also {commit_id: change_number} of the landed
    commits, for cl_dirs. The balance stage `cl` builds on them;
    the Feedback Index (cosh/review_feedback.py) reads them one at a time
    (`iter_cl_facts`)."""
    rows, by_cid = iter_cl_facts(ddb, gdb)
    return list(rows), by_cid


def iter_cl_facts(ddb, gdb):
    """`cl_facts`, the tuples as an iterator, so a caller that keeps a few
    of their columns never holds them all (a million CLs)."""
    emails = dict(ddb.execute("SELECT account_id, email FROM accounts"))
    cls = ddb.execute("""SELECT change_number, owner_account, status, created_at, closed_at, close_week,
                                insertions, deletions, patchsets FROM changes
                         WHERE is_bot_owned = 0 AND project = 'chromium/src' AND branch = 'main'""").fetchall()
    cls.sort()
    landed = {}
    for cid, n, sha, files, ins, dels, rv, rl in gdb.execute(
            "SELECT commit_id, change_number, sha, files, ins, dels, reverts_sha IS NOT NULL, is_reland "
            "FROM commits WHERE commit_id > 0 AND change_number IS NOT NULL"):
        landed[n] = (cid, sha, files, ins + dels, rv, rl)
    reverted = {}
    for target, at in gdb.execute("SELECT reverts_sha, landed_at FROM commits WHERE commit_id > 0 AND reverts_sha IS NOT NULL"):
        reverted[target] = min(at, reverted.get(target, at))
    by_cid = {v[0]: n for n, v in landed.items()}

    def rows():
        for n, owner, status, created, closed, cweek, ins, dels, nps in cls:
            lg = landed.get(n) if status == "MERGED" else None
            yield (n, owner, emails.get(owner), status, epoch(created), epoch(closed) if closed else None,
                   cweek, ins, dels, nps, *(lg[1:] if lg else (None,) * 5),
                   reverted.get(lg[1]) if lg else None)
    return rows(), by_cid


def cl_dirs(gdb, by_cid, numbers=None, dels=True, current=None, moved=None):
    """The cl_dirs table: {(change_number, 3-level directory): [files, lines]}
    of the landed commits in `by_cid` (from cl_facts), only for the CLs in
    `numbers` if given. Lines are insertions plus deletions, or insertions
    alone without `dels` (the Feedback Index's lines). With `current`
    (commits.current_paths), files count in today's directories; with
    `moved` (commits.moved_lines), a renamed file by the lines changed
    between its two names, as Gerrit counts a CL's lines."""
    # Each path's directory, worked out once and shared by every row there.
    dirs, uniq = {}, {}
    for k, v in gdb.execute("SELECT path_id, path FROM paths"):
        d = dir_of(current.get(v, v) if current else v, 3)
        dirs[k] = uniq.setdefault(d, d)
    del uniq
    agg = defaultdict(lambda: [0, 0])
    for cid, pid, ins, d in gdb.execute("SELECT commit_id, path_id, ins, dels FROM commit_files WHERE commit_id > 0"):
        n = by_cid.get(cid)
        if n is None or (numbers is not None and n not in numbers):
            continue
        if moved:
            ins, d = moved.get((cid, pid), (ins, d))
        g = agg[(n, dirs[pid])]
        g[0] += 1
        lines = max(ins, 0) + (max(d, 0) if dels else 0)
        g[1] += lines
    return agg
