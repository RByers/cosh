# Extraction v1: what is implemented

Status (2026-11-03): **2026-W44** (Mon 2026-10-26 to Sun 2026-11-01 UTC) was
extracted and validated first. The approved one-year backfill (2025-W45 ..
2026-W44) and an open-CL snapshot for the same year (`extract-open`) follow
it. A backfill to 2023-07-01 was approved on 2026-11-04. Fetching beyond that
needs approval (see `docs/plan.md`).

**metric_version 7** (2026-11-04): the primary metric is **addressed review
comments**. These are comments in a review thread that led the CL owner to
change the CL, decided by a regex on the owner's reply or by a Claude Haiku
label (`comment-classifier.md`). All review comments remain available, and
are the fallback for weeks not yet classified.
- Both are counted from metric_version 6's comments: self-declared AI
  comments from reviewers' own accounts included, each counted in the week
  it was written, and only on the paths `config/paths.txt` includes.
- Reviews without a comment don't count, and neither do patchset-level
  comments from a reviewer who left no inline comment on the CL.

See "Metric definitions" below.

This follows `gerrit-api-research.md` and `storage-design.md`. Below are the
decisions made while implementing it; where they differ from those docs, this
file wins.

## Commands

```
python3 -m cosh extract --week 2026-W44     # network; cached and resumable (NoteDb by default)
python3 -m cosh extract-open                # network; open-CL snapshot + its NoteDb refs (after the backfill)
python3 -m cosh derive [--out PATH]         # offline: raw cache -> data/private/derived.sqlite
python3 -m cosh summarize [--db PATH] [--out DIR]   # offline: -> summaries/ (path scope: config/paths.txt)
python3 -m cosh radar [--offline]           # Cloudflare Radar; needs `source ~/.secrets/cosh/secrets.sh`
python3 -m cosh backfill --weeks 52 [--go]  # plan only unless --go (the 52 weeks are approved)
python3 -m cosh update-affiliations         # refresh config/affiliations.json5 (analyses also do it)
python3 -m cosh status
python3 -m unittest tests.test_derive tests.test_extract tests.test_radar tests.test_classify
```

## Pipeline and data flow

```
Gerrit REST listing ─► data/private/raw.sqlite ─┐
NoteDb `git fetch`  ─► data/private/notedb/*.git ┼─ derive ─► data/private/derived.sqlite ─┬─ summarize ─► summaries/
                                                 │                                          │
                                                 └─ classify (claude -p, Haiku) ─► data/private/labels.sqlite ─┘
Cloudflare Radar    ─► data/public/radar/raw/ ──── radar ──► data/public/radar_browser_share.csv
```

- **`classify` is optional.** It reads `derived.sqlite` (which threads
  need a label) and the comment text from NoteDb or the REST cache. It
  writes only `labels.sqlite`, which is never deleted: the labels cost Max
  usage to make.
- **`summarize` without labels:** it attaches `labels.sqlite` read-only
  if it exists. Without it, weeks just show as unclassified.

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
   `User-Agent: cosh/0.1 (...; contact: <email>)` and `From: <email>`.
   - Git sends the same through `GIT_USER_AGENT` (which also sets the protocol
     `agent=` field) and `http.extraHeader`.
   - All of this lives in `cosh/contact.py`. The address is not in the repo:
     it comes from `{"contact_email": "..."}` in the gitignored
     `data/private/settings.json` (the data dir's, else the main checkout's,
     so every worktree shares one file), or `COSH_CONTACT` overrides it.
     Commands that fetch (`extract`, `extract-open`, `backfill --go`,
     `radar` without `--offline`, `update-affiliations`) fail at once,
     asking for an e-mail address, if none is set. Offline commands never
     need one.

## Metric definitions (metric_version 7)

**metric_version 7** (2026-11-04) adds **addressed comments**, the primary
metric:
- **What scores:** a non-owner comment scores one point if its thread was
  started by a reviewer, led the CL owner to change the CL, and the comment
  was written no later than the owner's last reply in the thread.
