# Extraction v1: what is implemented

Status (2026-11-03): **2026-W44** (Mon 2026-10-26 to Sun 2026-11-01 UTC) was
extracted and validated first. The approved one-year backfill (2025-W45 ..
2026-W44) and an open-CL snapshot for the same year (`extract-open`) follow
it. Fetching beyond that needs approval (see `docs/plan.md`).

**metric_version 2** (2026-11-03): review activity counts in the week it
happened, not in the week the CL closed. See "Metric definitions" below.

This follows `gerrit-api-research.md` and `storage-design.md`. Below are the
decisions made while implementing it; where they differ from those docs, this
file wins.

## Commands

```
python3 -m cosh extract --week 2026-W44     # network; cached and resumable (NoteDb by default)
python3 -m cosh extract-open                # network; open-CL snapshot + its NoteDb refs (after the backfill)
python3 -m cosh derive [--out PATH]         # offline: raw cache -> data/private/derived.sqlite
python3 -m cosh summarize [--metric comments|cls|chars] [--db PATH]   # offline: -> summaries/
python3 -m cosh radar [--offline]           # Cloudflare Radar; needs `source secrets.sh`
python3 -m cosh backfill --weeks 52 [--go]  # plan only unless --go (the 52 weeks are approved)
python3 -m cosh update-affiliations         # refresh config/affiliations.json5
python3 -m cosh status
python3 -m unittest tests.test_derive tests.test_extract tests.test_radar
```

## Pipeline and data flow

```
Gerrit REST listing ─► data/private/raw.sqlite ─┐
NoteDb `git fetch`  ─► data/private/notedb/*.git ┼─ derive ─► data/private/derived.sqlite ─ summarize ─► summaries/
Cloudflare Radar    ─► data/public/radar/raw/ ──── radar ──► data/public/radar_browser_share.csv
```

- `data/private/` (gitignored for size; see `storage-design.md` §4) holds the
  raw stores and the derived DB.
  - `raw.sqlite` and `notedb/` keep **everything downloaded, losslessly and
    permanently**, even data no metric uses yet. This is the intended design;
    see `storage-design.md` §3.8, which also covers what NoteDb contains and
    the size per year.
  - `derived.sqlite` is derived (one row per comment and per vote, with
    lengths but no text) and can be rebuilt. `derive` opens `raw.sqlite`
    read-only. The older `cosh.sqlite` (metric_version 1, one row per CL and
    reviewer) is obsolete.
- `data/public/`, `summaries/`, `config/`, code and docs are committed.

## What we fetch from Gerrit, and how gently

Scope: `chromium/src`, **branch `main` only**: **merged and abandoned** CLs by
week, plus a snapshot of **open** CLs (step 3).

1. **Listing over REST.** The query is
   `project:chromium/src branch:main status:{merged|abandoned}` with
   `o=DETAILED_ACCOUNTS&o=DETAILED_LABELS&n=500`.
   - Each UTC day is split into four 6-hour windows. A window that overflows
     is bisected, never paged with `S=`.
   - Merged CLs use `mergedafter:`/`mergedbefore:`.
   - Gerrit has no operator for abandon time, so abandoned CLs use
     `after:`/`before:`, which filter on last update. An abandoned CL's last
     update is almost always the abandon itself.
   - W44 took 56 requests: 5,823 merged and 1,825 abandoned CLs.
2. **Comments over git (NoteDb).**
   - Only human-owned CLs with `total_comment_count > 0` are fetched: 3,409
     CLs in W44.
   - Their `refs/changes/NN/N/meta` refs are fetched from
     `https://chromium.googlesource.com/chromium/src`, 200 explicit refspecs
     per `git fetch` (never a glob), into `data/private/notedb/chromium_src.git`.
   - Comments are read from the notes JSON and converted to the REST
     `/comments` shape, so the rest of the pipeline is identical.
   - W44 took 18 fetches and about 23 minutes of fetch time (0.46 s per CL).
   - **Validated:** NoteDb produced identical review rows to REST `/comments`
     on all 856 CLs where both were available.
   - `--via rest` still exists: one REST `/comments` request per CL.
   - **Refetch rule:** a ref is fetched if it is missing locally, or if its
     local tip is older than the listing's `updated`. The tip's commit time
     equalled `updated` on all 3,429 W44 CLs. A refetch is incremental: only
     the new NoteDb commits come down. Re-running a cached week never
     refetches, because its cached listing matches the tip.
