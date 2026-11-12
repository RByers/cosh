# Addressed threads or all threads: which better tracks review's value?

Part of the Review Balance analysis (`docs/balance.md`), 2026-11-10. Script:
`scripts/balance_addressed_value.py`. Nothing was fetched and no model was
run: it reads the review-ROI per-CL table, `balance*.sqlite` and the
existing addressed labels (`labels.sqlite`, `docs/comment-classifier.md`:
precision 0.98, recall 0.99).

## The question

The balance page measures the review a CL received by the **feedback
index**: reviewer-started threads ÷ the 2023–24 mean for CLs of its size
(10 buckets) and 2-level directory. Value Exchange's classifier also says
which of those threads the author **addressed** (changed something in
response). Is an index built on addressed threads a better predictor of
review's value than the feedback index on its own?

- **Addressed index:** addressed threads ÷ the 2023–24 mean addressed
  threads for the same size and directory, built exactly like the feedback
  index. **Unaddressed index:** the same for the remaining threads.
- **Review value**, in the page's two senses (`#value`): direct (the code
  changed before landing; fewer defects escaped) and over time (authors
  need less review later and grow into reviewers and OWNERS).

Every quarter from 2023 Q3 is fully labelled (no unclassified threads). In
the unit (356,546 merged, human-owned, non-mechanical CLs landed
2023-07 .. 2026-09; `docs/review-roi-part1.md`), 58% of 1.07M reviewer
threads were addressed; 65% of CLs got a thread and 39% an addressed one.

## Short answer

**The addressed index is the better measure of the value review delivers
on the CL itself, and a sharper learning signal. It is no better at
predicting anything later.**

1. **Code changed after review:** the addressed count explains 26% of the
   variation in lines changed after the first review (within size ×
   directory × half-year), against 22% for all threads. Unaddressed threads
   explain 4.5% and add almost nothing once addressed ones are known.
2. **Learning curves are steeper:** a newcomer's CL (first 3 months) drew
   5.1× a 10-year veteran's addressed feedback for its size and place, but
   only 3.6× the feedback index (2023 H2–2024). The gap between the two is
   significant (ratio 1.44, CI 1.36–1.53), and holds for practice in the
   directory (1.20) and in 2026 (1.26). Veterans' threads are mostly ones
   they don't act on: the addressed share falls from 66% for newcomers to
   45% after ten years.
3. **Later outcomes:** reverts, bug-inducing CLs, line survival, becoming
   an OWNER, later review share: the addressed index predicts each about
   as well as the feedback index (same AUC or R² to two decimals) or not at
   all. The one small difference: at equal threads, CLs whose threads were
   all addressed were reverted about 0.3 points less (of 2.7%), weakly
   significant and in line with Part 1's D6.
4. **The unaddressed part is mostly noise or culture:** it has the flattest
   tenure gradient, barely tracks code change, goes with *more* reverts
   than addressed threads do, and predicts how many threads the author
   later writes on others' CLs (team review habit, as H2c found).

**Suggestion:** keep the feedback index as the measure of review *load*
(every thread costs reviewer and author time, addressed or not), and use
the addressed index where the page means review that *changed* something:
the learning curves (`#value-sources`) and "review's value shows in what it
changes". Neither one rescues reverts or later outcomes as evidence of
value; that remains the substance pilot's direct count
(`review-roi-substance.md`).

## On the page

`web/balance.html`, section 4, "Counting only the feedback authors acted
on" (`#acted-on`): the three indices by tenure (dataset `addr_tenure`), a
table of the main comparisons and two paragraphs (`addr_compare`), with the
note that labels start in July 2023, so the rest of the page still counts
all threads. The feedback-index definition and its popover say the same.
The datasets come from `balance_addressed_value.py report` (below).

## Results

### 1. Learning gradients (per CL, ratio of sums)

Newcomer ÷ veteran (first ÷ last bin), with 95% author-clustered bootstrap
intervals (200 resamples):