- **How threads are decided:** by a regex on the owner's first reply in
  `derive`, or by a Haiku label from the optional `cosh classify` step
  (`labels.sqlite`).
- **Coverage:** weeks whose threads aren't all decided report
  `pending_comments`, and the UI hides the metric for them.

Everything else is metric_version 6. See `comment-classifier.md`, "Design".

Versions:
1. Counted everything in the week the CL closed and left post-merge comments
   out of the headline.
2. Put post-merge comments in the headline, plus a vote floor: a Code-Review
   vote with no comment counted as one comment.
3. Counted review activity in the week it happened.
4. Counted self-declared AI comments from a reviewer's own account in the
   headline (summarize only). Over 53 weeks this added 1.1% to comments and
   moved no org's share by more than 0.04 points.
5. Kept 3's weeks and 4's AI rule, and made two changes:
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
6. The current version (summarize only; `derived.sqlite` is unchanged). It
   changes how comments are placed on files:
   - A patchset-level comment is placed on its author's own anchor on the
     CL, the file that reviewer left the most inline comments on, not on
     the CL's anchor.
   - A patchset-level comment from a reviewer who left no inline comment on
     the CL is unplaced, like a comment on a CL with no inline comments.
   - Accounts that never left an inline comment anywhere are dropped,
     `area_weekly.json` included.
   The reasons are under "Path scope", "Why reviewer-only patchset comments
   are unplaced". Over 2025-W45..2026-W44 this took comments from 150,197 to
   140,984, reviewed-CL credits from 24,506 to 23,506 and reviewers from
   1,854 to 1,541. The non-Google share went from 10.65% to 10.80% of
   comments, from 10.50% to 10.29% of characters and from 9.92% to 8.55% of
   reviewed CLs. About half of that CL drop is spam leaving "Other".

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
    `chrome/browser/resources/webnn_internals/`,
    `chrome/browser/ui/webui/webnn_internals/`, `components/viz/`,
    `components/services/storage/`, `components/surface_embed/`, and the
    accessibility directories `chrome/renderer/accessibility/`,
    `chrome/browser/accessibility/`, `chrome/browser/ash/arc/accessibility/`,
    `chrome/browser/resources/accessibility/`,
    `chrome/browser/ui/{ash,aura,views,webui}/accessibility/` and
    `chrome/test/accessibility/ax_client/`.
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
  On 2026-11-06 an OWNERS search added the excluded directories whose own
  OWNERS files (with their `file:` includes) name owners outside google.com
  and chromium.org, and that have outside review or are shared platform
  work: `components/surface_embed/` (Microsoft owners, 36% non-Google of
  320 comments), `chrome/browser/resources/webnn_internals/` and
  `chrome/browser/ui/webui/webnn_internals/` (Intel and Microsoft owners;
  the second was added on the user's request the same day) and the `chrome/` accessibility directories, which
  include `ui/accessibility/OWNERS` and its Microsoft owners. Over
  2025-W45..2026-W44 they added 1,160 in-scope comments (140,998 →
  142,158), and the non-Google share moved from 10.80% to 10.82%
  (characters 10.29% → 10.32%, addressed 11.68% → 11.70%, reviewed CLs
  unchanged at 8.55%). Most other excluded directories with outside owners
  have them only on `per-file` lines (e.g. `chrome/browser/`) or see
  almost no review.
- **Placement** (metric_version 6; `summarize.reviewer_anchors`). We don't
  fetch CL file lists, so:
  - an inline comment is on its own file;
  - a patchset-level or commit-message comment goes to its author's anchor
    on that CL: the file the same reviewer left the most inline comments on
    (ties: the alphabetically first path);
  - a patchset-level comment whose author left no inline comment on the CL
    can't be placed. It is excluded, and shown as the area `(no file)` in
    `area_weekly.json`;
  - comments from accounts that never left an inline comment anywhere are
    dropped entirely, `(no file)` included.
  Until metric_version 5, patchset-level comments went to the CL's anchor
  (`changes.anchor_path`, the file with the most inline comments from
  anyone, owner replies included), so only CLs with no inline comments at
  all were unplaced. `derive` still records that column, but nothing uses
  it. In-scope comments over 2025-W45..2026-W44 under the old rule: 110,488
  inline, 30,504 patchset-level from reviewers who also commented inline on
  the CL, and 9,215 from reviewers who didn't. Version 6 keeps the first two
  and drops the third. Exact file lists
  would need a blob-less git fetch of `main`'s history (not approved; see
  `plan.md`, Open questions).
