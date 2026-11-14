# Planned renames

The data-flow page labels every database box with its file name
(`docs/data-architecture.md`, `stores[]`), so a database's file name has to
say what it holds. These three don't. Renaming them moves files in the main
checkout's `data/private/` and breaks every open worktree that still uses
the old name, so do it only when the project is idle.

| Now | Rename to | What it holds |
|---|---|---|
| `data/private/derived.sqlite` | `data/private/reviews.sqlite` | Per-CL, per-comment and per-thread review facts, no comment text |
| `data/private/labels.sqlite` | `data/private/addressed.sqlite` | Haiku's addressed / not-addressed label per review thread (never delete) |
| `data/private/raw.sqlite` | `data/private/gerrit.sqlite` | Every Gerrit REST response, and which weeks are done (never delete; sits beside `notedb/`) |

## When

- No extractor, `derive`, `classify`, `cosh.sentiment`, balance or patch-set
  run in progress (`ps -u rbagent -o pid,args | grep '[c]osh'`, and
  `flock -n data/private/extract.lock true`).
- No other session working in a cosh worktree, or each one warned: their
  branches must rebase onto the rename before running anything that opens
  these files.

## How

1. In one worktree commit, replace every reference (`git grep -n
   'derived\.sqlite\|labels\.sqlite\|raw\.sqlite'`): code defaults (`cosh/`,
   `scripts/`), tests, `config/dataflow.json` (store ids and paths, step
   inputs and outputs, the `raw.sqlite + notedb/` name), docs, `CLAUDE.md`
   and the memory notes that name them. Keep function names such as
   `open_derived` unless they read wrong. Run `python3 scripts/dataflow.py
   check` and the unit tests.
2. Land it on `main` (fast-forward, as in `CLAUDE.md`).
3. Right after, in the main checkout, move the files with `mv` (never copy
   and delete: `labels.sqlite` and `raw.sqlite` can't be remade). Move any
   `-wal` / `-shm` files with them, or checkpoint first.
4. Check that `python3 -m cosh summarize` and `cosh update --dry-run` (or
   their equivalents) open the new names, then delete this file in a
   follow-up commit.
