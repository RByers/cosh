# The return on code review: design and findings

Status: built (2026-11-09). The design is below, then the findings, which
are on the balance page as the `#roi` section ("What review buys"). Nothing here fetches anything: every input is already on disk
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
| `balance-timeline.sqlite` `votes` | every Code-Review vote with voter, value, time, patch set: who approved (+2) and when |
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

| # | Package | Scripts | Findings |
|---|---|---|---|
| 0 | Shared inputs (first commits, OWNERS additions, mechanical list) | `scripts/balance_analysis.py mechanical` (with `BALANCE_MECH_OUT`), git log | regenerated 2026-11-09: 11,827 first commits, 36,450 OWNERS additions, 4,875 mechanical CLs (matches `balance.md` §8) |
| 1 | Per-CL table and Part 1 designs D1–D8 | `scripts/review_roi_table.py`, `scripts/review_roi_part1.py` | `review-roi-part1.md` |
| 2 | Part 2 panels (H2a–c) and the blame pilot (H2d–e) | `scripts/review_roi_part2.py`, `scripts/review_roi_blame.py` | `review-roi-part2.md` |
| 3 | Revert study | `scripts/review_roi_reverts.py` | `review-roi-reverts.md` |
| 3b | Substance pilot: what addressed review threads change (H2f, 200 threads through the sandbox) | `scripts/review_roi_substance.py` | `review-roi-substance.md` |
| 4 | Page section and `summaries/balance.json` datasets | `scripts/review_roi_report.py`, `web/balance.html`, `web/src/balance.ts` | the `#roi` section |

## Findings (2026-11-09)

Everything below ran on data already on disk; nothing was fetched. The
unit is 356,546 merged, human-owned, non-mechanical CLs landed on `main`
2023-07-01 .. 2026-09-30 (reverts, relands and Rubber-Stamper approvals
excluded). 2.67% of them were reverted within 30 days.

### The short version

1. **Reverts cannot show the value of review.** Every measure of how much
   review a CL got goes with *more* reverts, raw and after normalizing for
   size, directory, author practice and era (threads: odds ratio 1.75 raw,
   1.39 normalized). Normalization removes a third to a half of the
   association and never flips its sign: reviewers spend more on the CLs
   that look risky, and the controls cannot see all of that risk. The one
   exposure with a protective sign, the approver's habitual thoroughness
   measured on their *other* CLs, is worth at most 1.4 fewer reverts per
   1,000 CLs (CI 0.4–2.4, about 5% of reverts), and it "prevents" reverts
   for flaky tests and unrelated breakage just as much as reverts for real
   bugs, which marks it as confounding rather than prevention. The
   within-author comparison is null. The one quasi-experiment, the
   approver's weekly load as an instrument, is null but imprecise:
   −3.8 reverts per 1,000 CLs for a quartile-to-quartile more thorough
   approver, CI −11.6 to +4.1, so a protective effect of up to a third of
   reverts cannot be excluded either.
2. **That is partly because reverts measure CI, not review.** 64% of
   reverts come within 24 hours of landing, and about 52% are for a test
   or compile failure. Only about 16% name a crash, functional bug or
   performance regression, the kind of thing review is for; 11% are for
   reasons review could never prevent. A revert-plus-reland cycle costs a
   median 6 reviewer attention hours (mean 53, long tail), and 31% of
   reverted CLs are relanded.
3. **No long-term signal either.** Within a directory, deeper review in one
   half-year does not predict fewer reverts in the next (−0.07 points per
   SD, CI −0.24 to +0.09) and goes with slightly *more* review cost later,
   not less. Newcomers who drew more addressed feedback in year one still
   drew more in year two and were reverted more: selection, not learning.
   In the blame pilots, CLs whose lines a later bug fix rewrote had
   slightly *more* review than matched CLs, and lines from well-reviewed
   CLs survive a year no better than lines from rubber-stamped ones (58%
   survive either way; the 300-CL pilot cannot rule out a 5-point gap).
4. **What review demonstrably does is change the code before it lands,
   and some of that is breakage caught.** 65% of unit CLs got at least
   one reviewer thread and 39% got one the author acted on. In a 200-thread
   pilot, 7% of addressed threads fixed a correctness problem and 4.5%
   fixed something that would plausibly have broken (CI 2.4–8.3%): about
   6% of all CLs, roughly twice the 2.67% that get reverted. Most addressed
   threads are about clarity (docs 29%, style 23%, design 19%, tests 11%),
   whose return, if any, is the long-term kind that Part 2 could not
   detect. That direct count, not avoided reverts, is the measurable
   return, and a 2,000-thread sample would make it precise for a few
   minutes of model time.

