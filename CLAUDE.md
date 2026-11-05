# cosh: notes for Claude sessions

Start with `docs/plan.md`, which covers the goal, ground rules, the decisions
log, status and next steps. Then read `docs/extraction-v1.md` for the
implementation and metric definitions, and `docs/comment-classifier.md` for
the primary metric: addressed review comments, classified by a regex plus
Claude Haiku (`cosh classify`).

## Hard rules

- **The 52-week backfill (2025-W45 .. 2026-W44) is approved** and was started
  on 2026-11-03. It is resumable: rerun `python3 -m cosh backfill --weeks 52
  --go` from the main checkout if it stops. Fetching beyond that year (years
  2–5, other repos or hosts) still needs explicit approval.
- **Backfill back to 2023-07-01 (Radar's first data) is approved**
  (2026-11-04). That is `backfill --weeks 175 --newest 2026-W44`, 2023-W26 ..
  2026-W44, started 2026-11-04 with log `data/private/backfill-3y-*.log`. It is
  resumable with the same command. Nothing earlier is approved.
- **The open-CL snapshot for that year is approved** (2026-11-03):
  `python3 -m cosh extract-open` lists open CLs updated since the oldest
  fetched week, plus CLs closed after the newest one, and fetches their NoteDb
  refs. Run it only after the backfill has finished, never alongside it.
  Rerunning it to refresh is fine.
- **Keep load on Gerrit and googlesource low.**
  - Requests are serial.
  - Never lower `--interval` below 1 s.
  - Never run two extractors at once. `extract`, `extract-open` and
    `backfill --go` take `data/private/extract.lock`. (Backfills started
    before 2026-11-03 don't take it.)
  - Use NoteDb batches, not REST requests per CL.
- **Per-person data may be committed and published** (in git and on the
  public site) when it is derived from already-public data, such as
  Chromium Gerrit reviews. This is the user's policy as of 2026-11-03
  (`docs/plan.md`, ground rule 3). `data/private/` is still gitignored, but
  because it holds multi-GB raw caches and rebuildable DBs, not because the
  data is personal. Anything not from a public source still needs the user's
  approval before it's committed.
- **The Radar token** is loaded with `source secrets.sh`. Never print or
  commit it.

## Conventions

- Python standard library only. Run with `python3 -m cosh <cmd>`.
- Tests: `python3 -m unittest tests.test_derive tests.test_extract tests.test_radar tests.test_classify`.
  These run in a single process, which complies with the global limit of 4
  test workers. `tests.test_extract` uses a fake Gerrit and never touches the
  network.
- Data lives in `data/private/` next to the code, or in `$COSH_DATA_DIR`. From
  a worktree, point `COSH_DATA_DIR` at the main checkout's `data/private` and
  pass `derive --out` / `summarize --db` a scratch path. `derive` and
  `summarize` open `raw.sqlite` read-only, so they're safe while an extractor
  runs.
- Web UI: `web/` (Vite + TypeScript, Chart.js). `cd web && npm test` builds
  it and runs Vitest unit tests and headless-Chrome tests (puppeteer-core with
  `/usr/bin/google-chrome`). Vitest is capped at `maxWorkers: 4`, with test
  files run serially.
- In a worktree, give `web/` its dependencies by symlinking the main
  checkout's: `ln -s /home/rbagent/projects/cosh/web/node_modules
  web/node_modules`. Don't run `npm ci` or `npm install` there. Git ignores
  the link, so leave it in place: `git worktree remove` cleans it up, and
  removing it yourself triggers a permission prompt.
- `data/private/derived.sqlite` can always be rebuilt with
  `rm data/private/derived.sqlite && python3 -m cosh derive` (about 9 min
  for 666k CLs, 2026-11-04, threads included). It is the only derived DB: older versions (`cosh.sqlite`,
  metric_versions 1–2; `derived.sqlite` before metric_version 5) were
  deleted on 2026-11-04, and `open_derived` refuses a pre-v5 file.
- Never delete `data/private/raw.sqlite` or `data/private/notedb/`. Those
  hold the fetched data, and re-fetching costs server load.
- Never delete `data/private/labels.sqlite` either. It holds the
  addressed-comment labels from `python3 -m cosh classify`, and remaking them
  costs the user's Claude Pro usage. Unlike `derived.sqlite`, it is not
  rebuildable. `classify` is an optional step after `derive`. It runs
  headless `claude -p` (Haiku) serially, so size each run with `--week` or
  `--max-threads` and check `--dry-run` first. Without labels, `summarize`
  and the UI still work; the addressed metric is then shown only for weeks
  that are classified.
- **Keep whatever we download; download only what we need.** Anything we
  put server load on to fetch is kept, losslessly, so it never has to be
  fetched again if we later want it (`docs/storage-design.md` §3.8). This is
  not a rule to download everything: fetching less, e.g. a narrower query or
  a leaner fetch, is welcome when it still gets what we need. But what does
  come over the wire stays. Never strip, truncate or "slim" the raw stores,
  and never prune a NoteDb repo (`gc --prune`, `prune`). Reduce data only in
  `derived.sqlite`. Lossless housekeeping (`cosh notedb-maintain`,
  `repack -a -d` without pruning) is fine.

## Finishing work

When a piece of work is complete (tests pass, changes committed on the
worktree branch), land it on `main` automatically, without asking:

1. Rebase the branch onto the current `main` from the worktree:
   `git rebase main`. Resolve any conflicts and rerun the relevant tests if
   the rebase changed anything.
2. Leave the worktree (ExitWorktree with `keep`), then fast-forward `main`
   from the main checkout (`/home/rbagent/projects/cosh`):
   `git merge --ff-only <branch>`. A worktree session can't run git against
   the main checkout, so this step has to happen after exiting.
3. Only fast-forward. Never create a merge commit. If the fast-forward fails
   because `main` moved, rebase again and retry. If uncommitted changes in
   the main checkout block it, stop and report instead of touching them.
4. Once `main` contains the branch, delete the worktree and the branch from
   the main checkout:
   `git worktree remove .claude/worktrees/<name> && git branch -d <branch>`.
   Use `-d`, not `-D`, so git refuses if the branch isn't fully merged.
   Don't delete worktrees or branches that belong to other sessions.
