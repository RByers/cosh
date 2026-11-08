"""Backfill many ISO weeks, newest first, gently.

  python3 -m cosh backfill --weeks 52            # print the plan only
  python3 -m cosh backfill --weeks 52 --go       # actually fetch

POLICY (see CLAUDE.md): the backfill back to 2023-W26 (2023-07-01, Radar's
first data) is approved; going further back still needs explicit approval.

Per week: REST listing (~56 requests) + NoteDb git fetches (~10-18 x 200 refs),
serial, one connection, at least 5 s between fetches. The default duty_cycle
1.0 (approved 2026-11-04) runs fetches back to back; 0.5 idles after every
fetch for as long as it took, so the server sees us at most half the time. Weeks whose
fetch already completed are skipped, so it's resumable at any point; each
completed week is derived immediately (into derived.sqlite). Afterwards, run
`extract-open` so comments on CLs that are still open are counted too.
"""

import sys
from datetime import datetime, timedelta, timezone

from . import store
from .derive import derive
from .extract import extract_week

# Measured over the 52-week backfill (2025-W45 .. 2026-W44, duty cycle 0.5):
# 21.7 min per week = ~7 min of NoteDb fetching (559 fetches of 200 refs,
# ~38 s each) + as much again idle + ~8 min of listing and local work.
EST_FETCH_MIN = 7
EST_OTHER_MIN = 8


def last_complete_week(now=None):
    now = now or datetime.now(timezone.utc)
    d = now - timedelta(days=7)
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def week_list(newest, n):
    y, w = newest.split("-W")
    monday = datetime.fromisocalendar(int(y), int(w), 1)
    out = []
    for i in range(n):
        yy, ww, _ = (monday - timedelta(weeks=i)).isocalendar()
        out.append(f"{yy}-W{ww:02d}")
    return out


def backfill(host, project, weeks, go=False, duty_cycle=1.0, batch_size=200, argv="",
             jobs=1, jobs_until=None):
    """jobs > 1 (user-approved only) runs that many NoteDb fetches at once
    until `jobs_until` (unix seconds), then one at a time."""
    raw = store.open_raw()
    done = {w for (w,) in raw.execute(
        "SELECT iso_week FROM week_progress WHERE host=? AND project=? AND fetched_at IS NOT NULL",
        (host, project))}
    raw.close()
    todo = [w for w in weeks if w not in done]
    est_h = len(todo) * (EST_OTHER_MIN + EST_FETCH_MIN / duty_cycle) / 60
    print(f"backfill {project}: {len(weeks)} weeks requested ({weeks[-1]} .. {weeks[0]}), "
          f"{len(weeks) - len(todo)} already done, {len(todo)} to fetch; "
          f"estimated {est_h:.0f} h wall-clock at duty cycle {duty_cycle}", file=sys.stderr)
    if not go:
        print("plan only; pass --go to fetch", file=sys.stderr)
        return
    throttle = None
    if jobs > 1:
        from .patchsets import DeadlineThrottle
        throttle = DeadlineThrottle(jobs, jobs_until)
    for i, w in enumerate(todo, 1):
        print(f"=== [{i}/{len(todo)}] {w} ===", file=sys.stderr)
        extract_week(host, project, w, via="notedb", batch_size=batch_size,
                     duty_cycle=duty_cycle, argv=argv, throttle=throttle)
        derive(weeks=[w])
    print("backfill done. Comments on still-open CLs are not fetched yet: run "
          "`python3 -m cosh extract-open`, then `derive` and `summarize`.", file=sys.stderr)