### Part 1 in more detail (`review-roi-part1.md`)

| Exposure (30-day revert odds) | Raw OR | Normalized OR (size × dir2 × author practice × half-year) |
|---|---:|---:|
| reviewer-started threads | 1.75 | 1.39 (1.32–1.46) |
| reviewer attention hours | 1.47 | 1.26 (1.20–1.32) |
| addressed threads | 1.66 | 1.33 (1.27–1.40) |
| rubber stamp (approved with no thread; 35% of CLs) | 0.65 | 0.76 (0.71–0.81) |
| first approver's habitual thoroughness, p25 → p75 (D4, logistic, all controls) | | 0.959 per SD; −1.4 reverts per 1,000 (−2.4 to −0.4) |
| approver expertise: prior approvals or commits in the directory, OWNERS, tenure | | flat or slightly above 1 |
| negative control: the habit against reverts review cannot prevent | | 0.952 (as protective as against real bugs, 0.970) |

- The habit measure is a real trait (split-half reliability 0.75–0.87),
  and the result holds with approver clustering and on the votes-only
  subset. It is concentrated in authors under two years' tenure and in
  2025, and fades in 2026.
- Within author × dir3 × half-year × size (4,495 matched sets): the
  habit's conditional OR is 0.97 (0.92–1.02).
- Rubber stamp → one addressed thread: MH OR 1.24 (1.10–1.37), the most
  confounded comparison of all (a CL draws a comment *because* something
  looks off).
