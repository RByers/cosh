"""The dates a page's data covers, stamped into what it publishes.

Every analysis page shows a subtitle under its title, "Based on Chromium
Gerrit and git data from 3 Jul 2017 to 1 Nov 2026"
(docs/data-architecture.md, "Data spans"). Its dates come from a
`data_span` object that the step publishing the page's data writes into the
first file the page loads, in the same run and from the same inputs as the
data itself, so the subtitle can't fall behind the figures:

    {"first": "2017-07-03", "last": "2026-11-01", "sources": ["gerrit", "git"]}

`first` and `last` are UTC days, both included. `last` is the older of the
step's own end and each source's: a page built from Gerrit through 1 Nov
and git through 7 Nov is current to 1 Nov.

- Gerrit: the ISO weeks `derive` recorded as fetched (reviews.sqlite's
  meta `fetched_weeks`), Monday of the first to Sunday of the last.
- git: commits.sqlite, through the day the newest commit on main landed.
"""

import json
import os
import sqlite3
from datetime import date, datetime, timedelta, timezone

from . import store

DAY = timedelta(days=1)


def _ro(path):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def gerrit_span(ddb):
    """(Monday of the first fetched week, the Monday after the last) of an
    open reviews.sqlite, or None if it records no fetched week."""
    row = ddb.execute("SELECT v FROM meta WHERE k = 'fetched_weeks'").fetchone()
    weeks = sorted(json.loads(row[0])) if row and row[0] else []
    if not weeks:
        return None

    def monday(w):
        y, n = w.split("-W")
        return date.fromisocalendar(int(y), int(n), 1)
    return monday(weeks[0]), monday(weeks[-1]) + 7 * DAY


def git_end(cdb):
    """The day after the newest commit in an open commits.sqlite landed
    (UTC), or None if it has none."""
    t = cdb.execute("SELECT max(landed_at) FROM commits").fetchone()[0]
    return datetime.fromtimestamp(t, timezone.utc).date() + DAY if t is not None else None


def stamp(first, end, sources):
    """The data_span object for data from `first` up to `end` (dates; `end`
    excluded), where `sources` maps each source's name to where its data
    ends (excluded), or None if unknown."""
    ends = [end] + [e for e in sources.values() if e is not None]
    return dict(first=first.isoformat(), last=(min(ends) - DAY).isoformat(), sources=sorted(sources))


def _day(x):
    if x is None or isinstance(x, date) and not isinstance(x, datetime):
        return x
    if isinstance(x, datetime):        # a naive one is UTC
        return (x if x.tzinfo is None else x.astimezone(timezone.utc)).date()
    if isinstance(x, (int, float)):
        return datetime.fromtimestamp(x, timezone.utc).date()
    return date.fromisoformat(str(x)[:10])


def of_data(first=None, end=None, sources=("gerrit", "git"), data_dir=None, ddb=None, cdb=None):
    """The data_span object of data read from reviews.sqlite and (with "git"
    in `sources`) commits.sqlite: from `first` (default: the first fetched
    Gerrit week) up to `end` (excluded; default: where Gerrit ends), cut
    short where a source ends. `first` and `end` may be dates, datetimes,
    unix seconds or ISO strings. Open connections may be passed; otherwise
    the files are opened read-only in `data_dir`. A missing file adds no
    limit (tests); with no `first` and no Gerrit data, returns None."""
    from . import commits as commit_store
    data_dir = data_dir or store.DATA_DIR
    first, end = _day(first), _day(end)
    opened = []

    def open_ro(conn, path):
        if conn is None and os.path.exists(path):
            conn = _ro(path)
            opened.append(conn)
        return conn
    try:
        ddb = open_ro(ddb, os.path.join(data_dir, store.DERIVED_FILE))
        span = gerrit_span(ddb) if ddb is not None else None
        ends = {}
        if "gerrit" in sources:
            ends["gerrit"] = span[1] if span else None
        if "git" in sources:
            cdb = open_ro(cdb, commit_store.db_path(data_dir))
            ends["git"] = git_end(cdb) if cdb is not None else None
    finally:
        for c in opened:
            c.close()
    first = first or (span[0] if span else None)
    end = end or (span[1] if span else None)
    if first is None or end is None:
        return None
    return stamp(first, end, ends)
