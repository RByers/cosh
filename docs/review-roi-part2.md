# Return on code review, part 2: does review today make later changes easier and safer?

Work package 2 of `docs/review-roi.md` (hypotheses H2a–H2e; H2f and H2g
are separate). Run 2026-11-09. Everything is offline: `balance.sqlite`,
`balance-git.sqlite`, `derived.sqlite` (thread root accounts only, never
comment text), `bugs/bugs.sqlite` and the shared bare Chromium clone
(read-only, `GIT_NO_LAZY_FETCH=1`). Nothing was fetched or downloaded, and
no model was called.

**Summary.** None of the five tests shows review depth making later
changes cheaper or safer in a way that holds up to the checks.

- **H2a**: a directory's review depth doesn't predict its revert rate in
  the next half-year. Two estimates one year ahead are negative, but
  equally large "effects" backwards in time (the placebo) and the quarterly
  version don't support them.
- **H2b**: deeper review in a directory goes with slightly *more* review
  cost in the next period, not less.
- **H2c**: newcomers who drew more addressed feedback in their first year
  still drew more feedback in their second year, and their CLs were
  reverted more. That is who they are and what they work on (selection),
  not evidence of learning or of its absence.
- **H2d**: in the blame pilot, CLs whose lines a later bug fix rewrote had
  *more* review than matched CLs, not less.
- **H2e**: a year after landing, lines from CLs with more feedback survive
  no better than lines from rubber-stamped CLs at equal size and place
  (58% survive overall). The pilot of 300 CLs can't rule out a 5-point
  difference.

The fix-commit links are cheap enough to run in full: about 16–29 CPU
hours for every eligible fix commit since 2024. Survival costs more:
about 170 CPU hours for line survival of every 2024 CL with 20–500 added
lines (53k CLs). This pilot ran on 2 cores, which puts the fix-commit run
at about 8–15 hours of wall time.

## Unit and definitions

- **Unit CL:** merged, human-owned (not a `Bot-Commit`, owner not a bot),
  not a revert or reland (`cl` and `gcommits` flags), not mechanical,
  landed on `main` 2023-07-01 .. 2026-09-30. That's 356,546 CLs.
  Mechanical: `inputs/mech.jsonl` (≥ 100 files, or ≥ 10 files with
  repetition ≥ 0.8; `balance.md` §8). Tenure starts at the first commit
  over all history (`inputs/first_commit.txt`). Both final runs used these
  rules. A first run with the provisional rules (≥ 50 files; first commit
  since 2017) gave the same picture: no estimate changed sign, and only
  two borderline ones crossed the significance line (feedback index →
  threads per 100 lines, +0.12 [+0.01, +0.23] then; addressed → attention
  hours, +2.8 [−0.1, +5.7] then).
- **Main directory:** the 3-level directory with most of the landed
  commit's lines (`cl_dirs`). dir2 is its first two levels.
- **Feedback index:** threads ÷ the 2023–24 mean for the CL's size
  (`balance_growth.size10`, 10 log buckets of Gerrit lines) × dir2, with at
  least 30 CLs per cell, else size alone. Recomputed on the unit CLs.
- **Revert:** `reverted_at` within 30 days of landing.
- **Rubber-stamped:** no reviewer thread at all.
- **Approvers:** `Reviewed-by` on the landed commit, author excluded,
  identities merged as in `balance_growth` (`Ids`, alias pairs).

## H2a / H2b: directory panels (`scripts/review_roi_part2.py`)

**Cells:** dir3 × half-year, with periods t = 2023H2 .. 2026H1 and the
outcome in t+1 (2026H2 is Q3 only). Quarters are the robustness check.
A cell needs at least 30 unit CLs in both periods.

| | Half-years | Quarters |
|---|---:|---:|
| dir3 × period cells | 15,758 | 22,930 |
| … with ≥ 30 CLs | 1,579 | 1,628 |
| (t, t+1) pairs | 1,020 in 293 dirs (235,189 CLs in t) | 1,087 in 213 dirs |
| (t, t+2) pairs | 775 | 908 |
| pairs in the FE fits (dirs with ≥ 2 pairs) | 949 in 222 dirs | 1,032 in 158 dirs |

