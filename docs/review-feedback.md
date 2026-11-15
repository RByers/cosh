# Feedback Index: addressed feedback rate (AFR) and index

**Purpose of the Feedback Index** (`web/feedback-index.html`). The page
answers: how much review feedback do Chromium changes get per 100 lines,
and how fast does it fall with experience? It is for individual
contributors: anyone can type an email address to see that person's
figures against their peers' and how they change over time, as a learning
guide, not a ranking.

What changes to it are judged by: `docs/goals.md` (goal 2 is about figures
for one person).

`web/feedback-index.html` shows how much review feedback Chromium changes
draw per 100 lines as their authors gain experience, and lets anyone type an
email address to see that person's AFR and index against their
peers'. It is
a learning guide, and the page says so at the top: "This analysis is imperfect
and is intended as a learning guide only". The landing page links to it
(since 2026-11-12), and it carries `noindex`.


Correcting for the reviewer (analysis, not built): `docs/review-feedback-reviewers.md`.
## Definitions

Both are fixed: the page has no switches for them (the user's call,
2026-11-14).

- **Addressed feedback rate (AFR):** addressed reviewer threads per 100 new or changed
  lines, pooled over a set of CLs (all their addressed threads × 100 / all
  their lines). Lines are the landed commit's insertions: a changed line
  counts once, and deleted lines don't count (since 2026-11-14; see "Why
  deletions don't count"). Moved files count by the lines changed between
  their names, not as new (`commits.moved_lines`). CLs that only delete
  lines, or only move files, are left out. Until 2026-11-14 a CL's lines
  were Gerrit's insertions, capped by the landed commit's where Gerrit
  missed a move (`move_free_ins`), and split over directories by the
  commit's; the commit's own count is 1.1% larger in all (96.1M lines
  against 95.1M; 3,794 CLs differ by more than 10%), and switching moved 33
  of 2,808 people with 25+ CLs by more than 10% (rank correlation 0.999).
  The CLs are merged,
  human-owned CLs on `main` that are neither mechanical nor part of a
  large-scale change (the same CLs as the Review Balance page's feedback
  index, `docs/balance.md` section 4; mechanical and LSC CLs from
  `commits.sqlite`, `docs/commits.md`), and only those with addressed labels
  (from `addr_start`, which is the start of the data since every week was
  labelled on 2026-11-13). **Reviewer threads** are threads not started by a
  bot, on a file or the commit message. Patch-set-level threads (general
  comments) aren't counted: Gerrit has recorded them as threads only since
  July 2020, they can't be tied to a directory, and only 5% are addressed.
  A thread is **addressed** by the regex or the Haiku label in
  `addressed.sqlite` (`docs/comment-classifier.md`).
