# cosh: notes for Claude sessions

Start with `docs/plan.md`, which covers the goal, ground rules, the decisions
log, status and next steps. Then read `docs/extraction-v1.md` for the
implementation and metric definitions.

## Hard rules

- **Don't fetch more than the one Gerrit week already fetched (2026-W44)**
  until the user has validated the web UI. Never run `cosh backfill ... --go`
  or `extract` for another week without explicit approval in the current
  conversation.
- **Keep load on Gerrit and googlesource low.**
  - Requests are serial.
  - Never lower `--interval` below 1 s.
  - Never run two extractors at once.
  - Use NoteDb batches, not REST requests per CL.
- **Personal data stays out of git.** `data/private/` holds emails. Commit
  only aggregates, public data, config, code and docs.
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
