"""Backfill many ISO weeks, newest first, gently.

  python3 -m cosh backfill --weeks 52            # print the plan only
  python3 -m cosh backfill --weeks 52 --go       # actually fetch

POLICY (see CLAUDE.md): the one-year backfill (52 weeks) is approved; going
further back still needs explicit approval.

Per week: REST listing (~56 requests) + NoteDb git fetches (~18 x 200 refs),
serial, one connection. duty_cycle=0.5 idles after every git fetch for as long
as the fetch took, so the server sees us at most half the time. Weeks whose
fetch already completed are skipped, so it's resumable at any point; each
completed week is derived immediately.
"""

import sys
from datetime import datetime, timedelta, timezone

from . import store
from .derive import derive
from .extract import extract_week

# Measured on 2026-W44: ~7,650 CLs, ~3,400 NoteDb refs at ~0.46 s server time
# each, plus ~2 min of listing.
EST_MINUTES_PER_WEEK = 30


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


def backfill(host, project, weeks, go=False, duty_cycle=0.5, batch_size=200, argv=""):
    raw = store.open_raw()
    done = {w for (w,) in raw.execute(
        "SELECT iso_week FROM week_progress WHERE host=? AND project=? AND fetched_at IS NOT NULL",
        (host, project))}
    raw.close()
    todo = [w for w in weeks if w not in done]
    est_h = len(todo) * EST_MINUTES_PER_WEEK / 60 / duty_cycle
    print(f"backfill {project}: {len(weeks)} weeks requested ({weeks[-1]} .. {weeks[0]}), "
          f"{len(weeks) - len(todo)} already done, {len(todo)} to fetch; "
          f"estimated {est_h:.0f} h wall-clock at duty cycle {duty_cycle}", file=sys.stderr)
    if not go:
        print("plan only; pass --go to fetch", file=sys.stderr)
        return
    for i, w in enumerate(todo, 1):
        print(f"=== [{i}/{len(todo)}] {w} ===", file=sys.stderr)
        extract_week(host, project, w, via="notedb", batch_size=batch_size,
                     duty_cycle=duty_cycle, argv=argv)
        derive(weeks=[w])
