# Feedback Index: drift of feedback rates over time

The question (2026-11-14): the index compares each change with its peers'
pooled AFR in the same directory and experience bin over **all** the data,
2017-07 .. 2026-10. If a directory drew little feedback in 2017–2024 and
then got new OWNERS who review more strictly from 2025, someone who landed
many changes there in 2025–26 gets a high index for something that isn't
theirs. How big is that bias, and can we correct it within the goals in
`docs/goals.md`?

Short answer: the bias is real and larger than the directory example
suggests, mostly because all of Chromium drew about a quarter less
feedback per line in 2026. Comparing each change with peer rates from the
**same half-year**, with the person's own changes left out of their peers'
rates, removes it, makes the index more reliable on both tests below, and
costs no tokens, no per-person files and about 50 KB more in `peers.json`.
Not built yet.

## How it was measured

Every number below comes from the published files
(`web/public/review-feedback/`, 2026-11-14): 872,196 CLs rebuilt from the
half-year files (lines, experience bin, directory shares and addressed
threads per directory), with the index's rules (`MIN_RATE_CLS` 200,
fallback to the parent directory, median person scaled to 1, people with
`MIN_CLS` 25 CLs). The rebuild reproduces the published index: 2,808
people, 10th–90th percentile 0.42–1.96. Scripts:
`data/private/scratch/feedback-drift/` (`load_rows.py`, then `drift.py`,
`lso.py` and `lso2.py`, `why2026.py`, `size.py` and `size2.py`; outputs in `*.out`).

## How big the drift is

**Chromium-wide.** Addressed threads over what the all-time rates expect
(directory and experience), per year:

| 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|---|
| 0.98 | 0.96 | 0.92 | 1.02 | 1.07 | 0.94 | 1.00 | 1.02 | 0.95 | 0.74 |

Within ±8% until 2025, then 26% below in 2026. Changes got bigger (median
36 inserted lines in 2026, 24–27 every year before) and draw less feedback
at the same size (64–255 lines: 3.4–3.8 addressed threads per CL in
2017–22, 2.9 in 2025, 2.2 in 2026). Under the current rates everyone's
median index per half-year runs 1.0–1.16 until 2025H1, then 0.97, 0.94 and
0.78 for 2026H2.

**Per directory**, beyond the Chromium-wide drift (directory-years with
200+ CLs, by share of lines; the factor is the directory-year's addressed
threads over what the all-time rates expect, divided by Chromium's factor
that year):

| | within 0.8–1.25× | 0.67–1.5× | beyond |
|---|---|---|---|
| 1-level directories | 78% | 13% | 8% |
| 2-level | 80% | 11% | 10% |
| 3-level | 67% | 19% | 14% |

The scenario in the question happens. Among the 35 three-level directories
with 500+ CLs both in 2017–22 and in 2025–26, the factor rose 2.4× in
`net/http/`, 1.7× in `infra/config/generated/`, 1.6× in
`third_party/blink/web_tests/` and 1.2× in `third_party/blink/renderer/`,
and fell to 0.56× in `components/password_manager/core/` and 0.66× in
`chrome/browser/ui/` (median 0.86, 10th–90th percentile 0.66–1.46).

**Effect on people.** For the 606 people with 25+ CLs who landed at least
half of them in 2025–26, the index under per-half-year rates (option G
below) over the index now: median 1.15, 10th percentile 0.79, 90th 1.66.
So the current index understates the typical recent contributor by about
13%, mostly through 2026, while for one in ten it overstates them by a
quarter or more, as in the question.

## Options

All are offline: none costs tokens (goal 4). "Moved" compares with the
index now (people with 25+ CLs). Reliability: rank correlation of each
person's index from their odd and even CLs, and from the older and newer
half of their CLs (goal 1, `docs/goals.md`).

| | option | odd/even | early/late | Spearman with now | moved >20% |
|---|---|---|---|---|---|
| A | all-time rates (now) | 0.748 | 0.522 | – | – |
| B | A, each person left out of their own peers' rates | 0.757 | 0.528 | 0.997 | 2% |
| C | A × Chromium's factor per year | 0.742 | 0.522 | 0.990 | 7% |
| D | A × directory factor per year (shrunk toward the parent) | 0.696 | 0.499 | 0.906 | 33% |
| E | A × directory factor over the 2 years before each CL | 0.706 | 0.480 | 0.937 | 22% |
| F | rates per directory, experience and year | 0.759 | 0.540 | 0.898 | 29% |
| F′ | F, person left out | 0.769 | 0.545 | 0.897 | 30% |
| G | **rates per directory, experience and half-year, person left out** | **0.776** | **0.555** | 0.882 | 34% |
| H | rates per 2 years, person left out | 0.758 | 0.530 | 0.915 | 25% |

