"""Who is who in Chromium's git history and Gerrit, two ways:

- `person` folds chromium.org into google.com (user@chromium.org and
  user@google.com are one person), which is right for nearly everyone but
  not always. The analyses in scripts/ use it.
- `exact_identities` merges addresses only on evidence: a git author whose
  CLs are mostly owned in Gerrit by one address (`alias_pairs`), and a
  Reviewed-by address that is no Gerrit account's but whose CLs' approving
  vote came from one account (`vote_links`). The published pages use it
  (the Feedback Index, Review Load and the threads behind them; the user's
  call, 2026-11-14).

Also bot addresses (config/bots.txt)."""

import calendar
import json
import time
from collections import Counter, defaultdict
from functools import cache

from .bots import _PATTERNS


@cache            # pure, and called millions of times per analysis
def person(e):
    """One identity per person across Chromium's two common domains: many
    people author as user@chromium.org and review as user@google.com."""
    e = (e or "").lower()
    if e.count("@") > 1:            # SVN-era author: user@domain@<repository uuid>
        e = e.rsplit("@", 1)[0]
    local, _, dom = e.partition("@")
    return f"{local}@google.com" if dom in ("chromium.org", "google.com") else e


@cache
def address(e):
    """An address as written, lower case, an SVN-era author's repository
    uuid dropped; no domains merged (`exact_identities`)."""
    e = (e or "").strip().lower()
    if e.count("@") > 1:
        e = e.rsplit("@", 1)[0]
    return e


@cache
def is_bot_email(e):
    """True for a missing address or one config/bots.txt matches."""
    return not e or any(p.search(e) for p in _PATTERNS)


class Ids:
    """Union-find over emails, each normalised by `norm` first: `person`
    (Chromium's two domains merged; the default, for scripts/) or `address`
    (exact). Callers union the aliases they have evidence for.

    An identity is named by one of its addresses (`find`): with `latest`
    (address -> when it was last used), the most recently used one, so
    someone who changed their address is always called by their current
    one, never the one they left behind (docs/goals.md, goal 2); without
    it, or on a tie, the alphabetically first."""

    def __init__(self, norm=person, latest=None):
        self.p = {}
        self.norm = norm
        self.latest = latest or {}

    def find(self, e):
        e = self.norm(e)
        self.p.setdefault(e, e)
        while self.p[e] != e:
            self.p[e] = self.p[self.p[e]]
            e = self.p[e]
        return e

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            keep = min((ra, rb), key=lambda e: (-self.latest.get(e, 0), e))
            self.p[rb if keep == ra else ra] = keep

    def groups(self):
        """{identity: every address merged into it}, over the addresses seen."""
        out = defaultdict(set)
        for e in list(self.p):
            out[self.find(e)].add(e)
        return out


def alias_pairs(cls, commits, min_cls=3, min_share=0.5, norm=person):
    """(owner email, git author email) pairs to treat as one person: the git
    author's CLs are mostly (>= min_share, >= min_cls) owned in Gerrit by
    that address. A single CL whose owner differs from its author (someone
    landing another person's CL, a copybara import) is not evidence: merging
    on those once chained ~400 people into one identity (2026-11-08)."""
    by_n = {c["n"]: c for c in commits if c["n"]}
    own = defaultdict(Counter)
    for c in cls:
        g = by_n.get(c["change_number"])
        if g and c["owner_email"] and not is_bot_email(c["owner_email"]):
            own[norm(g["email"])][norm(c["owner_email"])] += 1
    out = []
    for b, cnt in own.items():
        tot = sum(cnt.values())
        for a, n in cnt.items():
            if a != b and n >= min_cls and n / tot >= min_share:
                out.append((a, b))
    return out


