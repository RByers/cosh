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
2. **Lines reviewed per reviewer**: the quarter's reviewed lines over the
   people who reviewed anything in it. The tooltip gives each quarter's
   change on the quarter before and on a year before.
3. **Time to first review**, weekends left out:
   - *upload to first review* (mean and median, all quarters): a CL's
     creation to the first Code-Review vote or comment by a human other
     than its owner, over the CLs that got one;
   - *reviewer's turn to first answer* (mean, from 2021Q1): a reviewer
     entering the attention set to their own first vote or comment.
4. **Reviewers' time in the attention set** (from 2021Q1), weekends left
   out: the total over all reviewers, and the mean per reviewer.
5. **Where the load is**: a table by directory (three levels, opened level
   by level) for the last four quarters: lines reviewed, each quarter's
   change in lines reviewed on the quarter before, and each quarter's mean
   attention-set hours per CL and reviewer, shaded against all of Chromium
   in that quarter (red: twice as long or more; green: half or less).

Typing an address adds that reviewer: a line on each chart (commits they
reviewed, lines they reviewed, their turn-to-answer time, the hours CLs
spent in their attention set) and two table columns (their lines reviewed
and hours per CL in each directory, shaded against everyone's there).

## Definitions

- **Reviewed commit**: not by a bot, not a revert, not part of a large-scale
  change (`is_lsc`), not mechanical (100+ files, or 10+ files with a
  repetition ratio of 0.8+, as `commits.mechanical`), with a `Reviewed-by`
  footer naming a person other than the author.
- **Lines reviewed**: a reviewed commit's insertions plus deletions (a
  renamed file by the lines changed in it, a binary file 0), once for each
  such reviewer. A commit with two reviewers counts twice: the measure is
  review work. Reviewers who commented without approving are not in
  `Reviewed-by` and don't count here.
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
- **Directory**: of the lines changed, as the directory is named today
  (`commits.current_paths`). A commit counts in each directory by its lines
  there; a CL's attention-set hours are split the same way. A directory is
  listed with 5,000 lines reviewed in the four quarters; the rest of its
  parent is "Other".
- **People**: exact identities, the Feedback Index's
  (`cosh.people.exact_identities`; docs/review-feedback.md, "Who is who"):
  addresses merge only on evidence, never by domain. Gerrit accounts map
  through their address. Each other address of a reviewer gets a
  `{"see": <name>}` file, so typing any of them finds them.

## Data flow

```
gerrit.sqlite + notedb/ ─┐
reviews.sqlite ──────────┴─ review-timeline ─▶ review-timeline.sqlite ─┬─▶ balance-interdiff, balance-cl, …
commits.sqlite, reviews.sqlite ───────────────────────────────────────┴─ review-load ─▶ web/public/review-load/all.json
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
  attention hours; rebuilt whole). Balance's `cl` stage takes `sent_at` and
  `cl_attention` from `cl_reviewers`.
- `nice -n 5 python3 -m cosh.review_load` (`cosh/review_load.py`) writes
  the page's files. `python3 -m cosh update` runs both.

Published files: `all.json` in `web/public/review-load/` (committed), and
the per-reviewer files, written gzipped to `data/private/review-load-people/`
and uploaded, when deploying, by `python3 -m cosh.r2 publish review-load/people/v2` to the
R2 bucket (`docs/r2.md`; until 2026-11-14 they were committed next to
`all.json`). On localhost the page reads the local copies:

| File | Holds |
|---|---|
| `all.json` | per quarter: commits, reviewed commits and lines, reviewers, both waits (mean, median, count), attention hours, turns and reviewers; the table's directories at every level with five quarters of lines and four of attention |
| `<name>.json` | one reviewer, in one file (version 2), fetched in one request: `years`, by year, `{"q": {quarter number: [commits reviewed, lines reviewed, attention weekday hours, turns, asked-to-answer hours (summed), answers]}}`; and `dirs`, by quarter (the table's four), their 3-level directories `[directory, lines, attention hours, turns]` |

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
  change against everyone's in the same directory). The charts don't yet:
  their lines and waits are drawn against all of Chromium's mean, whatever
  directories they review in, and nothing has been measured about how
  reproducible a reviewer's quarterly figures are.
- **Weekly update (goal 3).** The timeline step reads only CLs and listings
  that are new or changed, then rebuilds `cl_reviewers` (about 1.5 min in
  all when little is new); `review-load` takes 30 s and 1.5 GB. Because
  only whole quarters are published, past figures don't move and a new
  week changes no file until it completes a quarter.
- **Repository volume (goal 4).** 7.6 MB in 23,774 files on 2026-11-14
  (`all.json` 93 KB, 38 KB gzipped). A year's files are frozen once the
  year ends; a completed quarter rewrites that year's files for the
  reviewers active in it (about 2,200 files of about 100 bytes) and adds
  one folder of directory files (about 1,400 files, 1.6 MB), while the
  oldest directory folder is removed.
- **Tokens (goal 5).** None: no model calls.
- **Data flow (goal 6).** One shared store (`review-timeline.sqlite`), one
  publish step, two published stores.

## Not done yet

- OWNERS: which reviewers are owners of what they review, and how much of
  a directory's review its owners carry (`commits.sqlite` has
  `owners_added`).
- Second +1s for non-committers' changes by people who aren't OWNERS
  (`reviews.sqlite` has `committers`; the votes are in the timeline).
- How unevenly a directory's review is spread over its reviewers.
- When review was requested before the attention set (2017–2020): NoteDb
  records reviewer additions, which the walk doesn't read, so the long
  series starts its clock at the CL's first upload.

Tests: `tests.test_review_timeline`, `tests.test_review_load`; the page's
in `web/test/` ("review load").
