# Goals of the Feedback Index

This is what changes to the Feedback Index (`web/feedback-index.html`,
`docs/review-feedback.md`) are judged by. The project's overall goal is in
`docs/plan.md`; goals 2–5 here hold for the whole repository too, since
every dashboard shares the weekly update, the git history, the token
budget and the data flow.

The goals are in priority order. Goal 1 is what the page is for; goals 2–5
are constraints on how we get there. A change that makes the index
noticeably more accurate may cost some update time, repository volume or
tokens, but each of those has a ceiling, and staying within them is part
of the job.

## 1. Foremost: a reasonably accurate benchmark of one's engineering work

People should be able to look up their own address and get a fair sense of
the quality of their engineering work against their peers', and track how
it changes as they improve.

- **Their own work, not where or when they worked.** Differences that come
  from the directory (its reviewers and norms), the period (Chromium-wide
  shifts in how much feedback changes draw) or the stage of a career are
  not the person's, so the index compares each change with peers doing
  similar work: the same directory, experience and time. What remains
  should be about the person.
- **Improvement over time is visible.** A person's figures for different
  periods must be comparable, so a better or worse half-year shows as one.
  The addressed feedback rate (AFR) is absolute (it moves when all of
  Chromium does); the feedback index (FI) is relative to the peers of the
  time.
- **Reasonably accurate, not precise.** The page is a learning guide, not
  a ranking for performance review. It is good enough when a person's
  index is reproducible from different samples of their own work, and when
  a high or low figure points at real comments worth reading. We judge
  that, lacking ground truth, by:
  - split-half reliability: the rank correlation of each person's index
    from their odd and from their even CLs (people with 25+ CLs);
  - early/late consistency: the same from the older and the newer half of
    their CLs, which a bias that changes over time lowers;
  - robustness: a few threads in a quiet directory shouldn't swing the
    index, and no person's own changes should set the norm they are
    compared with;
  - a figure a reader can check: the page shows what each comparison is
    made of (the directory table, everyone's AFR per experience bin).
- **Fair to kinds of work.** A measure shouldn't penalise work that draws
  little review for good reasons (deletions, configuration, imported
  code) or reward work for drawing none.
- **Reproducible.** The page computes a person's figures from the
  published files, and they match the script's.

## 2. An efficient weekly update

Adding a new week of Gerrit data and refreshing the page should be routine:

- Only the new week is fetched and labelled; every local step is
  incremental or takes minutes (`review-feedback` took 2 min and 3 GB on
  2026-11-14), and `python3 -m cosh update` runs them with no manual
  steps beyond the fetch and model calls it lists.
- **Past figures are stable.** A finished half-year's files don't change
  when a week is added, and a person's figures for past periods move
  little from week to week. Only the current period is provisional.
- Nothing needs a full rebuild of the raw stores or a re-run of model
  calls over past data.

## 3. Repository volume well under 1 GB, without history explosion

Everything the site reads is committed, so git keeps every version of it.
This goal is about committed files only: data on disk that isn't committed
(`data/private/`) costs nothing here (goal 5).

- **Publish the minimum the pages need.** A committed file holds only what
  a page reads, in the leanest form that keeps it reproducible (goal 1):
  no unused fields, no values a page can compute from others it already
  loads, nothing kept "in case". Whatever else is useful for analysis
  stays in uncommitted stores.

- **The whole repository stays well under 1 GB** packed, history included
  (338 MB on 2026-11-14, of which the Feedback Index's history is about
  196 MB after a few days of format changes).
- **A weekly update adds little:** the Feedback Index aims for well under
  2 MB of packed growth per week (under 100 MB a year), mostly the
  current half-year's files of the people active that week.
- **Finished periods are frozen.** Per-person data is split by half-year
  so that git stores a finished half-year once. Global files the page
  reads (`peers.json`) are rewritten each week, so they stay small (about
  60 KB gzipped).
- **Format changes that rewrite every file are rare and batched**: each
  rewrites about 35–50 MB of compressed data. Prefer changes that touch
  the small global files over changes to the per-person files.

## 4. Moderately low token costs for each weekly update

- The weekly loop's model calls are the addressed labels (`cosh classify`,
  about 1M Haiku tokens a week, $0.22 API-equivalent) and the tone scores
  the comment links show. Anything added to the weekly loop should keep it
  within a few million Haiku-class tokens a week, run on the Max plan.
- Computing the index itself is offline: no model calls.
- Per-person model calls (`scripts/feedback_coach.py`, 115–150k Opus
  tokens a report) run on request, never for everyone each week.
- Labels and scores already paid for are kept (`addressed.sqlite`,
  `sentiment.sqlite`), so a change of method that can reuse them is
  preferred over one that needs them remade.

## 5. A clean data flow; intermediate data on disk is fine

- **Intermediate data on disk is fine, in any amount.** Uncommitted
  stores in `data/private/` (caches, derived databases, scratch, run logs)
  cost nothing against the goals above, as long as the disk holds them.
  Keeping a large intermediate store is better than re-fetching, re-paying
  model calls or rebuilding slowly (and `CLAUDE.md` asks us to keep
  whatever we download).
- **What matters is a data flow that is easy to reason about and update.**
  `config/dataflow.json` (drawn by `web/dataflow.html`, explained in
  `docs/data-architecture.md`) should stay small and clear: few stores and
  steps, each with one evident purpose and a name that says who uses it,
  every flow tracing back to a source and ending in something a page
  reads. Prefer one well-named intermediate store that several steps read
  over each step deriving its own copy, and remove stores and steps that
  nothing reads any more.
- So an extra intermediate store is a good trade when it makes the
  published files smaller (goal 3), the weekly update faster (goal 2) or
  the flow simpler, and a poor one when it only adds another box to the
  graph.
