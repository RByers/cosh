# Predicting AI-authored CLs from descriptions (draft, 2026-11-08)

Can a CL's description tell us it was written with an AI tool, when it
doesn't say so? The labels are the broad AI marker (`docs/balance-ai.md`).
The code is `scripts/balance_ai_predict.py`. It is offline apart from the
Haiku calls, which run through `cosh.sandbox` (no tools, scrubbed env,
bwrap), because descriptions are author text (SECURITY.md). Everything
here is aggregate.

## Data

`build` reads `main`'s first-parent history from the shared clone and
leaves out bots, reverts and relands. It also leaves out the dead-TODO
campaign, `[TDR]` CLs and automated spanification, which are templates.
Groups:

| Group | Period | CLs |
|---|---|---:|
| marked | 2025-07 .. 2026-11 | 1,873 (170 authors) |
| unmarked | 2025-07 .. 2026-11 | 169,554 |
| mid | 2024-07 .. 2025-06 | 103,765 |
| pre (pre-AI) | 2023-07 .. 2024-06 | 108,670 |

Each description is stripped so the marker can't give it away. Gerrit
footers are removed, along with every paragraph that mentions an AI tool
(whole paragraphs, so no sentence fragments are left as a tell). Bug lines
are dropped and numbers of 6+ digits are masked, because old and new bug
IDs date a CL. After that, 27 of the 1,873 marked descriptions still contain
"AI" or "agent", mostly in Chrome feature names. Half the marked CLs come from five
people, so every comparison caps each author (10 CLs for features, 3 for
Haiku, 2 per quarter for the trend).

## 1. Hand-built features: verbosity, little else

The expected cues are almost absent from committed descriptions, in every
group: markdown bold, headers, em dashes, "Key changes:", "comprehensive",
"ensure" (each under 0.1 per CL). Chromium descriptions are plain wrapped
text. What differs is **length**. Marked descriptions are about 1.5× as
long (mean 547 against 425 unmarked and 296 pre-AI characters), with more
backticks. A combined score gets AUC 0.66 against pre-AI CLs, 0.61 against
the same authors' pre-AI CLs, and only 0.55 against same-period unmarked
CLs. (AUC is the chance that a random marked CL scores above a random
other one; 0.5 is chance.)

Word choice is mostly **topic**. The words most over-represented in marked
CLs are "unsafe", "buffer", "span", "std": the unsafe-buffer cleanup that
people hand to agents. The rest are explanatory prose: "every", "each",
"both", "already", "still", "same". Several of those climb steadily from
pre-AI to unmarked to marked (e.g. "already" 2.2% → 6.3% → 9.8% of CLs),
which suggests unlabelled AI use among the unmarked CLs.

## 2. Haiku

`haiku` sends balanced samples, 10 descriptions per call, with a prompt
that lists AI and human cues. Haiku returns P(AI) for each one. 150 CLs per
side:

| Comparison | Haiku AUC | Feature AUC | Recall at p ≥ 0.5 | False positives at p ≥ 0.5 |
|---|---:|---:|---:|---:|
| marked vs pre-AI (2 seeds) | 0.82–0.83 | 0.64–0.67 | 0.36–0.41 | 1–2% |
| marked vs same authors' pre-AI CLs | 0.81 | 0.63 | 0.41 | 1% |
| marked vs pre-AI, unsafe-buffer topic removed | 0.80 | 0.70 | 0.37 | 1% |
| marked vs unmarked, same period | 0.64 | 0.53 | 0.37 | 19% |
| same, topic removed | 0.58 | 0.58 | 0.33 | 27% |
| placebo: unmarked 2025–26 vs pre-AI | 0.71 | 0.64 | 0.24 | 1% |

- **Against human text, Haiku is precise but misses most AI CLs.** At p ≥ 0.5
  it flags 1–2% of pre-AI CLs and 36–41% of marked ones. The result holds
  within the same people and without the unsafe-buffer topic, so it isn't
  just the person or the topic.