def vote_links(reviewed_by, account_email, voters, min_cls=2, min_share=0.5):
    """(Reviewed-by address, Gerrit account address) pairs to treat as one
    person, for Reviewed-by addresses that are no account's address (the
    reviewer changed their preferred address since; Gerrit writes the
    voter's then preferred address in the trailer). On a CL with exactly one
    such address and exactly one approving voter whose address isn't in its
    Reviewed-by, the two are linked; an address is linked to the account it
    is linked to on at least `min_cls` CLs and `min_share` of its CLs.

    `reviewed_by`: [(change number, [addresses])]; `account_email`: account
    id -> address; `voters`: change number -> account ids that voted
    Code-Review +1 or +2."""
    known = {address(e) for e in account_email.values() if e}
    seen, got = Counter(), defaultdict(Counter)
    for n, rb in reviewed_by:
        rb = [address(e) for e in rb]
        miss = [e for e in rb if e not in known and not is_bot_email(e)]
        for e in miss:
            seen[e] += 1
        if len(miss) != 1:
            continue
        free = [address(account_email[v]) for v in voters.get(n, ())
                if account_email.get(v) and address(account_email[v]) not in rb]
        if len(free) == 1 and not is_bot_email(free[0]):
            got[miss[0]][free[0]] += 1
    out = []
    for e, cnt in got.items():
        a, k = cnt.most_common(1)[0]
        if k >= min_cls and k / seen[e] >= min_share:
            out.append((e, a))
    return out


def exact_identities(ddb, gdb, tdb=None, host="chromium-review.googlesource.com"):
    """An `Ids` over exact addresses (`address`), with the merges there is
    evidence for: `alias_pairs` (a git author and the Gerrit owner of most
    of their CLs) and, given review-timeline.sqlite (`tdb`), `vote_links`.
    `ddb`: reviews.sqlite; `gdb`: commits.sqlite. The Feedback Index, Review
    Load and the comment threads all call this, so they agree on who is who."""
    account_email = dict(ddb.execute("SELECT account_id, email FROM accounts WHERE host = ?", (host,)))
    owners = [dict(change_number=n, owner_email=account_email.get(o)) for n, o in ddb.execute(
        "SELECT change_number, owner_account FROM changes WHERE host = ? AND status = 'MERGED' "
        "AND is_bot_owned = 0 AND project = 'chromium/src' AND branch = 'main'", (host,))]
    # When each address was last used, to name an identity by its newest
    # (`Ids`): git authorship and Reviewed-by trailers by landing time; an
    # account's address by its owned CLs' last update and its newest
    # Code-Review vote (Gerrit reports only an account's current address, so
    # it carries the account's whole history).
    latest = defaultdict(int)

    def used(e, at):
        if e and at:
            e = address(e)
            latest[e] = max(latest[e], int(at))
    authors, reviewed_by = [], []
    for n, email, bot, rb, at in gdb.execute(
            "SELECT change_number, author_email, is_bot, reviewed_by, landed_at FROM commits "
            "WHERE commit_id > 0 AND change_number IS NOT NULL"):
        if not bot and not is_bot_email(email):
            authors.append(dict(n=n, email=email))
            used(email, at)
        if rb:
            reviewed_by.append((n, json.loads(rb)))
            for e in reviewed_by[-1][1]:
                used(e, at)
    for o, at in ddb.execute("SELECT owner_account, max(updated_at) FROM changes WHERE host = ? "
                             "GROUP BY owner_account", (host,)):
        if at:
            used(account_email.get(o), calendar.timegm(time.strptime(at[:19], "%Y-%m-%d %H:%M:%S")))
    if tdb is not None:
        for table in ("votes", "listing_votes"):
            for v, at in tdb.execute(f"SELECT voter, max(at) FROM {table} GROUP BY voter"):
                used(account_email.get(v), at)
    ids = Ids(address, latest)
    for a, b in alias_pairs(owners, authors, norm=address):
        ids.union(a, b)
    if tdb is not None:
        voters = defaultdict(set)
        for table in ("votes", "listing_votes"):
            for n, v in tdb.execute(f"SELECT change_number, voter FROM {table} WHERE value > 0"):
                voters[n].add(v)
        for a, b in vote_links(reviewed_by, account_email, voters):
            ids.union(a, b)
    return ids

