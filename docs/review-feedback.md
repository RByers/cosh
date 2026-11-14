# Feedback Index: feedback rate and index

`web/feedback-index.html` shows how much review feedback Chromium changes
draw per 100 lines as their authors gain experience, and lets anyone type an
email address to see that person's feedback rate and index against their
peers'. It is
a learning guide, and the page says so at the top: "This analysis is imperfect
and is intended as a learning guide only". The landing page links to it
(since 2026-11-12), and it carries `noindex`.

## Definitions

Both are fixed: the page has no switches for them (the user's call,
2026-11-14).

- **Feedback rate (FR):** addressed reviewer threads per 100 new or changed
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
- **Feedback index (FI):** a person's FR over their peers'. For each CL, the
  addressed threads its peers would have drawn are its lines / 100 × a
  typical rate × factors, and FI = addressed threads / that sum
  (`expected` in the script, `unitExpected` in `web/src/feedback.ts`). What
  the peers are (`NORMS`, picked on the page with three checkboxes):
  - *Experience* (`e`, on by default): the typical rate is `ref_bin`, the
    median FR of people at the CL's experience bin (the opening chart's
    line). Without it, `ref_all`: the median FR of everyone with `MIN_CLS`
    (25) CLs over all of theirs.
  - *Directories* (`d`, on by default): each CL's lines are split over the
    3-level directories its landed commit changed, by inserted lines
    (`unit_fracs`; `cl_dirs` with `dels=False`),
    and each part gets its directory's factor: two levels (`chrome/browser/`),
    else one level, else 1, for directories with `MIN_FACTOR_CLS` (300) CLs'
    worth. A factor is the directory's pooled addressed threads over what
    the typical rate predicts there.
  - *Organization* (`o`, off by default): a factor per org (the CL's, by
    `cosh/orgs.py`), computed the same way on top of the other two; orgs
    with fewer than 300 CLs share one (`*`).

  The factors are pooled by lines, so their level is off: low-feedback
  directories with many lines (configuration, imported third-party code)
  pull the pooled average down, and before rescaling the median person's
  index under experience and directories was 0.85 against 0.97 under
  experience alone. Each factor table is therefore scaled so that the
  median person's index (people with `MIN_CLS` CLs) is the same with the
  factor as without it (`rescale` in `rate_model`); only the factors'
  spread matters. On 2026-11-14 the median index is 0.979 under every norm
  with experience and 1.000 under every norm without it (the experience
  bins' medians are over person-bins, the index over people, so they differ
  slightly).

## What it shows

**The opening card**, "Feedback rate" (no person needed), says nothing of
the index: the FR's definition, then the FR by experience bin (y-axis
"feedback rate"): the median of people's FR in each bin (each
person's CLs in that bin pooled, with `MIN_BIN_CLS` = 5 or more there), with
the middle half and the 10th–90th percentile shaded (`fr_bins`). On
2026-11-14: 5.40 at 8, 4.11, 3.52, 2.86, 2.49, 2.00, 1.64, 1.28, 1.04 and
0.80 at >2k, from 3,379 people in the first bin down to 71 in the last.
(With deletions counted they were 3.95 down to 0.43; with 5, 3 or 8 CLs as
the minimum those medians moved by at most 0.15.) Below it,
"Distribution of feedback rate change with experience": the growth rates'
distribution, smoothed (a Gaussian kernel of 0.12 in log2 on a grid from
−75% to +183%, `growth_dist`), with the median and, when a person is shown,
their own growth marked.

The FR falls as much as the old index did, though the chart may look
flatter: the old addressed index adjusted for size and directory fell 5.3×
from <10 to 1,000+ earlier commits (2.36 → 0.44), the median FR 5.2× from 8
to 2k CLs (5.40 → 1.04) and 6.7× to >2k (6.7× and 9× with deletions
counted). The bands make the difference: the
y-axis has to reach the 90th percentile (14.3 in the first bin), so the
median line sits in the bottom third, where the old chart drew medians only
on an axis to about 2.6.

