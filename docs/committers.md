# Committers: telling them apart in data we already hold

Status: exploration, 2026-11-07. Nothing here is implemented yet.

Chromium committers are the members of `committers@chromium.org`. Spam and
drive-by comments come from everyone else, so several analyses
(`docs/sentiment.md`, "To do: split by committer and non-committer") want
each review comment tagged as written by a committer or not. This note shows
that the data we have already fetched answers that, with no new fetch.

## Signal 1: Gerrit's permitted voting range (status when fetched)

In chromium/src only committers may vote Code-Review. A reviewer on CL
7678490 told its owner "you aren't a chromium committer yet … you can't +1
changes" (`summaries/thread_examples.json`). Every listing we store
(`responses`, kind `list_window`, fetched with `DETAILED_LABELS`) gives, for
each account in `labels.Code-Review.all[]`, a `permitted_voting_range`.
Gerrit computes it from that account's permissions **at fetch time**.

Over all 10,274 listings (fetched 2026-11-03 13:14 to 2026-11-05 04:29 UTC,
856k CLs):

| CL status | Range | Meaning |
|---|---|---|
| `NEW`, `ABANDONED` | `{min:-1, max:1}` | may vote: committer |
| `NEW`, `ABANDONED` | absent | may not vote: not a committer |
| `MERGED` | `{1,1}` or `{0,1}` | may vote (the range is clipped to the vote already cast) |
| `MERGED` | absent | unclear: a committer with vote 0 also shows no range |

On open CLs the split is clean: of the 2,905 accounts seen there, 1,663 always
had `{-1,1}` and 1,242 never had a range; none had both. Over the whole
store, 1,918 accounts show a range somewhere and 2,468 lack one on an open or
abandoned CL. One account is in both sets (its status changed during the
fetch).

This needs no extra fetch, and each `extract-open` rerun refreshes it.
Coverage is limited to accounts listed as reviewer or CC, which nearly every
commenter is. Of last year's (2025-W45 .. 2026-W44) 483k non-bot comments in
`derived.sqlite`:

| Author | Comments | Accounts |
|---|---|---|
| committer | 476,877 (98.7%) | 1,559 |
| not a committer | 4,282 (0.9%) | 342 |
| unknown (never listed with a range) | 2,039 (0.4%) | 835 |

Most unknown accounts (621 of 835) are outside google.com and chromium.org.
Of the non-committers, 210 are google.com accounts: being a Googler does not
grant the vote.

## Signal 2: Code-Review votes in NoteDb (status at a point in time)

Signal 1 is today's status. To approximate status *when the comment was
written*, use votes: an account that cast a Code-Review vote at time T was a
committer at T. Votes outlive permission (70 `+1` votes on open CLs come from
accounts that can no longer vote), so a vote is evidence about the moment it
was cast, not about now.

A local scan of every NoteDb meta ref (`git log --all --grep='^Label:
Code-Review='`, about 2.5 min, no network) finds `Label: Code-Review=…` lines
from 2,212 accounts. "On behalf" lines (`Label: Code-Review=+1, Gerrit User N
<…>`) name the voter; they are mostly copies written at submit time, so they
can only make a first-vote time later, never earlier.

1,814 of the 1,918 current committers have voted, and so have 354 of the 2,468
current non-committers: those are former committers. Splitting reviewer
comments by the author's first and last vote:

| Author at comment time | 3 years (2023-W26 ..) | Last year |
|---|---|---|
| current committer, after first vote | 94.93% | 98.11% |
| current committer, before first vote | 1.24% | 0.52% |
| current committer, never voted | 0.04% | 0.06% |
| former committer (voted, can't now), after first vote | 2.48% | 0.36% |
| non-committer, never voted | 0.80% | 0.53% |
| unknown | 0.51% | 0.42% |

So today's list alone is a fine approximation for the last year (about 1% of
comments might be misplaced), but over three years it would call 2.5% of
comments non-committer that came from people who were committers then.

## Proposed rule

A comment by account A at time T is by a committer if

- A has a permitted Code-Review range now (signal 1) and T is at or after
  A's first vote, or A has never voted; or
- A has no range now but voted at some time at or before T, and T is no
  later than A's last vote plus a grace period (say 1 year; committer
  status lapses some time after the last vote).

Everything else is non-committer. Comments by a current committer written
before their first vote (0.5% last year) are the uncertain case. They could
be split by how long before the first vote they were written.

## Implementation sketch

- `derive`: add an `accounts.can_review` column (1, 0 or NULL) from the
  listings' ranges, taking the most recent listing per account. Add a
  `cr_votes(account_id, first_at, last_at)` table from the NoteDb scan. Both
  are rebuildable, so they belong in `derived.sqlite`, not the raw stores.
- Consumers (`cosh.sentiment`, `summarize`) apply the rule above and get a
  committer flag per comment.
- Optional, needs approval: `GET /projects/chromium%2Fsrc/access` (one
  request) would show which group the Code-Review grant goes to, confirming
  that it is the committers group. Gerrit doesn't expose the group's
  members anonymously, and fetching `committers@chromium.org` itself would be
  a new data source.
