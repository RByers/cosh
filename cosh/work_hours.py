"""Working hours: an 8-hour window a day per person, fitted to their Gerrit activity.

We don't know where anyone works, so each person gets, per quarter, the 8
consecutive hours of the day (UTC, wrapping midnight) that hold the most of
their activity in it: comments, Code-Review votes and patch-set uploads. The
window's start is taken as 09:00 local time, which gives a UTC offset and so
the person's own Saturday and Sunday. A span of time then has "working
hours": the part of it inside the window on the person's weekdays
(docs/review-timezones.md, "Working hours").

One window per quarter, not per week or day: authors come to expect a
reviewer's usual hours, so a trip counts as the wait it causes, while a move
to another timezone shows from the next quarter. With fewer than
MIN_EVENTS events in the quarter, the window is fitted to everything the
person did up to that quarter's end, however little, and failing that to
everything they did at all.

Memory and time stay small: SQL counts events per (person, quarter, hour),
24 numbers per person-quarter (about 50k rows for 2021..2026), and a fit is
a scan of 24 sums.
"""

from collections import defaultdict
from datetime import datetime, timezone

DAY, HOUR = 86400, 3600
WINDOW_H = 8
LOCAL_START_H = 9           # the window's start, in local time
MIN_EVENTS = 10             # a quarter with fewer is fitted to the person's history
REGIONS = ("Americas", "EMEA", "APAC")


def quarter(t):
    d = datetime.fromtimestamp(t, timezone.utc)
    return f"{d.year}Q{(d.month - 1) // 3 + 1}"


def fit(counts):
    """The start hour (UTC) of the 8-hour window holding most of 24 hourly
    counts; among equals, the one whose middle is nearest the events, so a
    lone event sits in the middle of its window. None without any events."""
    if not any(counts):
        return None

    sums = [sum(counts[(i + j) % 24] for j in range(WINDOW_H)) for i in range(24)]
    best = [i for i in range(24) if sums[i] == max(sums)]
    if len(best) == 1:
        return best[0]

    def far(i):
        mid = i + WINDOW_H / 2
        return sum(c * min(abs(h + 0.5 - mid) % 24, 24 - abs(h + 0.5 - mid) % 24) for h, c in enumerate(counts) if c)
    return min(best, key=far)


def offset_s(start_h):
    """The UTC offset (seconds, in [-12 h, +12 h)) that puts `start_h` at 09:00 local."""
    return ((LOCAL_START_H - start_h + 12) % 24 - 12) * HOUR


def region(start_h):
    """Americas, EMEA or APAC, by where 09:00 local falls in UTC: UTC+5 .. +12 is
    APAC, UTC-2 .. +4 EMEA, the rest the Americas."""
    return "APAC" if start_h >= 21 or start_h <= 4 else "EMEA" if start_h <= 11 else "Americas"


def overlap_h(a, b):
    """Hours two 8-hour windows starting at hours `a` and `b` share."""
    d = abs(a - b) % 24
    return max(0, WINDOW_H - min(d, 24 - d))


def work_seconds(s, e, start_h):
    """Seconds of [s, e) inside the window starting at `start_h` (UTC) on the
    days that are Monday..Friday where the window starts at 09:00."""
    tot, off = 0, offset_s(start_h)
    for k in range(s // DAY - 1, e // DAY + 1):
        ws = k * DAY + start_h * HOUR
        if ((ws + off) // DAY + 3) % 7 >= 5:     # day 0 (1970-01-01) was a Thursday
            continue
        tot += max(0, min(e, ws + WINDOW_H * HOUR) - max(s, ws))
    return tot


class Windows:
    """Each person's window per quarter, from {(account, quarter): 24 hourly counts}."""

    def __init__(self, counts):
        self.counts = counts
        self.by_account = defaultdict(dict)
        for (a, q), c in counts.items():
            self.by_account[a][q] = c
        self._memo = {}

    def start(self, account, q):
        """(start hour, basis) of `account`'s window in quarter `q`: basis
        "quarter" with MIN_EVENTS events in it, else "history" (everything up
        to q, or failing that everything); (None, None) without any events."""
        key = (account, q)
        if key not in self._memo:
            qs = self.by_account.get(account, {})
            c = qs.get(q)
            if c and sum(c) >= MIN_EVENTS:
                self._memo[key] = (fit(c), "quarter")
            else:
                past = [v for k, v in qs.items() if k <= q] or list(qs.values())
                tot = [sum(x) for x in zip(*past)] if past else None
                self._memo[key] = (fit(tot), "history") if tot and any(tot) else (None, None)
        return self._memo[key]

    def at(self, account, t):
        return self.start(account, quarter(t))[0]

    def rows(self):
        """work_windows rows of every window looked up or with events: (account, quarter, start, basis, events)."""
        for a, q in sorted(set(self.counts) | set(self._memo)):
            s, basis = self.start(a, q)
            if s is not None:
                c = self.counts.get((a, q))
                yield a, q, s, basis, sum(c) if c else 0


QUARTER_SQL = "strftime('%Y', {t}, 'unixepoch') || 'Q' || ((CAST(strftime('%m', {t}, 'unixepoch') AS INTEGER) + 2) / 3)"


def activity_counts(tdb, ddb):
    """{(account, quarter): 24 hourly counts} of comments (reviews.sqlite,
    `ddb`, written by people, not AI) and votes and uploads
    (review-timeline.sqlite, `tdb`)."""
    out = defaultdict(lambda: [0] * 24)
    t = "unixepoch(written_at)"
    queries = (
        (ddb, f"SELECT account_id, {QUARTER_SQL.format(t=t)}, {t} % 86400 / 3600, count(*) FROM comments "
              "WHERE is_ai = 0 GROUP BY 1, 2, 3"),
        (tdb, f"SELECT voter, {QUARTER_SQL.format(t='at')}, at % 86400 / 3600, count(*) FROM votes GROUP BY 1, 2, 3"),
        (tdb, f"SELECT uploader, {QUARTER_SQL.format(t='at')}, at % 86400 / 3600, count(*) FROM uploads GROUP BY 1, 2, 3"),
    )
    for db, sql in queries:
        for a, q, h, n in db.execute(sql):
            out[a, q][h] += n
    return dict(out)
