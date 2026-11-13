"""Who is who in Chromium's git history and Gerrit: one identity per person
across the chromium.org and google.com domains and SVN-era addresses, bot
addresses (config/bots.txt), and owner/author aliases. Shared by the Feedback
Index (cosh/feedback.py), commits.sqlite's queries and the analyses."""

from collections import Counter, defaultdict

from .bots import _PATTERNS


def person(e):
    """One identity per person across Chromium's two common domains: many
    people author as user@chromium.org and review as user@google.com."""
    e = (e or "").lower()
    if e.count("@") > 1:            # SVN-era author: user@domain@<repository uuid>
        e = e.rsplit("@", 1)[0]
    local, _, dom = e.partition("@")
    return f"{local}@google.com" if dom in ("chromium.org", "google.com") else e


def is_bot_email(e):
    """True for a missing address or one config/bots.txt matches."""
    return not e or any(p.search(e) for p in _PATTERNS)


class Ids:
    """Union-find over emails: Chromium's two domains and SVN-era emails merge
    by person(); Gerrit owner email and landed-commit author email of the
    same CL merge too (people who switched addresses)."""

    def __init__(self):
        self.p = {}

    def find(self, e):
        e = person(e)
        self.p.setdefault(e, e)
        while self.p[e] != e:
            self.p[e] = self.p[self.p[e]]
            e = self.p[e]
        return e

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)


def alias_pairs(cls, commits, min_cls=3, min_share=0.5):
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
            own[person(g["email"])][person(c["owner_email"])] += 1
    out = []
    for b, cnt in own.items():
        tot = sum(cnt.values())
        for a, n in cnt.items():
            if a != b and n >= min_cls and n / tot >= min_share:
                out.append((a, b))
    return out