- **Recall depends on the period.** On marked CLs it is about 17% in
  2025 Q3, 16–36% in 2026 Q1–Q2 and 50–73% in 2026 Q3–Q4 (trailer CLs
  highest). Early AI-assisted CLs mostly have human-sounding descriptions.
  By 2026 the agent writes the description too. The three `Agent-Generated`
  authors write terse descriptions, and Haiku misses them.
- **It can't separate marked from unmarked CLs of the same period**, because
  Haiku flags many unmarked recent CLs too (the placebo row).

## 3. The trend: unmarked CLs, quarter by quarter

150 unmarked CLs per quarter, at most 2 per author (`trend`: 2,100
descriptions in 210 calls), with the plain length statistics over *all*
human CLs alongside:

| Quarter | Haiku p ≥ 0.5 | p ≥ 0.7 | Median chars (all) | > 800 chars (all) |
|---|---:|---:|---:|---:|
| 2023Q3 | 0.0% | 0.0% | 243 | 4.9% |
| 2023Q4 | 0.0% | 0.0% | 234 | 5.2% |
| 2024Q1 | 1.3% | 0.0% | 220 | 5.6% |
| 2024Q2 | 0.0% | 0.0% | 226 | 5.3% |
| 2024Q3 | 4.0% | 0.7% | 234 | 5.3% |
| 2024Q4 | 1.3% | 0.7% | 225 | 4.9% |
| 2025Q1 | 2.7% | 0.0% | 218 | 4.8% |
| 2025Q2 | 2.0% | 0.0% | 216 | 5.2% |
| 2025Q3 | 5.3% | 1.3% | 223 | 5.5% |
| 2025Q4 | 8.7% | 2.0% | 231 | 6.0% |
| 2026Q1 | 8.0% | 3.3% | 247 | 6.6% |
| 2026Q2 | 28.0% | 12.7% | 289 | 10.2% |
| 2026Q3 | 33.3% | 17.3% | 350 | 15.0% |
| 2026Q4 (to Nov 8) | 39.3% | 21.3% | 484 | 24.7% |

The flagged share is flat at 0–4% for two years, then jumps in 2026 Q2. The
length statistics for every human CL jump at the same time, after two flat
years. Style drift would be gradual, so this looks like adoption: by late
2026, a large share of descriptions are written the way marked AI CLs are.
If the 2026 recall (about 0.55) and 1% false-positive rate carry over,
roughly 50–70% of 2026 Q3–Q4 descriptions are AI-written. That is a rough
estimate: recall measured on marked CLs may not hold for unmarked ones.

## 4. How accurately can we estimate the share?

`estimate` fits the AI share of each quarter's unmarked CLs as a two-part
mixture: human CLs look like pre-AI ones (2023Q3–2024Q2), and AI CLs look
like a reference set of marked CLs. It reports 95% bootstrap intervals,
resampling the quarter, both reference sets and the fit. There are three
inputs: description length alone; length given diff size, so that growing
CLs can't pass for AI (`balance-git.sqlite`); and Haiku's p (150 CLs per
quarter from `trend`). The reference is marked CLs from 2026 Q2 on.

| Quarter | Length | Length given diff size | Haiku |
|---|---:|---:|---:|
| 2024Q3–2025Q2 (out-of-sample checks) | 0% (≤ 2.6%) | 0–2% (≤ 5.6%) | 2–6% (≤ 12%) |
| 2025Q3 | 0% [0, 2] | 1% [0, 4] | 11% [5, 19] |
| 2025Q4 | 1% [0, 4] | 3% [1, 6] | 17% [10, 25] |
| 2026Q1 | 4% [1, 9] | 5% [2, 9] | 21% [12, 31] |
| 2026Q2 | 25% [19, 32] | 20% [13, 25] | 47% [37, 56] |
| 2026Q3 | 47% [35, 53] | 33% [24, 36] | 64% [55, 75] |
| 2026Q4 | 100% [87, 100] | 78% [59, 76] | 73% [62, 83] |