Cell variables: CLs, lines, mean feedback index, addressed threads per 100
lines, rubber-stamp share, 30-day revert rate, threads per 100 lines, mean
rounds, mean interdiff share, median hours from sent to first review, mean
attention hours per CL, distinct approvers, approver turnover (share of the
period's approvals by people who gave none in that directory the period
before), and the share of CLs by authors under 1 year.

Cell means (half-years, pairs used): 231 CLs, feedback index 0.99,
addressed 1.59 per 100 lines, rubber-stamped 32%, revert rate 2.8%,
threads 2.9 per 100 lines, rounds 1.05, interdiff share 0.40, 6.0 h to
first review, 60 attention hours, 56 approvers, turnover 24%.

**Fits:** outcome(t+k) on depth(t), one exposure at a time, per 1
within-directory SD of the exposure (feedback index 0.22, addressed per
100 lines 0.67, rubber-stamp share 0.067 at half-years). Revert rates are
in percentage points. Columns:

- *raw r*: the Pearson correlation across cells;
- *pooled*: OLS with period dummies and controls, no directory effects;
- *FE*: directory fixed effects (within-transformation) and period
  dummies, with controls log CLs, log lines and the newcomer share;
- *FE + lag*: FE plus the outcome in t.

Standard errors are clustered by directory, with 95% CIs.

Two more checks. A **placebo** regresses the outcome one period *before*
on depth(t) with the same controls: review can't act backwards, so the
placebo shows how much persistence and confounding the forward estimates
carry. The cells' **variance share between directories** shows how much of
each measure is fixed per directory. At half-years it is: feedback index
62%, addressed 65%, rubber-stamp 83%, revert rate 56%, threads per 100
lines 67%, latency 45%, attention 52%.

### H2a: revert rate (percentage points per SD of depth)

Half-years:

| Depth (t) | Horizon | raw r | pooled | FE | FE + lag |
|---|---|---:|---:|---:|---:|
| feedback index | t+1 | +0.01 | −0.05 [−0.24, +0.14] | −0.10 [−0.25, +0.06] | −0.07 [−0.24, +0.09] |
| | t+2 | −0.01 | −0.07 [−0.26, +0.13] | **−0.19 [−0.35, −0.03]** | **−0.16 [−0.33, −0.00]** |
| | placebo t−1 | −0.01 | −0.11 [−0.28, +0.05] | −0.12 [−0.25, +0.02] | −0.10 [−0.23, +0.03] |
| addressed / 100 lines | t+1 | +0.09 | +0.09 [−0.15, +0.33] | −0.00 [−0.17, +0.16] | +0.02 [−0.15, +0.19] |
| | t+2 | +0.03 | −0.00 [−0.20, +0.20] | **−0.24 [−0.42, −0.07]** | **−0.23 [−0.40, −0.05]** |
| | placebo t−1 | +0.07 | +0.04 [−0.15, +0.24] | −0.02 [−0.16, +0.13] | −0.01 [−0.15, +0.13] |
| rubber-stamp share | t+1 | +0.09 | +0.08 [−0.13, +0.30] | +0.02 [−0.13, +0.18] | +0.02 [−0.14, +0.18] |
| | t+2 | +0.07 | +0.04 [−0.21, +0.28] | −0.01 [−0.20, +0.17] | −0.04 [−0.23, +0.16] |
| | placebo t−1 | +0.11 | +0.17 [−0.02, +0.36] | +0.08 [−0.07, +0.23] | +0.07 [−0.08, +0.22] |

Quarters (FE + lag):

| Depth (t) | t+1 | t+2 | t+4 (a year) | placebo t−1 |
|---|---:|---:|---:|---:|
| feedback index | +0.07 [−0.12, +0.25] | −0.01 [−0.19, +0.18] | −0.07 [−0.24, +0.09] | −0.06 [−0.24, +0.11] |
| addressed / 100 lines | −0.02 [−0.19, +0.16] | +0.06 [−0.11, +0.23] | −0.01 [−0.19, +0.17] | +0.08 [−0.09, +0.25] |
| rubber-stamp share | +0.00 [−0.22, +0.22] | −0.03 [−0.20, +0.14] | +0.10 [−0.07, +0.27] | +0.16 [+0.01, +0.30] |

