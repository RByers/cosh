# Author and reviewer cohorts by clustering

`scripts/balance_clusters.py` groups person-half-years by what people did:
how much they authored, how much and whom they approved, and, since 2023 H2,
how much review their CLs drew and how they reviewed others. It then follows
people's paths through those groups. It is part of the Review Balance analysis
(`docs/balance.md`).

**Clusters are descriptions, not judgements.** They say what someone did in a
half-year relative to everyone active then, nothing about the quality of
their work. **Never publish anyone's cluster, PC scores or trajectory**
(`docs/plan.md`, ground rules 3 and 5; "no rankings"). Only the aggregates
below may appear on the public page. The per-person output is private and
lives in `data/private/balance_clusters/`.

## Method

**Who and when.** A person is one identity across addresses
(`balance_growth.Ids`, with `alias_pairs()`: the Gerrit owner and the git
author of the same CLs merge only when that author has at least 3 CLs and
at least half are owned by that address). A row is a person-half-year with
at least 3 authored commits, 3 approvals given (`Reviewed-by`), or 3
Gerrit reviews. People need a first commit on `main`, so pure commenters
without a commit are left out. The data covers 2017 H1 to 2026 H2; 2026 H2
runs only to October.

**Features** (raw values; `build_panel`):

| Feature | What |
|---|---|
| authored | log(1 + commits ÷ 6 months) |
| active_months | months with a commit ÷ 6 |
| size | log(1 + median changed lines), with 3+ commits |
| breadth | distinct 3-level directories among 10 random commits (rarefied, so it doesn't just track volume) |
| approvals | log(1 + approvals given ÷ 6) |
| review_share | approvals ÷ (approvals + commits) |
| newcomer_approvals | share of approvals on CLs by first-year authors |
| owner | 1 once first added to any OWNERS file |
| tenure | log(1 + years since first commit) |
| feedback_resid | mean residual of log(1 + threads) on the person's CLs, against size × directory × quarter (`cl_residuals`), from 2023 H2 |
| interdiff | median share of lines changed after first review, from 2023 H2 |
| rounds_resid | mean residual of review rounds, from 2023 H2 |
| threads_per_review | threads started per CL commented on, from 2023 H2 |
| response_h | log(1 + median weekday hours from being added to the attention set to the first comment), from 2023 H2 |
| gerrit_reviews | log(1 + others' CLs commented on ÷ 6), from 2023 H2 |

Every feature is turned into a z-score **within its half-year**. That way a
calendar effect, such as everyone landing more CLs in 2026, doesn't move
anyone, and the results show who does more or less than their peers. Missing
values become 0, the half-year's mean. Mechanical CLs use the repetition rule
in `docs/balance.md`.

**Two models**, each fit by PCA (Jacobi eigendecomposition of the covariance)
and then k-means (k-means++ with 5 restarts on a sample of 6,000, refined on
all rows):

- the **git model**, with the 9 git features from 2017 on, which can follow
  paths over nine years;
- the **review model**, with all 15 features from 2023 H2 on.

On silhouette, 4 clusters is best. The default is 6 (`--k`) because the
extra 2 keep distinct roles apart (mentors, a second early-career group),
at a modest cost. All silhouettes are low, 0.17 to 0.25: the clusters are
regions of a continuum, not separate types.

**Names** come from each centroid's profile (`name_cluster`), using neutral
words for what the group does. For paths, clusters fold into three families:

- **review:** reviewer-mentors, mostly reviewing, and authors who also review
  a lot;
- **light:** newcomers ramping up, early-career with light activity, and
  occasional contributors;
- **author:** the rest.

A **trajectory** compares the most common family in the first third of a
person's active half-years with the last third. It needs at least 4 active
half-years.

## How to regenerate

From a worktree or the main checkout, about 10 minutes and a few GB of RAM.
It reads `balance*.sqlite`, `commits.sqlite`, `derived.sqlite` and the shared Chromium clone,
and fetches nothing. Its inputs are the same as `balance_report.py`'s
(`docs/balance.md`), from `commits.sqlite`: the first-commit list, OWNERS additions and the
mechanical-CL list.

```bash
COSH_DATA_DIR=/home/rbagent/projects/cosh/data/private GIT_NO_LAZY_FETCH=1 nice -n 5 \
  python3 scripts/balance_clusters.py [--k 6] [--out DIR]
```

It prints the aggregate tables below and writes two files:

- `data/private/balance_clusters/clusters.json`: both models (features, PCA
  components, centroids, names, silhouettes) and the aggregates.
- `data/private/balance_clusters/people.json` (**private**), keyed by the
  canonical identity `Ids.find(email)`. Note that `A.person()` turns
  `user@chromium.org` into `user@google.com`, so look people up through
  `Ids.find`, not by raw address. Per person it holds `aliases`,
  `first_commit` (unix), `owner_at` (unix or null), `trajectory`, and
  `halves`: `{"2025H2": {git_cluster, git_pc[3], review_cluster,
  review_pc[3], features{…raw values…}, raw{commits, approvals,
  gerrit_reviews, median_lines, active_months}}}`. The review fields are null
  before 2023 H2.

Tests: `python3 -m unittest tests.test_balance_clusters` (PCA, k-means,
silhouette and naming on toy data).

## Results (run of 2026-11-08, after the identity fix)

There are 27,966 person-halves of 4,878 people in the git model and 11,249
in the review model.

**PCA.** Both models have the same first two axes:

- **PC1 (40%), "seniority and reviewing":** approvals, OWNERS status, review
  share and tenure.
- **PC2 (21%), "authoring activity":** active months and commits, against
  review share.

In the review model, PC3 (9%) gathers how much review a person's CLs drew:
feedback and rounds residuals and interdiff. It is mostly a newcomer signal.

**Git-model clusters** (medians per half-year):

| Cluster | Share | Tenure (y) | Commits | Approvals given | OWNERS |
|---|---|---|---|---|---|
| authors who also review a lot | 23% | 6.6 | 53 | 106 | 100% |
| steady authors | 20% | 2.8 | 32 | 18 | 95% |
| newcomers ramping up | 20% | 0.3 | 12 | 0 | 4% |
| mostly reviewing | 16% | 6.5 | 2 | 12 | 97% |
| early-career, light activity | 14% | 1.1 | 5 | 0 | 14% |
| reviewer-mentors (most approvals on newcomers' CLs) | 7% | 2.2 | 24 | 22 | 80% |

The review model finds the same six groups. Its "newcomers ramping up"
(11%, tenure 0.3 years) draw much more review feedback than usual for their CLs'
size and directory (feedback and rounds residuals +1.7 SD), and its
reviewer-mentors (6%) start a few more threads per review.

**Windows.** The shares barely move between pre-AI (2023 H2 to 2024 H2) and
recent (2025 H2 to 2026 H1) half-years, in both models. Steady authors fell
from 23% to 19% of the git model, and authors who also review a lot rose
slightly. Since shares are relative within each half-year, this says the
*mix of roles* is stable, not that activity levels are.

**Trajectories** (2,368 people with 4+ active half-years since 2017):

| Trajectory | Share |
|---|---|
| light → reviewer | 24% |
| stable reviewer | 22% |
| stays light | 21% |
| ramping up to author | 15% |
| author → reviewer | 10% |
| stable author | 4% |
| reviewer → author | 2% |

**Joiners at the same tenure** (first three years, 4+ active half-years):

| | 2017–2019 joiners (505) | 2021–2023 joiners (580) |
|---|---|---|
| light → reviewer | 32% | 23% |
| ramping up to author | 32% | 36% |
| stays light | 27% | 34% |

Within three years of joining, fewer of the 2021–2023 joiners moved into a
reviewing role than of the 2017–2019 joiners, and more stayed light. This
matches `docs/balance.md`, where mentees who became mentors fall from 16% to
4%. It began before AI tools.

**Year-over-year transitions** (family a year later, by starting half-years):

| From → | 2019–20 | 2021–23 | 2024 → 2025 | 2025 H1 → 2026 H1 |
|---|---|---|---|---|
| light → review | 19% | 17% | 20% | 22% |
| light → author | 27% | 28% | 19% | 24% |
| author → review | 47% | 49% | 46% | 48% |
| review → review | 86% | 86% | 83% | 86% |

Moving from authoring into a reviewing role a year later is steady at
about half throughout. The one dip is light → author into 2025 (19%), which
recovered in 2026. Nothing here shows the AI era cutting the step from
author to reviewer. The slowdown is in newcomers reaching reviewing within
their first three years, and that predates 2025.

## Map and rules (on the page)

`scripts/balance_cluster_map.py` (2026-11-08) draws the git-model patterns
for the page and turns them into plain criteria. Run it after
`balance_clusters.py`, then `balance_page_extras.py`:

```bash
COSH_DATA_DIR=/home/rbagent/projects/cosh/data/private python3 scripts/balance_cluster_map.py
COSH_DATA_DIR=/home/rbagent/projects/cosh/data/private python3 scripts/balance_page_extras.py
```

It reads `people.json` and writes `balance_clusters/map.json`, aggregates
only:

- **Maps.** Person-halves binned in 0.25-unit squares on PC1 × PC2 and
  PC1 × PC3, with each square's count and most common pattern. Squares
  with fewer than 5 person-halves are dropped (267 and 367 of 27,966), so no
  square stands for one person and no one's PC scores are published.
  PC1 × PC2 separates four patterns; PC3 (larger CLs, more approvals on
  newcomers' CLs) separates the two pairs that overlap there:
  reviewer-mentors from steady authors, newcomers from early-career.
- **Ellipses.** Per pattern and map, mean ± 1.5 SD along the principal axes
  of its scores. Each holds 62–71% of its pattern's half-years.
- **Rules** (`rule()`), checked in order on raw per-half-year values. They
  came from a depth-4 decision tree on raw counts (84% agreement), rounded
  to readable thresholds:

  | # | Pattern | Rule | Caught | Right |
  |---|---|---|---|---|
  | 1 | reviewer-mentors | 3+ approvals, a third or more on first-year authors' CLs | 92% | 65% |
  | 2 | authors who also review a lot | in OWNERS, 12+ commits, 50+ approvals | 78% | 89% |
  | 3 | steady authors | in OWNERS, 12+ commits, under 50 approvals | 74% | 79% |
  | 4 | mostly reviewing | in OWNERS, under 12 commits, approvals ≥ commits | 78% | 90% |
  | 5 | newcomers ramping up | anyone else with median CL ≥ 40 lines | 87% | 84% |
  | 6 | early-career, light activity | everyone else | 89% | 73% |

  They agree with k-means for 81.4% of person-halves. The rules use fixed
  counts while the clusters use within-half z-scores, so the fit varies a
  little by year.


- Low silhouettes: membership near a boundary is arbitrary, so read a
  person's path as a tendency, not a label.
- Relative within half-year: a cluster share can't show the project-wide
  shifts on the page (more CLs per author, fewer threads per line).
- `Reviewed-by` starts mid-2017 and counts approvers only, so 2017 rows
  under-count reviewing. Gerrit features exist only from 2023 H2.
- 2026 H2 covers four months, but per-month features and within-half
  z-scores keep it comparable.
- OWNERS status is "ever added by then", including team moves.
- People without a commit on `main` (reviewers only, or other repos) are
  not here.