3. **Open CLs (`extract-open`).** The weekly listings only find CLs that have
   closed, so a comment would otherwise stay invisible until its CL lands or
   is abandoned. One snapshot lists:
   - `status:open` CLs on main whose last update is at or after the start of
     the oldest fetched week (2025-11-03), using `after:`/`before:` windows of
     7 days, bisected on overflow;
   - merged and abandoned CLs closed at or after the end of the newest fetched
     week, which no weekly listing covers yet (1-day windows).
   Windows are listed oldest first, then a catch-up window from the snapshot's
   start to now. A CL updated during the listing only moves later, so the
   catch-up still sees it. The CL index goes into `open_changes`, keyed by
   the snapshot's `listed_at`. NoteDb refs are fetched with the same batches,
   duty cycle and refetch rule. An unfinished snapshot is resumed; to refresh,
   run it again for a new snapshot. Derive uses each CL's newest listing,
   whether weekly or from a snapshot.
4. **Account lookups.** Account IDs seen in NoteDb comments but absent from the
   listing are resolved with `/accounts/{id}`. W44 needed 4 lookups.
5. **Politeness.**
   - Strictly serial.
   - REST: at least 1.0 s between requests, gzip, exponential backoff on
     429/5xx that honours `Retry-After`.
   - Git: one connection, at least 5 s between fetches. `backfill` and
     `extract-open` default to duty cycle 1.0 (fetches back to back, one at a
     time; approved 2026-11-04). Until then the default was
     duty cycle 0.5: after each fetch it idles as long as the fetch took.
   - Every response is cached, so a re-run fetches nothing twice.
   - One 429 was seen at about 0.78 REST requests/s (during the abandoned
     all-REST approach); NoteDb saw none.
6. **Identification.** Every request carries
   `User-Agent: cosh/0.1 (...; contact: rick@rbyers.net)` and
   `From: rick@rbyers.net`.
   - Git sends the same through `GIT_USER_AGENT` (which also sets the protocol
     `agent=` field) and `http.extraHeader`.
   - All of this lives in `cosh/contact.py`; override with `COSH_CONTACT`.

## Metric definitions (metric_version 3)

Versions: 1 counted everything in the week the CL closed and left post-merge
comments out of the headline. 2 put post-merge comments in the headline,
together with the vote floor (below). 3, the current version, counts review
activity in the week it happened and keeps 2's rules.

Review activity counts in the ISO week (UTC) in which it happened. Under
metric_versions 1–2, everything counted in the week the CL closed. That week
held only 63% of the comments counted for W44 CLs: 22% were written in W43,
and about 4% eight or more weeks earlier. It also produced spikes for small
orgs: two long-running CLs made up 223 of the 258 Microsoft comments that
were counted in W44 but written earlier.

- **Tables** (`cosh/store.py`, `DERIVED_SCHEMA`):
  - `comments`: one row per published comment by a non-owner on a
    human-owned CL, with its `written_at` and `iso_week`.
  - `votes`: one row per standing non-zero Code-Review vote by a non-owner,
    with `voted_at` and `iso_week`.
  - `changes`: one row per CL, from its newest listing. `close_week` is NULL
    for open CLs.
  - `cl_reviewers` (a view): every (CL, account) with a comment or vote on a
    closed CL. It is used only for reviewed CLs.
- **Week of a comment:** the week of its `writtenOn` time in NoteDb (REST:
  `updated`).
- **Week of a vote:** the voter's own latest non-zero `Label: Code-Review=…`
  line in the CL's NoteDb history.
  - The listing's vote `date` can't be used: Gerrit restamps it at submit
    (11,003 of 11,036 merged-CL votes in W43–W44 carried the submit time).
  - A label line that names another user (`… Gerrit User N <…>`) inside
    someone else's update records a copied vote, not a new one, and is
    skipped.
  - CLs without comments have no NoteDb fetch, so their votes fall back to
    the listing date, which is usually the submit time.
- **Reviewed CLs** stay per CL: they count in the week the CL closed (merged,
  or abandoned at its last update), with the org as of the close. Open CLs
  don't count yet.
