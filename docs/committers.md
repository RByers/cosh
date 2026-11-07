# Committers: telling them apart in data we already hold

Chromium committers are the members of `committers@chromium.org`. Spam and
drive-by comments come from everyone else, so several analyses
(`docs/sentiment.md`, "To do: split by committer and non-committer") want
each review comment tagged as written by a committer or not. The listings we
already fetched answer that, with no new fetch. `derive` writes the answer to
the `committers` table in `derived.sqlite` (since 2026-11-07).

## The signal: Gerrit's permitted voting range

In chromium/src only committers may vote Code-Review. A reviewer on CL
7678490 told its owner "you aren't a chromium committer yet … you can't +1
changes" (`summaries/thread_examples.json`). Every listing we store
(`responses`, kind `list_window`, fetched with `DETAILED_LABELS`) gives, for
each account in `labels.Code-Review.all[]`, a `permitted_voting_range`.
Gerrit computes it from that account's permissions **when the listing is
fetched**.

| CL status | Range | Meaning |
|---|---|---|
| `NEW`, `ABANDONED` | `{min:-1, max:1}` | may vote: committer |
| `NEW`, `ABANDONED` | absent | may not vote: not a committer |
| `MERGED` | `{1,1}` or `{0,1}` | may vote (the range is clipped to the vote already cast) |
| `MERGED` | absent | tells us nothing: a committer with vote 0 also shows no range |

On open CLs the split is clean. Of the 2,905 accounts seen there, 1,663
always had `{-1,1}` and 1,242 never had a range; none had both.

## The table

`committers(host, account_id, is_committer, seen_at)`, built by
`cosh.derive.committer_evidence` from each CL's newest listing:

- `is_committer` is 1 if the account has a range on any listing, 0 if it
  lacks one on an open or abandoned CL. If listings disagree, the newest
  (`seen_at`, the listing's fetch time) wins.
- Accounts never listed on the Code-Review label of a listing that tells us
  have no row. Treat them as unknown, not as committers.
- Each `extract-open` rerun plus `derive` refreshes it.

Measured over all 10,274 listings (fetched 2026-11-03 13:14 to 2026-11-05
04:29 UTC), for last year's (2025-W45 .. 2026-W44) 483k non-bot comments:

| Author | Comments | Accounts |
|---|---|---|
| committer | 476,877 (98.7%) | 1,559 |
| not a committer | 4,282 (0.9%) | 342 |
| unknown | 2,039 (0.4%) | 835 |

Most unknown accounts (621 of 835) are outside google.com and chromium.org.
Of the non-committers, 210 are google.com accounts: being a Googler does not
grant the vote.

## Limit: it is today's status, not the status at comment time

Every listing was fetched within the same 40 hours, so the table is one
snapshot of early November 2026, even for a 2023 CL. Someone who was a
committer in 2023 and has since lost the status counts as a non-committer,
and someone who became one later counts as a committer for their earlier
comments.

The stored listings show this: 15,497 Code-Review votes on merged CLs (and 87
on open ones) come from accounts that have no range now. They could vote then
and can't today.

How much this matters was measured with NoteDb votes (a vote at time T shows
the voter was a committer at T). For last year's comments, about 1% may be
misplaced. Over three years (from 2023-W26), 2.5% of reviewer comments came
from 354 former committers, who voted then but can't now. The user chose the
snapshot as good enough (2026-11-07). If a long-range view needs more, the
fix is to count an account with no range now as a committer up to its last
Code-Review vote in NoteDb (`git log --all --grep='^Label: Code-Review='`
over the local meta refs, about 2.5 min, no network).

## Not used

- `GET /projects/chromium%2Fsrc/access` (one request; would need approval)
  would show which group the Code-Review grant goes to, confirming that it
  is the committers group.
- Gerrit doesn't expose the group's members anonymously, and fetching
  `committers@chromium.org` itself would be a new data source.