**Reading.** No robust signal. The next-period estimates are all
indistinguishable from zero, at half-years and at quarters, with CIs of
about ±0.17 points per SD on a 2.8% base rate. They rule out effects larger
than about 6% of the revert rate per SD. A year ahead (half-year t+2),
deeper review goes with about 0.2 points fewer reverts per SD. That is the
sign H2a predicts. But:

- for the feedback index, the placebo (reverts in the period *before*) is
  about as large (−0.10);
- the quarterly fits don't reproduce it: a year ahead (t+4; 683 pairs in
  150 directories), addressed threads give −0.01 [−0.19, +0.17];
- these are 2 significant estimates out of 18 revert fits here.

The raw cross-sectional correlations are near zero (+0.01 to +0.09): the
directories that review more don't revert less. Within a directory, the
fixed-effects estimates move toward the negative side only slightly. Treat
the one-year addressed-threads estimate as a hypothesis to check on a
longer panel, not as a finding.

### H2b: later review cost (per SD of depth, half-years, t+1)

| Depth (t) → outcome (t+1) | raw r | pooled | FE | FE + lag | placebo t−1 (FE + lag) |
|---|---:|---:|---:|---:|---:|
| feedback index → threads / 100 lines | +0.33 | +0.00 [−0.14, +0.15] | −0.00 [−0.09, +0.09] | +0.11 [−0.00, +0.22] | +0.05 [−0.11, +0.21] |
| feedback index → rounds | +0.23 | −0.04 [−0.07, −0.02] | +0.015 [−0.001, +0.032] | **+0.033 [+0.010, +0.055]** | −0.021 [−0.043, +0.001] |
| feedback index → interdiff share | +0.18 | +0.010 [−0.000, +0.020] | −0.002 [−0.011, +0.006] | +0.002 [−0.009, +0.013] | +0.003 [−0.005, +0.011] |
| feedback index → hours to first review | +0.01 | +0.04 [−0.35, +0.44] | −0.15 [−0.48, +0.18] | −0.15 [−0.49, +0.19] | −0.13 [−0.44, +0.18] |
| feedback index → attention h / CL | +0.15 | +3.0 [+0.5, +5.4] | +1.7 [−0.5, +3.8] | **+2.7 [+0.6, +4.7]** | +0.4 [−2.2, +3.0] |
| addressed / 100 lines → threads / 100 lines | +0.47 | −0.30 [−0.64, +0.05] | −0.06 [−0.17, +0.06] | +0.13 [−0.19, +0.46] | +0.34 [−0.14, +0.81] |
| addressed → rounds | +0.35 | +0.007 [−0.030, +0.044] | +0.004 [−0.014, +0.023] | +0.020 [−0.007, +0.047] | −0.027 [−0.055, +0.002] |
| addressed → interdiff share | +0.24 | +0.015 [+0.006, +0.024] | −0.005 [−0.013, +0.002] | −0.001 [−0.010, +0.007] | +0.004 [−0.004, +0.013] |
| addressed → hours to first review | +0.03 | +0.26 [−0.12, +0.63] | +0.15 [−0.19, +0.50] | +0.17 [−0.16, +0.51] | −0.08 [−0.40, +0.25] |
| addressed → attention h / CL | +0.20 | +5.8 [+1.8, +9.7] | +1.8 [−1.1, +4.7] | **+3.3 [+0.3, +6.2]** | +0.2 [−2.9, +3.3] |
| feedback index → feedback index | +0.51 | +0.17 [+0.14, +0.20] | −0.012 [−0.026, +0.002] | (same) | −0.015 [−0.030, −0.001] |

One year ahead (t+2, FE + lag), every H2b estimate is within its CI of
zero. The largest are feedback index → threads −0.02, rounds +0.009,
attention +0.9 h, and addressed → attention −0.6 h. Quarters agree:
feedback index → rounds +0.031 [+0.005, +0.057] at t+1, the rest null.

By approver turnover in t+1 (median 21% of approvals by people new to the
directory that period; FE + lag, t+1):

| | Low turnover | High turnover |
|---|---:|---:|
| feedback index → threads / 100 lines | +0.03 [−0.07, +0.13] | +0.19 [+0.02, +0.36] |
| feedback index → rounds | +0.015 [−0.022, +0.052] | +0.044 [+0.013, +0.074] |
| feedback index → attention h | −2.8 [−6.7, +1.1] | +3.1 [−0.2, +6.4] |
| addressed → threads / 100 lines | −0.35 [−0.67, −0.04] | +0.21 [−0.35, +0.76] |
| addressed → feedback index | −0.039 [−0.074, −0.005] | −0.006 [−0.039, +0.026] |

