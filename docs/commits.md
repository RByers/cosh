# Commits: an author-side metric for Value Exchange

Status: built 2026-11-07 as the Value Exchange page's fifth metric
("Commits"), with a Ratio toggle on the organization chart. "If we build it"
below was the plan; "As built" says what shipped.

Every Value Exchange metric today credits the **reviewer**. This note tries
the classic other side: commits landed on `main`, credited to their
**author**, computed locally from `~/projects/shared/chromium` (no fetch).
Prototype: `scripts/commits_explore.py`.

## Method

- `git log main --first-parent --name-only`, 2023-W26 .. 2026-W44, with
  `GIT_NO_LAZY_FETCH=1`. A commit's week is the ISO week of its committer
  date in UTC (when the CQ landed it). The whole range takes **95 s**, all
  local.
- **CL:** the `Reviewed-on:` footer. Of 570,294 commits, all but 13 map to
  a merged CL already in `derived.sqlite`.
- **Bots:** the CL owner's `is_bot` flag from `derived.sqlite`, falling
  back to `config/bots.txt` on the git author. That leaves 399,261 human
  commits (171,033 bot commits, mostly autorollers).
- **Org:** `OrgResolver` on the git author email at the commit date, the
  same rule as for reviewers, with `gmail.com` folded into Other.
