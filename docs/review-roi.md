# The return on code review: design and findings

Status: design (2026-11-09). Findings are added below as the work packages
finish. Nothing here fetches anything: every input is already on disk
(`balance*.sqlite`, `derived.sqlite`, `labels.sqlite`, `bugs/bugs.sqlite`, the
shared Chromium clone and the patch-set repo). Any LLM pass or new download
is piloted on a small sample first and costed before it runs at scale.

## The question

Code review costs expert time. What does Chromium get for it? Review has
two purposes:

1. **Immediate risk:** catch what would break with this change.
2. **Future risk:** keep later changes easy to make and easy to verify as
   safe (clear code, tests, documented intent, shared knowledge).

Part 1 asks how much of (1) the data shows, using reverts as the outcome.
Part 2 looks for signals of (2), which is harder to measure, and says
honestly where there is none.

## Why this is hard

Reviewers spend more time on riskier changes. So in the raw data, more
review goes with *more* reverts, not fewer, and that tells us nothing about
what review prevents. Every design below is an attempt to compare like with
like: the same kind of change, in the same place, by the same kind of author,
with more or less review. Three ideas carry most of the weight:

- **Normalize for difficulty.** Size (10 buckets), directory (2–3 levels),
  the author's tenure and prior commits in that directory, and the
  half-year. The balance work's *feedback index* (threads ÷ the 2023–24
  mean for the CL's size and directory) is the starting point.
- **Use the reviewer's habit, not this CL's review.** How many threads a
  reviewer writes on *other* CLs (residualized for size and directory) is a
  stable trait (split-half r ≈ 0.9 in `review-impact.md`), and it does not
  depend on how risky *this* CL is. The same for expertise: the approver's
  prior commits and approvals in the CL's directory, and whether they were
  an OWNER of it at the time. If CLs that happen to land in front of a
  thorough or expert reviewer are reverted less, at equal size, place,
  author and era, that is evidence review prevents breakage.
- **Compare within author.** The same author, the same directory, the same
  half-year, similar size: does the more reviewed CL get reverted less?
  This removes author skill, which otherwise confounds everything.

A **negative control** checks the designs: reverts whose stated reason is
unrelated to the change (flaky tests, infrastructure, "unrelated failure")
cannot be prevented by review. If a design "shows" review preventing those
too, it is picking up confounding, not prevention.

## Data

| Source | What it gives |
|---|---|
| `balance.sqlite` `cl` | per CL (509,646; 403,235 merged; 2023-07 .. 2026-11): size, dirs, threads, addressed, comments, reviewers, rounds, rework, interdiff share, attention hours, first-review latency, `reverted_at`, `is_revert`, `is_reland`, owner |
| `balance.sqlite` `cl_dirs`, `cl_attention` | the landed commit's lines per 3-level directory; each non-owner's attention hours |
| `balance-votes.sqlite` `votes` | every Code-Review vote with voter, value, time, patch set: who approved (+2) and when |
| `balance-git.sqlite` `gcommits`, `gfiles` | 1.30M first-parent commits on `main` since 2017: author, `Reviewed-by`, `reverts_sha`, `is_reland`, `Bot-Commit`, per-file lines. Reviewer and author history per directory comes from here |
| `derived.sqlite` `threads`, `comments`, `accounts` | thread roots and their authors (who started each thread), `regex_addressed`; `labels.sqlite` for the Haiku labels |
| `~/projects/shared/chromium` | full `main` history with blobs: revert messages (reasons), blame, later fixes to a CL's lines |
| `bugs/bugs.sqlite` | 67k fetched bugs; `fixed_by` CLs, type, priority. "Introduced In" is a milestone, so it can't name a CL |

Shared inputs, regenerated from local git into the job's scratch directory
(`inputs/first_commit.txt`, `inputs/owners_added.txt`, `inputs/mech.jsonl`):
each person's first commit, every OWNERS addition with its path and time,
and the mechanical-CL list (≥ 100 files, or ≥ 10 files with repetition
≥ 0.8; `balance.md` §8).

