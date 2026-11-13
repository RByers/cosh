"""What the user has approved fetching (config/approved.json).

Fetchers call these before any request, so the bound is enforced by the
command, not only stated in CLAUDE.md. A request outside it stops with an
error naming the file; the fix is the user's approval and an edit to it.
"""

import json
import os

PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "approved.json")


class NotApproved(SystemExit):
    pass


def load(path=PATH):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _week_key(w):
    y, n = w.split("-W")
    return int(y), int(n)


def check_weeks(weeks, path=PATH):
    """Refuse Gerrit weeks ('2026-W44') outside gerrit_weeks."""
    r = load(path)["gerrit_weeks"]
    lo, hi = _week_key(r["from"]), _week_key(r["to"])
    bad = [w for w in weeks if not lo <= _week_key(w) <= hi]
    if bad:
        raise NotApproved(f"not approved: {', '.join(bad[:5])}{' …' if len(bad) > 5 else ''} "
                          f"(config/approved.json allows {r['from']} .. {r['to']}; "
                          "fetching more needs the user's approval first)")


def patchsets_range(since=None, path=PATH):
    """(since, until) dates for the patch-set fetch; refuses a `since` before
    the approved one."""
    r = load(path)["patchsets"]
    since = since or r["since"]
    if since < r["since"]:
        raise NotApproved(f"not approved: patch sets since {since} (config/approved.json allows "
                          f"{r['since']} .. {r['until']}; earlier needs the user's approval first)")
    return since, r["until"]


def bug_footers_since(path=PATH):
    return load(path)["bug_footers"]["since"]