What they show:

- **Including the person in their own peers' rates hurts** (B, D). In a
  directory one person dominates, their own changes set the norm, so the
  index pulls them toward 1. D, a correction factor per directory and
  year, is worst on reliability because a directory-year is small enough
  for that to matter a lot. Leaving the person out helps every variant a
  little.
- **Chromium-wide correction alone (C) changes little** for ranks: it
  shifts recent work up about 10% but doesn't touch directory drift.
- **Looking back (E) lags.** A trailing window still expects 2025's rates
  in 2026, so it corrects little of the 2026 drop and is less reliable
  than now.
- **Finer time is better, down to half-years** (H < F′ < G). Narrower
  periods leave fewer cells with 200 CLs' worth (55–88 directories per
  half-year at 1, 2 or 3 levels, against 712 over all the data), so more
  lines take a parent directory's rate, but the gain from comparing within
  the same period outweighs that. Months or quarters weren't tried: cells would
  thin out much further.
- The early/late gain matters most for the goal: a drift that differs
  between a person's older and newer changes lowers that correlation, so
  removing it should raise it, and G raises it most (0.522 → 0.555).
  Odd/even rising too says the finer comparison removes noise rather than
  signal; a bias shared by a person's odd and even CLs would, if anything,
  have propped up the old figure.

## Option G against the goals

**Goal 1 (accuracy).** The most reliable on both tests, and it means what
readers expect: "compared with people working in the same directory, at
the same experience, in the same half-year". About a third of people with
25+ CLs move by more than 20% (13% by more than 50%), a one-time break
the page should note. What changes in meaning:

- Everyone's median index per half-year sits near 1 by construction, so
  the index no longer shows Chromium-wide shifts like 2026's. The AFR
  charts (absolute) do, and the page should say so where the index over
  time is drawn.
- A person's index across half-years compares them with each half-year's
  peers. Improvement shows as rising relative to peers, which is what the
  index is for; whether all of Chromium improved is the AFR's job.

**Goal 2 (weekly update).** A finished half-year's rates don't change, so
past figures stay put; only the current half-year's rates move each week,
as its per-person files already do. In the first weeks of a half-year its
cells are thin and fall back to parent directories and to the half-year's
Chromium-wide rate, so early figures are noisier. A fix if that shows: let
the current half-year's rates cover the last 26 weeks until it has 13
weeks of its own. Run time barely changes.

**Goal 3 (repository volume).** Per-person files don't change: the rates
live in `peers.json`, which the page loads on opening. Leaving the person
out needs each cell's sums ([CLs' worth, lines, addressed threads])
instead of a rate, so the page can subtract the person's own changes
(which it already loads, every half-year). The sums for all 19
half-years measured 153 KB, 39 KB gzipped (the all-time rates now: 59 KB,
11 KB gzipped), so `peers.json` grows from 59 to about 90 KB gzipped,
rewritten weekly. If that
weekly churn matters, finished half-years' rates can move to frozen files
(`rates/<half>.json`) that git stores once. The change itself rewrites only
`peers.json`, not the 35 MB of half-year files.

**Goal 4 (tokens).** None: rates are computed from labels already paid
for.

**Cost to build.** `rate_model` and `peer_rate` take a period key (the
CL's half-year) and keep sums; the script and `web/src/feedback.ts`
subtract the person's own cell sums before the 200-CL test (the script for
everyone's spread, the page for the person shown); the scales are
recomputed as now; the `--check` comparison must match again; the directory
table's "peers' AFR" tooltip already sums expected threads, so it works
unchanged. `docs/review-feedback.md` and `config/dataflow.json`
(`peers.json`'s size) change with it.

## Not tried

- Shrinking each half-year's rate toward the directory's all-time rate
  instead of falling back to the parent directory.
- Smoothing over time (a kernel over neighbouring half-years) instead of
  hard half-year cells.
- Months or quarters (cells too thin at 200 CLs' worth).
