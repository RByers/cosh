# Review ROI, Part 1: review depth and the revert rate

Work package 1 of `docs/review-roi.md` (2026-11-09). Does deeper or more
expert code review lower the revert rate of Chromium CLs, after normalizing
for difficulty? Scripts: `scripts/review_roi_table.py` (the per-CL table)
and `scripts/review_roi_part1.py` (designs D1–D8); rerun commands are in
their docstrings. Outputs in the job scratch directory `part1/`:
`cl_table.sqlite` (the table), `part1_report.txt` (every table printed
below, in full), `part1_report.json` (everything), `part1_results.json`
(plain-named main numbers for the page; aggregates only, no identities).
Nothing was fetched, no comment text was read and no model was called.

## Summary in plain language

- **The data show no protective effect of review on reverts that survives
  the checks.** Every measure of how much review *this* CL got (threads,
  feedback index, comments, rounds, attention hours, addressed threads)
  goes with *more* reverts, raw and after normalizing for size, directory,
  author practice and half-year. Normalization shrinks the association by a
  third to a half but never flips its sign. The reason is the one the design
  anticipated: reviewers spend more on riskier changes, and the controls
  cannot see all of the risk.
- **A rubber stamp goes with fewer reverts, not more.** CLs approved with no
  reviewer thread (35% of the unit) were reverted 1.99% of the time against
  3.03% for the rest; at equal size, place, author practice and era the odds
  ratio is 0.76 (0.71–0.81). Going from a rubber stamp to one *addressed*
  thread goes with 24% higher odds of a revert (MH OR 1.24, 1.10–1.37).
- **The approver's habit is the only exposure with a protective sign, and it
  is small and not specific.** CLs whose first approver habitually writes
  more threads than the norm (measured on their *other* CLs) were reverted
  slightly less: 1.4 fewer reverts per 1,000 CLs from the 25th to the 75th
  percentile of that habit (95% CI 0.4 to 2.4), about 5% of the 26.7 per
  1,000 base rate. But the same habit "prevents" reverts for reasons review
  cannot prevent (flaky tests, infrastructure, dependent CLs) just as much in
  relative terms (OR 0.95 against 0.97 for reasons review can catch), and
  the within-author comparison (D5) is null (0.97, 0.92–1.02). So the small
  association is better read as confounding (thorough approvers work where
  CLs are less breakable) than as prevention.
- **Expertise shows nothing.** The approver's prior approvals or commits in
  the directory, OWNERS coverage and tenure are flat or slightly *positive*
  with reverts at equal difficulty (senior and OWNER approvers get the hard
  CLs).