## Part 1: review depth and the revert rate

**Unit.** Merged, human-owned, non-mechanical CLs with a landed first-parent
commit on `main`, closed 2023-Q3 .. 2026-Q3, landed at least 30 days before
the data ends. Reverts and relands are excluded as units (relands are
re-attempts of reverted work and have their own revert rate; they appear in
Part 1 only as a robustness check). `Bot-Commit` approvals (Rubber Stamper)
are excluded as units too.

**Outcome.** Reverted within 30 days: a later first-parent commit on `main`
says `This reverts commit <sha>`. Also within 7 days (mostly sheriff
reverts for CI breakage) against days 8–30, and within 90 days as a check.

**Exposures (review depth), per CL:**

- reviewer-started threads; addressed threads; comments and characters;
- the feedback index (threads ÷ 2023–24 norm for size × 2-level dir);
- rounds; rework uploads after first review; interdiff share (lines changed
  after the first review ÷ final lines);
- reviewer attention hours (sum over non-owner humans), hours sent → first
  substantive review, total time in review;
- distinct non-owner commenters; approvers (+2, non-owner, before landing);
- the rubber-stamp flag: approved with no reviewer thread at all.

**Exposures (reviewer expertise and habit), per CL, aggregated over its
approvers (max, and the first approver's):**

- prior commits the approver authored in the CL's main 3-level directory
  (and 2-level), and prior approvals they gave there, both before the CL;
- whether the approver had been added to an OWNERS file covering the CL's
  main directory (or a parent) before the CL;
- the approver's tenure (years since first commit);
- **habitual thoroughness:** the approver's mean residual threads (actual −
  expected for size × dir) over their *other* CLs in the same half-year,
  leave-one-out;
- **habitual outcome:** the approver's leave-one-out revert rate on other
  CLs, as a descriptive trait.

