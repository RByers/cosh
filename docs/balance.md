# Author/reviewer balance: design notes and findings

Status: analysis done over all the data (2026-11-08); the page
(`web/balance.html`) is not built yet. Nothing was fetched for this:
everything comes from data already on disk (Gerrit 2023-07 .. 2026-10,
NoteDb, the patch-set commits of every reviewed CL, and `main`'s full
history).

## The question

The user's note *Agents and Accountability of Authors and Reviewers*
([Google doc](https://docs.google.com/document/d/1Zwq7exQ52CK34nGY8PrnWniOui5B7lsGSveZgqBpiFw/edit?usp=sharing))
argues that agentic tools make CLs cheap to write but not to review, which
moves effort from authors to scarce expert reviewers. Its principles:

1. Authors own the correctness and reviewability of their work.
2. Reviewers owe timely feedback.
3. Authors should learn from feedback, so their CLs need less review feedback
   over time.
4. Reviewers should get a return on their time, by building author skill.

The page asks: **does Chromium still grow and scale through review**, with
experts training newcomers who become experts and train the next ones, now
that AI tools are common? It looks at:

- per CL: change complexity, review difficulty, rework before landing,
  reverts and review latency, against what is typical for the code touched;
- the trends since 2025: larger CLs, more of them, slower and thinner
  review;
- growth: needing less feedback for a given size and area, taking on
  bigger changes or new areas, reviewing others, becoming an OWNER. People
  grow along different paths, so no single measure is used;
- the burden of supporting others: who reviews newcomers, how review moves
  from experts to people who were newcomers a few years earlier.

## Primary finding: the two growth trajectories (2026-11-08)

The user's call (2026-11-08): of everything here, two patterns are the
clearest trends showing growth, and the ones to optimize for.

1. **Feedback falls with tenure.** Before AI tools (2023 H2–2024), a CL
   from someone in their first three months drew 2.41× the 2023–24 review
   feedback for its size and directory, and after ten years 0.68×, falling at
   every step between (section 4). In 2026 the curve keeps its shape but
   sits lower (1.77× → 0.55×).
2. **Review share rises with years since joining.** Approvals given ÷
   (approvals + CLs landed) goes from nothing in year one (81% approve no
   one's CL) to a median of 51% by year five, and every join year from
   2017 to 2025 follows the same path (year-five medians 50–53%; section 6
   and `scripts/balance_review_share.py`).

The page leads with both (`#trajectories`, and the first paragraph of
"What we see so far"). Most people follow both. The question that follows is
who doesn't, and whether that is changing (section 0 below).

## Correction: identity merge (2026-11-08)

`balance_growth.load_all` merged a Gerrit owner's address with a commit's git
author whenever the two differed on even one CL. 648 one-off pairs (someone
landing another's CL, copybara imports) chained about 400 people into one
"person". Since the fix (`alias_pairs`), two addresses are merged only when
one owns at least 3 and at least half of the other's CLs. The largest merged
identity now has 2 addresses. Every figure on the page and in
`summaries/balance*.json` was regenerated, and the six tables that came from
`balance_growth.py` are now parsed by `scripts/balance_growth_tables.py`
instead of copied by hand.

What changed, by finding (older text further down still has the old
figures; the page has the corrected ones):

- **Authors per quarter:** about 1,650 in 2023 Q3, not 1,190.
  - CLs per author went from 16.7 to 23.0 in 2026 Q3, not 24.5 to 31.4.
  - The median author was steady at about 9 CLs a quarter; the rise is in
    the busiest authors.
- **Approval concentration was an artefact.** The busiest tenth of
  approvers gave 46% (2019), 45% (2024) and 48% (2026), not 57% → 68%.
- **Newcomers' approvers:**
  - 2–5-year reviewers gave 34% of approvals on newcomers' CLs in 2019 and
    21% in 2026, not 25% → 6%.
  - 10+-year reviewers gave 33%, not 69%.
- **Mentees who became mentors:** 19% (2018 joiners) → 9% (2022), not
  16% → 4%. The busiest tenth of mentors takes about a quarter of
  newcomers every year, so mentoring isn't concentrating.
- **Learning curves keep their shape.** By tenure: 2.41× in the first
  quarter → 0.68× after ten years (2023–24), and 1.77× → 0.55× in 2026. By
  familiarity: 1.70× → 0.66×.
- **Cohorts at 9–12 months, 2025 joiners against 2023 joiners:** 7.2 CLs a
  month against 3.0, feedback index 1.05× against 1.52×, and 2.4 reviews a
  month against 1.3. The 2025 joiners don't start with smaller CLs.
- **People improving on none of the four git paths:** 40% (2019–20), 45%
  (2023–24), 43% (2025–26).
- **AI-marked CLs:** with the identity fix, the trailer list still showed a
  first review 34 h sooner (95% interval 1–67 h, 47 author-quarters). The
  broader marker (`docs/balance-ai.md`, 2,527 commits, 201 author-quarters)
  replaces it on the page:
  - marked CLs are about 1.6× as large;
  - review, rework, waits and reverts don't differ;
  - the faster first review doesn't replicate.
- **Unchanged:** waits, reverts, rework, the feedback index and the mechanical
  rule, which don't depend on identities.

## Further analyses (2026-11-08)

Each has its own doc, with commands to regenerate:

- `docs/balance-signals.md`:
  - **−1 votes** (about 0.5% of reviewed CLs) fall with tenure and
    familiarity as steeply as the feedback index.
  - **Abandonment** rose from 5.7% to 8.0%.
  - **Same people, 2024 → 2026:** the same reviewers write 3% fewer
    threads, and the same authors get 9% fewer, while their rework and
    reverts are flat. That leans to reviewers easing off for established
    authors.
  - **Matched cohorts:** 2025 joiners keep their lead over matched 2024
    joiners, and their CLs change less after review. That leans to
    arriving better equipped.
- `docs/balance-ai.md`:
  - the broad AI marker;
  - same-author comparisons: marked CLs are larger and reviewed the same;
  - directory adoption: agent files don't predict use;
  - footers: not relevant.
- `docs/balance-ai-predict.md`:
  - predicting unmarked AI use from description style: Haiku is too weak
    per CL, but the flagged share per quarter jumps in 2026 Q2 after a flat
    pre-AI baseline.
- `docs/balance-clusters.md`:
  - six activity patterns and nine trajectories;
  - fewer recent joiners move into reviewing within three years.
- `docs/bugs-and-security.md`:
  - the Chrome Releases security fixes, with 2026's jump to about 3,900
    CVEs;
  - how bug-tracker data could be fetched (that needs approval).
- `docs/balance-addressed.md` (2026-11-10): an *addressed index* (threads
  the author acted on ÷ their 2023–24 norm) against the feedback index.
  It tracks code changed after review better (R² 0.26 vs 0.22) and falls
  more steeply with tenure (newcomer ÷ veteran 5.1× vs 3.6×), but predicts
  reverts, bug-inducing CLs, OWNERS and later reviewing no better. Keep the
  feedback index for load; use the addressed index for review that changed
  something.
- `docs/review-roi.md` (the page's `#roi` section, datasets `roi_*` from
  `scripts/review_roi_report.py`):
  - the return on review time: reverts can't show it, since more review
    goes with more reverts even like for like, and most reverts are CI
    breakage within a day;
  - no long-term payoff shows either (directory panels, newcomers, blame
    pilots);
  - what review does change, from a 200-thread pilot: mostly docs, style
    and design, with about 4.5% of addressed threads fixing something that
    would have broken.

## Goal and signals (as stated on the page, 2026-11-08)

**Goal.** Chromium has grown through code review: experts give feedback,
newcomers learn to need less of it, then review and own code and train the
next newcomers. AI tools make changes cheaper to write than to review. The
page asks whether that cycle still holds, and how the community can adapt to
agentic engineering in a way that improves product quality, robustness,
engineering rigour and velocity, and keeps growing its people into expert
engineers.

**Signals.**

- *Balance:* feedback index (threads against the 2023–24 norm for the
  CL's size and directory); CLs per reviewer.
- *Speed:* hours to first substantive review; attention-set waits.
- *Quality:* lines changed after review, rounds, reverts within 30 days.
- *Growth:* feedback index by tenure and familiarity; growth paths (velocity,
  size, breadth, reviewing, independence) against a shuffled null; cohorts.
- *Carrying the project:* review share by tenure, who approves newcomers,
  new regular reviewers and OWNERS, mentees who become mentors.

## Review of claims and goals (Fable, 2026-11-08)

A second review read the page and these notes against the data. Its factual
points were checked and hold, and the page now says:

- (Superseded by the identity correction below.) The review said about as
  many people comment as author. With identities fixed, 1,323 commenters
  served 1,694 authors in 2026 Q3, so fewer people review than author. Neither
  approvals nor threads concentrate much (busiest tenth: approvals 46% →
  48%, threads 56% → 57%). "Who carries the load" is now "How review is
  shared".
- Per-author velocity rose from 2023 (6.3 → 10.4 commits a month, mean), as
  active authors fell, not first in 2026. The median author has stayed at
  about 2 a month since 2017; the rise is in the top tail (90th percentile
  12.7 → 15.3).
- The median wait in 2026 Q3 (5.2 h) is back at 2023 Q3's (5.1 h), not a
  new high.
- New regular reviewers recovered from 68 (2025) to 99 by October 2026.
- The 2–5-year share of newcomer approvals fell partly because 2023–24 had
  the smallest intakes of new authors; it needs a per-capita version.
- "Joined" means first commit on `main`, which includes experienced
  engineers. The 2025 cohort's lower feedback index may be reviewers easing off.
  Its later points rest on few people, and it doesn't start with larger CLs.
  The heading is now "the 2025 joiners land more and review sooner".
- The AI-marked first-review difference (39 h, 95% interval 2–77 h, 41
  author-quarters, one of seven tests) is now worded "may have".
- Pages name groups only neutrally: "Growth paths by career stage" replaces
  "who isn't growing".

Still open from the review:

- per-capita newcomer review by tenure band;
- a balanced panel (people active in both 2024 and 2026) for velocity;
- splitting first-time contributors from people who were active in Gerrit
  before their first commit;
- colouring the directory table by feedback index rather than by a team's response
  time;
- folding the mechanical section into the method.

**Gaps against the goals** (all from local data unless marked):

- complexity beyond lines (files, directories, OWNERS approvals needed,
  non-test share);
- newcomers' thoroughness as reviewers (addressed threads per review,
  response time by months since joining);
- the distribution of reviewer load (concurrent CLs in a reviewer's
  attention set; share held over 24 weekday hours);
- `new_dir_share` (moving to new areas) on the cohort charts;
- review-driven vs author-driven rework (changed lines on files with an
  addressed thread);
- reviewability on arrival (uploads before sending, description length,
  `Bug:` footer);
- AI attribution beyond the trailer (tool names in messages, the sentiment
  AI-friction flags, and difference-in-differences by when a directory first
  uses the trailer).

A Gerrit backfill back to 2017-07 was approved and started on 2026-11-09
(`docs/plan.md`); its patch sets still need approval.

**Proposed additional goals for agentic engineering:**

1. Do tests travel with code (test co-change, test ÷ code lines)?
2. Post-land fixes: lines changed again within 30/90 days, by the same
   author or others.
3. Revert–reland cycles, including flaky-test reverts.
4. Does review depth track risk (security-sensitive trees against leaf UI)?
5. Do AI-era newcomers still learn (early feedback against later
   independence measured on author-side signals)?
6. Reviewer load sustainability and each directory's bus factor (approvers
   covering 80% of approvals).
7. Time to first OWNERS and to first approval of another's CL, by cohort.
8. Review conversation under agents (questions vs directives, addressed
   rate, AI friction).

Each would be shown as aggregates by quarter, cohort or directory group,
never by person.

## Next data and analyses (Fable, 2026-11-08)

A third review asked what to collect and what to run next. Its main
finding: much of the "new" data is already local and needs no approval.
Counts it found were spot-checked (27 `AGENTS.md`, 23 `GEMINI.md` and 620
`Agent-Generated` commits since July 2026 on `main`).

**Data, by value per cost:**

1. **Local, approved, CPU only.**
   - *Per-directory AI adoption dates:* first `AGENTS.md`, `GEMINI.md`,
     `agents/`, `.gemini/` or `.claude/` in each directory. This is a
     staggered treatment date for the difference-in-differences in item 3
     of the next list.
   - *A broader AI marker:* tool names and `Co-Authored-By` or
     `Assisted-by` trailers in commit messages, about 6× the trailer set and
     starting in 2025.
   - *NoteDb tags `derive` drops today:*
     - CQ dry runs and their results, a proxy for try-job quality;
     - work-in-progress uploads before sending;
     - who added which reviewer;
     - Code-Owners results, giving the OWNERS approvals each CL needed.
   - *Commit footers:*
     - `Bug:`/`Fixed:`, on about 75% of commits;
     - `Owners-Override`;
     - `Low-Coverage-Reason`, falling from 1,660 in 2024 to 273 in 2026;
     - `Auto-Submit`.
   - *Abandoned CLs:* 67,005 already in `balance.sqlite`.
2. **Gerrit backfill 2020-07 .. 2023-06** (**needs approval**; about
   11 GB and 2 days serial). It gives a four-year pre-AI baseline. The
   attention set starts late 2020, and interdiff would need those patch sets
   too (about 70 GB more, a separate approval).
3. **Bug-tracker metadata** for the `Bug:`/`Fixed:` IDs of reverts,
   relands and fixes, sampled (**new source, needs approval**). It would
   show regressions, security bugs and risk by directory.
4. **Chrome Releases security-fix lists** (**needs approval**; tiny), to
   tag security-fixing CLs.
5. Lower value:
   - other repos as comparison communities;
   - LUCI flake data (mostly covered by CQ tags);
   - patch sets of unreviewed CLs;
   - surveys or interviews (non-public; need approval and consent).

**Analyses on data we have:**

1. *Author-side vs reviewer-side decomposition* in balanced panels: do
   reviewers ease off, or do authors arrive better equipped? Reviewers' threads with
   reviewer fixed effects, against signals reviewers don't set: interdiff,
   rounds, CQ failures, WIP uploads, reverts, post-land fixes.
2. *Matched-cohort learning curves:* 2025 joiners against 2024 joiners
   matched on first-quarter size, directory, org and prior Gerrit activity.
3. *Event-study difference-in-differences* around each directory's first
   agent-instruction file, against not-yet-treated directories. Check
   pre-trends.
4. *Within-person comparison* on the broader marker, including each
   author's unmarked CLs before and after their first marked one.
5. *Event studies* around dated project events (`agents/` 2025-07-10, the
   AI policy 2025-08-01, the trailer 2026-07), against the same weeks of
   2023–24.
6. *Reviewer load and bus factor* per directory, with `Owners-Override`
   and `Auto-Submit` as stress signals.
7. *Quality beyond reverts:* post-land fixes, `Fixed:` chains, CQ failure
   rate, test co-change.
8. *Abandoned CLs:* review that stops a CL is the cycle working.
9. *Review conversation under agents:* a sandboxed Haiku pass.

**Its top five, in order:**

1. Mine the local signals into `balance.sqlite`.
2. Run the decomposition and matched cohorts.
3. Run the directory difference-in-differences and the broader
   within-person comparison.
4. Ask whether to approve the 2020–23 backfill.
5. Ask whether to approve sampled bug metadata and the security-fix list.

## The user's decisions (2026-11-08)

- **People:** aggregate and cohort views, plus an individual lookup, but no
  rankings. Leaderboards celebrate growth and contribution without shaming
  anyone, as the Review Tone page's praise boards do. Growth scores per
  person are computed only to be aggregated and are never published.
- **Mechanical CLs** can be toggled off, and the page defends the cutoff
  with its own chart (below).
- **All 175 weeks** of Gerrit data are used, plus `main`'s history for
  everything git can tell.
- **Latency** comes from the attention set, with a caveat that it doesn't
  know working hours.
- **Reverts** are tracked.

## Data and how it's built

`python3 -m cosh.balance <stage>` (offline, `GIT_NO_LAZY_FETCH=1`) writes
rebuildable files in `data/private/`:

| Stage | Output | What | Time |
|---|---|---|---|
| `git` | `balance-git.sqlite` | first-parent `main` since 2017-01-01: author, dates, CL (`Reviewed-on`), `Reviewed-by` approvers, reverts, relands, per-file line counts (`gcommits`, `gfiles`, `paths`); 1.30M commits | ~1.5 h |
| `timeline` | `balance-timeline.sqlite` | per CL from NoteDb: uploads with Gerrit's change kind, and attention-set intervals per account; 337k CLs (CLs with no comments have no local meta ref) | ~10 min |
| `interdiff` | `balance-interdiff.sqlite` | per reviewed CL: the first reviewed patch set's diff against the final one, as multisets of added and removed lines, so a rebase changes nothing; 275k CLs | ~25 min with `--shard i/3` |
| `cl` | `balance.sqlite` | one row per human-owned CL joining all of the above with review threads and labels (`cl`), per-reviewer attention (`cl_attention`), lines per directory (`cl_dirs`) | ~1 min |

Definitions in `cl`:

- **First substantive review:** the first inline reviewer comment, else the
  root of the first reviewer thread the owner answered. A lone "LGTM" isn't
  substantive review; 74,792 CLs with comments had none.
- **Sent for review:** the first time a non-owner human entered the
  attention set.
- **Rounds:** owner rework uploads after the CL was sent that follow a new
  reviewer-started thread.
- **Interdiff share:** lines that differ between the first reviewed and
  final patch sets' diffs, over the final diff's lines.
- **Attention hours:** the union of the intervals in which any non-owner
  human (or the owner) was in the attention set. It counts nights,
  weekends and holidays. `reviewer_wait_wd_h` leaves out Saturdays and
  Sundays in UTC, which is only a partial fix. The page calls the
  reviewer side, `reviewer_wait_wd_h`, **review time**: the weekday hours a
  CL was blocked waiting for review. `balance_report.py` gives its
  percentiles per quarter (`review_time_p5` .. `_p95` in `exchange`,
  drawn as bands, with p90 as a dashed line) and its median per
  directory (`review_time_p50` in `areas` and `dirs`), 2026-11-08.

Also used: when each person was first added to an OWNERS file (41,208
additions since 2012, from `git log -p -- '*OWNERS'`), each author's first
commit over all history (tenure), and the ~1,000 commits with an AI marker
in their message (`Agent-Generated:` trailer from 2026-07, "Generated with
Gemini" and the like from 2025).

People are joined across addresses: `chromium.org` and `google.com` by
username, SVN-era `user@domain@<uuid>` emails, and a Gerrit owner's email
with the git author of the same CL.

Analyses: `scripts/balance_analysis.py trends|mechanical|pipeline`,
`scripts/balance_growth.py growth|burden|ai`, `scripts/balance_dirgrowth.py`
(growth by directory, section 6c), and `scripts/balance_report.py`
(the datasets behind the published report). They print tables, read no
comment text, and print no one's identity. (`scripts/balance_explore.py`
is the first W44-only prototype, superseded by `cosh/balance.py`.)

## Findings

### 0. Falling behind the growth trajectories (`scripts/balance_behind.py`)

How often do people who still contribute significantly fall well behind
the two trajectories, and is that rate changing? Run 2026-11-08 (9,130
people after the identity merge). Shares only; nothing per person is
written.

**Behind on reviewing.** Person-years of people who joined in 2017–2025, in
years 3–9 since joining, who landed 24 or more CLs that calendar year (2
a month; 2026 prorated to the 10 months in the data): 3,038 person-years,
1,122 people. *Behind* means a review share under half the pooled median
for that year since joining (year 3: under 19%; year 5 and later: under
25–27%).

| Calendar year | People | Behind | Same tenure mix | Years 3–4 | Years 5–9 | Median share |
|---|---:|---:|---:|---:|---:|---:|
| 2021 | 331 | 13.9% | 13.6% | 14.9% | 9.7% | 47% |
| 2022 | 362 | 15.2% | 16.3% | 19.5% | 8.5% | 50% |
| 2023 | 451 | 16.0% | 16.2% | 16.8% | 15.1% | 47% |
| 2024 | 616 | 16.4% | 16.8% | 19.9% | 12.6% | 46% |
| 2025 | 502 | 19.7% | 21.7% | 22.3% | 18.0% | 46% |
| 2026 (to Oct) | 502 | 21.5% | 25.1% | 29.8% | 18.8% | 46% |

- **It is rising.** About one in six steady contributors was behind in
  2021–24; one in five in 2025 and one in four in 2026 (95% interval for
  the raw 2026 rate 18–25%, against 14–20% in 2024). The rise shows at 3–4
  years and at 5–9 years. 2019–20 (29%, 25%) hold only the 2017–18
  joiners in years 3–4, so they aren't comparable.
- **The median doesn't move** (46–50% since 2021), and the share approving
  nothing at all stays at 3–5%. The middle of the curve holds while the
  lower tail grows.
- **By join year, at year five:** 10% (2017 and 2018 joiners), 16% (2019),
  19% (2020), 18% (2021), 21% (2022). At year three it varies between 15%
  and 29% with no trend.
- **Robust to the thresholds.** Same-mix rate in 2024 → 2026: 21% → 28%
  with 12+ CLs landed; 15% → 20% with 48+; 11% → 18% with a cut at a third
  of the median; 31% → 38% at three quarters.
- **Lasting, often a phase.** Of people behind one year and counted the
  next, 53% are behind again, against 12% of everyone. Of the 518 people
  counted in three or more years, 31% were behind at least once and 5%
  three years in a row.

**Behind on feedback.** Person-halves of authors with 2 or more years
since their first commit and 12 or more merged, non-mechanical CLs in the
half-year (6 in 2026 Q3, the last whole quarter): 4,903 person-halves,
1,278 people. A person's feedback index is their CLs' reviewer threads ÷ the
sum of each CL's 2023–24 norm. *Behind* means 1.5× or more the median of
their tenure band (2–4, 4–8, 8+ years) in the same half-year. The 2023
H2–2024 medians were 1.02, 0.82 and 0.73.

| Half-year | People | Behind peers | 95% interval | Chance alone | Behind the 2023–24 curve |
|---|---:|---:|---:|---:|---:|
| 2023 H2 | 645 | 21.7% | 18.7–25.1% | 7.0% | 21.9% |
| 2024 H1 | 741 | 20.8% | 18.0–23.9% | 7.0% | 21.5% |
| 2024 H2 | 752 | 21.0% | 18.3–24.1% | 8.0% | 20.7% |
| 2025 H1 | 730 | 21.6% | 18.8–24.8% | 7.6% | 17.4% |
| 2025 H2 | 664 | 22.3% | 19.3–25.6% | 7.3% | 15.7% |
| 2026 H1 | 672 | 18.8% | 16.0–21.9% | 6.5% | 14.4% |
| 2026 Q3 | 687 | 26.1% | 22.9–29.5% | 10.8% | 13.1% |

- **Level, not rising.** Relative to peers in the same half-year, about
  21% are behind throughout. 2026 Q3 is a single quarter with half the CLs
  per person, so its noise floor (*chance alone*) is higher too; the
  excess over chance (12–15 points) is steady.
- *Chance alone* deals each half-year's and band's CLs out to the same
  people at random (20 times) and counts how many land 1.5× over the
  median: 7.7% overall. About two thirds of those behind are beyond noise.
- **Against the fixed 2023–24 curve**, fewer people are behind each year
  (22% → 13%), but that is the project-wide drop in review feedback
  (section 4), not people catching up.
- Of people behind one half-year and counted the next, 48% are behind
  again, against 19% of everyone.

**Is it the same people?** Among person-years in both sets, people behind
on reviewing also had a half-year behind on feedback 30% of the time in
2024 (others 27%), but 48% in 2025 (others 30%) and 41% in 2026 (others
28%; about 95 people behind each year). Tentative: in 2025–26 the two
groups started to overlap.

**Reading.** The learning curve (needing less review) is holding for the
same share of people as before. The step into reviewing is what more
steady contributors miss now, and since 2025 they are more often also the
people still drawing heavy review. It fits the other signs that fewer
recent joiners move into reviewing (section 6, `docs/balance-clusters.md`)
and that per-author velocity rose in the top tail: landing more without
approving more lowers review share. What causes it (team structure,
OWNERS coverage, time pressure, AI tools) isn't something this data shows.

Rerun (about 6 min; `--cache` keeps the loaded data for reruns,
`--explore` prints the threshold, volume and overlap checks and writes
nothing):
`COSH_DATA_DIR=<main>/data/private python3 scripts/balance_behind.py
--first-commit F --owners-added O --mech M` (writes `behind_share_*` and
`behind_feedback*` into `summaries/balance.json`).

### 1. The exchange since AI: more and bigger CLs, thinner review

Human commits on `main` with a CL, and merged human-owned CLs, by quarter:

| Quarter | Commits per active author per month | Median lines | p90 lines | Reviewer threads per CL | Standardized threads per CL (half-year) |
|---|---:|---:|---:|---:|---:|
| 2019Q3 | 5.7 | 39 | 391 | | |
| 2022Q3 | 4.8 | 42 | 386 | | |
| 2023Q3 | 5.5 | 38 | 346 | 3.19 | 3.10 |
| 2024Q3 | 5.8 | 45 | 393 | 2.97 | 2.85 |
| 2025Q1 | 5.6 | 43 | 366 | 2.89 | 2.78 |
| 2025Q3 | 6.3 | 42 | 360 | 2.75 | 2.64 |
| 2026Q1 | 6.5 | 44 | 359 | 2.75 | 2.47 |
| 2026Q2 | 6.7 | 52 | 386 | 2.76 | |
| 2026Q3 | 7.6 | 65 | 445 | 2.61 | 1.98 (2026H2) |

- **Velocity and size broke out in 2026, not 2025.** Commits per author
  stayed between 4.5 and 6.5 a month from 2017 to 2025, then reached 7.6 in
  2026Q3.
  Median CL size, flat at 38–46 lines for nine years, rose to 65 (and 72
  in the partial 2026Q4). The largest CLs grew less: the share ≥ 1,000
  lines stayed at 2.5–3.1%.
- **Review per line fell.** Reviewer threads per 100 changed lines (mean
  per CL, CLs ≥ 10 lines) went 4.3 (2023Q3), 3.9 (2025Q1), 2.8 (2026Q3).
- **It isn't composition.** Re-weighting every half-year to 2024's mix of
  author tenure, CL size (10 buckets) and directory, threads per CL go
  3.10, 3.07, 2.85, 2.78, 2.64, 2.47, 1.98 (2023H2 .. 2026H2). The fall is
  steeper after standardization, because CLs got bigger.
- **Reverts did not rise.** Landed CLs reverted within 30 days: about
  3.5% in 2017–2020, 3.0% in 2022–23, 2.6–2.8% in 2024–25, and 2.6–3.0% in
  2026 (2026Q4's 1.9% isn't final yet). Relands per quarter rose with
  volume (~420 to 562).

### 2. Latency: faster in 2025, slower again in 2026

Merged human-owned CLs that got substantive review:

| Quarter | Hours sent → first substantive review (p50, p75) | Reviewer attention hours per CL (p50) | Owner attention hours (p50) |
|---|---|---:|---:|
| 2023Q3 | 5.2, 22.5 | 18.3 | 22.4 |
| 2024Q3 | 3.7, 19.7 | 15.5 | 9.7 |
| 2025Q2 | 3.3, 18.2 | 12.4 | 10.9 |
| 2026Q1 | 4.3, 20.4 | 16.2 | 15.7 |
| 2026Q3 | 5.2, 22.4 | 17.9 | 17.6 |

Review got faster through 2025Q2 and has slowed every quarter since, as
volume rose. Owner attention time rose too: CLs wait longer on both sides.
Hours count nights and weekends, so the medians reflect time zones as much
as effort. Per reviewer, weekday attention hours per CL for reviewers with
10+ years' tenure went from 5.6 (2025H1) to 8.8 (2026H2).

### 2b. Blink's rise in review delay (2026-11-08)

The CLs here are merged, human-owned CLs under 100 files whose landed
commit has most of its lines in `third_party/blink/`, and that got a
substantive first review: about 39% of them each quarter. Hours run from
when the CL was sent to its first substantive review. The comparison is
A = 2024Q1–2025Q2 against B = 2026Q2–Q4. 2026Q4 runs only to early
November.

| Quarter | Reviewed CLs | p25 | p50 | p75 |
|---|---:|---:|---:|---:|
| 2024Q2 | 1,158 | 0.8 | 5.3 | 22.0 |
| 2025Q2 | 1,291 | 0.8 | 4.2 | 19.9 |
| 2025Q4 | 1,028 | 1.2 | 8.6 | 27.3 |
| 2026Q2 | 1,425 | 1.5 | 10.8 | 34.6 |
| 2026Q3 | 1,465 | 2.0 | 12.3 | 45.6 |

From A to B the median went from 5.6 to 12.2 h and the p75 from 22 to
43 h. CLs reviewed within an hour fell from 26% to 18%, and waits over a
day rose from 23% to 33%. Over the same time the Chromium-wide median went
from 3.3 to 5.2 h. Blink slowed about twice as much as the project, and
about as much as `content/browser` (section 6c).

- **The mix of CLs explains about 1 h of the 6.6.** B's CLs were given A's
  waits for CLs of the same org group, size, author tenure and
  Friday/weekend send. That gives a median of 6.6 h, against 12.2 h
  actual. The mix shifts are real but small:
  - Microsoft-owned CLs rose from 10% to 17% of reviewed blink CLs, and
    they wait about twice as long as Google-owned ones (10 → 19 h).
  - Authors in their first year in blink rose from 10% to 17%.
  - The median CL grew from about 40 lines to 57–65 by 2026Q3–Q4.
- **Every group slowed about 2×.**
  - Google-owned CLs went from 4.6 to 8.9 h, and CLs by authors with 4+
    years in blink from 4.9 to 11.1 h.
  - Every size band, both `renderer/` and `web_tests/`, and every number
    of reviewers slowed.
  - Same-day turnaround was lost most: CLs sent 16–20 UTC (US mornings and
    afternoons) went from 3.0 to 10.4 h, and Friday sends from 4.9 to
    15.2 h.
- **Load per reviewer rose.**
  - People who were in the attention set of 5+ blink CLs in a quarter
    numbered 175–182 in 2024Q4–2025Q2 and 149–164 in 2026, while blink
    CLs rose.
  - Blink CLs per such reviewer went from about 24 to 29–31 a quarter.
  - The 30 busiest blink reviewers of A mostly stayed: only 2 cut their
    blink rate by three-quarters. The rest went from a median of 47 to 62
    blink CLs a quarter, and from 97 to 109 CLs across all of Chromium.
  - 34 reviewers had enough CLs where they were the only reviewer in both
    periods. The 27 whose load rose 25% or more got slower by a median of
    2 h. The 7 whose load didn't rise got 0.5 h faster, though that is a
    small group.
- **It happened in two steps.**
  - From mid-2025 to early 2026 the median rose to 7–12 h while blink's
    volume stayed flat and its reviewer pool shrank (130 in 2025Q4).
  - From 2026Q2, volume rose. Lines merged in blink went from about 140k a
    month to 220k in September 2026 and 286k in October. October also had
    a record 1,854 CLs from 332 authors, a broad rise, not a few authors.
- **AI-marked CLs are under 1% of blink's**, too few to say whether
  AI-written code plays a part.
- Approvers' growth, and whether it explains the delay, is in section 6c.

These numbers come from ad hoc queries of `balance.sqlite`.
`scripts/balance_dirgrowth.py` reproduces the A/B medians and the
blink drill-down.

### 3. Rework after review

After the first substantive review, a reviewed CL's diff changed by a
median 5% of its lines (p75 44%, p90 96%). Pooled, lines changed over final
lines were 0.37 (2023Q3), 0.28–0.31 (2024), 0.31–0.36 (2025–26). Owner
rework uploads after review: 3.0 (2023), 2.8–3.1 (2024–25), 3.1–3.2
(2026). Rounds per reviewed CL: 1.25 (2023), 1.11–1.17 (2025), 1.18–1.20
(2026). CLs aren't landing in better shape in the AI era, and they aren't
clearly worse.

In the 2026-W44 prototype, 98% of files with an addressed thread changed
after review, against few of the files whose threads weren't addressed.
The interdiff and the classifier agree.

### 4. Learning curves: needing less feedback, before and after AI

**Feedback index:** reviewer threads on a CL ÷ the mean for CLs of its
size (10 buckets) and top 2-level directory in 2023–24 (1.00 = the
2023–24 norm). Merged, non-mechanical CLs:

| Author tenure | 2023H2–2024 | 2025 | 2026 |
|---|---:|---:|---:|
| < 6 months | 2.43 | 2.00 | 1.45 |
| 6–12 months | 1.89 | 1.66 | 1.10 |
| 1–2 years | 1.50 | 1.68 | 0.96 |
| 2–5 years | 1.08 | 1.06 | 0.85 |
| 5+ years | 0.86 | 0.78 | 0.66 |

| Author's prior commits in the CL's main directory (3 levels) | 2023H2–2024 | 2025 | 2026 |
|---|---:|---:|---:|
| 0 | 1.82 | 1.75 | 1.34 |
| 1–4 | 1.57 | 1.38 | 1.12 |
| 5–19 | 1.24 | 1.11 | 0.94 |
| 20–99 | 0.96 | 0.93 | 0.75 |
| 100+ | 0.81 | 0.75 | 0.63 |

- **The learning signal is clear before AI.** A newcomer's CL drew 2.8×
  the review of a 5-year veteran's at the same size and place, and a first
  CL in a directory 2.2× that of someone with 100+ commits there.
- **In 2026 everyone gets less review feedback, and newcomers lose the most.** A
  newcomer's CL fell from 2.43 to 1.45 of the old norm, a veteran's from
  0.86 to 0.66. The newcomer-to-veteran gap narrowed from 2.8× to 2.2×.
  That's either newcomers arriving better equipped (such as with effective AI tools), or
  reviewers giving newcomers less of the feedback that trains them. The
  data can't yet tell which. Section 6 suggests the second is at least
  part of it, since the same experts are spread thinner.

### 4b. Practice or time: commits landed against tenure

`scripts/balance_learning.py` (2026-11-08) asks whether review need falls
with months on the project or with CLs landed. Authors whose first commit
is in 2017 or later (so `balance-git.sqlite` holds all their commits);
merged, non-mechanical CLs of 2023Q3–2024Q4 (112,615 CLs, 2,158 people).
"Practice" is the author's commits on `main` before the CL.

- **Practice predicts about twice as well.** Share of the variance in the
  calendar-adjusted thread residual explained by bin means: tenure 3.5%,
  practice 7.6%, both 7.9%. Spearman ρ with the residual: −0.15 and −0.24.
  Within a practice bin, tenure barely correlates (ρ −0.11 to +0.06);
  within a tenure bin, practice still does (ρ −0.16 to −0.37). In
  2025Q4–2026Q3 (`--era now`): 5.3%, 8.2%, 8.4%, same pattern.
- **Prolific newcomers learn faster by the calendar, not per CL.** Groups
  by commits landed in the first 12 months: the top fifth (34 or more,
  "prolific") and the middle fifth (3–9, "average"). Feedback index in the
  second year: 1.18 against 1.84. By commits landed: 0–9, 2.84 against
  2.82; 30–99, 1.54 against 1.39; 100–299, 1.14 against 0.91. Per CL the
  average group learns at least as fast. Points with fewer than 200 CLs
  or 20 people are left out.
- Caveats: groups are by first-year output, so they may also differ in
  role, team and kind of work. This is association, not cause.

Rerun: `COSH_DATA_DIR=<main>/data/private python3 scripts/balance_learning.py
--first-commit F --owners-added O --mech M` (writes `learning_practice` and
`learning_practice_fit` into `summaries/balance.json`; `--explore` prints the
tenure × practice table instead; about 5 min).

### 4c. Does the feedback index predict reviewing and owning? (`scripts/balance_feedback_predicts.py`, 2026-11-08)

Unit: an author's half-year (2023 H2, 2024 H1, 2024 H2) with 6 or more
merged, non-mechanical CLs whose summed 2023–24 norm is at least 3 threads:
3,503 person-halves, 1,516 people. The predictor is their feedback index
that half-year divided by the median of their tenure band (under 1, 1–2,
2–4, 4–8, 8+ years) in the same half-year, so 1.0 is typical for their
tenure and era. Outcomes after the half-year ends:

- first added to any OWNERS file within 18 months (only the 786
  person-halves not yet in one; 78% already are);
- review share (approvals ÷ (approvals + CLs landed), git) over the next 12
  months, among people with 6 or more of either;
- review threads started on others' merged CLs per month over the next 12
  months.

By fifth of the relative index (least feedback → most):

| | Least | 2nd | Middle | 4th | Most |
|---|---:|---:|---:|---:|---:|
| Index (median, relative) | 0.46 | 0.75 | 1.00 | 1.34 | 2.12 |
| CLs in the half (median) | 37 | 39 | 35 | 29 | 18 |
| OWNERS within 18 mo, under 2 y | 36% | 35% | 47% | 22% | 20% |
| OWNERS within 18 mo, 2+ y | 27% | 29% | 19% | 20% | 28% |
| Review share next year, under 2 y | 46% | 43% | 40% | 38% | 28% |
| Review share next year, 2+ y | 63% | 62% | 61% | 58% | 53% |
| Threads given per month, median, all | 7.0 | 10.3 | 8.4 | 5.7 | 2.3 |

Fits per doubling of the relative index, standard errors clustered by
person. *Volume* controls for log CLs landed in the half, tenure band and
half-year; *full* adds the same outcome measured during the half (review
share, and threads given; both for OWNERS):

| Outcome | Group | Volume | Full | Per doubling of CLs (full) |
|---|---|---:|---:|---:|
| OWNERS (odds ratio) | all | 0.83 [0.69, 1.01] | 0.84 [0.69, 1.02] | 1.64 [1.33, 2.03] |
| | under 2 y | 0.74 [0.59, 0.94] | 0.77 [0.60, 0.98] | 1.86 [1.43, 2.42] |
| | 2+ y | 1.03 [0.72, 1.49] | 0.99 [0.69, 1.42] | 1.30 [0.90, 1.87] |
| Review share (points) | all | −4.8 [−6.1, −3.6] | −1.4 [−2.2, −0.6] | +0.1 |
| | under 2 y | −5.9 [−8.1, −3.6] | −1.8 [−3.5, −0.2] | −0.4 |
| Threads given (ratio) | all | 0.92 [0.87, 0.97] | 1.01 [0.98, 1.04] | 1.17 [1.14, 1.21] |

- **The raw gradient is clear, the added signal small.** The fifth drawing
  most feedback goes on to review less (28% against 46% review share for
  people under 2 years) and is added to OWNERS less often (20% against
  36%). But that fifth also lands half as many CLs, and people who already
  review draw less feedback on their own CLs (they know the code). Holding
  those equal, the review-share gap falls to 1.4 points per doubling and
  the threads-given gap disappears.
- **OWNERS:** for people under 2 years, each doubling still goes with about
  three quarters of the odds; for 2+ years, nothing. Ranking who is added
  (AUC), the index alone scores 0.58, the controls 0.71, both 0.72. CLs
  landed are the stronger predictor.
- **Not noise.** Split-half reliability of the log index (alternate CLs of
  the same half, Spearman–Brown) is 0.77, so the weak prediction isn't
  just measurement error.
- **Reading.** Needing less feedback and taking on review grow together
  (the two trajectories), but at a given volume and current reviewing,
  how much feedback someone draws adds little warning about whether they
  will review or own code. Caveats: association, not cause; 18 months is
  short for OWNERS, and an OWNERS addition is often a team decision, not
  a judgement of the author; the base halves are all before AI tools.

Rerun (about 5 min to load, then seconds with `--cache`):
`COSH_DATA_DIR=<main>/data/private python3 scripts/balance_feedback_predicts.py
--first-commit F --owners-added O --mech M [--cache P]` (writes
`fb_predict_fifths`, `fb_predict_fit` and `fb_predict_summary` into
`summaries/balance.json`; `--explore` prints them and writes nothing). The
page shows it under "Learning to need less review feedback"
(`#predicts`).

### 5. Growth along several paths

For each person and half-year (`scripts/balance_growth.py growth`):

- **velocity:** CLs per active month;
- **size:** median lines;
- **breadth:** distinct 3-level directories among a random 20 of the
  half-year's CLs, so it doesn't just track volume;
- **reviewing:** `Reviewed-by` approvals per active month;
- **independence** (2023+): minus the residual of threads, interdiff share
  and rounds against (size, directory, quarter) means.

Each dimension has the half-year's population median subtracted, so a
person's growth is measured against their peers in the same era, not
against the AI tools everyone got. In each two-year window, each person
gets a least-squares slope per dimension (≥ 3 measured half-years). The
slope is shrunk toward zero by its noise
(`var_between / (var_between + se²)`). It counts as "improving" if it is
above the 80th percentile of slopes from the same people with their
half-years shuffled. By chance alone, 20% would "improve" on any one
dimension.

Share improving, all people with ≥ 3 measured half-years:

| Window | People | Velocity | Size | Breadth | Reviewing | Independence (threads) | Improving on none of the 4 git dimensions |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2019–20 | 743 | 25% | 19% | 29% | 36% | | 40% |
| 2021–22 | 761 | 27% | 18% | 21% | 44% | | 39% |
| 2023–24 | 803 | 22% | 19% | 20% | 34% | 36% | 47% |
| 2025–26 | 695 | 24% | 18% | 28% | 41% | 43% | 42% |

(2017–18 is left out: `Reviewed-by` starts mid-2017, which inflates
"reviewing".)

- **People grow by reviewing and by needing less review feedback**, well above
  chance. **They don't grow by writing bigger CLs**: size is at chance in
  every window, which fits the project's preference for small CLs. Breadth
  and velocity are only modestly above chance.
- **Newcomers grow fastest.** In 2025–26, 0–2-year people improved on
  independence 58% of the time and on reviewing 52%. Those who joined
  during the window: 71% and 73%.
- **The share growing on none of the git paths rose before AI**, from 39–40%
  (2019–22) to 47% (2023–24), then eased to 42% (2025–26). Most of it is
  people with 5+ years' tenure, who plateau (59% in 2023–24), as expected.
  So far there's no sign that AI-era people grow less. The 2025–26 window
  is only 3.5 half-years long, and its newcomers have been watched for a
  year at most.
- **Independence growth may be partly reviewers easing off.** Section 4
  shows review thinning for newcomers in 2026, so the independence slopes
  overstate learning in that window. Interdiff share and rounds are less
  sensitive to how much reviewers write, and grow less (29% and 44%).

### 6. Taking on the burden: from author to reviewer to OWNER

**Review share** (approvals given ÷ (approvals + CLs authored)), median by
start cohort and tenure year: about 0 in year 1, 0.03–0.17 in year 2,
0.26–0.36 in year 3, 0.33–0.50 in year 4, and 0.5–0.7 after 6+ years.
People reliably move from writing to reviewing. The 2023 cohort is a
little slower (0.33 in year 4); the 2025 cohort is faster (0.17 in year 2,
small n).
The spread around those medians is wide and also much the same for every
join year, so the page shows one pooled histogram, then the medians by
join year: in year 3, 20% still approve nothing while 29% approve at least
as many CLs as they land; in year 5, 11% and 53%. Join-year medians run
0.38–0.51 in year 4 and 0.50–0.53 in year 5.

**Who reviews newcomers** (approvals of CLs by authors in their first
year, by the approver's tenure):

| Year | Newcomer-CL approvals | < 2 y | 2–5 y | 5–10 y | 10+ y | Approvers | Share of all approvals |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2019 | 26,593 | 10% | 25% | 40% | 25% | 657 | 23% |
| 2021 | 13,919 | 8% | 24% | 32% | 35% | 670 | 12% |
| 2023 | 13,311 | 6% | 20% | 24% | 51% | 651 | 11% |
| 2025 | 14,742 | 6% | 11% | 21% | 62% | 631 | 14% |
| 2026 | 26,018 | 8% | 6% | 16% | 69% | 745 | 20% |

The 10+ year column partly reflects the project aging (no one could have
10 years' tenure in 2017). But the drop of the 2–5-year "recent
graduates", from a quarter of newcomer review to 6%, is the clearest sign
that the training chain is thinning. In 2026, newcomer CLs are a fifth of
all approvals, and the oldest reviewers carry most of them.

**The pipeline:**

| Year | New authors (≥ 5 CLs) | New regular reviewers (first year with ≥ 60 approvals) | First added to an OWNERS file |
|---|---:|---:|---:|
| 2018 | 271 | 160 | 147 |
| 2020 | 261 | 108 | 182 |
| 2022 | 413 | 115 | 223 |
| 2023 | 160 | 120 | 215 |
| 2024 | 170 | 122 | 132 |
| 2025 | 222 | 68 | 129 |
| 2026 (to Oct) | 276 | 99 | 189 |

Kaplan-Meier, by start cohort (people with ≥ 20 CLs ever): the share who
became regular reviewers within 3 years was 15–22% (2017–2021 cohorts), 17%
(2022) and 13% (2023). The share in an OWNERS file within 3 years was 43–57%
(2017–2022), then 38% (2023). The ≥ 20 CLs condition favours fast starters
in recent cohorts, so the decline is if anything understated.

**Mentorship lineage.** A person's mentors are the top 2 approvers of their
first 10 CLs. Of 2017–2019 newcomers, 11–16% went on within 4 years to
mentor at least 2 newcomers themselves; of 2020–21 newcomers 7%, and of
2022's 4% (that window closes in 2026). Mentoring is concentrating: the
busiest 10% of mentors took 41–45% of newcomers in 2017–2024 and 49–52% in
2025–26.

**Cross-org review:** 7% of approvals in 2017–18 crossed email domains,
9–12% in 2019–25, and 12.8% in 2026.

**Reading it together:** the chain still works for individuals. Newcomers
still learn fast, and people still move from writing to reviewing. But
fewer of them complete it: fewer new regular reviewers and OWNERS per
cohort, and fewer mentees becoming mentors, a decline that started around
2020, before AI. In 2026, newcomer volume jumped while recent graduates
almost stopped reviewing newcomers. The experts who now carry it give
less feedback per CL (section 4) and take longer to give it (section 2).

### 6b. Reviewer load, cohorts and directories (`scripts/balance_report.py`)

These use the final mechanical rule (section 8) and people joined across
addresses. `balance_report.py` writes them as one JSON file of aggregates.

**Reviewers are spread thinner.** People who commented on someone else's
CL in a quarter: 1,450 (2023Q3) → 1,325 (2026Q3), while authors went
1,190 → 1,240. Merged CLs per commenting reviewer: 19.1 → 29.4. The
busiest tenth of approvers gave 55–57% of approvals in 2017–19, 63% in 2024
and 68% in 2026. That concentration started before AI tools. Per CL, the
feedback index (threads vs the 2023–24 norm for the size and directory)
went 1.09 (2023Q3) → 0.91 (2025Q3) → 0.72 (2026Q3).

**Individual reviewers were not slower, until 2026.** Weekday hours from
being added to the attention set to a reviewer's first comment stayed at a
median of 3–5 for every tenure band from 2023 to 2025. In 2026 the
longest-serving bands slowed: 10+ years 3.8 (2025H1) → 5.1 (2026H1) →
6.2 h (2026H2), 5–10 years 2.9 → 3.9 → 4.6, 2–5 years 2.4 → 2.7 → 3.6,
under 2 years flat at 2.6 (`reviewers_by_tenure`; corrected 2026-11-09,
section 6d). Threads per CL reviewed fell slightly for the 5–10-year band
(3.65 → 2.7). Most of the longer wait for authors still comes from volume:
the same people face more CLs.

**Joiner cohorts.** People who joined in 2023, 2024 or 2025, 9–12 months
after their first commit:

| Cohort | CLs per person per month | Feedback index | Others' CLs reviewed per month |
|---|---:|---:|---:|
| Joined 2023 | 2.2 | 1.69 | 1.0 |
| Joined 2024 | 2.5 | 1.87 | 0.8 |
| Joined 2025 | 6.6 | 1.08 | 2.1 |

The 2025 cohort lands about 2.5× as many CLs, needs less feedback sooner,
and starts reviewing others earlier. Part of the lower feedback is the 2026
project-wide drop (veterans fell about 20%), but even scaled up by that the
2025 cohort's 1.35 is below 1.69 and 1.87. Each point counts only people
still active, so this describes those who stayed.

**Directories (2024 vs 2025Q4–2026Q3).** The shift is broad. Newcomers' share
of CLs rose in nearly every busy directory: `chrome/browser` 3.9% → 13.5%,
`chrome/test` 2.7% → 21.9%, `components/autofill` 3.7% → 16.3%. Threads per
100 lines fell in most. Median first-review waits nearly doubled in
`content/browser` (5.8 → 11.1 h) and `third_party/blink` (5.9 → 10.0 h),
while UI-heavy directories stayed flat or got faster.

### 6c. Growth by directory: difficulty and openness (`scripts/balance_dirgrowth.py`, 2026-11-08)

Directories are 2-level: the one holding most of a commit's lines. A
person's **directory tenure** is the time since their first commit in it.
git history starts in 2017, so anyone already in a directory then starts
in 2017. That still puts them in the top bin for 2023+ CLs.

**Difficulty: how fast review need falls with directory tenure.** The
feedback index (section 4) of a directory's CLs is binned by the
author's directory tenure (< 6 months, 6–12 months, 1–2, 2–4, 4+ years).
Then ln(index) is fitted against log2(tenure), weighted by CLs.
exp(slope) is the **factor per doubling**: 0.80 means an author's CLs draw
20% fewer threads each time their tenure there doubles. A lower factor
means a steeper learning curve, with more to learn before an author needs
little review. The table also gives the ratio of the first year's index to
the 4+ year bin's.

**Openness: how fast authors become reviewers there.**

- **Promotion:** of people who joined the project in 2017 or later,
  started in the directory in 2017–19 or 2020–21, and landed 5+ CLs there
  within 2 years, the share who gave 10+ approvals (`Reviewed-by`) on
  others' commits there within 3 years of starting.
- **New-reviewer share:** the share of the directory's approvals given by
  approvers under 3 years on the project. Directory tenure can't be used
  here: before about 2021 it can't tell veterans from newcomers.

Busiest directories. "Pre" is 2023Q3–2024Q4 and "now" is 2025Q4–2026Q3:

| Directory | CLs pre | Factor per doubling, pre → now | First year ÷ 4+ years, pre → now | Promoted within 3 y, 2017–19 → 2020–21 | New-reviewer share 2019, 2022, 2024, 2026 |
|---|---:|---|---|---|---|
| `chrome/browser` | 41,804 | 0.80 → 0.83 | 2.48 → 2.10 | 50% → 50% | 20, 21, 21, 14% |
| `third_party/blink` | 17,532 | 0.76 → 0.75 | 3.08 → 3.04 | 40% → 29% | 15, 14, 11, 4% |
| `ios/chrome` | 10,353 | 0.84 → 0.81 | 1.97 → 2.36 | 36% → 61% (small) | 22, 11, 23, 13% |
| `content/browser` | 5,507 | 0.81 → 0.89 | 2.23 → 1.62 | 32% → 42% | 11, 15, 11, 5% |
| `tools/metrics` | 5,051 | 0.84 → 0.80 | 1.98 → 2.51 | 19% → 31% | 11, 18, 17, 8% |
| `chrome/android` | 4,957 | 0.78 → 0.85 | 2.51 → 2.09 | 45% → 45% | 18, 15, 16, 17% |
| `chrome/test` | 3,717 | 0.83 → 0.84 | 2.27 → 1.76 | 30% → 45% | 32, 32, 29, 24% |
| `components/autofill` | 3,620 | 0.74 → 0.78 | 2.77 → 2.98 | 17% → – | 19, 33, 45, 12% |
| `testing/variations` | 3,246 | 0.95 → 0.86 | 1.21 → 1.79 | 26% → 25% | 8, 22, 25, 14% |

Promotion cohorts have 50–440 people in the big directories and under 40
in `ios/chrome` and `components/autofill`. 2026 runs to the end of
October.

- **Blink is the hardest directory to grow in.** Of the 22 directories
  with 800+ CLs pre, its curve is the second steepest pre and the
  steepest now. A first-year blink author's CL draws 3.1× the review of a
  4+ year one's. Elsewhere that ratio is 1.2–2.9×. Its curve hardly moved
  between eras (index 2.65, 1.75, 1.35, 0.97, 0.76 pre; 2.21, 1.89, 1.88,
  1.14, 0.69 now). `components/autofill` is about as steep, and testing
  and config directories are the flattest.
- **Openness falls in nearly every directory in 2026.** The 2026
  new-reviewer share is below 2024's in 21 of 22 directories. That is the
  project-wide thinning of section 6 seen per directory.
- **Blink has become one of the least open of the big directories.**
  - Its new-reviewer share went 15% (2018–20) → 11% (2024) → 4% (2026),
    the lowest of the big directories with `content/browser`.
  - Promotion within 3 years fell from 40% to 29%. `chrome/browser` held
    at 50%.
  - New regular blink approvers (first year with 25+ blink approvals)
    numbered 44–51 a year in 2019–20, 20 in 2024 and 10 in 2026 to
    October.
  - Approvers with 10+ blink approvals in a year numbered 234 in 2025 and
    206 in 2026, and the busiest 10 gave 25% of approvals in 2024 and 32%
    in 2026.
  - Approvers with 8+ years on the project gave 15% of blink approvals in
    2018 and 64% in 2026.
- **Difficulty and openness barely go together across directories.** The
  correlation between the factor per doubling and promotion is −0.16.
  Hard directories aren't clearly the closed ones.

**Does either explain blink's longer review waits (section 2b)? Not
directly.**

- **Across directories, difficulty doesn't predict the slowdown.** The
  median first-review wait from A to B (2024Q1–2025Q2 to 2026Q2–Q4)
  doubled in blink (5.6 → 12.2 h), `content/browser` (6.2 → 12.3),
  `ash/*`, `gpu/command_buffer`, `media/gpu`, `components/viz`,
  `build/config` and `testing/buildbot`. It rose 20–30% in
  `chrome/browser`, `ios/chrome`, `chrome/android` and `chrome/test`, and
  fell in `components/autofill`. Correlation of the log wait ratio with
  the factor per doubling: +0.34, the wrong sign for "hard directories
  slowed more". With the first-year ratio: −0.38, the same message.
- **Openness predicts it only weakly.** The correlation with the 2026
  new-reviewer share is −0.42 (closed directories slowed more), and with
  promotion −0.03. With 22 directories, of very different sizes, none of
  these is clearly above noise.
- **Within blink, the shift to older approvers explains none of it.** On
  blink CLs with one approver, approvers with 8+ years on the project went
  from 53% to 66% and those under 3 years from 11% to 3%. Giving B's CLs
  A's waits for their approver's tenure band leaves the median at 4.7 h,
  against 11.6 h actual. Every band slowed:

  | Approver's years on the project | Share A → B | Median wait A → B |
  |---|---|---|
  | < 3 | 11% → 3% | 5.4 → 19.3 h |
  | 3–8 | 36% → 31% | 4.6 → 14.8 h |
  | 8+ | 53% → 66% | 4.8 → 10.1 h |

  Approvers with few blink approvals slowed too (3.4 → 15.3 h for under
  10 a quarter, 248 CLs in B), so per-reviewer blink load isn't the whole
  story either.
- **Difficulty adds load through the author mix.** Blink's first-year
  authors draw 3× the review, and their share of reviewed CLs rose from
  10% to 17%. Their waits rose less than veterans' (9.9 → 16.5 h against
  4.9 → 11.1 h). This is the same small mix effect as in section 2b, about
  1 h.
- **The timing doesn't match.** Blink's openness has been falling
  steadily since about 2020, and its difficulty is stable. The wait
  jumped in 2025H2–2026, together with volume and across nearly every
  platform directory at once.

**Who arrives (2026-11-08).** Someone arrives in a directory with their
first commit there, if 3 or more of their commits land there within 120
days. They are new to Chromium if their first commit anywhere was within
the half-year before. Active authors land 3+ commits there in the
half-year. Google is the org of the arriving commit's author email
(`cosh.orgs`: `chromium.org` counts as Google unless the affiliations file
says otherwise). Rates are arrivals per half-year per 100 active authors.
Years before 2020 are left out: git starts in 2017, and Blink's
directories were renamed into `third_party/blink` in 2018–19, which makes
everyone look new there.

| Directory | All arrivals 2020–22, 2023–24, 2025–26H1 | Googlers new to Chromium, per 100 Google authors | Non-Google share of arrivals, 2025–26H1 |
|---|---|---|---:|
| `third_party/blink` | 13.2, 8.2, 10.6 | 7.9, 3.1, 3.4 | 53% |
| `content/browser` | 15.6, 10.6, 13.4 | 7.6, 3.0, 3.5 | 36% |
| `chrome/browser` | 15.2, 7.9, 14.2 | 12.8, 4.8, 11.0 | 16% |
| `chrome/android` | 13.5, 15.1, 20.5 | 9.2, 7.9, 12.1 | 6% |
| `ios/chrome` | 19.9, 16.5, 18.6 | 12.5, 7.1, 10.3 | 9% |

- **Yes, new people come to blink less than to Chrome's directories,
  and new Googlers far less.** All five dipped in 2023–24. The 2025–26
  wave of new people went to the Chrome directories, which got back to
  10–12 new-to-Chromium Googlers per 100 Google authors. Blink and
  `content/browser` stayed at about 3.5, under half their 2020–22 rate.
- Half of blink's arrivals since 2025 are from outside Google (29% in
  2020–22), and Google authors fell from 80% of blink's active authors to
  71%.
- **This feeds the reviewer pipeline, not this year's queue.** Few new
  Googlers in blink means few future blink reviewers (promotion is
  mostly of Googlers). Today it adds load through newcomer CLs, which in
  blink draw 3× the review.

**Load per reviewer doesn't separate the directories either.** Merged CLs
per active reviewer (in the attention set of 5+ of the directory's CLs in
the quarter), 2024 → 2026Q3: blink 17–19 → 22, `chrome/browser` 15–16 →
25, `chrome/android` 17–20 → 27, `content/browser` 10–11 → 12. The Chrome
directories took on the most volume and the most new reviewers
(`chrome/browser` 383 active reviewers in 2025Q3, 524 in 2026Q3) and their
waits barely moved. `content/browser`'s load per reviewer stayed flat
while its wait doubled.

**Reading it together:** blink's slower first review is a recent, broad
slowdown that hits every approver group. It's shared by the platform
directories around it (`content/browser`, `gpu/`, `media/gpu`,
`components/viz`) and not by the Chrome UI directories, even though the
Chrome directories' reviewers took on more CLs each. So it's neither a
growth problem that suddenly bit nor simply more CLs per reviewer in the
directory. The likeliest explanation is that platform reviewers' time is
going elsewhere, to review in other directories or to work outside
review, which these data don't show. The thin pipeline matters
indirectly. Blink is the hardest place to grow, attracts few new
Googlers, and has promoted ever fewer authors to reviewers. So when its
volume rose in 2026, no new reviewers absorbed it, and the busiest 10
approvers took a larger share.

The page shows this in "Source of longer review queues" (`#queues`), from
the `queue_*` datasets this script writes; section 6d has the project-wide
part of that section.

This seems to contradict section 6b's "individual reviewers are not
slower". The two measure different things. Here it is time from the CL
being sent to its first substantive review. There it is time from a given
reviewer being added to their own first comment.

Rerun: `COSH_DATA_DIR=<main>/data/private python3 scripts/balance_dirgrowth.py
[summaries/balance.json] --first-commit F --owners-added O --mech M
[--min-cls 800]` (prints the tables; with the path, also writes the
page's `queue_*` datasets; about 5 min). `--min-cls 800` also sets which
directories `queue_dirs` lists.

### 6d. Source of longer review queues, project-wide (2026-11-09)

The page's `#queues` section was reworked to explain the project-wide
slowdown first and blink as the sharpest case. Same CLs as 6c (merged,
human-owned, non-mechanical, with a substantive first review); "A" (then)
is 2024Q1–2025Q2 and "B" (now) 2026Q2–Q4, Q4 to early November, with
per-quarter rates pro rata. Active reviewer: in the attention set of 5+ of
the directory's CLs in a quarter. All from `scripts/balance_dirgrowth.py`
(`queue_summary`, `queue_months`, `queue_hours`, `queue_dirs`,
`queue_shift`, `queue_mix`), cross-checked with ad hoc queries of
`balance.sqlite` that use Gerrit account IDs rather than the identity
merge; the two agree to within rounding.

**The queue, 2024 average → 2026Q3, all of Chromium:**

| CLs a quarter | Active reviewers | CLs per active reviewer | Feedback index | Median wait |
|---:|---:|---:|---:|---:|
| 27,888 → 38,915 (+40%) | 993 → 996 (0%) | 28.0 → 39.1 (+39%) | 0.97 → 0.72 (−26%) | 4.0 → 5.2 h (+28%) |

- **By month** the rise is recent and steep: median 3.7 h in October
  2025, 4.2–5.2 through the first half of 2026, 6.7 in September 2026 and
  8.2 in October 2026 (p75 19.6 → 24.4). CLs a month went 10,045 →
  17,838 (+78%) over the same year; the median CL from 40 to 69 lines.
  Early November (1,205 reviewed CLs) is at 9.5 h.
- **Two steps.** Active reviewers fell from ~1,000 (2023Q3–2024Q3) to 840
  (2025Q4), −16%, while CLs held at 26–28k a quarter. Waits still fell to
  3.3 h (2025Q2): reviewers covered the gap by reviewing more lightly
  (feedback index 0.97 → 0.92). From 2026Q1 CLs rose to 30.6k, 32.8k and
  38.9k; active reviewers came back to 996 (new people, section below),
  so CLs per active reviewer went 28 → 39, the feedback index fell to
  0.72, and the median wait rose every quarter to 5.2 h. The relation
  between load per reviewer and wait is loose, though: 2023Q3 had 27
  CLs per reviewer and a 5.1 h wait, 2025Q2 31 and 3.3 h.

**Not the CLs.** B's reviewed CLs given A's waits for the same size band
(<10, 10–50, 50–200, 200–1000, 1000+ lines), hour band sent (US 14–22
UTC, Europe 6–14, night, weekend), reviewers in the attention set (1, 2,
3+) and owner org (Google or not): median 4.29 h, against 5.58 actual and
3.82 in A. Size alone gives 4.27. So the mix explains about a quarter of
the rise and all of it is bigger CLs; the shares by hour, reviewers and
org barely moved. (Adding the 2-level directory to the key leaves 12% of
B's CLs unmatched and gives 3.9 h; directory mix is not it either.) Owner
org: Google-owned CLs 3.46 → 4.78 h (93.6% → 91.4% of reviewed CLs),
others 11.1 → 15.5 h. Every size band slowed 30–40%; every number of
reviewers 45–50%; every weekday 40–50%.

**By hour sent (UTC), median wait A → B:** the slowdown is same-day
turnaround for US afternoons.

| Hour | 09 | 12 | 14 | 16 | 18 | 20 | 21 | 22 | 23 | 02 |
|---|---|---|---|---|---|---|---|---|---|---|
| A | 4.5 | 2.8 | 2.6 | 2.6 | 2.1 | 2.1 | 2.8 | 6.5 | 13.3 | 13.9 |
| B | 5.2 | 2.9 | 3.3 | 3.3 | 3.0 | 4.4 | 8.0 | 13.4 | 15.3 | 14.3 |

CLs sent 0–13 UTC (Asia and Europe's day) changed little: they were
always answered the next US morning. The share of CLs by hour is the
same in both periods (US hours 14–22 are 51% → 52%).

**By directory (800+ CLs in A), CLs a quarter, median wait, active
reviewers a quarter, CLs per active reviewer, renewal (share of B's
active reviewers not active there in A), median lines:**

| Directory | CLs/q A → B | Wait A → B | Reviewers/q A → B | Per reviewer A → B | Renewal | Lines A → B |
|---|---|---|---|---|---:|---|
| `gpu/command_buffer` | 173 → 212 | 2.2 → 10.1 | 10 → 13 | 17.6 → 15.9 | 29% | 26 → 64 |
| `testing/buildbot` | 174 → 82 | 1.4 → 5.8 | 8 → 2 | 22.7 → 49.0 | 8% | 21 → 10 |
| `ash/webui` | 215 → 59 | 3.9 → 11.0 | 18 → 2 | 12.0 → 25.1 | 2% | 48 → 54 |
| `media/gpu` | 134 → 131 | 5.1 → 12.1 | 10 → 7 | 13.0 → 18.7 | 14% | 36 → 47 |
| `third_party/blink` | 3,106 → 3,857 | 5.6 → 12.2 | 168 → 140 | 18.5 → 27.5 | 15% | 43 → 57 |
| `components/viz` | 162 → 128 | 4.2 → 9.0 | 12 → 7 | 13.6 → 17.5 | 11% | 42 → 61 |
| `content/browser` | 873 → 1,154 | 6.2 → 12.3 | 83 → 77 | 10.5 → 14.9 | 28% | 67 → 84 |
| `infra/config` | 254 → 317 | 1.7 → 3.1 | 13 → 13 | 20.1 → 25.0 | 38% | 27 → 24 |
| `ash/system` | 185 → 74 | 7.4 → 12.9 | 15 → 3 | 12.5 → 24.8 | 8% | 59 → 30 |
| `chromeos/ash` | 258 → 152 | 5.3 → 9.2 | 25 → 7 | 10.3 → 20.8 | 4% | 71 → 57 |
| all | 27,374 → 38,526 | 3.8 → 5.6 | 956 → 915 | 28.6 → 42.1 | 21% | 43 → 60 |
| `ios/chrome` | 1,806 → 2,751 | 3.7 → 4.9 | 60 → 72 | 30.2 → 38.0 | 42% | 40 → 59 |
| `chrome/android` | 954 → 2,013 | 2.2 → 2.8 | 51 → 69 | 18.6 → 29.2 | 45% | 56 → 67 |
| `chrome/browser` | 6,865 → 12,299 | 3.5 → 4.3 | 436 → 455 | 15.8 → 27.0 | 29% | 54 → 71 |
| `testing/variations` | 543 → 690 | 1.3 → 1.6 | 12 → 12 | 45.2 → 59.2 | 37% | 19 → 18 |
| `tools/metrics` | 822 → 832 | 2.7 → 3.2 | 50 → 26 | 16.6 → 31.6 | 12% | 11 → 9 |
| `chrome/test` | 556 → 1,050 | 3.8 → 4.4 | 41 → 59 | 13.5 → 17.9 | 62% | 81 → 89 |
| `ui/views` | 172 → 233 | 6.5 → 7.0 | 16 → 15 | 11.1 → 15.5 | 21% | 33 → 63 |
| `components/autofill` | 601 → 861 | 3.2 → 2.9 | 30 → 32 | 19.9 → 26.6 | 40% | 71 → 86 |
| `ash/wm` | 174 → 54 | 4.2 → 3.5 | 8 → 3 | 21.3 → 20.2 | 12% | 70 → 28 |

- The directories that doubled are platform and graphics
  (`third_party/blink`, `content/browser`, `gpu/command_buffer`,
  `components/viz`, `media/gpu`), build and test infrastructure
  (`build/config` 0.8 → 2.6 h, `testing/buildbot`, `infra/config`) and
  ChromeOS (`ash/*`, `chromeos/ash`), which lost 60–75% of their CLs and
  most of their reviewers as ChromeOS moved onto Android. Chrome's UI
  directories rose 15–35% and `components/autofill` got faster.
- **Load per reviewer within the directory doesn't separate them.**
  Across the 22 directories, the correlation of the log wait ratio with
  the log ratio of CLs per active reviewer is −0.04; `chrome/browser`
  took on the most per reviewer (+71%) and slowed least. With the log
  ratio of active reviewers it is −0.20, with renewal −0.26, with the
  change in reviewers per CL +0.21, and with how much the directory's A
  reviewers' attention share there fell −0.10. None is clearly above
  noise with 22 directories of very different sizes.
- Platform directories renewed their reviewer pools least (blink 15%,
  `media/gpu` 14%, `components/viz` 11%) and the Chrome directories most
  (28–62%). Reviewers per CL hardly changed anywhere (blink 1.30 → 1.28).

**What the same reviewers did (people active as reviewers in the
directory in A who still reviewed anywhere in B), per quarter, means per
person:**

| Directory | People | Reviewed there A → B | Reviewed elsewhere A → B | Own CLs landed A → B |
|---|---:|---|---|---|
| `third_party/blink` | 273 of 302 | 13.3 → 15.9 | 36.5 → 47.6 | 25.3 → 29.3 |
| `content/browser` | 143 of 160 | 8.9 → 10.1 | 62.3 → 78.0 | 29.0 → 35.9 |
| `chrome/browser` | 625 of 747 | 14.4 → 22.9 | 29.4 → 35.1 | 25.0 → 30.1 |
| `chrome/android` | 90 of 96 | 13.2 → 22.6 | 52.3 → 85.0 | 38.2 → 50.1 |
| `ios/chrome` | 96 of 103 | 20.7 → 27.1 | 33.5 → 43.7 | 35.5 → 38.8 |
| all (active anywhere) | 1,108 of 1,417 | – | 31.4 → 42.0 (median 16.0 → 15.9) | 20.5 → 24.5 (median 12.8 → 10.5) |

- Reviewers who stayed review about a third more CLs and land a fifth
  more of their own; the medians are flat, so the growth is in the
  heavier reviewers and authors. Only 29 of blink's 302 A reviewers
  stopped reviewing altogether (3 of them still author).
- Blink's and `content/browser`'s reviewers review as many of their own
  directory's CLs per head as before and more elsewhere. Of blink
  reviewers' attention-set memberships, `chrome/browser` went from 19% to
  25% and blink from 27% to 25%; `content/browser` reviewers' went
  `chrome/browser` 19% → 25%, `content/browser` 13% → 11%. So the
  platform reviewers' extra effort went mostly to `chrome/browser`, where
  the volume is, and to their own CLs; their directories' CLs each still
  get as many reviewers, but every one of those reviewers has a longer
  personal queue.
- `chrome/browser`'s review supply grew with its CLs: attention-set
  memberships in the directory 10,556 → 17,707 a quarter, 3,104 of them
  from people not active there in A.

**Individual response time.** Weekday hours from being added to a CL to
the reviewer's first comment (`reviewers_by_tenure`): 10+ years 3.8 (2025H1)
→ 6.2 (2026H2), 5–10 years 2.9 → 4.6, 2–5 years 2.4 → 3.6, under 2 years
2.6 → 2.6. The page's latency section and 6b were corrected.

**Reading it together.** In order of how firmly the data support each:

1. **More CLs for the same reviewers**: the one firm driver. CLs +40%
   (October +78% year on year), the median CL half again as big,
   newcomers' share of CLs tripled, and reviewers land a fifth more CLs of
   their own; the reviewer pool is 2024's size. AI-marked CLs are too few
   to say how much of the volume is AI-written.
2. **A pipeline that thinned before AI**: 68 new regular reviewers in
   2025 (fewest since 2017), new-reviewer share down in 21 of 22
   directories; the surge found no new reviewers, least of all in the
   platform directories.
3. **Attention follows the volume** (a reading, not a measured cause):
   platform reviewers added `chrome/browser` reviewing and their own CLs
   on top of their platform reviewing.
4. Not drivers: the CL mix (a quarter, all size); the shift to
   longer-serving approvers (none); load per reviewer within a directory.
5. Not visible: time outside review, working hours beyond the UTC hour,
   AI use in authoring, and whether authors choose busy reviewers or
   OWNERS leave no one else.

The page draws: the five tiles (`queue_summary`); monthly median wait and
CLs (`queue_months`, to the last complete month); the five quarterly
series indexed to 2024 (`queue_quarters`, dir `all`, which now also carries
`ftr_p75` and `feedback_index`); wait by hour sent (`queue_hours`);
stacked bars of what stayers did (`queue_shift`); horizontal bars of the
median wait by directory (`queue_dirs`); then the blink-against-Chrome
charts of 6c.

### 7. AI-marked CLs

960 marked CLs fall in 53 author-quarters where the same author also landed
unmarked CLs. Paired by author and quarter, the marked ones got their first
review 39 hours sooner (95% CI 2–77 h). Size, threads, threads per line,
interdiff share, rounds and reverts showed no significant difference (all
CIs span zero). The sample is small, self-selected and dominated by a few
teams. The marker only exists from 2026-07, so most AI use is unmarked and
can't be compared directly.

### 8. Mechanical CLs

Merged human-owned CLs with a landed commit (403,149), by file count:

| Files | CLs | With a reviewer thread | Threads per CL | Threads per file | Reverted < 30 d |
|---|---:|---:|---:|---:|---:|
| 1 | 115,564 | 46% | 0.85 | 0.85 | 2.3% |
| 2–4 | 136,743 | 63% | 1.99 | 0.73 | 2.9% |
| 5–9 | 83,593 | 75% | 4.02 | 0.62 | 3.6% |
| 10–19 | 44,702 | 81% | 6.65 | 0.51 | 4.6% |
| 20–49 | 16,899 | 78% | 7.50 | 0.29 | 5.2% |
| 50–99 | 3,069 | 69% | 4.52 | 0.07 | 5.2% |
| 100–199 | 1,228 | 64% | 3.25 | 0.024 | 4.6% |
| 200–499 | 835 | 45% | 2.07 | 0.007 | 4.8% |
| 500+ | 516 | 35% | 1.40 | 0.001 | 3.9% |

Review per file collapses past about 50 files. File count alone mixes big
real refactors with mass edits, so the 67,249 CLs with ≥ 10 files also get
a **repetition ratio**: 1 − distinct changed lines ÷ changed lines, from the
landed commit's diff. A line added to 300 files, or a renamed symbol,
scores near 1.

| Repetition | CLs (≥ 10 files) | With a thread | Threads per file | Median files |
|---|---:|---:|---:|---:|
| 0–0.2 | 9,123 | 73% | 0.31 | 13 |
| 0.2–0.4 | 31,900 | 84% | 0.53 | 14 |
| 0.4–0.6 | 16,501 | 81% | 0.44 | 16 |
| 0.6–0.8 | 6,625 | 68% | 0.14 | 23 |
| 0.8–0.9 | 1,312 | 59% | 0.08 | 25 |
| 0.9–1.0 | 1,459 | 52% | 0.04 | 38 |

**Proposed rule:** a CL is mechanical if it has ≥ 100 files, or ≥ 10 files
with repetition ≥ 0.8. That's 4,875 CLs (1.2% of merged CLs). They get
0.010 threads per file, against 0.36 for the other CLs with ≥ 10 files, and
47% of them got no thread at all. The rule deliberately doesn't use review
counts, which would bias the review measures it filters. The page's hexbin
(files against threads per file, coloured by repetition) shows the cluster
and the cutoff. The analyses above used a provisional rule (≥ 50 files and
no thread); switching is a next step.

Reverts climb with file count (2.3% for one file, about 5% for 20+ files),
so the revert chart should be by size as well as over time.

## The page (`web/balance.html`)

**Status (2026-11-08):** a first draft is live as `web/balance.html`, with a
large "Draft: under development" warning at the top. Its landing-page card
(2026-11-08) carries a yellow "In development" box below its description. It has 52 charts and 7 tables, drawn with Chart.js from
`summaries/balance.json`. That file holds 47 aggregate datasets:
- `balance_report.py`'s `report.json`;
- the growth, pipeline, mentorship, AI-paired and mechanical tables from
  `balance_growth.py` (via `balance_growth_tables.py`) and
  `balance_analysis.py`;
- since 2026-11-08, `scripts/balance_page_extras.py`, which adds the growth
  signals (−1 votes, abandonment, same-people panels, matched cohorts;
  `docs/balance-signals.md`), the activity patterns
  (`docs/balance-clusters.md`, aggregate shares only, plus the pattern
  maps and rules from `balance_clusters/map.json`) and the Chrome
  Releases CVE counts (`docs/bugs-and-security.md`). Rerun it after any of
  those inputs changes:
  `COSH_DATA_DIR=<main>/data/private python3 scripts/balance_page_extras.py`.
  It reads `data/private/balance_signals.json` (`balance_signals.py report
  --out`).
- `scripts/balance_dirgrowth.py` (2026-11-08, extended 2026-11-09), the
  "Source of longer review queues" section: `queue_*` datasets (sections
  6c and 6d).
- `scripts/balance_histograms.py` (2026-11-08), the "Waiting for review"
  histograms: shares of reviewed CLs by hours to first substantive review
  and by reviewers' weekday attention-set hours, for the latest year
  (2025 Q4 – 2026 Q3) against the 2023 H2–2024 baseline. Same CLs as the
  quarterly charts; it reads `balance.sqlite` and the `--mech` list:
  `COSH_DATA_DIR=<main>/data/private python3 scripts/balance_histograms.py --mech mech.jsonl`.
- `scripts/balance_definitions.py` (2026-11-08), for the "Defined: the
  feedback index" section: shares of CLs by reviewer threads (0 to 20,
  one bin each, plus the share above 20) for each tenth of CLs by size,
  over 2023–24, the feedback index's norm years. Same CLs and `--mech` list:
  `COSH_DATA_DIR=<main>/data/private python3 scripts/balance_definitions.py --mech mech.jsonl`.

- `scripts/balance_behind.py` (2026-11-08), the "two growth
  trajectories" section at the top of the page: shares of steady
  contributors behind on review share (by calendar year) and on feedback
  (by half-year), with persistence and a chance baseline (section 0).
- `scripts/balance_review_share.py` (2026-11-08), the "From author to
  reviewer" histogram: shares of people by review share (none, then
  tenths) at each year since joining, all 2017–2025 join years pooled, plus
  per-year summaries (`review_share_years`: share approving nothing, share
  at 50% or more, and the range of join-year medians). Same people and
  definition as `git_cohorts`:
  `COSH_DATA_DIR=<main>/data/private python3 scripts/balance_review_share.py --first-commit F --owners-added O`.

- `scripts/balance_authors.py` (2026-11-08), the "Authors in the last
  year" section: per author with 10+ CLs landed from 2025-11 to 2026-10
  (1,313 people), distinct 3-level directories touched, the feedback
  index pooled over their CLs, tenure and CLs landed, with their most-used
  commit email. Unlike the other scripts it writes **one row per person**
  (`summaries/balance_authors.json`), drawn as a histogram of directories
  and a scatter (directories × feedback index, colour = tenure on a continuous green → blue → red scale, area =
  CLs). Its hover card names the author only behind a hidden setting:
  pressing "e" 10 times in a row (no other key between) switches emails
  on or off, for that page load only (off again after a reload). The emails are still in the
  published JSON. Published under ground rule 3
  (public data; the feedback index is not tone). Breadth tracks volume
  (Spearman 0.72 with CLs) and goes with slightly less feedback per CL
  (−0.24):
  `COSH_DATA_DIR=<main>/data/private python3 scripts/balance_authors.py --first-commit F --owners-added O --mech M`
  (about 3 min).
  The same script (2026-11-08) also summarizes **abandonment after review
  against tenure**, per author: of their non-mechanical CLs closed in the
  year with a first substantive review before closing, the share abandoned,
  for the 1,152 authors with 10+ such CLs. **Abandonment does not correlate
  with tenure** (Spearman 0.03; median 6.3% under 2 years, 6.7% at 10+
  years, pooled 6.9%), while people vary widely (p90 17%, 181 abandoned
  none). A per-author scatter of it (tenure × rate, coloured by org) was
  tried and dropped as uninformative; the page quotes the finding in one
  sentence of "Wrong turns", next to the aggregate abandon index by tenure
  (`docs/balance-signals.md`), and the summary fields are `abandon_*` and
  `rho_tenure_abandon` in `balance_authors.json`.
  A scatter of each author's percentile within their tenure band on review
  share against feedback index (2026-11-08, same year and authors) was also
  tried and dropped: the two barely correlate (Spearman −0.23; 29% behind
  on both halves against 25% by chance), so it showed a near-uniform cloud.
  The aggregate overlap is in section 0 ("Is it the same people?").

**Narrative restructure (2026-11-09).** The page now opens with a narrative,
"Chromium code review load analysis": the intro (the strain reviewers report,
and the question of what review is worth), a contents list and eight
sections, each framing → charts → what they show → at most one "Open
question" or "Not measured yet" line: 1 `#burden` (percentile fans of lines,
comments and CLs per reviewer, nine years of approvals), 2 `#value` (reverts
since 2017, the #roi charts and forests), 3 `#quality-nuance`, 4
`#value-sources` (reviewer and author tenure, organizations), 5 `#capacity`
(review share, new reviewers' growth, organizations, the pool before AI), 6
`#inflection` (fewer newcomers from 2023, fewer new reviewers from 2025), 7
`#ai-review` (effort, spread, quality of AI-marked CLs) and 8 `#monitor` (a
table of measures to track, the two "behind" charts, and properties of good
change evaluation). Charts reused from the earlier analysis are drawn again
into canvases with ids starting `n-` (the builders take their target id),
and the new ones read the narrative datasets below. A fan (`fan()` in
`balance.ts`) shows a median line with bands up to p75, p90, p95 and p99,
on a log axis where the top dwarfs the median. Below a full-width "Earlier
analysis" break the previous page follows unchanged, its old lede included,
to be moved up into the narrative or removed.

Since 2026-11-08 each section follows one layout: before the charts only
what a reader needs to read them (definitions, who is counted), then the
charts, then what they show, with the figures. The text doesn't describe a
chart's shape (axes, series, colours): the legends and axes do that, and a
figure's `.note` caption names only what they can't, such as the unlabelled
dashed norm line. Findings are never stated above the chart they come from.

The page ends with two definition sections, "Defined: the feedback
index" and "Defined: newcomers and tenure" (a tenure timeline drawn in
HTML and CSS). Every use of "feedback index" or "newcomer" in the page's prose
is a dotted-underlined `<button class="term" popovertarget="def-…">`;
tapping it opens a popover with a short definition and a link to the
section, which `web/src/terms.ts` places beside the term. Headings, table
headers, labels and links aren't marked.

Sections added on 2026-11-08: "Wrong turns" (−1 votes and abandoned CLs by
tenure), "Arriving better equipped, or easing off?" (the panels and matched cohorts),
"Patterns of activity", AI adoption by directory and footers, and "Security
fixes". "Reviewers by tenure" and "Arriving better equipped, or easing
off?" were tables until 2026-11-08 and are now charts: four small line charts
over half-years (one line per reviewer tenure band), an interval chart of the
same-people changes on one shared scale (each change as a share of its 2024
level, faded where the 95% interval crosses zero; the natural-unit figures
are in each row's hover title), and small 2025-vs-2024 charts for the matched
cohorts. It has
no date range or mechanical toggle yet (planned below). Single-series charts
show distributions as shaded bands (middle half and 5th–95th percentile)
around the median, named p25–p75 and p5–p95 in the legend rather than in
each caption. The outer band was p10–p90 until 2026-11-08; it reaches p95
because 1 in 20 is still a common case (a review wait of about 4.5 days in
2026 Q3), and that tail grew more than p90 did (CLs per reviewer: p90 49 →
72, p95 74 → 109 from 2023 Q3 to 2026 Q3). At the bottom p5 nearly always
equals p10 (1 CL, no lines changed after review), so nothing is lost there. "How review is shared" has two histograms of commenting
reviewers per quarter, by CLs commented on and by threads started
(`reviewer_load_hist` and its 100-or-more summary `reviewer_load_top` from
`balance_report.py`, copied into `balance.json` on 2026-11-08). "Directories over time" is an expandable heatmap of
directories by quarter, from `summaries/balance_dirs.json`
(`dirs` in `balance_report.py`'s output), with a choice of measure.
"Across the codebase" is the same tree as an expandable table, 2024 against
the last four quarters (`areas` in `balance_report.py`'s output, rows flat
as `y24_<measure>` and `now_<measure>`): each CL counts in its main
directory and its parents, and a directory needs 200 CLs in each period.
Since 2026-11-08 both trees go below three levels: a CL's main directory is
its main 3-level one (most changed lines), then down into the subdirectory
with the most lines while that outweighs the files directly in it
(`balance_analysis.commit_main_dirs`). Levels 1–3 list as before; below
that a directory opens only when it has over 1% of the CLs (`OPEN_SHARE`
in `balance_report.dir_tree`), and a directory with one listed child
holding 90% of its CLs is skipped, so Java package chains such as
`chrome/android/java/src/org/chromium/chrome/browser/` show as one row.
That added 122 rows to the heatmap (to 388, 218 KB) and 42 to the table
(to 147), the deepest nine levels down.
Cells are shaded on one scale per measure, so both periods and every row
compare at a glance. Rebuilt 2026-11-08 by copying `areas` from a fresh
`report.json` into `balance.json`.

The design below is the target. Each chart follows the project's conventions: text in the HTML, dates not
ISO weeks, one date range for the page, a mechanical-CL toggle.

1. **The exchange:** two lines by quarter, CLs per active author and
   reviewer threads per 100 lines (raw and standardized to 2024's mix),
   with 2025 marked. The core of the page in one chart.
2. **Size and rework:** median and p90 lines, interdiff share and rounds by
   quarter; revert rate within 30 days.
3. **Latency:** percentile bands (p25/p50/p75/p90) of hours to first
   substantive review, and reviewer and owner attention hours, with the
   working-hours caveat in the caption.
4. **Learning curves:** feedback index by tenure (x axis), one line per
   era, and the same by familiarity with the directory. These answer "do
   people still need less review feedback as they learn?"
5. **Growth paths:** grouped bars per window, the share improving on each
   path, with the 20% chance line dashed, and the share improving on none.
   No individual appears.
6. **From author to reviewer:** review share by tenure year, one line per
   cohort; beside it, a stacked area of newcomer approvals by approver
   tenure per year.
7. **The pipeline:** Kaplan-Meier step curves by cohort for "regular
   reviewer" and "OWNER"; new reviewers and OWNERS per year; mentees who
   became mentors.
8. **By directory:** typical size, feedback index, rework and latency
   per directory, as a drill-down tree like Value Exchange's.
9. **Mechanical CLs:** a hexbin of files against threads per file,
   coloured by repetition ratio, with the cutoff drawn on it. It defends
   the toggle.
10. **Individual lookup:** one person's own paths over time (CLs a month,
    size, directories, approvals given, newcomers reviewed, mentees, the
    date they became an OWNER) against their cohort's band. No rank, no
    growth score, no feedback index (it reads as a judgment and mixes
    in reviewer behaviour).
11. **Celebration boards** (named, positive only, like the praise boards):
    milestones in the range (first regular year as a reviewer, first
    OWNERS file, first newcomer reviewed), most newcomers reviewed,
    mentees who went on to review others, and fastest median first
    review given. Never a "least" board and never a growth score.

The summaries will be built by `summarize` from `balance.sqlite`: quarterly
aggregates, cohort tables, per-directory figures, and per-person monthly
counts for the lookup and boards (all from public Gerrit and git data;
ground rule 3).

## Data-quality notes

- **The shared clone has a damaged object:** a tree delta at offset
  2,323,392,059 of `pack-f60330f3…` fails zlib's check. Git falls back to
  the older duplicate pack, which still holds every commit and tree, so
  nothing here was affected. A blob damaged the same way would have no
  fallback. Run `git fsck` on `~/projects/shared/chromium` before trusting
  the older pack's removal.
- Gerrit's `main` was `master` until 2021-04-07 00:00 UTC (the listing
  queries both before 2021-05-01; `derive` records `master` as `main`).
  On the rename day, 6,836 stale `master` CLs, created 2017–2019, were
  abandoned at once. They are real abandons, but they make 2021-W14's
  abandoned count a one-off spike: leave that week's mass abandon out of
  trends.
- `Reviewed-on` used the short form `…/c/<n>` from Oct 2018 to Feb 2019,
  and `Reviewed-by` footers start mid-2017.
- `Bot-Commit:` marks Rubber Stamper's approval (clean reverts, relands,
  cherry-picks), not a bot author. Those commits are left out of velocity
  but counted when finding what got reverted.
- Reverts per quarter among human-approved commits fell after 2021 because
  most reverts became bot-approved (`Bot-Commit:`): 4,075 human-approved
  reverts in 2020, then about 1,200 human-approved and 2,400–3,100
  bot-approved a year from 2021.
- The patch-set fetch's final repack crashed (git exit 134) after all
  fetches finished. The data is complete, but the repo has 1,200 packs.

## Next steps

1. Switch the analyses to the mechanical rule in section 8 (repetition
   ratios for every ≥ 10-file CL go into `balance.sqlite`).
2. Write `summaries/balance.json` from the scripts directly (today it is
   assembled by hand), add the controls planned above, and then drop the
   draft warnings (page and landing-page card).
3. Check whether "independence" growth in 2025–26 holds on interdiff share
   and rounds alone, as more half-years arrive.
4. Once the Gerrit backfill back to 2017-07 (started 2026-11-09) is done,
   rebuild the balance stages and extend the review-need learning curve's
   pre-AI baseline. Before late 2020 there is no attention set, so "sent
   for review" and attention hours need a fallback definition, used for
   every year.

## Narrative datasets (`scripts/balance_narrative.py`, 2026-11-09)

For the page's narrative restructure ("Chromium Code Review Load
Analysis"), one script adds 13 aggregate datasets to
`summaries/balance.json` (about +49 KB). Same population as
`balance_report.py`: merged, human-owned, non-mechanical CLs closed
2023Q3..2026Q3; people merged across addresses; tenure from the first
commit on `main`. A *review* is a (CL, reviewer) pair: a non-bot non-owner
who commented before close and has a first commit, as in
`reviewer_quarters` (keyed by account it reproduces `reviewed_p50`/`p90`
exactly; keyed by person, as here, the median is 1 higher). Git datasets
use human non-revert commits with a CL and their `Reviewed-by` approvers
(from 2017-07). Orgs come from `cosh.orgs` on the raw e-mail at the CL's
or commit's date. Cells under 20 people or 200 CLs are dropped or pooled
into "Other".

- `reviewer_burden` (per quarter): spread across reviewers of `cls`,
  `lines` (changed lines of the CLs they commented on), `comments`
  (individual comments, replies included) and `hours` (weekday hours in
  the attention set on those CLs, summed: waiting time, not work):
  `_p50.._p99`, `_mean`. `approver_burden`: the same for approvals and
  approved lines from git, 2017Q3..2026Q3.
- `org_feedback`: author org × era (`pre` 2023H2–2024, `now` 2025Q4–2026Q3)
  × tenure band (`<1y`, `1-2y`, `2-5y`, `5y+`, `all`) → feedback index.
  `org_feedback_fit`: per org and era, indirect standardisation for
  tenure (threads ÷ threads expected from size, area *and* the all-org
  index of the author's tenure band); `ratio` (1 = all orgs) with a 95%
  bootstrap interval over the org's authors, and the tenure mix.
- `org_reviewing`: review share (approvals ÷ (approvals + CLs), people
  with 6+ in the year, join years 2017–2025) by org of the person's
  commits that year and year since joining: median and share approving
  anything. `org_review_value`: per reviewer org, threads, addressed
  threads and comments per review, and the addressed share.
- `new_reviewer_growth`: by the reviewer's years since first commit
  (1..5, 6-7, 8-10, 11+) and era (`pre` 2023Q3–2025Q2, `now`
  2025Q3–2026Q3): reviews per active reviewer-quarter, threads and
  addressed threads per review, addressed ÷ threads started.
- `ai_quarters`, `ai_reviewer_load`, `ai_summary`: CLs with the broad
  marker (`ai_marked_broad.txt`, `docs/balance-ai.md`) as `marked`;
  `predicted` = unmarked CLs Haiku scores p ≥ 0.5 (`ai_predict/scores.sqlite`,
  2025-07 on; 99% precise, `docs/balance-ai-predict.md` §5), a subset of
  `other`. Load: concentration (top 10%, top 1%, Gini) and reviewer-tenure
  mix of reviews, with `other_matched` = 200 quarter-matched random samples
  of other CLs of the marked set's size. Summary: revert rates raw,
  standardised to marked CLs' size bucket × top directory × quarter (normal
  and author-cluster bootstrap 95% intervals, in points), and the paired
  figure from `ai_paired`.
- `capacity_years` (2017 Jul–Dec .. 2026 Jan–Sep, with `months`),
  `capacity_tenure` (authors by tenure band: share who approve, shares of
  commits and approvals) and `capacity_orgs` (Google vs other, by the org
  of a person's commits that year). `new_regular_reviewers` and
  `new_owners` follow `pipeline`; `left_*` and `new_approvers` are censored
  at the ends (2017 has no prior year; 2026 is 9 months).

Regenerate (about 5 min cold, 10 s with `--cache`; deterministic):
`COSH_DATA_DIR=<main>/data/private nice -n 5 python3 scripts/balance_narrative.py
--first-commit F --owners-added O --mech M [--cache /tmp/…/narrative.pkl]`.
