# cosh: data architecture

Status: review of 2026-11-12, updated the same day. This covers how cosh's
data fits together, what makes it hard to manage, the architecture to aim
for, and the changes that get there. Section 6 records what has been done
since the review; items marked *(done)* below are resolved.

The facts are in `config/dataflow.json`: every source, store, step and page.
`web/dataflow.html` shows it as tables and a graph, and
`python3 scripts/dataflow.py plan <id>` prints what to rerun. This document
doesn't repeat the inventory. Sizes, row counts, commands and costs live
there, and only there.

## Summary

- **Today:** 10 external sources, 47 stores, 42 steps, 6 pages. The Gerrit
  core (`extract` → `derive` → `classify` → `summarize`) is clean: one module
  each, one writer per store, one command per step. Radar is cleaner still.
- **The hard parts are the three pipelines that grew out of analysis:**
  balance, sentiment and review feedback. They work, but they depend on
  hand steps, files with no fixed home, date ranges typed or hard-coded per
  script, and a published file with about a dozen writers.
- **The fix is mostly convention, not new machinery:** one command per
  published file, one writer per store, date ranges taken from the data,
  inputs at fixed paths, and an `update` command that walks the inventory.
- **Two things still need your decision** (section 5): whether to delete a
  2.1 GB leftover, and whether the Review Balance and Review Tone pages
  should follow new weeks or stay fixed-window analyses. How the Feedback
  Index is published was decided on 2026-11-12: its files are committed.

## 1. The inventory

`config/dataflow.json` has five lists. Ids are stable names that the other
lists refer to.

| List | One entry per | Id |
|---|---|---|
| `groups` | pipeline (Gerrit core, balance, …) | short word |
| `sources` | external system we fetch from, plus the Claude model | short name |
| `stores` | database, git repo, directory, or family of published files | its path |
| `steps` | command a person or script runs | short name |
| `pages` | page of the site | `page-…` |

Fields that scripts rely on:

- **`stores[].tier`** says what losing the store costs.

  | Tier | Meaning | If lost |
  |---|---|---|
  | `raw` | fetched from outside | refetch: server load, maybe approval |
  | `labels` | model output | pay Claude usage again |
  | `derived` | computed from local data | rerun a step |
  | `analysis` | scratch behind a doc | rerun a script, or nothing |
  | `published` | what a page reads | rerun and commit |
  | `config` | hand-kept input | can't be regenerated |

- **`stores[].tracked_in_git`** and **`git_paths`** (globs; the store's
  `path` when absent) say which files to commit when the store changes.
- **`stores[].tables`** lists a database's tables with row counts, or a
  file family's members.
- **`steps[].inputs` / `outputs`** are source and store ids. These are the
  edges of the graph. A step that lists a store in both resumes from it.
- **`steps[].refresh`** says when a step runs.

  | Value | Meaning |
  |---|---|
  | `routine` | free and local (or an approved small fetch); rerun whenever an input changes |
  | `optional` | costs Claude usage, needs approval, or redraws a fixed-window analysis; rerun when wanted |
  | `one-off` | a backfill or setup that is finished |
  | `analysis` | exploratory; its output goes into a doc, not the site |
  | `automatic` | runs by itself (the Pages workflow on push) |

- **`steps[].duration`, `token_cost`, `cost_source`** are measured figures
  and where each was measured. `null` means nobody has measured it.
- **`pages[].reads`** are the stores a page imports or fetches.

