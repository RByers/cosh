"""Fetch one ISO week of merged CLs and their comments into raw.sqlite.

Listing: per UTC day, merge-time windows of WINDOW_HOURS each (one page of
n=500 each). A window that overflows is bisected rather than paged with S=,
because deep offsets are slow server-side and the result order (by `updated`)
can shift between pages. See docs/gerrit-api-research.md §1.

Scope: branch main only; merged and abandoned CLs. Bot-owned CLs are listed (so the timeline shows them)
but their comments are never fetched and they get no review rows.

Comments: for each human-owned CL with total_comment_count>0, from NoteDb
(batched git fetch, default) or one REST /comments request per CL.
Everything is cached; re-running skips anything already fetched.
"""

import json
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone

from . import store
from .bots import is_bot_account
from .gerrit import GerritClient

PAGE_SIZE = 500          # anonymous max on chromium-review
WINDOW_HOURS = 6
MIN_WINDOW = timedelta(minutes=15)
LIST_OPTIONS = ["DETAILED_ACCOUNTS", "DETAILED_LABELS"]
GERRIT_TS = "%Y-%m-%d %H:%M:%S"
BRANCH = "main"           # release branches are out of scope
# Abandoned CLs count: review that keeps a flawed CL from landing is valuable work.
STATUSES = ("merged", "abandoned")


def iso_week_bounds(iso_week):
    """'2026-W44' -> (monday 00:00 UTC, next monday 00:00 UTC)."""
    year, week = iso_week.split("-W")
    start = datetime.fromisocalendar(int(year), int(week), 1).replace(tzinfo=timezone.utc)
    return start, start + timedelta(days=7)


def iso_week_of(gerrit_ts):
    dt = parse_gerrit_ts(gerrit_ts)
    y, w, _ = dt.isocalendar()
    return f"{y}-W{w:02d}"


def parse_gerrit_ts(ts):
    # '2026-10-27 22:44:07.000000000' (UTC)
    return datetime.strptime(ts[:19], GERRIT_TS).replace(tzinfo=timezone.utc)


def closed_ts(change):
    """Timestamp that buckets a CL into a week: submit time for merged CLs;
    for abandoned CLs `updated` (Gerrit has no abandoned-after operator, and an
    abandoned CL's last update is almost always the abandon itself).

    A merged CL can lack `submitted` (seen once in 708k listings: 5039071,
    merged 2023-12-04 by Gerrit's merged-time index but listed without a
    submitter, probably merged outside Gerrit's submit); it falls back to
    `updated` too. extract_week keeps such a CL in the week whose merged
    query listed it (see `in_week`)."""
    if change.get("status") == "ABANDONED":
        return change["updated"]
    return change.get("submitted") or change["updated"]


def window_key(project, start, end, offset=0, status="merged", snap=None):
    k = f"{project}@{BRANCH}|{status}|{start:%Y-%m-%dT%H:%M:%S}|{end:%Y-%m-%dT%H:%M:%S}"
    # Open-CL listings change over time; `snap` (the snapshot's listed_at)
    # keeps each snapshot's windows apart, while a resumed snapshot reuses them.
    return k + (f"|S={offset}" if offset else "") + (f"|snap={snap}" if snap else "")


def list_window(client, raw, project, start, end, offset=0, status="merged", snap=None):
    """Return the list of change dicts for one window page (cached).
    status 'merged' filters on merge time; 'abandoned' and 'open' on `updated`."""
    key = window_key(project, start, end, offset, status, snap)
    cached = store.get_response(raw, client.host, "list_window", key)
    if cached is not None and cached[0] == 200:
        return json.loads(cached[1]), key
    after, before = ("mergedafter", "mergedbefore") if status == "merged" else ("after", "before")
    q = (f'project:{project} branch:{BRANCH} status:{status} '
         f'{after}:"{start:{GERRIT_TS}} +0000" {before}:"{end:{GERRIT_TS}} +0000"')
    params = [("q", q), ("n", PAGE_SIZE)] + [("o", o) for o in LIST_OPTIONS]
    if offset:
        params.append(("S", offset))
    http, body, url = client.get("/changes/", params)
    if http != 200:
        raise RuntimeError(f"HTTP {http} listing {key}: {body[:200]}")
    store.put_response(raw, client.host, "list_window", key, url, http, body)
    raw.commit()
    return json.loads(body), key