- **Scope:** a commit counts if it touches at least one file that
  `config/paths.txt` includes. That is 49.7% of human commits (74% of
  those touch only in-scope files). A fractional variant (the share of a
  commit's files in scope) is shown for comparison.

### Git author or Gerrit owner?

Same email on 92.7% of human commits; almost all of the rest are the same
person's `@google.com` and `@chromium.org` addresses. By org, the two
disagree on 113 of last year's 64,276 in-scope commits (0.2%), mostly
`xwf.google.com` authors on CLs owned by `google.com` accounts. Either
works. The CL owner would match the review metrics (the author side there
is the owner) and needs no git at all, except for the path scope. Only 231
commits carry a `Co-authored-by:` footer, so co-authors can be ignored.

## Last year (2025-W45 .. 2026-W44)

64,276 in-scope human commits, against 142,158 review comments and 83,434
addressed comments.

| Org | Commits | Share | Fractional | Unscoped | Authors | Comments | Addressed |
|---|---:|---:|---:|---:|---:|---:|---:|
| google.com | 56,065 | 87.2% | 85.6% | 91.9% | 1,778 | 89.0% | 88.1% |
| microsoft.com | 3,276 | 5.1% | 5.8% | 3.1% | 191 | 7.7% | 8.5% |
| igalia.com | 1,282 | 2.0% | 2.2% | 1.6% | 44 | 0.4% | 0.4% |
| Other | 1,229 | 1.9% | 2.1% | 1.3% | 215 | 0.3% | 0.2% |
| intel.com | 535 | 0.8% | 1.0% | 0.4% | 19 | 1.1% | 1.0% |
| opera.com | 414 | 0.6% | 0.8% | 0.3% | 7 | 1.1% | 1.4% |
| januschka.com | 304 | 0.5% | 0.5% | 0.3% | 1 | 0.0% | 0.0% |
| bytedance.com | 105 | 0.2% | 0.2% | 0.1% | 14 | 0.0% | 0.0% |
| samsung.com | 81 | 0.1% | 0.1% | 0.1% | 17 | 0.0% | 0.0% |
| **non-Google** | | **12.8%** | 14.4% | 8.1% | | 11.0% | 11.9% |

"Unscoped" is every human commit on `main`, Chrome product code included:
the path scope raises the non-Google share from 8.1% to 12.8%, as it does
for review.

Value ratios (share ÷ the org's browsers' share of Chromium usage, Radar
weekly average over the year):

| Org | Usage | Commits | Addressed | Comments |
|---|---:|---:|---:|---:|
| google.com | 71.9% | 1.21 | 1.22 | 1.24 |
| microsoft.com | 8.6% | **0.60** | 1.00 | 0.90 |
| samsung.com | 2.3% | 0.06 | 0.01 | 0.00 |
| opera.com | 1.8% | 0.37 | 0.77 | 0.61 |
| meta.com | 1.0% | 0.03 | 0.01 | 0.02 |
| alibaba-inc.com | 0.25% | 0.04 | 0.00 | 0.01 |

By year, non-Google commit shares and comment shares move together
(Microsoft 1.5% → 3.2% → 4.2% → 5.3% of commits from 2023 H2 to 2026), but
the gap between them is steady.

## What it shows

- **Commits tell a different story for some orgs.** Igalia and the
  independents ("Other", januschka.com) write far more code than they
  review: 2.0% of commits against 0.4% of addressed comments for Igalia.
  Microsoft and Opera are the reverse: about half as large by commits as
  by review. A page credited only by review leaves contract developers
  (Igalia's work is often paid for by browser vendors) and individuals
  nearly invisible.
- **Google's ratio barely moves** (1.21 against 1.22), so the headline
  question, whether others give back in proportion to their usage, comes
  out the same either way. The browser vendors other than Microsoft and
  Opera are near zero on every metric.
- **Counting commits rewards small CLs**, which `review-impact.md` warned
  against for comments. Lines changed would weight by size: `--numstat`
  takes about 20 s a week with the full blobs local, so about an hour for
  all 175 weeks. Lines have their own bias (generated files, mass
  renames, test data) and would need per-path exclusions.
- **Commits by Igalia may be paid work for another org.** Neither git nor
  Gerrit records the sponsor, so an author metric can only credit the
  author's employer, as the review metrics do.

## As built (2026-11-07)

The user chose: credit the git author, count commits (not lines), and add a
fifth metric button.

- **`python3 -m cosh commits`** (`cosh/commits.py`) rebuilds two tables of
  `derived.sqlite` from the local clone, offline: `commits` (sha, CL from
  the `Reviewed-on:` footer, git author, landing time, week, bot flag, file
  count) and `commit_dirs` (each directory a commit touches). About 1 min
  for 2023-W26 onward. A full `derive` runs it at its end; a per-week
  derive (backfill) doesn't.
- **Bots:** a commit is a bot's if its CL is bot-owned *or* its git author
  matches `config/bots.txt`. The second rule was added after the page named
  `chops-service-accounts.iam.gserviceaccount.com` as an org: a WebLayer
  builder authored 739 commits on CLs that people own.
- **`summarize`** adds `commits`, `authors` (distinct git emails) and
  `share_commits` to `org_weekly`, and writes three files the page loads
  only when Commits or Ratio is chosen: `author_weekly.json` (per author
  and week; the account is the Gerrit account with the git author's email,
  else the CL owner's), `area_commits.json` (per directory bucket, every
  commit, in scope or not, once in each bucket it touches) and
  `area_authors.json` (who made them, for the directory links, which search
  `owner:` and `status:merged`). Folded into the review files they would
  have doubled what every visit loads (commits touch far more directories
  than comments do); kept apart, every visit loads 31 KB more (gzipped).
- **The page:** a "Commits" button, a Commits tile and table column. Every
  section works under Commits; Review complexity and Contribution depth show
  review comments, as they do for Reviewed CLs. Sections were renamed so
  they fit either side, and no heading changes with the metric anymore:
  Contribution by organization, Contribution by directory (and over time),
  Contribution per person, Leaderboard, Contribution depth. Orgs are named in the
  charts if they have 0.25% of review comments *or* of commits.
- **Ratio** (organization chart, Off by default): the chosen review metric
  ÷ commits per org and week (addressed comments ÷ commits under Commits),
  "Ratio shows … over commits". Last year (2025-W45 .. 2026-W44),
  addressed comments per commit: opera.com 2.74, microsoft.com 2.18,
  intel.com 1.56, google.com 1.31, igalia.com 0.26, Other 0.16.

## The plan before building

1. `cosh commits` (or a step in `derive`): one row per `main` commit into
   `derived.sqlite`: sha, CL, author email, landed week, bot flag, in-scope
   file count, file count. Local only, under 2 min, rebuildable. The file
   list also gives `derive` the CL's real files (plan, Next steps 9).
2. `summarize`: `commits` per (week, org) in `org_weekly`, and per author
   in `reviewer_weekly` (or a new `author_weekly.json`).
3. UI: a fifth "Contribution metric" button ("Landed CLs"), with the
   page's description widened from "code review" to "code and review". Or,
   since this is the other side of the exchange, a separate author series
   next to the review ratio rather than one more interchangeable metric.

Open questions for the user: author by git or by Gerrit owner (they agree
on 99.8% by org); count commits, lines, or both; and whether authorship
belongs on the Value Exchange page or on the balance page (Next steps 7).
