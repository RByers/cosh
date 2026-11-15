# Feedback Index: correcting for the reviewer

Purpose: decide whether the Feedback Index should compare each change
with what its own reviewers' approvals usually draw, instead of (or as
well as) what its directory draws. Analysed and built on 2026-11-14: the
index now compares by experience and reviewer (below, "What was built").

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

## Which files did each approver review? (2026-11-14)

The analysis above credits every approver with the whole CL. Gerrit can't
say which files a reviewer read: the per-file "Reviewed" checkbox is
private to each account and isn't in NoteDb. The worry: reviewers who
often approve one file of a large CL get a factor made of other people's
reviews. Prototyped with OWNERS as the stand-in for "the files this
approver was there for".

**How.** `git log -p -- '*OWNERS'` over main's history (offline, 3 min)
gives every OWNERS line with the dates it was there, so each CL is judged
by the OWNERS of the day it landed: owners and `per-file` rules from the
file's directory up, `set noparent`, `file://` and `include`. An approver
covers a file they owned; a file none of the CL's approvers owned (5.3%
of the lines of CLs with several approvers) is covered by all of them.
Threads on the commit message or a file the landed commit didn't change
go by the approver's share of the directory's lines. The reviewer factor
then counts only covered lines and their addressed threads. Same test as
above (owner left out, m = 50).

**How common.** 30% of CLs have two or more approvers, and they hold 52%
of the expected and 65% of the addressed threads. Of their approver-CL
pairs, 33% own every file, 14% none, 53% some. Approvals of one file (or
under 20% of the lines) of a CL of 5+ files that someone else also
approved are 8.4% of approvals and those CLs carry 20% of approvers'
expected threads. Among the 1,657 reviewers with 50+ approvals, the share
of expected threads that comes from such CLs is 18% at the median, 43% at
the 90th percentile; 382 reviewers are at 30% or more and 98 at 50% or
more. So the outliers exist.

**But approvers don't comment by OWNERS.** From `reviews.sqlite`, each
approver's own threads on CLs with several approvers:

| the approver owns | approver-CLs | start a file thread | threads per CL | of those threads, on files they own | if spread by lines |
|---|---|---|---|---|---|
| no file | 86,377 | 37% | 1.27 | – | – |
| under 5% of the lines | 54,838 | 35% | 1.67 | 6% | 2% |
| 5–20% | 56,019 | 38% | 1.37 | 27% | 11% |
| 20–50% | 60,479 | 43% | 1.55 | 50% | 34% |
| 50–80% | 63,308 | 47% | 1.94 | 71% | 67% |
| 80–100% | 103,014 | 56% | 3.09 | 92% | 94% |
| every file | 208,241 | 39% | 1.54 | – | – |

An approver who owns a sliver of a CL comments a little less often and
about half as much as its main owner, and 94% of what they write is on
files they don't own. They lean toward their own files (6% against 2% by
lines) but mostly review the rest of the CL too.

**Prediction** (deviance over the 835,056 CLs with an approver; lower is
better):

| reviewer factors computed from | all | one approver (570,161) | several (264,895) |
|---|---|---|---|
| no reviewer factor | 2,751,586 | 1,305,593 | 1,445,993 |
| the whole CL, each approver in full (above) | 2,619,343 | 1,254,722 | 1,364,621 |
| the files each owned | 2,616,782 | 1,251,924 | 1,364,858 |
| the whole CL, split equally among its approvers | 2,615,605 | 1,250,915 | 1,364,690 |
| only CLs they approved alone | 2,657,115 | 1,262,870 | 1,394,245 |

- Each CL here is predicted with the plain mean of its approvers'
  factors. Weighting that mean by who owns which file is clearly worse
  (several approvers: 1,379,612 with owned-file factors, 1,380,904 with
  whole-CL ones), as the comment table suggests.
