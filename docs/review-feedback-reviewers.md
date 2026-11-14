# Feedback Index: correcting for the reviewer

Purpose: decide whether the Feedback Index should compare each change
with what its own reviewers' approvals usually draw, instead of (or as
well as) what its directory draws. Analysis only (2026-11-14); nothing on
the page uses reviewers yet.

The question: rather than correcting for drift over time
(`docs/review-feedback-drift.md`), correct for the reviewer. Is the
reviewer a better predictor of addressed feedback than the directory, and
should the index use a reviewer factor overall, or one per directory and
reviewer?

## Short answer

Yes. The approving reviewer predicts how much addressed feedback a change
draws much better than its directory does, and the two together do best.
A factor per reviewer on top of today's directory and experience rates
cuts the prediction error by about five times as much as lowering the
directory minimum to 50 did, and directly covers the case that started the
drift study (a directory gets stricter OWNERS). About a fifth of people
with 25+ CLs would move by more than 20%. Building it means publishing
each change's approvers and a factor per reviewer, which needs the user's
call on how reviewers are shown (below).

## How it was measured

- **Reviewer:** the approvers in each landed commit's `Reviewed-by`
  trailers (`commits.sqlite` `reviewed_by`: those who voted Code-Review),
  owner removed, addresses folded as `cosh.people.person` does. That is
  mostly independent of the outcome: an approver is there whether or not
  they commented. 835,056 of the 872,196 CLs (96%) have one; 1.4 per
  commit on average.
- **CLs:** rebuilt from the published half-year files of 2026-11-14 (same
  rules as the index: inserted lines, addressed threads per directory,
  experience bins), joined to approvers by change number.
- **Test:** the one `docs/goals.md` uses to choose peer groups. Each model
  predicts every CL's addressed threads from other people's CLs (the
  owner's own left out of every rate and factor), with a factor per size
  bucket, scored by Poisson deviance (lower is better).
- **Reviewer factor:** a reviewer's approved CLs' addressed threads over
  what the base model expects on them, the owner's CLs left out, shrunk
  toward 1 with `m` expected threads (`(observed + m) / (expected + m)`).
  A CL with several approvers takes their mean; one with none, 1.
- Scripts: `data/private/scratch/feedback-drift/` (`load_rows2.py`,
  `reviewer.py`, `reviewer2.py` and their `.out`).

## Results

| model | deviance | gain over Chromium-wide |
|---|---|---|
| Chromium-wide, by experience (no directory, no reviewer) | 2,990,483 | – |
| directory by experience (the index now) | 2,824,586 | 165,897 |
| Chromium-wide × reviewer factor | 2,691,886 | 298,597 |
| directory × reviewer factor | 2,686,484 | 303,999 |
| directory × reviewer-in-2-level-directory factor | 2,661,884 | 328,599 |

- **The reviewer explains about 1.8× what the directory does**, and once
  the reviewer is known the directory adds little (5k). Reviewers mostly
  work in a few directories, so a reviewer factor carries most of what the
  directory did, plus how strict each reviewer is within it.
- **Shrinkage barely matters** (m = 5, 20, 50: 2,687,118, 2,686,520,
  2,686,484). Most reviewers have plenty of CLs.
- **Per directory and reviewer** (a factor per reviewer and 2-level
  directory, shrunk toward the reviewer's overall factor with 100 expected
  threads; 10: 2,674,916, 30: 2,666,098, 300: 2,663,449) adds about 25k
  more: some reviewers are stricter in one area than another.
- **Reviewers differ a lot:** among the 1,944 reviewers with 50+ expected
  threads, the factor runs 0.56 (10th percentile) to 1.48 (90th), quartiles
  0.74 and 1.21.

### Is it the reviewer, or the authors they review?

A reviewer who mostly approves newcomers' or one weaker team's changes
would look strict for reasons that are the authors'. Leaving the owner
out handles that for the person being rated, but a reviewer's factor still
mixes everyone else's authors. A two-way fit (author and reviewer factors
estimated together, alternating 8 times, m = 50) separates them:

- Reviewers keep their order: rank correlation 0.865 between the plain and
  the author-purged factors. So most of a reviewer's factor is the
  reviewer, but not all of it.
- People's index moves less with purged factors (rank correlation with
  now 0.971, against 0.958 for the plain factors on the same footing) and
  stays more consistent between odd and even CLs (0.724 against 0.698).
- As predictors the two are close (2,610,027 purged, 2,594,752 plain, both
  fitted on all CLs, so not owner-left-out and not comparable with the
  table above).

If this is built, the purged factors are the safer choice: they credit or
discount a person for their reviewers' strictness, not for their
reviewers' other authors.

### Effect on people (2,808 with 25+ CLs)

| index | 10th–90th percentile | odd/even | rank correlation with now | moved > 20% |
|---|---|---|---|---|
| now (directory by experience) | 0.42–1.96 | 0.741 | – | – |
| × reviewer factor | 0.46–1.91 | 0.717 | 0.959 | 21% |
| × reviewer-in-directory factor | 0.46–1.90 | 0.717 | 0.947 | 26% |
| × two-way (author-purged) reviewer factor | 0.45–1.88 | 0.724 | 0.971 | – |

The spread narrows a little: part of what looked like differences between
people was who reviewed them. Odd/even consistency falls, as expected when
a stable part of where someone works is taken out (`docs/goals.md`: that
test rewards coarser comparisons), so it doesn't argue against the change.

## Against the goals

- **Accuracy (goal: their own work, not where they worked).** The best
  predictor found so far, by a wide margin. It also takes away a way to
  look good: choosing lenient reviewers no longer lowers someone's index.
  Two cautions: who reviews a change isn't wholly outside the author's
  control or wholly independent of the change (harder changes may go to
  stricter, more senior reviewers, which the factor then credits the
  author for); and reviewers change over the years, which a factor over
  all the data averages.
- **Showing what a comparison is made of.** The page would need to show a
  person their reviewers and each one's factor ("changes approved by X
  draw 1.4× what their directory predicts"). That is a published
  per-reviewer strictness figure. It isn't review tone (ground rule 5),
  and stricter isn't worse, but a low factor reads as "lenient", so how
  it's shown is the user's call: on every page (a reviewer table), only
  in a person's own view after their address is typed (with reviewers
  keyed by hashed address, like person files), or not at all (factors
  used, not shown).
- **Repository volume.** The per-person files would gain each CL's
  approvers (a reviewer list per half-year file plus an index per CL):
  one rewrite of every half-year file, about 35 MB compressed, then the
  usual weekly churn. `peers.json` would gain the reviewer sums (two
  numbers per reviewer, a few thousand reviewers: tens of KB; a few times
  that per reviewer and directory).
- **Weekly update and tokens.** Local only: `commits.sqlite` already has
  the trailers after `cosh commits`. A two-way fit adds seconds. No model
  calls.

## Suggested next steps

1. Decide how reviewer factors may be shown (above).
2. Build directory × author-purged reviewer factor (the simpler overall
   factor first; the per-directory one adds about a fifth more of the
   gain for a larger table), with the person left out on the page as now.
3. Check it on the page against the script, as with the rates.

Not tried: reviewers who commented but didn't approve, a reviewer factor
per period, and per 3-level directory.
