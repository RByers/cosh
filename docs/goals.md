# Goals of the analyses

This is what changes to any analysis in this repository are judged by:
Value Exchange, Review Tone, Review Balance, the Feedback Index and those
that follow. The project's overall goal and ground rules are in
`docs/plan.md`.

Each analysis has its own purpose: the question it answers and for whom.
That purpose is written down in the analysis's own doc
(`docs/extraction-v1.md` and `docs/comment-classifier.md` for Value
Exchange, `docs/sentiment.md` for Review Tone, `docs/balance.md` for
Review Balance, `docs/review-feedback.md` for the Feedback Index,
`docs/review-load.md` for Review Load), near
the top, and a new analysis states its purpose there before it gets a
page. The goals here are what every analysis shares.

The goals are in priority order. Goals 1 and 2 are what a page is for;
goals 3–6 are constraints on how we get there. A change that makes a page
noticeably more useful or accurate may cost some update time, published
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
  from the directory, its reviewers and their norms, the period
  (Chromium-wide shifts in how much feedback changes draw) or the stage of
  a career are not the person's, so a comparison is with similar work: in
  the Feedback Index, the same experience and the same reviewers (each
  reviewer's factor carries their directory's norms too, and predicts
  feedback better than the directory: `docs/review-feedback-reviewers.md`),
  and the same time where that measurably helps (it hasn't yet:
  `docs/review-feedback-drift.md`). What remains should be about the
  person.
- **No reward for gaming.** A person shouldn't be able to improve their
  figure by something other than better work, such as picking lenient
  reviewers; the Feedback Index compares each change with what its own
  reviewers' approvals draw for that reason.
- **Improvement over time is visible.** A person's figures for different
  periods must be comparable, so a better or worse half-year shows as one.
  In the Feedback Index, the addressed feedback rate (AFR) is absolute (it
  moves when all of Chromium does); the feedback index (FI) is relative to
  peers.
- **Reasonably accurate, not precise.** A figure about a person is a
  learning guide, not a ranking for performance review. It is good enough
  when it is reproducible from different samples of the person's own work,
  and when a high or low figure points at something real worth looking at
  (in the Feedback Index, comments worth reading). We judge that, lacking
  ground truth, by:
  - the peers' norm predicting peers: what a comparison expects of a CL
    should predict what other people's CLs actually drew, scored on every
    CL with its owner left out (in the Feedback Index, the Poisson
    deviance of each CL's addressed threads, with a factor per size
    bucket so that size doesn't swamp the rest). This is the test for how
    fine the peer groups should be (directories, periods, minimums);
  - split-half reliability: the rank correlation of each person's figure
    from their odd and from their even CLs (people with 25+ CLs);
  - early/late consistency: the same from the older and the newer half of
    their CLs. Both of these reward coarser comparisons, since where
    someone works is a stable part of their figure (comparing with no
    directories at all scores highest), so they can't choose the peer
    groups; they help with noise, such as how a figure is pooled;
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

## 4. A small GitHub repository; large data in R2, changed compatibly

GitHub keeps the code, the docs and small published data. Anything large,
or rewritten often, is published to the Cloudflare R2 bucket `cosh`
(`docs/r2.md`, the user's decision of 2026-11-14) and fetched by the
pages from `cosh-data.rbyers.ca`. Data on disk that isn't published
(`data/private/`) costs nothing here (goal 6).

- **Publish the minimum the pages need**, in git and in R2 alike. A
  published file holds only what a page reads, in the leanest form that
  keeps it reproducible (goal 2): no unused fields, no values a page can
  compute from others it already loads, nothing kept "in case". Whatever
  else is useful for analysis stays in uncommitted stores.
- **GitHub stays very small: ideally under 50 MB.** Git keeps every
  version of a committed file, so committed data is limited to small files
  that change little: summaries a page needs at once, global files such as
  `peers.json` (about 60 KB gzipped), configuration. Per-person,
  per-directory and other large file families go to R2. A weekly update
  should add almost nothing to git's history. (On 2026-11-14 the
  repository was 351 MB packed, history included, and its tree held
  224 MB, mostly `web/public/` and `summaries/`. The Feedback Index's and
  Review Load's per-person files moved to R2 on 2026-11-14 (`config/r2.json`,
  `docs/r2.md`); `summaries/` is still to do (`docs/plan.md`). Pushed
  history is never rewritten, so what is already in it stays.)
- **R2 data evolves compatibly.** The site (GitHub Pages) and the bucket
  update separately, and browsers may run an older build of a page, so
  new data in R2 must never break JavaScript that is already deployed:
  - *Add, don't change.* New data is something older pages ignore: new
    fields, or new weeks and periods outside the dates a page asks for
    (pages always filter by date, never take "everything in the file").
    Existing fields keep their names and meanings.
  - *A breaking change gets a new name*, such as a version prefix
    (`.../v2/...`) or a new file name, written alongside the old files.
    The old ones stay until no deployed page reads them (`cosh.r2
    publish` deletes them only then). Breaking changes
    are rare and batched, since each rewrites a whole family.
  - *Data before code.* A deploy uploads new R2 data first, then pushes
    the page that reads it; a page copes with an object that is missing (a person
    or period with no data yet) rather than failing.
- **Incremental updates are fast and cheap.** Files in R2 are laid out so
  that a week of new data changes few of them: split by period
  (half-years in the Feedback Index) so finished periods are written once
  and never again, and keyed so that only the people, directories or
  periods touched that week change. `cosh.r2 sync` uploads only changed
  files (about 2,000 thread files a week), well inside
  R2's free tier. A format that rewrites every object each week, or a
  step that has to regenerate a whole family to add a week, fails this
  goal.

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
