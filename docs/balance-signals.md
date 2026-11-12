# Growth signals: −1 votes, abandoned CLs, arriving better equipped or easing off, matched cohorts

Part of the Review Balance analysis (`docs/balance.md`). It answers three
questions the page leaves open:

1. Do **−1 votes** and **abandoned CLs** fall as people gain tenure and
   familiarity, like the feedback index does? (A −1 or an abandoned CL
   often means the approach was wrong from the start, or the author lacked
   the skill to solve it.)
2. When review feedback per CL fell in 2026, did **authors arrive better equipped** (such as with effective AI tools), or did
   **reviewers ease off**?
3. Do the 2025 joiners still look faster once compared with **matched**
   2024 joiners?

Everything here is aggregate. Per-person values are computed only to be
averaged and are never written out.

## Data and definitions

- **Window:** CLs closed (merged or abandoned) from 2023-W26 to 2026-W44
  on chromium/src `main`, human-owned, mechanical CLs left out (the
  repetition rule in `docs/balance.md`). Eras: 2023 H2–2024, 2025, and
  2026 (to October).
- **Votes** (table `votes` in `data/private/balance-timeline.sqlite`,
  written by `python3 -m cosh.balance timeline` in the same NoteDb walk as
  the uploads and attention set; until 2026-11-12 a separate
  `balance_signals.py votes` pass wrote `balance-votes.sqlite`):
  - Every `Label: Code-Review=<v>` line in a CL's NoteDb meta history, with
    the voter, value, time and patch set. The voter is the meta commit's
    author, or the `Gerrit User N` named on the line when a vote was cast
    on someone's behalf. `-Code-Review` and `=0` are removals, stored as 0.
  - `Copied-Label` lines (a vote carried to a new patch set) are skipped.
  - Only votes by humans other than the CL owner count.
  - It reads the local NoteDb repo only and fetches nothing. It is
    resumable, and rereads a CL whose meta ref has moved since
    (`timeline_done` keeps each CL's tip).
- **Negative vote:** any −1 or −2 from a non-owner human. *neg share* is the
  share of substantively reviewed CLs with one. *neg index* is that share ÷
  the 2023–24 share for CLs of the same size (ten log buckets): 1.0 is the
  2023–24 norm, like the feedback index.
- **Abandon rate:** the share of substantively reviewed CLs (a reviewer
  thread or inline comment, the page's definition) that were abandoned.
  *abandon index* is the same against the 2023–24 rate by size. Size for
  abandoned CLs is Gerrit's insertions + deletions of the last patch set,
  since they have no landed commit.
- **After a −1:** among CLs with a negative vote, the share abandoned, the
  share landed after an owner rework upload made after the first −1, and
  the share landed without one.
- **Tenure:** months from the author's first commit on `main` to the CL's
  creation. **Familiarity:** the author's earlier commits in the CL's main
  3-level directory (merged CLs only, as abandoned ones have no landed
  directory).
- **Uploads before sending:** owner rework uploads before the CL was first
  sent for review (`sent_at`), from `balance-timeline.sqlite`.

### Balanced panels (arriving better equipped vs easing off)

- **Reviewer side.**
  - The panel: reviewers with ≥ 20 reviews in 2024 and ≥ 20 in 2026. A
    review is a (CL, reviewer) pair where a non-owner human commented
    before the CL closed.
  - For each review, log(1 + threads they started) and whether they voted
    −1/−2. Each is turned into a residual against the 2024 mean for the
    same CL size, 2-level directory and author tenure band (falling back
    to size × tenure, then size).
  - Per reviewer, the change is the 2026 mean residual minus the 2024
    one. The table gives the mean over reviewers with a 95% bootstrap
    interval (1,000 resamples of reviewers).
  - This is a reviewer fixed-effects design: the same people, like-for-like
    CLs.
- **Author side.**
  - The panel: authors with ≥ 10 substantively reviewed CLs in both years.
  - Signals the reviewer doesn't set: interdiff share (lines changed after
    the first review ÷ final lines), uploads before sending, reverts within
    30 days, and abandon rate. Also two that reviewers drive: rounds (owner
    rework after new reviewer threads) and threads received.
  - Each is a residual against the 2024 mean for the same size and the
    author's *current* tenure band, so two years of ageing is not counted
    as change.
- **Reading it.** The same reviewers writing fewer threads while author-side
  quality is flat or worse means reviewers are easing off. Author-side
  measures improving alongside means authors are arriving better equipped.

### Matched cohorts

- **Joiners:** people whose first commit on `main` fell in 2024 or 2025
  (only from 2023-W26, so the first months are in the Gerrit window).
- **Matching:** exactly on four features of their first three months:
  - median CL size (< 20, 20–99, 100+ lines);
  - most common top-level directory;
  - domain group (google.com or chromium.org vs other);
  - prior Gerrit activity (a comment anywhere at least two weeks before
    their first commit, which approximates an engineer already working in
    Gerrit before landing on `main`).
  
  Within each cell, 2025 and 2024 joiners are paired at random, 1:1,
  without replacement (seed 5).
- **Outcomes by months since the first commit** (0–3, 3–6, 6–9, 9–12),
  counting only people whose whole window is observed:
  - share still active;
  - merged CLs and reviews given per active person-month;
  - feedback index;
  - calendar-adjusted thread residual (against the same size, directory
    and *quarter*, so the 2026 project-wide drop doesn't count);
  - median interdiff share and rounds;
  - neg share and abandon rate.

## How to regenerate

```bash
cd ~/projects/cosh   # or a worktree; data comes from the main checkout
export COSH_DATA_DIR=/home/rbagent/projects/cosh/data/private
nice -n 5 python3 -m cosh.balance timeline              # votes, uploads, attention (below)
nice -n 5 python3 scripts/balance_signals.py report --out signals.json   # ~4 min
```

The `timeline` stage reads every CL with a NoteDb meta ref (716k of the
1.14M after the 2017 backfill; see `docs/balance.md` for its time). It
lists `refs/meta/` once with each ref's tip (`cosh.balance.meta_refs`);
passing each batch's 2,000 refnames to `for-each-ref` as patterns cost
54 s a batch at 715k refs. With 3,198 packs outside a stale index the
reads ran at 14–34 CLs/s; `cosh notedb-maintain` fixes that, and
`backfill` now runs it every 20 weeks and at the end.
`COSH_BALANCE_TIMELINE=<path>` points the stage and its readers at another
file, for a scratch run.

Its inputs (first commits, OWNERS additions, AI markers, mechanical CLs)
come from `commits.sqlite`, as for `scripts/balance_report.py` (see
`docs/balance.md`, "Data and how it's built"). Tests:
`python3 -m unittest tests.test_balance tests.test_balance_signals` (the
vote parser and the timeline stage are in `tests.test_balance`).

## Results

Run 2026-11-08, after the identity fix in `balance_growth.alias_pairs`
(an owner and git author merge only when the author's CLs are ≥ 3 and ≥ 50%
owned by that address): 9,130 people. The window holds 460,432 closed CLs
and votes from 315,966 CLs with at least one Code-Review vote.

### −1 votes are rare; abandonment is the stronger signal

Chromium reviewers rarely vote −1: about 0.5% of substantively reviewed
CLs get one, in every era. They mostly object in comments. Abandonment is
ten times as common:

| Era | Reviewed CLs | Abandoned | Any −1/−2 | Abandoned after a −1 |
|---|---:|---:|---:|---:|
| 2023 H2–2024 | 83,988 | 5.7% | 0.53% | 42% |
| 2025 | 50,808 | 5.9% | 0.56% | 51% |
| 2026 (to Oct) | 59,914 | 8.0% | 0.59% | 58% |

Abandonment rose by 40% in 2026, and a −1 now ends a CL more often than it
leads to a reworked landing.

### Both fall with tenure and familiarity, like the feedback index

Index: 1.0 is the 2023–24 rate for CLs of the same size.

| Tenure | Neg index 2023–24 | 2025 | 2026 | Abandon index 2023–24 | 2025 | 2026 |
|---|---:|---:|---:|---:|---:|---:|
| 0–3 months | 2.80 | 2.54 | 2.75 | 1.27 | 1.34 | **1.99** |
| 3–6 | 2.70 | 1.27 | 1.33 | 1.28 | 1.33 | 1.72 |
| 6–12 | 1.91 | 1.03 | 1.21 | 1.25 | 1.20 | 1.47 |
| 1–2 years | 1.08 | 1.47 | 1.02 | 1.02 | 1.34 | 1.37 |
| 2–5 | 0.89 | 1.00 | 1.05 | 1.00 | 1.06 | 1.40 |
| 5–10 | 0.77 | 0.87 | 0.86 | 0.92 | 0.89 | 1.48 |
| 10+ | 0.50 | 0.58 | 0.73 | 0.88 | 0.87 | 1.10 |

Familiarity (merged CLs, author's earlier commits in the directory) gives
the same pattern. The neg index goes from about 1.1 on a first CL in a
directory to 0.24–0.31 after 100 or more commits there, in every era.

- **Negative votes** are a learning signal, as strong as the feedback index:
  newcomers draw about 5× a 10-year veteran's rate. After the first three
  months the newcomer premium has been smaller since 2025 (1.0–1.3 against
  1.9–2.7 in 2023–24).
- **Abandonment** fell gently with tenure before 2026. In 2026 it rose at
  every tenure, most for newcomers (twice the norm in their first quarter)
  but also for 5–10-year veterans (1.48). That is consistent with cheaper,
  more exploratory CLs. It isn't evidence of weaker skill.
- **Per author, abandonment doesn't track tenure** (2026-11-08,
  `scripts/balance_authors.py`): over Nov 2025 – Oct 2026, among 1,152
  authors with 10+ reviewed CLs, the rank correlation of tenure with the
  share abandoned is 0.03 (median 6.3% under 2 years, 6.7% at 10+). The
  index above differs by tenure mostly in the first quarter, which few
  of those authors are in; between people, the spread (p90 17%) swamps it.

By start cohort (months since first commit), neg index and abandon index:

| Months | 2023 joiners | 2024 joiners | 2025 joiners |
|---|---|---|---|
| 0–3 | 3.12 / 1.29 | 2.57 / 1.18 | 2.59 / 1.44 |
| 3–6 | 2.61 / 1.16 | 2.14 / 1.14 | 1.38 / 1.42 |
| 6–9 | 3.13 / 1.25 | 1.27 / 1.00 | 1.21 / 1.22 |
| 9–12 | 2.16 / 1.21 | 0.55 / 1.21 | 1.15 / 1.16 |
| 12–18 | 0.70 / 1.12 | 1.76 / 0.87 | 0.78 / 1.01 |

The 2025 joiners' −1 rate falls quickly, but no faster than the 2024
joiners'. They abandon more CLs in their first six months (index about 1.4
against 1.1–1.3). Cells hold 130–450 people and votes are rare, so the
neg-index cells move by ±0.5 from noise alone.

### Arriving better equipped, or easing off? (balanced panels, 2024 → 2026)

**Reviewer side** (527 reviewers with ≥ 20 reviews in both years; 84k and
96k reviews):

| Per review, like for like | Change, 95% CI |
|---|---|
| log(1 + threads started) | **−0.032** (−0.047 to −0.018): about 3% fewer threads |
| −1/−2 vote rate | +0.001 (−0.000 to +0.002): no change |

Raw: 3.10 → 2.94 threads per review.

**Author side** (590 authors with ≥ 10 reviewed CLs in both years). Each
measure is adjusted for size and the author's current tenure band:

| Per CL | 2024 → 2026 raw | Adjusted change, 95% CI |
|---|---|---|
| Threads received (log) | 1.51 → 1.42 | **−0.093** (−0.111 to −0.074) |
| Rounds | 1.47 → 1.33 | −0.10 (−0.14 to −0.06) |
| Interdiff share | 0.36 → 0.35 | +0.010 (−0.002 to +0.022): flat |
| Reverted within 30 days | 3.4% → 3.3% | −0.002 (−0.006 to +0.002): flat |
| Abandoned | 5.0% → 6.8% | **+0.026** (+0.019 to +0.033) |
| Uploads before sending | 2.03 → 2.55 | **+0.41** (+0.31 to +0.52) |
| Any −1 received | 0.38% → 0.41% | flat |

**Verdict.** The evidence leans to *reviewers easing off*, modestly. It
does not show authors arriving better equipped:

- The same reviewers, on like-for-like CLs, write about 3% fewer threads.
- The same authors receive about 9% fewer threads. The gap beyond 3%
  comes from which reviewers they get, and from reviewers who left or
  joined the panel.
- On the author-side signals reviewers don't set, those authors are no
  better:
  - their CLs change as much after the first review;
  - they are reverted as often;
  - they are abandoned more often.
- Authors do iterate more on their own before sending, about 0.4 more
  uploads per CL. That fits AI-assisted self-revision, but it hasn't shown
  up as less change after review.
- Rounds fall because rounds are triggered by new reviewer threads, so
  they follow the threads.
- Flat interdiff alongside fewer threads also means the threads that
  remain drive as much change as before. So reviewers may be dropping
  low-value comments rather than real problems.

### Matched cohorts: 2025 against 2024 joiners

499 joiners in 2025 and 435 in 2024 (first commit since 2023-W26). Of
these, 310 pairs were matched on size, top-level directory, domain group
and prior Gerrit activity. Only 6–7% of either year had commented in Gerrit
before their first commit. The google.com/chromium.org share is 61% and
56%.

| Months 9–12 | Joined 2025 | Joined 2024 |
|---|---:|---:|
| Still active | 42% | 39% |
| Merged CLs per active month | 6.45 | 4.00 |
| Reviews given per active month | 2.45 | 1.32 |
| Feedback index | 1.43 | 1.93 |
| Thread residual, calendar-adjusted | 0.84 | 1.02 |
| Interdiff share, median | 0.29 | 0.37 |
| Rounds | 1.76 | 2.09 |
| Any −1 | 0.5% | 0.2% |
| Abandoned | 6.3% | 6.8% |

At 3–6 months the order is the same: 5.0 against 3.2 CLs a month, feedback
index 1.83 against 2.28, and abandonment 8.6% against 6.5%.

**Verdict.** The 2025 joiners' lead survives matching:
- They land more and review others more.
- They draw less review feedback than matched 2024 joiners.
- Their CLs also change less after review: interdiff 0.29 against 0.37, an
  author-side signal.
- Their thread residual is lower even against the same quarter's norm.

So their lead isn't the 2026 project-wide drop alone. Survivorship is
similar in both arms. The one cost is early abandonment (8.6% against 6.5%
at 3–6 months). For newcomers, then, the signs lean to *arriving better equipped*,
unlike the established-author panel.

## Caveats

- **−1 votes are too rare to read person by person.** Cells under a few
  hundred CLs swing a lot.
- **The panels compare 2024 with 2026 only.** There is no pre-AI pair of
  years with the same two-year ageing. The tenure-band adjustment nets out
  the typical ageing curve, but not cohort-specific change. The 2020–23
  backfill will allow a 2021 → 2023 placebo panel.
- **Reviewer-panel selection.** Reviewers active in both years are the
  steady core. People who left or joined aren't in it.
- **Matching.**
  - It is exact on coarse cells, so 189 of the 499 2025 joiners had no
    match.
  - The matched comparison has no confidence intervals yet. Pairs are
    random within cells (seed 5).
  - "Prior Gerrit activity" covers only comments since 2023-W26, so it
    misses experienced engineers from other Gerrit hosts and repos.
- **Abandonment.**
  - Abandoned CLs include duplicates, experiments and CLs replaced by
    another; none of these is a skill signal.
  - The 2026 rise may also reflect AI-drafted CLs that are cheap to
    discard.
