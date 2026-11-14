# Feedback Index: addressed feedback rate (AFR) and index

What changes to it are judged by: `docs/goals.md`.

`web/feedback-index.html` shows how much review feedback Chromium changes
draw per 100 lines as their authors gain experience, and lets anyone type an
email address to see that person's AFR and index against their
peers'. It is
a learning guide, and the page says so at the top: "This analysis is imperfect
and is intended as a learning guide only". The landing page links to it
(since 2026-11-12), and it carries `noindex`.

## Definitions

Both are fixed: the page has no switches for them (the user's call,
2026-11-14).

- **Addressed feedback rate (AFR):** addressed reviewer threads per 100 new or changed
  lines, pooled over a set of CLs (all their addressed threads × 100 / all
  their lines). Lines are Gerrit's insertions: a changed line counts once,
  and deleted lines don't count (since 2026-11-14; see "Why deletions don't
  count"). CLs that only delete lines are left out. The CLs are merged,
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
  >2k (`BIN_EDGES` on earlier commits, `xbin`, `BIN_LABELS`; the names
  changed from "<8, 8–15, …" on 2026-11-14, the bins didn't). The page's
  axis says "experience (CLs landed on main)".
- **Directories** are named as they are at main's tip
  (`commits.current_paths`, `docs/commits.md`), for CLs' lines, comment
  threads and earlier commits alike: a CL of 2017 in
  `third_party/WebKit/Source/core/` counts in
  `third_party/blink/renderer/core/`, so a directory's AFR, its peers'
  rate and a person's experience there follow it across renames. A file
  that moved to another directory counts where it is now; one deleted
  before its directory moved takes the directory's new name. In the
  per-thread files, a thread on a file that has moved since names its unit
  (`[file, days, addressed, unit]`), since the page can't tell it from
  the file.
- **Feedback index (FI):** a person's AFR over their peers'. Per directory
  a CL wrote lines in, the addressed threads its peers would have drawn are
  those lines / 100 × the peers' rate there, and FI = addressed threads /
  that sum (`unit_expected` in the script, `unitExpected` in
  `web/src/feedback.ts`). The peers' rate (`rates`, `peer_rate`,
  `peerRate`) is the pooled AFR of everyone else's lines in the CL's
  3-level directory, landed in the CL's half-year at its experience bin:
  the person's own CLs are left out (`rates` holds each cell's sums,
  [CLs' worth, lines, addressed threads], and the script and page subtract
  the person's own, `rate_cells` and `ownCells`). A directory with fewer
  than `MIN_RATE_CLS` (200) CLs' worth there without them (each CL split
  over its directories by inserted lines, `unit_fracs`; `cl_dirs` with
  `dels=False`) takes its parent's (2 levels, then 1, then all of
  Chromium that half-year), cell by cell; where all of Chromium has too
  few (the first weeks of a half-year), the nearest earlier half-year's
  with enough counts, else that half-year's anyway. What the peers are (`NORMS`,
  picked on the page with three checkboxes):
  - *Experience* (`e`, on by default): rates per experience bin; without
    it, the rates at any experience (the last entry of each list).
  - *Directories* (`d`, on by default): rates per directory; without it,
    all of Chromium's (`rates[half][""]`).
  - Every norm compares within the CL's half-year, without the person.
  - *Organization* (`o`, off by default): a factor per org (the CL's, by
    `cosh/orgs.py`), its pooled addressed threads over what the other two
    predict; orgs with fewer than `MIN_FACTOR_CLS` (300) CLs share one (`*`).

  Pooled rates are lower than the typical person's (big CLs draw less per
  line, and they carry most of the lines), so each norm's expected threads
  are multiplied by `scale[norm]`, which makes the median person's index
  (people with `MIN_CLS` CLs) exactly 1; the org factors are scaled the
  same way. On 2026-11-14 the scales were 0.923 (experience and
  directories), 1.038 (experience), 1.133 (directories) and 1.331 (none).

  **Why this way** (2026-11-14, replacing a median rate per experience bin
  times a two-level directory factor). Comparing within each directory and
  experience bin is what readers expect the index to mean, and the page
  can show it: everyone's table lists each directory's AFR, and a person's
  index in a row is their AFR there over the peers' rate on the same lines.
  Adding up threads and expected threads weighs each directory by the
  feedback peers draw there, so a parent's index is the same whether it is
  open or not, and the overall index is the same sum. Weighing directories
  by lines instead (a lines-weighted mean of per-directory indexes) lets a
  few threads in a directory that draws almost none (configuration,
  imported code) swing the index. Measured on the 2,808 people with 25+
  CLs: the rank correlation of each person's index from their odd and
  their even CLs was 0.739 with this method (`MIN_RATE_CLS` 200), 0.734 at
  100, 0.723 at 50, 0.738 at 300, 0.698 weighing by lines, and 0.729 with
  the old one; ranks under the new and old ones agree closely (Spearman
  0.96). The spread barely moved: 10th–90th percentile 0.42–1.96 (was
  0.43–1.91), quartiles 0.68 and 1.42 (0.67 and 1.39).

  **Per half-year, without the person** (2026-11-14, replacing rates over
  all the data that included the person's own CLs). Feedback per line
  drifts: all of Chromium drew 26% less than the all-time rates expect in
  2026, and some directories moved 1.5–2.4× between 2017–22 and 2025–26
  (`net/http/`, `third_party/blink/web_tests/`), others down to 0.56×.
  With all-time rates, someone working mostly in 2025–26 was compared with
  other eras' norms (the median such person's index was 13% low), and in a
  directory one person dominates, their own CLs set the norm and pulled
  their index toward 1. Comparing within the half-year without the person
  made the index more consistent within each person: the rank correlation
  of the index from odd and even CLs rose from 0.748 to 0.776, and from
  the older and the newer half of their CLs from 0.522 to 0.555 (yearly
  rates, every-two-years rates, a factor per directory and year, and a
  trailing two-year window all did worse; `docs/review-feedback-drift.md`).
  About a third of people with 25+ CLs moved by more than 20%. The index
  no longer shows Chromium-wide shifts (everyone's median per half-year
  runs 0.96–1.14, against 0.75–1.16 before); the AFR charts do. It cost
  `peers.json` 34 KB gzipped and nothing else: the per-person files didn't
  change. The spread: quartiles 0.65 and 1.44, 10th–90th percentile
  0.35–2.04.

