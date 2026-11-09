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
  month against 3.0, load index 1.05× against 1.52×, and 2.4 reviews a
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
- **Unchanged:** waits, reverts, rework, the load index and the mechanical
  rule, which don't depend on identities.

## Further analyses (2026-11-08)

Each has its own doc, with commands to regenerate:

- `docs/balance-signals.md`:
  - **−1 votes** (about 0.5% of reviewed CLs) fall with tenure and
    familiarity as steeply as the load index.
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
- `docs/balance-clusters.md`:
  - six activity patterns and nine trajectories;
  - fewer recent joiners move into reviewing within three years.
- `docs/bugs-and-security.md`:
  - the Chrome Releases security fixes, with 2026's jump to about 3,900
    CVEs;
  - how bug-tracker data could be fetched (that needs approval).

## Goal and signals (as stated on the page, 2026-11-08)

**Goal.** Chromium has grown through code review: experts give feedback,
newcomers learn to need less of it, then review and own code and train the
next newcomers. AI tools make changes cheaper to write than to review. The
page asks whether that cycle still holds, and how the community can adapt to
agentic engineering in a way that improves product quality, robustness,
engineering rigour and velocity, and keeps growing its people into expert
engineers.

**Signals.**

- *Balance:* review load index (threads against the 2023–24 norm for the
  CL's size and directory); CLs per reviewer.
- *Speed:* hours to first substantive review; attention-set waits.
- *Quality:* lines changed after review, rounds, reverts within 30 days.
- *Growth:* review load by tenure and familiarity; growth paths (velocity,
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
  engineers. The 2025 cohort's lower review load may be reviewers easing off.
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
- colouring the directory table by load rather than by a team's response
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

A Gerrit backfill to 2020 and the bug tracker **need approval**.

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
`scripts/balance_growth.py growth|burden|ai`, and `scripts/balance_report.py`
(the datasets behind the published report). They print tables, read no
comment text, and print no one's identity. (`scripts/balance_explore.py`
is the first W44-only prototype, superseded by `cosh/balance.py`.)

## Findings

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

**Review load index:** reviewer threads on a CL ÷ the mean for CLs of its
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
  "prolific") and the middle fifth (3–9, "average"). Load index in the
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
review load index (threads vs the 2023–24 norm for the size and directory)
went 1.09 (2023Q3) → 0.91 (2025Q3) → 0.72 (2026Q3).

**Individual reviewers are not slower.** Weekday hours from being added to
the attention set to a reviewer's first comment stayed at a median of 3–5
for every tenure band from 2023 to 2026. Threads per CL reviewed fell
slightly for the 5–10-year band (3.65 → 2.7). Longer waits for authors
come from volume, not from slower individuals.

**Joiner cohorts.** People who joined in 2023, 2024 or 2025, 9–12 months
after their first commit:

| Cohort | CLs per person per month | Review load index | Others' CLs reviewed per month |
|---|---:|---:|---:|
| Joined 2023 | 2.2 | 1.69 | 1.0 |
| Joined 2024 | 2.5 | 1.87 | 0.8 |
| Joined 2025 | 6.6 | 1.08 | 2.1 |

The 2025 cohort lands about 2.5× as many CLs, needs less feedback sooner,
and starts reviewing others earlier. Part of the lower load is the 2026
project-wide drop (veterans fell about 20%), but even scaled up by that the
2025 cohort's 1.35 is below 1.69 and 1.87. Each point counts only people
still active, so this describes those who stayed.

**Directories (2024 vs 2025Q4–2026Q3).** The shift is broad. Newcomers' share
of CLs rose in nearly every busy directory: `chrome/browser` 3.9% → 13.5%,
`chrome/test` 2.7% → 21.9%, `components/autofill` 3.7% → 16.3%. Threads per
100 lines fell in most. Median first-review waits nearly doubled in
`content/browser` (5.8 → 11.1 h) and `third_party/blink` (5.9 → 10.0 h),
while UI-heavy directories stayed flat or got faster.

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
large "Draft: under development" warning at the top. It isn't linked from the
landing page yet. It has 44 charts and 6 tables, drawn with Chart.js from
`summaries/balance.json`. That file holds 42 aggregate datasets:
- `balance_report.py`'s `report.json`;
- the growth, pipeline, mentorship, AI-paired and mechanical tables from
  `balance_growth.py` (via `balance_growth_tables.py`) and
  `balance_analysis.py`;
