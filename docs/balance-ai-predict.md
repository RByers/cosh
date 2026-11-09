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

## Verdicts

- **Per CL: not reliable as a label.** With AUC ~0.82 against human text,
  Haiku has high precision only at cutoffs where it misses over half of AI
  CLs, and less still for 2025 CLs. Don't use it to mark individual CLs, and
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
  difference-in-differences against review load, using the flagged share
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
```

Each Haiku run of 300 descriptions takes about 30 s with 4 calls at once.
The CLI reported $0.02–0.03 per run and $0.14 for the trend.
