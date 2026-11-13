"""cosh CLI.

  python3 -m cosh extract --week 2026-W44 [--via notedb|rest] [--max-comment-fetches N]
  python3 -m cosh extract-open [--since ...] [--closed-since ...]
  python3 -m cosh derive [--week 2026-W44] [--out PATH]
  python3 -m cosh commits [--db PATH] [--jobs N]
  python3 -m cosh classify [--week 2026-W44] [--max-threads N] [--dry-run] [--db PATH]
  python3 -m cosh summarize [--metric comments|cls|chars|addressed|commits] [--db PATH] [--out DIR]
  python3 -m cosh backfill --weeks 52 [--go] [--duty-cycle 1.0]
  python3 -m cosh patchsets [--go]
  python3 -m cosh status
  python3 -m cosh update-affiliations
  python3 -m cosh radar [--start 2020-09-01] [--agg 1d|1w] [--offline]

Data lives in data/private/ next to the code, or in $COSH_DATA_DIR.
"""

import argparse
import sys

from . import store

HOST = "chromium-review.googlesource.com"
PROJECT = "chromium/src"


def _utc(s):
    """'2025-11-03' or '2025-11-03T00:00:00Z' -> '2025-11-03T00:00:00Z'."""
    return s if "T" in s else f"{s}T00:00:00Z"