**Reading.** Review doesn't get cheaper after a deep-review period. The
raw correlations (r = +0.2 to +0.5) say that directories that review
deeply keep doing so. That is a directory trait: 50–83% of each measure's
variance is between directories. With fixed effects it mostly disappears.
What remains in the next period goes the wrong way for H2b: a deeper half
is followed by slightly more rounds (+0.03 per SD on a mean of 1.05) and
more attention hours (+2.7 h per SD on a mean of 60). These are short-run
continuations (a hard project spans two halves), and they're gone a year
on.

The turnover split was meant to separate "the same reviewers keep their
habit" from "review left the code easier to review". It doesn't give a
clean answer:

- where the approvers stayed, deeper *addressed* review is followed by
  fewer threads per 100 lines (−0.35 [−0.67, −0.04]) and a lower feedback
  index (−0.04 [−0.07, −0.01]), the H2b sign;
- where the approvers changed, the continuation is stronger.

That is also what a stable team that resolved its issues would look like,
and it is one of many split estimates. Count it as weak, unreplicated
support at most. In the quarterly split the same coefficients are +0.20
and +0.004 (null).

**Confounding.** Directory fixed effects remove fixed team habits, not
changing ones: a re-org, a new tech lead, or a project phase (new feature
→ hardening) moves review depth and later outcomes together. With 3–6
periods per directory, a lagged outcome under fixed effects has Nickell
bias of order 1/T. That is why the table reports the FE fit both without
and with the lag; their signs agree.

## H2c: author dose-response (`review_roi_part2.py`, `h2c`)

**Who:** authors whose first commit over all history is 2023-07-01 ..
2025-09-30, with at least 5 unit CLs and a summed 2023–24 norm of at least
2 threads in months 1–12, and at least 3 months of year 2 observed before
2026-10-01. That's 404 authors, 256 of them with the full 12 months of
year 2, and 12,561 year-2 CLs.

