# Review Feedback: a personal view of the feedback index

`web/feedback-index.html` lets anyone type an email address and study the
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
  people's per-half-year values (half-years with 6+ CLs and 3+ expected
  threads, `MIN_COHORT_CLS`: lower than the peer minimum, because noise
  barely moves a median and a higher bar would keep only the most prolific
  newcomers in the early points) by tenure, in half-year bins, where 20+ people share a
  point. Every line starts at tenure 0: the page draws the years from 2018
  (`cohort_from`) whose curve begins at 0 with 3+ points, every other one when
  there are more than five, always keeping the newest (`cohortYears`), so
  2018, 2020, 2022, 2024 and 2025 for all threads. For those, the script also counts the merged, human-owned
  CLs on `main` from 2018 to June 2023 in `derived.sqlite` (about 494k),
  against the same 2023–24 norms; older CLs leave out only those with 100+
  files (`mech.jsonl` covers 2023 on). Addressed labels and directory
  experience exist only from the data's start (July 2023), so with those the lines start in
  2023. On 2026-11-12 the curves line up: 2.2–2.5× in the first half-year
  for every start year from 2018 to 2024 (size and directory, all threads).
- *Year-over-year change:* every contributor-year (`yearly_changes`): for
  each person and pair of consecutive calendar years in which they landed
  25+ changes with 12+ expected threads (the peer minimum, below), the ratio
  of the later year's value to the earlier's (values under 0.05 count as
  0.05). Bins are equal steps of ×2^(1/3) on a ratio scale (÷2.52 … ×2.52,
  so halved and doubled are edges). Linear % bins (the first version) put
  every rise above 30% in one open-ended bin while the same span of falls
  was split over five, so noise piled up in "grew 30%+" (16–20% of all
  values). All reviewer threads use every CL from 2018 (older ones as for
  the cohort curves). Addressed threads and directory experience use whole
  years from their start (2024 on), with the same values as the person's
  sections. A pair counts for an org group by the later year's org. On
  2026-11-12: 5,240 changes from 1,561 people, median 16% less feedback a
  year (21% for addressed threads); bins 7, 8, 13, 17, 19 | 16, 9, 6, 3, 3%.
  The spread is mostly noise: splitting person-years' CLs at random in two
  shows a year's value varies by about ±58% at 12–17 CLs, ±38% at 25–34,
  ±27% at 50–74 and ±16% at 150+, and a year-over-year change by about 1.4
  times that.
- *All or addressed feedback, by tenure* (`kinds`, `kind_share`): like the
  Balance page's "Feedback by tenure, acted on or not", two lines: the
  median of all reviewer threads and of addressed ones, over the same
  person-half-years (those with `MIN_COHORT_CLS` CLs, all labelled, from
  `addr_start`), in the Balance page's tenure bins (0–3, 3–6, 6–12 months,
  1–2, 2–5, 5–10, 10+ years), with each line's 2023–24 norm dashed. The
  feedback switch doesn't apply; adjustment and "Peers" do. On 2026-11-12
  (size and directory, all authors, 10,687 half-years): all threads 1.92× →
  0.55× (3.5 times less), addressed 2.03× → 0.49× (4.1 times less), and the
  share of threads addressed falls from 84% to 74%. Addressed falls more
  steeply under every adjustment and org (outside Google 2.1 against 2.5
  times), which is what the page says makes it the better sign of growth;
  the sentence flips if the data ever says otherwise.
  The gap is narrower than on the Balance page (all 3.6, acted on 5.1
  times), mostly because this page leaves out general comments: they are
  rarely addressed and barely fall with tenure, so counting them flattens
  the all-threads line, while the addressed line hardly moves. A scratch
  probe on 2026-11-12 (fall from 0–3 months to 10+ years, all / addressed):
  this chart 3.5 / 4.1; with general comments 2.8 / 4.1; pooled per CL
  over 2023 H2–2024 without them 4.5 / 5.1, and with them 3.6 / 5.1
  (66% → 45% addressed), which reproduces the Balance chart. Pooling
  instead of medians makes both lines steeper, and the period matters
  little. This chart and the next sit side by side (`.rf-pair`), each
  with its own note.