| Era | Gradient | Feedback index | Addressed index | Unaddressed index | Addressed ÷ feedback steepness |
|---|---|---:|---:|---:|---:|
| 2023 H2–2024 | tenure 0–3 mo ÷ 10+ y | 3.56 (3.15–4.03) | **5.12** (4.42–6.10) | 2.25 (2.03–2.53) | **1.44** (1.36–1.53) |
| 2023 H2–2024 | practice 0 ÷ 100+ commits in dir3 | 2.53 (2.34–2.75) | **3.04** (2.73–3.38) | 2.01 (1.89–2.13) | **1.20** (1.17–1.24) |
| 2026 | tenure | 3.23 (2.85–3.58) | **4.08** (3.47–4.63) | 2.38 (2.15–2.64) | **1.26** (1.19–1.33) |
| 2026 | practice | 2.43 (2.25–2.62) | **2.71** (2.48–2.98) | 2.11 (1.95–2.28) | **1.12** (1.07–1.17) |

By tenure, 2023 H2–2024:

| Tenure | CLs | Feedback index | Addressed index | Unaddressed index | Addressed share |
|---|---:|---:|---:|---:|---:|
| 0–3 months | 4,671 | 2.44 | 2.73 | 1.91 | 66% |
| 3–6 months | 2,104 | 2.12 | 2.35 | 1.68 | 66% |
| 6–12 months | 4,541 | 1.71 | 1.82 | 1.44 | 65% |
| 1–2 years | 23,866 | 1.34 | 1.43 | 1.15 | 64% |
| 2–5 years | 49,499 | 1.01 | 1.00 | 0.98 | 59% |
| 5–10 years | 43,751 | 0.80 | 0.71 | 0.89 | 52% |
| 10+ years | 28,954 | 0.69 | 0.53 | 0.85 | 45% |

(2026: the same shape, lower; addressed share 64% → 49%.)

Two readings of the falling addressed share, which the data can't separate:
reviewers' comments to veterans are more often optional (questions, FYIs,
"consider"), or veterans push back more and are right to. Either way the
part of the feedback index that does *not* fall with experience is the part
nobody acted on.

### 2. Direct value on the CL

Within size × dir2 × half-year strata, per doubling (log2 of 1 + count),
errors clustered by author. Within-R² is the share of the within-stratum
variance explained.

| Outcome | Predictor | Per doubling | Within-R² |
|---|---|---:|---:|
| Lines changed after first review ÷ final lines (165,003 CLs; mean 0.39) | threads | +0.240 | 0.224 |
| | addressed | +0.230 | **0.264** |
| | unaddressed | +0.119 | 0.045 |
| | addressed + unaddressed | +0.221 / +0.036 | 0.268 |
| Rounds (278,429 CLs; mean 1.0) | threads | +0.93 | 0.556 |
| | addressed | +0.96 | **0.618** |
| | addressed + unaddressed | +0.86 / +0.34 | 0.655 |
| 30-day revert, points (356,546 CLs; mean 2.67) | threads | +0.54 | 0.0012 |
| | addressed | +0.50 | 0.0009 |
| | unaddressed | +0.68 | 0.0011 |
| | addressed + unaddressed | +0.31 / +0.50 | 0.0014 |
| | threads + addressed share | +0.59 / **−0.28** (−0.49 to −0.06) | 0.0013 |

- The interdiff is measured from the code, the addressed label from the
  conversation, so their agreement is a real check: the label picks out the
  threads that changed the code. Rounds partly count rework after any
  thread by construction, so they're weaker evidence.
- Reverts: every measure of review goes with *more* reverts (Part 1:
  reviewers look hardest at risky CLs). Among CLs with a thread, the
  addressed-share effect is −0.19 points (−0.42 to +0.03); Part 1's
  matched D6 gave odds 0.95 (0.88–1.01). A weak hint at most.

### 3. Later defects (the review-ROI blame pilots, same samples)

| Sample | Measure | Feedback | Addressed | Unaddressed |
|---|---|---:|---:|---:|
| 418 CLs whose lines a later bug fix rewrote, minus their stratum's mean (log2 1 + count) | | +0.20 (0.06–0.33) | +0.23 (0.09–0.36) | +0.10 (−0.01 to +0.19) |
| same, index | | +0.16 (0.03–0.31) | +0.18 (−0.00 to +0.38) | |
| 298 CLs: correlation of share of added lines alive after a year with the stratum deviation | | −0.04 (−0.15 to +0.07) | −0.04 (−0.15 to +0.08) | −0.04 (−0.15 to +0.08) |

Bug-inducing CLs had more of every kind of review, addressed included;
survival is null for all three.