The planner (`scripts/dataflow.py plan`, and the page's "What to rerun")
walks forward from the changed ids through `routine`, `optional` and
`automatic` steps, orders them by their place in the flow, and lists the
tracked stores they write.

`scripts/dataflow.py check` (run by `tests.test_dataflow`) fails when:

- an id is unknown or duplicated, or the graph has a loop;
- a step's code file or a page doesn't exist;
- a committed file under `summaries/`, `data/public/` or `config/` belongs
  to no store;
- a page script imports a data file that no page's `reads` covers;
- a page exists that the inventory doesn't list.

It can't check purposes, sizes or costs.

## 2. Today's architecture

Data moves through five layers. The first three are in `data/private/`
(gitignored), the fourth is committed, the fifth is built.

1. **Fetched** (`raw`): `raw.sqlite`, `notedb/`, `git/`, `bugs/raw/`,
   `chrome_releases/raw/`, and the committed `data/public/radar/raw/`.
   About 47 GB, plus the 69 GB shared Chromium clone that cosh only reads.
2. **Labels**: `labels.sqlite`, `sentiment.sqlite`, `ai_predict/scores.sqlite`.
   Under 100 MB, and the only stores that cost money to remake.
3. **Derived**: `derived.sqlite` is the hub that nearly everything reads.
   The balance stage files build on it and on git, and the sentiment
   comment files are rendered from it.
4. **Published**: `summaries/*`, `data/public/radar_browser_share.csv`,
   `config/org_browsers.csv` and `web/public/review-feedback/` (all
   committed; the last since 2026-11-12).
5. **Site**: `web/dist/`, built locally or by the Pages workflow from the
   committed files.

A new week of Gerrit data today needs, in order: `backfill --weeks 1`,
`extract-open`, a full `derive`, `classify --week`, `summarize`, then a
commit. That path is five commands and well defined. Everything past it
(balance, sentiment, feedback) adds about 20 more steps, several of them
manual.

## 3. What makes it hard to manage

Each item names the evidence. Items marked *(reviewer)* were found by the
code review and spot-checked in the code; the rest I measured directly.

### 3.1 One published file, a dozen writers, and hand copying

`summaries/balance.json` is written by `balance_report.py` (whose output is
a scratch `report.json`, with sections then copied in by hand), by eleven
dataset scripts, by `balance_page_extras.py` and by `review_roi_report.py`.
Each reads the file, replaces its own keys and writes it back. Nothing
records the order, and nothing rebuilds the file from empty.
`summaries/balance_dirs.json` is copied by hand entirely.

Consequences: the file can't be regenerated with confidence, a script that
is forgotten leaves stale datasets with no sign of it, and two scripts
still disagree on a definition (`balance_growth.py` and
`balance_analysis.py` use the old 50-file rule for mechanical CLs, the rest
use `mech.jsonl`) *(reviewer)*.

### 3.2 Inputs with no home and no command

Most balance and feedback scripts take `--first-commit F --owners-added O
--mech M --ai-marked A`.

- `mech.jsonl` is written only when the environment variable
  `BALANCE_MECH_OUT` is set (`scripts/balance_analysis.py:153`).
- `first_commit.txt`, `owners_added.txt` and the narrow `ai_marked.txt`
  have no script at all, only prose in `docs/balance.md`.
- Two of the four currently sit in `data/private/review_feedback_inputs/`.
  The other two have no fixed path.
- The review-ROI scripts write to another session's scratch directory,
  which they hard-code (`/home/rbagent/.claude/jobs/9e4a825c/tmp/…` in six
  scripts). Their results were copied to `data/private/review_roi/` by hand.

### 3.3 Date ranges are typed or hard-coded per command

- Balance scripts fix their window in constants (`LAST_Q = "2026Q3"` in
  `scripts/balance_report.py:28`, and likewise in `balance_growth.py` and
  `balance_signals.py`). New weeks can't reach the page without code edits.
- Five sentiment commands each take `--week 2025-W45:2026-W44` (or
  `--full-weeks`, `--praise-week`) by hand, and the ranges must agree.

So the planner can say *which* steps follow new data, but running them
unchanged republishes the same window.

### 3.4 Steps that never look at a CL twice

Three incremental steps mark a CL done by its number alone *(reviewer)*:

- `balance timeline` (`timeline_done`) ignores later NoteDb updates.
- `balance_signals.py votes` marks CLs with no NoteDb ref as done without
  reading them, so a ref that arrives later (as the 2017 backfill's did) is
  never read.
- `cosh patchsets` skips any CL in its fetched list, even if the CL gained
  patch sets since.

`extract-open` refreshes open CLs every run, so these three go quietly
stale for exactly the CLs that change most.

### 3.5 A plain rerun can exceed an approval

`cosh patchsets --go` selects every reviewed CL in `derived.sqlite`
(`cosh/patchsets.py:83-95`), with no week bound. Since the 2017 backfill,
that includes about 9 years of CLs whose patch sets are not approved. The
bound exists only in CLAUDE.md prose. `extract` has the same shape: the
approved range is in prose, not in the command.

### 3.6 Steps that fetch and rewrite config *(by design)*

`OrgResolver()` fetches the affiliations file and may rewrite
`config/affiliations.json5`. Eight call sites in seven files build one:
`summarize`, `sentiment_people`, `review_feedback.py`, two balance scripts
and two analysis scripts. So a summary step can change a config file as a side
effect, and docs that call these steps offline are wrong. In the inventory
this had to be modelled as "runs `update-affiliations` by itself".

This is now a decision, not an accident (`docs/plan.md`, 2026-11-12): the
fetch is cheap, many analyses depend on the file and some are slow, so none
should run on a stale copy. `COSH_AFFILIATIONS_OFFLINE=1` skips it. Rule 7
below is relaxed accordingly: the inventory should say which steps refresh
affiliations, and docs shouldn't call them offline.

### 3.7 Published data that isn't published *(done)*

`web/public/review-feedback/` was 302 MB in 7,000-odd files and gitignored,
so the live Feedback Index page found nobody. On 2026-11-12 its files were
slimmed to 126 MB (53 MB as git stores them), committed, and published; the
landing page links the page.

### 3.8 Three kinds of entry point

Steps on the path to a published file are spread over `python3 -m cosh
<cmd>` (core, radar, patchsets), `python3 -m cosh.<module>` (balance,
sentiment, bugs) and `python3 scripts/<name>.py` (feedback, votes, every
balance dataset, chrome releases). `scripts/` mixes these with one-off
analyses, and the only way to tell them apart is the inventory.

### 3.9 Smaller things

- **Leftovers.** `data/private/derived.prev.sqlite` (2.1 GB) and
  `derived.new.sqlite-*` are from the 2026-11-12 rebuild; no code reads
  them. `data/private/git/chromium-src.git` is the patch-set pilot,
  superseded by `chromium-patchsets.git`.
- **Scratch in the published tree.** `data/public/radar/adhoc/` (119 of
  the 162 tracked Radar files) is a one-off probe that nothing reads.
  `summaries/org_weekly.csv` is read by no page.
- **Two walks of the same logs.** `balance timeline` and
  `balance_signals.py votes` both read every CL's NoteDb event log. The
  votes pass took 5 h 14 min on 2026-11-12, before two fixes the same day
  (list `refs/meta/` once; refresh the NoteDb multi-pack index after a
  backfill, then a repack from 3,823 packs to 14) made a cold read about
  560 CLs/s, roughly 20 minutes for every CL.
- **One schema in five files.** Each `balance-*.sqlite` carries every
  stage's tables, mostly empty (`cosh/balance.py:114`).
- **Same file, two writers.** `cosh.sentiment collect` and
  `cosh.sentiment_people collect` write the same `comments-<week>.jsonl`,
  with and without identities. Whichever ran last wins, and `praise` fails
  if it was the wrong one *(reviewer)*.
- **Uncached model calls.** The identifying-detail screening inside
  `sentiment samples` and `sentiment_recent` is cached in memory only, so
  each rerun pays again *(reviewer)*.
- **Duplicated constants.** The browsers left out of the usage denominator
  are in `config/browsers.csv` and again in `web/src/data.ts`
  (`RATIO_EXCLUDED_BROWSERS`). The classifier prompt has an older copy in
  `scripts/comment_classifier.py`.
- **A wrong estimate.** `classify --dry-run` assumes 230 tokens per thread
  (`cosh/classify.py:320`); production runs measured 300 to 360.
- **A growing refresh.** `extract-open` starts from the oldest fetched
  week, now 2017-W27, so each refresh lists about 490 weekly windows.
- **No updater for the shared clone.** `cosh commits` reads
  `~/projects/shared/chromium`, but nothing in cosh fetches it, so a new
  week has no commits until someone does.
- **Stale docs.** Sizes, durations and schemas are repeated across
  `docs/*.md` and CLAUDE.md and several disagree with the code (the three
  durations for `cosh commits`, the pack count in `docs/balance.md`, the
  file list in `docs/storage-design.md` §3.1).

## 4. The architecture to aim for

Seven rules. The Gerrit core already follows all of them.

1. **Every store has exactly one writer step**, and that step can rebuild
   it from its inputs alone. No read-modify-write of shared files, and no
   hand copying. A published file is written whole by one command.
2. **Every step on the way to a published file is a `cosh` command.**
   `scripts/` holds only analysis whose output goes into a doc. The
   inventory's `refresh` then matches the directory: anything in
   `scripts/` is `analysis`.
3. **Every store lives at a fixed path under its tier.** Inputs that
   scripts share are stores with a writer, not arguments pointing at
   wherever the file happens to be. Proposed layout, applied to new stores
   first and to old ones only when convenient:

   | Path | Holds |
   |---|---|
   | `data/private/raw.sqlite`, `notedb/`, `git/`, `bugs/`, `chrome_releases/` | fetched (as today) |
   | `data/private/labels.sqlite`, `sentiment.sqlite`, `ai_predict/` | labels (as today) |
   | `data/private/derived.sqlite`, `balance/*.sqlite`, `sentiment/` | derived |
   | `data/private/scratch/<topic>/` | analysis output, safe to delete |
   | `data/private/logs/` | run logs and PID files (60-odd loose files today) |
   | `summaries/` | every published data file |

4. **Date ranges come from the data.** A step's default range is "every
   complete week (or month) its inputs have", read from `derived.sqlite`'s
   `meta` or the labels' coverage. A fixed window is an explicit argument
   that the publishing command records in the file it writes.
5. **Incremental steps key on content, not on the CL number.** A done
   marker stores what it saw (the NoteDb tip, the patch-set count), and the
   step redoes a CL whose marker no longer matches.
6. **Approvals are data that commands enforce.** A small committed file
   (say `config/approved.json`) gives each fetcher its approved range, and
   the fetcher refuses anything outside it without an explicit override.
   CLAUDE.md keeps the reasons; the bound itself stops being prose.
7. **A step is offline unless the inventory says it fetches.** The one
   deliberate exception is the affiliations refresh that every
   `OrgResolver()` does (3.6); the inventory marks those steps.

On top of these, one command ties the flow together:

```
python3 -m cosh update [--from ID ...] [--dry-run] [--with-optional]
```

It reads `config/dataflow.json`, runs the `routine` steps downstream of
what changed in order, stops at the first failure, and prints the
`optional` steps it skipped with their measured cost and the files to
commit. It is `scripts/dataflow.py plan` plus execution, so it stays small.
It only becomes possible once rules 1 to 4 hold, because today several
steps can't be run without hand edits.

What stays as it is:

- **SQLite files and bare git repos, standard library only.** Nothing here
  needs a workflow engine, a build system or a new store.
- **`derived.sqlite` as the hub**, rebuilt whole. It is the simplest part of
  the system, and at under an hour it doesn't need to be incremental yet.
- **Separate balance stage files.** They let the slow stages run in
  parallel and be rebuilt alone. Only their schemas and location change.
- **Keeping everything fetched, losslessly** (`docs/storage-design.md` §3.8).

## 5. What needs to change

In order. Each step leaves the system working, and the inventory is
updated with it. Sizes: S is under an hour, M a few hours, L a day or more.

### First: decisions only you can make

| # | Decision | Why it's yours |
|---|---|---|
| D1 | Delete `data/private/derived.prev.sqlite` and `derived.new.sqlite-*` (2.1 GB)? | Deleting data. No code reads them and `derived.sqlite` is rebuildable. |
| D2 | *(done 2026-11-12)* How should the Feedback Index files be published? | Decided: slimmed to 126 MB and committed to `main`; finished half-years don't change between runs, so git stores them once. |
| D3 | Should Review Balance and Review Tone follow new weeks, or stay fixed-window analyses? | It decides whether their steps become `routine` (and need rule 4) or stay `optional` snapshots that are rerun deliberately. |
| D5 | *(done)* Delete `data/private/notedb/repack-20261112/old-packs` (12 GB)? | Deleted by the user on 2026-11-12. |
| D4 | Retire the pilot repo `data/private/git/chromium-src.git`? | CLAUDE.md says never delete it. Only exploratory balance scripts read it. |

### Then: quick fixes that remove real risk

| # | Change | Size | Rule |
|---|---|---|---|
| 1 | *(done)* Give `cosh patchsets` `--since`/`--until`, defaulting to the approved 2023-W26 .. 2026-W44, so a plain rerun can't fetch unapproved CLs | S | 6 |
| 2 | *(dropped)* Make `OrgResolver()` read the committed file; fetch only in `update-affiliations` | — | the user chose the refresh (3.6) |
| 3 | *(done)* Fix the `classify --dry-run` estimate (use the last runs' measured tokens per thread from `labels.sqlite`'s `runs`) | S | — |
| 4 | *(done in part)* Drop `summaries/org_weekly.csv` (done). Moving `data/public/radar/adhoc/` was dropped: it is 0.9 MB of fetched Radar responses that must be kept anyway, and moving it changes nothing else | S | 3 |
| 5 | *(dropped)* Read `RATIO_EXCLUDED_BROWSERS` from `config/browsers.csv` (emit it in the Radar CSV or a small JSON) | S | 1 |
| 6 | *(done, differently)* Bound `extract-open` to a recent window by default (say 2 years), with `--since` for a full relist | S | — |

### Then: the balance pipeline, where most of the hand work is

| # | Change | Size | Rule |
|---|---|---|---|
| 7 | Add `cosh.balance inputs`: writes the first-commit, OWNERS-added, AI-marked and mechanical lists as tables in `balance.sqlite` (or fixed files beside it). Scripts read them from there; the `--first-commit … --mech …` arguments go | M | 3 |
| 8 | Fold the votes walk into `balance timeline` (one pass over NoteDb instead of two) and key `timeline_done` on the ref's tip | M | 1, 5 |
| 9 | Add `cosh.balance publish`: imports each dataset script's compute function, builds `balance.json`, `balance_dirs.json` and `balance_authors.json` from empty, and writes each once. The scripts keep their `main()` for exploration but no longer write into `summaries/` | L | 1, 2 |
| 10 | Take the window from the data in `publish` (pending D3), and use one rule for mechanical CLs everywhere | M | 4 |
| 11 | Give each stage file only its own tables, and move them to `data/private/balance/` | S | 3 |

Step 9 is the largest change in this plan and the one that pays most: it
turns about 15 commands and two hand copies into one, and makes the page's
data reproducible. A golden-file test (the new command must reproduce
today's `balance.json` key for key) makes it safe to do in pieces.

### Then: sentiment and feedback

| # | Change | Size | Rule |
|---|---|---|---|
| 12 | *(done)* One `collect` that always writes identities; steps that must not see them read a view without | S | 1 |
| 13 | `cosh.sentiment publish --weeks …`: one command and one range for the trend, praise, samples, recent and people files (default range pending D3) | M | 1, 4 |
| 14 | Cache screening verdicts in `sentiment.sqlite`, keyed by comment and prompt hash | S | — |
| 15 | Move `review_feedback.py` to `cosh/feedback.py` (`python3 -m cosh.feedback`); it writes the committed `web/public/review-feedback/` (D2) | M | 2 |
| 16 | Give the review-ROI scripts a `--out` under `data/private/scratch/review_roi/` instead of the hard-coded session path | S | 3 |

### Last: the update command and tidying

| # | Change | Size | Rule |
|---|---|---|---|
| 17 | `python3 -m cosh update`, as in section 4 | M | — |
| 18 | `config/approved.json` read by `extract`, `backfill`, `patchsets` and `bugs` | M | 6 |
| 19 | Move run logs and PID files to `data/private/logs/` | S | 3 |
| 20 | Key the patch-set fetch on patch-set count | S | 5 |
| 21 | In `docs/*.md`, replace repeated sizes, durations and schemas with a pointer to the inventory, and fix the stale passages listed in 3.9 | M | — |
| 22 | Decide who updates the shared Chromium clone and add that step to the inventory (it belongs to argus-config, not cosh) | S | — |

### What this buys

After steps 1 to 17, a new week of data is:

```
python3 -m cosh update --from gerrit-rest gerrit-notedb    # routine steps, in order
python3 -m cosh classify --week <week>                     # optional, about $0.22
python3 -m cosh.sentiment score --week <week>              # optional, about $1.25
python3 -m cosh update --from data/private/labels.sqlite data/private/sentiment.sqlite
git add summaries config && git commit
```

The inventory shrinks too: about 30 steps instead of 42, with every
published file having one writer, and `scripts/` holding only analysis.

## 6. Progress

What has changed since the review, newest last. The inventory has the
details; this is the log.

- **2026-11-12, Feedback Index published (D2).** Its files are committed
  and served by GitHub Pages (3.7).
- **2026-11-12, affiliations refresh kept (3.6).** The user chose to have
  every `OrgResolver()` refresh the file; item 2 is dropped.
- **2026-11-12, NoteDb reads fast again.** `votes` lists meta refs once,
  `backfill` refreshes the multi-pack index, and the NoteDb repo was
  repacked (3,823 packs to 14); the old packs are gone (D5).
- **2026-11-12, quick fixes 1, 3 and 12.** `cosh patchsets` selects only
  reviewed CLs closed (or last updated) since the approved 2023-06-26
  unless `--since` says otherwise; `classify --dry-run` estimates from the
  measured tokens per thread in `labels.sqlite` (317); `cosh.sentiment
  collect` always writes identities, so the comment files have one writer.
- **2026-11-12, item 6 without losing coverage.** Instead of a fixed
  window, `extract-open` lists only open CLs updated since the last
  complete snapshot (a day's margin), when the snapshots reach back to the
  oldest fetched week; derive already takes each CL's newest listing. A
  refresh drops from about 490 weekly windows to one or two.
- **2026-11-12, item 4 in part.** `summarize` no longer writes
  `summaries/org_weekly.csv`, a copy of `org_weekly.json` no page read.
  Items 4 (moving `radar/adhoc/`) and 5 (the browser list in `data.ts`)
  were dropped: neither removes a step or a store, and 5 would add a data
  file for the page to fetch.