## What it shows

**The opening card**, "AFR" (no person needed), says nothing of
the index: the AFR's definition, then the AFR by experience bin (y-axis
"AFR", logarithmic from 0.2 to 20 since 2026-11-14, so the
steady fall per doubling is a straight line): the median of people's AFR in each bin (each
person's CLs in that bin pooled, with `MIN_BIN_CLS` = 5 or more there), with
the middle half and the 10th–90th percentile shaded (`fr_bins`). On
2026-11-14: 5.40 at 8, 4.11, 3.52, 2.86, 2.49, 2.00, 1.64, 1.28, 1.04 and
0.80 at >2k, from 3,379 people in the first bin down to 71 in the last.
(With deletions counted they were 3.95 down to 0.43; with 5, 3 or 8 CLs as
the minimum those medians moved by at most 0.15.) Below it,
"Distribution of AFR change with experience": the growth rates'
distribution, smoothed (a Gaussian kernel of 0.12 in log2 on a grid from
−75% to +183%, `growth_dist`), with the median marked. Once a person is
shown, their own values are drawn in red on all three opening charts:
their AFR per bin on the first (hollow under `MIN_BIN_CLS`, a rate of 0 at
0.2), their fitted growth rate on the second and their FI (under
`FI_NORM`, whatever norm is picked below) on the feedback-index chart.

