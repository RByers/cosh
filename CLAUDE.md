# cosh: notes for Claude sessions

Start with `docs/plan.md`, which covers the goal, ground rules, the decisions
log, status and next steps. Then read `docs/extraction-v1.md` for the
implementation and metric definitions.

## Hard rules

- **The 52-week backfill (2025-W45 .. 2026-W44) is approved** and was started
  on 2026-11-03. It is resumable: rerun `python3 -m cosh backfill --weeks 52
  --go` from the main checkout if it stops. Fetching beyond that year (years
  2–5, other repos or hosts) still needs explicit approval.
- **Keep load on Gerrit and googlesource low.**
  - Requests are serial.
  - Never lower `--interval` below 1 s.
  - Never run two extractors at once.
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
- Tests: `python3 -m unittest tests.test_derive tests.test_radar`. These run
  in a single process, which complies with the global limit of 4 test
  workers.
- Web UI: `web/` (Vite + TypeScript, Chart.js). `cd web && npm test` builds
  it and runs Vitest unit tests and headless-Chrome tests (puppeteer-core with
  `/usr/bin/google-chrome`). Vitest is capped at `maxWorkers: 4`, with test
  files run serially.
- `data/private/cosh.sqlite` can always be rebuilt with
  `rm data/private/cosh.sqlite && python3 -m cosh derive`.
- Never delete `data/private/raw.sqlite` or `data/private/notedb/`. Those
  hold the fetched data, and re-fetching costs server load.
- **Keep everything downloaded.** The raw stores are lossless on purpose
  (`docs/storage-design.md` §3.8). Never strip, truncate or "slim" them, and
  never prune a NoteDb repo (`gc --prune`, `prune`). Reduce data only in
  `cosh.sqlite`.

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
