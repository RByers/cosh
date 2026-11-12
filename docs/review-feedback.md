# Review Feedback: a personal view of the feedback index

`web/review-feedback.html` lets anyone type an email address and study the
review feedback on that person's Chromium changes against their peers'. It is
a learning guide, and the page says so at the top: "This analysis is imperfect
and is intended as a learning guide only". It isn't linked from the landing
page yet, and it carries `noindex`.

## What it shows

The page opens with the switches (feedback, adjusted for, same tenure by,
peers), then a card that explains the feedback index before anyone types an
address, then the address field. The sections about a person appear only
once an address is found.

**The opening card** (`renderIntro`, data in `peers.json`) follows the
feedback and adjustment switches; "Peers" picks its population (a half-year
counts by its org, a person's change by the org of most of their
half-years), and tenure by directory experience shows the values against
that experience. Its axis is always years. It shows:

- *Cohort curves:* per year of first commit on `main`, the median of
  people's per-half-year values (counted half-years only: 6+ CLs, 3+
  expected threads) by tenure, in half-year bins, where 20+ people share a
  point. Every line starts at tenure 0: the page draws the years from 2018
  (`cohort_from`) whose curve begins at 0 with 3+ points, every other one when
  there are more than five (`cohortYears`), so 2018, 2020, 2022 and 2024 for
  all threads. For those, the script also counts the merged, human-owned
  CLs on `main` from 2018 to June 2023 in `derived.sqlite` (about 494k),
  against the same 2023–24 norms; older CLs leave out only those with 100+
  files (`mech.jsonl` covers 2023 on). Addressed labels and directory
  experience exist only from the data's start (July 2023), so with those the lines start in
  2023. On 2026-11-12 the curves line up: 2.2–2.5× in the first half-year
  for every start year from 2018 to 2024 (size and directory, all threads).
- *Year-over-year change:* every contributor-year (`yearly_changes`): for
  each person and pair of consecutive calendar years in which they landed
  12+ changes with 6+ expected threads (twice the half-year minimums), the
  change in their value from one year to the next (values under 0.05 count
  as 0.05), as a histogram of % less feedback. All reviewer threads use every
  CL from 2018 (older ones as for the cohort curves). Addressed threads and
  directory experience use whole years from their start (2024 on), with the
  same values as the person's sections. A pair counts for an org group by
  the later year's org. On 2026-11-12: 6,849 changes from 2,020 people,
  median 17% less feedback a year. The spread is mostly noise: splitting
  person-years' CLs at random in two shows a year's value varies by about
  ±58% at 12–17 CLs, ±38% at 25–34, ±27% at 50–74 and ±16% at 150+, and a
  year-over-year change by about 1.4 times that.

For the person's sections below:

For merged, human-owned, non-mechanical CLs on `main` (the same CLs as the
Review Balance page's feedback index, `docs/balance.md` section 4;
mechanical CLs from `mech.jsonl`), over whatever dates the data covers.
**Reviewer threads** are threads not started by a bot, on a file or the
commit message. Patch-set-level threads (general comments) aren't counted:
Gerrit has recorded them as threads only since July 2020, they can't be tied
to a directory, and only 5% are addressed (against about 80% of the others;
they were 29% of all threads but 2.6% of addressed ones, 2026-11-12). So the
figures differ from the Balance page's index, which counts them.

