# Review Load

`web/review-load.html` shows how much code review lands on Chromium's
reviewers, how long changes wait for them, and where. Its purpose is to
show how overloaded reviewers are and to help spread the load: where
existing reviewers could take more, where more reviewers are needed, and
(not built yet) where people who aren't OWNERS could give the second +1 a
non-committer's change needs. It is judged by `docs/goals.md`.

Kept current, like `docs/data-architecture.md`: this describes the page as
it is. Decisions are logged in `docs/plan.md`.

## What the page shows

Whole quarters only, from 2017Q3 (Gerrit and `Reviewed-by` footers start
mid-2017) to the newest quarter that both the fetched Gerrit weeks and
main's history cover.

1. **Commits landed per quarter**: every first-parent commit on `main`, and
   those excluding bots (no `Bot-Commit` footer, author not in
   `config/bots.txt`).
2. **Lines reviewed per reviewer**: the spread of each reviewer's lines
   reviewed in the quarter, over the people who reviewed anything in it,
   drawn as the Feedback Index draws one (median line, middle half and
   10th–90th percentile shaded; all three charts of spreads are drawn this
   way since 2026-11-15). The tooltip gives the median's change on the
   quarter before and on a year before; the note also gives the mean.
3. **Reviewer's turn to first answer** (the same spread, from 2021Q1,
   weekends left out): a reviewer entering the attention set to their own
   first vote or comment. The chart starts in 2021Q1. (Upload
   to first review was dropped on 2026-11-14: its clock includes the
   owner's own time before asking for review.)
4. **Reviewer response time** (from 2021Q1, weekends left out): the
   hours of every reviewer turn on the CLs landed in the quarter, drawn as
   the Feedback Index draws a spread: the median a line, the middle half
   (25th–75th percentile) and the 10th–90th percentile shaded. It replaced
   the mean attention-set hours per reviewer on 2026-11-15, a load figure
   whose scale didn't sit with the waits. On 2026Q3: 80,259 turns, median
   2.8 h, middle half 0.4–17 h, 10th–90th 0.1–35 h, mean 16 h.
5. **Where the load is**: a table by directory (three levels, opened level
   by level) for the last four quarters: lines reviewed (shaded on a log
   scale, white to dark blue, from the listing threshold to the biggest
   top-level directory), each quarter's
   change in lines reviewed on the quarter before, and each quarter's
   reviewer response time at the percentile chosen above the table (the
   90th by default, or the median or 75th), shaded against all of
   Chromium's same percentile in that quarter (red: twice as long or more;
   green: half or less).