def main(argv=None):
    p = argparse.ArgumentParser(prog="cosh")
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("extract", help="fetch one ISO week from Gerrit (cached, resumable)")
    e.add_argument("--week", required=True, help="ISO week, e.g. 2026-W44")
    e.add_argument("--host", default=HOST)
    e.add_argument("--project", default=PROJECT)
    e.add_argument("--interval", type=float, default=1.0,
                   help="min seconds between requests (default 1.0; never lower)")
    e.add_argument("--max-comment-fetches", type=int, default=None,
                   help="only fetch comments for N CLs (for smoke tests)")
    e.add_argument("--via", choices=["notedb", "rest"], default="notedb",
                   help="comment source: batched git fetch of NoteDb refs (default) "
                        "or one REST /comments request per CL")
    e.add_argument("--batch-size", type=int, default=200, help="NoteDb refs per git fetch")
    o = sub.add_parser("extract-open",
                       help="snapshot open CLs (and CLs closed after the newest fetched week) "
                            "and fetch their NoteDb refs, so recent weeks are complete")
    o.add_argument("--since", help="open CLs updated at/after this UTC date "
                                   "(default: start of the oldest fetched week)")
    o.add_argument("--closed-since", help="also CLs closed at/after this UTC date "
                                          "(default: end of the newest fetched week)")
    o.add_argument("--host", default=HOST)
    o.add_argument("--project", default=PROJECT)
    o.add_argument("--interval", type=float, default=1.0,
                   help="min seconds between requests (default 1.0; never lower)")
    o.add_argument("--duty-cycle", type=float, default=1.0,
                   help="fraction of time a git fetch may be in flight (default 1.0: one fetch at a time, back to back)")
    o.add_argument("--batch-size", type=int, default=200, help="NoteDb refs per git fetch")
    o.add_argument("--max-comment-fetches", type=int, default=None,
                   help="only fetch NoteDb refs for N CLs (for smoke tests)")
    d = sub.add_parser("derive", help="rebuild derived.sqlite from the raw cache (offline)")
    d.add_argument("--week", action="append",
                   help="only CLs in this week's listing (default: every CL)")
    d.add_argument("--source", choices=["auto", "notedb", "rest"], default="auto",
                   help="comment source (auto = NoteDb if fetched, else REST cache)")
    d.add_argument("--out", help="derived DB path (default: data/private/derived.sqlite)")
    g = sub.add_parser("commits", help="update commits.sqlite, main's history, from the local Chromium "
                                        "git clone (offline; $COSH_CHROMIUM_GIT)")
    g.add_argument("--db", help="store path (default: $COSH_COMMITS_DB or data/private/commits.sqlite)")
    g.add_argument("--jobs", type=int, default=4, help="git diff processes for repetition ratios (at most 4)")
    sub.add_parser("fetch-git", help="fetch chromium/src main (only) into the shared clone "
                                     "~/projects/shared/chromium, under the extract lock")
    c = sub.add_parser("classify",
                       help="label review threads as addressed with Claude Haiku via `claude -p` "
                            "(uses Max usage; writes data/private/labels.sqlite; optional step)")
    c.add_argument("--week", action="append",
                   help="only threads with a comment written in this ISO week (repeatable; default: all)")
    c.add_argument("--max-threads", type=int, help="label at most N threads this run")
    c.add_argument("--batch", type=int, default=100, help="threads per claude -p call (default 100)")
    c.add_argument("--model", default="haiku", help="claude -p model alias (default haiku)")
    c.add_argument("--jobs", type=int, default=8,
                   help="claude -p calls run at once (default 8, at most 16)")
    c.add_argument("--dry-run", action="store_true", help="count pending threads, call nothing")
    c.add_argument("--sandbox", choices=["auto", "bwrap", "none"], default="auto",
                   help="jail for claude -p (SECURITY.md): auto = bubblewrap if it works here")
    c.add_argument("--db", help="derived DB path (default: data/private/derived.sqlite)")
    s = sub.add_parser("summarize", help="write summaries/ (path scope: config/paths.txt)")
    s.add_argument("--metric", choices=["comments", "cls", "chars", "addressed", "commits"], default="comments",
                   help="headline share: review comments (default), reviewed CLs, characters, "
                        "or addressed comments")
    s.add_argument("--db", help="derived DB path (default: data/private/derived.sqlite)")
    s.add_argument("--out", help="summaries directory (default: summaries/)")
    b = sub.add_parser("backfill", help="extract many weeks newest-first (plan only without --go)")
    b.add_argument("--weeks", type=int, required=True, help="number of weeks to cover")
    b.add_argument("--newest", help="newest ISO week (default: last complete week)")
    b.add_argument("--duty-cycle", type=float, default=1.0,
                   help="fraction of time a git fetch may be in flight (default 1.0: one fetch at a time, back to back)")
    b.add_argument("--batch-size", type=int, default=200)
    b.add_argument("--jobs", type=int, default=1,
                   help="NoteDb fetches in flight at once (default 1; more only with the user's "
                        "approval: 6 approved until Monday 2026-11-09, CLAUDE.md)")
    b.add_argument("--jobs-until",
                   help="ISO time after which --jobs drops to 1 (e.g. 2026-11-09T00:00-05:00)")
    b.add_argument("--go", action="store_true", help="actually fetch (otherwise print the plan)")
    b.add_argument("--host", default=HOST)
    b.add_argument("--project", default=PROJECT)
    m = sub.add_parser("notedb-maintain",
                       help="lossless local housekeeping of the NoteDb repo (pack refs, "
                            "multi-pack index); takes the extract lock, no network")
    m.add_argument("--project", default=PROJECT)
    ps = sub.add_parser("patchsets",
                        help="fetch every patch set (with blobs) of CLs that have human review "
                             "comments into data/private/git/chromium-patchsets.git "
                             "(plan only without --go; resumable)")
    ps.add_argument("--go", action="store_true", help="actually fetch (otherwise print the plan)")
    ps.add_argument("--interval", type=float, default=2.0,
                    help="seconds between fetches (default 2.0; never below 1.0)")
    ps.add_argument("--max-cls", type=int, default=1000, help="CLs per fetch (default 1000)")
    ps.add_argument("--max-patchsets", type=int, default=5000,
                    help="patch sets per fetch (default 5000)")
    ps.add_argument("--max-batches", type=int, help="stop after N fetches (for smoke tests)")
    ps.add_argument("--jobs", type=int, default=1,
                    help="fetches in flight at most (default 1, at most 8; fewer while "
                         "googlesource rate-limits us; above 1 needs "
                         "the user's approval, CLAUDE.md)")
    ps.add_argument("--repack-gb", type=float, default=8.0,
                    help="repack after this many GB of new packs (default 8; it also repacks "
                         "when under 25 GB is free, and always at the end)")
    ps.add_argument("--db", help="derived DB path (default: data/private/derived.sqlite)")
    ps.add_argument("--since", default=None,
                    help="CLs closed (or last updated) on or after this date (default and earliest: "
                         "config/approved.json)")
    sub.add_parser("status", help="show extraction progress")
    sub.add_parser("update-affiliations", help="refresh config/affiliations.json5 from chromium/src")
    r = sub.add_parser("radar", help="fetch Cloudflare Radar browser share (needs CLOUDFLARE_API_TOKEN) "
                                     "and write data/public/radar_browser_share.csv")
    r.add_argument("--start", default="2020-09-01", help="earliest date to request (YYYY-MM-DD)")
    r.add_argument("--agg", choices=["1d", "1w"], default="1d",
                   help="Radar aggInterval (default 1d, aggregated locally to ISO weeks and months)")
    r.add_argument("--limit-per-group", type=int, default=50, help="Radar limitPerGroup (top N + other)")
    r.add_argument("--interval", type=float, default=1.0, help="min seconds between requests (>= 1.0)")
    r.add_argument("--retry-errors", action="store_true", help="re-request chunks cached as HTTP 4xx")
    r.add_argument("--offline", action="store_true", help="only rebuild the CSV from the raw cache")
    sub.add_parser("update", add_help=False,
                   help="rerun what is downstream of new data, in order (python3 -m cosh update --help)")
    if argv is None:
        argv = sys.argv[1:]
    if argv[:1] == ["update"]:
        from .update import main as update
        sys.exit(update(argv[1:]))
    a = p.parse_args(argv)

    # Commands that talk to a server need the contact e-mail (cosh/contact.py).
    # Check before taking locks or starting work, so a missing one fails fast.
    if (a.cmd in ("extract", "extract-open", "update-affiliations", "fetch-git")
            or (a.cmd in ("backfill", "patchsets") and a.go)
            or (a.cmd == "radar" and not a.offline)):
        from .contact import ContactMissing, contact
        try:
            contact()
        except ContactMissing as e:
            p.exit(2, f"cosh {a.cmd}: error: {e}\n")

    if a.cmd == "extract":
        if a.interval < 1.0:
            p.error("--interval below 1.0s is not allowed (be polite to Gerrit)")
        from .extract import extract_week
        from .approved import check_weeks
        check_weeks([a.week])
        with store.extract_lock():
            extract_week(a.host, a.project, a.week, min_interval=a.interval,
                         max_comment_fetches=a.max_comment_fetches, argv=" ".join(sys.argv),
                         via=a.via, batch_size=min(a.batch_size, 500))
    elif a.cmd == "extract-open":
        if a.interval < 1.0:
            p.error("--interval below 1.0s is not allowed (be polite to Gerrit)")
        if not 0.05 <= a.duty_cycle <= 1.0:
            p.error("--duty-cycle must be in [0.05, 1.0]")
        from .extract import extract_open
        with store.extract_lock():
            extract_open(a.host, a.project, since=a.since and _utc(a.since),
                         closed_since=a.closed_since and _utc(a.closed_since),
                         min_interval=a.interval, argv=" ".join(sys.argv),
                         batch_size=min(a.batch_size, 500), duty_cycle=a.duty_cycle,
                         max_comment_fetches=a.max_comment_fetches)
    elif a.cmd == "derive":
        from .derive import derive
        derive(weeks=a.week, source=a.source, out_path=a.out)
    elif a.cmd == "commits":
        from .commits import update
        update(a.db, jobs=max(1, min(a.jobs, 4)))
    elif a.cmd == "fetch-git":
        from .commits import fetch_main
        with store.extract_lock():
            old, new = fetch_main()
        print(f"main: {old[:12]} -> {new[:12]}" if old != new else f"main: up to date at {new[:12]}")
    elif a.cmd == "classify":
        from .classify import classify
        classify(db_path=a.db, weeks=a.week, model=a.model, batch=max(1, min(a.batch, 200)),
                 max_threads=a.max_threads, dry_run=a.dry_run, jobs=max(1, min(a.jobs, 16)),
                 sandbox=a.sandbox)
    elif a.cmd == "summarize":
        from .summarize import summarize
        kw = dict(out_dir=a.out) if a.out else {}
        for r in summarize(db_path=a.db, metric=a.metric, **kw):
            print(f"{r['iso_week']}  {r['org']:<24} share={r['share']:<7} "
                  f"reviewers={r['reviewers']:>4} comments={r['comments']:>6} "
                  f"cls={r['reviewed_cls']:>5} chars={r['review_chars']:>8} "
                  f"ai={r['ai_comments']:>5} post_merge={r['post_merge_comments']:>4} "
                  f"addressed={r['addressed_comments']:>5} pending={r['pending_comments']:>5}")
    elif a.cmd == "backfill":
        from .backfill import backfill, last_complete_week, week_list
        if not 0.05 <= a.duty_cycle <= 1.0:
            p.error("--duty-cycle must be in [0.05, 1.0]")
        weeks = week_list(a.newest or last_complete_week(), a.weeks)
        if not 1 <= a.jobs <= 6:
            p.error("--jobs must be 1..6 (more needs the user's approval)")
        if a.jobs > 1 and not a.jobs_until:
            p.error("--jobs above 1 needs --jobs-until (the approval is time-limited)")
        from datetime import datetime as _dt
        until = _dt.fromisoformat(a.jobs_until).timestamp() if a.jobs_until else None
        kw = dict(go=a.go, duty_cycle=a.duty_cycle, batch_size=min(a.batch_size, 500),
                  argv=" ".join(sys.argv), jobs=a.jobs, jobs_until=until)
        if a.go:
            from .approved import check_weeks
            check_weeks(weeks)
            with store.extract_lock():
                backfill(a.host, a.project, weeks, **kw)
        else:
            backfill(a.host, a.project, weeks, **kw)
    elif a.cmd == "patchsets":
        if a.interval < 1.0:
            p.error("--interval below 1.0s is not allowed (be polite to googlesource)")
        from . import patchsets
        from .approved import patchsets_range
        since, until = patchsets_range(a.since)
        kw = dict(derived_path=a.db, interval=a.interval, max_cls=a.max_cls,
                  max_ps=a.max_patchsets, max_batches=a.max_batches,
                  repack_bytes=a.repack_gb * 1e9, jobs=max(1, min(a.jobs, 8)),
                  since=since, until=until)
        if a.go:
            with store.extract_lock():
                patchsets.run(go=True, **kw)
        else:
            patchsets.run(**kw)
    elif a.cmd == "notedb-maintain":
        from . import notedb
        with store.extract_lock():
            print(f"maintained in {notedb.maintain(notedb.default_repo(a.project)):.0f}s",
                  file=sys.stderr)
    elif a.cmd == "update-affiliations":
        from .orgs import update_affiliations, load_affiliations
        update_affiliations()
        print(f"{len(load_affiliations())} affiliation entries")
    elif a.cmd == "radar":
        if a.interval < 1.0:
            p.error("--interval below 1.0s is not allowed")
        import datetime
        from .radar import run
        run(start=datetime.date.fromisoformat(a.start), agg=a.agg, offline=a.offline,
            limit_per_group=a.limit_per_group, retry_errors=a.retry_errors, min_interval=a.interval)
    elif a.cmd == "status":
        raw = store.open_raw_ro()
        for r in raw.execute("SELECT * FROM week_progress ORDER BY iso_week"):
            print("week:", r)
        if store.has_table(raw, "open_listings"):
            for r in raw.execute("SELECT * FROM open_listings ORDER BY listed_at"):
                print("open snapshot:", r)
        for r in raw.execute("SELECT run_id, started_at, finished_at, requests, status "
                             "FROM extract_runs ORDER BY run_id DESC LIMIT 5"):
            print("run:", r)
        print("cached responses:", raw.execute(
            "SELECT kind, count(*), sum(length(body_zlib)) FROM responses GROUP BY kind").fetchall())


if __name__ == "__main__":
    main()