### 4. Over time: people (as in §4c of `balance.md`)

Unit: an author's half-year (2023 H2, 2024 H1, 2024 H2) with ≥ 6 merged,
non-mechanical CLs and a summed norm ≥ 3 threads: 3,503 person-halves,
1,516 people. Each index is relative to the median of the author's tenure
band in that half-year, log2. Controls are §4c's "full" set (log CLs
landed, tenure band, half-year, and the outcome during the half). Errors
clustered by person.

- **Reliability** (split-half by alternate CLs, Spearman–Brown):
  feedback 0.76, addressed 0.73, unaddressed 0.68. The two indices
  correlate 0.89 across person-halves (log), so they mostly rank people
  alike.

| Outcome (all person-halves) | Controls only | + feedback index | + addressed index | + addressed and unaddressed |
|---|---:|---:|---:|---:|
| OWNERS within 18 months (817 not yet OWNERS): AUC | 0.715 | 0.718; OR 0.87 (0.71–1.06) | 0.718; OR 0.89 (0.76–1.03) | 0.718; 0.87 / 1.03 |
| Review share next 12 months (3,169): R² | 0.550 | 0.552; −1.4 pts (−2.2 to −0.6) | 0.552; −0.9 pts (−1.5 to −0.4) | 0.552; −0.8 / −0.2 |
| Threads given next 12 months, log2 (3,503): R² | 0.678 | 0.678; +0.01 | 0.678; −0.01 | 0.679; −0.04 / **+0.08 (0.02–0.14)** |
| Feedback index next half, log2 (3,016): R² | 0.110 | **0.355**; +0.59 | 0.316; +0.38 | 0.353; +0.26 / +0.32 |
| Addressed index next half, log2 (3,016): R² | 0.116 | 0.308; +0.72 | **0.326**; +0.53 | 0.330; +0.48 / +0.13 |

(People under 2 years: the same pattern; OWNERS AUC 0.729 → 0.735
feedback, 0.734 addressed.)

- **Careers:** the addressed index adds no more than the feedback index
  to predicting OWNERS or review share, and both add almost nothing to
  volume and current reviewing (§4c's finding stands for either).
- **Learning:** if acting on feedback taught authors to need less, a
  person-half's *addressed* feedback should predict less feedback next
  half than unaddressed feedback does. It doesn't, clearly: +0.26
  (0.22–0.31) against +0.32 (0.25–0.39) per doubling, overlapping. Both
  persist: who draws feedback is a stable trait (H2c's "persistence, not
  learning"). Each kind mostly predicts more of itself.

## Caveats

- Association, not cause, throughout. "Value" here is what the data can
  observe; the classifier's label says the author changed something, not
  that the change was an improvement.
- The addressed label depends on the owner's reply. Authors who fix things
  silently, or reply "Done" to placate, blur it; the audit's 0.98
  precision is against the reply, not the diff.
- The steeper gradient could partly be veterans pushing back, not needing
  less. That still makes the addressed index the better measure of review
  that changed code, but not necessarily of skill.
- The blame samples are small pilots (418 and 298 CLs).

## How to regenerate

```bash
export COSH_DATA_DIR=/home/rbagent/projects/cosh/data/private
# Inputs: the review-ROI per-CL table (scripts/review_roi_table.py) and its
# shared inputs (docs/review-roi.md, package 0); blame scratch from
# scripts/review_roi_blame.py szz / survival.
R=$COSH_DATA_DIR/review_roi
nice -n 5 python3 scripts/balance_addressed_value.py cl --table cl_table.sqlite --out $R/addressed_cl.json   # ~1 min
nice -n 5 python3 scripts/balance_addressed_value.py blame --table cl_table.sqlite \
    --blame-dir <blame scratch> --out $R/addressed_blame.json                                             # ~1 min
nice -n 5 python3 scripts/balance_addressed_value.py people \
    --cache people.pkl --out $R/addressed_people.json                                                     # ~6 min
nice -n 5 python3 -m cosh.balance_publish     # turns them into addr_tenure and addr_compare (step addressed)
```

`report --cl F --blame F --people F [--out F]` prints the two datasets
without publishing. The 2026-11-10 run used the table built 2026-11-09
(`cl_table_f.sqlite`, 356,546 unit CLs) and the inputs regenerated that day.
