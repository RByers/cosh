# Extraction v1: what is implemented

Status (2026-11-03): one week, **2026-W44** (Mon 2026-10-26 to Sun 2026-11-01
UTC), has been extracted and validated. **Do not fetch more weeks** until the
web UI is built and the user has signed off on the design (see
`docs/plan.md`).

This follows `gerrit-api-research.md` and `storage-design.md`. Below are the
decisions made while implementing it; where they differ from those docs, this
file wins.

## Commands

```
python3 -m cosh extract --week 2026-W44     # network; cached and resumable (NoteDb by default)
python3 -m cosh derive                      # offline: raw cache -> data/private/cosh.sqlite
python3 -m cosh summarize [--metric comments|cls|chars]   # offline: -> summaries/
python3 -m cosh radar [--offline]           # Cloudflare Radar; needs `source secrets.sh`
python3 -m cosh backfill --weeks 52 [--go]  # plan only unless --go (DO NOT --go yet)
python3 -m cosh update-affiliations         # refresh config/affiliations.json5
python3 -m cosh status
python3 -m unittest tests.test_derive tests.test_radar
```

## Pipeline and data flow

```
Gerrit REST listing ─► data/private/raw.sqlite ─┐
NoteDb `git fetch`  ─► data/private/notedb/*.git ┼─ derive ─► data/private/cosh.sqlite ─ summarize ─► summaries/
Cloudflare Radar    ─► data/public/radar/raw/ ──── radar ──► data/public/radar_browser_share.csv
```

- `data/private/` (gitignored for size; see `storage-design.md` §4) holds the
  raw stores and the derived DB.
  - `raw.sqlite` and `notedb/` keep **everything downloaded, losslessly and
    permanently**, even data no metric uses yet. This is the intended design;
    see `storage-design.md` §3.8, which also covers what NoteDb contains and
    the size per year.
  - `cosh.sqlite` is derived, holds only counts and lengths, and can be rebuilt.
- `data/public/`, `summaries/`, `config/`, code and docs are committed.

## What we fetch from Gerrit, and how gently

Scope: `chromium/src`, **branch `main` only**, **merged and abandoned** CLs.

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
3. **Account lookups.** Account IDs seen in NoteDb comments but absent from the
   listing are resolved with `/accounts/{id}`. W44 needed 4 lookups.
4. **Politeness.**
   - Strictly serial.
   - REST: at least 1.0 s between requests, gzip, exponential backoff on
     429/5xx that honours `Retry-After`.
   - Git: one connection, at least 5 s between fetches. `backfill` defaults to
     duty cycle 0.5: after each fetch it idles as long as the fetch took.
   - Every response is cached, so a re-run fetches nothing twice.
   - One 429 was seen at about 0.78 REST requests/s (during the abandoned
     all-REST approach); NoteDb saw none.
5. **Identification.** Every request carries
   `User-Agent: cosh/0.1 (...; contact: rick@rbyers.net)` and
   `From: rick@rbyers.net`.
   - Git sends the same through `GIT_USER_AGENT` (which also sets the protocol
     `agent=` field) and `http.extraHeader`.
   - All of this lives in `cosh/contact.py`; override with `COSH_CONTACT`.

## Metric definitions (metric_version 1)

- **CL in week:** the ISO week (UTC) of `closed_at`. That is the submit time
  for merged CLs and the last update for abandoned ones.
- **Abandoned CLs count.** Review that points out flaws so that a CL never
  lands is valuable work.
- **Bot commits.** A CL is bot-owned if its owner has Gerrit's
  `SERVICE_USER` tag or matches a regex in `config/bots.txt`. W44 had 2,211.
  - Each gets one `changes` row with `is_bot_owned=1`.
  - It gets no review rows and no comment fetch.
  - It is counted in `summaries/weekly_totals.csv`, so bot-only stretches
    don't look like gaps.
- **Review row:** one per (CL, account), for any non-owner account that did
  either of these:
  - cast a non-zero Code-Review vote (`voted_cr`, from the listing);
  - wrote at least one published comment, inline or `/PATCHSET_LEVEL`.
  Being listed only as a reviewer or CC creates no row. Bot reviewers get
  rows but are flagged, and summaries drop them.
- **Accounts without an email are bots.** An account still has no email
  after derive (e.g. AI agents such as "Jetski (…)", deleted accounts, or
  accounts `/accounts/{id}` returns 404 for) is assumed to be a bot or AI agent
  and gets `is_bot=1`. Their review rows stay in `reviews`, but summaries drop
  them. `accounts.name` falls back to Gerrit's `display_name` when an account
  has no full name, then to "Deleted User" (as Gerrit's UI shows it) for an
  account the listing marks `deleted`.
- **`review_comments` (the headline metric)** counts human comments written
  up to `closed_at`. It excludes:
  - `ai_comments`: comments with the `is_ai` flag or an `autogenerated:*`
    tag;
  - `post_merge_comments`: comments written after `closed_at`. They are
    still valuable review, so summaries report them per org and week as
    `post_merge_comments`, separate from the headline.
- **`review_chars`:** characters in those comments after removing quoted `>`
  lines.
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

The org is a domain name, evaluated as of the CL's `closed_at`:

1. **Affiliations file.** If the email is in `config/affiliations.json5`, use
   its most recent affiliation whose `start` is on or before that date.
   - The file is a verbatim copy of Chromium's
     `third_party/blink/tools/commit_stats/affiliations.json5`.
   - Dates before a person's earliest `start` fall through to rule 2 or 3.
   - The values `Individual` and `Undisclosed` are kept as-is.
2. **Other `@chromium.org` accounts** are attributed to `google.com`.
3. **Everyone else** is attributed to the domain of their email address.

`org_weekly` reports every org, however few reviewers it has; only
`gmail.com` is folded into `Other`. `summaries/reviewer_weekly.json` holds each
week's top 50 reviewers by comments, by reviewed CLs and by review
characters, with the same scope as `org_weekly`. Each reviewer's org is the
one on most of their reviewed CLs that week.

## W44 results (first look)

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
- An abandoned CL that is touched again after abandonment moves to a later
  week. Rows are keyed by CL, so this never duplicates data.
- Extraction resolves only account IDs that are absent from the listing. IDs
  present in the listing without an email are not looked up (the remaining
  8 rows).
