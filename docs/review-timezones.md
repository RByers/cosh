# Review Timezones

**Purpose.** Show where Chromium's review waits come from people working
in different hours, and where adding OWNERS, especially in other
timezones, would shorten them. It is for directory owners and leads
deciding whom to add to an OWNERS file, and for anyone wondering why their
changes wait overnight. The page is `web/review-timezones.html`, its data
`web/public/review-timezones/all.json`, written by `python3 -m
cosh.review_timezones` (`cosh/review_timezones.py`).

## The page

1. **Less overlap, longer waits**: every reviewer turn on the changes
   landed in the last four whole quarters, by how many working hours the
   author and the reviewer share (none, 1–2, 3–4, 5–6, 7–8), drawn as the
   median, middle half and 10th–90th percentile of the wait in the
   author's working hours. On 2025Q4 .. 2026Q3 (268,637 turns): median
   3.2 h with no overlap, 2.1 h with 1–2 h, 1.7 h, 1.2 h, and 0.9 h with 7–8
   shared hours; 20% of turns had 2 h or less in common.
2. **Who reviews whom**: the same turns by the author's and the reviewer's
   region (from their working hours): each author region's share of turns
   per reviewer region and the median wait. Authors in Asia-Pacific hours
   waited a median 2.1 h a turn, against 1.1 h in the Americas and 1.3 h in
   Europe, the Middle East and Africa; 34% of their turns went to reviewers
   in Asia-Pacific hours, against 86% of Americas authors' to the Americas.
   In 2026Q3, 891 people active in Gerrit worked Americas hours, 417 EMEA
   hours and 168 Asia-Pacific hours.
3. **Where an owner in other hours would help**: each directory with an
   OWNERS file and at least 400 turns, sorted by extra wait. Its columns
   are the turns, the people listed in that OWNERS file who were active in
   the last quarter by region, the share of turns whose author is *outside
   owners' hours* (sharing fewer than 4 working hours with every active
   owner listed there), where most of those authors work, the median wait
   outside and inside owners' hours, and the extra wait: outside turns
   times the difference of the two medians, the authors' working hours an
   owner in their hours might have saved. Each directory links to its
   OWNERS file on Code Search.

## Working hours

`cosh/work_hours.py`. We don't know where anyone works, so each person's
working day is guessed from public Gerrit timestamps: the comments they
wrote (not AI ones), their Code-Review votes (any value, removals too) and
the patch sets they uploaded. SQL counts them per person, quarter and hour
of the day (UTC), 24 numbers per person-quarter, so memory stays small
(about 74k person-quarters for 2017..2026).

- **The window**: the 8 consecutive hours (wrapping midnight) holding the
  most of a person's events in the quarter; among equal windows, the one
  whose middle is nearest the events. Measured on 2026Q3, the window held a
  median 85% of a person's events in the quarter (92% of a week's), the
  10th percentile 67%.
- **One per quarter.** Authors come to expect their reviewers' usual
  hours, so a trip isn't followed: the wait it causes counts. A move to
  another timezone shows from the next quarter. (A weekly window was
  tried: it moved more than 3 h in 7% of person-weeks, and the waits came
  out the same.)
- **Too little activity**: with fewer than 10 events in the quarter, the
  window is fitted to everything the person did up to its end (`basis`
  "history"), and failing that to everything they did. A reviewer with no
  events at all gets the CL owner's window. In 2017..2026, 49k
  person-quarters were fitted to their own quarter and 25k to history.
- **Timezone**: the window's start is taken as 09:00 local, which gives a
  UTC offset and so the person's own Saturday and Sunday (Monday morning in
  Tokyo is Sunday evening in UTC). Someone working noon to 8 pm in
  California is placed at UTC−11 by this, which moves their weekend by a
  few hours, not their working hours.
- **Regions** by where 09:00 local falls: UTC−11 .. −3 the Americas, UTC−2
  .. +4 Europe, the Middle East and Africa, UTC+5 .. +12 Asia-Pacific (New
  Zealand in its summer lands in the Americas).
- A span's **working hours** are its part inside the window on the
  person's weekdays. Holidays and leave aren't known.