The AFR falls as much as the old index did, though on a linear axis the
chart looked flatter (hence the log axis): the old addressed index adjusted for size and directory fell 5.3×
from <10 to 1,000+ earlier commits (2.36 → 0.44), the median AFR 5.2× from 8
to 2k CLs (5.40 → 1.04) and 6.7× to >2k (6.7× and 9× with deletions
counted). The bands make the difference: the
y-axis has to reach the 90th percentile (14.3 in the first bin), so the
median line sits in the bottom third, where the old chart drew medians only
on an axis to about 2.6.

**The second card**, "Feedback index": its definition, and everyone's index
(`fi_dist`: people with `MIN_CLS` CLs, over all the data, under
experience and directories, `FI_NORM`), smoothed on a log2 grid from 1/8
to 5.7 (kernel 0.15), with the median and the 10th and 90th percentiles
marked. On 2026-11-14: 2,808 people, quartiles 0.65 and 1.44, 10th–90th
percentile 0.35–2.04.

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
**Yours** columns appear (lines, feedback, addressed, AFR, FI under the
norm picked in their section) and each level sorts by their lines: each of
their units goes to its directory and parents, and to "rest of" or that
level's "Other" where the table has no row for it. A row's FI is its
addressed threads over its expected ones, so a parent adds up its children
however they are shown; its tooltip gives the peers' AFR on those lines.
Rows with fewer than `MIN_CLS` of the person's CLs show no AFR or FI of
theirs.

**Your feedback** (after an address is found), one section each:

- *Your AFR:* a link to the opening chart (where the person's line is
  drawn) and a table per bin with CLs: when the person reached the bin ("As of": the first bin on their
  first commit, the others on the day their first CL in it landed, "by"
  that day when that CL wasn't the bin's first commit; `binReached`), CLs,
  lines, addressed threads, the person's AFR and the median AFR of all
  contributors there (`ref_bin`). The last row is all CLs.
