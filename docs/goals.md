# Goals of the analyses

This is what changes to any analysis in this repository are judged by:
Value Exchange, Review Tone, Review Balance, the Feedback Index and those
that follow. The project's overall goal and ground rules are in
`docs/plan.md`.

Each analysis has its own purpose: the question it answers and for whom.
That purpose is written down in the analysis's own doc
(`docs/extraction-v1.md` and `docs/comment-classifier.md` for Value
Exchange, `docs/sentiment.md` for Review Tone, `docs/balance.md` for
Review Balance, `docs/review-feedback.md` for the Feedback Index), near
the top, and a new analysis states its purpose there before it gets a
page. The goals here are what every analysis shares.

The goals are in priority order. Goals 1 and 2 are what a page is for;
goals 3–6 are constraints on how we get there. A change that makes a page
noticeably more useful or accurate may cost some update time, repository
volume or tokens, but each of those has a ceiling, and staying within them
is part of the job.

## 1. Foremost: a clean and simple visualization for the analysis's purpose

Each page shows what its analysis is for, and little else. It should be
useful, constructive and fair, and honest and transparent without pointing
fingers.

- **Clean and simple.** A reader who knows Chromium gets the main point
  from the first screen, without reading the docs. A chart, table or
  control that doesn't serve the purpose is left out, however interesting
  the data behind it.
- **Useful.** The page answers a question someone has and can act on, with
  figures accurate enough to act on.
- **Constructive.** What the page shows should help people and the project
  do better: what works, where the effort goes, what to read or try next.
  We don't point fingers and we aren't critical of people, teams or
  organizations. Negative findings appear as aggregates or anonymously,
  never as a ranking or list of whom to blame (`docs/plan.md`, ground
  rule 5, is the strict form of this for review tone).
- **Fair.** Comparisons are between like and like. A difference that comes
  from the kind of work, the place or the time is not shown as a
  difference between people or organizations.
- **Honest and transparent.** Not pointing fingers doesn't mean hiding
  things. A page doesn't leave out or soften a finding because it is
  unwelcome, doesn't suggest more precision than the data has, and says
  what each figure is made of and where it falls short. The method is in
  the analysis's doc, the data flow is on `web/dataflow.html`, and the
  code and published data are in the repository for anyone to check.

## 2. Figures about an individual: accurate, comparable and checkable