Typing an address adds that reviewer: a line on each chart (commits they
reviewed, lines they reviewed, their turn-to-answer time, the hours CLs
spent in their attention set) and two table columns (their lines reviewed
and the chosen percentile of their turns in each directory over the four
quarters, shaded against everyone's there).

## Definitions

- **Reviewed commit**: not by a bot, not a revert, not part of a large-scale
  change (`is_lsc`), not mechanical (100+ files, or 10+ files with a
  repetition ratio of 0.8+, as `commits.mechanical`), with a `Reviewed-by`
  footer naming a person other than the author.
- **Approver**: a person in a commit's `Reviewed-by` footers. Gerrit
  writes one footer for each positive Code-Review vote (+1 or +2) standing
  on the patch set that is submitted, so the footers are the approvers,
  not everyone added as a reviewer: someone added who never voted is left
  out, and so is someone whose vote a later patch set cleared. Checked on
  2026-11-15 against `review-timeline.sqlite`'s votes, for human commits
  (no reverts or large-scale changes) landed in 2018, 2021 and 2025: 99.4%,
  99.1% and 99.8% of footer names had a positive vote standing at submit;
  every sampled exception voted under another address (a changed address,
  or an account with no address in Gerrit's data). Of the
  reviewers added to those changes (`cl_reviewers`), 5%, 15% and 16% are
  in no footer, and 93%, 97% and 81% of those never voted: it is common
  for one reviewer to approve before another gets to the change. Counting
  every +1 ever cast instead would have added at most 4% more names in
  2025, people
  whose vote a new patch set cleared; the footers are kept. Lines reviewed
  and the owner figures use approvers; the Gerrit review times count
  everyone asked, approver or not, since being asked is load.
- **Lines reviewed**: a reviewed commit's insertions plus deletions (a
  renamed file by the lines changed in it, a binary file 0), once for each
  such reviewer who read the file (see "Who read what"). A commit whose two
  reviewers both read a file counts its lines twice: the measure is
  review work. Reviewers who commented without approving are not in
  `Reviewed-by` and don't count here (see **Approver**).
- **Reviewer** (Gerrit figures): a human account other than the CL's owner.
  The CLs are those of the reviewed commits, in the quarter they landed.
- **Answer**: a Code-Review vote (not a removal) or a comment before the
  CL closed. CLs without comments have no local NoteDb ref (extract
  fetches NoteDb only for CLs with comments), so for them only the votes
  standing in the listing are known; a vote that a later patch set cleared
  is missed there.
- **Attention-set hours**: the union of a reviewer's attention-set
  intervals on a CL, from its creation to its close, without Saturdays and
  Sundays (UTC). Elapsed time a CL waited on someone, not time spent
  reviewing. CLs without comments (about a fifth) have no attention-set
  history locally and are not counted.
- **Turn**: one stay of a reviewer in a CL's attention set (overlapping
  intervals merged), from being added to leaving it: about five in six
  end with the reviewer's own vote or comment, the rest because the owner
  or someone else took them out. **Reviewer response time** is the
  working hours (below) of turns that ended before the CL closed. A turn still open when
  the CL landed (within a minute of its close) is left out: the CL didn't
  wait on that reviewer. Per turn rather than per CL, so a directory whose
  changes go back and forth more (more careful reviewers, more complex
  code) isn't marked slow for it. Measured over 2025Q4 .. 2026Q3
  (2026-11-14): a reviewer had 1.69 turns per CL, 1.3 to 2.5 across
  2-level directories, which explained little of their spread (log
  variance 0.026 of 0.372; per turn 0.325), so the switch barely reranks
  directories. Leaving out the turns open at the close mattered more:
  5% of turns but 15% of the hours (mean 52 h, against 15 h for turns a
  reviewer ended by answering). `mojo/public/`, for one, had 63% of its
  hours in them.
- **Working hours** (since 2026-11-16): both wait charts and the
  directory table count only the hours inside the **reviewer's** working
  window: the 8 hours of the day holding most of their Gerrit activity,
  Monday to Friday where it starts at 09:00, fitted per quarter
  (`work_windows`; `docs/review-timezones.md`, "Working hours"). A turn's
  are `cl_turns.work_h`; the time to first answer is computed here from
  the reviewer's window in the quarter they were asked (else their latest
  earlier one, else their earliest). The page measures how quickly
  reviewers answer, so a night in the reviewer's timezone isn't counted
  against them; what the overlap costs the author is Review Timezones'
  subject. Until then they were weekday hours (Saturdays and Sundays UTC
  left out). On 2026Q3: the median turn 2.78 → 1.14 h, the 90th
  percentile 35 → 11 h, the median first answer 3.91 → 1.47 h; every
  turn and answer still counts (all have a window). Directories' 90th
  percentiles over the four quarters keep their order (Spearman rank
  correlation 0.98 over 752 directories); their medians move more (0.86), since a turn
  spanning a night or a weekend now counts near zero. The per-person
  file's attention-set hours (`years`, third figure) are still weekday
  hours; the page doesn't show them.