`cosh.review_timeline` (its `reviewers` stage) stores the
windows in `work_windows` and gives each row of `cl_turns` two working-hours
figures: `work_h`, in the reviewer's window (the turn as the reviewer's
working time), and `owner_work_h`, in the CL owner's (the wait as the
author saw it). This page uses `owner_work_h`. The stage reads CLs 20,000
at a time, by key, and redoes only CLs whose inputs changed or whose
turns used a window that moved since the last run (a window looked up
then is kept in `work_windows`, so its move is seen). On a busy box on
2026-11-15 a week's worth of CLs took 22 s and 140 MB, and all of them
110-130 s and 160 MB (2.1 GB before it streamed); the windows take about
10 s and 70 MB of it.

On the turns of the CLs landed in 2026Q3 (82,209), the median turn was 2.7
weekday hours (UTC weekends left out, as Review Load counts) but 1.1 of the
reviewer's working hours and 1.3 of the owner's; the 90th percentile 35
weekday hours against 11 working hours.

## Definitions

- **Turns**: as on Review Load (`docs/review-load.md`, "Definitions"):
  stays of a reviewer in a change's attention set that ended before it
  closed, on the CLs of the reviewed commits landed in the four quarters
  (not by bots, not reverts, large-scale or mechanical). CLs without
  comments have no attention-set history here.
- **Overlap**: the hours two 8-hour windows share, 0 to 8, from the
  author's and the reviewer's windows in the quarter the turn started.
- **OWNERS directory of a change**: the nearest directory at or above each
  changed file that has an OWNERS file (at the end of the last quarter
  shown); the change counts, whole, in the one with most of its changed
  lines. A file renamed since the first quarter shown counts under its last
  name; older renames aren't followed, as they don't touch these commits.
- **Owners at work**: the addresses in that directory's own OWNERS file
  (and the files it includes with `file://`), not those inherited from
  above, matched to Gerrit accounts by each account's own address and by
  the git author address of each CL shown with the account that owned it
  (most often), counted when their window in the last
  quarter was fitted to that quarter (10 or more events). Inherited owners
  can approve too, but are left out so that the column says what this
  OWNERS file covers; `per-file` rules aren't read.
- **Outside owners' hours**: the author's window shares fewer than 4 hours
  with every owner at work there. A median needs 30 turns.

## Limits

- Activity in Gerrit isn't working time: people who split their day, or
  work long and uneven hours, fit less well, and someone who reviews from
  home late at night is placed there.
- A longer wait outside owners' hours isn't all down to the hours: those
  authors may be newer to the code, or their changes of another kind. The
  table shows where the hours differ, not why.
- An owner listed but rarely reviewing still counts as coverage.

## Against the goals (`docs/goals.md`)

- **A clean, constructive page (goal 1).** One chart and two tables. It
  names directories, never people, and describes waits as time a change
  waited. Its directory table points at where an owner would help, not at
  anyone's slowness.
- **Figures about an individual (goal 2).** None are published. A
  directory's owner counts by region can tell the region of a directory
  with a single owner, which is derived from public timestamps and isn't
  a negative figure (ground rule 3). The windows themselves stay in
  `review-timeline.sqlite` and are withheld from the data flow's samples.
- **Weekly update (goal 3).** The windows add about 9 s to the timeline's
  `reviewers` stage (counting each person's activity by quarter and hour:
  SQL groups 12M comments, votes and uploads, with each day's quarter
  joined from a small table, since SQLite's date functions per row took
  25–75 s). `review-timezones` takes 7 s and 200 MB: it reads only the
  four quarters' commits, file changes, CLs (by key) and turns, streams the
  tree listing when reading OWNERS, and matches OWNERS addresses without
  the Feedback Index's identities, which scan all of history (24 s and
  1.1 GB when this was written; 7 s and 135 MB since they stream it,
  2026-11-15; they matched 949 active owners' addresses, this 946). Whole
  quarters only, so the file changes when a quarter completes.
- **Repository volume (goal 4).** `all.json` is 16 KB.
- **Tokens (goal 5).** None.
- **Data flow (goal 6).** The windows and working hours live in the shared
  timeline store, so Review Load can use them too; one publish step.

## Not done yet

- Review Load's wait charts still count weekday hours (UTC); they could
  switch to working hours.
- A view of one directory over time, or by hour of the day (when its
  authors send changes against when its owners work).