- **Reviewers** in a week: non-bot accounts credited with anything that
  week: a comment written, a vote cast, or a reviewed CL that closed that
  week. This is the same set as the rows of `reviewer_weekly.json`, so the
  web UI's distinct-reviewer counts match `org_weekly`.
- **Weeks reported:** only fully fetched weeks (`meta.fetched_weeks`).
  Activity before the oldest week, or in the current partial week, is
  stored but not summarized. Recent weeks are complete only as of the last
  open-CL snapshot (`meta.open_snapshot_at` in `org_weekly.json`); comments
  written after it appear on the next snapshot or once their CL closes.
- **Abandoned CLs count.** Review that points out flaws so that a CL never
  lands is valuable work.
- **Bot commits.** A CL is bot-owned if its owner has Gerrit's
  `SERVICE_USER` tag or matches a regex in `config/bots.txt`. W44 had 2,211.
  - Each gets one `changes` row with `is_bot_owned=1`.
  - It gets no comment or vote rows and no comment fetch.
  - It is counted in `summaries/weekly_totals.csv` (by close week), so
    bot-only stretches don't look like gaps.
- Being listed only as a reviewer or CC creates no row. Bot reviewers get
  rows but are flagged, and summaries drop them.
- **Accounts without an email are bots.** An account that still has no email
  after derive is assumed to be a bot or AI agent and gets `is_bot=1`. Examples
  are AI agents such as "Jetski (…)", deleted accounts, and accounts that
  `/accounts/{id}` returns 404 for.
  - Their rows stay, but summaries drop them.
  - `accounts.name` falls back to Gerrit's `display_name` when an account has
    no full name, then to "Deleted User" (as Gerrit's UI shows it) for an
    account the listing marks `deleted`.
- **`comments` (the headline metric)** counts human comments written in the
  week, including those written after the CL closed. It excludes
  `ai_comments`: comments with the `is_ai` flag or an `autogenerated:*` tag.
  - `post_merge_comments`: the subset written after `closed_at`, however
    late (no window), counted in the week they were written. They count
    because post-merge review that leads to a follow-up CL is real value.
    Summaries also report them per org and week. (58% arrive within a day of
    the close, 89% within 14 days.)
  - metric_version 1 excluded them from the headline.
  - Spam among them (names, pasted prompts) is an open issue; see
    `plan.md`, Open questions.
- **Vote floor (applied in `summarize`, not stored):** a Code-Review vote on
  a CL where the voter wrote no counted (non-AI) comment, typically a bare
  +1, counts as **one** comment, in the week of the vote. Without this, a
  review that needed no changes would not appear in the comments chart at
  all.
  - A vote never adds to a review that has comments, so "LGTM" plus +1 is 1,
    not 2, even when the comment and the vote fall in different weeks.
  - Summaries report the number per org and week as `vote_only_reviews`.
  - Under metric_version 2 (W44): 2,792 of 6,526 review rows (43%) were
    vote-only. The floor raised the week's comments by 27% and moved
    google.com from 95.9% to 96.4%.
- **`votes` rows** hold the reviewer's Code-Review vote *as it stands in the
  CL's newest listing* (`labels.Code-Review.all`), timed from NoteDb. They
  are used for reviewer credit, reviewed CLs and the vote floor.
  - In principle a vote cleared by a later patchset is lost. In practice,
    Chromium's copy condition carries Code-Review votes across trivial
    rebases, no-code changes and committer uploads that leave files
    unchanged, so this almost never happens.
  - **Checked on W44 (2026-11-03):** the NoteDb vote history of all 3,429
    human-owned CLs with comments has 4,496 human non-owner Code-Review
    voters. Every one has a review row and a final vote, so none are missed.
  - The 2,008 CLs without comments have no NoteDb history. Their listing
    `reviewers.REVIEWER` holds 277 human accounts without a row, mostly on
    abandoned CLs. On CLs with history, 0 of 402 such accounts had ever
    voted, so these are reviewers who were added and never acted.
  - All 30 merged human-owned CLs with no human review row were approved by
    Rubber Stamper (`Bot-Commit+1`): clean reverts and relands, gardener
    suppressions and translation dumps. The translation-dump account is now
    in `config/bots.txt`.
- **`review_chars`:** characters in those comments after removing quoted `>`
  lines.
- **Validation:** for CLs that closed in W44, the `comments` and `votes`
  tables reproduce the CL-keyed tables exactly: 10,426 pre-close comments,
  1,910,448 chars, 1,142 AI comments, 78 post-merge comments and 6,526
  (CL, reviewer) pairs.
- **`is_owner`:** NULL for now (deferred). The code-owners API answers against
  the *current* OWNERS files, so it is wrong for history. Plan: evaluate the
  OWNERS files at the merge commit's parent in a local checkout.

### AI comments: what we can and can't tell

- **What's detected:** only self-declared AI use, i.e. the comment carries
  `is_ai: true` or a tag starting with `autogenerated:`. Nothing looks at the
  comment text.
- **In W44:**
  - 9.8% of reviewer-side comments: 1,132 AI comments against 10,424 human
    ones.
  - 94% of flagged comments have no tag. A few tagged ones are not flagged,
    such as `blink_ai_review` and `last-mile`.
- **Missed:** pasted LLM output and tools that don't set the flag.
- **Overcounted:** heavily edited AI drafts, and some non-AI automation tags.
- **Use:** treat `ai_comments` as a lower bound, tracked separately from the
  headline.

## Org attribution (`cosh/orgs.py`)

The org is a domain name. It is evaluated as of the day of the comment or
vote, or, for reviewed CLs, as of the CL's `closed_at`:

1. **Affiliations file.** If the email is in `config/affiliations.json5`, use
   its most recent affiliation whose `start` is on or before that date.
   - The file is a verbatim copy of Chromium's
     `third_party/blink/tools/commit_stats/affiliations.json5`.
   - Dates before a person's earliest `start` fall through to rule 2 or 3.
   - The values `Individual` and `Undisclosed` are kept as-is.
2. **Other `@chromium.org` accounts** are attributed to `google.com`.
3. **Everyone else** is attributed to the domain of their email address.

`org_weekly` reports every org, however few reviewers it has; only
`gmail.com` is folded into `Other`. `summaries/reviewer_weekly.json` holds
every reviewer's comments, reviewed CLs and review characters per week, with
the same scope and weeks as `org_weekly`: one row per (week, account, org),
with orgs resolved per comment or vote (or per CL, for reviewed CLs) as in
`org_weekly`, but before the `gmail.com` fold. Summed
per (week, folded org), the rows reproduce `org_weekly`'s `reviewers`,
`comments` and `review_chars` exactly, so the web UI can count distinct
reviewers and rank reviewers over any range of weeks. (An org's
`reviewed_cls` can't be rebuilt from it, since two reviewers can share a CL;
the UI sums that from `org_weekly`, which is exact because each CL closes in
one week.) The format is compact: names once per account, orgs once, and
rows of `[account_id, org index, comments, cls, chars]`.

## W44 results (first look, metric_version 1)

| org | share of comments | reviewed CLs | reviewers |
|---|---|---|---|
| google.com | 95.9% | 4,446 | 851 |
| microsoft.com | 3.0% | 55 | 33 |
| Other | 0.45% | 43 | 13 |
| igalia.com | 0.37% | 27 | 11 |
| gmail.com | 0.22% | 17 | 13 |

- 8 of 6,526 review rows have no email. Two of those accounts return 404 from
  `/accounts`.
- The listing cache is about 9.7 MB per week, compressed. Most of it is
  `avatars` and label metadata.

## Known gaps

- Comments on bot-owned CLs are never fetched. Reviewers of autorolls appear
  only in `weekly_totals`, not in review metrics.
- An abandoned CL that is touched again after abandonment can appear in two
  weekly listings. Derive uses the newer listing, and comments are keyed by
  their own id and time, so nothing is double counted. Only that CL's
  reviewed-CLs week moves.
- Vote times on CLs without comments come from the listing, which restamps
  them at submit (see "Week of a vote").
- Votes that were changed or removed count once, at the voter's latest own
  non-zero vote. Earlier votes on the same CL aren't counted as separate
  activity.
- Comments on CLs that are still open and were last updated before the
  snapshot's `since` (2025-11-03) are out of scope. They predate the year.
- Extraction resolves only account IDs that are absent from the listing. IDs
  present in the listing without an email are not looked up (the remaining
  8 rows).