- since 2026-11-08, `scripts/balance_page_extras.py`, which adds the growth
  signals (−1 votes, abandonment, same-people panels, matched cohorts;
  `docs/balance-signals.md`), the activity patterns
  (`docs/balance-clusters.md`, aggregate shares only) and the Chrome
  Releases CVE counts (`docs/bugs-and-security.md`). Rerun it after any of
  those inputs changes:
  `COSH_DATA_DIR=<main>/data/private python3 scripts/balance_page_extras.py`.
  It reads `data/private/balance_signals.json` (`balance_signals.py report
  --out`).
- `scripts/balance_histograms.py` (2026-11-08), the "Waiting for review"
  histograms: shares of reviewed CLs by hours to first substantive review
  and by reviewers' weekday attention-set hours, for the latest year
  (2025 Q4 – 2026 Q3) against the 2023 H2–2024 baseline. Same CLs as the
  quarterly charts; it reads `balance.sqlite` and the `--mech` list:
  `COSH_DATA_DIR=<main>/data/private python3 scripts/balance_histograms.py --mech mech.jsonl`.
- `scripts/balance_definitions.py` (2026-11-08), for the "Defined: the
  review load index" section: shares of CLs by reviewer threads (0 to 20,
  one bin each, plus the share above 20) for each tenth of CLs by size,
  over 2023–24, the load index's norm years. Same CLs and `--mech` list:
  `COSH_DATA_DIR=<main>/data/private python3 scripts/balance_definitions.py --mech mech.jsonl`.

- `scripts/balance_review_share.py` (2026-11-08), the "From author to
  reviewer" histogram: shares of people by review share (none, then
  tenths) at each year since joining, all 2017–2025 join years pooled, plus
  per-year summaries (`review_share_years`: share approving nothing, share
  at 50% or more, and the range of join-year medians). Same people and
  definition as `git_cohorts`:
  `COSH_DATA_DIR=<main>/data/private python3 scripts/balance_review_share.py --first-commit F --owners-added O`.

The page ends with two definition sections, "Defined: the review load
index" and "Defined: newcomers and tenure" (a tenure timeline drawn in
HTML and CSS). Every use of "load index" or "newcomer" in the page's prose
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
directories (to three levels) by quarter, from `summaries/balance_dirs.json`
(`dirs` in `balance_report.py`'s output), with a choice of measure.
"Across the codebase" is the same tree as an expandable table, 2024 against
the last four quarters (`areas` in `balance_report.py`'s output, rows flat
as `y24_<measure>` and `now_<measure>`): each CL counts in its main 3-level
directory and its parents, and a directory needs 200 CLs in each period.
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
4. **Learning curves:** review load index by tenure (x axis), one line per
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
8. **By directory:** typical size, review load index, rework and latency
   per directory, as a drill-down tree like Value Exchange's.
9. **Mechanical CLs:** a hexbin of files against threads per file,
   coloured by repetition ratio, with the cutoff drawn on it. It defends
   the toggle.
10. **Individual lookup:** one person's own paths over time (CLs a month,
    size, directories, approvals given, newcomers reviewed, mentees, the
    date they became an OWNER) against their cohort's band. No rank, no
    growth score, no review load index (it reads as a judgment and mixes
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
   assembled by hand), add the controls planned above, and then a
   landing-page card once the draft warning can go.
3. Check whether "independence" growth in 2025–26 holds on interdiff share
   and rounds alone, as more half-years arrive.
4. Ask: would a Gerrit backfill of 2020–2023 (not approved) be worth it?
   It would give the review-need learning curve a pre-AI baseline of four
   years instead of 18 months.
