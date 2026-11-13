# cosh: storage design

> **Current state (2026-11-04).** This is the original proposal, and it is
> mostly as built. Three things changed:
> - The **headline metric** is addressed review comments (metric_version
>   7), not the measures weighed in §3.6.
> - There is a **third local store**, `data/private/labels.sqlite`. It holds
>   the addressed-comment labels from `cosh classify`. Like `raw.sqlite`, it
>   is never deleted, because remaking it costs Claude Max usage.
>   `comment-classifier.md`, "Design", has its schema, sizes and pipeline.
> - **`extraction-v1.md` is the authority** on what is implemented.

Status: proposal, 2026-11-03. Scope: how extracted Gerrit review data is stored,
kept idempotent and resumable, and reduced to the small summaries the web front
end reads. Gerrit API details are in `gerrit-api-research.md`. This document
only touches the API where it affects storage.

## TL;DR

- **Use two SQLite files (stdlib `sqlite3`) plus committed CSV/JSON summaries.**
  - `data/private/raw.sqlite`: an append-only cache of every Gerrit response,
    stored as zlib-compressed JSON blobs keyed by request. It is the source of
    truth, so metrics can be re-derived without touching Gerrit again.
  - `data/private/notedb/*.git`: bare repos holding the fetched NoteDb meta
    refs, with their full history.
  - **Whatever we download is retained, losslessly and permanently** (§3.8),
    so it never has to be fetched twice. Reduction to counts and lengths
    happens only in derived data.
  - `data/private/derived.sqlite` (§3.3):
    derived tables (`changes`, `comments`, `accounts`, `meta`, and since
    metric_version 7 `threads`; `committers`) that can be rebuilt from `raw.sqlite` and
    NoteDb at any time.
  - `data/private/labels.sqlite` (added with metric_version 7): the Haiku
    labels behind addressed comments, keyed by thread and input hash. They
    can't be rebuilt for free, so they are never deleted.
  - `summaries/*.csv` + `summaries/*.json`: per-org per-week and per-month
    aggregates, under about 1 MB in total. **These are the only data committed to git.**
- Do not use flat CSV as the store, because it can't upsert, so idempotent
  re-runs need full rewrites. Do not use Parquet/DuckDB either: it isn't in
  stdlib, and the data is too small to need it (about 3M fact rows). If ad-hoc
  analytics ever want it, add a Parquet export later.
- The volume is about **4x the initial assumption**. chromium/src merges
  **~6,000 CLs/week**, not 1,000–1,500 (see §1), so a 5-year backfill is about 1.5M CLs.
  Request count, not storage, is the constraint. Plan for a resumable backfill that runs
  for about 1–2 weeks of wall-clock time at 1 request/second.

## 1. Volume and size estimates

### 1.1 Measured volume (5 anonymous requests, 2 s apart, 2026-11-03)

| Query | Result |
|---|---|
| `project:chromium/src status:merged after:2026-10-19 before:2026-10-26`, 4 pages × 500 | 2,000 CLs and `_more_changes: true` still set. Fri 2026-10-23 alone had **1,155** merged CLs. Sat had 276, Sun 174. |
| `project:chromium/src mergedafter:2026-10-20 mergedbefore:2026-10-21`, page `S=1000` | 135 more, so **1,135** CLs merged on Tue 2026-10-20 |

Composition of the 2,000-CL sample:
- 85% `main`, 15% release branches (`refs/branch-heads/*`).
- About 30% are autoroller-style subjects (`Roll ...`, `Update ...`).
- 53% have `total_comment_count = 0`.
- The top 3 owners (roller bots) own 29% of CLs.

**Gotcha:** `after:`/`before:` filter on `updated`, not on merge time. The
sample contained CLs submitted as far back as February. Always select weeks with
`mergedafter:`/`mergedbefore:` and bucket by the `submitted` timestamp.

Derived volume:
- About 1,150 per weekday × 5 + about 450 per weekend gives **~6,000 merged CLs/week**.
  About 3,500 of those are human-authored CLs on `main`.
- **5 years is about 1.3–1.6M CLs.** Activity was likely somewhat lower in 2021–22, so
  1.5M is used as the planning number.
