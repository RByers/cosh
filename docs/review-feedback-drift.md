# Feedback Index: drift of feedback rates over time

The question (2026-11-14): the index compares each change with its peers'
pooled AFR in the same directory and experience bin over **all** the data,
2017-07 .. 2026-10. If a directory drew little feedback in 2017–2024 and
then got new OWNERS who review more strictly from 2025, someone who landed
many changes there in 2025–26 gets a high index for something that isn't
theirs. How big is that bias, and can we correct it within the goals in
`docs/goals.md`?

**Since 2026-11-14 the index compares by reviewer, not directory**
(`docs/review-feedback-reviewers.md`). With reviewers and authors
accounted for, feedback was steady until 2026H1 (0.96–1.07 of expected per
half-year, size-adjusted) and drew 0.81 of expected in 2026H2; the page's
methodology shows it. The study below compared directory-based rates.

Short answer: the drift is real, mostly because all of Chromium drew
about a quarter less feedback per line in 2026, but no time correction we
tried makes the peers' rates better. Judged by how well they predict the
feedback other people's changes drew, rates over all the data beat rates
per half-year, per-directory windows that widen over earlier (or later)
half-years until they have enough changes, and all-time rates times a
Chromium-wide factor per half-year: directory detail matters more than
time, and every narrower period costs directories their own rate. What
did help is leaving each person out of their own peers' rates and
lowering the minimum per directory from 200 to 50 changes' worth. That is
what the index uses since 2026-11-14 (below, "What we built").

A first round of this study, judged by how consistent each person's index
is between halves of their changes, recommended per-half-year rates, and
they were live for a few hours. That test rewards coarser comparisons
(comparing with no directories at all scores highest), so it can't choose
the peer groups; the sections "Options judged by consistency" and "Why
consistency misled" keep that round for the record.

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

## Options judged by consistency (superseded)

All are offline: none costs tokens (goal 5). "Moved" compares with the
index now (people with 25+ CLs). Reliability: rank correlation of each
person's index from their odd and even CLs, and from the older and newer
half of their CLs (goal 2, `docs/goals.md`).

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

## Why consistency misled

Varying only the minimum per directory, per half-year: odd/even 0.776 at
200, 0.782 at 400, 0.784 at 800, 0.786 at 1,600 and 0.787 with no
directories at all; older/newer half 0.555 up to 0.574. Where someone
works is a stable part of their index, so the coarser the comparison, the
more of it the person carries from one half of their changes to the
other. Per-half-year rates looked better partly because only 55–88
directories per half-year have 200 changes' worth (712 over all the
data), so most lines took a parent's rate. Widening each directory's
window backwards, which keeps more directories, looked worse for the same
reason (odd/even 0.767 widening up to a year, 0.754 without limit).

## Judged by prediction

What the index needs from its peers' rates is a good estimate of what
other people's changes draw on the same lines. So each variant predicts
every CL's addressed threads from everyone else's CLs (the owner left
out), scaled by a factor per size bucket (powers of two of inserted
lines; without it, size swamps everything: small CLs drew 2.3× more than
predicted in 2026 and the largest a quarter), and is scored by Poisson
deviance over the 872,196 CLs (lower is better):

| peers' rates | deviance |
|---|---|
| all-time, minimum 50 (built) | **2,819,561** |
| all-time, minimum 25 | 2,820,743 |
| all-time, minimum 100 | 2,833,787 |
| all-time, minimum 200 (before 2026-11-14) | 2,843,113 |
| all-time, minimum 10 | 2,846,445 |
| widen each directory both ways over half-years until 200 | 2,859,702 |
| all-time min 50 × Chromium's factor per half-year | 2,871,139 |
| all-time × Chromium's factor per half-year | 2,891,810 |
| all-time × the 2-level directory's factor per half-year | 2,897,234 |
| widen each directory both ways until 1,000 | 2,898,869 |
| widen each directory back over earlier half-years until 200 | 2,906,493 |
| per half-year, minimum 50 | 2,944,119 |
| widen back until 1,000 | 2,964,440 |
| per half-year, minimum 200 (live for a few hours) | 2,974,124 |

Without the size factor the order is much the same (all-time minimum 50
3.13M, 100 3.18M, 200 3.21M; per half-year 3.51M). Year by year, Chromium's factor per half-year helps in
2026 (351.6k → 339.0k without the size factor) and hurts in every other
year: a factor from pooled lines follows how many big CLs landed, so it
misjudges small ones. A time correction that accounts for size might
help; that is untried.

## Not tried

- Shrinking each half-year's rate toward the directory's all-time rate
  instead of falling back to the parent directory.
- Smoothing over time (a kernel over neighbouring half-years) instead of
  hard half-year cells.
- Months or quarters (cells too thin at 200 CLs' worth).

## What we built (2026-11-14)

All-time rate sums per directory and experience bin in `peers.json`,
with the person's own subtracted before the minimum of 50 (`rate_model`,
`cell_rate` and `peer_rate` in `cosh/review_feedback.py`, `ownCells` and
`peerRate` in `web/src/feedback.ts`; `docs/review-feedback.md`,
Definitions). The per-person files didn't change; `peers.json` is 83 KB
gzipped (59 KB with all-time rates before, 93 KB per half-year), and the
page matched the script's values for 300 people exactly. Quartiles of
everyone's index 0.68 and 1.44, 10th–90th percentile 0.43–1.96;
everyone's median per half-year still shows the drift (0.76 for 2026H2).
Scripts: `data/private/scratch/feedback-drift/` (`widen*.py`,
`minrate.py`, `deviance.py`, `dev2.py` to `dev5.py`, with their `.out`).