def _keep(out, key, c):
    """Record a listed CL; if it was listed twice, keep the newer listing."""
    cur = out.get(c["_number"])
    if cur is None or c.get("updated", "") > cur[1].get("updated", ""):
        out[c["_number"]] = (key, c)


def list_range(client, raw, project, start, end, out, status="merged", snap=None):
    """Collect {change_number: (window_key, change)} for CLs in [start, end]
    (by merge time for 'merged', by `updated` otherwise)."""
    changes, key = list_window(client, raw, project, start, end, status=status, snap=snap)
    if changes and changes[-1].get("_more_changes"):
        if end - start > MIN_WINDOW:
            mid = start + (end - start) / 2
            mid = mid.replace(microsecond=0)
            list_range(client, raw, project, start, mid, out, status, snap)
            list_range(client, raw, project, mid, end, out, status, snap)
            return
        # Tiny window still overflowing (should not happen): fall back to paging.
        offset = 0
        while changes and changes[-1].get("_more_changes"):
            offset += len(changes)
            for c in changes:
                _keep(out, key, c)
            changes, key = list_window(client, raw, project, start, end, offset, status, snap)
    for c in changes:
        _keep(out, key, c)
    print(f"  listed {status} {start:%Y-%m-%d %H:%M}..{end:%Y-%m-%d %H:%M}: {len(changes)} CLs "
          f"(requests so far: {client.request_count})", file=sys.stderr)


def needs_comments(change):
    return (change.get("total_comment_count", 0) > 0
            and not is_bot_account(change.get("owner", {})))


def comments_path(project, number):
    return f"/changes/{urllib.parse.quote(project, safe='')}~{number}/comments"


def extract_week(host, project, iso_week, min_interval=1.0, max_comment_fetches=None,
                 data_dir=store.DATA_DIR, argv="", via="notedb", batch_size=200,
                 batch_gap=5.0, duty_cycle=1.0):
    raw = store.open_raw(data_dir)
    client = GerritClient(host, min_interval=min_interval)
    run_id = raw.execute(
        "INSERT INTO extract_runs(started_at, command, status) VALUES (?,?,?)",
        (store.now_iso(), argv, "running")).lastrowid
    raw.commit()
    status = "failed"
    try:
        week_start, week_end = iso_week_bounds(iso_week)
        found = {}
        for cl_status in STATUSES:
            print(f"[{iso_week}] listing {project}@{BRANCH} {cl_status} "
                  f"{week_start:%Y-%m-%d}..{week_end:%Y-%m-%d}", file=sys.stderr)
            day = week_start
            while day < week_end:
                w = day
                while w < day + timedelta(days=1):
                    w_end = w + timedelta(hours=WINDOW_HOURS)
                    list_range(client, raw, project, w, w_end, found, cl_status)
                    w = w_end
                day += timedelta(days=1)

        # Bounds are inclusive; keep only CLs whose closing time is in this week.
        # A merged CL without `submitted` was listed by Gerrit's own merge time
        # for this week, and no other week's merged query lists it, so keep it.
        in_week = {n: (k, c) for n, (k, c) in found.items()
                   if c.get("status") in ("MERGED", "ABANDONED")
                   and ((c["status"] == "MERGED" and not c.get("submitted"))
                        or week_start <= parse_gerrit_ts(closed_ts(c)) < week_end)}
        raw.execute("DELETE FROM week_changes WHERE host=? AND project=? AND iso_week=?",
                    (host, project, iso_week))
        raw.executemany("INSERT INTO week_changes VALUES (?,?,?,?,?)",
                        [(host, project, iso_week, n, k) for n, (k, _) in in_week.items()])
        raw.execute(
            """INSERT INTO week_progress(host, project, iso_week, listed_at, cl_count, last_run_id)
               VALUES (?,?,?,?,?,?) ON CONFLICT(host, project, iso_week) DO UPDATE SET
               listed_at=excluded.listed_at, cl_count=excluded.cl_count,
               last_run_id=excluded.last_run_id""",
            (host, project, iso_week, store.now_iso(), len(in_week), run_id))
        raw.commit()

        todo = [n for n, (_, c) in sorted(in_week.items()) if needs_comments(c)]
        if via == "notedb":
            remaining = fetch_notedb(client, raw, project, todo, in_week, batch_size,
                                     batch_gap, max_comment_fetches, duty_cycle)
        else:
            remaining = fetch_rest_comments(client, raw, host, project, todo,
                                            max_comment_fetches)
        if not remaining:
            raw.execute("UPDATE week_progress SET fetched_at=? WHERE host=? AND project=? AND iso_week=?",
                        (store.now_iso(), host, project, iso_week))
        status = "ok" if not remaining else "partial"
        print(f"[{iso_week}] done: {client.request_count} REST requests this run; "
              f"{len(remaining)} CLs still pending", file=sys.stderr)
    except KeyboardInterrupt:
        status = "interrupted"
        raise
    finally:
        raw.execute("UPDATE extract_runs SET finished_at=?, requests=?, status=? WHERE run_id=?",
                    (store.now_iso(), client.request_count, status, run_id))
        raw.commit()
        raw.close()