**Exposure:** in months 1–12, addressed threads received ÷ their 2023–24
norm (mean addressed threads for the CL's size × dir2), summed over the
author's CLs. Unaddressed threads get the same treatment with their own
norm. Both enter as log2 (floor 1/16), so coefficients are per doubling. A
"total" variant uses the feedback index instead.

**Outcomes (months 13–24):**

- log2 feedback index, for authors with ≥ 3 CLs in year 2;
- log2(1 + CLs landed per year);
- log2(1 + threads given per year): threads they started on other
  people's merged CLs, from thread roots;
- 30-day revert, per CL: logit with the CL's size × dir2 base revert rate
  (as log odds) and the author's year-1 revert rate as controls.

**Controls:** log2 first-year CLs, log2 mean lines per CL, top-dir2 share
of first-year CLs, start half-year (era); for threads given, also
first-year threads given. Errors are clustered by author.

| Outcome (year 2) | per doubling of addressed (y1) | per doubling of unaddressed (y1) | total feedback index (y1) |
|---|---:|---:|---:|
| log2 feedback index (n = 239) | **+0.36 [+0.24, +0.48]** | **+0.27 [+0.02, +0.51]** | **+0.69 [+0.55, +0.83]** |
| … full year 2 only (148) | +0.27 [+0.13, +0.41] | +0.30 [+0.01, +0.59] | +0.60 [+0.46, +0.74] |
| revert, odds ratio (12,561 CLs) | **1.32 [1.11, 1.58]** | 0.91 [0.68, 1.22] | **1.34 [1.11, 1.61]** |
| … full year 2 only (6,459) | 1.42 [1.15, 1.75] | 0.84 [0.58, 1.21] | 1.40 [1.11, 1.75] |
| log2 CLs landed per year (404) | −0.18 [−0.37, +0.01] | +0.33 [−0.01, +0.67] | −0.06 [−0.28, +0.16] |
| log2 threads given per year (404) | −0.02 [−0.15, +0.11] | **+0.35 [+0.09, +0.62]** | +0.22 [+0.04, +0.40] |

By fifth of first-year addressed feedback (relative to the norm, within
start half-year):

| Fifth | Authors | Addressed ÷ norm | Unaddressed ÷ norm | CLs y1 | Feedback index y2 | Revert y2 | CLs y2 / yr | Threads given y2 / yr |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| least | 82 | 0.70 | 1.04 | 27.5 | 0.66 | 1.9% | 7.0 | 2.2 |
| 2nd | 80 | 1.41 | 1.47 | 22 | 1.01 | 2.6% | 13.0 | 2.7 |
| 3rd | 82 | 2.13 | 1.68 | 23.5 | 1.14 | 3.2% | 9.0 | 2.5 |
| 4th | 80 | 3.05 | 2.13 | 16 | 1.73 | 3.3% | 6.8 | 4.0 |
| most | 80 | 5.34 | 2.41 | 13.5 | 1.51 | 2.4% | 0.0 | 0.0 |

(Medians, except the revert rate, which pools year-2 CLs. The top fifth's
median author landed nothing in year 2: many left or stopped landing.)

**Already known** (`balance.md` §4b–4c):

- review need falls with practice (commits landed) more than with tenure;
- prolific newcomers learn faster by the calendar but not per CL;
- a person-half's feedback index adds little to CLs landed in predicting
  later reviewing or OWNERS.

**New here:**

1. **Persistence, not learning.** A newcomer's first-year feedback level
   carries into year 2: elasticity 0.6–0.7 per doubling, at equal volume,
   size, place and era. Addressed and unaddressed feedback both predict
   *more* year-2 feedback, so there's no sign that feedback the author
   acted on lowers later need more than feedback they didn't act on.
2. **Reverts.** Year-2 CLs of authors who drew twice the addressed
   feedback are reverted about 1.3× as often, even after the author's own
   year-1 revert rate. Unaddressed feedback doesn't predict reverts.
3. **Threads given.** Authors who received more *unaddressed* feedback go
   on to start more threads themselves (+0.35 log2 per doubling). That fits
   team review culture (some teams comment a lot, including optional
   remarks) better than learning.

**Reading.** This design can't detect learning from feedback, because
who draws feedback is a stable trait of the author and their work: harder
areas inside a dir2, weaker starting skill, or a chatty team. The
association has the opposite sign to H2c, and that's what selection
predicts. Testing H2c needs variation in feedback that the author didn't
cause: the first-year reviewers' *habitual* thoroughness (Part 1's
leave-one-out reviewer habit, D4) as an instrument, comparing newcomers
on the same team who happened to get thorough vs light reviewers. That
needs the reviewer-habit table from package 1; it's a natural next step.
Caveats:

