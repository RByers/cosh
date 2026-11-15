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
  review-feedback   ─▶ Feedback Index global data ─────────────────────┬─▶ Feedback Index
  (cosh.review_feedback) ─▶ per-person files ─ r2-feedback ─▶ in R2 ──┤
  review-threads ─▶ full threads ─ r2-feedback ─▶ threads in R2 ──────┘
  (per-person files + NoteDb + reviews.sqlite + addressed.sqlite)
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
   doc), `one-off` or `maintenance`, and never runs in an update.
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
    and an edit to that file, logged in `docs/plan.md`. CLAUDE.md keeps the
    reasons and the load rules.
11. **A step is offline unless the inventory says it fetches.** The
    affiliations files too: only `update-affiliations` fetches them, and the
    steps that attribute orgs read the local copy.
12. **Keep whatever we download, download only what we need**
    (`docs/storage-design.md` §3.8). Raw stores are never slimmed or pruned;
    data is reduced only in derived stores.

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

  `duration`, `token_cost` and `cost_source` are measured figures and
  where each was measured; `null` means nobody has measured it.
- **`pages[]`**: a page of the site, the stores it `reads`, and the `names`
  of its analysis for rule 4.

Building and deploying the site (`npm run build`; the Pages workflow on
push) is not a data step and isn't listed.

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
purposes, sizes or costs: keep those current by hand (CLAUDE.md).

## 4. Running it

`python3 -m cosh update [--from ID ...] [--with-optional] [--dry-run]`
plans from the given sources or stores (default: every source), runs each
planned step that has a `run` command, in flow order, stops at the first
failure, and lists the steps left for a person (fetches, which need
approval, and model calls, which cost usage) with their measured cost, then
the files to commit.

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
