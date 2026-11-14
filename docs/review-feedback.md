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
  their lines). Lines are Gerrit's insertions: a changed line counts once,
  and deleted lines don't count (since 2026-11-14; see "Why deletions don't
  count"). Moved files count by the lines changed, not as new: Gerrit's
  counts mostly leave moves out already, and where Gerrit missed one (381k
  lines in 1,141 CLs, 0.24% of all lines), the landed commit's insertions
  with renamed files counted by their edits cap the CL's lines
  (`move_free_ins`). CLs that only delete lines, or only move files, are
  left out. The CLs are merged,
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
  reviewers. A CL is expected to draw its lines / 100 × everyone's pooled
  AFR at its experience bin (`rate_bin`) × its reviewer factor × `scale`,
  split over its directories by inserted lines (`unit_expected` in the
  script, `unitExpected` in `web/src/feedback.ts`); FI = addressed threads
  / that sum. The comparison is fixed: the page has no choice of peers.
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
  don't set their reviewers' factors (the authors' factors take them).
  Factors are then scaled so that over all CLs they leave the expected
  total unchanged: 1.0 is the typical reviewer. 2,708 reviewers on
  2026-11-14, their factors in `reviewers.json` by hashed address.

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
their units goes to its directory and parents, and to "rest of" or that
level's "Other" where the table has no row for it. A row's FI is its
addressed threads over its expected ones, so a parent adds up its children
however they are shown; its tooltip gives the AFR expected on those lines
for the person's experience and reviewers.
Rows with fewer than `MIN_CLS` of the person's CLs show no AFR or FI of
theirs.

**Your feedback** (after an address is found), one section each:

- *Your AFR:* a link to the opening chart (where the person's line is
  drawn) and a table per bin with CLs: when the person reached the bin ("As of": the first bin on their
  first commit, the others on the day their first CL in it landed, "by"
  that day when that CL wasn't the bin's first commit; `binReached`), CLs,
  lines, addressed threads, the person's AFR and the median AFR of all
  contributors there (`ref_bin`). The last row is all CLs.
- *Your feedback index:* tiles for changes landed (and their lines),
  addressed threads, AFR, FI (with the share of everyone with `MIN_CLS`
  CLs whose index is lower, from `fi.all`) and the latest doubling
  (below), then the FI per half-year against the 10th–90th percentile,
  middle half and median of everyone's index that half-year (`fi[half]`).
  Dots with fewer than `MIN_CLS` CLs are hollow. Selecting a dot filters
  the comments-per-change chart to that half-year.
- *Your reviewers* (`reviewerRows`): everyone who approved one of the
  person's CLs, most CLs first: the person's CLs they approved, addressed
  threads on them, the person's AFR there, the reviewer's factor, everyone's
  CLs they approved, and the person's FI on those CLs. A CL with several
  approvers counts under each. Rows under `MIN_BIN_CLS` of the person's CLs
  show no AFR or FI. The note says how many of the person's CLs had no
  approver, and `rev_none`.
- *Latest doubling* (the tile, `latestDoubling`): the % change in AFR from
  the person's second-newest to their newest bin with `MIN_BIN_CLS` CLs,
  per doubling when bins in between have too few, with the date they
  reached the newer bin (`binReached`) and the typical change over the same
  bins (from `ref_bin`).
- *Growth rate* (the opening growth chart): the % change in AFR per doubling of changes landed, from a
  least-squares line through log2 AFR by bin, each bin weighted by its CLs,
  over bins with `MIN_BIN_CLS` CLs, needing `MIN_GROWTH_BINS` (3) of them;
  FRs under `FR_FLOOR` (0.1) count as 0.1 (`growth`). On 2026-11-14 2,517
  people have one: median −18.8%, 10th percentile −44.6%, 90th +21.1%
  (−20.9%, −47.4% and +22.7% with deletions counted).
- *Addressed comments per change:* the histogram of the person's CLs by
  addressed threads (0, 1–2, 3–5, 6–10, 11–20, 21+).

The person's directories are the Yours columns of everyone's directory
table (`dirTable`, `tableRows`), in the Feedback index card. A
per-person directory tree down to files and their CLs, with links to each
addressed comment and its tone score, was removed on 2026-11-14 as
redundant with those columns (the user's call), and its link files with it.
The page has no comment text: a feedback report will take that role (the
user's call, 2026-11-14).

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
- *How it's measured:* the definitions above in prose.

**Dates come from the data**, never from the code. The range runs from the
oldest week in `reviews.sqlite`'s `fetched_weeks` (but no earlier than the
oldest usable CL) to the end of the newest, trimmed to whole months
(`trim_start`, `trim_end`). `peers.json` gives the page `start`, `end`
(exclusive) and `addr_start` as day numbers. There is no date selector:
every figure covers all of it, and only the over-time chart splits it, by
half-year.

**Praise** has no section here: after a lookup, "See also your praise"
links to the Review Tone page's popup for the address
(`sentiment.html#person=<address>`). **Tone** doesn't appear on the
page.

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

## Ground rules

- **No tone** (`docs/plan.md`, ground rule 5): the script reads no review
  tone, so no chart, figure or file of the page carries it.
- **No completions, no browsing.** The input has `autocomplete="off"`, no
  datalist and no name. Data files are named by
  `sha256("cosh-review-feedback-v1:" + normalised address)[:32]`
  (`key` in the script, `personKey` in `web/src/feedback.ts`; unit tests check
  they agree), so the folder lists no addresses and the page finds only
  someone whose address you type. Normalising follows
  `balance_analysis.person`: lower case, `chromium.org` = `google.com`.
  Other addresses of the same person (from the identity merge) get a stub
  `{"see": <key>}`. The address never goes into the URL.
- Everything comes from public Gerrit and git data, so per-person files may be
  published (ground rule 3). No comment text is published (since
  2026-11-14); file paths come from git and Gerrit and the page renders
  them only as text.

## Generate

Offline: a few minutes and 3 GB (`config/dataflow.json` has the measured
times):

```
COSH_DATA_DIR=<main>/data/private nice -n 5 python3 -m cosh.review_feedback [--out DIR]
```

It (`review-feedback`) reads `reviews.sqlite`, `commits.sqlite`,
`addressed.sqlite` and config, and writes `peers.json`, `reviewers.json`,
`u/` and the half-year folders. It reads no review tone or comment text,
and no `balance*.sqlite`, so refreshing the page
needs none of the balance stages (timeline, interdiff, cl). The per-CL facts
it needs (owner, status, Gerrit insertions, closing time, the landed
commit's sha, and its lines per 3-level directory and in the files that
drew threads, under today's names) come from `cosh.cl_facts` (`cl_facts`,
and `cl_dirs` with `files`). First commits and mechanical CLs come from
`commits.sqlite` (`docs/commits.md`).

To take in an older backfill (back to 2017-07), let it finish, then run a
full `derive` (which ends with `python3 -m cosh commits`), then this
script: nothing in it names a date.

The served site (`npm run serve`) rebuilds by itself once `public/` has been
quiet for 5 seconds, so a run's files are served shortly after it ends
(`web/serve.mjs`, 2026-11-12). Until that build finishes, the pages keep the
old data, and a page change that needs new `peers.json` fields draws nothing.

Output (default `web/public/review-feedback/`, which Vite copies into the
site), with `<key>` the hash of the person's address, in three kinds of file
that the page loads at different times:

- `peers.json` (global, loaded on opening; version 11, about 134 KB, 42 KB
  gzipped): the experience bins (`bins`, `bin_edges`), the index's rates
  per bin (`rate_bin`), `rev_none` and `scale`, the methodology's
  comparison, reviewers within directories and drift (`method`,
  `dir_revs`, `drift`), the
  median AFR per bin (`ref_bin`, `ref_all`, for comparisons), everyone's
  directory table (`dir_table`), the spread of AFR per bin (`fr_bins`) and
  of everyone's index per period (`fi`), and the methodology's data (`cohorts`, `growth`,
  `by_size`, `by_dir`, `by_org`), with the minimums the page names.
- `reviewers.json` (loaded with the first person; about 71 KB, 34 KB
  gzipped): `rev_none` and, per reviewer by the first 12 hex digits of
  `key` of their address (so it lists no addresses), [factor, CLs
  approved]. The page hashes each of the person's approvers to look them
  up (`attachReviewers`); every figure about the person needs them.
  Rewritten on every run.
- Per person, loaded once an address is typed:
  - `u/<key>.json` (version 6): first commit, the org most of their CLs
    were landed as, and which half-years the person has files for. Small
    and rewritten on every run. Each other address of the person is a
    stub `{"see": <key>}`.
  - `<half-year>/<key>.json` (`2017H2` … `2026H2`, one per half-year in the
    range; `shard` in the script, whose docstring has the layout): that
    half-year's CLs, each [change number and day landed, each less the
    previous CL's; Gerrit's inserted lines; earlier commits on main; the
    landed commit's inserted lines per 3-level directory; its approvers;
    and the files that drew reviewer threads, each with its inserted
    lines, threads and addressed threads], with directory and file names
    (today's) and approvers' addresses listed once (`dirs`, `files`,
    `revs`). Nothing else per CL: no org, no expected values, no per-thread
    data. A file's threads count in its 3-level directory when that is one
    of the CL's, else in the CL's main directory (the commit message, files
    the landed commit didn't change).

The page computes a person's figures from these, the same way the script
does for the spread of everyone's index: totals, AFR and FI for any period,
and the growth rate, from the rounded rates and factors in `peers.json` and
`reviewers.json`. `--check FILE` writes the script's values for 300
people; on 2026-11-14, with reviewer factors, the page's `buildPerson`,
`attachReviewers`, `sums` and `fiOf` matched all 3,475 of them exactly
(FI, CLs, addressed threads and lines per period), every approver found
by hashed address.

So a half-year's files don't change once it is over, as long as the inputs
don't (labels, mechanical list, identity merge, today's names of moved
paths, approvers): git stores them
once. Reviewer factors live in `reviewers.json`, not in these files, so
they can change every week without rewriting a finished half-year. Each
run rewrites the current half-year, `u/`, `peers.json` and
`reviewers.json`.

Sizes on 2026-11-14 (6,862 people, 122 stubs), gzipped file by file as git
stores them: 37.6 MB for the 19 half-year folders (32,676 files; 31.8 MB
before approvers were added, the same day), 1.0 MB for `u/`, 42 KB for
`peers.json` and 34 KB for `reviewers.json`: 39 MB in all, 110 MB
unpacked. Each run replaces `u/` and every half-year folder.

**Committed and published** (the user's call, 2026-11-12):
`web/public/review-feedback/` is in git, so the GitHub Pages build serves it.
After regenerating, commit the folder with the change that needed it
(`git add -A web/public/review-feedback/`, which also drops files the run
removed). The browser tests serve a made-up person
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

## Downloading your comments

Once an address is typed, the page's last card, "Download your review
comments", saves one file with every comment thread a reviewer started on
that person's landed changes, each reply in full, for the half-years they
pick (by default the latest two). Markdown (one section per change, each
thread with its file, line, patch set, whether it was addressed, a Gerrit
link and every comment quoted), optionally headed by instructions for an AI
coach (the same task as `scripts/feedback_coach.py`'s, in the page's
`dl-prompt` template), or JSON (the files as fetched). The file is built in
the browser; comment text never goes into the page itself. This hands the
coaching report to the person's own assistant instead of spending our
model usage on it.

The threads are too big for git (400 MB gzipped: 32,676 files, 2.78M threads, 2026-11-14), so they live in the Cloudflare
R2 bucket `cosh` and are served gzipped from
`https://cosh-data.rbyers.ca/review-feedback/threads/<half>/<key>.json`,
fetched only when someone downloads (`?v=` is the data's end, so a new week
isn't hidden by the day-long cache). Same hashed keys as the per-person
files, so like them they are reachable only by typing an address (ground
rule 5 allows comment text there, negative comments included).

```
COSH_DATA_DIR=<main>/data/private nice -n 5 python3 -m cosh.review_threads [--half 2026H2]
python3 -m cosh.r2 sync data/private/review-threads review-feedback/threads   # from the main checkout
```

`cosh.review_threads` (step `review-threads`, after `review-feedback`) reads
the published half-year files for each person's changes, `reviews.sqlite`
(subjects, owners, accounts, which threads were addressed), `addressed.sqlite`
and the NoteDb repos (comment text, file, line, patch set, resolved), and
writes `data/private/review-threads/<half>/<key>.json.gz`, byte for byte
the same when nothing changed (the module's docstring has the format).
Threads by bots and AI reviewers, and threads the owner started, are left
out; "addressed" is the Feedback Index's own measure, null for
change-level threads. About 5 minutes for all 19 half-years, 20 s for one.

`cosh.r2 sync` (step `r2-threads`) uploads the files whose sha256 differs
from `data/private/r2-manifest.json`, deletes objects whose file is gone,
and never lists the bucket. It refuses more than 50,000 objects in a run or
5 GB in all (`--max-objects`, `--max-total-gb`). Credentials:
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
