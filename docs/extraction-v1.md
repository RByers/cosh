# Extraction v1: what is implemented

Status (2026-11-03): **2026-W44** (Mon 2026-10-26 to Sun 2026-11-01 UTC) was
extracted and validated first. The approved one-year backfill (2025-W45 ..
2026-W44) and an open-CL snapshot for the same year (`extract-open`) follow
it. A backfill to 2023-07-01 was approved on 2026-11-04. Fetching beyond that
needs approval (see `docs/plan.md`).

**metric_version 5** (2026-11-04): the metric is review comments (self-declared
AI comments from reviewers' own accounts included), each counted in the week
it was written, only on the paths `config/paths.txt` includes. Reviews without
a comment don't count. See "Metric definitions" below.

This follows `gerrit-api-research.md` and `storage-design.md`. Below are the
decisions made while implementing it; where they differ from those docs, this
file wins.

## Commands

```
python3 -m cosh extract --week 2026-W44     # network; cached and resumable (NoteDb by default)
python3 -m cosh extract-open                # network; open-CL snapshot + its NoteDb refs (after the backfill)
python3 -m cosh derive [--out PATH]         # offline: raw cache -> data/private/derived.sqlite
python3 -m cosh summarize [--db PATH] [--out DIR]   # offline: -> summaries/ (path scope: config/paths.txt)
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
  - `raw.sqlite` and `notedb/` keep **whatever we download, losslessly and
    permanently**, even data no metric uses yet, so nothing is ever fetched
    twice. That doesn't mean downloading everything: a leaner fetch is fine
    if it still gets what we need. See `storage-design.md` §3.8, which also
    covers what NoteDb contains and the size per year.
  - `derived.sqlite` is derived (one row per comment, with its file path but
    no text) and can be rebuilt. `derive` opens `raw.sqlite`
    read-only. It reads NoteDb comments in batches, one listing window
    (~100 CLs) at a time, with a few `git cat-file --batch` processes per
    window (`notedb.read_comments_many`). Starting git costs 2.5–10 ms per
    process in a repo of hundreds of packs, so the earlier two processes per
    CL took most of the run time: a full rebuild of 332k CLs fell from about
    20 min to 3.5 min (2026-11-04).
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

## Metric definitions (metric_version 5)

Versions:
1. Counted everything in the week the CL closed and left post-merge comments
   out of the headline.
2. Put post-merge comments in the headline, plus a vote floor: a Code-Review
   vote with no comment counted as one comment.
3. Counted review activity in the week it happened.
4. Counted self-declared AI comments from a reviewer's own account in the
   headline (summarize only). Over 53 weeks this added 1.1% to comments and
   moved no org's share by more than 0.04 points.
5. The current version. It keeps 3's weeks and 4's AI rule, and makes two
   changes:
   - **Comments only.** Vote-only reviews no longer count, so there is no
     vote floor and no `votes` table. Review characters and reviewed CLs
     stay as selectable metrics, both counted from comments.
     A review without a comment can't be valued: a bare +1 may stand for a
     careful read or a rubber stamp. The vote floor had added about 18% to
     the headline. It lowered the non-Google share from 4.08% to 3.77% over a
     year, because Google's reviews are vote-only more often (38% of review
     rows, against 28% for Microsoft). Opera is the exception: 64% of its
     reviews were bare approvals.
   - **Path scope.** Only comments on the paths that `config/paths.txt`
     includes count (see "Path scope" below).

Review activity counts in the ISO week (UTC) in which it happened. Under
metric_versions 1–2, everything counted in the week the CL closed. That week
held only 63% of the comments counted for W44 CLs: 22% were written in W43,
and about 4% eight or more weeks earlier. It also produced spikes for small
orgs: two long-running CLs made up 223 of the 258 Microsoft comments that
were counted in W44 but written earlier.

- **Tables** (`cosh/store.py`, `DERIVED_SCHEMA`):
  - `comments`: one row per published comment by a non-owner on a
    human-owned CL, with its `written_at`, `iso_week` and `path` (a file, or
    a Gerrit pseudo-path such as `/PATCHSET_LEVEL` or `/COMMIT_MSG`).
  - `changes`: one row per CL, from its newest listing. `close_week` is NULL
    for open CLs. `anchor_path` is the file with the most inline comments
    on the CL (see "Path scope").
  - `open_derived` refuses a `derived.sqlite` from before metric_version 5
    and says how to rebuild it.
- **Week of a comment:** the week of its `writtenOn` time in NoteDb (REST:
  `updated`).
- **Reviewers** in a week: non-bot accounts with an in-scope comment that
  week (an AI-only reviewer counts too). This is the same set as the rows
  of `reviewer_weekly.json`, so the web UI's distinct-reviewer counts match
  `org_weekly`.
- **Weeks reported:** only fully fetched weeks (`meta.fetched_weeks`).
  Activity before the oldest week, or in the current partial week, is
  stored but not summarized. Recent weeks are complete only as of the last
  open-CL snapshot (`meta.open_snapshot_at` in `org_weekly.json`); comments
  written after it appear on the next snapshot or once their CL closes.
- **Abandoned and open CLs count.** Review that points out flaws so that a
  CL never lands is valuable work.
- **Bot commits.** A CL is bot-owned if its owner has Gerrit's
  `SERVICE_USER` tag or matches a regex in `config/bots.txt`. W44 had 2,211.
  - Each gets one `changes` row with `is_bot_owned=1`.
  - It gets no comment rows and no comment fetch.
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
- **`comments` (the metric)** counts comments by human (non-bot) accounts
  written in the week on in-scope paths, including those written after the
  CL closed and, since metric_version 4, self-declared AI comments. `share`
  is an org's comments ÷ everyone's.
  - `ai_comments`: the subset with the `is_ai` flag or an `autogenerated:*`
    tag. Before metric_version 4 they were excluded from the headline.
  - `review_chars`: the length of those comments after removing quoted `>`
    lines (selectable metric).
  - `reviewed_cls` (selectable metric): CLs an org's reviewers commented on
    in scope, counted once per org in the week the CL closed, with the org as
    of the close. Open CLs count once they close. An org's share uses the
    sum of every org's CL count, so a CL reviewed by two orgs credits both.
  - `post_merge_comments`: the subset written after `closed_at`, however
    late (no window), counted in the week they were written. They count
    because post-merge review that leads to a follow-up CL is real value.
    Summaries also report them per org and week. (58% arrive within a day of
    the close, 89% within 14 days.)
  - Spam among them (names, pasted prompts) is an open issue; see
    `plan.md`, Open questions.
- **Validation (metric_version 3):** for CLs that closed in W44, the
  activity-keyed `comments` table reproduced the CL-keyed tables exactly:
  10,426 pre-close comments, 1,142 AI comments and 78 post-merge comments.
- **`is_owner`:** not stored (deferred). The code-owners API answers against
  the *current* OWNERS files, so it is wrong for history. Plan: evaluate the
  OWNERS files at the merge commit's parent in a local checkout.

### Path scope (`config/paths.txt`, `cosh/paths.py`)

Every comment is placed on one file, and the scope decides whether that file
counts.

- **Rules:** `exclude <dir>/` and `include <dir>/` lines. The longest matching
  prefix wins, and a path matching no rule is included. Now:
  - excluded: `chrome/`, `ios/`, `android_webview/`, `ash/`, `chromeos/`,
    `components/`;
  - included again: `chrome/browser/web_applications/`, `chrome/browser/webnn/`,
    `components/viz/`, `components/services/storage/`.
  The excluded trees are Google's own products built on Chromium (Chrome,
  Chrome for iOS, Android WebView, ChromeOS), where review is mostly Google
  reviewing Google's product code, and `components/`, which is mostly browser
  features built for Chrome. Over 2025-W45..2026-W44, `components/` held
  15.8% of placed review comments, 1.85% of them non-Google; its top ten
  subdirectories (autofill, accessibility_annotator, policy, signin,
  browser_ui, viz, enterprise, omnibox, optimization_guide, password_manager)
  held 49%, and all but viz were under 1% non-Google. The exceptions are
  shared platform work that other Chromium browsers build on: Microsoft
  writes much of the `web_applications` review, Intel and Microsoft much of
  the WebNN review, `components/viz/` (the compositor) was 11.6%
  non-Google, and `components/services/storage/` (DOM storage, the backend
  for `localStorage`/`sessionStorage`) was 88% Microsoft (791 comments).
  `components/surface_embed/` (35% Microsoft, 308 comments) also had outside
  review and is out of scope.
- **Placement.** We don't fetch CL file lists, so:
  - an inline comment is on its own file;
  - a patchset-level or commit-message comment goes to the CL's anchor, the
    file with the most inline comments on the CL from anyone, the owner's
    replies included (ties: the alphabetically first path);
  - a comment on a CL with no inline comments at all can't be placed. It is
    excluded, and shown as the area `(no file)` in `area_weekly.json`.
  In a 20k-CL sample of human review comments, 68% were inline, 22% were
  placed through the anchor and 10% couldn't be placed. Exact file lists
  would need a blob-less git fetch of `main`'s history (not approved; see
  `plan.md`, Open questions).
- **Directory tree** (`area_weekly.json`, the web UI's "Review by
  directory" chart; `dir_tree` in `cosh/paths.py`): every comment, in scope
  or not, so the page can show what the scope leaves out.
  - Roots are the areas: the longest matching `area` prefix in
    `config/paths.txt` (`third_party/blink/` is listed as one), else the
    top-level directory, plus `(no file)` and `(top-level files)`.
    Re-included directories stay inside their parents.
  - Every include/exclude rule directory is a node, so each node's own
    bucket is wholly in or out of scope, and the UI can show how much of a
    partly included directory (e.g. `components/`, with `viz/` and
    `services/storage/` back in) is in scope.
  - Below a root, the 10,000 directories with the most comments
    (`DIR_LIMIT`) are kept, with their ancestors. A comment in any other
    directory counts in its nearest kept ancestor's own bucket. Over
    2025-W45..2026-W44 only 10,312 directories had comments, so 99.9% of
    comments stay in their own directory.
  - Rows are per (week, node, org) for each node's own bucket: comments and
    chars by week written, reviewed CLs by week closed, counting (CL, bucket)
    pairs. The client sums buckets up the tree, so children add up to their
    parent.
  - Size: for those 52 weeks, 14,500 nodes and 1.76 MB of JSON (0.52 MB
    gzipped); the weekly rows grow with the weeks covered.
- **Changing the scope** needs only `summarize`, not a new `derive`: paths
  are stored per comment.

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
- **Use:** treat `ai_comments` as a lower bound. It is a subset of the
  headline (since metric_version 4), reported per org so AI-assisted review
  can still be told apart.


## Org attribution (`cosh/orgs.py`)

The org is a domain name, evaluated as of the day of the comment:

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
every reviewer's in-scope comments per week, with the same scope and weeks
as `org_weekly`: one row per (week, account, org), with orgs resolved per
comment as in `org_weekly`, but before the `gmail.com` fold. Summed per
(week, folded org), the rows reproduce `org_weekly`'s `reviewers` and
`comments` exactly, so the web UI can count distinct reviewers and rank
reviewers over any range of weeks. The format is compact: names once per
account, orgs once, and rows of `[account_id, org index, comments, cls,
chars]`. (Reviewed CLs can't be summed across reviewers, since two can share
a CL; the UI takes an org's `reviewed_cls` from `org_weekly`.)

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
- Reviews with no comment (a bare vote) aren't counted at all, by design
  (metric_version 5).
- Patchset-level comments are placed on the CL's most-commented file, not on
  the files the CL actually touches; about 10% of comments can't be placed
  (see "Path scope").
- An abandoned CL that is touched again after abandonment can appear in two
  weekly listings. Derive uses the newer listing, and comments are keyed by
  their own id and time, so nothing is double counted.
- Comments on CLs that are still open and were last updated before the
  snapshot's `since` (2025-11-03) are out of scope. They predate the year.
- Extraction resolves only account IDs that are absent from the listing. IDs
  present in the listing without an email are not looked up (the remaining
  8 rows).
