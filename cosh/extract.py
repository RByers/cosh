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
    abandoned CL's last update is almost always the abandon itself)."""
    if change.get("status") == "ABANDONED":
        return change["updated"]
    return change["submitted"]


def window_key(project, start, end, offset=0, status="merged"):
    k = f"{project}@{BRANCH}|{status}|{start:%Y-%m-%dT%H:%M:%S}|{end:%Y-%m-%dT%H:%M:%S}"
    return k + (f"|S={offset}" if offset else "")


def list_window(client, raw, project, start, end, offset=0, status="merged"):
    """Return the list of change dicts for one window page (cached)."""
    key = window_key(project, start, end, offset, status)
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


def list_range(client, raw, project, start, end, out, status="merged"):
    """Collect {change_number: (window_key, change)} for CLs closed in [start, end]."""
    changes, key = list_window(client, raw, project, start, end, status=status)
    if changes and changes[-1].get("_more_changes"):
        if end - start > MIN_WINDOW:
            mid = start + (end - start) / 2
            mid = mid.replace(microsecond=0)
            list_range(client, raw, project, start, mid, out, status)
            list_range(client, raw, project, mid, end, out, status)
            return
        # Tiny window still overflowing (should not happen): fall back to paging.
        offset = 0
        while changes and changes[-1].get("_more_changes"):
            offset += len(changes)
            for c in changes:
                out.setdefault(c["_number"], (key, c))
            changes, key = list_window(client, raw, project, start, end, offset, status)
    for c in changes:
        out.setdefault(c["_number"], (key, c))
    print(f"  listed {status} {start:%m-%d %H:%M}..{end:%H:%M}: {len(changes)} CLs "
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
        in_week = {n: (k, c) for n, (k, c) in found.items()
                   if c.get("status") in ("MERGED", "ABANDONED")
                   and week_start <= parse_gerrit_ts(closed_ts(c)) < week_end}
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


def fetch_notedb(client, raw, project, todo, in_week, batch_size, batch_gap, max_cls,
                 duty_cycle=1.0):
    """Batched `git fetch` of NoteDb meta refs, then resolve any comment
    author account ids the REST listing didn't give us. Returns CLs missing."""
    import time
    from . import notedb
    repo = notedb.init_repo(notedb.default_repo(project))
    pending = [n for n in todo if n not in notedb.fetched_numbers(repo)]
    if max_cls is not None:
        pending = pending[:max_cls]
    nb = (len(pending) + batch_size - 1) // batch_size
    print(f"  NoteDb: {len(pending)} meta refs to fetch in {nb} git fetches", file=sys.stderr)
    dt = 0.0
    for i in range(0, len(pending), batch_size):
        if i:
            # duty_cycle 0.5 => idle as long as the last fetch took
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