Where a page gives specific information about one person (the Feedback
Index's lookup by address, a leaderboard entry), goal 1 holds in full, and
these rules on top of it. The Feedback Index is the main case: people
should be able to look up their own address, get a fair sense of the
quality of their engineering work against their peers', and track how it
changes as they improve.

- **Their own work, not where or when they worked.** Differences that come
  from the directory (its reviewers and norms), the period (Chromium-wide
  shifts in how much feedback changes draw) or the stage of a career are
  not the person's, so a comparison is with peers doing similar work: the
  same directory, experience and time. What remains should be about the
  person.
- **Improvement over time is visible.** A person's figures for different
  periods must be comparable, so a better or worse half-year shows as one.
  In the Feedback Index, the addressed feedback rate (AFR) is absolute (it
  moves when all of Chromium does); the feedback index (FI) is relative to
  the peers of the time.
- **Reasonably accurate, not precise.** A figure about a person is a
  learning guide, not a ranking for performance review. It is good enough
  when it is reproducible from different samples of the person's own work,
  and when a high or low figure points at something real worth looking at
  (in the Feedback Index, comments worth reading). We judge that, lacking
  ground truth, by:
  - split-half reliability: the rank correlation of each person's figure
    from their odd and from their even CLs (people with 25+ CLs);
  - early/late consistency: the same from the older and the newer half of
    their CLs, which a bias that changes over time lowers;
  - robustness: a few data points in a quiet corner (a few threads in a
    quiet directory) shouldn't swing the figure, and no person's own
    changes should set the norm they are compared with;
  - a figure a reader can check: the page shows what each comparison is
    made of (in the Feedback Index, the directory table and everyone's AFR
    per experience bin).
- **Fair to kinds of work.** A measure shouldn't penalise work that draws
  little review for good reasons (deletions, configuration, imported
  code) or reward work for drawing none.
- **Reproducible.** The page computes a person's figures from the
  published files, and they match the script's.
- **Constructive for the person.** The page names people for what went
  well. What is less flattering about someone is shown only to a reader
  who typed that person's address, never in a list or ranking that can be
  reached by clicking (`CLAUDE.md`, "Sentiment").

## 3. An efficient weekly update

Adding a new week of Gerrit data and refreshing every page should be
routine:

- Only the new week is fetched and labelled; every local step is
  incremental or takes minutes (`review-feedback` took 2 min and 3 GB on
  2026-11-14), and `python3 -m cosh update` runs them with no manual
  steps beyond the fetch and model calls it lists.
- **Past figures are stable.** Files of a finished period (a finished
  half-year of the Feedback Index) don't change when a week is added, and
  figures for past periods move little from week to week. Only the current
  period is provisional.
- Nothing needs a full rebuild of the raw stores or a re-run of model
  calls over past data.

## 4. Repository volume well under 1 GB, without history explosion

Everything the site reads is committed, so git keeps every version of it.
This goal is about committed files only: data on disk that isn't committed
(`data/private/`) costs nothing here (goal 6).

- **Publish the minimum the pages need.** A committed file holds only what
  a page reads, in the leanest form that keeps it reproducible (goal 2):
  no unused fields, no values a page can compute from others it already
  loads, nothing kept "in case". Whatever else is useful for analysis
  stays in uncommitted stores.
- **The whole repository stays well under 1 GB** packed, history included
  (338 MB on 2026-11-14, of which the Feedback Index's history is about
  196 MB after a few days of format changes).
- **A weekly update adds little.** Summaries per week or month grow by a
  few rows. Per-person data is the large part: the Feedback Index aims for
  well under 2 MB of packed growth per week (under 100 MB a year), mostly
  the current half-year's files of the people active that week.
- **Finished periods are frozen.** Per-person data is split by period
  (half-years in the Feedback Index) so that git stores a finished period
  once. Global files a page reads that are rewritten each week
  (`peers.json`) stay small (about 60 KB gzipped).
- **Format changes that rewrite every file are rare and batched**: in the
  Feedback Index each rewrites about 35–50 MB of compressed data. Prefer
  changes that touch the small global files over changes to the per-person
  files.

## 5. Moderately low token costs for each weekly update

- The weekly loop's model calls are the addressed labels (`cosh classify`,
  about 1M Haiku tokens a week, $0.22 API-equivalent) and the tone scores
  (`cosh.sentiment score`). Anything added to the weekly loop should keep
  it within a few million Haiku-class tokens a week, run on the Max plan.
- Everything after the labels and scores is offline: summaries, indexes
  and published files are computed with no model calls.
- Per-person model calls (`scripts/feedback_coach.py`, 115–150k Opus
  tokens a report) run on request, never for everyone each week.
- Labels and scores already paid for are kept (`addressed.sqlite`,
  `sentiment.sqlite`), so a change of method that can reuse them is
  preferred over one that needs them remade.

## 6. A clean data flow; intermediate data on disk is fine

`config/dataflow.json` is the inventory of the flow, `web/dataflow.html`
draws it, and `docs/data-architecture.md` has the rules in full
(section 2).

- **Clear steps per analysis.** Each analysis has its own short chain of
  steps from the shared stores to the files its page reads, and a reader
  of the graph can follow it without reading the code: each store and
  step has one evident purpose, every flow traces back to a source and
  ends in something a page reads.
- **Analyses share work.** When two analyses need the same thing (derived
  review facts, the git history, labels, scores), one step computes it
  into one store that both read. Prefer one well-named shared store over
  each analysis deriving its own copy.
- **Names always say what a thing does and who uses it.** A store or step
  is named after an analysis only while it feeds that page alone. When
  another analysis starts to read it, or what it holds or does changes, it
  is renamed in the same change, to what it holds: `comments-score`, not
  "tone-score", once the Feedback Index read its scores too;
  `feedback-comments` became `feedback-links` when it stopped publishing
  comment text. A name that no longer fits is a defect, even when the
  rename touches many files (data-architecture rule 4, which
  `scripts/dataflow.py check` enforces).
- **Intermediate data on disk is fine, in any amount.** Uncommitted
  stores in `data/private/` (caches, derived databases, scratch, run logs)
  cost nothing against the goals above, as long as the disk holds them.
  Keeping a large intermediate store is better than re-fetching, re-paying
  model calls or rebuilding slowly (and `CLAUDE.md` asks us to keep
  whatever we download).
- **The flow stays small.** Remove stores and steps that nothing reads any
  more. An extra intermediate store is a good trade when it makes the
  published files smaller (goal 4), the weekly update faster (goal 3) or
  the flow simpler, and a poor one when it only adds another box to the
  graph.