- **Experience** is the owner's CLs landed on `main`, counting the CL itself
  (their earlier commits from the start of main's history in 2008, reverts
  left out, plus one), in power-of-two bins named by their top, so each bin
  is one doubling: 8 (8 or fewer), 16 (9–16), 32, …, 1k, 2k (1,025–2,048),
  4k (2,049–4,096), >4k (`BIN_EDGES` on earlier commits, `xbin`,
  `BIN_LABELS`; the names changed from "<8, 8–15, …" on 2026-11-14, the
  bins didn't). The top bin was >2k until 2026-11-14; it was split because
  71 people have passed 2k and 16 have passed 4k, but only one has passed
  8k, too few for a bin of its own. The page's
  axis says "experience (CLs landed on main)".
- **Directories** are named as they are at main's tip
  (`commits.current_paths`, `docs/commits.md`), for CLs' lines, comment
  threads and earlier commits alike: a CL of 2017 in
  `third_party/WebKit/Source/core/` counts in
  `third_party/blink/renderer/core/`, so a directory's AFR, its peers'
  rate and a person's experience there follow it across renames. A file
  that moved to another directory counts where it is now; one deleted
  before its directory moved takes the directory's new name. The half-year
  files name files as they are today too, so the page puts a file's
  threads in its directory from its name alone. A CL's lines are split over directories by git's line counts
  with each renamed file counted by its edit (`commits.moved_lines`), so a
  CL that moves 600 lines and edits 3 elsewhere is priced where the 3 are.

  **Moves barely move the index** (measured 2026-11-14 with `--fi-dump`,
  which writes each person's index over all their CLs and over their odd
  and even CLs): counting moves by their edits, in the split and in the
  cap above, left the spread unchanged (10th–90th percentile 0.38–2.05,
  SD of log index 0.806), the split-half rank correlation went from 0.775
  to 0.774, and 27 of 2,792 people moved by more than 5% (24 up, 3 down;
  9 up by more than 10%). Gerrit's counts already left most moves out.
- **Feedback index (FI):** a person's addressed threads over the number
  their CLs would be expected to draw, given their experience and their
  reviewers. A CL is expected to draw its lines / 100 × everyone else's
  pooled AFR at its experience bin × its reviewer factor from everyone
  else's CLs × `scale`, split over its directories by inserted lines
  (`unit_expected` in the script, `unitExpected` in
  `web/src/feedback.ts`); FI = addressed threads / that sum. The
  comparison is fixed: the page has no choice of peers.
- **The person's own CLs are left out** (2026-11-14, the user's call) of
  both the rate and their reviewers' factors (`own_factors`, `leaveOut` in
  the page), so nobody's own feedback sets what it is compared with. The
  rate per bin is everyone's sums (`rate_sums`) less the person's. A
  reviewer's factor is the fit's last step less the person's CLs:
  (observed − theirs + `FACTOR_SHRINK`) / (expected − theirs +
  `FACTOR_SHRINK`) / `norm`, every author's factor kept, the person's
  computed from the published factors (`author_factor`). A reviewer who
  approved only the person's CLs could not tell a strict reviewer from an
  author who draws much feedback; left out, they get the prior, 1 / norm
  (the typical reviewer), and those CLs are compared by experience alone.
  With the person's CLs in, such a pair split the difference and pulled
  the person's index toward 1. On 2026-11-14, 61 of 2,792 people with 25+
  CLs moved by more than 10% (57 down: people who draw little feedback had
  pulled their reviewers' factors down), 22 by more than 20%; the median
  moved 0.1%. Quartiles 0.67 and 1.43 (were 0.68 and 1.43), 10th–90th
  percentile 0.41–1.88 (0.42–1.87), split-half rank correlation 0.753
  (0.750). Almost all of it is the reviewer factors; leaving the person
  out of the rate alone moved 0.1% of people by over 10%. The page does
  the subtraction from the global files and the person's CLs, so no
  per-person file changes.
- **Reviewers** are a CL's approvers: the addresses in its landed commit's
  `Reviewed-by` trailers (those who voted Code-Review; `commits.sqlite`
  `reviewed_by`), as identities (`Ids.find`), the owner left out. 835,086
  of the 872,196 CLs (96%) have at least one. A CL's **reviewer factor** is
  its approvers' mean factor (`rev_factor`, `revFactor`); a CL without an
  approver takes `rev_none` (0.018 on 2026-11-14: such CLs draw almost
  nothing). Factors are fitted together with a factor for every author
  (`two_way`): a CL is expected to draw base × author × reviewers' mean,
  each factor is (observed + `FACTOR_SHRINK`) / (expected +
  `FACTOR_SHRINK`) given the others (50 expected threads; a CL with
  several approvers counts a share for each), alternating
  `FACTOR_ITERS` (10) times. So a reviewer isn't counted as strict for
  approving newcomers' or one weaker team's CLs, and a person's own CLs
  set their reviewers' factors only through their author factor (and not
  at all for their own index: see below).
  Factors are then scaled so that over all CLs they leave the expected
  total unchanged: 1.0 is the typical reviewer. 2,708 reviewers on
  2026-11-14, their factors in `reviewers.json` by hashed address
  (`reviewer_key`; the file is committed, so it lists no addresses).

  Pooled rates are lower than the typical person's (big CLs draw less per
  line, and they carry most of the lines), so the expected threads are
  multiplied by `scale`, which makes the median person's index (people
  with `MIN_CLS` CLs) exactly 1: 0.978 on 2026-11-14.

  **By reviewer, not directory** (2026-11-14, the user's call, replacing
  per-directory rates). Who approved a CL predicts its addressed threads
  much better than its directory: each CL predicted from other people's
  CLs (owner left out), scored by Poisson deviance with a factor per size
  bucket, the directory removes 5.6% of the error of experience alone,
  the reviewer 10.0%, both 10.2%, and a factor per reviewer and 2-level
  directory 11.0% (`method_compare`, on the page as "What each comparison
  predicts"). Reviewers mostly work in a few directories, so the reviewer
  carries what the directory says, and within a busy directory reviewers
  differ a lot (in `chrome/browser/`, whose CLs draw 1.26× what experience
  predicts, the middle four in five reviewers' approved CLs draw 0.61× to
  1.91×; `dir_reviewers`). It also means nobody improves their index by
  picking lenient reviewers (`docs/goals.md`). The overall factor was
  chosen over the per-directory one: a fifth more of the gain for a much
  larger table. `docs/review-feedback-reviewers.md` has the study. A
  fifth of people with 25+ CLs moved by more than 20%; quartiles 0.67 and
  1.42 (were 0.68 and 1.44), 10th–90th percentile 0.41–1.87 (0.43–1.96).

  **Before, the same day:** rates per 3-level directory and experience
  bin (falling back to the parent under `MIN_RATE_CLS` CLs' worth),
  replacing a median rate per experience bin times a two-level directory
  factor; for a few hours rates per half-year, then all-time rates with the
  person left out and a minimum of 50 (`docs/review-feedback-drift.md`).
  The directory code stays for the methodology's comparison
  (`rate_cells`, `peer_rate`). The experience, directory and organization
  checkboxes went the same day: the index has one comparison.

## What it shows

**The opening card**, "AFR" (no person needed), says nothing of
the index: the AFR's definition, then the AFR by experience bin (y-axis
"AFR", logarithmic from 0.2 to 20 since 2026-11-14, so the
steady fall per doubling is a straight line): the median of people's AFR in each bin (each
person's CLs in that bin pooled, with `MIN_BIN_CLS` = 5 or more there), with
the middle half and the 10th–90th percentile shaded (`fr_bins`). On
2026-11-14: 5.40 at 8, 4.11, 3.52, 2.87, 2.51, 2.00, 1.65, 1.28, 1.04,
0.81 at 4k and 0.53 at >4k, from 3,379 people in the first bin down to 69
at 4k and 16 at >4k (before the >2k bin was split: 0.80 there, 71 people).
(With deletions counted they were 3.95 down to 0.43; with 5, 3 or 8 CLs as
the minimum those medians moved by at most 0.15.) Below it,
"Distribution of AFR change with experience": the growth rates'
distribution, smoothed (a Gaussian kernel of 0.12 in log2 on a grid from
−75% to +183%, `growth_dist`), with the median marked. Once a person is
shown, their own values are drawn in red on all three opening charts:
their AFR per bin on the first (hollow under `MIN_BIN_CLS`, a rate of 0 at
0.2), their fitted growth rate on the second and their FI on the
feedback-index chart.

The AFR falls as much as the old index did, though on a linear axis the
chart looked flatter (hence the log axis): the old addressed index adjusted for size and directory fell 5.3×
from <10 to 1,000+ earlier commits (2.36 → 0.44), the median AFR 5.2× from 8
to 2k CLs (5.40 → 1.04), 6.7× to 4k and 10× to >4k (before the split, 6.7×
to >2k, and 9× with deletions counted). The bands make the difference: the
y-axis has to reach the 90th percentile (14.3 in the first bin), so the
median line sits in the bottom third, where the old chart drew medians only
on an axis to about 2.6.

**The second card**, "Feedback index": its definition, and everyone's index
(`fi_dist`: people with `MIN_CLS` CLs, over all the data), smoothed on a log2 grid from 1/8
to 5.7 (kernel 0.15), with the median and the 10th and 90th percentiles
marked. On 2026-11-14: 2,808 people, quartiles 0.67 and 1.42, 10th–90th
percentile 0.41–1.87.

Below it, **By directory**: everyone's directory table (`dir_table` in
`peers.json`, `dirTable` and `tableRows` on the page), with lines,
feedback (reviewer threads), addressed threads and AFR per directory, the
AFR shaded from the card (0.25 per 100 lines or less) to dark blue (8 or
more, `afrShade`). Each CL's lines and threads are split over its
directories by lines. A directory (1, 2 or 3 levels) gets a row with
`MIN_DIR_CLS` (100) CLs, under a parent that has one; smaller ones are
pooled into an "Other (n)" row per level, and a directory with
subdirectories has a "rest of" row for its own files. Each level shows its
12 largest directories and an "n more" row for the rest; ▸ opens a row. On
2026-11-14 the table has 2,938 entries. Once a person is shown, five
**Yours** columns appear (lines, feedback, addressed, AFR, FI) and each
level sorts by their lines: each of
their cells goes to its directory and parents, and to "rest of" or that
level's "Other" where the table has no row for it. A row's FI is its
addressed threads over its expected ones, so a parent adds up its children
however they are shown; its tooltip gives the AFR expected on those lines
for the person's experience and reviewers.
A row's CLs are the person's CLs' shares there by lines (a CL with 3 of
its 4 lines in a directory counts as 0.75 there), so a parent's CLs add up
its children's. Rows with fewer than `MIN_CLS` of the person's CLs show no
AFR or FI of theirs. A row's Yours Feedback count links to Your feedback,
filtered to that row: the lines, addressed threads and expected threads of
the 3-level directories counted there (`DirStats.dirs`), with each
reviewer's CLs as shares too (shown rounded); a reviewer's listed threads are those
counted in one of those directories (each thread's `dir` in the thread
files).