**Sampling error is the small part.** The biggest error comes from what we
assume AI-written descriptions look like, and the marked CLs are the only
guide. For 2026Q3 by reference set:

| AI reference | Length given size | Haiku |
|---|---:|---:|
| marked 2026Q2+ | 37% | 64% |
| trailer rule only | 25% | 56% |
| phrase rule only (2026Q2+) | 30% | 70% |
| marked 2025 | 5% | 100% |

The 2025 marked CLs mostly have human-style descriptions (an agent wrote the
code, a person the description). Taken as the AI reference, they make
length see almost nothing, and make Haiku call everything AI. So the question
has to be narrower: what share of descriptions *read like 2026 agent output*.
With a 2026 reference, the answers range over about ±10 points between
references, on top of the bootstrap interval.

**Length alone is not enough:**
- It is blind before 2026. It estimates 0–1% in 2025 Q3–Q4, where Haiku finds
  11–17% and the marked CLs prove some use.
- It breaks as descriptions keep growing. In 2026 Q4, unmarked descriptions
  are longer than the marked reference, so the fit hits 100% (and with diff
  size, the bootstrap interval doesn't even contain the estimate).
- CLs got bigger too. Controlling for diff size takes 2026Q3 from 47% to
  33%.
- It can't tell a long human description from an AI one. Pre-AI
  descriptions over 800 characters are 5.2% of CLs, and Haiku flags only 4%
  of them.

**Haiku sees more than length.** At the same length, the share it flags
(p ≥ 0.5) rose from pre-AI to 2026 Q2+: 0% → 4% under 200 characters,
0.5% → 13% at 200–400, 0% → 52% at 400–800, and 4% → 80% over 800.

**Haiku's false-positive floor:** 0.3% of pre-AI CLs at p ≥ 0.5. Its
out-of-sample 2024Q3–2025Q2 estimates are 2–6%. That is either early AI use
or a few points of bias; the intervals reach 12%.

**What we can say with confidence:**
- A lower bound with no model of AI text: in 2026 Q4, 39% of unmarked CLs
  get p ≥ 0.5 against 0.3% before AI, so **at least about a third** of
  recent descriptions read as AI-written.
- The mixture estimate (2026 reference): **about 55–75% in 2026 Q3–Q4**,
  and 10–20% in late 2025.
- Quarter-to-quarter changes are much better determined than levels: every
  method and reference shows the same 2026 Q2 jump.

**To tighten it:** 600 CLs per quarter (about $0.50 in all) would halve the
Haiku sampling interval to about ±5 points. The reference problem needs
ground truth, though: for example, CLs whose description changed between
patch sets in the way agents rewrite them, or an author survey. Classifying
more cheaply won't fix it.

## 5. Per CL: how well can we tell?

**Descriptions, 2026 style.** This compares marked 2026 Q2+ CLs (174) with
pre-AI CLs (449), each scored once per CL. Haiku's AUC is **0.89**. Length
alone gets 0.77. Adding length to Haiku in a logistic model, cross-validated
by author, gets 0.888, so it adds nothing.

| Haiku cutoff | Recall (2026 marked) | False positives (pre-AI) | Flagged CLs that are AI* | Unflagged CLs that are AI* | Correct* |
|---|---:|---:|---:|---:|---:|
| p ≥ 0.3 | 82% | 16.5% | 88% | 24% | 83% |
| p ≥ 0.4 | 69% | 4.2% | 96% | 33% | 80% |
| p ≥ 0.5 | 53% | 0.9% | 99% | 42% | 71% |
| p ≥ 0.7 | 29% | 0.2% | 99% | 54% | 57% |

\* At a 60% AI share, about 2026 Q3 (§4). This assumes 2026's human
descriptions look like pre-AI ones and unmarked AI ones like marked ones.

So a **flag is trustworthy** (96–99% at p ≥ 0.4), but **no flag doesn't mean
human**: a third or more of unflagged 2026 CLs are still AI. Per CL it is
right about 80% of the time at best. That's good enough to select
likely-AI CLs for aggregate comparisons, but not to label every CL.

**2025-style CLs (AI code, human description).** Haiku on the description
gets AUC 0.74 against pre-AI CLs, with 23% recall at p ≥ 0.5.

**Can the code tell instead?** Not cheaply. `diffs` computes regex features
over the landed commits' added code lines (local shared clone): comment share, words per
comment, sentence-style comments, explaining comments ("ensure", "so that",
"note:"), test share and size. The AUCs, marked against pre-AI and against
the same authors' pre-AI CLs:

| Feature | 2025 marked | 2026 marked |
|---|---|---|
| test share | 0.59 | 0.57 |
| log added lines | 0.44–0.46 | 0.55–0.57 |
| comment share, words per comment, sentence comments | 0.34–0.38 (fewer) | 0.48–0.53 |
| explaining comments | 0.43–0.46 | 0.51–0.54 |

Marked 2025 CLs have *fewer* comments, but that is topic: many are small
unsafe-buffer fixes. Haiku given only the diff (`haiku-diffs`, first 3,000
characters, against the same authors' pre-AI CLs, 120 per side) gets AUC
0.71 for 2025 and 0.70 for 2026. Recall at p ≥ 0.5 is 17% and 36%, with 3–6%
false positives. Some of that may be topic too, since the comparison is with
older work. AI code in Chromium, after review and the author's edits, isn't
recognisable from the diff any better than from a 2025 description.
Diffs cost about 2× the tokens.

**Conclusion:** classify descriptions, and define the target as "the
description reads as AI-written". That is measurable (AUC 0.89 for current
tools) and is where adoption shows. AI-assisted code with a human
description is largely invisible, from the description or the diff, so
treat any estimate as a lower bound on AI involvement.

## 6. Haiku, Sonnet or Opus?

The same prompt, batches of 10 and identical items (`haiku --model
haiku|sonnet|opus --seed 3 --n 80`) went to all three models. The two samples
each have 80 marked and 80 pre-AI CLs, at most 3 per author. The 95%
intervals come from a paired bootstrap over the items. "Recall at 1 FP" is
the recall at the cutoff that lets through one of the 80 human CLs.

| | Haiku | Sonnet | Opus | Mean of 3 |
|---|---:|---:|---:|---:|
| **2026Q2+ marked:** AUC | 0.89 | 0.91 | **0.93** | 0.93 |
| difference from Haiku | — | +0.02 [−0.01, +0.06] | +0.04 [0.00, +0.08] | +0.04 [+0.01, +0.07] |
| recall at 1 FP | 0.59 | 0.75 | 0.74 | 0.74 |
| **All marked (with 2025):** AUC | 0.85 | 0.86 | **0.91** | 0.90 |
| difference from Haiku | — | +0.01 [−0.05, +0.06] | +0.06 [+0.01, +0.10] | +0.05 [+0.02, +0.08] |
| recall at 1 FP | 0.45 | 0.55 | 0.71 | 0.71 |
| CLI-reported cost per 1,000 CLs | ~$0.06 | ~$1.25 | ~$2.50 | |

- **Opus is better, mostly on the harder cases.** It gains 0.04 AUC on
  2026-style CLs and 0.06 with 2025's included. At a near-zero
  false-positive rate it catches 71–74% of marked CLs, where Haiku catches
  45–59%.
- **Sonnet's gain over Haiku is within noise** on AUC. It is mainly better
  calibrated: Haiku's false positives at p ≥ 0.3 (9%) fall to 0–1%.
- **Averaging the three models adds nothing over Opus alone.**
- The models agree on 87–95% of CLs at p ≥ 0.5. All three are fully
  precise at p ≥ 0.5 on these samples (0 or 1 false positive in 80).
- 80 per side is small: the intervals are about ±0.05 AUC.

**Choice:** Haiku is good enough for quarterly shares, where §4's error is
dominated by the reference definition, not the classifier. For per-CL
selection, e.g. a "likely AI" group of CLs to compare the feedback index on, Opus
raises recall by about 15 points at the same precision. At ~$2.50 per 1,000
CLs, scoring every landed human 2026 CL (120,110 to 2026-11-07) would cost
about $310 in CLI-reported usage, against about $150 for Sonnet and $8 for
Haiku. At 4 calls at once, each would take 2.5–3.5 hours.

## 7. Scoring every CL

`score` runs the classifier over every description in a date range and
stores one row per CL in `data/private/ai_predict/scores.sqlite` (table
`scores`: sha, model, prompt version, commit time, label, length, p). Each
batch is committed as it finishes, so stopping and rerunning the same
command resumes. Rows are keyed by model and a hash of the prompt, so a new
prompt or model starts a fresh set beside the old one. `report` prints the
monthly share of CLs flagged (p ≥ 0.5 and ≥ 0.7).

```
export COSH_DATA_DIR=<main>/data/private
python3 scripts/balance_ai_predict.py build        # first, to pick up newly landed CLs
python3 scripts/balance_ai_predict.py score --since 2025-07-01 --dry-run   # count and cost
nice -n 5 python3 scripts/balance_ai_predict.py score --since 2025-07-01   # 8 calls at once
python3 scripts/balance_ai_predict.py report
```

- Only the Claude API is called, through `cosh.sandbox`. Gerrit is never
  touched, so the serial-request rule doesn't apply (as with `cosh
  classify`). `ai_predict/score.lock` stops two runs at once.
- Failed calls are logged and skipped, and their CLs are picked up by the
  next run. After 5 failures in a row (a usage limit, say) the run stops.
  `runs` records each run's counts and why it stopped.
- **First run (2026-11-08):** Haiku, 2025-07-01 .. 2026-11-07, 171,804 CLs
  in 116 min at 8 calls at once, with no failed calls, $12.60 CLI-reported
  ($0.07 per 1,000). Log `ai_predict/score-20261108T2231.log`.
- Like the other Claude-made data (`labels.sqlite`, `sentiment.sqlite`),
  `scores.sqlite` costs Max usage to remake: don't delete it.

**Results (all landed human CLs, Haiku, prompt `3dd3ca1ff755`):**

| Month | CLs | Marked | p ≥ 0.5 | p ≥ 0.7 |
|---|---:|---:|---:|---:|
| 2025-07 | 9,257 | 30 | 6.5% | 1.7% |
| 2025-08 | 8,431 | 122 | 8.6% | 2.2% |
| 2025-09 | 9,455 | 72 | 8.6% | 2.0% |
| 2025-10 | 9,617 | 45 | 8.5% | 2.2% |
| 2025-11 | 7,780 | 58 | 8.9% | 2.3% |
| 2025-12 | 7,154 | 39 | 9.6% | 2.1% |
| 2026-01 | 9,118 | 32 | 10.3% | 2.6% |
| 2026-02 | 9,425 | 47 | 12.8% | 4.1% |
| 2026-03 | 10,686 | 120 | 15.7% | 5.2% |
| 2026-04 | 10,405 | 58 | 17.3% | 6.7% |
| 2026-05 | 10,139 | 63 | 20.8% | 8.8% |
| 2026-06 | 10,819 | 36 | 23.2% | 10.3% |
| 2026-07 | 11,608 | 89 | 27.2% | 14.7% |
| 2026-08 | 12,399 | 144 | 33.8% | 20.2% |
| 2026-09 | 13,701 | 250 | 39.0% | 22.5% |
| 2026-10 | 17,430 | 577 | 36.9% | 16.7% |
| 2026-11 (to 7th) | 4,380 | 91 | 37.0% | 14.7% |

- Pre-AI CLs score p ≥ 0.5 at about 0.3–1% (§2, §3), and 2024 Q3 –
  2025 Q2 samples at 1–4%. So July 2025 is already above baseline.
- Counting every CL, the rise is a steady ramp: flat at about 9% through
  2025 H2, then up every month from 2026-01 to 39% in 2026-09. The quarterly
  samples (§3) showed a sharper 2026 Q2 step. They counted each author at
  most twice per quarter, so they weight people equally, while this table
  weights CLs, which favours heavy authors.
- October's CL count jumped by 27% while the flagged share levelled off and
  the p ≥ 0.7 share fell (22.5% → 16.7%). §8 shows this is mostly Haiku
  losing recall on a new agent writing style, not adoption stalling.
- These are raw flag rates, which miss AI descriptions Haiku is unsure of. §4's mixture
  estimates run at about twice the sampled p ≥ 0.5 rate in every quarter
  (1.7–2.6×).

## 8. October 2026: more CLs, fewer confident flags

**Where the extra CLs came from.** September had 13,701 CLs and October
17,430 (+3,729). The extra CLs are **not** newcomers, mass edits or tiny
CLs:
- the share of authors under 6 months fell from 9.4% to 8.1%;
- the share of CLs with ≥ 100 files fell from 0.5% to 0.3%;
- the median diff stayed at 70 lines, and CLs of ≤ 10 lines went from 17.7% to 17.0%.

The same people wrote more: authors +5% (1,293 → 1,361), CLs per author
10.6 → 12.8. The 50 authors with the biggest gains account for 69% of the
increase. Half their October CLs are flagged (p ≥ 0.5: 48%), and the 10
biggest gainers carry 343 of October's 577 marked CLs. So the volume jump is
largely AI-heavy authors landing more CLs.

**Why the flags fell.** Everyone else's p ≥ 0.7 share also fell (22.4% →
15.9%), while descriptions got *longer* (median 409 → 479 characters).
Within every length band the confident share fell. At 300–600 characters,
for example, it went 20% (Sep) → 11% (Oct) → 7% (Nov). Haiku's recall on
known-AI CLs fell too: trailer-marked CLs dropped from 73% to 38% at p ≥ 0.7
and phrase-marked from 28% to 12%. So AI descriptions changed style.

Weekly, the confident share drops from the week of Sep 21 (W39) on. Over
the same weeks, the style of all descriptions shifted:

| | Jun | Jul | Aug | Sep | Oct | Nov |
|---|---:|---:|---:|---:|---:|---:|
| "This CL / change / patch" | 33.7% | 30.8% | 31.2% | 25.7% | 17.8% | 14.6% |
| first person (I, we) | 10.2% | 8.1% | 7.8% | 5.7% | 4.2% | 3.0% |
| `Test:` line | 3.7% | 4.0% | 4.3% | 4.1% | 6.8% | 7.7% |
| > 3 paragraphs | 25.8% | 25.9% | 28.8% | 32.6% | 34.4% | 33.2% |

**Likely causes**, from the shared clone (file names, dates and a few
lines read as data):
- 2026-09-09 and 09-11: `agents/prompts/templates/git_operations.md`, the
  shared template for agents' git work, now says a new patch set doesn't
  update the Gerrit description, and that agents must update it with `git
  cl description`. Landed descriptions would then carry later revisions,
  not just the first draft. Landing trails upload by a week or more, so
  this fits a drop from W39.
- 2026-10-16: 36 rule files under `agents/knowledge_base/rules/` on
  writing commit messages in Chromium style (e.g. "replace tool boilerplate
  with accurate commit description", "prefix commit message summary with
  subsystem"). `Test:` lines rise from the next week (5.9% → 9.3%).
- Model or tool upgrades may also play a part; nothing local shows them.

**Corrected for recall.** Dividing each month's flagged share by that
month's recall on marked CLs (leaving out the three-person `Agent-Generated`
group, whose terse descriptions Haiku misses anyway) gives:

| Month | Flagged | Recall | Corrected share [95%] |
|---|---:|---:|---:|
| 2026-07 | 27.2% | 50% | 54% [41, 76] |
| 2026-08 | 33.8% | 63% | 53% [46, 63] |
| 2026-09 | 39.0% | 75% | 51% [47, 57] |
| 2026-10 | 36.9% | 51% | 72% [64, 83] |
| 2026-11 (to 7th) | 37.0% | 20% (n = 50) | not usable |

Monthly recall is noisy, and marked CLs may not write like unmarked
ones. Still, October's share is more likely *higher* than September's,
not flat.

**Consequences:**
- A fixed classifier drifts as agent instructions and models change.
  Raw flagged shares after 2026-09 undercount, and comparisons across
  that date need a recall correction or a refreshed classifier.
- Cheap fix: estimate each month against a rolling AI reference (that
  month's marked CLs, as above, or the §4 mixture). This needs no new calls.
- Better fix: rewrite the prompt for current agent output and rescore
  2026-09 onward (about 35k CLs, ~$2.50 with Haiku). Or test whether Opus
  (§6) holds its recall on October's marked CLs before switching models.
- This also blurs AI-written and AI-assisted descriptions further. As
  agents learn Chromium's house style, the description stops being a
  reliable tell.

## Verdicts

- **Per CL: precise flags, unreliable negatives.** For 2026-style
  descriptions AUC is 0.89. At p ≥ 0.4, 96% of flagged CLs are AI, but a third
  of unflagged ones are too (§5). 2025-style CLs (AI code, human
  description) are mostly invisible, from the description or the diff. Don't use it to mark individual CLs, and
  never to name people (`docs/plan.md`, rule 5 spirit).
- **In aggregate: a useful adoption indicator.** The share of flagged
  descriptions per quarter tracks AI use with a flat pre-AI baseline, at
  roughly ±10–15 points on the level (§4). Description length alone moves
  with it in 2026, but it misses 2025, saturates in 2026 Q4 and is confounded
  with CL size. It could replace or complement the
  voluntary marker when comparing periods or directories on the balance
  page.
- **It measures AI-written descriptions, not AI-written code.** 2025's
  marked CLs mostly have human-style descriptions. A tool that only drafts
  descriptions would also raise the rate.
- **Verbosity is the user's hunch confirmed; distinctive wording mostly
  isn't.** The markdown and buzzword tells of chat output don't survive into
  Chromium descriptions.

## Next steps

- Per-directory or per-tenure flagged shares (aggregate only), and a
  difference-in-differences against the feedback index, using the flagged share
  in place of the 5% marker threshold (`docs/balance-ai.md` §3).
- Calibrate on a larger 2026 marked sample, and try Sonnet on a subset to see
  whether recall on 2025-style CLs improves.
- Check whether a Gerrit or `git cl` description generator launched in
  2026 Q2, which would explain the jump without coding agents.

## Regenerating

```
export COSH_DATA_DIR=<main>/data/private
python3 scripts/balance_ai_predict.py build        # ~1.5 min -> ai_predict/descs.jsonl
python3 scripts/balance_ai_predict.py features
python3 scripts/balance_ai_predict.py haiku --n 150 --pos marked --neg pre [--no-topic] [--seed 2]
python3 scripts/balance_ai_predict.py haiku --n 150 --pos marked --neg pre_same|unmarked
python3 scripts/balance_ai_predict.py haiku --n 150 --pos unmarked --neg pre
python3 scripts/balance_ai_predict.py trend --n 150
python3 scripts/balance_ai_predict.py estimate   # ~30 s, needs the haiku and trend outputs
python3 scripts/balance_ai_predict.py diffs      # ~30 s, regex features of the landed diffs
python3 scripts/balance_ai_predict.py haiku-diffs --period 2025|2026   # Haiku on diffs, ~$0.07
python3 scripts/balance_ai_predict.py haiku --n 80 --seed 3 --model sonnet|opus [--pos-since 2026Q2]   # §6
```

Each Haiku run of 300 descriptions takes about 30 s with 4 calls at once.
The CLI reported $0.02–0.03 per run and $0.14 for the trend.