- The 22% of CLs with no Gerrit votes on disk are genuine zero-comment
  CLs (Gerrit's own comment count is 0 for 2,997 of a 3,000 sample), so
  counting them as rubber stamps is right.
- Upper bound: taking the most favourable 95% bound of the best design, a
  quartile-to-quartile more thorough approver avoids at most 2.4 reverts
  per 1,000 CLs (9% of reverts), worth roughly 130 attention hours per
  1,000 CLs at the revert study's mean cost, for about 1,300 extra threads.
  The negative control says the true causal share is probably smaller.

### Part 2 in more detail (`review-roi-part2.md`)

| Hypothesis | Test | Result |
|---|---|---|
| H2a past depth → fewer reverts next period | 949 dir3 × half-year pairs, directory fixed effects | −0.07 points per SD (−0.24, +0.09); one-year lags show two negative estimates, but the backwards placebo is as large |
| H2b past depth → cheaper review later | same panel | rounds +0.03 (+0.01, +0.06), attention +2.7 h (+0.6, +4.7): more, not less |
| H2c early addressed feedback → less later, fewer reverts | 404 newcomers, year 1 → year 2 | year-2 feedback +0.36 log2 per doubling; reverts OR 1.32 (1.11–1.58): selection |
| H2d thin review → later bug fixes rewrite its lines | SZZ-style blame, 500 fix commits → 418 induced unit CLs | induced CLs had *more* review: feedback index +0.15 (+0.01, +0.29) |
| H2e thin review → lines survive less | blame at +1 year, 300 CLs | top vs bottom tercile −1.0 point (−11.5, +9.4) |

Full blame runs are CPU only (no download): about 16 CPU hours for every
eligible fix commit since 2024 (8,317), and 10–16 CPU hours for a
3,000–5,000-CL survival sample. Neither is likely to change the picture;
they would tighten the bounds.

### Revert study in more detail (`review-roi-reverts.md`)

14,286 reverted commits from 2023-07-01, a flat 34–38 per 1,000 non-bot
commits a year. Reasons by regex (21% unknown): test failure 39.6%, crash
or functional bug 14.0%, compile or link 12.2%, flaky or unrelated 7.0%,
dependent or requested 4.0%, perf or size 2.0%. A third party reverts
62.8%, the author 23.0%, a bot 9.6%, an approver 4.7%. Median time to
revert 11.5 hours; 91% of 30-day reverts happen within 7 days. Reverted
CLs had *more* review than same-size, same-directory CLs that stayed
(+0.3 threads, +18 reviewer attention hours).

### Substance pilot (`review-roi-substance.md`)

200 random addressed threads (unit CLs landed 2025-07 .. 2026-09, which
have 245,335 addressed threads in all), labelled by Haiku through the
sandbox, 274 tokens and 0.4 s per thread; 90% agreement with 40 blind hand
labels (κ 0.87, would-break 40/40). Shares with 95% Wilson intervals:

| What the reviewer's point changed | Share of addressed threads |
|---|---:|
| docs, comments, commit message, naming for clarity | 29.0% (23–36) |
| style, formatting, nits | 23.0% (18–29) |
| design, structure, API | 18.5% (14–25) |
| tests | 11.0% (7–16) |
| **correctness: a bug, crash, race, leak, wrong logic** | **7.0% (4–11)** |
| process (bug links, flags, metrics) | 6.5% (4–11) |
| other | 5.0% (3–9) |
| of which **would plausibly have broken** (test failure, crash, user-visible bug) | **4.5% (2.4–8.3)** |

- Review changed something in 38% of unit CLs. Assuming threads within a
  CL are independent, about 8% of all unit CLs got a correctness fix in
  review and about 6% a fix for something that would plausibly have
  broken, against 2.67% of CLs reverted within 30 days. That is the one
  place the data show review preventing breakage directly: roughly twice
  as many would-break problems are fixed in review as escape to a revert.
  The interval is wide (9 of 200 threads), and "would plausibly break" is
  a model judgment on the thread text, not an observed failure.
- Correctness is a smaller share than the 18% of the 50-thread hand sample
  in `review-impact.md` §5; free-text replies carry more of it (10.4%)
  than Done-button replies (5.9%).
- **Near misses:** of 60 CLs reverted for a crash or functional bug, a
  reviewer had raised the very problem fully in 11.7% and partly in 23.3%
  of them (14 of the 60 had no reviewer thread at all). Review saw about a
  third of these failures coming and did not stop them; in 9 of those 21
  CLs the author changed something in response and the CL was still
  reverted.
- **Cost to scale (needs the user's go-ahead):** a 2,000-thread random
  sample, enough for ±2-point shares and about 90 would-break threads,
  is about 0.55M Haiku tokens, 3–4 minutes at 4 calls at once ($0.17
  reported by the CLI; about $1.40 at list price). Every addressed thread
  since 2025-07 (245k) is about 67M tokens and 7 hours; since 2023-07
  (622k) about 170M tokens and 17 hours. The sample is enough for the
  page; the full passes would only be needed for per-directory or
  per-reviewer breakdowns.

### Part 1 follow-up: an exogenous source of review depth

(`review-roi-part1.md`, "Follow-up"; `scripts/review_roi_part1_followup.py`)

- **Reverts review could plausibly prevent** (crash, functional bug, perf
  or size regression: 1,527 reverts, 4.3 per 1,000 CLs) against CI
  breakage (compile and test failures: 15.5 per 1,000): the picture is the
  same. Threads go with more of both (OR 1.25 and 1.23 per doubling); the
  approver's habit is slightly more protective in relative terms on the
  preventable class (OR 0.947 per SD, CI 0.890–1.008, about −0.3 reverts
  per 1,000) but no more than on the unrelated reverts of the negative
  control.
- **The first approver's weekly load as an instrument.** How many CLs an
  approver approved that week, relative to their own median week, does
  lower the review this CL gets (first stage F = 397; the rubber-stamp
  rate rises 1.5 points per doubling) and does not predict unrelated
  reverts (+0.09 per 1,000, CI −0.15 to +0.32), so it is a credible
  instrument. Reduced form on all 30-day reverts: +0.41 per 1,000 per
  doubling of load (CI −0.44 to +1.25). Implied effect of review depth:
  **−3.8 reverts per 1,000 CLs for the 25th-to-75th-percentile
  thoroughness gap, CI −11.6 to +4.1.** The honest reading: the only
  quasi-experimental estimate we have is null but imprecise. It excludes
  neither zero nor a protective effect of about 10 per 1,000 (a third of
  all reverts), several times the habit estimate. A second instrument
  (threads the approver wrote on other CLs that week) fails the exclusion
  restriction (it "predicts" unrelated reverts too) and was discarded.
- **Glance approvals** (approved under 15 minutes after sending, no
  thread) are 0.5% of CLs with votes and revert at 2.75%, against 2.07%
  for slower rubber stamps (OR 1.27, CI 0.91–1.77): the direction fits
  "some look matters" but it is not significant.
- **Rubber stamps on CLs with votes on disk only** (16% of them): OR 0.79
  stratified, 0.81 with all controls, the same as on all CLs.

### What would move the needle

- A randomized or quasi-random assignment of review depth. The closest
  thing in the data is the approver's weekly load (see the follow-up).
- Counting what review catches directly (the substance pilot, scaled to a
  2,000-thread sample) rather than inferring it from what escapes.
- Outcomes slower than reverts at scale: the fix-inducing links (16 CPU
  hours) and a survival sample (10–16 CPU hours).

### What the page says

The `#roi` section of `web/balance.html` shows: the revert landscape (what
reverts are for, how fast); revert rate by review depth, raw and
normalized, with the honest reading that the slope never flips; the
odds-ratio table above as a dot-and-interval chart including the negative
control; the long-term panel estimates; and what review changes (the
substance pilot's shares, marked as a pilot).