**Your feedback** (after an address is found), one section each:

- *Your AFR:* a link to the opening chart (where the person's line is
  drawn) and a table per bin with CLs: when the person reached the bin ("As of": the first bin on their
  first commit, the others on the day their first CL in it landed, "by"
  that day when that CL wasn't the bin's first commit; `reached` in the
  person's file, `bins_reached` in the script), CLs,
  lines, addressed threads, the person's AFR and the median AFR of all
  contributors there (`ref_bin`). The last row is all CLs.
- *Your feedback index:* tiles for changes landed (and their lines),
  addressed threads, AFR, FI (with the share of everyone with `MIN_CLS`
  CLs whose index is lower, from `fi.all`) and the latest doubling
  (below), then the FI per half-year against the 10th–90th percentile,
  middle half and median of everyone's index that half-year (`fi[half]`).
  Dots with fewer than `MIN_CLS` CLs are hollow. Selecting a dot filters
  Your feedback to the CLs landed that half-year.
- *Your feedback* (`reviewerRows`): everyone who approved one of the
  person's CLs (in the picked half-year and directory, if any) whose
  approvals drew addressed threads (rows with none are left out), most
  CLs first: the
  person's CLs they approved, addressed threads on them, the person's AFR
  there, the reviewer's factor without the person's CLs (so it can differ
  a little from what others see), everyone's CLs they approved, and the
  person's FI on those CLs. A CL with several approvers counts under each.
  Rows under `MIN_BIN_CLS` of the person's CLs show no AFR or FI. The note
  says how many of the person's CLs had no approver, and their factor
  (`rev_none` without the person's CLs). ▸
  opens a reviewer into the addressed threads they started on the person's
  CLs (`reviewerComments`), newest first: the day of the first comment, the
  change number linking to the thread in Gerrit, and the file ("commit
  message" for `/COMMIT_MSG`). They come from the person's thread file in R2
  ("Downloading your comments"), so only for changes landed in the past
  year, fetched the first time a reviewer is
  opened. A commenter is a reviewer when their Gerrit account's address
  belongs to that approver's identity ("Who is who", below);
  `cosh.review_threads` records which approver each commenter is
  (`reviewers`). No comment text and no tone. Threads from someone who
  never approved one of the person's CLs aren't listed, having no row.
- *Latest doubling* (the tile, `latestDoubling`): the % change in AFR from
  the person's second-newest to their newest bin with `MIN_BIN_CLS` CLs,
  per doubling when bins in between have too few, with the date they
  reached the newer bin (`reached`) and the typical change over the same
  bins (from `ref_bin`).
- *Growth rate* (the opening growth chart): the % change in AFR per doubling of changes landed, from a
  least-squares line through log2 AFR by bin, each bin weighted by its CLs,
  over bins with `MIN_BIN_CLS` CLs, needing `MIN_GROWTH_BINS` (3) of them;
  FRs under `FR_FLOOR` (0.1) count as 0.1 (`growth`). On 2026-11-14 2,517
  people have one: median −18.8%, 10th percentile −44.6%, 90th +21.1%
  (−20.9%, −47.4% and +22.7% with deletions counted).

The person's directories are the Yours columns of everyone's directory
table (`dirTable`, `tableRows`), in the Feedback index card. A
per-person directory tree down to files and their CLs, with links to each
addressed comment and its tone score, was removed on 2026-11-14 as
redundant with those columns (the user's call), and its link files with it.
The page shows no comment text: the download takes that role. The
histogram of addressed comments per CL was removed the same day (the
user's call).

**Methodology and details** is a collapsed `<details>` at the bottom whose
charts are drawn when it opens:

- *Why compare by reviewer, not directory:* what each comparison predicts
  (`method`: % of the experience-only deviance removed by directory,
  reviewer, both, and reviewer per directory), and reviewers within the
  `CHART_DIRS` (12) busiest 2-level directories (`dir_revs`: each
  directory's factor against experience alone as a mark, its reviewers'
  10th–90th percentile and middle half, for reviewers expecting
  `MIN_SPREAD_EXP` (50) threads there; not shrunk, since a few expected
  threads shrunk toward 1 would lift reviewers in directories that draw
  almost nothing). On 2026-11-14 every directory's mark sits within its
  reviewers' range.
- *Drift over time* (`drift`): per half-year, everyone's addressed threads
  over what experience and size expect, and over what experience, size,
  reviewers and authors expect (size by a factor per size bucket over all
  the data, so a few huge CLs don't swing a half-year). On 2026-11-14 the
  second runs 0.96–1.07 from 2017H2 to 2026H1 (the first 0.85–1.13), so
  factors over all the years are sound, but 2026H2 is 0.81 (0.70 by
  experience and size): CLs drew less feedback even with the same
  reviewers and authors, falling month by month (0.91 in July to 0.75 in
  October, size-adjusted), as the median CL grew from about 26 to 43
  lines. Everyone's 2026H2 index runs low.

- *How it's changing:* people's AFR over their CLs in one experience bin,
  picked with a selector (default 8 or fewer CLs; it offers the bins with a
  median in 3 or more years, 8 through 1k on 2026-11-14), by year of first
  commit on `main` from 2018 (`COHORT_FROM`; people with `MIN_BIN_CLS` CLs
  in the bin): median and middle half. On 2026-11-14 the medians at 8 or
  fewer run 5.24, 5.92, 5.89, 5.56, 5.73, 5.57, 6.18, 5.32 for 2018–2025
  and 3.89 for 2026 (not over); at 129–256 they run 2.53, 2.07, 2.06, 2.14,
  2.13, 1.91, 1.79, 1.72 for 2018–2025.
- *By change size:* two bar charts per size bucket (`size10`): the median
  person's addressed threads per CL (0.10 under 4 lines → 9.58 at 512–1k on
  2026-11-14) and their AFR (5.54 → 1.40, 0.21 at 1k+). Per line the
  difference is much smaller, which is why the AFR counts per line. A person
  counts in a bar with `MIN_CELL_CLS` (10) CLs there; a bar needs
  `MIN_PEERS` people.
- *By directory* and *by organization:* the median person's AFR over their
  CLs whose main directory (two levels) is in each of the `CHART_DIRS` (12)
  directories with the most people, and over their CLs from each of the
  `CHART_ORGS` (10) orgs with the most people, highest first. On 2026-11-14
  code directories run 1.2–3.3 (components/autofill/ 3.29, chrome/browser/
  2.61, third_party/blink/ 1.80) while configuration directories draw
  almost none (testing/buildbot/ 0.16, (root)/ 0.15). Org factors with
  experience run 0.37–1.73 for orgs with 300+ CLs (google.com 1.01,
  microsoft.com 0.89, igalia.com 0.85), against 0.38–3.25 without it, so
  orgs differ partly through their contributors' experience; with
  experience and directories (per half-year, without the person; the
  index no longer has org factors), 0.39–1.97 (google.com 1.00, microsoft.com 0.95, igalia.com 0.91).
  Whether the index should compare by organization: "Google and other
  organizations" below.
- *How it's measured:* the definitions above in prose.

**Dates come from the data**, never from the code. The range runs from the
oldest week in `reviews.sqlite`'s `fetched_weeks` (but no earlier than the
oldest usable CL) to the end of the newest, trimmed to whole months
(`trim_start`, `trim_end`). `peers.json` gives the page `start`, `end`
(exclusive) and `addr_start` as day numbers. There is no date selector:
every figure covers all of it, and only the over-time chart splits it, by
half-year.

**Praise** and **tone** don't appear on the page (the "See also your
praise" link to the Review Tone page was removed on 2026-11-14).

Removed on 2026-11-14 with the switches: the cohort curves by start year,
the year-over-year and per-doubling histograms of the old index, the
all-against-addressed and tenure-comparison charts, the count tiles' ranks
in the latest half-year, and the 2023–24 size and directory norms as a
measure (the files still carry the expected values, unused, so the
half-year files didn't change).

## Why deletions don't count

Until 2026-11-14 lines were insertions plus deletions. A study that day
(913,707 labelled CLs, 2017-07 .. 2026-10; deletions are 40% of their
changed lines) showed that deleted lines draw almost no addressed feedback:

- At the same total size, addressed threads per CL fall steeply with the
  deleted share. For 256–1023 lines: 10.3 with under 5% deleted, 5.0 at
  25–50%, 2.3 at 50–75%, 0.40 at 95% or more. CLs that only delete
  (41k) drew 0.08 addressed threads each, against 1.89 overall; 6% had any.
- Fitting addressed ≈ k·(insertions + w·deletions)^p by Poisson deviance,
  w = 0 fit best for every p tried (0.4 – 0.9), also against w = 0.01.
  A changed line is already one insertion, so insertions cover what
  reviewers read.
- Counting deletions penalised people who delete a lot. Ranks among people
  with 25+ CLs barely moved overall (Spearman 0.96), but people deleting
  half their lines or more rose 12 percentile points on average with
  insertions alone, and those deleting under 20% fell 8.
- Experienced people delete more (28% of changed lines under 8 earlier
  changes, 49% at 2k+), so part of the fall of AFR with experience was
  deletions: the drop from <8 to 2k+ is ×6.8 with insertions, ×9.2 with
  both.
- With insertions the 2023–24 size norms explain more of the CL-to-CL
  spread (R² 0.20 against 0.14 for addressed threads), and the spread of
  people's FI narrows a little (10th–90th percentile 0.43–1.91 against
  0.38–1.94 under experience and directories).

A dashboard on deletion over time is an idea in `docs/plan.md` (Next
steps 9).

## Google and other organizations

**The question** (2026-11-14): does the index favour people at Google, who
have experts nearby to help before a CL reaches Gerrit and are mostly
reviewed by colleagues? Should it compare within an organization, or have
an organization filter again? **No:** nothing in the data shows non-Googlers
drawing more feedback or tougher reviews than Googlers, if anything the
opposite, and an organization factor moves people without predicting
better. The index stays without one.

Measured on 872,193 CLs and the 2,834 people with `MIN_CLS` CLs. A person's
org is the one most of their CLs landed as (`OrgResolver`, per CL at its
close day); an unlisted `chromium.org` address counts as Google, and
`config/affiliations.json5` lists the non-Google ones (refreshed
2026-11-12). Lower means less addressed feedback than expected.

| Group | People | Index: 10th pct. | Quartile | Median (95% CI) | Quartile | 90th pct. |
|---|---|---|---|---|---|---|
| Google | 2,503 | 0.40 | 0.68 | 1.02 (0.99–1.04) | 1.44 | 1.91 |
| of them, `google.com` addresses | 1,014 | 0.38 | 0.67 | 0.97 (0.92–1.04) | 1.44 | 1.93 |
| Outside Google | 331 | 0.35 | 0.56 | 0.86 (0.78–0.98) | 1.32 | 1.84 |
| microsoft.com | 142 | 0.35 | 0.56 | 0.85 (0.71–0.98) | 1.29 | 1.85 |
| gmail.com | 42 | 0.36 | 0.66 | 1.10 (0.98–1.27) | 1.73 | 2.38 |
| igalia.com | 40 | 0.35 | 0.54 | 0.87 (0.62–1.03) | 1.20 | 1.53 |

- **The gap runs the other way, and is small.** Googlers' median is 1.18
  times (1.06–1.32) that of people outside Google. A random Googler's index
  is above a random non-Googler's 56% of the time. The gap in mean log
  index (0.14) is a fifth of the spread between people (SD 0.68) and half
  of one person's own noise (0.27, from odd and even CLs; split-half rank
  correlation 0.76 for Google, 0.67 outside).
- **Newcomers show it most.** Pooled addressed threads over expected, in
  the first 8 CLs: Google 1.08, outside 0.89 (ratio 1.22, 1.07–1.38); CLs
  9–16, 1.06 and 0.85; 17–32, 1.01 and 0.65. Help before upload would
  show as the opposite. From 128 CLs up the ratio's interval includes 1
  (few people outside Google have that many).
- **Half of it is where people work.** Pooled over CLs, Google's observed
  over expected is 1.20 times (1.08–1.35) the others'; with a factor per
  directory, 1.07; with CL size, directory, period and no-approver
  together, 1.08 (1.02–1.15). By period, with those controls: 1.21 in
  2017–20, 1.05 in 2021–23, 1.01 in 2024–26.
- **Reviewers don't treat outsiders differently.** 80% of non-Googlers'
  CLs are approved only by Googlers (95% of Googlers' are). For the 800
  Google reviewers with at least 5 expected threads on each side, addressed
  threads over the full fit's expected (author and reviewer factors both
  in) on outsiders' CLs are 1.01 times (0.97–1.04) those on colleagues',
  and half the reviewers are on each side of 1. By cell, the same measure
  is 1.00 for Google authors with Google approvers and 0.96 (0.95–0.98)
  for other authors with Google approvers. No period differs.
- **An organization factor moves people without predicting better.** A
  factor for Google or not (1.006 and 0.839, fitted like a reviewer's, the
  person left out) raises all 331 non-Googlers, by 18% at the median, and
  removes 12.14% of the error of experience alone where the index removes
  12.10% (`method_compare`'s deviance, owner left out). A factor per org
  moves 284 people by more than 10% and predicts slightly worse (12.02%).
  `docs/goals.md` chooses peer groups by prediction.

What does differ, for everyone alike:

- **Familiar pairs draw less.** An approver's first approval of an
  author's CL draws 1.18 times the full fit's expected threads, 1.05 after
  1–4 earlier ones, 0.99 after 5–19 and 0.91 after 20 or more (Google
  pairs; for non-Googlers with other orgs' approvers 1.07 → 0.89, with
  their own org's 1.23 → 0.92). Googlers get 36% of their expected threads
  from pairs of 20 or more, others 19%: by that mix alone Googlers would
  sit about 4% lower. The reviewer factor carries none of this.
- **More approvers, more feedback.** A CL with two or more approvers
  draws about 1.5 times what one with a single approver does (1.18 against
  0.79 of the fit's expected, Google pairs), and the index takes the
  approvers' mean factor. 48% of non-Googlers' CLs have two or more, 29%
  of Googlers'.

Either could go into the expected count if it passes `method_compare`;
neither has been tried.

Limits. Googlers are 88% of the people, so they set the median and the
rates: help that every Googler gets off Gerrit can't be seen in any of
this. The other group is small and mostly Microsoft and Igalia. The org
factor was fitted on top of the index's expected count, not together with
the author and reviewer factors. Which reviewer sees which CL isn't
random. Scripts and full tables are scratch, not in git:
`data/private/scratch/fi-org-bias/` (`capture.py` and `pairs_capture.py`
run `cosh.review_feedback` up to its rate model and write nothing;
`analyze.py`, `pairs_analyze.py`, `pairs_mix.py`).

## Working across many directories

**The question** (2026-11-14): does the index penalise people who work
across many directories? Experience counts CLs landed anywhere on `main`,
so someone who keeps moving to code new to them keeps ramping up while
their experience bin says "veteran". **Per change, yes; per person, no.**
A CL in a directory new to its author draws about 1.2 times what the index
expects. But people who do much of that work don't have a higher index,
and a correction for it moves almost nobody. The index stays as it is.

Measured on 872,193 CLs and the 2,834 people with `MIN_CLS` CLs, with the
index's own expected threads (owner left out). A unit's **familiarity** is
the owner's earlier commits on `main` (from 2008, reverts left out,
today's names) that touched the same 3-level directory. A **new**
directory has fewer than 4 of them.

- **Per change, unfamiliarity costs about one or two doublings.** Adjusted
  for size (a factor per size bucket) and directory (a factor per 2-level
  directory), a CL whose main directory is one its author never committed
  to draws 1.19 times (1.15–1.21) the expected threads (81k CLs). After 64
  or more commits there it draws 0.87–0.89 times. Veterans pay more in a
  new directory: 1.15 at 64 CLs or fewer, 1.21 at 65–256, 1.28 at 257–1k
  and 1.47 above 1k. By rate per line, a 257–1k author in a new directory
  draws like a 65–256 one, not like a newcomer.
- **It fades with commits there.** For veterans (more than 256 CLs), by
  earlier commits in the 3-level directory: 1.29 at 0, 1.20 at 1, 1.13 at
  2–3, 1.08 at 8–15, 1.00 at 16–31 and 0.85–0.89 from 64 up. Returning
  after a year away costs about half the effect (1.16, against 0.95 with a
  commit in the last year).
- **It holds within each person.** For 817 people with 10 or more CLs on
  each side in the same experience bin, CLs in a never-touched directory
  draw a median 1.23 times (1.17–1.29) what their CLs in directories with
  16+ earlier commits do. 64% are above 1. It holds within every size
  group and every era, though it has shrunk (veterans in new directories:
  1.51 in 2017–20, 1.29 in 2021–23, 1.17 in 2024–26). Reviewers aren't
  stricter there (mean reviewer factor about 1.14 either way). Most of the
  excess is on CLs spanning several directories: single-directory CLs in
  new directories draw about what the index expects.
- **The index as published barely penalises it, because big CLs cancel
  it.** The index doesn't adjust for size, and 843 CLs of over 1,024 lines
  whose main directory is new to the author (imports, new components) draw
  0.20 of their expected threads while carrying a third of that group's.
  With all CLs pooled, lines in new directories draw 1.01 of expected and
  familiar ones 0.98. Without the huge CLs, a new main directory draws 1.44
  and a familiar one 1.17. So someone whose new-directory work is small
  edits looks a little worse, and someone landing large code drops looks
  better.
- **Broad people don't have a higher index.** The **unfamiliar share** is
  the share of a person's expected threads in new directories. It has a
  rank correlation of about 0 with the index within bands of CL count
  (25–63, 64–255, 256–1,023, 1,024+): −0.02 to +0.08, and +0.09 for the
  489 people with 512+ CLs. The broadest fifth's median index is 0.91, the
  narrowest fifth's 0.92. It is mostly a newcomer's measure: its median
  falls from 0.47 at 25–63 CLs to 0.13 at 1,024+, and only 12 people with
  512+ CLs have over half their work in new directories.
- **Spread, as distinct from newness, goes with a higher index.** People
  whose lines are spread evenly over many 3-level directories (the
  exponential of the entropy of their lines) have a higher index. The
  median by fifth, within bands of CL count, runs from 0.77 for the most
  concentrated to 1.13 for the most spread (rank correlation +0.21; +0.16
  between odd CLs' spread and even CLs' index). The unfamiliar share
  explains none of it, so it isn't ramping up. A likely cause, not tested:
  concentrated people more often work where little feedback is drawn
  (tests, generated or configuration files), which the reviewer factor
  takes in only in part.

**Corrections tried.** Each was fitted on a random half of people and
applied to the other half, both ways, then rescaled to a median index of
1. "Error removed" is the Poisson deviance of per-CL addressed threads,
with a factor per size bucket, as a share of the index's own.

| Correction | Error removed | Split-half (0.754 now) | Moved > 10% (> 20%) | Broadest fifth's median |
|---|---|---|---|---|
| A factor per familiarity bucket (0, 1–3, 4–15, 16–63, 64+), fitted over all CLs | +0.25% | 0.756 | 8 (0) | ×0.99 |
| A rate per experience bin and familiarity bucket | −0.23% | 0.756 | 303 (32) | ×0.98 |
| Experience in the 3-level directory instead of on `main` | −8.7% | 0.775 | 2,200 (1,647) | ×1.10 |
| A familiarity factor fitted with a factor per author (like `two_way`) | +0.60% | 0.761 | 283 (0) | ×0.94 |

The last is the only one that predicts better and is more consistent. Its
factors are 1.18, 1.08, 1.02, 0.95 and 0.87 by familiarity bucket. But it
gains little next to the reviewer factor (which removed 10% of the error
of experience alone, "By reviewer, not directory"), moves nobody by more
than 20%, and lowers broad people's index by 6%, not raises it. It would
also reward moving between directories a little (by at most about 17%)
and read as punishing depth. Global experience predicts clearly better
than any count within a directory.

**A broad contributor, for example.** One of the broadest people in the
data has 738 CLs since late 2023, in 354 2-level and 733 3-level
directories. 44% of their expected threads are in new directories (95th
percentile of their CL-count band, whose median is 19%). Their index is
1.52. In new directories it is 1.26 (AFR 2.45), in familiar ones 1.72
(2.66): the opposite of the typical pattern. Their CLs of over 1,024
lines in new directories drew no addressed threads against 86 expected.
Without them, new directories give 1.48 against 1.97 familiar. With the
within-person correction their index would be 1.49 (78th percentile to
77th). Ramping up doesn't explain this person's index: their higher
figures are in their home directories.

**What could be shown instead.** If the question keeps coming up, the
page could split a person's AFR and index between new and familiar
directories, next to what peers' new-directory work typically draws.
That needs a familiarity bucket in the per-person cells (about 17% more
cells, measured without approvers in the key) and five numbers in
`peers.json`. The by-directory table could also show the person's earlier
commits in each directory. Not built.

Limits. Familiarity counts only commits landed on `main`, under today's
directory names: work on other projects, or reviewing in a directory,
doesn't count. A new directory may also mean a new project, a new team or
owners from elsewhere, which the data can't tell apart from the author's
learning. Scripts and full tables are scratch, not in git:
`data/private/scratch/feedback-breadth/` (`capture.py` runs
`cosh.review_feedback` up to its rate model and writes `breadth.sqlite`,
per CL and per CL × 3-level directory with the owner's earlier commits
there; `cl-level/`, `person-level/` and `correction/` hold the analyses).

## Ground rules

- **No tone** (`docs/plan.md`, ground rule 5): the script reads no review
  tone, so no chart, figure or file of the page carries it.
- **No completions, no browsing.** The input has `autocomplete="off"`, no
  datalist and no name. Per-person files are named by the address as
  typed, lower case (`file_name` in the script, `personFile` in `web/src/feedback.ts`;
  unit tests check they agree), with each byte of a character outside
  `a-z 0-9 . _ @ -` written as `~xx`. They live in the R2 bucket, which
  can't be listed, so the page finds only someone whose address you type.
  (Until 2026-11-14 they were named by a salted hash, which kept the
  addresses out of git while the files were committed.) Normalising is
  `people.address`: lower case, an SVN-era `user@domain@uuid` cut to
  `user@domain`, and no domains merged. Every other address of the
  person's identity ("Who is who") gets a stub `{"see": <name>}`. The
  address never goes into the page's URL.
- Everything comes from public Gerrit and git data, so per-person files may be
  published (ground rule 3). No comment text is published (since
  2026-11-14); file paths come from git and Gerrit and the page renders
  them only as text.

## Who is who

A person is an exact identity (`people.exact_identities`, shared with
Review Load and the thread files, the user's call on 2026-11-14):
addresses merge only on evidence, never because they share a username
across `chromium.org` and `google.com`.

- **Owner and author.** A git author address and the Gerrit owner address
  of most of their CLs (3 or more CLs and half of the author's) are one
  person (`alias_pairs` on exact addresses). This covers 98.6% of the
  68,805 merged CLs whose owner and author differ only in domain.
- **Reviewer.** A Reviewed-by address is the Gerrit account's whose
  address it is (Gerrit writes the voter's preferred address there; 97.4%
  of 1.41M Reviewed-by addresses). One that is no account's address (the
  reviewer changed their preferred address since) is tied to the account
  that cast the CL's approving vote when that is unambiguous on 2 or more
  CLs and half of its CLs (`vote_links`, from `review-timeline.sqlite`):
  136 of 169 such addresses, 88% of their uses, 49 of them under another
  username.
- Gerrit's public data gives only each account's preferred address, not
  the ones linked to it, so two accounts of one person with no such
  evidence stay two people. Before 2026-11-14 the Feedback Index folded
  `chromium.org` into `google.com` (`people.person`, which scripts/ still
  use); of the 1,162 usernames with an account in each domain, about five
  look like different people. Exact identities give 7,142 people and 803
  other addresses (6,862 and 122 with the domains folded).

## Generate

Offline: about 2 minutes and 1.5 GB at its peak (`config/dataflow.json`
has the measured times; see "Memory" below):

```
COSH_DATA_DIR=<main>/data/private nice -n 5 python3 -m cosh.review_feedback [--out DIR]
```

It (`review-feedback`) reads `reviews.sqlite`, `commits.sqlite`,
`addressed.sqlite` and config, and writes `peers.json`, `reviewers.json`,
the per-person files and the CL index. It reads no review tone or comment text,
and no `balance*.sqlite`, so refreshing the page
needs none of the balance stages (timeline, interdiff, cl). The per-CL facts
it needs (owner, status, Gerrit insertions, closing time, the landed
commit's sha, and its lines per 3-level directory under today's names)
come from `cosh.cl_facts` (`cl_facts` and `cl_dirs`). First commits and mechanical CLs come from
`commits.sqlite` (`docs/commits.md`).

To take in an older backfill (back to 2017-07), let it finish, then run a
full `derive` (which ends with `python3 -m cosh commits`), then this
script: nothing in it names a date.

The served site (`npm run serve`) rebuilds by itself once `public/` has been
quiet for 5 seconds, so a run's files are served shortly after it ends
(`web/serve.mjs`, 2026-11-12). Until that build finishes, the pages keep the
old data, and a page change that needs new `peers.json` fields draws nothing.

Output, with `<name>` the person's normalised address, in three kinds of
file that the page loads at different times: `peers.json` and
`reviewers.json` in `web/public/review-feedback/` (`--out`, committed, which
Vite copies into the site), and the per-person files, gzipped, in
`data/private/feedback-people/` (`--people-out`), which `python3 -m cosh.r2
publish` uploads to the R2 bucket under `review-feedback/people/v2/`
(`docs/r2.md`). It also writes `data/private/feedback-cls.json.gz`
(`--cls-out`, private, not published): each person's CLs per half-year with
their approvers and the directory each of their threads counts in
(`cl_index`), from which `cosh.review_threads` writes the comment files.

- `peers.json` (global, loaded on opening; version 12, about 134 KB, 42 KB
  gzipped): the experience bins (`bins`, `bin_edges`), the index's rates
  per bin (`rate_bin`) and their sums ([lines, addressed threads],
  `rate_sums`), `rev_none` and `scale`, the methodology's
  comparison, reviewers within directories and drift (`method`,
  `dir_revs`, `drift`), the
  median AFR per bin (`ref_bin`, `ref_all`, for comparisons), everyone's
  directory table (`dir_table`), the spread of AFR per bin (`fr_bins`) and
  of everyone's index per period (`fi`), and the methodology's data (`cohorts`, `growth`,
  `by_size`, `by_dir`, `by_org`), with the minimums the page names.
- `reviewers.json` (version 2, loaded with the first person; about 105
  KB, 51 KB gzipped): `rev_none`, `none` (the observed and expected
  threads of CLs without an approver), `norm`, `shrink` and, per reviewer
  by `reviewer_key` of their address (the first 12 hex digits of
  `sha256("cosh-review-feedback-v1:" + normalised address)`, so the
  committed file lists no addresses), [factor, CLs approved, observed and
  expected addressed threads]. The page hashes each of the person's
  approvers (`reviewerKey`) to look them
  up (`attachReviewers`) and takes the person's CLs out of the sums
  (`leaveOut`); every figure about the person needs them.
  Rewritten on every run.
- `<name>.json` (version 8), one file per person, loaded once an address
  is typed (one request): first commit (`first`, `first_day`), the org
  most of their CLs were landed as, when they reached each experience bin
  (`reached`: [day, exact] or null per bin), the days of their first and
  last labelled CL (`days`), and `halves`: by half-year (`2017H2` …
  `2026H2`), their labelled CLs as cells (`person_doc` and `half_cells` in
  the script). A cell is every CL's share in one experience bin, 3-level
  directory and set of approvers: [bin, directory, approvers, CLs in
  thousandths, the landed commits' inserted lines, reviewer threads,
  addressed threads], with directory names (today's) and approvers'
  addresses listed once per half-year (`dirs`, `revs`). A CL is split over
  its directories by lines, in thousandths that add up to 1,000
  (`milli_fracs`), so whole half-years and bins add up to whole CLs. A
  thread counts in its file's 3-level directory when the CL inserted lines
  there, else in the CL's main directory (the commit message, files the
  landed commit didn't change). No change numbers, days, files or
  per-thread data. Each other address of the person is a stub
  `{"see": <name>}`. Until 2026-11-14 the halves held each CL (version 7,
  `shard`): its change number and day, Gerrit's lines, earlier commits,
  lines per directory, approvers and the files that drew threads.

The page computes a person's figures from these, the same way the script
does for the spread of everyone's index: totals, AFR and FI for any period,
and the growth rate, from the rounded rates and factors in `peers.json` and
`reviewers.json`. `--check FILE` writes the script's values for 300
people; on 2026-11-14, from the cells (files v8), with the person's own CLs left out, the page's
`buildPerson`, `attachReviewers`, `sums` and `fiOf` matched all 3,448 of them exactly
(FI, CLs, addressed threads and lines per period), every approver found
by `reviewerKey`, and every growth rate.

So a person's file changes only when they land a CL (or an input changes:
labels, mechanical list, identity merge, today's names of moved paths,
approvers). Reviewer factors live in `reviewers.json`, not in these files,
so they can change every week without rewriting anyone's file. Each run
rewrites `peers.json` and `reviewers.json` and the files of people with
CLs in the current half-year (1,871 files, 8.8 MB gzipped in 2026H2;
18 MB before cells), which the next publish uploads.

Sizes on 2026-11-14 (7,142 people, 803 stubs), gzipped file by file:
14.8 MB for the per-person files (7,945 files; 29 MB with each CL, and
before they were joined into one per person 37.6 MB for the half-year
files and 1.0 MB for `u/`), 42 KB for `peers.json` and 51 KB for
`reviewers.json`; the private CL index is 35 MB. Each run writes only the
per-person files that changed and removes those no longer written.

**Published** (the user's call, 2026-11-12): from 2026-11-12 to 2026-11-14
the whole folder was committed and served by GitHub Pages; since then
`peers.json` and `reviewers.json` are committed and the per-person files
are in R2 (`docs/plan.md`, 2026-11-14). After regenerating, run `python3
-m cosh.r2 publish` before pushing the change that needed the new files.
On localhost (`npm run serve`) the page reads the local copies at once,
with no upload. The browser tests serve a made-up person
(`web/test/feedback-fixture.ts`), so they don't depend on the data. The
script's inputs (`data/private/*.sqlite`) aren't published.

**The lean layout** (2026-11-14, files v6, replacing v4 and the comment
list; the goals' "publish the minimum", `docs/goals.md`). Before, 34 MB of
half-year files (gzipped) kept each thread's file, day and label from 2025H2
(per-directory counts before), two unused expected values, each
directory's share and earlier commits, and the org of each CL, and 16 MB of
comment files kept 200-character excerpts. Measured one step at a time
(gzipped): dropping the unused expected values saved 3.0 MB, keeping only
lines per directory 5.9 MB, keeping thread counts per file instead of each
thread 2.6 MB, the org per CL 0.6 MB, and storing change numbers and days
as differences 1.5 MB. Naming every file of every CL would have cost
58 MB (6.1 files per CL, 1.1 with threads), so only the files that drew
threads are named. Comment ids are random and cost about 1.3 MB per
half-year, so they start in 2023 (23 MB for all years; the user's call).

**Cells, not changes** (2026-11-14, files v8; the user's call). Every
figure about a person sums over lines, threads and addressed threads per
experience bin, directory and approvers: the page never needs a CL as
such. Fitting the index on such cells instead of CLs gave every person
the same index (rank correlation 1.0000, nobody moved). Two other ways of
counting were tried and not taken: crediting each addressed thread to the
approver who wrote it (about 90% of them; the rest come from someone who
commented but didn't approve) moved 1,141 of 2,808 people by more than 10%,
spread reviewer factors (0.43–1.88 against 0.59–1.51 at the 10th–90th
percentile) and made the index less consistent between a person's odd and
even CLs (0.742 against 0.753); counting only approvers' threads dropped 14%
of newcomers' addressed feedback but 6% of experts', and would let an
author lower their index by choosing who approves. So a CL's threads still
count equally for each of its approvers. Scripts and results:
`data/private/scratch/feedback-edges/`.

### Memory

The build holds every labelled CL in memory at once (about 870k on
2026-11-14), because the reviewer and author factors are fitted over all
of them together (`two_way`, ten passes), each person's comparison takes
their own CLs away from everyone's sums (`own_factors`), and a person's
file needs all of their CLs. So memory grows with the data, by about
0.8 KB per CL: about 80 MB a year at Chromium's rate of 95k CLs, with the
data already back to Gerrit's start in 2017.

To keep that small (4.8 GB peak before 2026-11-14, 1.5 GB after, the
files unchanged byte for byte), a CL is a `Row` with slots rather than a
dict, and the same object serves the rate model and the per-person files;
CLs are read one at a time (`cl_facts.iter_cl_facts`) and only the merged,
human, line-inserting ones are kept; each thread keeps only its root and
the index of the directory it counts in, with per-directory counts on the
CL; addressed labels are joined in SQLite rather than held in a dict;
directory names are shared strings; and expected threads per unit
(`_ue`, `method_compare`) sit in flat `array("d")`s, with
`method_compare`'s leave-one-out sums built one person at a time.

Processing in chunks (say by half-year) would bound memory, but only by
re-reading every chunk for each pass of the global fit (about 15), which
would make the build several times slower. If memory ever matters again,
the next step is columnar rows (`array`s per field, about 150 bytes per CL)
rather than chunks.

## Downloading your comments

Once an address is typed, the page's last card, "Download your review
comments", saves one file with every comment thread a reviewer started on
that person's changes that landed in the past year (the 52 weeks up to
the data's end), each reply in full. Markdown (one section per change, each
thread with its file, line, patch set, whether it was addressed, a Gerrit
link and every comment quoted), optionally headed by instructions for an AI
coach (the same task as `scripts/feedback_coach.py`'s, in the page's
`dl-prompt` template), or JSON (the file as fetched). The file is built in
the browser; comment text never goes into the page itself. This hands the
coaching report to the person's own assistant instead of spending our
model usage on it.

The threads are too big for git (52 MB gzipped: 2,384 files, 349k threads, 2026-11-14), so they live in the Cloudflare
R2 bucket `cosh` and are served gzipped from
`https://cosh-data.rbyers.ca/review-feedback/threads/v3/<name>.json`,
fetched only when someone downloads or opens a reviewer in Your feedback
(`?v=` is the data's end, so a new week
isn't hidden by the day-long cache). Named like the per-person files, so
like them they are reachable only by typing an address (ground rule 5
allows comment text there, negative comments included). One file per
person (median 8 KB, up to 412 KB gzipped), and only the past year: every
year back to 2017, one file per half-year, was 33,015 files and 407 MB,
far more than the download's purpose (recent feedback for the person's
own assistant) needs (the user's call, 2026-11-14). A person with no such
thread in the year has no file, which the page reads as "no comments".
Each weekly publish uploads the files of people with changes that week
(about 1,900 of them, most of the 52 MB).

```
COSH_DATA_DIR=<main>/data/private nice -n 5 python3 -m cosh.review_threads
python3 -m cosh.r2 publish review-feedback/threads/v3   # from the main checkout, when deploying
```

`cosh.review_threads` (step `review-threads`, after `review-feedback`) reads
the CL index (`data/private/feedback-cls.json.gz`) for each person's
changes and the directory each thread counts in, `reviews.sqlite`
(subjects, owners, accounts, which threads were addressed), `addressed.sqlite`
and the NoteDb repos (comment text, file, line, patch set, resolved), and
writes `data/private/review-threads/<name>.json.gz`, byte for byte
the same when nothing changed (the module's docstring has the format).
Threads by bots and AI reviewers, and threads the owner started, are left
out; "addressed" is the Feedback Index's own measure, null for
change-level threads. About 60 seconds, 1.1 GB of memory (2026-11-15).

`cosh.r2 publish` (step `r2-feedback`, with the per-person files) runs
only when deploying, before the push (`docs/r2.md`, "Deploying"). It
uploads the files whose sha256 differs from `data/private/r2-manifest.json`,
deletes objects whose file is gone once the live site no longer reads them,
and never lists the bucket. It refuses more than 50,000 objects in a run or
5 GB in all (`--max-objects`, `--max-total-gb`; the first is per prefix). The bucket's setup
(domain, CORS, caching, costs, the token) is in `docs/r2.md`. Credentials:
`~/.secrets/cosh/r2.json` (endpoint, bucket, access key, secret, public
base), a token that can only read and write this bucket. Weekly, only the
current half-year's files change.

## Caveats

- Tenure in years counts from the first commit on `main`, and earlier
  commits, on `main` or in a directory, from the start of its history
  (2008). Before 2026-11-12 earlier commits counted only from 2017
  (`balance-git.sqlite`'s start), which undercounted people active before
  then. Before 2017, reverts are told by "This reverts commit" and bots by
  address alone (there is no `Bot-Commit` trailer then).
- Reviewer threads include any thread a non-owner started, including
  drive-by and gardening comments, as the feedback index does.
- Peer groups mix very different roles, teams and kinds of work. A high or
  low figure is a prompt to look at the comments, not a conclusion.
- Who reviews a CL isn't wholly independent of the CL: harder changes may
  go to stricter, more senior reviewers, and the reviewer factor then
  credits the author for that. Reviewers' habits change over the years,
  which a factor over all the data averages. CLs without an approver
  (4%) are expected to draw almost nothing.
- A pooled rate weighs big CLs by their lines, and feedback per line falls
  with size (5.5 per 100 lines under 4 lines, 1.4 at 512–1k, 0.21 over
  1k): someone landing larger changes gets a lower rate at the same care.
  The index doesn't adjust for size.
- The rates and factors cover all the data (2017–2026). With reviewers
  and authors accounted for, feedback was steady until 2026H1 (0.96–1.07
  of expected per half-year), but 2026H2 drew 0.81 of expected, so
  everyone's index for it runs low (the methodology's drift chart; the
  over-time chart shows everyone's spread per half-year). Every time
  correction tried before reviewers predicted peers' feedback worse
  (`docs/review-feedback-drift.md`).
- Each run's new CLs change every rate a little, so past figures move
  slightly from week to week.
- A rate over a few CLs is noisy, so part of the spread in each bin and in
  the growth rates is noise, not people.

## Per-person feedback report (`scripts/feedback_coach.py`)

`python3 scripts/feedback_coach.py <email>` writes a private Markdown report
to `data/private/feedback-coach/<email>.md` (not published, not on the site).
It takes the author's past year (`--days 365`, up to the newest comment in
`reviews.sqlite`) of reviewer threads on their own `main` CLs: file and
commit-message threads they **addressed** (regex, else the Haiku label), plus
CL-level threads minus bare approvals. The newest 600 (`--max-threads`) go to
one call of Claude Opus through `cosh.sandbox.Sandbox` (no tools, bwrap, reply
bound to a JSON schema; comments are untrusted, `SECURITY.md`). The report
opens with a Summary of at most 3 points on the biggest opportunities, then
the patterns, each with examples and where to invest. With 80+
threads the report gets a section per 2nd-level directory that has 20+
(file threads by their file, the rest by the CL's main directory). The model
cites threads as `[T12]`; the script turns them into Gerrit comment links and
strips any other URL or HTML. Its reply is kept next to the report
(`.reply.json`), so `--reuse` re-renders without a new call; `--dry-run` only
counts. On 2026-11-12 one report took about 1 min and 115–150k tokens.