- 404 authors is small;
- the year-2 feedback index needs ≥ 3 CLs, so authors who left drop out
  (the top fifth's median author landed nothing);
- the 2025 cohorts have truncated year 2 (the full-year rows agree).

## H2d / H2e: blame pilot (`scripts/review_roi_blame.py`)

### H2d: SZZ-style fix-inducing CLs

**Fix commits.** First-parent commits on `main` since 2024-01-01 with a
`Fixed:` footer (parsed with `cosh.bugs.footer_ids`, old Monorail IDs mapped
through `monorail_map`):

| Step | Commits |
|---|---:|
| with a `Fixed:` footer | 26,675 |
| … naming a fetched bug of type Bug or Vulnerability | 8,669 |
| … not a revert or reland | 8,536 |
| … at most 20 files (eligible) | 8,317 |

Restricted bugs (most unfixed security bugs) aren't in `bugs.sqlite`, so
they're missing.

**Method.** A random sample of 500 (seed 20261109). For each fix commit:

1. diff its first parent against it (`-U0 -M`) to find the deleted or
   modified non-blank lines of each changed file;
2. skip new files, test, expectations and data files (`TEST` regex:
   384 files), and files over 20k lines at the parent (1);
3. blame those lines at the parent:
   `git blame -w -l --porcelain -L a,b … <parent> -- <file>`;
4. keep blamed commits landed before the bug was filed (`bugs.created`)
   and map them to CLs via `gcommits.change_number`.

On 8 fix commits the whole file was also blamed without `-L`, to cost the
plain variant.

**Pilot results:**

- 500 fixes, 712 files blamed;
- 323 fixes had a blamable non-test file with deleted lines;
- 282 yielded at least one inducing CL (218 none: fixes that only add
  code, or only touch tests);
- 3,431 blamed lines are older than the bug report, 2,588 newer
  (excluded), and 158 are pre-2017 or not first-parent;
- 1.68 inducing CLs per fix on average (median 1);
- 823 distinct inducing CLs, 418 of them unit CLs (landed 2023-07 ..
  2026-09, human, non-mechanical).

**Comparison.** Induced unit CLs against the non-induced unit CLs of the
same size10 × dir2 × half-year (375 matched; strata need ≥ 5 non-induced
CLs). The difference is the mean over induced CLs of (value − stratum
mean), with a 95% CI. *n for 80% power* is the number of induced CLs
needed to detect the observed difference at p < 0.05:

| Measure | Induced | Matched | Difference | n for 80% power |
|---|---:|---:|---:|---:|
| feedback index | 1.13 | 0.98 | **+0.15 [+0.01, +0.29]** | 651 |
| log2(1 + threads) | 2.12 | 1.91 | **+0.21 [+0.07, +0.34]** | 328 |
| rubber-stamped | 18.9% | 20.6% | −1.6 pts [−5.4, +2.2] | 4,120 |
| any addressed thread | 63.7% | 57.3% | **+6.4 pts [+2.0, +10.9]** | 366 |
| log2 lines (balance check) | | | +0.05 [+0.01, +0.09] | |
| reverted ≤ 30 d | 0% | 3.3% | (by construction: a revert removes the lines) | |

With coarser size strata (5 buckets) the picture is the same: feedback
index +0.16 [+0.03, +0.30], rubber-stamped −2.4 pts [−6.1, +1.3]. Without
any matching, 0.64 per 1,000 rubber-stamped CLs were later blamed by a
sampled fix, against 1.46 per 1,000 reviewed CLs (unadjusted: stamped CLs
are smaller and simpler).

**Reading.** In the pilot, the CLs whose lines a later bug fix rewrote had
been reviewed *more* than comparable CLs, not less. This is the same
selection as with reverts: reviewers spend more on complex, risky code,
and that code is where later bugs are found. The size balance check
barely moves (+3% lines within the bucket), so size within a bucket
doesn't explain it.

Nothing here supports "thinly reviewed code is more often the origin of
a later bug fix". Rubber-stamped CLs are no more often fix-inducing
(−1.6 points, CI ±3.8). With 500 fixes the pilot is a power check:

- detecting the feedback-index difference seen needs about 650 induced
  CLs, which is about 780 fixes;
- detecting a rubber-stamp difference of the size seen (1.6 points) needs
  about 4,100 induced CLs, about 4,900 fixes.

The full run (8,317 fixes, so about 7,000 induced unit CLs at the pilot's
0.84 per fix) has the power for both. It should then use the reviewer-habit
designs of Part 1 (D4), not this CL's own review, to get past the
selection.

SZZ caveats:

- a fix often rewrites lines that aren't the bug (refactors in the same
  commit);
- fixes that only add code (a missing check) blame nothing;
- the inducing commit can be a move or reformat (`-w` helps only with
  whitespace);
- Vulnerabilities fixed under restriction are missing.

**Cost.** Wall time was 1,739 s for 500 fixes on 2 workers. Per worker,
a commit took 6.9 s on average (median 1.0 s, p90 20 s, max 141 s), and a
file 4.7 s (median 3.0 s, p90 11.7 s, max 33 s).

| Full run (8,317 eligible fixes since 2024) | CPU hours | Wall at 2 jobs |
|---|---:|---:|
| blame `-L` of the changed lines (as piloted) | **≈ 16** | ≈ 8 h |
| blame of whole files (8-file subsample: 1.8× slower) | **≈ 29** | ≈ 15 h |

All local git: **no download** is involved and the server sees no load.
The whole-file ratio comes from only 8 files and should be taken as rough.
Blame peaks at about 1 GB RSS per process.

### H2e: line survival

**Method.** A random sample (seed 20261109) of 300 unit CLs landed in
2024 with 20–500 added lines in the landed commit. That's 53,386 eligible,
out of 106,086 unit CLs in 2024. The target is the last first-parent
commit on `main` landed before landing + 365 days. Each file the CL added
lines to (`diff-tree --numstat -M`) is blamed at the target:

    git blame -w -l --porcelain <sha>^..<target> -- <file>

