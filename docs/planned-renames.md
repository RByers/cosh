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

## Steps, scripts and other stores

These need no data moved (except the last row), so they are less
disruptive, but they still break open worktrees that import or run the old
names. Do them in the same idle window.

| Now | Rename to | Why |
|---|---|---|
| `cosh/feedback.py` (`python3 -m cosh.feedback`) | `cosh/review_feedback.py` | Its step, output (`web/public/review-feedback/`), doc and test are all `review-feedback`; "feedback" alone is easy to confuse with `scripts/feedback_coach.py` |
| step `affiliations` | `update-affiliations` | The box should name the command it runs (`cosh update-affiliations`), like the other steps |
| `scripts/review_roi_part1.py` | `scripts/review_roi_depth.py` | It tests whether deeper or more expert review lowers the revert rate; "part 1" says nothing. Rename `docs/review-roi-part1.md` to match |
| `scripts/review_roi_part1_followup.py` | `scripts/review_roi_depth_followup.py` | Follows the rename above |
| `scripts/review_roi_part2.py` | `scripts/review_roi_later_changes.py` | It tests whether review today makes later changes easier and safer. Rename `docs/review-roi-part2.md` to match |
| `scripts/balance_narrative.py` | `scripts/balance_review_load.py` | Named after the page restructure that added it; it computes who carries review, how orgs and tenure shape feedback, reviewer growth and AI-marked CLs for "Chromium Code Review Load Analysis" |
| `scripts/balance_page_extras.py` | fold into `balance_signals.py`, `balance_clusters.py` and `review_roi_reverts.py` | "Extras" holds three unrelated datasets (growth signals, activity patterns, security fixes); each belongs beside the script that makes its input. `balance_publish.STEPS` names the new homes |
| `data/private/sentiment/` | `data/private/comments/` | Comments rendered with their thread context; the Feedback Index reads them too, not just tone scoring (its box is labelled "Rendered comments" for now) |

Left alone: `derive`, `classify` and `summarize` read clearly once their
outputs are `reviews.sqlite`, `addressed.sqlite` and the Value Exchange
summaries, and their commands are in every doc and run log.
`ai_marked_broad.txt` is "broad" against the narrow Agent-Generated tag in
`commits.sqlite`, so it stays.

## When

- No extractor, `derive`, `classify`, `cosh.sentiment`, balance or patch-set
  run in progress (`ps -u rbagent -o pid,args | grep '[c]osh'`, and
  `flock -n data/private/extract.lock true`).
- No other session working in a cosh worktree, or each one warned: their
  branches must rebase onto the rename before running anything that opens
  these files.

## How

1. In one worktree commit, replace every reference to every old name in
   the tables (`git grep -n 'derived\.sqlite\|labels\.sqlite\|raw\.sqlite'`,
   and so on): code defaults (`cosh/`,
   `scripts/`), tests, `config/dataflow.json` (store ids and paths, step
   inputs and outputs, the `raw.sqlite + notedb/` name), docs, `CLAUDE.md`
   and the memory notes that name them. Keep function names such as
   `open_derived` unless they read wrong. Run `python3 scripts/dataflow.py
   check` and the unit tests.
2. Land it on `main` (fast-forward, as in `CLAUDE.md`).
3. Right after, in the main checkout, move the files (the three
   databases and `sentiment/`) with `mv` (never copy
   and delete: `labels.sqlite` and `raw.sqlite` can't be remade). Move any
   `-wal` / `-shm` files with them, or checkpoint first.
4. Check that `python3 -m cosh summarize` and `cosh update --dry-run` (or
   their equivalents) open the new names, then delete this file in a
   follow-up commit.