OPEN_WINDOW = timedelta(days=7)      # initial window for open CLs; bisected on overflow
CLOSED_WINDOW = timedelta(days=1)


def fetched_week_span(raw, host, project):
    """(start of the oldest, end of the newest) fully fetched ISO week, or None."""
    weeks = [w for (w,) in raw.execute(
        "SELECT iso_week FROM week_progress WHERE host=? AND project=? AND fetched_at IS NOT NULL",
        (host, project))]
    if not weeks:
        return None
    return iso_week_bounds(min(weeks))[0], iso_week_bounds(max(weeks))[1]


def _parse_iso(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _list_span(client, raw, project, start, end, step, out, status, snap):
    w = start
    while w < end:
        w_end = min(w + step, end)
        list_range(client, raw, project, w, w_end, out, status, snap)
        w = w_end


def extract_open(host, project, since=None, closed_since=None, min_interval=1.0,
                 data_dir=store.DATA_DIR, argv="", batch_size=200, batch_gap=5.0,
                 duty_cycle=1.0, max_comment_fetches=None):
    """Snapshot the CLs whose comments the weekly (closed-CL) listings can't see
    yet, and fetch their NoteDb refs:
      - open CLs on main updated at/after `since` (default: start of the oldest
        fetched week), and
      - merged/abandoned CLs closed at/after `closed_since` (default: end of the
        newest fetched week), which no weekly listing covers yet.
    Comments are later bucketed by the week they were written, so this is what
    makes recent weeks complete. An unfinished snapshot is resumed (its cached
    windows are reused); a finished one is never reused: rerun to refresh."""
    raw = store.open_raw(data_dir)
    client = GerritClient(host, min_interval=min_interval)
    run_id = raw.execute(
        "INSERT INTO extract_runs(started_at, command, status) VALUES (?,?,?)",
        (store.now_iso(), argv, "running")).lastrowid
    raw.commit()
    status = "failed"
    try:
        resume = raw.execute(
            """SELECT listed_at, since, closed_since FROM open_listings WHERE host=? AND project=?
               AND fetched_at IS NULL ORDER BY listed_at DESC LIMIT 1""", (host, project)).fetchone()
        if resume and since is None and closed_since is None:
            snap, since_s, closed_s = resume
            print(f"[open] resuming snapshot {snap}", file=sys.stderr)
        else:
            span = fetched_week_span(raw, host, project)
            if span is None and (since is None or closed_since is None):
                raise SystemExit("no fetched weeks yet: pass --since and --closed-since")
            snap = store.now_iso()
            since_s = since or f"{span[0]:%Y-%m-%dT%H:%M:%SZ}"
            closed_s = closed_since or f"{span[1]:%Y-%m-%dT%H:%M:%SZ}"
            raw.execute("""INSERT INTO open_listings(host, project, listed_at, since, closed_since,
                           last_run_id) VALUES (?,?,?,?,?,?)""",
                        (host, project, snap, since_s, closed_s, run_id))
            raw.commit()
        t_snap, t_since, t_closed = _parse_iso(snap), _parse_iso(since_s), _parse_iso(closed_s)

        found = {}
        print(f"[open] listing open CLs updated {since_s} .. {snap}, and CLs closed since "
              f"{closed_s}", file=sys.stderr)
        # Oldest windows first. A CL updated during the listing moves to a later
        # `updated`, never an earlier one, so the catch-up window below
        # (snapshot start .. now) still sees it.
        _list_span(client, raw, project, t_since, t_snap, OPEN_WINDOW, found, "open", snap)
        for st in STATUSES:
            _list_span(client, raw, project, t_closed, t_snap, CLOSED_WINDOW, found, st, snap)
        t_now = datetime.now(timezone.utc).replace(microsecond=0)
        for st in ("open",) + STATUSES:
            list_range(client, raw, project, t_snap, t_now, found, st, snap)

        keep = {}
        for n, (k, c) in found.items():
            if c.get("status") == "NEW":
                keep[n] = (k, c)
            elif (c.get("status") in ("MERGED", "ABANDONED")
                  and parse_gerrit_ts(closed_ts(c)) >= t_closed):
                keep[n] = (k, c)
        with raw:
            raw.execute("DELETE FROM open_changes WHERE host=? AND project=? AND listed_at=?",
                        (host, project, snap))
            raw.executemany("INSERT INTO open_changes VALUES (?,?,?,?,?)",
                            [(host, project, snap, n, k) for n, (k, _) in keep.items()])
            raw.execute("""UPDATE open_listings SET cl_count=?, last_run_id=? WHERE host=? AND
                           project=? AND listed_at=?""", (len(keep), run_id, host, project, snap))
        n_open = sum(1 for _, c in keep.values() if c.get("status") == "NEW")
        print(f"[open] {len(keep)} CLs: {n_open} open, {len(keep) - n_open} closed since "
              f"{closed_s}; {client.request_count} listing requests", file=sys.stderr)

        todo = [n for n, (_, c) in sorted(keep.items()) if needs_comments(c)]
        remaining = fetch_notedb(client, raw, project, todo, keep, batch_size, batch_gap,
                                 max_comment_fetches, duty_cycle)
        if not remaining:
            with raw:
                raw.execute("""UPDATE open_listings SET fetched_at=? WHERE host=? AND project=?
                               AND listed_at=?""", (store.now_iso(), host, project, snap))
        status = "ok" if not remaining else "partial"
        print(f"[open] done: {client.request_count} REST requests this run; "
              f"{len(remaining)} CLs still pending", file=sys.stderr)
    except KeyboardInterrupt:
        status = "interrupted"
        raise
    finally:
        raw.execute("UPDATE extract_runs SET finished_at=?, requests=?, status=? WHERE run_id=?",
                    (store.now_iso(), client.request_count, status, run_id))
        raw.commit()
        raw.close()


def fetch_rest_comments(client, raw, host, project, todo, max_fetches):
    """One REST /comments request per CL. Returns CLs still missing."""
    have = {int(k) for (k,) in raw.execute(
        "SELECT key FROM responses WHERE host=? AND kind='comments'", (host,))}
    pending = [n for n in todo if n not in have]
    print(f"  REST: {len(pending)} /comments fetches to do", file=sys.stderr)
    batch = pending if max_fetches is None else pending[:max_fetches]
    for i, n in enumerate(batch, 1):
        st, body, url = client.get(comments_path(project, n))
        if st not in (200, 404):
            raise RuntimeError(f"HTTP {st} for {url}")
        store.put_response(raw, host, "comments", str(n), url, st, body)
        raw.commit()
        if i % 50 == 0 or i == len(batch):
            print(f"  comments {i}/{len(batch)} (requests: {client.request_count})",
                  file=sys.stderr)
    return pending[len(batch):]


def stale_refs(todo, listed, tips):
    """CLs in `todo` whose meta ref is missing locally or older than the
    listing's `updated`. listed: {n: (window_key, change)}; tips: {n: unix}."""
    return [n for n in todo if n not in tips
            or tips[n] < parse_gerrit_ts(listed[n][1]["updated"]).timestamp()]


def fetch_notedb(client, raw, project, todo, in_week, batch_size, batch_gap, max_cls,
                 duty_cycle=1.0):
    """Batched `git fetch` of NoteDb meta refs, then resolve any comment
    author account ids the REST listing didn't give us. Returns CLs missing."""
    import time
    from . import notedb
    repo = notedb.init_repo(notedb.default_repo(project))
    # Fetch refs we lack, and refetch refs whose listing is newer than the local
    # tip (e.g. a CL fetched while open that has since gained comments). A
    # refetch is incremental: only the new NoteDb commits are downloaded.
    tips = notedb.tip_times(repo)
    pending = stale_refs(todo, in_week, tips)
    n_stale = sum(1 for n in pending if n in tips)
    if n_stale:
        print(f"  NoteDb: {n_stale} local meta refs are older than their listing; refetching",
              file=sys.stderr)
    if max_cls is not None:
        pending = pending[:max_cls]
    nb = (len(pending) + batch_size - 1) // batch_size
    print(f"  NoteDb: {len(pending)} meta refs to fetch in {nb} git fetches", file=sys.stderr)
    dt = 0.0
    for i in range(0, len(pending), batch_size):
        if i:
            # duty_cycle 0.5 => idle as long as the last fetch took; 1.0 => batch_gap only
            time.sleep(max(batch_gap, dt * (1 - duty_cycle) / duty_cycle))
        chunk = pending[i:i + batch_size]
        dt = notedb.fetch_batch(repo, project, chunk)
        print(f"  git fetch {i // batch_size + 1}/{nb}: {len(chunk)} refs in {dt:.0f}s",
              file=sys.stderr)
    have = notedb.fetched_numbers(repo)

    # Account ids seen in comments but absent from the listing's DETAILED_ACCOUNTS.
    known = set()
    for _, c in in_week.values():
        known |= _account_ids(c)
    known |= {int(k) for (k,) in raw.execute(
        "SELECT key FROM responses WHERE host=? AND kind='account'", (client.host,))}
    unknown = set()
    for n in todo:
        if n in have:
            for cl in (notedb.read_comments(repo, n) or {}).values():
                unknown |= {x["author"]["_account_id"] for x in cl} - known
    unknown.discard(None)
    if unknown:
        print(f"  resolving {len(unknown)} account ids via /accounts/", file=sys.stderr)
    for aid in sorted(unknown):
        st, body, url = client.get(f"/accounts/{aid}")
        store.put_response(raw, client.host, "account", str(aid), url, st, body)
        raw.commit()
    return [n for n in todo if n not in have]


def _account_ids(obj):
    """All _account_id values anywhere in a JSON structure."""
    out = set()
    stack = [obj]
    while stack:
        o = stack.pop()
        if isinstance(o, dict):
            if isinstance(o.get("_account_id"), int):
                out.add(o["_account_id"])
            stack.extend(o.values())
        elif isinstance(o, list):
            stack.extend(o)
    return out
