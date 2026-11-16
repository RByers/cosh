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
        self.accounts, self.linked = {}, set()     # set by exact_identities

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
    return _alias_out(own, min_cls, min_share)


def _alias_out(own, min_cls=3, min_share=0.5):
    """`alias_pairs` from its counts: {author: {owner address: CLs}}."""
    out = []
    for b, cnt in own.items():
        tot = sum(cnt.values())
        for a, n in cnt.items():
            if a != b and n >= min_cls and n / tot >= min_share:
                out.append((a, b))
    return out


def vote_links(reviewed_by, account_email, voters, min_cls=2, min_share=0.5):
    """(Reviewed-by address, Gerrit account) pairs to treat as one person,
    for Reviewed-by addresses that are no account's address. Gerrit writes
    the voter's then preferred address in the trailer, so either the
    reviewer changed their preferred address since, or their account has
    none now (Gerrit shows no address for a deleted account). On a CL with
    exactly one such address and exactly one approving voter whose address
    isn't in its Reviewed-by, the two are linked; an address is linked to
    the account it is linked to on at least `min_cls` CLs and `min_share`
    of its CLs. The account is given by its address, or by its id (an int)
    when it has none.

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
        free = [address(account_email[v]) if account_email.get(v) else v for v in voters.get(n, ())
                if not account_email.get(v) or address(account_email[v]) not in rb]
        if len(free) == 1 and not (isinstance(free[0], str) and is_bot_email(free[0])):
            got[miss[0]][free[0]] += 1
    out = []
    for e, cnt in got.items():
        a, k = cnt.most_common(1)[0]
        if k >= min_cls and k / seen[e] >= min_share:
            out.append((e, a))
    return out


def owner_links(owned, account_email, min_cls=3, min_share=0.5):
    """{account id: git author address} for accounts with no address: the
    one author of at least `min_cls` and `min_share` of the merged CLs the
    account owns. `owned`: [(owner account, git author address)]."""
    by = defaultdict(Counter)
    for o, a in owned:
        if not account_email.get(o) and a and not is_bot_email(a):
            by[o][address(a)] += 1
    return _owner_out(by, min_cls, min_share)


def _owner_out(by, min_cls=3, min_share=0.5):
    """`owner_links` from its counts: {account: {author address: CLs}}."""
    out = {}
    for o, cnt in by.items():
        a, k = cnt.most_common(1)[0]
        if k >= min_cls and k / sum(cnt.values()) >= min_share:
            out[o] = a
    return out


def linked_accounts(ddb, gdb, tdb, host="chromium-review.googlesource.com"):
    """`exact_identities(ddb, gdb, tdb).linked` without loading all of history:
    the accounts with no address that `vote_links` or `owner_links` tie to
    one. Only those accounts' votes and owned CLs are read in full; commits'
    Reviewed-by trailers are streamed from SQLite twice, keeping only the
    addresses that can link to them. About 60 MB, against 1.1 GB for
    `exact_identities` then, 135 MB once it streamed too (2026-11-15)."""
    account_email = dict(ddb.execute("SELECT account_id, email FROM accounts WHERE host = ?", (host,)))
    bare = {a for a, e in account_email.items() if not e}
    known = {address(e) for e in account_email.values() if e}

    def misses(rb):
        rb = [address(e) for e in rb]
        return rb, [e for e in rb if e not in known and not is_bot_email(e)]

    def voters_of(numbers):
        out = defaultdict(set)
        nums = sorted(numbers)
        for i in range(0, len(nums), 500):
            part = nums[i:i + 500]
            for table in ("votes", "listing_votes"):
                for n, v in tdb.execute(f"SELECT change_number, voter FROM {table} WHERE value > 0 AND change_number "
                                        f"IN ({','.join('?' * len(part))})", part):
                    out[n].add(v)
        return out

    def free_voters(n, rb, voters):
        return [address(account_email[v]) if account_email.get(v) else v for v in voters.get(n, ())
                if not account_email.get(v) or address(account_email[v]) not in rb]

    def trailers():
        for n, rb in gdb.execute("SELECT change_number, reviewed_by FROM commits WHERE commit_id > 0 "
                                 "AND change_number IS NOT NULL AND reviewed_by IS NOT NULL"):
            yield n, json.loads(rb)

    found = set()
    # Votes: only an address missing from every account, on a CL where an account with no address
    # approved, can link to one; then that address's every CL decides (vote_links' rule).
    their_cls = set()
    for table in ("votes", "listing_votes"):
        for n, v in tdb.execute(f"SELECT change_number, voter FROM {table} WHERE value > 0"):
            if v in bare:
                their_cls.add(n)
    voters = voters_of(their_cls)
    candidates = set()
    for n, rb in trailers():
        if n in their_cls:
            rb, miss = misses(rb)
            if len(miss) == 1 and any(isinstance(f, int) for f in free_voters(n, rb, voters)):
                candidates.add(miss[0])
    seen, single = Counter(), []
    for n, rb in trailers():
        rb, miss = misses(rb)
        if not candidates.intersection(miss):
            continue
        for e in miss:
            seen[e] += 1
        if len(miss) == 1:
            single.append((n, rb, miss[0]))
    voters = voters_of({n for n, _, _ in single})
    got = defaultdict(Counter)
    for n, rb, e in single:
        free = free_voters(n, rb, voters)
        if len(free) == 1 and not (isinstance(free[0], str) and is_bot_email(free[0])):
            got[e][free[0]] += 1
    for e, cnt in got.items():
        a, k = cnt.most_common(1)[0]
        if isinstance(a, int) and k >= 2 and k / seen[e] >= 0.5:
            found.add(a)
    # CLs owned: the git authors of the merged CLs each such account owns.
    owned = [(n, o) for n, o in ddb.execute(
        "SELECT change_number, owner_account FROM changes WHERE host = ? AND status = 'MERGED' AND is_bot_owned = 0 "
        "AND project = 'chromium/src' AND branch = 'main'", (host,)) if o in bare]
    pairs = []
    for n, o in owned:
        for email, bot in gdb.execute("SELECT author_email, is_bot FROM commits WHERE change_number = ? AND commit_id > 0",
                                      (n,)):
            if not bot and not is_bot_email(email):
                pairs.append((o, email))
    found |= set(owner_links(pairs, account_email))
    return found


def exact_identities(ddb, gdb, tdb=None, host="chromium-review.googlesource.com"):
    """An `Ids` over exact addresses (`address`), with the merges there is
    evidence for: `alias_pairs` (a git author and the Gerrit owner of most
    of their CLs) and, given review-timeline.sqlite (`tdb`), `vote_links`.
    `ddb`: reviews.sqlite; `gdb`: commits.sqlite. The Feedback Index, Review
    Load and the comment threads all call this, so they agree on who is who.

    Accounts that Gerrit shows with no address (mostly deleted ones, which
    derive marks as bots) get one from evidence: the Reviewed-by address
    their votes stand for (`vote_links`) or the git author of most of their
    CLs (`owner_links`). The result's `accounts` maps every account id with
    an address, given or found, to it, and `linked` holds those found:
    callers map accounts through `accounts` and count `linked` ones as
    people, not bots."""
    account_email = dict(ddb.execute("SELECT account_id, email FROM accounts WHERE host = ?", (host,)))
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

    # Everything is streamed into small counts, never held per row: one
    # pass over `changes` (the owner of each merged human CL on main, and
    # each account's newest update), one over `commits`, and votes only for
    # the few CLs whose Reviewed-by has an address that is no account's.
    # A GROUP BY on `changes` sorted all 1.6M rows (18 s); this takes a
    # fraction of the time and memory of loading every commit (2026-11-15).
    owner_of, updated = {}, {}
    for n, o, at, status, bot, project, branch in ddb.execute(
            "SELECT change_number, owner_account, updated_at, status, is_bot_owned, project, branch "
            "FROM changes WHERE host = ?", (host,)):
        if at and at > updated.get(o, ""):
            updated[o] = at
        if status == "MERGED" and not bot and project == "chromium/src" and branch == "main":
            owner_of[n] = o
    known = {address(e) for e in account_email.values() if e}
    own = defaultdict(Counter)       # alias_pairs: git author -> owner address -> CLs
    by_owner = defaultdict(Counter)  # owner_links: account with no address -> git author -> CLs
    missing = []                     # vote_links: (change number, Reviewed-by) with an unknown address

    def alias(email, o):
        oe = account_email.get(o)
        if oe and not is_bot_email(oe):
            own[address(email)][address(oe)] += 1
    # alias_pairs counts a CL once, by its last human commit: the few CLs
    # that landed more than once wait for the end.
    dups = {n for n, in gdb.execute(
        "SELECT change_number FROM commits WHERE commit_id > 0 AND change_number IS NOT NULL "
        "GROUP BY change_number HAVING count(*) > 1")}
    last = {}
    for n, email, bot, rb, at in gdb.execute(
            "SELECT change_number, author_email, is_bot, reviewed_by, landed_at FROM commits "
            "WHERE commit_id > 0 AND change_number IS NOT NULL"):
        if not bot and not is_bot_email(email):
            used(email, at)
            o = owner_of.get(n)
            if o is not None and not account_email.get(o):
                by_owner[o][address(email)] += 1
            if n in dups:
                last[n] = email
            elif o is not None and n:
                alias(email, o)
        if rb:
            rb = json.loads(rb)
            for e in rb:
                used(e, at)
            if any(address(e) not in known and not is_bot_email(e) for e in rb):
                missing.append((n, rb))
    for n, email in last.items():
        if n in owner_of and n:
            alias(email, owner_of[n])
    del owner_of, last
    # Addresses for accounts with none, from votes, then from CLs owned.
    pairs = []
    if tdb is not None:
        voters = defaultdict(set)
        ns = sorted({n for n, _ in missing})
        for table in ("votes", "listing_votes"):
            for i in range(0, len(ns), 500):
                chunk = ns[i:i + 500]
                for n, v in tdb.execute(f"SELECT change_number, voter FROM {table} WHERE value > 0 "
                                        f"AND change_number IN ({','.join('?' * len(chunk))})", chunk):
                    voters[n].add(v)
        pairs = vote_links(missing, account_email, voters)
    found = {b: a for a, b in pairs if isinstance(b, int)}
    by_owner = _owner_out(by_owner)
    accounts = {k: address(e) for k, e in account_email.items() if e}
    for k, e in by_owner.items():
        found.setdefault(k, e)
    accounts.update(found)
    for o, at in updated.items():
        used(accounts.get(o), calendar.timegm(time.strptime(at[:19], "%Y-%m-%d %H:%M:%S")))
    if tdb is not None:
        for table in ("votes", "listing_votes"):
            for v, at in tdb.execute(f"SELECT voter, max(at) FROM {table} GROUP BY voter"):
                used(accounts.get(v), at)
    ids = Ids(address, latest)
    ids.accounts, ids.linked = accounts, set(found)
    for a, b in _alias_out(own):
        ids.union(a, b)
    for a, b in pairs:
        ids.union(a, accounts[b] if isinstance(b, int) else b)
    for k, e in by_owner.items():        # an account's Reviewed-by and git author addresses are one person
        ids.union(e, accounts[k])
    return ids
