# cosh: data architecture

> **Kept current.** This document describes the data architecture as it is
> now, and is updated in the same change as anything it describes. It holds
> no history and no done-lists: to see what changed and when, compare
> versions in git (`git log -p docs/data-architecture.md`, and the same for
> `config/dataflow.json`). Decisions and their reasons are logged in
> `docs/plan.md`.

The facts are in `config/dataflow.json` (the inventory): every source,
store, step and page, with paths, sizes, row counts, commands, measured
times and costs. They live there and only there; this document and the
other docs point to it rather than repeat its figures.

- `web/dataflow.html` draws it: the flow of the pages you pick, top to
  bottom, the facts of any item with sample entries of each store, a
  planner, and tables.
- `python3 scripts/dataflow.py check` verifies it against the repository
  and the flow rules below (run by `tests.test_dataflow`).
- `python3 scripts/dataflow.py plan <id> ...` prints what to rerun after
  new data, in order, and the files to commit.
- `python3 -m cosh update` runs that plan (section 4).

## 1. The shape

Data moves down through five tiers. The first three live in `data/private/`
(gitignored because of size, not privacy), the published tier is committed,
and the site is built from it, apart from files too big for git, which go
to the Cloudflare R2 bucket `cosh` (`cosh.r2 sync`; `docs/r2.md`).

| Tier | What | If lost |
|---|---|---|
| `raw` | fetched from outside, kept losslessly | refetch: server load, maybe approval |
| `labels` | model output (Haiku scores and labels) | pay Claude usage again |
| `derived` | computed from local data | rerun a step |
| `published` | what a page reads, committed (or uploaded to R2) | rerun and commit (or sync) |
| `config` | hand-kept input in git | can't be regenerated |
| `analysis` | scratch behind a doc, off every page's flow | rerun a script, or nothing |

The dashboards other than Review Balance share one concise flow:

```
Chromium Gerrit ─ gerrit-fetch ─▶ gerrit.sqlite + notedb/ ─ derive ─▶ reviews.sqlite ─┬─ classify ─▶ addressed.sqlite
Chromium git ─── fetch-git ───▶ Chromium git clone ── commits ─▶ commits.sqlite       ├─ comments-collect ─▶ Rendered comments
Affiliations file ─ update-affiliations ─▶ affiliations.json5                         │     └─ comments-score ─▶ sentiment.sqlite
Cloudflare Radar ── radar ─▶ Browser shares (Radar)                                   │
Claude (Haiku): classify, comments-score, tone-publish's screening                    │
                                                                                      ▼
  summarize      ─▶ Value Exchange summaries ─┐
  (+ Radar shares, org_browsers.csv)          ├─▶ Value Exchange
  tone-publish   ─▶ Review Tone summaries ────┼─▶ Review Tone
  review-feedback   ─▶ FI global data ─────────────────────────────────┬─▶ Feedback Index
  (cosh.review_feedback) ─▶ per-person files ─ r2-feedback ─▶ in R2 ──┤
  review-threads ─▶ full threads ─ r2-feedback ─▶ threads in R2 ──────┘
  (its CL index + NoteDb + reviews.sqlite + addressed.sqlite)
  review-timeline   ─▶ review-timeline.sqlite ─ review-load ─▶ all.json ─────────────────▶ Review Load
  (NoteDb + listings + reviews.sqlite)          (+ commits.sqlite) └▶ per-reviewer files ─ r2-review-load ─▶ in R2 ─┘
```