- **Dates come from the data**, never from the code. The range runs from
  the oldest week in `derived.sqlite`'s `fetched_weeks` (but no earlier than
  the oldest CL in `balance.sqlite`, which lags an older backfill until
  `cosh.balance` is rerun) to the end of the newest. A range that spills a
  week or less into a month is trimmed to the month, so the page can name
  periods by month without slivers: Monday 2023-06-26 .. Sunday 2026-11-01
  becomes 2023-07-01 .. 2026-10-31. `peers.json` gives the page `start`,
  `end` (exclusive) and `addr_start` as day numbers, and the page's prose and
  half-year names come from them. There is no date selector: every figure
  covers all of it (the user's call, 2026-11-11), and only the over-time
  chart splits it, by half-year. So the script computes peers for
  everything and for each half-year, not per calendar year.
- **The addressed measures** count only the CLs from `addr_start`: the first
  week from which every week's CLs have an addressed label for at least 95%
  of the threads that need one (the owner replied, and no "Done"-style regex
  match), trimmed to the month like the range. Before it, those CLs count
  for neither the person, their peers nor the opening card (`ok_a` and `acls` in the person's
  values), and the page lists only the periods it covers while "addressed"
  is selected. Labels are near complete from 2022-W06 (2026-11-11) and
  absent before 2021-W52; the user doesn't want them for older years. The
  script warns if 2023–24, the norms' reference years, isn't covered.

The measures:

- **The measure**, from three switches:
  - *Feedback:* every reviewer thread (a thread started by a human other than
    the owner), or only the threads the owner **addressed** (regex plus the
    Haiku labels in `labels.sqlite`, `docs/comment-classifier.md`).
  - *Adjusted for:* nothing (threads per CL), CL size (÷ the 2023–24 mean for
    the CL's size bucket, 10 log buckets), or size and directory (÷ the
    2023–24 mean for size × top 2-level directory, groups of 30+, else size
    alone), computed the same way as `balance_growth.cl_residuals` but from
    this page's thread counts.
- **Peers always have the same tenure**, because feedback falls steeply with
  it (about 1.7× under a year or under 50 earlier commits, against 0.6× at
  10+ years or 1,000+). Two selectors pick the group:
  - *Same tenure by:* years since the first commit on `main` (under 1, 1–2,
    2–5, 5–10, 10+); earlier commits on `main` (from 2017, reverts left out:
    under 50, 50–199, 200–499, 500–999, 1,000+); or **experience in each
    directory** (below). The band is taken at the median of the person's CLs
    in the period, so the over-time chart follows the person from band to
    band.
  - *Peers:* all authors, Google, or everyone outside Google (the org most
    of the period's CLs are attributed to, `cosh/orgs.py`).

  peers.json has a distribution per period, measure and group:
  `time:<band>:<org>`, `changes:<band>:<org>` and `dir:<org>`. A person
  counts among peers for a period with 6+ CLs and 3+ expected threads; a
  group of fewer than 10 (`min_peers`) gets no percentiles, which happens to
  most non-Google groups past 200 earlier commits. The page shows the peers'
  median and middle half and the share of peers with less feedback.
- **Directory experience.** Each CL is split over the 3-level directories its
  landed commit changed (`cl_dirs`, weighted by lines + files), and each
  reviewer thread goes to the directory of its file (commit-message threads,
  and files outside those directories, go to the CL's main directory). Experience is the owner's earlier commits on `main` touching that
  directory (from 2017, `balance-git.sqlite`), banded 0, 1–4, 5–19, 20–99,
  100+. Everyone's feedback is pooled per band; the "same experience" view
  divides a person's threads by the sum, over their CL-directory pieces, of
  expected threads × that band's pooled rate relative to everyone's. So 1.00×
  is typical *for the experience the person had in the directories they
  worked in*, which credits people who work across more of the codebase. A
  chart and table give the person's feedback per band against everyone's.
- **Directories**: CLs, threads, expected threads, their ratio and earlier
  commits per directory, as an expandable tree like Value Exchange's
  directory chart: top-level directories first, opening down to the 3-level
  ones (a parent counts each CL once; earlier commits is the most in any one
  directory below it). The ratio cell is shaded red below 1, white at 1 and
  green above, on a log scale that saturates at 0.25× and 4×. Selecting a
  directory at any level filters the comment list to it and below, together
  with the page's all/addressed choice.
- **Half-year filter**: selecting one of the person's dots in the over-time
  chart filters the directory tree and the comments to the CLs landed in
  that half-year (the threads behind that point), together with any
  directory filter. A named filter line with a Clear button appears above
  both the tree and the comments, and the dot gets a ring for as long as
  the filter is on. Selecting the same dot again also clears it, as does
  looking up someone else or switching to a measure with no changes in that
  half-year.
- **Comments**: every reviewer thread, newest first, with file, date and
  addressed or not. Threads whose text has been collected (every week in
  `data/private/sentiment/comments-*.jsonl`, 2025-W45 on today) get a
  200-character excerpt and a link to the comment itself; the others get
  neither, and link to their CL (their comment ids would be 29% of the data,
  2026-11-11).
- **Praise** has no section here: after a lookup, "See also your praise"
  links to the Review Tone page's popup for the address
  (`sentiment.html#person=<address>`), which matches it in any case and
  across chromium.org and google.com (`resolveEmail` in `web/src/tone.ts`).
  The address is in the link's fragment, so it never reaches a server. The
  comment list still flags praise comments (scored glowing, ≥ +0.4, in the
  tone year) and can show only those. The script still writes the person's
  tone counts and the tone peers' shares, which nothing shows now.

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

Offline, about 2 minutes and 3 GB:

```
I=<dir with first_commit.txt and mech.jsonl, as for scripts/balance_report.py>
COSH_DATA_DIR=<main>/data/private nice -n 5 python3 scripts/review_feedback.py \
    --first-commit $I/first_commit.txt --mech $I/mech.jsonl [--out DIR]
```

To take in an older backfill (back to 2017-07), let it finish, then run a
full `derive` and `python3 -m cosh.balance git|timeline|interdiff|cl`, then
this script: nothing in it names a date.

Output (default `web/public/review-feedback/`, which Vite copies into the
site), with `<key>` the hash of the person's address:

- `peers.json`: every peer group's quantiles per period and measure, and of
  its changes landed and reviewer threads (`counts`; labelled changes and
  addressed threads for the addressed measures), and
  everyone's pooled feedback per directory-experience band, and the opening
  card's cohort curves (`cohorts`) and yearly-change histogram (`change`).
- `u/<key>.json`: first commit, which half-years the person has files for,
  and praise received. Small (0.8 MB gzipped for everyone) and rewritten on
  every run. Each other address of the person is a stub `{"see": <key>}`.
- `<half-year>/<key>.json` (`2023H2` … `2026H2` on 2026-11-11, one per
  half-year in the range): that half-year's CLs, with
  their directory splits, threads and excerpts, and the directory, file and
  org names listed once (`shard` in the script).

The page computes everything else from these, the same way the script does
for the peer groups: totals for any period, tenure, org, whether the person
counts among peers, the measures, and the same-experience measure (from
`peers.json`'s rounded `rel` per band). To keep the two in step, the script
rounds the norms and line shares where it computes them, and counts tenure
in whole days. `--check FILE` writes the script's values for 300 people;
on 2026-11-11 the page's matched all 54,126 of them to the last digit.

So a half-year's files don't change once it is over, as long as the inputs
don't (the 2023–24 norms, labels, mechanical list, identity merge and
collected comment text): git stores them once. Each run rewrites the
current half-year, `u/` and `peers.json`.

Sizes on 2026-11-11 (4,009 people, 64 stubs), gzipped file by file as git
stores them: 2.6–2.9 MB per half-year for 2023 H2 – 2025 H1, 4.8 MB for 2025
H2, 12.5 and 10.7 MB for 2026 H1 and H2 (those have the excerpts), 0.9 MB for
`u/` and `peers.json`: 40 MB in all, 110 MB unpacked. The script replaces
`u/` and every half-year folder on each run.

**Not committed yet.** `web/public/review-feedback/` is gitignored, so
publishing it on GitHub Pages waits for the user's decision. Until then the
page works wherever the folder has been generated (`npm run serve` in the
main checkout), and the browser tests serve a made-up person
(`web/test/feedback-fixture.ts`). The inputs used on 2026-11-11 are kept in
`data/private/review_feedback_inputs/`.

## Caveats

- Tenure in years counts from the first commit on `main`; earlier commits,
  on `main` or in a directory, count only from 2017, so people who were
  active before then are undercounted (most are in the top band anyway).
- Reviewer threads include any thread a non-owner started, including
  drive-by and gardening comments, as the feedback index does.
- Peer groups mix very different roles, teams and kinds of work. A high or
  low figure is a prompt to look at the comments, not a conclusion.
