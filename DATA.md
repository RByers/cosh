# cosh: where the data is kept, and what protects it

argus's data retention scheme (`~/projects/argus-config/dataretention.md`)
sorts each project's data into classes. This file lists cosh's. What each
store holds and which steps write it is in `config/dataflow.json` and
`docs/data-architecture.md`; this file only says how each is protected.

## Classes

| Class | What | Protected by |
|---|---|---|
| permanent-small | code, docs, `config/`, `summaries/`, `web/public/` data | git, pushed to GitHub |
| permanent-large | the stores below: fetched with server load, or labelled at a cost in Claude usage | `/protected/permanent/` snapshots: monthly ones kept forever |
| transient | everything else in `data/private/`: derived DBs (`reviews.sqlite`, `commits.sqlite`, `review-timeline.sqlite`, `balance*.sqlite`), published files, `comments/comments-*.jsonl`, `scratch/`, `logs/`, `backup-*/`; and the shared clone `~/projects/shared/chromium` | nothing: rebuild it, or fetch it again |

## Paths on /protected (permanent-large)

Each is moved to the same path under
`/protected/permanent/rbagent/projects/cosh/` and an absolute symlink is
left in its place in the main checkout (2026-11-15). Code keeps using the
`data/private/...` paths; worktrees reach them through `COSH_DATA_DIR`.
The symlinks aren't in git (`data/private/` is ignored).

| Path in `data/private/` | Size (2026-11-15) | Updated | Added to the archive per year (est.) |
|---|---|---|---|
| `notedb/chromium_src.git/` | 11.3 GB | each fetch adds packs; `packed-refs` (42 MB) is rewritten | 6–9 GB |
| `gerrit.sqlite` | 2.6 GB | each fetch inserts or replaces raw responses (about 75 MB a week) | about 4 GB |
| `git/chromium-patchsets.git/` | 18.3 GB | each run adds one pack (about 120 MB a week) | about 6 GB |
| `addressed.sqlite` | 41 MB | `classify` appends (keys start with the CL number) | tens of MB |
| `sentiment.sqlite` | 54 MB | `cosh.sentiment score` appends, as above | tens of MB |
| `ai_predict/` | 202 MB | `score` appends; rarely run | about 0 |
| `bugs/` (`raw/`, `bugs.sqlite`) | 1.4 GB | raw files only added; `parse` rewrites the 71 MB bugs table | under 0.5 GB |
| `chrome_releases/` | 34 MB | rarely | about 0 |
| `feedback-coach/` | 264 KB | rarely | about 0 |
| `comments/gold.jsonl`, `comments/tune-*.json` | under 1 MB | by hand | about 0 |

About 34 GB in all, growing to roughly 50–55 GB of snapshot space after a
year.

## Rules for the protected stores

- **Nothing written there is ever freed.** A snapshot is kept forever each
  month, so a rewritten or deleted file still takes its old space. Append;
  don't rewrite.
  - **Don't repack either git repo whole.** That adds a full copy (11 GB
    or 18 GB) to the archive. Rolling up only the small new packs costs about
    their own size. The patch-set repo's yearly repack (AGENTS.md) and
    `scripts/notedb_chunked_repack.sh` should group only the packs added
    since the last one.
  - No `VACUUM`, no schema change that copies a table, and no restoring a
    backup over one of these databases.
- **Never replace a symlink with a file.** A tool that saves by writing a
  temporary file and renaming it over the path would turn the link into a
  plain file on the unprotected disk. SQLite and git write through the link,
  and `cosh.bugs` renames only inside `bugs/raw/`, so nothing does this today.
- **The patch-set repo isn't complete on its own**: its alternates point at
  the shared clone, which isn't protected. The objects it relies on are on
  `main`, so a restore fetches the shared clone again first.
- A new store that can't be rebuilt goes here too: move it, link it, and add
  a row above.

## Restoring

Only root can read the snapshots (`/protected/.snapshots/permanent.<time>/rbagent/projects/cosh/...`):
ask the user. A deleted symlink is just recreated:
`ln -s /protected/permanent/rbagent/projects/cosh/data/private/<path> data/private/<path>`.