- **What the data can exclude.** Taking the most favourable 95% bound of
  the best-identified design (D4, the first approver's habit), moving a CL
  from a 25th- to a 75th-percentile-thorough approver avoids at most about
  2.4 reverts per 1,000 CLs (9% of reverts), and the negative control says
  even that is probably not caused by the review. For adding review to a
  CL that got none (one addressed thread instead of a rubber stamp), the
  data exclude any reduction at all at the 95% level, though here the
  confounding is so strong that this says little about the true effect.
- **What this does not say.** Reverts measure one narrow thing: breakage bad
  enough to be backed out within weeks, mostly CI failures caught within a
  day. Review that catches a bug before landing leaves no trace in this
  outcome, and the slower harms (bugs found months later, code that is hard
  to change) are Part 2's subject. The honest conclusion is that *reverts
  cannot show review's value*, not that review has none.

## The unit and the table

`review_roi_table.py` (67 s, peak RSS 3.6 GB) joins `balance.sqlite` `cl`,
`cl_attention`, `balance-git.sqlite` (`gcommits`, `gfiles`, `paths`),
`balance-timeline.sqlite` `votes`, and `derived.sqlite` `accounts` and `comments`
(counts only), plus the shared inputs `first_commit.txt`,
`owners_added.txt` and `mech.jsonl`.

| Step | CLs | Lost |
|---|---:|---:|
| `cl` rows (human-owned CLs on chromium/src main, 2023-06-26 .. 2026-11) | 509,646 | |
| merged | 403,235 | |
| with a landed first-parent commit, landed 2023-07-01 .. 2026-09-30 | 380,376 | 86 merged CLs have no first-parent commit; the rest land outside the window |
| owner a bot by email (`config/bots.txt`) | | 1,298 (0.34%) |
| `Bot-Commit` approval (Rubber Stamper) | | 10,616 (2.79%) |
| mechanical (`mech.jsonl`: ≥ 100 files, or ≥ 10 files with repetition ≥ 0.8) | | 4,007 (1.05%) |
| revert | | 3,541 (0.93%) |
| reland | | 4,368 (1.15%) |
| landed < 30 days before the newest commit (2026-11-07) | | 0 (the window ends 2026-09-30) |
| **unit** | **356,546** | 6.3% of 380,376 |

Shares are of the 380,376 in the window, applied in the order listed.
The provisional tables (`cl_table_v0/v1/v2`, mechanical rule ≥ 50 files,
4,685 excluded, 355,938 units) gave odds ratios within about ±0.01 of
the final ones and the same conclusions; all numbers below are from the final table
(mechanical rule from `mech.jsonl`).

**Outcomes.** Reverted within 7 days 2.42%, within 30 days **2.67%**
(9,518 CLs), within 90 days 2.80% (of the 333,376 CLs with 90 days of
follow-up). A revert is the first later first-parent commit on `main` whose
message says `This reverts commit <sha>` of the CL's landed commit.

**Approvers.** Non-owner human voters whose last Code-Review vote at or
before submission (+120 s) is positive. Chromium's Code-Review maximum is +1
(LGTM), so "+1" is the approval, not "+2". Against git `Reviewed-by`:

| votes vs `Reviewed-by` (CLs in the base set) | CLs |
|---|---:|
| same set of people | 284,656 |
| `Reviewed-by` has extra people | 14,405 |
| no vote recorded, `Reviewed-by` only | 85,484 |
| votes have extra people | 94 |
| differ otherwise / votes only | 76 |

The 85k "Reviewed-by only" CLs are CLs with no NoteDb meta ref on disk (no
comments, so the timeline stage has no data for them); for these the
approvers come from `Reviewed-by` (78,180 unit CLs, 22%). Where votes exist
they agree with `Reviewed-by` in 95% of CLs. Main results also hold on the
votes-only subset (below).

**Exposures, per CL.** Reviewer-started threads (`cl.threads`, threads
whose root is a non-owner human; never the owner's own), addressed threads,
reviewer comments, distinct non-owner commenters, rounds, rework uploads,
interdiff share, the sum of each non-owner human's attention-set hours
(`cl_attention`), hours from sent to first substantive review, approvers,
and the rubber-stamp flag (an approver and no reviewer thread). The
**feedback index** is threads ÷ the 2023–24 mean for the CL's size bucket
(10 log-spaced, `balance_growth.size10`) × top 2-level directory (≥ 30 CLs,
else size alone), recomputed in the table's base set.

**Approver expertise**, per approver at the CL's landing, max over
approvers and the first approver's: prior authored commits and prior
approvals (git `Reviewed-by`, since 2017) touching the CL's main 3-level and
2-level directory; OWNERS coverage (added before the CL to an OWNERS file
in the directory of the CL's heaviest file, or a parent; additions only,
`per-file` and `include` not modelled; 68% of unit CLs had such an
approver); tenure (years since first commit on `main`, all history).

**Approver habit**, leave-one-out: the approver's mean residual over the
*other* merged, non-mechanical CLs they approved in the same half-year
(at least 5 others; 99.1% coverage for the first approver). Two scales:
residual threads (threads − norm, as the design specified) and residual
log1p threads (log1p threads − the cell's 2023–24 mean of log1p threads).
Also the approver's leave-one-out 30-day revert rate, as a descriptive
trait.

**Split-half reliability** (first approver, approver × half-year cells
with ≥ 10 CLs, odd vs even CLs in time order, 5,672 cells):

| Habit measure | r | Spearman–Brown |
|---|---:|---:|
| mean residual threads | 0.60 | 0.75 |
| **mean residual log1p threads** | **0.77** | **0.87** |
| feedback index (Σ threads ÷ Σ norm) | 0.57 | 0.72 |
| 30-day revert rate | 0.14 | 0.25 |

The log-scale habit is the most reliable (close to `review-impact.md`'s
0.89 for a related measure), so it is reported first; the linear one is
the design's, and both are shown everywhere. A reviewer's revert rate is
barely a trait (0.25), as expected for a 2.7% event.

**Controls.** Size bucket (10), log2 files, 2-level directory (86 levels
with ≥ 400 unit CLs, the rest pooled), author tenure band (from
`first_commit.txt`), author practice band (prior commits in the CL's main
dir3: 0, 1–4, 5–19, 20–99, 100+), half-year, test-file share (paths under
`test/`, `tests/`, `testing/`, `test_data/`, `web_tests/`, … or named
`*_test.*`, `*_unittest.*`, `*_browsertest.*`, `*Test.java`, `*.test.ts`,
fakes and mocks), weekday and 6-hour band of landing (UTC). Levels with
fewer than 200 CLs join the reference level.

## Methods as run

`review_roi_part1.py --frac 1 --reps 200 --check` (2,248 s, about 37
minutes, niced).

- **Logistic models** (D3, D4, D6c, D7, D8) are fitted on *all* unit CLs
  (`--frac 1`; the case-control option was not needed): a sparse
  Newton–Raphson in pure Python, about 12 s per model on 356k rows × 121
  control columns. Standard errors are clustered by author with
  `cluster_cov`'s sandwich and small-sample factor, computed only for the
  exposure coefficients. At start-up the solver is checked against
  `balance_feedback_predicts.logit` on 4,000 rows: coefficients and
  clustered SEs agree to 3e-11. (That script is on `main` but not on this
  worktree's base; the import falls back to the main checkout.)
- **Effects** are odds ratios per doubling of (1 + x) for counts and
  hours, per standard deviation for the habit (linear in the residual), or
  yes vs no. The **25th → 75th percentile effect** is the mean, over a
  random 60,000-CL sample with their own controls, of the predicted revert
  probability at the exposure's 75th percentile minus at its 25th; the
  interval recomputes it at the coefficient's 95% bounds (other
  coefficients fixed). "Avoided reverts per 1,000 CLs" is minus that
  difference × 1,000.
- **D2** Mantel–Haenszel odds ratios, strata size10 × dir2 × author
  practice band × half-year, exposure above vs at-or-below the stratum
  median; 95% CI from 200 author-clustered bootstrap replicates. The raw OR
  splits at the global median (Woolf CI). By-fifth ORs use global fifths
  (merged where ties make cut points equal), MH vs the lowest, RGB CIs in
  the JSON.
- **D1** indirect standardization: expected rate per CL from its size10 ×
  dir2 × practice stratum, shrunk toward size10 × practice (k = 20);
  adjusted rate = observed ÷ expected × the overall rate.

## D1. Revert rate by level of each measure

30-day revert rate, raw and indirectly standardized (O/E = observed ÷
expected at the CL's size, directory and author practice).

| Reviewer-started threads | CLs | Raw | Adjusted | O/E |
|---|---:|---:|---:|---:|
| 0 | 123,576 | 1.99% | 2.32% | 0.87 |
| 1 | 89,360 | 2.18% | 2.44% | 0.91 |
| 2–3 | 66,178 | 2.77% | 2.70% | 1.01 |
| 4–6 | 35,789 | 3.53% | 2.99% | 1.12 |
| 7+ | 41,643 | 4.84% | 3.33% | 1.25 |

| Feedback index | CLs | Raw | Adjusted | O/E |
|---|---:|---:|---:|---:|
| < 0.24 | 142,041 | 2.12% | 2.27% | 0.85 |
| 0.24–0.50 | 36,225 | 2.90% | 2.48% | 0.93 |
| 0.50–0.77 | 35,584 | 2.71% | 2.57% | 0.96 |
| 0.77–1.11 | 35,643 | 2.76% | 2.80% | 1.05 |
| 1.11–1.58 | 35,589 | 2.95% | 2.95% | 1.10 |
| 1.58–2.43 | 35,794 | 2.99% | 3.08% | 1.15 |
| 2.43+ | 35,670 | 3.88% | 3.65% | 1.37 |

| Attention hours (sum over reviewers), deciles | Raw | Adjusted |
|---|---:|---:|
| < 0.28 h | 2.26% | 2.63% |
| 0.28–1 | 2.18% | 2.37% |
| 1–2.5 | 2.31% | 2.46% |
| 2.5–5.8 | 2.37% | 2.44% |
| 5.8–14.5 | 2.59% | 2.60% |
| 14.5–22 | 2.67% | 2.64% |
| 22–42 | 2.95% | 2.71% |
| 42–79 | 3.00% | 2.69% |
| 79–166 | 3.59% | 3.05% |
| 166+ | 4.81% | 3.54% |

| Rubber stamp | CLs | Raw | Adjusted |
|---|---:|---:|---:|
| no | 232,992 | 3.03% | 2.82% |
| yes | 123,554 | 1.99% | 2.32% |

| First approver's habit, log scale (deciles) | Raw | Adjusted |
|---|---:|---:|
| lowest | 2.58% | 2.59% |
| 2 | 2.82% | 2.80% |
| 3 | 2.81% | 2.82% |
| 4 | 2.83% | 2.80% |
| 5 | 2.81% | 2.85% |
| 6 | 2.67% | 2.71% |
| 7 | 2.57% | 2.58% |
| 8 | 2.60% | 2.63% |
| 9 | 2.37% | 2.39% |
| highest | 2.63% | 2.54% |

| Approver's LOO revert rate (descriptive) | Raw | Adjusted |
|---|---:|---:|
| lowest fifth (< 1.2%) | 1.88% | 1.99% |
| top decile (≥ 5.9%) | 4.37% | 3.77% |

Approver prior approvals or commits in dir3, OWNERS coverage: flat (every
decile 2.4–2.9% raw, O/E 0.96–1.07). Approver tenure: rising, 2.14% for
the least senior decile to 3.34% for the most (adjusted 2.36% → 2.98%).

**Reading.** Normalizing removes about half of the raw gradient (top vs
bottom threads: raw 2.4×, adjusted 1.4×) but none of its direction. The
habit deciles have no monotone shape: a slight dip in the top fourth, with
the bottom decile also low. Approvers' own revert rates do differ (1.9% vs
4.4%), but that trait has a split-half reliability of 0.25 and mostly
reflects the CLs they approve.

## D2. Stratified odds ratios: raw vs normalized

Exposure above vs at-or-below the median (stratum median for MH).
Rubber stamp and OWNERS are yes/no.

| Measure | Raw OR (95% CI) | Stratified MH OR (95% CI) | n |
|---|---|---|---:|
| reviewer-started threads | 1.75 (1.68–1.82) | 1.39 (1.32–1.46) | 356,546 |
| feedback index | 1.35 (1.30–1.41) | 1.39 (1.32–1.46) | 356,546 |
| reviewer comments | 1.62 (1.56–1.69) | 1.31 (1.26–1.40) | 356,546 |
| distinct non-owner commenters | 1.73 (1.66–1.81) | 1.34 (1.28–1.41) | 356,546 |
| addressed threads | 1.66 (1.59–1.73) | 1.33 (1.27–1.40) | 356,546 |
| review rounds | 1.84 (1.75–1.92) | 1.39 (1.32–1.49) | 278,429 |
| interdiff share | 1.25 (1.19–1.32) | 1.23 (1.16–1.31) | 165,003 |
| attention hours | 1.47 (1.40–1.54) | 1.26 (1.20–1.32) | 276,826 |
| hours to first substantive review | 1.25 (1.19–1.32) | 1.15 (1.08–1.21) | 166,233 |
| approvers | 1.45 (1.39–1.51) | 1.21 (1.15–1.28) | 356,546 |
| **rubber stamp** | **0.65 (0.62–0.68)** | **0.76 (0.71–0.81)** | 356,546 |
| approver prior approvals in dir3 (max) | 0.97 (0.93–1.01) | 1.05 (1.00–1.09) | 356,521 |
| approver prior approvals in dir2 (max) | 1.01 (0.97–1.05) | 1.05 (1.00–1.10) | 356,521 |
| approver prior commits in dir3 (max) | 0.95 (0.92–0.99) | 1.02 (0.96–1.07) | 356,521 |
| an approver is an OWNER covering the CL | 1.03 (0.99–1.08) | 1.05 (0.98–1.12) | 356,521 |
| approver tenure (max) | 1.25 (1.20–1.30) | 1.11 (1.06–1.18) | 356,515 |
| **first approver's habit, log scale** | **0.93 (0.89–0.96)** | **0.92 (0.86–0.96)** | 353,428 |
| first approver's habit, residual threads | 0.98 (0.95–1.03) | 0.98 (0.92–1.03) | 353,428 |
| first approver's habitual feedback index | 0.99 (0.95–1.04) | 0.97 (0.92–1.03) | 353,428 |
| most thorough approver's habit | 1.07 (1.02–1.11) | 1.00 (0.96–1.07) | 354,600 |
| first approver's LOO revert rate | 1.65 (1.58–1.72) | 1.21 (1.13–1.26) | 353,428 |

Threads and the feedback index give the same stratified OR by
construction: within a size × dir2 stratum the index is threads ÷ a
constant. By fifths (MH vs the lowest), threads rise steadily (1.11, 1.29,
1.69); the log habit falls only in the top fifth (1.05, 1.01, 0.97, 0.93).

**Reading.** The sign of no review measure flips with normalization. The
raw protective look of expertise (prior commits 0.95) turns neutral or
slightly harmful once the CL's difficulty is held fixed. The habit is the
only measure whose protective sign holds in both columns, and only on the
log scale.

## D3. Logistic models: this CL's review, all controls

30-day revert, author-clustered SEs, all 356,546 CLs (fewer where the
exposure is missing). Base rate 2.67%.

| Exposure | OR (95% CI) | Unit | p25 → p75 | Reverts per 1,000, p25 → p75 (95% CI) | Same, no controls |
|---|---|---|---|---|---|
| reviewer-started threads | 1.21 (1.18–1.24) | per doubling of 1 + x | 0 → 3 | +9.0 (+7.8 to +10.4) | +11.6 |
| feedback index | 1.30 (1.26–1.34) | per doubling | 0 → 1.4 | +8.2 (+7.1 to +9.4) | +7.8 |
| addressed threads | 1.18 (1.15–1.20) | per doubling | 0 → 1 | +3.9 (+3.3 to +4.5) | +5.6 |
| reviewer comments | 1.17 (1.15–1.20) | per doubling | 0 → 4 | +8.8 (+7.4 to +10.3) | +12.2 |
| distinct commenters | 1.27 (1.22–1.33) | per doubling | 0 → 1 | +5.7 (+4.6 to +6.8) | +8.6 |
| rounds | 1.30 (1.25–1.35) | per doubling | 0 → 1 | +6.6 (+5.6 to +7.7) | +9.0 |
| interdiff share | 1.30 (1.22–1.39) | per doubling | 0.02 → 0.63 | +5.6 (+4.1 to +7.2) | +5.0 |
| attention hours | 1.07 (1.06–1.08) | per doubling | 1.6 → 61 h | +8.1 (+6.5 to +9.8) | +11.8 |
| hours to first review | 1.04 (1.03–1.05) | per doubling | 0.7 → 20 h | +4.3 (+2.8 to +5.8) | +6.4 |
| approvers | 1.34 (1.25–1.43) | per doubling | 1 → 2 | +4.4 (+3.1 to +5.9) | +7.8 |
| rubber stamp | 0.76 (0.72–0.81) | yes vs no | no → yes | −6.6 (−7.9 to −5.2) | −10.5 |

**Reading.** Holding size, directory, author, era, test share and timing
fixed shrinks most associations by 20–40% and none to zero or below. A CL
that drew three threads instead of none was reverted 9 more times per
1,000. This is selection, not harm: reviewers comment where they see risk,
and the controls only partly capture risk.

## D4. Approver habit and expertise (the main identification strategy)

Exposures that do not measure this CL's review: they describe the approver
on *other* CLs, or before this one. All controls, author-clustered SEs.

| Exposure | OR (95% CI) | Unit | Reverts per 1,000, p25 → p75 (95% CI) |
|---|---|---|---|
| **first approver's habit, log scale** | **0.959 (0.930–0.987)** | per SD | **−1.44 (−2.42 to −0.43)** |
| most thorough approver's habit, log | 0.990 (0.959–1.022) | per SD | −0.33 (−1.38 to +0.75) |
| first approver's habit, residual threads | 0.966 (0.940–0.992) | per SD | −0.84 (−1.50 to −0.19) |
| most thorough approver's habit, residual threads | 0.993 (0.966–1.021) | per SD | −0.17 (−0.86 to +0.53) |
| first approver's habitual feedback index | 0.934 (0.854–1.021) | per doubling | −0.66 (−1.38 to +0.22) |
| approver prior approvals in dir3 (max) | 1.015 (1.003–1.027) | per doubling | +1.54 (+0.28 to +2.99) |
| approver prior commits in dir3 (max) | 1.009 (0.996–1.021) | per doubling | +0.86 (−0.38 to +2.28) |
| approver prior approvals in dir2 (max) | 1.012 (0.999–1.024) | per doubling | +1.15 (−0.07 to +2.60) |
| an approver is an OWNER covering the CL | 1.075 (1.012–1.141) | yes vs no | +1.84 (+0.29 to +3.47) |
| approver tenure (max) | 1.119 (1.080–1.160) | per doubling | +3.32 (+2.04 to +4.85) |
| first approver's LOO revert rate | 1.204 (1.163–1.246) | per SD | +4.95 (+3.89 to +6.09) |

Percentiles: log habit −0.094 → +0.278 (SD 0.30 log units); residual
threads −0.51 → +1.34; prior approvals in dir3 31 → 525; tenure 5.1 → 12.5
years.

Joint model (log habit, prior approvals and commits in dir3, OWNERS,
tenure together): habit OR 0.947 (0.918–0.976), −1.86 per 1,000
(−2.86 to −0.84); prior approvals 0.996, prior commits 1.004, OWNERS 1.030
(0.963–1.101), tenure 1.127 (1.079–1.176). With the linear habit: 0.955
(0.929–0.982), −1.12 per 1,000.

Robustness of the log habit:

| Variant | OR (95% CI) | Per 1,000, p25 → p75 |
|---|---|---|
| main | 0.959 (0.930–0.987) | −1.44 (−2.42 to −0.43) |
| SEs clustered by first approver | 0.959 (0.928–0.990) | −1.44 (−2.49 to −0.36) |
| approvers with 20+ other CLs in the half-year | 0.967 (0.937–0.998) | −1.15 (−2.20 to −0.07) |
| CLs whose approvers come from Gerrit votes | 0.935 (0.908–0.962) | −2.42 (−3.41 to −1.41) |

**Reading.** A small protective association: an approver one SD more
thorough than usual (on their other CLs) goes with about 4% lower odds of a
revert, 1.4 fewer reverts per 1,000 CLs between the quartiles, about 5% of
all reverts. It survives clustering by approver, a less noisy habit, and the
votes-only subset. It disappears when the habit of the *most* thorough
approver is used instead of the first, and the descriptive deciles (D1) show
no dose-response below the top fourth. Expertise has no protective
association: more experienced approvers and OWNERS go with slightly *more*
reverts, the signature of hard CLs being routed to them. The approver's own
revert history predicts reverts (OR 1.20 per SD), but that is a property of
where they review.

## D5. Within author × dir3 × half-year, matched on size

56,217 sets with 2+ CLs (212,765 CLs); 4,495 sets with exactly one revert.
Conditional logit on those (author-clustered SEs), and a sign test of
whether the reverted CL had more of the exposure than the mean of its
set-mates.

| Exposure | Conditional OR (95% CI) | Sets | Reverted CL higher | Lower | Sign test p |
|---|---|---:|---:|---:|---:|
| threads (per doubling) | 1.27 (1.22–1.32) | 3,952 | 2,261 | 1,673 | < 0.001 |
| feedback index (per doubling) | 1.41 (1.33–1.49) | 3,952 | 2,190 | 1,762 | < 0.001 |
| addressed threads (per doubling) | 1.23 (1.18–1.28) | 3,330 | 1,718 | 1,598 | 0.04 |
| attention hours (per doubling) | 1.07 (1.05–1.09) | 3,542 | 1,875 | 1,667 | 0.001 |
| rounds (per doubling) | 1.35 (1.26–1.44) | 2,859 | 1,573 | 1,269 | < 0.001 |
| rubber stamp (yes vs no) | 0.69 (0.63–0.76) | 2,208 | 796 | 1,412 | < 0.001 |
| first approver's habit, log (per SD) | 0.97 (0.92–1.02) | 4,230 | 1,963 | 2,266 | < 0.001 |
| first approver's habit, residual threads (per SD) | 0.95 (0.90–1.01) | 4,230 | 1,947 | 2,274 | < 0.001 |
| approver prior approvals in dir3 (per doubling) | 1.03 (1.00–1.05) | 4,479 | 2,290 | 2,189 | 0.14 |
| OWNER approver (yes vs no) | 1.17 (1.04–1.32) | 1,514 | 904 | 610 | < 0.001 |

**Reading.** Even comparing an author's own CLs in the same directory,
half-year and size bucket, the more-reviewed one is the one that gets
reverted. Author skill is not what drives the positive association; the
risk the reviewer sees in the specific change is. For the habit, the sign
test leans protective (the reverted CL's approver was the less thorough one
in 54% of sets) but the conditional logit, which uses the size of the
difference, is null (0.97, 0.92–1.02).

## D6. Addressed vs unaddressed review at equal threads

- **(a)** Among CLs with 1+ thread (232,970), an addressed share above the
  median of the CL's threads band × size × dir2 × practice × half-year
  stratum: raw OR (share > 0.5) 1.32 (1.26–1.38), **MH OR 0.95
  (0.88–1.01)**.
- **(b)** Against no thread at all (123,576 CLs, 1.99%):
  - one addressed thread (18,226 CLs, 2.50%): raw OR 1.26 (1.14–1.40),
    **MH OR 1.24 (1.10–1.37)**;
  - one unaddressed thread (71,134 CLs, 2.10%): raw OR 1.06 (0.99–1.13),
    MH OR 1.08 (0.99–1.18).
- **(c)** Logistic with both counts and all controls: addressed threads OR
  1.10 (1.07–1.12) per doubling, unaddressed 1.19 (1.16–1.23).

**Reading.** At equal thread counts, having more of the threads addressed
goes with at most a 5% lower odds of a revert (CI 0.88 to 1.01), not
significant. A thread that made the author change something marks a CL
with *more* revert risk than a thread that did not, which again fits
reviewers finding real problems in risky CLs rather than review removing
the risk.

## D7. Heterogeneity

Logistic, all controls; reverts per 1,000 for p25 → p75 (95% CI).

| Subgroup | Threads (this CL) | First approver's habit, log | Habit, residual threads |
|---|---|---|---|
| dir2 revert rate, low tercile (< 2.34%) | +3.9 (+2.5 to +5.4) | −0.6 (−1.5 to +0.3) | −0.4 (−1.0 to +0.2) |
| middle tercile | +8.4 (+5.3 to +11.9) | −0.6 (−3.5 to +2.6) | −1.1 (−2.9 to +0.7) |
| high tercile (≥ 2.81%) | +12.5 (+10.6 to +14.4) | −1.6 (−2.9 to −0.3) | −0.8 (−1.8 to +0.2) |
| size < 32 lines | +3.8 (+2.8 to +4.9) | −1.6 (−2.6 to −0.6) | −0.9 (−1.7 to −0.2) |
| 32–255 lines | +6.4 (+5.0 to +7.8) | −1.2 (−2.6 to +0.2) | −0.8 (−1.7 to +0.1) |
| 256+ lines | +18.3 (+13.6 to +23.6) | −2.7 (−5.6 to +0.2) | −1.8 (−3.9 to +0.4) |
| author tenure < 2 years | +10.7 (+7.9 to +13.8) | **−2.7 (−4.3 to −1.0)** | **−2.2 (−3.4 to −0.9)** |
| 2–8 years | +8.5 (+6.7 to +10.5) | −0.9 (−2.5 to +0.6) | −0.7 (−1.7 to +0.3) |
| 8+ years | +8.6 (+6.7 to +10.6) | −1.2 (−2.9 to +0.6) | +0.0 (−1.2 to +1.2) |
| 2023-07 .. 2024 | +9.7 (+8.0 to +11.5) | −1.1 (−2.3 to +0.1) | −0.7 (−1.6 to +0.2) |
| 2025 | +8.9 (+6.3 to +11.7) | −2.3 (−4.5 to −0.1) | −1.3 (−2.7 to +0.3) |
| 2026 (to Sep) | +8.2 (+6.2 to +10.4) | −0.5 (−1.9 to +1.0) | −0.3 (−1.6 to +1.0) |

By outcome window (whole unit):

| Outcome (rate) | Threads | Feedback index | Rubber stamp | Habit, log | Prior approvals dir3 |
|---|---|---|---|---|---|
| ≤ 7 days (2.42%) | +8.4 (+7.3 to +9.5) | +7.8 | −6.2 (−7.4 to −5.1) | −1.3 (−2.1 to −0.5) | +1.2 (+0.1 to +2.5) |
| 8–30 days (0.26%) | +0.6 (−0.0 to +1.4) | +0.5 (+0.1 to +1.1) | −0.4 (−0.9 to +0.3) | −0.2 (−0.7 to +0.4) | +0.3 (−0.1 to +0.9) |
| ≤ 90 days (2.80%) | +9.6 (+8.2 to +11.0) | +8.6 | −7.1 (−8.5 to −5.6) | −1.4 (−2.5 to −0.4) | +1.7 (+0.4 to +3.3) |

(8–30 days excludes CLs reverted within 7 days from the risk set.)

**Reading.** The positive association of this CL's review with reverts is
everywhere: every directory tercile, size, tenure band and era, and both
the fast (CI breakage) and slower (8–30 days) reverts. The habit's
association is concentrated in newcomers' CLs (−2.7 per 1,000, the only
subgroup where both habit measures exclude zero) and in 2025; it fades in
2026 and for veterans. That pattern would fit a real but small effect of a
thorough first approver on inexperienced authors, but see D8 before
reading it that way. Almost all reverts happen within 7 days, so the
slower window has little power.

## D8. Negative control: reverts review cannot prevent

The revert study's classes (`revert_reasons.tsv`, matched on the reverted
and reverting commits; every 30-day revert in the unit matched):

| Class | 30-day reverts in the unit |
|---|---:|
| test failure | 4,195 |
| unknown | 1,591 |
| crash or functional | 1,345 |
| compile or link | 1,317 |
| flaky or unrelated | 644 |
| dependent or requested | 228 |
| perf or size | 182 |
| policy or process | 14 |
| security | 2 |

"Related" (review could in principle catch it): compile/link, test
failure, crash/functional, perf/size, security: 7,041 (19.7 per 1,000
CLs). "Unrelated": flaky/unrelated plus dependent/requested: 872 (2.45 per
1,000). "Other": unknown and policy: 1,605 (4.5 per 1,000).

| Exposure | Related: OR (CI) | per 1,000 | Unrelated: OR (CI) | per 1,000 | Other: OR (CI) |
|---|---|---|---|---|---|
| threads | 1.23 (1.21–1.26) | +7.2 | 1.13 (1.06–1.20) | +0.56 | 1.12 (1.04–1.21) |
| feedback index | 1.35 (1.30–1.39) | +6.9 | 1.15 (1.06–1.25) | +0.43 | 1.18 (1.07–1.30) |
| attention hours | 1.08 (1.07–1.09) | +7.0 | 1.04 (1.01–1.08) | +0.43 | 1.03 (1.00–1.06) |
| rubber stamp | 0.73 (0.68–0.78) | −5.8 | 0.85 (0.73–0.99) | −0.39 | 0.88 (0.74–1.05) |
| **first approver's habit, log** | **0.970 (0.943–0.998)** | **−0.76** | **0.952 (0.890–1.019)** | **−0.16** | 0.915 (0.825–1.015) |
| first approver's habit, residual threads | 0.976 (0.949–1.003) | −0.44 | 0.952 (0.886–1.022) | −0.11 | 0.932 (0.857–1.013) |
| approver prior approvals in dir3 | 1.018 (1.006–1.032) | +1.4 | 0.988 (0.959–1.018) | −0.12 | 1.015 (0.989–1.041) |
| OWNER approver | 1.099 (1.031–1.171) | +1.8 | 0.926 (0.782–1.097) | −0.19 | 1.047 (0.906–1.210) |

**Reading.** If thorough approvers prevented breakage, their association
should be concentrated in the related reverts and absent from the
unrelated ones. It is not: the habit's odds ratio for reverts no review can
prevent (0.95) is at least as protective as for those it can (0.97); in
relative terms −6.5% of unrelated reverts against −3.9% of related ones.
The "other" class (mostly unexplained reverts) is the most protective of
all (0.92). The unrelated class is small, so its interval is wide and
includes both 1.0 and the related estimate; the control cannot prove
confounding, but it removes the habit association's main claim to being
causal. The review-depth measures pass the same test in the expected
confounded way: they predict even unrelated reverts (threads OR 1.13),
which review cannot cause, so their positive association is at least
partly selection.

## What the data can and cannot exclude

- **Best case for review, as a causal upper bound:** the first approver's
  habit (D4, log scale, all CLs). Moving from a 25th- to a
  75th-percentile-thorough first approver avoids 1.4 reverts per 1,000 CLs,
  and at most 2.4 (the 95% bound; 3.4 in the votes-only subset). That is
  at most about 9% of reverts (about 12% in the votes-only subset, whose
  base rate is higher). The negative
  control and the null within-author result (D5) say the true causal share
  is probably smaller, possibly zero.
- **Adding review to an unreviewed CL** (a rubber stamp → one addressed
  thread): the stratified estimate is +24% odds (1.10–1.37), so the data
  exclude any reduction. But this comparison is the most confounded of
  all (a CL draws a comment *because* something looks off), so it shows
  the limits of the outcome, not harm from review.
- **Expertise** (prior approvals in the directory, OWNERS, tenure): alone,
  each excludes any protective association (p25 → p75, the CI's favourable
  end is +0.28 reverts per 1,000 for prior approvals in dir3 and +0.29 for
  OWNERS coverage, both in the wrong direction). In the joint model, with
  the habit and tenure held fixed, the bounds are −2.4 to +2.2 (prior
  approvals) and −0.9 to +2.5 (OWNERS): a protective effect of up to about
  2 per 1,000 is not excluded there, but nothing points to one.
- **ROI in the requested form** cannot be stated from reverts: there is no
  credible "X extra reviewer hours avoid Y reverts". If one took the habit
  estimate at face value, a quartile-to-quartile more thorough approver
  writes about 0.37 log units more threads than their norm (≈ 45% more
  threads; at the unit's mean of 3.0 threads per CL, about 1.3 extra
  threads per CL) and avoids about 1.4 reverts per 1,000 CLs, against the
  revert study's mean of 53 reviewer attention hours per revert-plus-reland:
  roughly 75 attention hours saved per 1,000 CLs for about 1,300 extra
  threads. That is an upper bound on a
  number the negative control says is mostly not causal.

## Caveats

- **Selection dominates.** Reviewers respond to risk the controls cannot
  see (subtle code, an unfamiliar subsystem, a CL that looked off). No
  design here has an exogenous source of review depth; the approver habit is
  the closest, and it is not randomly assigned either (approvers are chosen
  by directory, team and OWNERS, which also determine CI fragility).
- **Reverts are mostly CI breakage caught within a day** (91% of 30-day
  reverts are within 7 days). Review rarely aims at that; trybots do. Bugs
  that review catches before landing are invisible here.
- **22% of CLs have no Gerrit votes on disk** (no NoteDb meta ref: no
  comments). Their approvers come from git `Reviewed-by`, their threads are
  0 and they count as rubber stamps. The habit result is stronger, not
  weaker, on the votes-only subset.
- **Attention hours** are waiting time in someone's attention set, not
  working time, and exist only for CLs with a NoteDb timeline (78%).
- **OWNERS coverage** uses additions only (no removals, no `per-file`, no
  `include`/`file://`), so it overstates who was an OWNER at the time.
- **The habit** is within a half-year and needs 5 other approvals; 0.9% of
  CLs have no habit for the first approver. The design asked for "mean
  residual threads"; the log-scale version was added because it is more
  reliable (0.87 vs 0.75). Both are shown throughout and agree in sign; the
  log one is somewhat stronger, which is one more fork to discount.
- **Multiple comparisons.** Dozens of models were fitted; isolated
  subgroup results with CIs just excluding zero (newcomers, 2025) should be
  read as hypotheses.
- **Relands** were excluded as units and not analysed separately.

## Follow-up (2026-11-09)

`scripts/review_roi_part1_followup.py` on `cl_table_f.sqlite`. That is the
final table plus approval and sent times and the first approver's weekly
load; the unit and all other columns are unchanged. The run took 603 s.
Output is in `followup.txt` and `followup.json`, and the main numbers are
in `part1_results.json` under `followup`. All models have the D3 controls.
SEs are clustered by author, except in item 2, where they are clustered
by first approver.

### 1. Reverts review could plausibly prevent

The outcome is a 30-day revert of one reason class; reverts of other
classes count as non-events. Each cell gives the OR, then reverts per
1,000 CLs from the 25th to the 75th percentile.

| Exposure | Crash/functional + perf/size (4.3 per 1,000) | Compile/link + test failure (15.5 per 1,000) | All (26.7 per 1,000) |
|---|---|---|---|
| threads (per doubling) | 1.25 (1.20–1.31); +1.8 (+1.3 to +2.2) | 1.23 (1.20–1.26); +5.5 (+4.7 to +6.4) | 1.21; +9.0 |
| rubber stamp | 0.70 (0.63–0.79); −1.4 (−1.8 to −1.0) | 0.73 (0.68–0.79); −4.4 (−5.3 to −3.4) | 0.76; −6.6 |
| habit, log (per SD) | 0.947 (0.890–1.008); −0.30 (−0.64 to +0.05) | 0.976 (0.948–1.006); −0.47 (−1.06 to +0.12) | 0.959; −1.44 |
| habit, residual threads (per SD) | 0.937 (0.882–0.995); −0.26 (−0.50 to −0.02) | 0.986 (0.958–1.016); −0.20 (−0.61 to +0.23) | 0.966; −0.84 |

**Reading.** On the reverts review is best placed to prevent, the habit's
OR is slightly lower: about −7% relative, against −2% for CI-type reverts.
But it is no lower than for the unrelated reverts in D8 (0.952). Its
interval overlaps both, and the absolute effect is about 0.3 per 1,000 CLs.
Threads and rubber stamps look the same in every class.

### 2. The first approver's weekly load as an outside source of review depth

The load is log2 of the first approver's count in the CL's approval week
(ISO week, UTC) divided by their median active week in the half-year. It is
then demeaned within approver × half-year, so only week-to-week variation
for the same approver is used. CLs qualify when their first approver was
active in 4+ weeks of the half-year: 353,218 CLs in 7,121 approver-halves.

"Threads load" counts threads the approver wrote on *other* CLs that week.
The reduced form and IV columns are per 1,000 CLs; "per doubling" means a
doubling of the load.

| Load measure | First stage: residual log1p threads per doubling (F) | Reduced form, all reverts (LPM per doubling; logistic OR per SD) | Crash/perf | Compile/test | Unrelated (negative control) | IV per +1 log1p thread, all reverts |
|---|---|---|---|---|---|---|
| CLs approved | −0.040 (F = 397) | +0.41 (−0.44 to +1.25); 1.012 (0.988–1.037) | −0.18 (−0.49 to +0.13) | +0.42 (−0.15 to +0.99) | +0.09 (−0.15 to +0.32) | −10.2 (−31.5 to +11.1) |
| threads written elsewhere | −0.054 (F = 1,125) | −1.15 (−1.70 to −0.61); 0.954 (0.934–0.975) | −0.29 (−0.49 to −0.09) | −0.66 (−1.05 to −0.27) | −0.10 (−0.26 to +0.06) | +21.2 (+11.3 to +31.2) |

Both first stages are strong. The first approver writes fewer threads in a
busy week, and their CLs are more often rubber-stamped: +1.5 points per
doubling of CL load, F = 120. The CL-count instrument has a null reduced
form and passes the negative control.

Its IV estimate, −10 reverts per 1,000 CLs per +1 log1p thread, has a CI
from −31 to +11. For the 0.37-log gap between a 25th- and a
75th-percentile-thorough approver, that is −3.8 per 1,000 (−11.6 to
+4.1). It excludes neither zero nor an effect several times the D4
estimate.

The threads-load instrument points the other way: busy weeks go with
fewer reverts, an IV of +21 per 1,000 per log1p thread. That would mean
more review causes reverts, which is implausible. Its reduced form on
unrelated reverts has the same relative size (−4% per doubling, against
−4.3% for all reverts), so it most likely fails the exclusion
restriction. Weeks heavy with threads written elsewhere are probably
weeks of a different kind of work.

**Reading.** The cleanest outside variation in review depth shows no
detectable effect on reverts. It is too imprecise to rule out a modest one
(about 12 per 1,000 at the bound).

### 3. Glance approvals (votes on disk only)

A glance approval is the first approving vote less than 15 minutes after
the CL was sent, with no reviewer thread. 1,309 of 276,803 qualifying CLs
(0.5%) are glance approvals; most rubber stamps take longer.

| Comparison | 30-day revert | OR (D3 controls) |
|---|---|---|
| glance vs every other CL | 2.75% vs 2.87% | 1.07 (0.77–1.49) |
| glance vs slower rubber stamps (43,833) | 2.75% vs 2.07% | 1.27 (0.91–1.77) |
| matched sets (author × dir3 × half × size, 66 sets) | glance CL reverted in 15, the other in 51 | conditional OR 0.91 (0.44–1.88) |

**Reading.** Glance approvals are too rare to say much. Their revert rate
is at the overall level, higher than slower rubber stamps (1.27, not
significant). That direction is what one would expect if *some* look
matters. It doesn't change the rubber-stamp picture, which is driven by
CLs that needed no comment.

### 4. Rubber stamp, votes on disk only

There are 278,341 CLs with votes on disk. Rubber stamps are 45,381 of them
(16.3%), with a 30-day revert rate of 2.10% against 3.03% for the rest.

| | Raw OR | Stratified MH OR | D3 logistic |
|---|---|---|---|
| votes only | 0.69 (0.64–0.74) | 0.79 (0.73–0.85) | 0.81 (0.74–0.88); −5.6 per 1,000 (−7.4 to −3.5) |
| all CLs (Part 1) | 0.65 (0.62–0.68) | 0.76 (0.71–0.81) | 0.76 (0.72–0.81); −6.6 per 1,000 |

**Reading.** The CLs without votes on disk don't drive the result.
Rubber-stamped CLs are reverted about 20% less often at equal size, place,
author practice and era on the votes-only subset too.

### Does the follow-up change the Part 1 conclusion?

No.

- Restricting to preventable reverts leaves the habit association small
  (about 0.3 per 1,000) and no more specific than for unrelated reverts.
- The approver-load instrument is strong. Its credible version, CLs
  approved, finds no effect on reverts, with a CI of roughly ±12 per 1,000
  for a quartile-sized change in thoroughness.
- Glance approvals are rare and uninformative.
- The rubber-stamp result holds without the CLs that have no votes.