The range blame walks only the year after landing. Older lines stop at the
boundary, so a line still attributed to the CL's commit survived
unmodified. On a 6-CL test this gave identical counts to a full-history
blame and was 4.7× faster. Survival is the CL's surviving lines ÷ its
added lines. Lines in files gone or renamed at the target count as not
surviving: 17.6% of added lines, reported separately as *survival in files
still present*.

**Results** (298 CLs with added lines; 1,730 files blamed). Mean survival
is 58.5% (SD 37 points). Terciles of the feedback index over all eligible
CLs (cuts 0.32 and 1.03; the bottom tercile is mostly CLs with no thread):

| Feedback-index tercile | CLs | Median index | Survival (mean of CLs) | Survival (pooled lines) | In files still present | Median added lines |
|---|---:|---:|---:|---:|---:|---:|
| lowest | 110 | 0.00 | 57.7% | 55.7% | 71.4% | 70 |
| middle | 96 | 0.60 | 57.8% | 56.0% | 64.9% | 72 |
| highest | 92 | 1.82 | 60.2% | 62.9% | 67.4% | 73 |

Adjusted: survival on tercile dummies and log added lines, demeaned by
dir2 (242 CLs in dir2s with ≥ 2 sampled CLs), errors clustered by dir2:

- middle vs lowest: −5.9 points [−18.2, +6.5];
- highest vs lowest: −1.0 [−11.5, +9.4];
- per log unit of added lines: +2.1 [−1.2, +5.4].

**Reading.** No signal. Code that drew more review is no more likely to be
left untouched a year later than code that was rubber-stamped, at equal
size and place. The CIs are ±10 points or more. Detecting a 5-point
difference between two terciles at 80% power needs about 1,300 CLs per
comparison (the SD is 37 points).

Survival is also ambiguous as a quality signal: code that stays may be
good, or abandoned. Code that changes may be bad, or central and actively
developed. Read it next to the H2d links, not alone.

**Cost.** Wall time was 1,705 s for 300 CLs on 2 workers. Per worker a CL
took 11.4 s on average (median 7.3 s, p90 23.5 s, max 153 s), and a file
2.0 s (median 1.7 s, p90 3.0 s).

| Full run | CLs | CPU hours | Wall at 2 jobs |
|---|---:|---:|---:|
| 2024 unit CLs with 20–500 added lines | 53,386 | **≈ 170** | ≈ 3.5 days |
| all unit CLs landed 2023-07 .. 2025-09 (larger CLs cost more, so a lower bound) | ≈ 234k | ≈ 740 | ≈ 15 days |

All local git, **no download**. A stratified sample of about 3,000–5,000
CLs (≈ 10–16 CPU h) would give the power above. That's the sensible next
step, not a full run.

## Rerun

```
export COSH_DATA_DIR=/home/rbagent/projects/cosh/data/private
I=/home/rbagent/.claude/jobs/9e4a825c/tmp/inputs
S=/home/rbagent/.claude/jobs/9e4a825c/tmp/scratch/part2
python3 scripts/review_roi_part2.py --first-commit $I/first_commit.txt --mech $I/mech.jsonl \
    --cache $S/cache.pkl --out $S/part2_panels.json          # ~25 s with a warm cache, ~1 min cold
python3 scripts/review_roi_blame.py szz --cache $S/cache.pkl --n 500 --full-sample 8 --jobs 2 \
    --scratch $S --out $S/blame_szz.json                      # ~30 min
python3 scripts/review_roi_blame.py survival --cache $S/cache.pkl --n 300 --jobs 2 \
    --scratch $S --out $S/blame_survival.json                 # ~28 min
```

Both scripts lower their own priority by 5 (`os.nice(5)`), and `--reuse`
redoes only the analysis from the saved per-item files. Outputs:

- `$S/part2_panels.txt`: the printed tables;
- `$S/part2_panels.json`, `blame_szz.json`, `blame_survival.json`: full
  aggregates;
- `$S/szz_items.jsonl` and `survival_items.jsonl`: per-item blame counts,
  public CL numbers and shas only;
- `$S/part2_results.json`: the main numbers.

`balance_feedback_predicts.py` (`ols`, `logit`, `cluster_cov`) is on
`main` but not yet on this worktree's base, so `review_roi_part2.py` falls
back to importing it from the main checkout.