**The second card**, "Feedback index": its definition, and everyone's index
(`fi_dist`: people with `MIN_CLS` CLs, over all the data, under
experience and directories, `FI_NORM`), smoothed on a log2 grid from 1/8
to 5.7 (kernel 0.15), with the median and the 10th and 90th percentiles
marked. On 2026-11-14: 2,808 people, quartiles 0.67 and 1.39, 10th–90th
percentile 0.43–1.91.

**Your feedback** (after an address is found), one section each:

- *Your feedback index:* the checkboxes (experience, directories,
  organization), tiles for changes landed (and their lines), addressed
  threads, FR, FI (with the share of everyone with `MIN_CLS` CLs whose
  index is lower, from `fi[norm].all`) and the growth rate (below), then
  the FI per half-year against the 10th–90th percentile, middle half and
  median of everyone's index that half-year (`fi[norm][half]`). Dots with
  fewer than `MIN_CLS` CLs are hollow. Selecting a dot filters the
  comments-per-change chart, the directory tree and the comments to that
  half-year, as before.
- *How your feedback rate compares to your peers:* the opening chart in grey
  with the person's FR per bin in colour (hollow under `MIN_BIN_CLS`), and
  a table per bin with CLs: CLs, lines, addressed threads, the person's FR,
  the median FR there, the FI over those CLs (shaded, only with
  `MIN_BIN_CLS` CLs), and the change in FR from the bin before (where both
  have `MIN_BIN_CLS`). The last row is all CLs, with the growth rate.
- *Growth rate:* the % change in FR per doubling of changes landed, from a
  least-squares line through log2 FR by bin, each bin weighted by its CLs,
  over bins with `MIN_BIN_CLS` CLs, needing `MIN_GROWTH_BINS` (3) of them;
  FRs under `FR_FLOOR` (0.1) count as 0.1 (`growth`). On 2026-11-14 2,517
  people have one: median −18.8%, 10th percentile −44.6%, 90th +21.1%
  (−20.9%, −47.4% and +22.7% with deletions counted).
- *Addressed comments per change:* the histogram of the person's CLs by
  addressed threads (0, 1–2, 3–5, 6–10, 11–20, 21+), whose columns filter
  the directories and comments.
- *Where your feedback comes from:* the directory tree as before (top level
  first, "Other" for entries under `MIN_CLS` CLs, any directory opens), with
  CLs, lines (each CL's lines × its fraction there), addressed threads, FR,
  FI under the chosen norm (shaded green below 1, red above, saturating at
  0.25× and 4×) and earlier commits. Rows under `MIN_CLS` CLs show no FR or
  FI.
- *The comments:* the addressed threads only, newest first, with the
  directory, half-year and column filters as before.

**Methodology and details** is a collapsed `<details>` at the bottom whose
charts are drawn when it opens:

- *How it's changing:* the FR over newcomers' first 10 CLs
  (`NEWCOMER_CLS`), by year of first commit on `main` from
  2018 (people with `MIN_BIN_CLS` such CLs): median and middle half. On
  2026-11-14 the medians run 3.73, 4.31, 4.21, 3.75, 4.05, 4.21, 4.31, 3.64
  for 2018–2025 and 2.78 for 2026 (not over).
- *By change size:* two bar charts per size bucket (`size10`): the median
  person's addressed threads per CL (0.10 under 4 lines → 9.58 at 512–1k on
  2026-11-14) and their FR (5.54 → 1.40, 0.21 at 1k+). Per line the
  difference is much smaller, which is why the FR counts per line. A person
  counts in a bar with `MIN_CELL_CLS` (10) CLs there; a bar needs
  `MIN_PEERS` people.