- *Which tenure explains the fall* (`tenure_cmp`): for each tenure measure
  (years, earlier commits on `main`, directory experience), everyone's
  pooled feedback per band against all five bands together, each CL placed
  by its own band when it landed (directory experience per CL-directory
  piece, as in the person's sections), drawn on one axis of five bands. Its
  test of which measure accounts for growth: each person-year's value is
  also computed against the pooled rate of the same years band and the same
  changes band (`xt`, `xc` in `person_period`, like `x` for directories),
  and `matched_changes` takes the median year-over-year change of each over
  the same pairs of years (as in the histogram). The page names the measure
  that leaves the change closest to zero (`bestTenure`). On 2026-11-12, all
  threads, size and directory: unmatched −16.2% a year (5,246 pairs from
  1,565 people), −5.9% against the same years, −11.3% against directory
  experience, −0.6% against changes landed (96% of the fall explained);
  addressed −18.1%, −9.0%, −14.4%, −4.2%. Bands first to last: 3.6, 4.6 and
  2.7 times less. Outside Google (109 people) years come out closest
  (−0.4%; changes landed overshoots to +4.9%).
- *By change size* and *by directory*, two half-width bar charts
  (`median_breakdowns`; `by_size`, `dir_names`, `by_dir` in `peers.json`):
  the median contributor's value for the chosen measure and "Peers" org
  (tenure not matched), over every CL in range. By size: each person's CLs
  in one size bucket. By directory: each person's line share of their CLs
  in the directory and the threads on its files (as in the person's
  directory table). A person counts in a bar with 10+ CLs there and 3+
  expected threads (size and directory norm); a bar needs 10 people. The
  directories: first-level ones, those with over 10% of all reviewer
  threads split into their second level (chrome/, third_party/ and
  components/ on 2026-11-12), the 10 with the most threads; the page sorts
  them by value. On 2026-11-12, all threads, per change: <4 lines 0.09 →
  512–1,023 6.25 → 1,024+ 4.4; adjusted for size and directory 0.56–0.86
  (medians sit below the 1.00 average, since a few heavily reviewed people
  pull the mean up). By directory, per change: components/autofill/ 4.19
  down to tools/ 1.05; adjusted: third_party/blink/ 1.05 down to
  chrome/test/ 0.59.
  An earlier chart (2026-11-12) compared ways of measuring by size: per
  1,000 changed lines the index runs 4.74 (<4 lines) → 0.20 (1,024+), so a
  per-line rate would favour big CLs about as strongly as a per-CL rate
  favours small ones; the bucket norms take the curve as it is.

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
    this page's thread counts. Size is changed lines (insertions plus
    deletions), in `balance_growth.size10`'s buckets: <4, 4–7, …, 1,024+.
    There is no directory-only choice: on 2026-11-11 the script's `norm fit`
    line gave R² 0.152 for the size norm, 0.034 for a directory-only norm and
    0.191 for size and directory (2023–24 CLs, all threads; addressed
    0.137 / 0.032 / 0.174). Directory adds a little on top of size, but alone
    it leaves almost all of the size effect in.
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
  counts among peers for a period with 25+ CLs and 12+ expected threads
  (`MIN_CLS`, the same for a half-year, a year or all the data: a figure's
  noise depends on its number of CLs, about ±38% at 25; on 2026-11-12 that
  is 1,750 people with 96.6% of all CLs over all the data, against 2,554 at
  the earlier minimum of 6); a group of fewer than 10 (`min_peers`) gets no percentiles, which happens to
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
  directory below it). The ratio cell is shaded green below 1, white at 1 and
  red above, on a log scale that saturates at 0.25× and 4×. Selecting a
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
- **Threads per change**, after the directory-experience card: a histogram
  of the person's CLs by how many reviewer threads (addressed ones, with the
  addressed measure) each drew, in columns of 0, 1–2, 3–5, 6–10, 11–20 and
  21+ (over all CLs since July 2023: 56, 23, 10, 6, 3 and 2%; addressed:
  65, 19, 8, 4, 2 and 1%, 2026-11-12), for the selected half-year if there
  is one. Selecting a column filters the directory tree and the
  comments to those CLs, together with the half-year and directory filters,
  with its own filter line and Clear button; selecting it again clears it,
  as does a new half-year or measure that leaves the column empty.
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

The served site (`npm run serve`'s `vite build --watch`) copies `public/`
into `dist/` only when a source file changes, so after a run its pages keep
the old data. Rebuild (`cd web && npx vite build`) or copy the changed files
into `web/dist/review-feedback/`; a page change that needs new `peers.json`
fields draws nothing until then (2026-11-12).

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

## Per-person feedback report (`scripts/feedback_coach.py`)

`python3 scripts/feedback_coach.py <email>` writes a private Markdown report
to `data/private/feedback-coach/<email>.md` (not published, not on the site).
It takes the author's past year (`--days 365`, up to the newest comment in
`derived.sqlite`) of reviewer threads on their own `main` CLs: file and
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
