# Feedback Index: addressed feedback rate (AFR) and index

What changes to it are judged by: `docs/goals.md` (goal 2 is about figures
for one person).

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
  with enough counts, else that half-year's anyway. The comparison is
  fixed: the page has no choice of peers (the experience, directory and
  organization checkboxes went on 2026-11-14, see "One comparison" below).

  Pooled rates are lower than the typical person's (big CLs draw less per
  line, and they carry most of the lines), so the expected threads are
  multiplied by `scale`, which makes the median person's index (people
  with `MIN_CLS` CLs) exactly 1: 0.923 on 2026-11-14.

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

  **One comparison** (2026-11-14). The checkboxes that picked the peers
  (experience and directories on, organization off) are gone, and with
  them the organization factors: the goals (`docs/goals.md`) define the
  index as a comparison within the same directory, experience and time,
  and every other combination needed its own rate sums in `peers.json`
  once the person is left out of their own peers. Organizations remain in
  the methodology's chart.

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
0.2), their fitted growth rate on the second and their FI on the
feedback-index chart.

The AFR falls as much as the old index did, though on a linear axis the
chart looked flatter (hence the log axis): the old addressed index adjusted for size and directory fell 5.3×
from <10 to 1,000+ earlier commits (2.36 → 0.44), the median AFR 5.2× from 8
to 2k CLs (5.40 → 1.04) and 6.7× to >2k (6.7× and 9× with deletions
counted). The bands make the difference: the
y-axis has to reach the 90th percentile (14.3 in the first bin), so the
median line sits in the bottom third, where the old chart drew medians only
on an axis to about 2.6.

**The second card**, "Feedback index": its definition, and everyone's index
(`fi_dist`: people with `MIN_CLS` CLs, over all the data), smoothed on a log2 grid from 1/8
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
**Yours** columns appear (lines, feedback, addressed, AFR, FI) and each
level sorts by their lines: each of
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
- *Your feedback index:* tiles for changes landed (and their lines),
  addressed threads, AFR, FI (with the share of everyone with `MIN_CLS`
  CLs whose index is lower, from `fi.all`) and the latest doubling
  (below), then the FI per half-year against the 10th–90th percentile,
  middle half and median of everyone's index that half-year (`fi[half]`).
  Dots with fewer than `MIN_CLS` CLs are hollow. Selecting a dot filters
  the comments-per-change chart and the directory tree to that half-year.
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
  the directory tree.
- *Where your feedback comes from* (`dirTree`, `dirRows`): the person's
  directories from the top level down to their 3-level directories, then
  down through any deeper directories to the files that drew reviewer
  threads, with changes, lines, feedback (reviewer threads), addressed
  threads, AFR and FI (shaded green below 1, red above, saturating at
  0.25× and 4×). Each level lists its entries with `MIN_CLS` CLs (all of
  them, up to 15, when none has that many) and pools the rest in "Other";
  rows under `MIN_CLS` CLs show no AFR or FI. A CL's lines go to its
  3-level directories and then to its files by the landed commit's
  inserted lines (times the CL's Gerrit lines, so the AFR's definition
  holds); a directory's lines that drew no threads are its "other files"
  row, and a file's expected threads are its share of its directory's. The
  commit message counts as a file of the CL's main directory. A file opens
  into its CLs, newest first: the change number linking to the change in
  Gerrit, the day it landed, its threads and addressed threads on the file,
  and for CLs from `links_from` (2023H1) a link to each addressed comment,
  with its tone score as a pill where it was scored (its tooltip says it is
  a sentiment score this analysis doesn't use). The links load when a file
  is first opened. The page has no comment text: a feedback report will
  take that role (the user's call, 2026-11-14).

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
(`sentiment.html#person=<address>`). **Tone** appears only beside the
comment links in a file's list of CLs: each addressed comment whose tone
has been scored (`sentiment.sqlite`, current prompt; mostly from
mid-2025) carries a pill with its score from −1 to +1, negative ones too
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

- **Tone only beside each comment's link** (`docs/plan.md`, ground rule 5, as
  tiered on 2026-11-14). The page shows a person's comment links only after
  someone types their address, so each may carry its tone score, negative
  ones included. Nothing reachable by clicking ranks or lists anyone by
  tone, no chart or figure uses tone, and orgs get no tone figures. The
  scores sit in their own files (`links/`), written by their own step, so
  tone never feeds the charts.
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

Offline, in two parts: a few minutes and 3 GB for the people part, seconds
for the links part (`config/dataflow.json` has the measured times):

```
COSH_DATA_DIR=<main>/data/private nice -n 5 python3 -m cosh.review_feedback --part people [--out DIR]
COSH_DATA_DIR=<main>/data/private nice -n 5 python3 -m cosh.review_feedback --part links [--out DIR]
```

Without `--part` it writes both in one run. The people part
(`review-feedback`) reads `reviews.sqlite`, `commits.sqlite`,
`addressed.sqlite` and config, and writes `peers.json`, `u/`, the half-year
folders and the link index `data/private/feedback-links.jsonl` (for each
person and half-year from `LINKS_FROM`, 2023H1, the comment ids of the
addressed threads by CL and file entry, `link_ids`). The links part
(`feedback-links`) joins that index with `sentiment.sqlite` and writes
`links/`. So review tone reaches only the CL lists under a file, and each
link file lines up with the half-year file of the same run by
construction. Neither part reads `balance*.sqlite`, so refreshing the page
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
site), with `<key>` the hash of the person's address, in four kinds of file
that the page loads at different times:

- `peers.json` (global, loaded on opening; version 9, about 206 KB, 66 KB
  gzipped): the experience bins (`bins`, `bin_edges`), the index's rate
  sums per half-year, directory and bin (`rates`) and its `scale`, the
  median AFR per bin (`ref_bin`, `ref_all`, for comparisons), everyone's
  directory table (`dir_table`), the spread of AFR per bin (`fr_bins`) and
  of everyone's index per period (`fi`), the first half-year with comment
  links (`links_from`), and the methodology's data (`cohorts`, `growth`,
  `by_size`, `by_dir`, `by_org`), with the minimums the page names.
- Per person, loaded once an address is typed:
  - `u/<key>.json` (version 6): first commit, the org most of their CLs
    were landed as, and which half-years the person has files for. Small
    and rewritten on every run. Each other address of the person is a
    stub `{"see": <key>}`.
  - `<half-year>/<key>.json` (`2017H2` … `2026H2`, one per half-year in the
    range; `shard` in the script, whose docstring has the layout): that
    half-year's CLs, each [change number and day landed, each less the
    previous CL's; Gerrit's inserted lines; earlier commits on main; the
    landed commit's inserted lines per 3-level directory; and the files
    that drew reviewer threads, each with its inserted lines, threads and
    addressed threads], with directory and file names (today's) listed
    once. Nothing else per CL: no org, no expected values, no per-thread
    data. A file's threads count in its 3-level directory when that is one
    of the CL's, else in the CL's main directory (the commit message, files
    the landed commit didn't change).
- `links/<half-year>/<key>.json` (from 2023H1, loaded when a file's CLs are
  first opened): per CL and file entry, the addressed threads' comment ids,
  oldest first, each with its tone score where scored (`link_file`).

The page computes a person's figures from these, the same way the script
does for the spread of everyone's index: totals, AFR and FI for any period,
and the growth rate, from the rounded rate sums in `peers.json`. `--check
FILE` writes the script's values for 300 people; on 2026-11-14, with this
layout, the page's `buildPerson`, `sums` and `fiOf` matched all 3,475 of
them (FI, CLs, addressed threads and lines per period; the largest FI
difference 0.0005, rounding).

So a half-year's files don't change once it is over, as long as the inputs
don't (labels, mechanical list, identity merge, today's names of moved
paths, and for `links/`, the tone scores): git stores them once. Each run
rewrites the current half-year, `u/` and `peers.json`.

Sizes on 2026-11-14 (6,862 people, 122 stubs), gzipped file by file as git
stores them: 31.8 MB for the 19 half-year folders (32,676 files), 0.7 MB
for `u/`, 66 KB for `peers.json` and 10.3 MB for `links/` (12,615 files):
43 MB in all, 117 MB unpacked. The people part replaces `u/` and every
half-year folder on each run, the links part `links/`.

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