**Controls.** Size bucket (10, by lines), file count, 2-level directory
(3-level where data allow), author tenure band, author practice band (prior
commits in the CL's main dir), half-year, test-file share of the changed
files, weekday and hour (UTC) of landing.

**Designs.**

- D1. Descriptive: 30-day revert rate by decile of each depth measure, raw
  and after re-weighting to the pooled size × dir × practice mix.
- D2. Stratified odds ratios (Mantel–Haenszel) with strata size bucket ×
  dir2 × author practice band × half-year; exposure above vs below the
  stratum median (and by quintile). Confidence intervals by author-clustered
  bootstrap.
- D3. Logistic regression of 30-day revert on log depth with all controls,
  errors clustered by author (reuse `logit` and `cluster_cov` from
  `scripts/balance_feedback_predicts.py`; pure Python, so collapse rows to
  binned covariate cells if it is slow). Report effects as the difference
  in revert rate between the 25th and 75th percentile of depth, holding
  controls at their mix.
- D4. Reviewer-habit and expertise as the exposure (the main identification
  strategy): D3 with the leave-one-out habit and the expertise measures in
  place of this CL's own review. Check the habit's split-half reliability.
- D5. Within author × dir3 × half-year pairs, matched on size bucket: sign
  test and conditional logit on which of the pair was reverted.
- D6. At equal threads, does *addressed* review (something changed) go with
  fewer reverts than unaddressed review?
- D7. Heterogeneity: by base revert rate of the directory, by size, by
  author tenure, by era (2023–24 vs 2025 vs 2026), for 7-day vs 8–30-day
  reverts.
- D8. Negative control: the same models with "unrelated" reverts (flaky,
  infra, dependent CL) as the outcome, using the revert-reason classes of
  the revert study below.

**The cost side (so an ROI can be stated).** What a revert costs: the
share of reverted CLs that are relanded and when; the reland's review
threads, rounds and attention hours; the revert's own review; the sheriff's
time proxied by time-to-revert; follow-up bug fixes. Review cost per CL is
attention hours. The ROI statement is then "X extra reviewer hours per 1,000
CLs avoid Y reverts, each costing Z hours", with every piece's uncertainty.

## Part 2: does review today make tomorrow's changes easier and safer?

Hypotheses, each with an offline test and what would count as a signal.

- **H2a. Past review depth lowers future reverts in a directory.**
  Panel of dir3 × half-year: mean feedback index (and addressed threads per
  100 lines) in period t against the revert rate in t+1, with directory
  fixed effects and controls for the directory's own revert rate, volume
  and author mix in t. Signal: a negative within-directory coefficient
  that survives lagging two periods.
- **H2b. Past review makes later review cheaper.** The same panel with
  period-t+1 review cost as the outcome: threads per 100 lines, rounds,
  interdiff share, hours to first review, attention hours per CL. Caveat:
  the same reviewers persist in a directory, so their habit confounds this.
  Use reviewer turnover (directories whose main approvers changed) and
  within-directory changes over time.
- **H2c. Authors who received more addressed feedback early need less
  later and break less.** Author-level dose-response: addressed threads
  received in the first 12 months (per CL, relative to the norm) against
  the feedback index and the revert rate in months 13–24, controlling for
  first-year volume, tenure and directory mix. `balance.md` §4b–4c found
  practice beats time for the feedback index; this adds reverts and
  separates addressed from unaddressed feedback.
- **H2d. Review-caught defects vs field defects.** Lines a CL introduced
  that a later bug-fix commit (`Fixed:` footer, bug type Bug, not a revert)
  deletes or rewrites within 12 months, found with blame at the fix's
  parent (an SZZ-style link). Reverts catch 3% of CLs within days; this
  catches slower bugs. All local git, but blame is CPU-heavy: pilot on
  ~500 fix commits, time it, and estimate the full run before deciding.
- **H2e. Line survival.** Share of a CL's added lines still present (not
  modified) 12 months later, by review depth, at equal size, place and
  file type. Reviewed-away churn would show as higher survival. Same blame
  pilot.
- **H2f. What review leaves behind.** Threads that asked for tests or
  documentation (substance tags) and the later review cost and revert rate
  of the files they touched. Needs an LLM substance pass over thread roots;
  pilot 200 threads through `cosh.sandbox`, measure agreement with a hand
  label, and cost the full pass before running it.
- **H2g. Knowledge transfer.** Whether being reviewed by an expert in a
  directory predicts later reviewing or owning that directory. `balance.md`
  §4c found the feedback index adds little beyond volume; this version
  conditions on *who* reviewed.

## Revert study (cost side and negative control)

From the revert commits' messages on `main` (local git): reason classes by
regex (compile or link failure, test failure, flaky or unrelated failure,
perf or size regression, crash or functional bug, dependent CL reverted,
requested by author, unknown), time from landing to revert, who reverted
(author, sheriff, bot), reland rate and days to reland, and the review cost
of the reland and of the revert. If the regex leaves a large unknown share,
a pilot of 100 revert reasons through `cosh.sandbox` says whether a model
pass is worth its cost.

## Work packages

| # | Package | Scripts | Status |
|---|---|---|---|
| 0 | Shared inputs (first commits, OWNERS additions, mechanical list) | `scripts/balance_analysis.py mechanical`, git log | running |
| 1 | Per-CL table and Part 1 designs D1–D8 | `scripts/review_roi_table.py`, `scripts/review_roi_part1.py` | running |
| 2 | Part 2 panels (H2a–c) and the blame pilot (H2d–e) | `scripts/review_roi_part2.py`, `scripts/review_roi_blame.py` | running |
| 3 | Revert study | `scripts/review_roi_reverts.py` | running |
| 4 | Page section and `summaries/balance.json` datasets | `scripts/review_roi_report.py`, `web/balance.html`, `web/src/balance.ts` | after 1–3 |

## Findings

(added as packages finish)