- **Directory**: of the lines changed, as the directory is named today
  (`commits.current_paths`). A commit counts in each directory by its lines
  there; a CL's turns count in each by the same share, as weights of the
  directory's percentiles (weighted: the turn whose cumulative weight
  first reaches the share). The percentiles are computed in
  `cosh.review_load` for every row the page can show (each directory, its
  "Other", and a looked-up reviewer's rows), since percentiles don't add
  up the way the lines do. A directory is
  listed with 5,000 lines reviewed in the four quarters; the rest of its
  parent is "Other".
- **People**: exact identities, the Feedback Index's
  (`cosh.people.exact_identities`; docs/review-feedback.md, "Who is who"):
  addresses merge only on evidence, never by domain. Gerrit accounts map
  through their address. A person is named by the address they used most
  recently, never one they left behind (docs/goals.md, goal 2). Accounts
  that Gerrit shows with no address (mostly deleted ones) are mapped
  through the address their votes or CLs tie them to (`Ids.accounts`), so
  their attention, turns and answers count. Each other
  address of a reviewer gets a `{"see": <name>}` file, so typing any of
  them finds them.

## Who read what

Nothing in git or Gerrit records which files of a change each of its
reviewers read, and crediting every reviewer with every line overstates
lines reviewed wherever reviewers share a change. Chromium needs an owner's
approval for every file, so `split_lines` (`cosh/review_load.py`) guesses
for each file of a commit with two or more approvers:

- The **first of the file's owners among the approvers to approve** reads
  it (OWNERS at the last commit of the commit's quarter, by the file's path
  in that commit; first Code-Review vote above 0 in the timeline's `votes`
  and `listing_votes`; with no vote found, the first approver listed). A
  common pattern: the owner of a narrow directory reviews most of a change
  and a broader owner is added for a few more files. The narrow owner
  approves first and is credited with everything they own; the broader one
  only with the files nobody before them could approve.
- **Approvers who own none of the commit's files** read all of it: a
  teammate's review before an owner's stamp.
- **Anyone who commented** on a file in that directory before the CL
  closed read it (`reviews.sqlite` `comments`, file comments only).
- A file **no approver owns** is read by all of them.

`per-file` rules are not read, so an owner by `per-file` alone counts as no
owner. `reviewers_per_commit.every` keeps the lines had every reviewer read
every file, the upper bound; the lower bound is each line read once.

Measured on 2026-11-15: each changed line was read by 1.36 reviewers in
2017Q3 and 1.28 in 2026Q3 (between 1.19 and 1.50 in every quarter),
against 1.74 and 1.59 had every reviewer read every file (1.44 to 1.90);
1.48 and 1.38 reviewers per commit, 33% and 30% of commits with two or
more. Lines reviewed per reviewer in 2026Q3 came to a median of 2,034
(2,668 crediting every line to everyone), a 90th percentile of 18,103
(23,166) and a mean of 6,446 (7,988). So per reviewer the figures are at
most 28% too high (had each line been read once) and 24% too low (had
everyone read everything), and the estimate moved 6% from 2017Q3 to
2026Q3, against 9% for the upper bound: how reviewers share changes
barely moves the trend.

Approvals that name what they cover ("third_party/blink LGTM", "//content
lgtm") could replace the guess where they exist, but they are rare: in
1,500 sampled commits with two or more approvers from each of 2018Q3,
2022Q3 and 2026Q3, 3%, 2% and 1% of approvals named a directory of the
commit (by regex over the vote's message and the reviewer's patch-set
comments within a minute of it; scratch script, 2026-11-15). As a check on
the guess: of those 212 approvals, the guess credited the reviewer with
exactly the named directories in 129 (61%), with more in 40, fewer in 23,
nothing in 11 and a different set in 9. So the page doesn't read approval
text.

## OWNERS and second approvals

The second table, "Who could share the load", covers the same four
quarters and directories. It is there to show where reviewers who are
already present could take more, where a directory depends on its owners
alone, and how much of the review of newcomers' changes owners do that
any committer could.

- **OWNERS files** are read from the shared clone (`cosh/owners.py`,
  offline) at the last commit of the last quarter shown, so the figures
  move only when a quarter completes. A file's owners are the addresses in
  its directory's `OWNERS` and in those of the directories above, up to one
  with `set noparent`; `file://` and `include` lines are followed; `*`
  makes everyone an owner; `per-file` rules are not read. Directories are
  today's names, and the OWNERS are one snapshot: someone made an owner in
  the last quarter counts as one for all four.
- **Half the review done by**: the fewest reviewers whose lines reviewed
  there add up to half of the directory's, next to how many reviewed there
  at all.
- **Owners who reviewed**: of the people listed in an OWNERS file in the
  directory or below (owners inherited from above aren't counted as
  listed there), how many are among its reviewers.
- **Reviewed by an owner**: the share of lines reviewed whose reviewer
  owns the file.
- **Lines needing two approvals**: a change by someone who is not a
  committer needs two committers' approval, one of them an owner. A person
  counts as a committer from their first Code-Review vote (the timeline's
  `votes` and `listing_votes`) or their first commit that landed with one
  reviewer, whichever is first; `reviews.sqlite`'s `committers` table is not
  used, because it is today's status. A commit by anyone else with two or
  more reviewers counts here, its lines once. With votes alone, over the
  four quarters to 2026Q3, 996 of 13,400 commits by such authors had landed
  with a single reviewer, 933 of them by people who can vote today
  (committers who hadn't voted yet): hence the single-reviewer rule.
- **Both approvals by owners**: the share of those lines that two or more
  owners of the file approved. The second of those approvals didn't have to
  come from an owner.

On 2026-11-15, for 2025Q4 .. 2026Q3: 1,550 reviewers, 122 of whom did half
the review; 1,123 of 1,386 listed owners reviewed something; 72% of lines
were reviewed by an owner of the file (66% before lines were split among
a change's reviewers, "Who read what"); non-committers' changes came to 1.41M
lines, 48% of them approved by two owners.

Nothing here is per person: no file names an owner or says what one did.

## Data flow

```
gerrit.sqlite + notedb/ ─┐
reviews.sqlite ──────────┴─ review-timeline ─▶ review-timeline.sqlite ─┬─▶ balance-interdiff, balance-cl, …
commits.sqlite, reviews.sqlite, OWNERS in shared/chromium ────────────┴─ review-load ─▶ web/public/review-load/all.json
                                                                                     └▶ data/private/review-load-people/ ─ r2 publish ─▶ R2
```

- `python3 -m cosh.review_timeline` (`cosh/review_timeline.py`) writes
  `data/private/review-timeline.sqlite`. It was the Review Balance stage
  `cosh.balance timeline`; both pages read it now, so it is its own step
  and store, and Review Load updates without rebuilding anything of
  balance. One run: the NoteDb walk (`uploads`, `attention`, `votes`;
  incremental by meta-ref tip), the listings' votes for CLs without
  comments (`listing_votes`; incremental by listing body), then
  `cl_reviewers` (per CL and reviewer: `asked_at`, `responded_at`,
  attention hours; and `cl_turns`, each turn that ended before the close
  with its weekday hours and its working hours, the reviewer's and the
  owner's, from each person's working window per quarter in `work_windows`:
  `docs/review-timezones.md`, "Working hours"; each CL redone only when
  its inputs, a working window it used or its accounts' bot status changed:
  `reviewers_done`, `reviewers_bots`). Balance's `cl` stage takes `sent_at` and
  `cl_attention` from `cl_reviewers`. The walk and the listing stages each
  keep a fingerprint of their code in `meta` (`walk_fingerprint`,
  `listing_fingerprint`; `cosh/codefp.py`): when it changes, that stage's
  rows are deleted and it reads every CL or listing again.
- `nice -n 5 python3 -m cosh.review_load` (`cosh/review_load.py`) writes
  the page's files. `python3 -m cosh update` runs both.

Published files: `all.json` in `web/public/review-load/` (committed), and
the per-reviewer files, written gzipped to `data/private/review-load-people/`
and uploaded, when deploying, by `python3 -m cosh.r2 publish review-load/people/v2` to the
R2 bucket (`docs/r2.md`; until 2026-11-14 they were committed next to
`all.json`). On localhost the page reads the local copies:

| File | Holds |
|---|---|
| `all.json` | per quarter: commits, reviewed commits and lines, reviewers, `reviewers_per_commit` (the reviewed commits' own lines, their reviewers summed, those with two or more, and `every`: the lines reviewed had every reviewer read every file), `reviewer_lines` (lines reviewed per reviewer), `reply` (the reviewer's turn to first answer) and `turns` (reviewer response time), each a spread: 10th, 25th, 50th, 75th, 90th percentile, mean and count; the table's directories at every level with five quarters of lines, four of the 50th/75th/90th percentile and turns, and the percentiles over the four; `others`: the same for each directory's "Other"; with OWNERS, each directory's seven figures (reviewers, how many did half, owners listed, owners who reviewed, lines reviewed by an owner, non-committers' lines, those two owners approved) and `owners`: the same for everything and the day of the OWNERS files |
| `<name>.json` | one reviewer, in one file (version 2), fetched in one request: `years`, by year, `{"q": {quarter number: [commits reviewed, lines reviewed, attention weekday hours, CLs counted in them, asked-to-answer hours (summed; the reviewer's working hours since 2026-11-16), answers]}}`; `dirs`, by quarter (the table's four), their 3-level directories `[directory, lines]` (until 2026-11-15 also attention hours and CLs); `turns`, by quarter, `[median working hours, turns]`; and `rows`, by table row (`d:<dir>`, `o:<dir>` for its "Other", `o:` for what no listed directory covers), their turns over the four quarters `[50th, 75th, 90th percentile, turns]` |

`<name>` is the address as typed, lower case, as the Feedback Index names its files
(`cosh.review_feedback.file_name`). The bucket can't be listed, so a
reviewer is found only by typing their address. Until 2026-11-14 a
reviewer's data was one file per year and per table quarter
(`review-load/people/v1/`, named by a salted hash), up to 14 requests of
about 100 bytes each for one lookup. Nothing on the page lists
or ranks people.

## Against the goals (`docs/goals.md`)

- **A clean, constructive page (goal 1).** Four charts and one table. The
  page shows load and waits as aggregates; it lists and ranks nobody, and a
  wait is described as time a change waited, not as a reviewer's fault.
- **Figures about an individual (goal 2).** A reviewer's figures appear
  only after their address is typed, and the page computes them from the
  published files. The table compares like with like (their hours per
  turn against everyone's in the same directory). The charts don't yet:
  their lines and waits are drawn against all of Chromium's mean, whatever
  directories they review in, and nothing has been measured about how
  reproducible a reviewer's quarterly figures are.
- **Weekly update (goal 3).** The timeline step reads only CLs and listings
  that are new or changed, then redoes `cl_reviewers` and `cl_turns` for
  those CLs and any whose working windows moved (22 s for a week of CLs); `review-load` takes 82 s and
  1.9 GB (2026-11-15), about half of it reading 37 quarters' OWNERS files (one quarter's at a time)
  and the files of every commit with two or more approvers for the split among them. Because
  only whole quarters are published, past figures don't move and a new
  week changes no file until it completes a quarter.
- **Repository volume (goal 4).** 7.6 MB in 23,774 files on 2026-11-14
  (`all.json` 114 KB, 48 KB gzipped, with the OWNERS figures). A year's files are frozen once the
  year ends; a completed quarter rewrites that year's files for the
  reviewers active in it (about 2,200 files of about 100 bytes) and adds
  one folder of directory files (about 1,400 files, 1.6 MB), while the
  oldest directory folder is removed.
- **Tokens (goal 5).** None: no model calls.
- **Data flow (goal 6).** One shared store (`review-timeline.sqlite`), one
  publish step, two published stores.

## Not done yet

- The OWNERS figures for one reviewer after their address is typed: what
  they own and review, and the second approvals they gave as a non-owner.
- `per-file` OWNERS rules, and OWNERS as they stood when each commit landed.
- When review was requested before the attention set (2017–2020): NoteDb
  records reviewer additions, which the walk doesn't read, so the wait
  charts start in 2021Q1.

Tests: `tests.test_review_timeline`, `tests.test_review_load`; the page's
in `web/test/` ("review load").