- Reviewer rows: human CLs average about 1.5–3 reviewers, and bot CLs about 0–1
  (rubber-stamp or sheriff). Planning figure: **~2 rows/CL, so about 3M `reviews`
  rows** (range 2–4.5M). If rows include zero-comment approvers (recommended, see
  §3.3), the count lands near the top of the range.

### 1.2 Sizes (5 years, planning figures)

| Artifact | Rows | Uncompressed | Compressed |
|---|---|---|---|
| `reviews` as CSV (change#, email, counts, owner bit, ~55 B/row) | 3M | ~165 MB | ~30 MB gzip (emails repeat heavily) |
| `reviews` in SQLite (integer account_id, `WITHOUT ROWID`, ~30 B/row + page overhead) | 3M | ~100 MB (~200 MB if keyed by email text) | — |
| `reviews` as Parquet (dictionary-encoded emails, zstd) | 3M | — | ~15–25 MB |
| `changes` as CSV/SQLite (~110 B without subject, ~170 B with subject) | 1.5M | 160–250 MB | ~50–70 MB gzip |
| `accounts` | ~30–50k | ~3 MB | <1 MB |
| **Derived DB total** (incl. indexes) | | **~350–500 MB** | ~120 MB gzip |
| **`raw.sqlite` cache** (change detail with messages, labels, and detailed accounts at about 20–40 KB JSON, plus `/comments` for the ~47% of CLs that have comments, compressed about 6:1 with zlib) | ~2.3M blobs | ~45–60 GB as JSON | **~6–10 GB on disk** |
| Front-end summaries (see §3.7) | ~10k | ~1 MB | ~150 KB gzip |

One week (the first milestone) is about 6k CLs, 12k reviews rows, about 2 MB
derived data, and about 40 MB of raw cache.

Request budget. These figures drive the resumability design:
- Fetching per CL takes about 1 detail request per CL plus 1 `/comments` request per
  commented CL. That is about 9,000 requests/week, or about 2.5 h/week at 1 rps, and
  **about 27 days for 5 years**.
- Pulling messages, labels, and detailed accounts in the *list* query instead
  (`o=MESSAGES&o=DETAILED_LABELS&o=DETAILED_ACCOUNTS`, n≈100) leaves only the
  `/comments` calls. That is about 3,000 requests/week, or **about 9–12 days for 5
  years**.

Either way, the backfill gets interrupted many times, so progress must be durable at
the level of individual CLs, not just weeks.

## 2. Format decision

| Need | Flat CSV | SQLite (stdlib) | Parquet / DuckDB |
|---|---|---|---|
| Idempotent re-run of a week | Rewrite whole file or partition | `DELETE … WHERE change` + `INSERT` in one transaction, or UPSERT | Rewrite the partition file |
| Resumable mid-week backfill | Needs a side progress file and has partial-line risk | Atomic per-CL commits, and the progress table lives in the same DB | Not incremental, so partial writes are buffered in memory |
| Joins (CL metadata ↔ reviews ↔ org map) | Done in Python by hand | SQL | SQL (DuckDB) |
| Raw response cache | ~3M small files = inode/backup pain | Compressed BLOBs in one file | n/a |
| Dependencies | none | **none (stdlib)** | pyarrow/duckdb |
| Git-friendliness | Good for small files | Binary, not committed | Binary |
| Scale needed (3M rows) | ok | trivially ok | overkill |

**Decision:**
- Use SQLite for both raw and derived storage, and CSV/JSON for published
  aggregates.
- Keep raw and derived storage in **separate files**:
  - The 6–10 GB raw cache is precious, expensive to rebuild, and backed up rarely.
  - `derived.sqlite` is disposable and gets dropped and rebuilt whenever the metric
    definitions change.
  - With separate files, `VACUUM` and schema migrations on the derived DB never touch
    the cache.

Raw-cache alternatives considered:
- *gzip file per CL under `data/raw/…`*: about 3M files once comments are included.
  That is slow to back up and `ls`, and needs temp-file plus rename to be atomic.
  Rejected.
- *one `.jsonl.gz` per week*: compact, but it can't be appended mid-week safely, and
  re-fetching one CL means rewriting the whole week. Rejected as primary storage.
  It is still fine as an **export format** for archiving, e.g.
  `data/private/archive/2026-W43.jsonl.gz`, generated from `raw.sqlite` once a
  week is closed.

Use SQLite settings `PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;` and
`STRICT` tables (SQLite ≥ 3.37; the box has 3.46.1).

## 3. Schema

### 3.1 Layout on disk

Superseded: the current layout is `config/dataflow.json`, which lists every
store with its path, tier and size (drawn at `web/dataflow.html`;
`docs/data-architecture.md` explains it). This section's original sketch is
in git history.

### 3.2 `raw.sqlite`: response cache

```sql
CREATE TABLE responses (
  host        TEXT    NOT NULL,          -- 'chromium-review.googlesource.com'
  kind        TEXT    NOT NULL,          -- 'list_page' | 'change_detail' | 'comments' | 'owners' ...
  key         TEXT    NOT NULL,          -- change number as text, or canonical query+offset for list pages
  url         TEXT    NOT NULL,          -- full request URL (options included)
  fetched_at  TEXT    NOT NULL,          -- ISO-8601 UTC
  http_status INTEGER NOT NULL,
  body_zlib   BLOB    NOT NULL,          -- zlib.compress(body without ")]}'" prefix)
  body_sha256 TEXT    NOT NULL,
  PRIMARY KEY (host, kind, key)
) STRICT, WITHOUT ROWID;
```

How the cache behaves:
- The cache keeps the latest copy of each response. Write with
  `INSERT … ON CONFLICT DO UPDATE`.
- If history ever matters, add `fetched_at` to the PK. It isn't needed now.
- A CL counts as fetched once its `change_detail` row exists, plus its `comments` row
  if it has comments.
- The fetcher checks this table before making any request. That alone makes a
  restarted backfill skip finished work.
- To re-fetch on purpose (for example, to pick up post-merge comments), pass a
  `--refresh-older-than` flag that compares against `fetched_at`.

### 3.3 `derived.sqlite`: derived tables

The schema lives in `cosh/store.py` (`DERIVED_SCHEMA`), and the metric
definitions are in `extraction-v1.md`. Since metric_version 5 (2026-11-04)
it holds:

- `changes`: one row per CL, from its newest listing (open CLs included),
  with the CL's anchor file for placing patchset-level comments
  (`cosh/paths.py`).
- `comments`: one row per published comment by a non-owner on a human-owned
  CL, with the ISO week it was written and its file path, but not its text.
- `accounts`: id, email, name and a bot flag.
- `committers`: whether each account may vote Code-Review (only committers
  may), as of the newest listing that shows it, with that listing's fetch
  time (`docs/committers.md`).
- `meta`: `metric_version`, `derived_at`, the fetched weeks and the open-CL
  snapshot time.

Votes aren't derived (the raw stores still hold them). `open_derived` refuses
a file from before metric_version 5. The first design (`cosh.sqlite`: one
`reviews` row per CL and reviewer, counted in the week the CL closed;
metric_versions 1-2) and metric_versions 3-4 (`comments` plus `votes`) are
recorded in the decisions log in `plan.md`; their files were deleted on
2026-11-04.

Design notes that still hold:
- **Key on `account_id`, not email.** Account ids are stable and small, and
  emails live in `accounts`.
- **The CL owner's comments are not review activity** and get no `comments`
  rows. Bot accounts are kept but flagged, and are filtered at aggregation
  time.
- **Idempotency:** for each CL, `derive` upserts `changes`,
  then `DELETE FROM comments WHERE host=? AND change_number=?`, then inserts
  its comments, one transaction per listing window. Re-running any week, or rebuilding everything, produces
  identical rows and never duplicates.
- **Multiple hosts and repos** are covered by `host` + `project`, so adding
  e.g. a v8 host needs no migration.

### 3.4 Progress and resumability (in `raw.sqlite`)

```sql
CREATE TABLE extract_runs (
  run_id       INTEGER PRIMARY KEY,
  started_at   TEXT NOT NULL,
  finished_at  TEXT,
  command      TEXT NOT NULL,          -- argv, for reproducibility
  status       TEXT NOT NULL           -- 'running' | 'ok' | 'failed' | 'interrupted'
) STRICT;

CREATE TABLE week_progress (
  host          TEXT NOT NULL,
  project       TEXT NOT NULL,
  iso_week      TEXT NOT NULL,          -- '2026-W43'
  listed_at     TEXT,                   -- list query fully paged (all CL numbers known)
  cl_count      INTEGER,                -- from the list
  fetched_count INTEGER NOT NULL DEFAULT 0,
  derived_at    TEXT,                   -- reviews rebuilt for this week
  last_run_id   INTEGER REFERENCES extract_runs(run_id),
  PRIMARY KEY (host, project, iso_week)
) STRICT;

CREATE TABLE week_changes (               -- the CL list per week, from the list query
  host TEXT NOT NULL, project TEXT NOT NULL, iso_week TEXT NOT NULL,
  change_number INTEGER NOT NULL,
  PRIMARY KEY (host, project, iso_week, change_number)
) STRICT, WITHOUT ROWID;
```

How a backfill resumes:
- The backfill loop walks weeks from newest to oldest, which gives useful data early.
- For each week it does three steps:
  1. Page the list query, unless `listed_at` is already set.
  2. Fetch each listed CL that `raw.sqlite` doesn't have yet.
  3. Derive the week.
- Killing the process at any point loses at most one in-flight request.
- These tables live in `raw.sqlite`, so the derived DB is freely deletable:
  `rm data/private/derived.sqlite && python3 -m cosh derive` is always safe.

### 3.5 Org mapping

> **Superseded.** Org attribution now uses Chromium's `affiliations.json5`,
> with other `@chromium.org` accounts mapped to google.com and everyone else
> mapped to their email domain. See `extraction-v1.md` § Org attribution.
> The text below is kept for history.

`config/org_domains.csv` (committed, contains no personal data):
```
domain,org
google.com,Google
chromium.org,            # empty org = "resolve per account; fall back to 'Unaffiliated/chromium.org'"
microsoft.com,Microsoft
opera.com,Opera
samsung.com,Samsung
igalia.com,Igalia
intel.com,Intel
gserviceaccount.com,BOT
```
The table allows suffix matching (`*.google.com`).

`data/private/account_orgs.csv` (local only, holds individual employer
attribution):
```
email,org,valid_from,valid_to,source
someone@chromium.org,Google,,,"manual: profile/commit history"
```

Resolution order:
1. The per-account override, valid at `submitted_at`.
2. The domain map.
3. Otherwise `Other`.

`valid_from`/`valid_to` handle people who change employer but keep their
chromium.org address. `summarize` reads both files (`cosh/orgs.py`). Nothing
from them is stored in `derived.sqlite`, so remapping only requires re-running
`summarize`.

`config/org_browsers.csv` maps orgs to Radar browsers:

| org | browser |
|---|---|
| Google | Chrome |
| Microsoft | Edge |
| Opera | Opera |
| Samsung | Samsung Internet |
| Yandex | Yandex Browser |

Orgs without a browser, such as Igalia or Intel, get an activity share but no ratio.
Brave has no row either: Radar counts Brave as Chrome, so its usage is unknown
(`radar-research.md` §6).

`data/public/radar_browser_share.csv`: `month,browser,share_of_chromium_based`.
Normalize Radar's all-browser shares to Chromium-based only at import time, and
record the Radar query or URL in `meta.json`.

### 3.6 Aggregation

```
org_share(org, period)   = review_chars(org, period) / review_chars(all non-bot, period)
browser_share(org, month) = Radar share of org's browser(s) among Chromium-based browsers
ratio                     = org_share / browser_share     # e.g. 0.90 / 0.70 = 1.29 (9/7)
```

The pipeline computes several activity measures side by side, because they
disagree in interesting ways:
- comment count
- review chars
- **reviewed CLs**: `COUNT(DISTINCT change_number)` per org, or per account
  before rolling up
- distinct active reviewers

"Reviewed CLs" doesn't need its own table. It falls out of `reviews` directly. A
CL counts once per org even if three Googlers reviewed it, if computed as
`COUNT(DISTINCT change_number)` grouped by org. It is the measure least sensitive
to verbose commenters, and probably the best headline candidate.

Weeks are ISO weeks of `submitted_at` in UTC. Radar data is monthly or weekly, so
weekly ratios use the share for the containing month (or the Radar week, if
available).

### 3.7 Front-end summaries (committed)

`summaries/org_weekly.json` has one row per (week, org) (a CSV copy,
`org_weekly.csv`, was written until 2026-11-12; no page read it):
```
iso_week,org,reviewed_cls,reviewers,comments,review_chars,share_cls,share_chars,browser_share,ratio_cls,ratio_chars
2026-W43,Google,2950,812,9100,1480000,0.88,0.90,0.70,1.26,1.29
```
- Orgs: the top ~15. Everything else rolls into `Other`.
- Size: 260 weeks × ~16 orgs ≈ 4,200 rows × ~90 B ≈ **400 KB** CSV, about 60 KB gzip.

`summaries/org_monthly.csv` uses the same columns per month: 60 × 16 ≈ 1,000 rows,
**~90 KB**.

The `.json` versions use a columnar layout (`{"weeks":[…],"orgs":{"Google":{"share_chars":[…]}}}`)
and are about the same size, under 50 KB gzip each. They are small enough to load
in one fetch with no backend.

`summaries/meta.json` holds:
- generation time
- covered range
- metric definitions version
- bot filter
- Radar source
- the minimum-group-size threshold

### 3.8 Retention: keep whatever we download

**This is the user's intended design.** Anything we put server load on to
fetch from Gerrit is kept, in a form that can be re-read later, even when no
current metric uses it. Then we never have to download it again if we decide
we want it.

This is **not** a goal to download everything. Fetching less is welcome
whenever it still gets the data we need: a narrower query, or a leaner kind of
fetch. The rule only says that what does come over the wire is not thrown
away. (User's clarification, 2026-11-04.)

Reasons for keeping it:
- New analyses, such as resolution rates, comment threads, vote timing or
  attention-set churn, become possible without fetching again.
- We can see what the fetched data contains and decide whether the fetching
  itself should change.
- Re-fetching costs Gerrit and googlesource server load, which we want to avoid.

What this means in practice:

| Raw store | Contents kept |
|---|---|
| `raw.sqlite` `responses` | The full response body (zlib), URL, HTTP status, fetch time and sha256 for every listing, REST `/comments` and `/accounts` response, including 404s |
| `notedb/<project>.git` | Every object of each fetched `refs/changes/NN/N/meta` ref, i.e. the change's whole NoteDb history, not only the tip comments |
| `data/public/radar/raw/` | Raw Radar JSON |

- Code only ever *reads* the raw stores to reduce them. `read_comments()` and
  `derive` drop fields (ranges, `submitRequirementResults`, change messages,
  votes) in memory. `parentUuid` and `unresolved` have been kept since
  metric_version 7, for the review threads. `derived.sqlite` holds one row
  per comment, without its text. Nothing ever strips or rewrites the
  raw stores.
- Never delete `raw.sqlite` or `notedb/`. Never run `gc --prune=now` or `prune`
  in a NoteDb repo. Auto-gc and maintenance are disabled there. `repack -a -d`
  is safe, because every object is reachable from a `refs/meta/*` ref.
- Known small gaps to close: a re-fetch overwrites the previous `responses` row
  and the local meta ref, so there's no version history. Response headers, the
  bodies of retried 429/5xx responses and the list of missing (deleted) meta
  refs are not stored. Invalid UTF-8 in a body is replaced on decode.

#### What the NoteDb data contains (measured on W44, 2026-11-03)

W44 has 3,429 meta refs, which is every human-owned CL with comments.

There is **no source code and there are no diffs**:
- A meta ref's commits are NoteDb metadata commits. They name patch-set
  commits by SHA in `Commit:` footers but don't link to them as parents.
- A fetch therefore downloads only the metadata commits, their small trees,
  and the notes blobs (one JSON blob per commented patch set).

| Object type | Count | Uncompressed | On disk (as fetched, 19 packs) | What it is | Used by `derive` today? |
|---|---|---|---|---|---|
| commits | 98,963 (about 29 per CL) | 73 MB | 42.5 MB | One per review event: patch-set upload, vote, change message, reviewer or CC change, attention-set update, status. The message bodies (46 MB) are change messages and footers (`Attention:` 15%, `Label:` 8%, `Submitted-with:` 5.5%, ...) | No (votes come from the REST listing instead) |
| tip-tree blobs | 7,314 | 74 MB | 10.8 MB | The current comment notes. Uncompressed, they break down as `submitRequirementResults` 48 MB (65%), whitespace 15 MB, comment `message` text 4.2 MB (6%) and other comment fields 6 MB | **Yes, only the comment fields** |
| older blobs | 9,571 | 26 MB | 3.3 MB | Earlier versions of the notes blobs | No |
| trees | 15,733 | 2 MB | 1.6 MB | Notes trees | Only to find the tip blobs |
| **total** | 131,581 | 175 MB | **60 MB** (32 MB after `repack -a -d -f`) | | |

**So the part `derive` actually uses is about 10 MB of 175 MB uncompressed,
about 6%. Of that, comment text is 4 MB, about 2.4%.**

The bulk is review-event history (commits) plus the stored submit-requirement
results. Both compress well, and both are fetched only because fetching a ref
downloads its whole history.
- A shallow fetch (`--depth=1`) would cut the download to roughly the tip blobs,
  about 11 MB/week instead of 60 MB.
- That would drop the commit history, which is exactly the data the retention
  goal wants. We don't do it.

#### Size projection for one year (52 weeks)

| Store | Per week (W44) | Per year |
|---|---|---|
| NoteDb repo, as fetched | 60 MB | about 3.1 GB (about 1.7 GB if repacked once) |
| `raw.sqlite` listings | 9.7 MB | about 0.5 GB |
| **Total raw** | about 70 MB | **about 2.2–3.6 GB** |

The download volume from googlesource is about the same as the as-fetched pack
size, about 3 GB/year. Older weeks may be somewhat smaller: there were fewer
CLs in earlier years, and `submitRequirementResults` notes only exist for
changes closed after submit requirements were introduced. Five years is
therefore under about 15 GB. That is not a storage concern on this machine.

## 4. Privacy

**Policy (user, 2026-11-03):** per-person data that is derived from
already-public data may be committed and published. Everything cosh fetches
from Gerrit is public: names, emails, reviews and comment text. Chromium's
`affiliations.json5` is public too. This replaces the earlier "summaries are
org-level only" rule, so per-reviewer summaries such as
`summaries/reviewer_weekly.json` (the leaderboard) are allowed.

What to commit and what to keep local:
- **Commit:**
  - code
  - `config/*.csv` (domain → org, org → browser, bot patterns)
  - Radar inputs
  - `summaries/*`, per-org and per-reviewer alike
- **Keep out of git:** `data/private/`. The reason is size and churn, not
  privacy: `raw.sqlite` and the NoteDb repos are several GB per year, and
  `derived.sqlite` can be rebuilt.
- No minimum group size: `org_weekly` reports every org, however few
  reviewers it has. (An earlier rule folded orgs with fewer than 5 reviewers
  into `Other` for privacy; it was dropped with the policy change.)
  `gmail.com` is still always folded into `Other`, since a webmail domain is
  not an organization.
- `account_orgs.csv`, if it is ever created, holds manual employer guesses.
  Commit a line only when its source is a public record, and record the source
  on each line. Ask the user before committing guesses that have no public
  source.
- Retention: the raw stores keep full comment text and review history, although
  today's metrics need only counts and lengths. This is deliberate (§3.8).

## 5. Open questions (do not block the first week)

- Whether to use the change-messages column in the headline metric. It is noisy,
  e.g. "PTAL", "LGTM".
- How to obtain `is_owner` historically. The code-owners API reflects *current*
  OWNERS files, while evaluating OWNERS at the base revision is accurate but costly.
- Whether to exclude release-branch cherry-picks (15% of merged CLs). They are
  mostly rubber-stamped, so they probably should be excluded from or down-weighted
  in the headline numbers. Keep them in storage either way.