`review-timeline.sqlite` (each CL's uploads, attention-set changes and
votes, and each reviewer's wait on it) is shared: Review Load publishes
from it, and Review Balance's stages read it (`docs/review-load.md`).

The Feedback Index's charts and tables read only its global and per-person
files. No review tone reaches it. Comment text reaches it only through the
threads in R2, fetched when someone downloads their comments, and goes only
into the downloaded file.

`reviews.sqlite` (per-CL, per-comment and per-thread facts, no comment
text) and `commits.sqlite` (main's whole first-parent history) are the two
hubs nearly everything reads. Comment text exists only in NoteDb, the
rendered comment files and the comment download's thread files, and
reaches a model of ours only through
`cosh.sandbox.Sandbox`.

**Review Balance** is a separate flow on top of the same hubs and the
review timeline: its stage
databases (`balance-interdiff`, `balance.sqlite`), the
AI-marker and AI-prediction stores, the clusters, the review-ROI results
and `python3 -m cosh.balance_publish`. Everything named "balance" feeds only
that page, and none of the other pages depends on any of it (the
naming rule below checks this), so it can be changed or deleted on its own.

## 2. Flow rules

`scripts/dataflow.py check` enforces the first five; the rest are how the
system is kept, and the inventory says where a step departs from them.

1. **Every flow has inflows.** Everything a page reads traces back, through
   the steps that write it, to an external source. The only stores with no
   writer are config. (So in the drawn flow the top layer holds only
   sources and config.)
2. **Every flow has a final output.** Every step that runs as part of an
   update (`routine` or `optional`) leads to something a page reads. A step
   whose output reaches no page is an `analysis` (its output goes into a
   doc), `one-off` or `maintenance`, and never runs in an update. Uploads
   to R2 are `deploy`: they reach pages, but run only when deploying.
3. **Every step writes something.**
4. **Names say who uses them.** A source, step or store is named after an
   analysis (a page's `names`: value, tone, balance, feedback) only when it
   feeds that page alone. Anything shared is named for what it holds:
   `review-timeline.sqlite`, not "load-timeline", because the balance
   stages read it too.
5. **Every source is read** by some step.
6. **One writer per store.** A step that lists a store as both input and
   output resumes from it; that is not a second writer. A store a step
   rewrites in place (NoteDb housekeeping) is `maintenance`. A cache table
   a step keeps inside another's store (screening verdicts in
   `sentiment.sqlite`) is noted on the step, not drawn.
7. **Steps on the way to a page are cosh commands** (`python3 -m cosh …`,
   `python3 -m cosh.<module>`), with a `run` command that `cosh update` may
   run when the step is free and local. `scripts/` holds analyses.
   Exceptions today are Review Balance's script steps (section 5).
8. **Date ranges come from the data.** Review Tone's year is the newest
   run of up to 52 fully scored weeks
   (`cosh.sentiment.scored_weeks`); Review Balance's window ends with the
   newest fetched week (`balance_publish.DATA_END`); Value Exchange covers
   every fetched week. A fixed range is an explicit argument.
9. **Incremental steps key on content, not on the CL number.** The review
   timeline keeps each CL's meta-ref tip and each listing's body hash, and the patch-set fetch keeps
   each CL's patch-set count; a CL whose marker no longer matches is read
   again.
10. **Approvals are data.** `config/approved.json` gives each fetcher its
    approved range; `extract`, `backfill`, `patchsets` and `cosh.bugs`
    refuse anything outside it. Widening a range needs the user's approval
    and an edit to that file, logged in `docs/plan.md`. AGENTS.md keeps the
    reasons and the load rules.
11. **A step is offline unless the inventory says it fetches.** The
    affiliations files too: only `update-affiliations` fetches them, and the
    steps that attribute orgs read the local copy.
12. **Keep whatever we download, download only what we need**
    (`docs/storage-design.md` §3.8). Raw stores are never slimmed or pruned;
    data is reduced only in derived stores.
13. **Every analysis page says what dates its data covers, from the data
    itself** (below, "Data spans").

### Data spans

Each analysis page shows a subtitle under its title, "Based on Chromium
Gerrit and git data from 3 Jul 2017 to 1 Nov 2026". Its dates are never
typed by hand: the step that publishes the page's data writes a
`data_span` into the first file the page loads, in the same run and from
the same inputs as the figures, so the two can't disagree:

    "data_span": {"first": "2017-07-03", "last": "2026-11-01", "sources": ["gerrit", "git"]}

`cosh.data_span.of_data` makes it. `first` and `last` are UTC days, both
included. `last` is the oldest of the step's own end (a whole quarter or
month, for pages that show those) and every source's end, so a page built
from Gerrit through 1 Nov and git through 7 Nov is current to 1 Nov:
Gerrit ends with the newest week `derive` recorded as fetched
(reviews.sqlite's `fetched_weeks`), git on the day the newest commit in
commits.sqlite landed. `web/src/data-span.ts` renders it into the page's
`<p id="data-span">` with the page's `<template data-msg="data-span">`,
which names the sources; a page reading several stamps (Value Exchange
adds Radar's weeks) shows the window they all cover: the latest `first`
to the earliest `last`.

| Page | Stamped file | Written by |
|---|---|---|
| Value Exchange | `summaries/org_weekly.json` (`meta.data_span`), with Radar's weeks | `summarize` |
| Review Tone | `summaries/sentiment_monthly*.json` | `tone-publish` (its `summary` step) |
| Review Balance | `summaries/balance.json` | `balance-publish` |
| Feedback Index | `web/public/review-feedback/peers.json` | `review-feedback` |
| Review Load | `web/public/review-load/all.json` | `review-load` |

Because the stamp is written with the data, `cosh update` keeps every
subtitle current by itself: rerunning a page's steps after new data
rewrites both. A new analysis page stamps its first file the same way and
adds the subtitle; the browser tests check that every analysis page shows
one.

## 3. The inventory

`config/dataflow.json` has four lists. Ids are stable names the others
refer to: a source's short name, a store's path (or a short id for a store
that spans paths or files), a step's short name, `page-…` for a page.

- **`sources[]`**: an external system we fetch from, plus the Claude model.
  `access`, `load_rules` and `coverage` say how we may use it.
- **`stores[]`**: a database, git repo, directory or family of files.
  `tier` (table above); `name` (a short label for a family or a store
  that spans paths; a database's box always shows its file name, so a
  database's `name` must contain it, and a file name that doesn't say
  what the database holds is a reason to rename the file (the
  2026-11-14 renames: `docs/legacy-symlinks.md`); `tracked_in_git` and `git_paths` (globs; the path when
  absent) say what to commit; `tables` lists a database's tables or a
  family's members; `never_delete` marks what can't be remade.
- **`steps[]`**: a command. `inputs` and `outputs` are source and store ids,
  the edges of the graph. `command` is what a person types, `run` what
  `cosh update` may run by itself (absent for fetches and model calls).
  `refresh` says when it runs:

  | Value | Meaning |
  |---|---|
  | `routine` | free and local, or an approved small fetch; rerun whenever an input changes |
  | `optional` | costs Claude usage or needs approval; rerun when wanted |
  | `one-off` | a setup that is finished |
  | `analysis` | exploratory; its output goes into a doc, not the site |
  | `maintenance` | lossless housekeeping of a store in place |
  | `deploy` | uploads published files to R2; run only when deploying (`python3 -m cosh.r2 publish`, then push main: docs/r2.md), never in an update |

  `duration`, `token_cost` and `cost_source` are measured figures and
  where each was measured; `null` means nobody has measured it.
- **`pages[]`**: a page of the site, the stores it `reads`, and the `names`
  of its analysis for rule 4.

Building the site (`npm run build`; the Pages workflow on push) is not a
data step and isn't listed. Deploying is two steps: upload to R2 (the
`deploy` steps), then push main, which deploys GitHub Pages.

**Samples.** The page shows five sample entries of every store: rows of
each table, lines, CSV rows, JSON entries, files of a directory, refs of a
repo. `python3 scripts/dataflow_samples.py` takes them from the local
stores (read-only, nothing fetched) into `config/dataflow-samples.json`,
which is committed and so published; rerun it when a store's layout
changes. It is metadata about the inventory, not a step of the flow, so
it isn't drawn. Fields that steer it, on a store or a table:

- `columns`: what each column holds, shown as the column names' hover
  titles. A table's, or a single-file store's (a CSV).
- `withheld`: why a store's or a table's rows aren't published. Used for
  what the ground rules keep private: tone scores and model reasons
  (ground rule 5), gold sets, coaching reports, per-person drafts, and the
  AI-written guesses per CL.
- `redact`: columns whose values are left out (request headers that carry
  the contact address).
- `database`: the file that holds `tables`, when the store is a directory.

`check` fails when a withheld or redacted value is in the samples, or when
a sampled table has a column without a meaning (or a meaning for a column
it lacks).

`check` also fails when an id is unknown or duplicated, the graph has a
loop, a step's code file or a page doesn't exist, a committed file under
`summaries/`, `data/public/` or `config/` belongs to no store, or a page
script imports a data file that no page's `reads` covers. It can't check
purposes, sizes or costs: keep those current by hand (AGENTS.md).

## 4. Running it

`python3 -m cosh update [--from ID ...] [--with-optional] [--dry-run]`
plans from the given sources or stores (default: every source), runs each
planned step that has a `run` command, in flow order, stops at the first
failure, and lists the steps left for a person (fetches, which need
approval, and model calls, which cost usage) with their measured cost, then
the files to commit.

It skips a step when nothing it depends on changed since it last ran here:
its `run` command, the content of its code, the files of its `inputs`
(sizes and modification times; a git repo by its refs) and of its
`outputs` (a missing or changed output runs it again). Its code is its
`code` files plus every Python module under `cosh/` and `scripts/` and every
`config/` file that its processes loaded or opened on its last run:
`cosh update` runs each step with `cosh/steptrace/` on `PYTHONPATH`, whose
`usercustomize.py` records them. So a change to a module the step imports,
or to a config file it reads, runs it again even when `code` doesn't name
it; a run that left no trace counts every code and config file. A step that
reads an external data source always runs (it fetches); a model source
counts as unchanged, since the steps cache its answers. The record is
`data/private/update-state.json`, written after each step succeeds, with
the files traced, the run's time and its peak memory (the largest
process's resident set, which includes git's memory-mapped packs). So with
nothing fetched, `cosh update` takes seconds, and after a fetch only what is
downstream of the changed stores runs. `--force` runs every planned step;
`--record` marks them done without running them (after running them by
hand; a recorded step has no trace until it next runs). This relies on each
step's `inputs` and `outputs` being complete: a step that reads a data file
it doesn't list may be skipped wrongly.

Runs take turns, so they don't push each other over the shared memory cap
(5 GB, `cosh.memcap`). One `cosh update` runs at a time: a second one,
from any session, waits for `data/private/update.lock` and then plans again
from the first one's record, so it skips what that one just did. Each step
runs in the cap and holds its heavy-run lock (a file in `/run/user/<uid>/`
that every session shares), which every script that calls
`memcap.join()` or runs under `python3 -m cosh.memcap` takes too. So a
step waits while another session's heavy run is in memory, and the other
way round; whoever waits prints whose run it is waiting for.

Rerunning a step is not enough when the step is incremental within itself
and its code changed: it must notice that its earlier rows came from older
code, and recompute them without mixing old and new (docs/goals.md, goal
3). Each such store keeps a code fingerprint per part (`cosh/codefp.py`: a
hash of the functions, regexes and constants that compute the part, a
version to bump by hand for anything else, and whole files where a part is
coarse) and redoes only the parts whose fingerprint changed:

- `derive`: each CL's fingerprint (`derive_inputs`) includes the hash of
  `derive.CODE_FILES` and `METRIC_VERSION`, so a code change re-derives
  every CL (about 9 min).
- `commits.sqlite`: one fingerprint per part in `meta` (`code_fp:<part>`).
  A changed part (reverts, LSC tags, OWNERS additions, repetition ratios,
  renames) has its rows and `*_through` marker reset in the transaction
  that records the new fingerprint, and the run recomputes it over all of
  history; message fields (CL, approvers, reland, AI marker) are reread in
  place from one `git log`. A change to the core (commits and their
  files, which every part hangs off) makes `cosh commits` refuse until
  rerun with `--rebuild` (about 1 h 55 min). docs/commits.md.
- `review-timeline.sqlite`: the walk and the listing stages each keep one
  in `meta`; a change deletes that stage's rows and it reads everything
  again (walk about 35 min). `cl_reviewers` is rebuilt every run.
- `balance-interdiff.sqlite`: one in `meta`; a change deletes every row
  and the stage compares every CL again (about 25 min with 3 shards).

A store without a fingerprint yet adopts the current code's, keeping its
rows. Keep logging out of the hashed functions: any edit to their source
counts as a change.

A new week of data:

```
# after the user's approval, widen gerrit_weeks in config/approved.json
python3 -m cosh backfill --weeks 1 --newest <week> --go
python3 -m cosh extract-open
python3 -m cosh fetch-git
python3 -m cosh update                                    # derive, commits, collect, timeline, summaries
python3 -m cosh classify --week <week>                    # optional (cost: the inventory)
python3 -m cosh.sentiment score --week <week>             # optional
python3 -m cosh update --from data/private/addressed.sqlite data/private/sentiment.sqlite
python3 -m cosh.r2 publish                                # per-person files and threads to R2, before pushing
git add summaries config web/public/review-feedback web/public/review-load && git commit
```

Where things live on disk, beyond the stores:

- `data/private/logs/`: run logs and PID files of long runs.
- `data/private/scratch/<topic>/`: analysis output, safe to delete.
- `data/private/backup-<date>/`: copies of what a cleanup touched, kept
  until a person deletes them.

## 5. Where it falls short

- **Review Balance** carries most of the remaining irregularity: several of
  its steps are scripts (`balance_ai.py markers`, `balance_clusters.py`),
  the review-ROI results are copied by hand from the analyses' scratch
  output into `data/private/review_roi/`, its `growth` step still uses the
  older 50-file rule for mechanical CLs, and its stage databases sit loose
  in `data/private/` rather than in a folder of their own. It may be
  deleted rather than fixed.
- **`reviews.sqlite` is rebuilt whole** by a full `derive`. That is simple
  and takes minutes; it becomes worth making incremental only if it grows
  much slower.
- **Optional steps take their weeks by hand** (`classify --week`,
  `cosh.sentiment score --week`), deliberately: they cost usage, so each
  run is sized first.
- **Some costs are unmeasured** (`duration: null` in the inventory).