- *Your feedback index:* the checkboxes (experience, directories,
  organization; they also set the Yours FI in everyone's directory table), tiles for changes landed (and their lines), addressed
  threads, AFR, FI (with the share of everyone with `MIN_CLS` CLs whose
  index is lower, from `fi[norm].all`) and the latest doubling (below), then
  the FI per half-year against the 10th–90th percentile, middle half and
  median of everyone's index that half-year (`fi[norm][half]`). Dots with
  fewer than `MIN_CLS` CLs are hollow. Selecting a dot filters the
  comments-per-change chart, the directory tree and the comments to that
  half-year, as before.
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
  addressed threads (0, 1–2, 3–5, 6–10, 11–20, 21+), whose columns filter
  the directories and comments.
- *Where your feedback comes from:* the directory tree as before (top level
  first, "Other" for entries under `MIN_CLS` CLs, any directory opens), with
  CLs, lines (each CL's lines × its fraction there), addressed threads, AFR,
  FI under the chosen norm (shaded green below 1, red above, saturating at
  0.25× and 4×) and earlier commits. Rows under `MIN_CLS` CLs show no AFR or
  FI.
- *The comments:* the addressed threads only, newest first, with the
  directory, half-year and column filters as before. Each comment's head
  starts with its CL number, linked to the comment in Gerrit, then its date
  and file, with its tone score as a pill at the right (its tooltip says it
  is a sentiment score this analysis doesn't use). Comments without stored
  text are in a table in a collapsed `<details>` below the list.

**Methodology and details** is a collapsed `<details>` at the bottom whose
charts are drawn when it opens:

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
  experience and directories (per half-year, without the person),
  0.39–1.97 (google.com 1.00, microsoft.com 0.95, igalia.com 0.91).
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
(`sentiment.html#person=<address>`). **Tone** appears only in the comment
list: each comment whose tone has been scored (`sentiment.sqlite`, current
prompt) carries a pill with its score from −1 to +1, negative ones too
(ground rule 5, 2026-11-14).

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

- **Tone only in the comment list** (`docs/plan.md`, ground rule 5, as
  tiered on 2026-11-14). The page shows a person's comments only after
  someone types their address, so each comment may carry its tone score,
  negative ones included. Nothing reachable by clicking ranks or lists
  anyone by tone, no chart or figure uses tone, and orgs get no tone
  figures. The scores sit in their own files (`comments/`), written by
  their own step, so tone never feeds the charts.
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
  published (ground rule 3). Comment text is untrusted: the script copies it
  without a model seeing it, and the page renders it only as text.

## Generate

Offline, in two parts: a few minutes and 3 GB for the people part, seconds
for the comments part (`config/dataflow.json` has the measured times):

```
COSH_DATA_DIR=<main>/data/private nice -n 5 python3 -m cosh.review_feedback --part people [--out DIR]
COSH_DATA_DIR=<main>/data/private nice -n 5 python3 -m cosh.review_feedback --part comments [--out DIR]
```

Without `--part` it writes both in one run. The people part
(`review-feedback`) reads `reviews.sqlite`, `commits.sqlite`,
`addressed.sqlite` and config, and writes `peers.json`, `u/`, the half-year
folders and the thread index `data/private/feedback-threads.jsonl` (for
each person and half-year from 2025H2, the comment ids of its threads in
the half-year file's order). The comments part (`feedback-comments`) joins
that index with the collected comment files (`data/private/comments/`) and
`sentiment.sqlite`, and writes `comments/`. So review tone and comment text
reach only the comment list, and each comment file lines up with the
half-year file of the same run by construction (the page still ignores a
change's comment entries if their count differs). Neither part reads
`balance*.sqlite`, so refreshing the page
needs none of the balance stages (timeline, interdiff, cl). The per-CL facts
it needs (owner, status, Gerrit insertions, closing time, the
landed commit's sha and files, and its lines and files per 3-level
directory) come from `cosh.balance.cl_facts` and `cl_dirs`, the functions
`python3 -m cosh.balance cl` builds `balance.sqlite`'s `cl` and `cl_dirs`
from, so the two can't drift (2026-11-12; before, it read them from
`balance.sqlite`). First commits and mechanical CLs come from
`commits.sqlite` (`docs/commits.md`); `--first-commit F` and `--mech F` read
the old hand-made files instead.

To take in an older backfill (back to 2017-07), let it finish, then run a
full `derive` (which ends with `python3 -m cosh commits`), then this
script: nothing in it names a date.

The served site (`npm run serve`) rebuilds by itself once `public/` has been
quiet for 5 seconds, so a run's files are served shortly after it ends
(`web/serve.mjs`, 2026-11-12). Until that build finishes, the pages keep the
old data, and a page change that needs new `peers.json` fields draws nothing.

Output (default `web/public/review-feedback/`, which Vite copies into the
site), with `<key>` the hash of the person's address, in three kinds of
file that the page loads at different times:

- `peers.json` (global, loaded on opening; version 8, about 318 KB, 93 KB
  gzipped): the experience bins (`bins`, `bin_edges`), the index's rate
  sums per half-year and directory (`rates`, about 150 KB, 39 KB gzipped),
  scales and org factors (`scale`, `f_org`), the median AFR per
  bin (`ref_bin`, `ref_all`, for comparisons), everyone's directory table
  (`dir_table`), the spread of AFR per bin (`fr_bins`) and of
  everyone's index per norm and period (`fi`), and the methodology's data
  (`cohorts`, `growth`, `by_size`, `by_dir`, `by_org`), with the
  minimums the page names.
- Per person, loaded once an address is typed:
  - `u/<key>.json` (version 5): first commit and which half-years the
    person has files for. Small and rewritten on every run. Each other
    address of the person is a stub `{"see": <key>}`.
  - `<half-year>/<key>.json` (`2017H2` … `2026H2`, one per half-year in the
    range): that half-year's CLs, with their directory splits and reviewer
    threads (file, day, addressed; no text), and the directory, file and
    org names listed once (`shard` in the script, whose docstring has the
    layout). Half-years before 2025H2 (`THREADS_FROM`) have thread counts
    per directory instead of each thread (`"counts": 1`; see "Slimmed
    before publishing" below).
- `comments/<half-year>/<key>.json` (comment list only, from 2025H2): per
  change, one entry per thread of the half-year file, in its order: 0
  without text, else the comment id, the excerpt and, where scored, the
  tone score (`comment_file`).

The page computes a person's figures from these, the same way the script
does for the spread of everyone's index: totals, AFR and FI under every norm
for any period, and the growth rate, with the rounded typical rates and
factors from `peers.json`. `--check FILE` writes the script's values for 300
people; on 2026-11-14, after the index moved to per-half-year rates without
the person, the page's `buildPerson`, `sums` and `fiOf` matched all 27,800
of them exactly (FI under every norm, CLs, addressed threads and lines):
both subtract the person's own sums from the same rounded cells.

So a half-year's files don't change once it is over, as long as the inputs
don't (the 2023–24 norms, still written though unused, labels, mechanical
list, identity merge, and for `comments/`, the collected comment text and
scores): git stores them once. Each run rewrites the current half-year,
`u/` and `peers.json`.

Sizes on 2026-11-14 (6,862 people, 122 stubs, 45,231 files), gzipped file
by file as git stores them: 35.2 MB for the 19 half-year folders, 0.9 MB
for `u/` and `peers.json`, and 16.7 MB for `comments/` (excerpts and
scores): 53 MB in all, 122 MB unpacked. The people part replaces `u/` and every half-year folder on each run, the
comments part `comments/`.

**Committed and published** (the user's call, 2026-11-12):
`web/public/review-feedback/` is in git, so the GitHub Pages build serves it.
After regenerating, commit the folder with the change that needed it
(`git add -A web/public/review-feedback/`, which also drops files the run
removed). The browser tests serve a made-up person
(`web/test/feedback-fixture.ts`), so they don't depend on the data. The
script's inputs (`data/private/*.sqlite`) aren't published.

**Slimmed before publishing** (2026-11-12, file format v4): 197 MB → 126 MB,
68 → 53 MB gzipped file by file. Nothing the page computes changed: every
person's values and changes matched the v3 files', except that CLs whose
two largest directories tie on rounded share now always take the first by
name as their main directory (8 of 2.2M threads moved, a few rates moved by
0.001). What changed:

- Half-years before the one that reaches the comment-text year (before
  2025H2) keep [threads, addressed] per directory of each CL instead of
  each thread. The comments list shows those as one row per change and
  directory ("3 threads in ui/views/"), linked to the change, without
  files or dates. (The user's call: the alternatives were shorter excerpts,
  dropping 2017–19, or dropping the per-directory data.)
- The expected threads by size alone (`exp_ts`, `exp_as`) depend only on
  the size bucket, so they left the files (`peers.json` listed them as
  `size_norm` until 2026-11-14, when the page stopped using norms).
- A thread's directory isn't stored: it is its file's (3 levels) when the
  CL has a unit there, else the CL's first unit.
- A CL wholly in one directory stores [directory, earlier commits there].

Measured then (gzipped): comment excerpts 13 MB, per-directory data 17 MB,
file paths 11 MB, comment uuids 3 MB; each half-year before 2023 about
1.7 MB.

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
- A pooled rate weighs big CLs by their lines, and feedback per line falls
  with size (5.5 per 100 lines under 4 lines, 1.4 at 512–1k, 0.21 over
  1k): someone landing larger changes gets a lower rate at the same care.
  The index doesn't adjust for size.
- The index compares within each half-year, so it doesn't show whether
  all of Chromium draws more or less feedback over time (it drew about a
  quarter less per line in 2026); the AFR does. Per half-year, fewer
  directories have 200 CLs' worth (55–88 at 1, 2 or 3 levels, against 712
  over all the data), so more lines take a parent directory's rate.
- In the first weeks of a half-year its rates rest on few CLs, so a
  person's index for the current half-year is provisional; finished
  half-years' rates don't change.
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