- *By directory* and *by organization:* the median person's FR over their
  CLs whose main directory (two levels) is in each of the `CHART_DIRS` (12)
  directories with the most people, and over their CLs from each of the
  `CHART_ORGS` (10) orgs with the most people, highest first. On 2026-11-14
  code directories run 1.2–3.3 (components/autofill/ 3.29, chrome/browser/
  2.61, third_party/blink/ 1.80) while configuration directories draw
  almost none (testing/buildbot/ 0.16, (root)/ 0.15). Org factors with
  experience run 0.35–1.75 for orgs with 300+ CLs (google.com 1.01,
  microsoft.com 0.88, igalia.com 0.86), against 0.38–3.25 without it, so
  orgs differ partly through their contributors' experience.
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
(`sentiment.html#person=<address>`). The comment list flags praise comments
(scored glowing, ≥ +0.4, in the tone year).

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
  changes, 49% at 2k+), so part of the fall of FR with experience was
  deletions: the drop from <8 to 2k+ is ×6.8 with insertions, ×9.2 with
  both.
- With insertions the 2023–24 size norms explain more of the CL-to-CL
  spread (R² 0.20 against 0.14 for addressed threads), and the spread of
  people's FI narrows a little (10th–90th percentile 0.43–1.91 against
  0.38–1.94 under experience and directories).

A dashboard on deletion over time is an idea in `docs/plan.md` (Next
steps 9).

## Ground rules

- **Tone is praise only** (`docs/plan.md`, ground rule 5). Nothing written
  marks a comment, a person or a group as negative: comments carry an
  addressed flag and a praise flag, never a score. Orgs get no tone figures.
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

Offline, about 2 minutes (119 s on 2026-11-14) and 3 GB:

```
COSH_DATA_DIR=<main>/data/private nice -n 5 python3 -m cosh.review_feedback [--out DIR]
```

It reads only `reviews.sqlite`, `commits.sqlite`, `addressed.sqlite`, the
sentiment files and config, never `balance*.sqlite`, so refreshing the page
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
site), with `<key>` the hash of the person's address:

- `peers.json` (version 5, about 44 KB): the experience bins (`bins`,
  `bin_edges`), the index's typical rates and factors (`ref_bin`,
  `ref_all`, `f_dir`, `f_org`), the spread of FR per bin (`fr_bins`) and of
  everyone's index per norm and period (`fi`), and the methodology's data
  (`newcomers`, `growth`, `by_size`, `by_dir`, `by_org`), with the
  minimums the page names. It still carries the tone peers' shares, which
  nothing shows.
- `u/<key>.json`: first commit, which half-years the person has files for,
  and praise received. Small (0.8 MB gzipped for everyone) and rewritten on
  every run. Each other address of the person is a stub `{"see": <key>}`.
- `<half-year>/<key>.json` (`2017H2` … `2026H2` on 2026-11-12, one per
  half-year in the range): that half-year's CLs, with
  their directory splits, threads and excerpts, and the directory, file and
  org names listed once (`shard` in the script, whose docstring has the
  layout). Half-years before 2025H2 have thread counts per directory instead
  of each thread (`"counts": 1`; see "Slimmed before publishing" below).

The page computes a person's figures from these, the same way the script
does for the spread of everyone's index: totals, FR and FI under every norm
for any period, and the growth rate, with the rounded typical rates and
factors from `peers.json`. `--check FILE` writes the script's values for 300
people; on 2026-11-14, after deletions were dropped, the page's
`buildPerson`, `sums` and `fiOf` matched all 38,225 of them (FI under every
norm, CLs, addressed threads and lines; the largest difference 0.0005,
rounding).

So a half-year's files don't change once it is over, as long as the inputs
don't (the 2023–24 norms, still written though unused, labels, mechanical
list, identity merge and collected comment text): git stores them once. Each run rewrites the
current half-year, `u/` and `peers.json`.

Sizes on 2026-11-12 (6,902 people, 122 stubs, 40,023 files), gzipped file
by file as git stores them: 27.4 MB for the 16 half-years 2017 H2 – 2025 H1
(about 1.7 MB each), 4.3 MB for 2025 H2, 10.7 and 9.3 MB for 2026 H1 and H2
(those have the excerpts), 1.5 MB for `u/` and `peers.json`: 53 MB in all,
126 MB unpacked. The script replaces
`u/` and every half-year folder on each run.

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
- The typical rates cover all the data (2017–2026). If Chromium's feedback
  per line drifts over the years, a half-year's index drifts with it; the
  over-time chart shows everyone's median index per half-year, so a drift
  is visible there.
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