- One-approver CLs are the clean test, since nothing about them is
  attributed: factors from owned files predict them better than
  whole-CL factors (by 2,798, 5% of the reviewer factor's gain there),
  and for the 382 outlier reviewers' own one-approver CLs the gain grows
  from 3,313 to 4,663. So the worry is real: whole-CL credit does blur
  those reviewers' factors.
- **Splitting each CL equally among its approvers does as well as
  OWNERS, or a little better, and needs no OWNERS data.** A reviewer's
  factor is then weighted toward the CLs where they were the only or the
  main reviewer.
- Factors from CLs approved alone are much worse: too little data, and
  not the same kind of CL.
- (With the 37,140 CLs without an approver, which take factor 1, the
  totals are 2,686,484 whole, 2,687,390 owned files, 2,689,287 split:
  the factors' average level shifts and those CLs don't follow it. That
  is calibration, not ranking.)

**Reviewers and people.** Of the 1,944 reviewers with 50+ expected
threads, the owned-file factor over the whole-CL factor is 0.94 at the
median, 0.75–1.13 at the 10th–90th percentile and 0.52–1.77 at the
1st–99th (rank correlation 0.865); for the 98 strongest outliers
0.69–1.47. People's indexes barely notice: against the whole-CL reviewer
factor, owned-file factors move 5.6% of people by more than 10% and 0.9%
by more than 20% (rank correlation 0.996); the equal split 2.3% and
0.3% (0.998).

**Conclusion.** Don't attribute files by OWNERS: it isn't how approvers
review, and it would add a step (OWNERS history) for no gain. Share each
CL equally among its approvers in each reviewer's sums, and predict a CL
with the mean of its approvers' factors. That is what was built
(`two_way`, below), so nothing changes.

Limits: OWNERS says who could approve a file, not who did. A file's owner
by a `per-file` rule in an included file isn't found (`include` brings in
only global owners). Not tried: weighting approvers by their own comment
counts (it would leak the outcome into the predictor), and Gerrit's
attention set or reviewer-added times as a sign of who was asked to
review what.

Scripts: `data/private/scratch/feedback-reviewer-files/` (`owners_hist.py`,
`load_cov.py`, `measure.py`, `check_comments.py` and their `.out`).

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

## What was built (2026-11-14)

The user's call: "I definitely don't want to reward people for picking
less strict reviewers, so let's switch from using directories to using
reviewers." The index is everyone's AFR at the CL's experience × the CL's
approvers' mean factor, the factors from the author-and-reviewer fit
(`two_way` in `cosh/review_feedback.py`; directory left out: it added
little once the reviewer is known). Reviewer factors are shown only after
someone types an address: the person's reviewers, each with their factor
("Your reviewers"), looked up in `reviewers.json` by hashed address. The
methodology shows why (what each comparison predicts, reviewers within
the busiest directories) and the drift that remains
(`docs/review-feedback.md`).

Later the same day the person's own CLs were left out of their index's
rate and reviewer factors, so a reviewer who approves only one author
counts as typical for that author (`docs/review-feedback.md`, "The
person's own CLs are left out").

`two_way` shares each CL equally among its approvers in the reviewers'
sums, which "Which files did each approver review?" above found as good
as crediting by OWNERS.

Not tried: a reviewer factor per period, and per 3-level directory.

### Why not commenters (2026-11-14)

Using the reviewers who commented, instead of the approvers, looks far more
predictive (deviance 1,692,333 against 2,622,964 for approvers and
2,984,772 for experience alone), but it leaks the outcome: only 46% of CLs
have a reviewer thread, and a CL with no commenter has no addressed
feedback by definition. It would expect about nothing of clean changes
(removing their credit) and more of changes because they drew comments.
People's ranks would also shift more (rank correlation with the
experience-only index 0.77, against 0.88 for approvers). The attention set
leaks the same way, since commenting puts a reviewer back in it. Reviewers
added to a CL (NoteDb `Reviewer:` events), whether or not they commented,
would avoid the leak but weren't tried: the user doubted they'd do better.
The page's methodology explains the choice ("Why approvers, not
commenters"). Script: `data/private/scratch/feedback-drift/commenters.py`.
