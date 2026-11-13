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

- **`python3 -m cosh commits`** (`cosh/commits.py`) reads the local clone,
  offline. Until 2026-11-12 it rebuilt two tables of `derived.sqlite`
  (`commits` and `commit_dirs`) at the end of every full `derive`; it now
  keeps `data/private/commits.sqlite` up to date instead (next section).
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
  section works under Commits; Review complexity shows
  review comments, as it does for Reviewed CLs; Contribution depth shows
  each author's files changed per commit (`author_weekly.json` has a files
  column: every file the counted commits change, in scope or not). A
  person's monthly chart plots their commits per month as a curved line.
  Sections were renamed so
  they fit either side, and no heading changes with the metric anymore:
  Contribution by organization, Contribution by directory (and over time),
  Contribution per person, Leaderboard, Contribution depth. Orgs are named in the
  charts if they have 0.25% of review comments *or* of commits.
- **Ratio** (organization chart, Off by default): the chosen review metric
  ÷ commits per org and week (addressed comments ÷ commits under Commits),
  "Ratio shows … over commits". Last year (2025-W45 .. 2026-W44),
  addressed comments per commit: opera.com 2.74, microsoft.com 2.18,
  intel.com 1.56, google.com 1.31, igalia.com 0.26, Other 0.16.

## commits.sqlite: one store for main's history (2026-11-12)

Main's history used to be read four times: `cosh commits` into
`derived.sqlite` (since the oldest fetched week, file names only),
`python3 -m cosh.balance git` into `balance-git.sqlite` (since 2017, with
line counts), `cosh.feedback.early_commits` (before 2017, on every run),
and by hand for the balance scripts' `--first-commit`, `--owners-added` and
`--ai-marked` files, plus `BALANCE_MECH_OUT` for `--mech`. Now one step
writes one store, and everything reads it:

```
python3 -m cosh commits [--jobs 4]      # offline; GIT_NO_LAZY_FETCH=1
```

`data/private/commits.sqlite` (`$COSH_COMMITS_DB` overrides the path) holds
every first-parent commit of `main` since 2008, with its first-parent
diff's files and line counts. It is incremental: a run appends the commits
landed since the last one (seconds when nothing is new), then their OWNERS
additions and repetition ratios. Rebuild it by deleting the file and
rerunning: about 1 h 50 min (1.5 h of `git log`, then 20 min of OWNERS diffs and repetition ratios with 4 processes) from empty, 1.1 GB, against 786 MB for `balance-git.sqlite` plus 442 MB for `derived.sqlite`'s two commits tables.

| Table | Rows | What |
|---|---:|---|
| `commits` | 1,676,752 | sha, git author (lowercased) and name, authored and landed (committer) time, CL (`Reviewed-on:`), `Bot-Commit:` flag, `Reviewed-by:` approvers, the commit it reverts, reland flag, AI-marker flag, files and lines |
| `commit_files`, `paths` | 13,556,620 / 1,642,612 | each file of its first-parent diff, with lines added and deleted (`-1` binary) |
| `owners_added` | 42,496 | each address on a line added to an OWNERS file (the first on the line) |
| `repetition` | 173,608 | 1 − distinct changed lines ÷ changed lines, for commits with a CL and 10 or more files (NULL over 50,000 lines) |
| views `gcommits`, `gfiles` | | the commits since 2017-01-01, the balance analyses' window |

`commit_id` is landing order: 1 is the first commit since 2017-01-01,
counting up, and the older history counts down from −1. So `commit_id > 0`
is the balance window, and its ids, path ids and row order are exactly
those of the former `balance-git.sqlite` (the store is built 2017-on
first, then the older history), which keeps every balance result
unchanged. "2017-01-01" is exactly what `balance-git.sqlite` had:
2017-01-02 02:47 UTC (`commits.BALANCE_SINCE`), because git's
`--since=2017-01-01` keeps the time of day of the run, so the 5 commits of
New Year's Day count as older history. Reverts are flagged two ways:
`reverts_sha` (a line "This reverts commit <40-hex sha>" after the subject
paragraph, as the balance scripts always read it) and `is_revert` (`git
log --grep='^This reverts commit'`, any line, which also catches SVN-era
reverts naming `r12345`; the earlier commits leave these out).

What reads it:

- **`summarize`** (`commit_facts`) and **`feedback_coach.py`**: the commits
  landed since `derived.sqlite`'s oldest fetched week
  (`commits.value_commits`, `commits.dirs_of`), with the bot rule above
  applied at read time.
- **`cosh.balance cl`** and the balance, feedback and review-ROI scripts:
  `balance.db_path("git")` is this file, read through `gcommits`, `gfiles`
  and `paths` as before.
- **The former hand-made inputs** are queries (`cosh/commits.py`, loaded by
  `scripts/balance_analysis.py`): `first_commits` (each author's first
  commit over all history), `owners_added` (since 2012), `ai_marked`
  (`AI_MARKER`, since 2023), and `mech_set` (merged CLs in `balance.sqlite`
  whose landed commit has 100 or more files, or 10 or more with a
  repetition of 0.8 or more). The scripts' `--first-commit`,
  `--owners-added`, `--ai-marked` and `--mech` flags still read the old
  files for exploration; without them the store is used.
- **`cosh/feedback.py`**'s earlier commits: the commits landed before
  2017-01-01.

Reproduced against the hand-made files on 2026-11-12: `gcommits`, `gfiles` and `paths` are row for row (ids and order) those of `balance-git.sqlite`; `first_commits` gives the same first commit for all 11,827 well-formed lines of `first_commit.txt`; `owners_added` the same 41,208 additions; `ai_marked` the same 1,002 shas; `mech_set` the same 11,624 CLs (every repetition ratio equal); the earlier commits the same 377,729. The Value window matches `derived.sqlite`'s commits and directories exactly, except the CL number: the store reads the short `Reviewed-on:` form (`chromium-review.googlesource.com/<n>`) that 152,372 commits of 2017-07 .. 2019 use and the old `cosh commits` missed. So `summarize` now credits 6,930 more of those commits to their CL owner's account (when no account has the git author's email) and counts 31 as bots' (bot-owned CLs); nothing after 2019 changes.

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