- **Why `(no file)` stays excluded** (checked 2026-11-04 over 2025-W28 ..
  2026-W45). Unplaced comments were 29,008 of 274,346 human review comments
  (10.6%), spread over 19,902 of 52,835 reviewed CLs (38%), about 200 CLs a
  week. They are mostly approvals and routing, not review that can be judged:
  - *30 random unplaced CLs, every reviewer comment read:* 15 had only
    "LGTM"/"thanks", 3 only routed or declined ("adding X", "X is better
    suited"), 8 added a minor note, question or commit-message nit to an
    approval, and 4 showed real review, all about direction rather than code
    (a narrower test list, which the owner adopted; a better competing CL,
    and this one was abandoned; "keep those metrics", abandoned; "answer the
    design doc first"). A reviewer with line-level feedback leaves an inline
    comment, which gives the CL an anchor.
  - *Comments in a 6,000-CL sample, by kind,* with a crude approval-only
    filter ("lgtm", "thanks", "ptal", "+1" and similar, or empty; it misses
    variants like "LGTM, thank you!", so it undercounts):

    | Kind | Approval-only | ≥ 80 chars | Not google.com/chromium.org |
    |---|---|---|---|
    | inline | 3.9% | 60.9% | 3.6% |
    | patchset-level, anchored | 22.7% | 35.2% | 4.3% |
    | unplaced | 43.2% | 27.7% | 3.3% |

  So placing them would add mostly approval-shaped counts, like the
  vote-only reviews metric_version 5 dropped, and would barely move org
  shares (their non-Google share is close to the rest). Options weighed for
  placing them anyway, none adopted:
  - *Guess from the owner's other placed CLs* (no fetch): tested on 41k
    anchored CLs, it picked the right area 65% of the time, the right
    in/out-of-scope side 86%, the right 3-level directory 41%. Too weak.
  - *`/revisions/current/files` per CL:* exact, ~20k requests a year;
    breaks the batches-not-per-CL rule.
  - *Batched query* `q=change:N1 OR … change:N100` with
    `o=CURRENT_REVISION&o=CURRENT_FILES`, anchoring on the file with the
    most inserted + deleted lines: exact, ~200 requests a year (~700 for
    the 3-year range), though `CURRENT_FILES` is heavy server-side
    (`gerrit-api-research.md`). The cheapest real fix if it's ever needed;
    needs approval.
  - *Blob-less git fetch of patchset commits:* file names only, no line
    counts without blobs; large first tree fetch.
- **Why reviewer-only patchset comments are unplaced** (checked
  2026-11-04 over 2025-W45..2026-W44; the case for dropping *all*
  patchset-level comments was weighed and rejected). Split the anchored
  patchset-level comments into *A*, written by a reviewer who also
  commented inline on the CL (a cover note), and *B*, written by one who
  didn't, so that only someone else's inline comments anchored it. For B's
  author the CL has no file, as for `(no file)`.
  - *Crude approval-only filter on 4,000 random comments of each kind:*
    inline 1.6%, A 20%, B 19%, `(no file)` 39%. At least 80 characters:
    63%, 37%, 37%, 29%.
  - *35 of each, read:* A had 12 substantive comments (design and
    direction: "I'd recommend against adding it to the base/test API",
    "Why is a fencedframe able to call this IPC in the first place?"), 17
    approvals, 3 routing, 3 minor or noise. B had 7 substantive, 13
    approvals (7 of them scoped OWNERS stamps such as "mojom lgtm" or "net/
    LGTM"), 6 routing or declining, 5 minor notes, 4 spam or noise.
  - *B was misplaced.* The CL's anchor is the main reviewer's file, not the
    files an OWNERS stamp covers: "mojom lgtm" landed on
    `content/browser/devtools/`, and "devtools_instrumentation LGTM" on
    `third_party/chromium-bidi/`. About 12% of B looked like such stamps.
  - *B is where spam lands.* In B, gmail.com ("Other") had 276 comments
    from 163 accounts, and most of them were spam or drive-by comments
    (ads, names, e-mail addresses, "Comment removed by …; Reason: spam",
    requests to merge into a release branch). One account's 10 HTML
    comments were 3.7% of all B characters. Gmail's inline comments (367
    from 42 accounts) were all real review in a sample of 30. B gave "Other"
    55% of its reviewed-CL credits, Igalia 30%, Intel 23%, Google 18%
    (OWNERS stamps) and Microsoft 11%.
  - So B is like `(no file)`: approval and routing heavy, placed on the
    wrong directory, and noisy. It goes. A is a reviewer's summary of their
    own line-level review, a third of it substantive, so it stays, placed
    on that reviewer's own file. Dropping all patchset-level comments as
    well would have moved the non-Google comment share from 10.80% to
    11.30%, by throwing away cover notes.
  - Spam outside B (in `(no file)` and the directory chart) is caught by
    dropping accounts that never commented inline. In-scope metrics can't
    contain such accounts anyway, since every placed comment's author
    commented inline on that CL.
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
  - **Gerrit links.** `area_reviewers.json` splits each (week, node, org)
    bucket by reviewer. Each org segment on the chart then links to Gerrit:
    `dir:<path>` plus `after:`/`before:` dates plus
    `(commentby:A -owner:A) OR …`, for the 100 reviewers in that row's
    subtree (or, for a "rest of" row, its own bucket) with the most comments
    in the range. That's a superset of the counted CLs. `dir:` can't be
    anchored (Chromium Gerrit has regex search off), it includes
    subdirectories and looks at the current patch set only, and Gerrit dates
    bound when a CL last changed, not when a comment was written. The
    `before:` bound is 28 days after the range ends. Gerrit has no domain or
    wildcard account search (`*@microsoft.com` matches nothing, and a bare
    `microsoft.com` expands past the 800-term limit), hence the explicit
    account ids.
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
   - Every analysis refreshes it first: `OrgResolver()` fetches the file from
     chromium/src `main` once per process (one small googlesource request)
     and rewrites it only when it changed, saying so on stderr; commit it
     with the outputs. A failed fetch stops the run;
     `COSH_AFFILIATIONS_OFFLINE=1` uses the local copy as it is (the tests
     set it in `tests/__init__.py`). `balance_narrative.py --cache` rebuilds
     a cache made with a different copy.
   - Dates before a person's earliest `start` fall through to rule 2 or 3.
   - The values `Individual` and `Undisclosed` are kept as-is. Summaries
     fold `Undisclosed` into Other, like `gmail.com` (`FOLD_INTO_OTHER`).
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
- Patchset-level comments are placed on their author's most-commented file
  on the CL, not on the files the CL actually touches. Those from reviewers
  with no inline comment on the CL, and all comments on CLs with no inline
  comments, can't be placed (see "Path scope").
- Spam from accounts that also commented inline somewhere is still
  counted.
- An abandoned CL that is touched again after abandonment can appear in two
  weekly listings. Derive uses the newer listing, and comments are keyed by
  their own id and time, so nothing is double counted.
- Comments on CLs that are still open and were last updated before the
  snapshot's `since` (2025-11-03) are out of scope. They predate the year.
- Extraction resolves only account IDs that are absent from the listing. IDs
  present in the listing without an email are not looked up (the remaining
  8 rows).
