# cosh plan, decisions and status

This is the entry point for anyone (human or a fresh Claude session) picking
the project up. Read this, then `README.md`, then `docs/extraction-v1.md`.

## Goal

cosh generates a set of dashboards about the health of the Chromium open
source project, published as one static site: a landing page
(`web/index.html`) with a card for each dashboard. Each dashboard answers one
question from public data. The sources are Chromium Gerrit code review and
Cloudflare Radar browser usage today. Chromium's git history and bug tracker
are planned, and others may follow. Each new source (or more data from an
existing one) is fetched only once the user has approved it (ground rule 1),
under the same load rules (ground rule 2). It gets its own extractor, a raw
cache in `data/private/` that is kept losslessly, and small committed
summaries that the pages read.

### First dashboard: Value Exchange (`web/value.html`)

For each organization *O* and period *t*, plot over time:

```
value_ratio(O, t) = O's share of Chromium addressed review comments
                    / O's browser's share of Chromium-based browser usage
```

- **Addressed review comments are the primary contribution measure**
  (metric_version 7, `comment-classifier.md`). They are review comments in
  threads that led the CL owner to change the CL.
  - **How threads are decided:** a regex on the owner's reply, then Claude
    Haiku via headless `claude -p` for the rest.
  - **Fallback:** for weeks not yet classified, the UI falls back to all
    review comments.
- Review data comes from Chromium Gerrit.
- Usage data comes from Cloudflare Radar.
- The result is the `value.html` page of the static site on GitHub Pages,
  which reads only `summaries/` and `data/public/radar_browser_share.csv`.

## Ground rules

1. **Fetch only what has been approved.** The user approved the one-year
   backfill (52 weeks, 2025-W45 .. 2026-W44) on 2026-11-03, before validating
   the UI. Going beyond that year still needs explicit approval.
   - `backfill` prints a plan unless it is given `--go`.
2. **Be gentle with Google's servers.**
   - Serial requests.
   - REST: at least 1 s between requests. Git: one connection, one fetch at a
     time, at least 5 s apart; duty cycle up to 1.0 (back to back) approved by
     the user on 2026-11-04, replacing "at most 0.5". Never parallel fetches.
   - Back off on 429.
   - Identify ourselves with the operator's contact address, set in the
     gitignored `data/private/settings.json` (`extraction-v1.md`, "Identification").
3. **Per-person data derived from public data may be committed and
   published** (user's policy, 2026-11-03). Gerrit reviews, names, emails
   and affiliations are already public, so per-reviewer summaries can go in
   `summaries/` and on the site.
   - `data/private/` stays gitignored because of its size (raw caches, NoteDb
     repos, rebuildable DBs), not for privacy.
   - Data that is *not* from a public source, such as manual employer
     guesses that aren't backed by a public record, still needs the user's
     approval before it's committed.
   - Sentiment is the exception: ground rule 5.
4. **Credentials:** `secrets.sh` (gitignored, mode 600) exports
   `CLOUDFLARE_API_TOKEN`. Load it with `source secrets.sh`, and never print
   or commit the token.
5. **Sentiment: our pages never point fingers** (user's policy, 2026-11-06;
   relaxed 2026-11-07). Review-comment tone (`cosh.sentiment`,
   `docs/sentiment.md`) is a reading of how people behave, so what we
   *publish* about it is held to a stricter rule than ground rule 3. The
   code is not: it may attach identities to any scored comment
   (`cosh.sentiment_people`) and compute per-person figures, and it's fine
   that someone could change it to single people out. We never do so in
   anything we publish: the site, `summaries/` and docs.
   - **Nothing we publish singles anyone out for negative behaviour.** No
     ranking, list, quote or link that ties negative tone to a person, team
     or other small, identifiable group. Project-wide figures (the monthly
     trend, the last two months in full, shares of angry, glowing or
     AI-frustrated comments, splits by role or by human vs AI recipient)
     are fine.
   - **Organizations get no tone figures at all**, positive or negative.
   - **People may be named for praise:** the praise leaderboards, "who makes
     whom happy" (counts of happy counterparts only, never a mean or
     anything negative) and sample praise with Gerrit links.
   - **Negative comments appear only anonymously:** text, month and at most
     the writer's role, no names, links, files or exact dates. That covers
     the grumpy samples and the AI-friction list. Each one must pass a
     sandboxed screen (`screen_identifying`: nothing that identifies anyone,
     accuses anyone of misconduct or points at a specific ticket). The 20
     samples are read before they're committed; the longer AI-friction list
     is spot-checked. Known limit: quoted text can still be found with
     Gerrit's comment search.
   - **Example comments may be quoted** (in prompts, docs or the UI) unless
     they are negative *and* name someone.
   - **Labelled data that ties negative labels to specific comments stays
     out of the repo:** gold sets (comment ids with scores) and
     per-comment model reasons.
   - **Otherwise publish as much as possible:** the method, every prompt
     version, the code, its security design, accuracy figures, the
     aggregate data and the praise views.

## Decisions log

| Date | Decision | Why |
|---|---|---|
| 2026-11-03 | Two SQLite files (raw cache plus derived tables) with CSV/JSON summaries, not flat CSV | Resumable, idempotent re-runs; the front end needs only small summaries (`storage-design.md`) |
| 2026-11-03 | Weeks are ISO weeks (UTC) of merge time, listed with `mergedafter:`/`mergedbefore:` | `after:` filters on last-updated time and would double count. (Still how CLs are *listed*; superseded for *counting* by metric_version 2 below) |
| 2026-11-03 | **metric_version 3:** count each comment in the week it was written and each vote in the week it was cast; only reviewed CLs stay per CL, by close week. Keeps metric_version 2's rules: post-merge comments count, in the week they were written, and the vote floor applies in the week of the vote. New schema `derived.sqlite` (`comments`, `votes`, `changes`, view `cl_reviewers`) replaces the CL-keyed `cosh.sqlite`. (Votes, the vote floor and reviewed CLs were dropped in metric_version 5, below) | User's instruction. Under close-week counting, 37% of W44's comments were written in earlier weeks, and long-running CLs made spikes for small orgs (Microsoft: 81% of its W44 comments, mostly from two CLs) |
| 2026-11-03 | Fetch open CLs too (`extract-open`): open CLs on main updated during the backfill year, plus CLs closed after the newest fetched week, with their NoteDb refs. Approved for that year | User's instruction. Without them, a comment stays invisible until its CL closes, so recent weeks are undercounted, most of all for orgs with long review cycles |
| 2026-11-03 | Vote times come from NoteDb `Label:` lines, not the listing's `date` | Gerrit restamps listing vote dates at submit (11,003 of 11,036 merged-CL votes in W43–W44). **Superseded:** votes aren't used since metric_version 5; the listings and NoteDb still hold them |
| 2026-11-03 | Refetch a NoteDb ref when the listing's `updated` is newer than the local tip | The tip time equals `updated` exactly (3,429 of 3,429 W44 CLs), so this refetches only CLs that changed, and only incrementally |
| 2026-11-03 | Org = email domain, with dated overrides from Chromium's `affiliations.json5`; other `@chromium.org` accounts → `google.com` | User's instruction; this is how Chromium itself attributes contributors |
| 2026-11-03 | `gmail.com` is always folded into `Other`, whatever its size (`FOLD_INTO_OTHER` in `cosh/summarize.py`) | User's instruction: a webmail domain is not an organization |
| 2026-11-03 | Headline metric is the review **comment count**; reviewed CLs and characters are options (`--metric`) | Balances verbose commenters against complex reviews. Still true under metric_version 5, with all three counted from comments only |
| 2026-11-03 | Only branch `main`; release branches ignored | User's instruction |
| 2026-11-03 | Bot-owned CLs get one row flagged as a bot commit and no review rows; counted in `weekly_totals.csv` | Avoids apparent gaps without crediting autoroll rubber-stamps |
| 2026-11-03 | Include abandoned CLs, bucketed by last update | Review that keeps a flawed CL from landing is valuable |
| 2026-11-03 | Track AI comments separately (`is_ai` flag or `autogenerated:*` tag), as a lower bound, excluded from the headline. **Superseded on 2026-11-04 (metric_version 4)** | Only self-declared AI use is detectable |
| 2026-11-04 | **metric_version 4:** self-declared AI comments from reviewers' own accounts count in the headline (comments, chars, and they satisfy the vote floor); `ai_comments` stays as the reported subset. Bot and AI-agent *accounts* (incl. email-less ones) stay excluded. Applied in `summarize`; derived schema unchanged from 3. Intro drops "human" wording | User's instruction: don't exclude AI review comments |
| 2026-11-03 | Treat accounts with no email as bots / AI agents; store `display_name` when there is no `name` | User's instruction: in W44 these were an AI agent (Jetski), a deleted account and two accounts `/accounts` 404s on |
| 2026-11-03 | A review with a Code-Review vote but no counted comment counts as one comment (applied in `summarize`; reported as `vote_only_reviews`) | User's instruction: a review that needed no changes should still count in the comments chart. A floor, not +1 per vote, so "LGTM" + vote isn't counted twice. **Superseded** by metric_version 5 |
| 2026-11-04 | **metric_version 5: review comments only.** Vote-only reviews no longer count; the vote floor, the `votes` table, the `cl_reviewers` view, review characters and reviewed CLs stay as selectable metrics, counted from comments (a CL counts as reviewed, in its close week, if the org commented on it in scope). The selector was briefly removed and restored on the user's request | User's instruction: the value of a review without comments can't be judged. Over the year the floor added 18% to the headline and lowered the non-Google share from 4.08% to 3.77% (Google's reviews are 38% vote-only; Opera's 64%) |
| 2026-11-04 | **Path scope** (`config/paths.txt`): exclude `chrome/`, `ios/`, `android_webview/`, `ash/`, `chromeos/` and `components/`, but include `chrome/browser/web_applications/`, `chrome/browser/webnn/`, `components/viz/` and `components/services/storage/`. Longest prefix wins. The value ratio, org chart, table and leaderboard count only in-scope comments; `area_weekly.json` and the "Review by directory" chart show every comment by directory, with a row for each re-included directory even when small | User's instruction (ash/, chromeos/, and components/ with components/viz/ and components/services/storage/, added the same day): those trees are Google-specific products (Chrome, Chrome for iOS, Android WebView, ChromeOS), where review is mostly Google reviewing Google. The two exceptions are shared platform work with heavy Microsoft and Intel review. In a 60k-CL sample, `chrome/` held 41% of reviewer comments but only 7% of non-Google ones. Over a year, `components/` was 15.8% of comments and 1.85% non-Google; of its top ten subdirectories only `viz/` (11.6%) had real outside review (`extraction-v1.md`, Path scope) |
| 2026-11-04 | Place each comment on a file without fetching CL file lists: inline comments on their file, patchset-level comments on the CL's most-inline-commented file (owner replies included); comments on CLs with no inline comments are excluded as `(no file)` | No new fetching. Covers about 90% of comments (68% inline, 22% via the anchor). Exact file lists would need a blob-less git fetch of `main`, which isn't approved |
| 2026-11-04 | Keep `(no file)` comments excluded; don't seek approval to fetch file lists just to place them. The UI says why: the measure is review attached to source files | Sampled 30 unplaced CLs: half were only LGTM/thanks, 4 of 30 showed real review. In a 6,000-CL sample, 43% of unplaced comments were approval-only against 4% of inline ones, and their non-Google share (3.3%) is close to the rest. Analysis and fetch options in `extraction-v1.md`, Placement |
| 2026-11-04 | **metric_version 6** (summarize only): a patchset-level comment goes to its author's own most-inline-commented file on the CL. If the author left no inline comment there, it is `(no file)`. Accounts that never commented inline are dropped everywhere. Keeping patchset-level cover notes was chosen over dropping all patchset-level comments | User's approval of the analysis in `extraction-v1.md`, "Why reviewer-only patchset comments are unplaced". Those comments (6% of in-scope comments) were approval, routing and OWNERS stamps placed on the wrong directory, plus most of the spam. Cover notes alongside one's own inline review are a third substantive. Over 2025-W45..2026-W44 non-Google: comments 10.65% → 10.80%, chars 10.50% → 10.29%, reviewed CLs 9.92% → 8.55%; reviewers 1,854 → 1,541 |
| 2026-11-04 | **Planned headline: addressed comments.** One point per non-author comment in a thread that led to a change, credited to the comment's author (multi-party threads credit each participant per comment); no points if the thread ended without a change, none to the CL author side. Classification is its own step (`cosh classify`), labels in a new, never-deleted `data/private/labels.sqlite`, and the UI must work with no labels or only some. Not built yet (Next steps 6) | User's instruction, after `review-impact.md` (a comment isn't valuable in itself) and `comment-classifier.md` (regex + Haiku ≈ 0.97 accuracy on 400 labelled threads) |
| 2026-11-04 | **metric_version 7: addressed comments built (v1).** `derive` records threads (`comments.root_uuid`, `threads` table, regex result); optional `cosh classify` labels the rest with Haiku via headless `claude -p` into never-deleted `labels.sqlite`; `summarize` writes `addressed_comments`, `pending_comments`, `share_addressed` and per-week coverage; the UI offers the metric for classified weeks only and defaults to it once the default range is classified. Author side = CL owner only in v1. 2026-W44 classified: 2,626 labels, 949k tokens, 11 min | User's instruction to build the basic classifier and UI and classify one week |
| 2026-11-04 | **Design principle: acceptance rate is not a citizenship signal.** Views should help organizations be better Chromium citizens, so they show how much review *drove changes* (addressed comments, per org and per reviewer over time), never a reviewer's or org's addressed ÷ comments rate as a score. Comments that led to no change are not bad: asking how a CL works or checking an assumption is good review. UI copy says so where unaddressed threads appear (thread box, reviewer chart). Dropped from the plan: acceptance-rate views by org, reviewer or directory | User's instruction: reviewers shouldn't be afraid to ask questions |
| 2026-11-04 | Web UI "Review by directory" is a drill-down tree: top-level areas, each opening into its subdirectories (plus a "rest of" row so children add up), 20 entries per level and an "N more" row that opens 20 at a time and closes again. `area_weekly.json` holds the 10,000 directories with the most comments (`DIR_LIMIT`) and their ancestors; rarer ones roll up into their nearest kept ancestor. Replaces the "Top N" selector | User's request. Over 2025-W45..2026-W44 only 10,312 directories had comments, so 10,000 keeps 99.9% in place; the year's file is 1.76 MB (0.52 MB gzipped), about as heavy as `reviewer_weekly.json` |
| 2026-11-04 | "Review by directory" no longer lists re-included directories at the top level: they stay inside their parents, and each volume bar is solid for the part in scope and hatched for the part left out (the included/excluded tags are gone). Every rule directory is a tree node, so the split is exact | User's request: simpler; the bar conveys partial inclusion |
| 2026-11-04 | **Directory filter and heatmap.** "Review by organization" takes a Directory field (`&dir=`): with one set, the chart counts every comment in that subtree from `area_weekly.json`, in scope or not, and says what share the scope leaves out; the value ratio is unaffected (usage isn't per directory). New "Review by directory over time": the directory tree against 1/4/13-week bins, for every org, all but google.com, or one org. Mix cells are small stacked columns, not pies; one-org cells are shaded in the org's colour (square-root volume, or share of the directory). Cells link to Gerrit like the directory chart, and their hover text names the top 3 reviewers from `area_reviewers.json`. No new summary data | User's request, after Microsoft's post-W36 drop (277 → 198 comments a week, W29–W36 vs W37–W44, with reviewed CLs steady) turned out to be a few of its own projects winding down in a few directories: `components/services/storage`, `chrome/browser/web_applications`, `gpu/command_buffer/service`, `third_party/blink/renderer`. Stacked columns follow the dataviz guidance for "a split changing over time"; pies can't show volume and are unreadable at cell size |
| 2026-11-03 | Report post-merge comments per org in summaries (`post_merge_comments`), excluded from the headline | User's instruction: post-merge review is still valuable; the headline measures review before landing. **Superseded by the next row** |
| 2026-11-03 | Post-merge comments count in the headline, however late (metric_version 2); `post_merge_comments` stays as the subset written after `closed_at` | User's instruction: post-merge comments that lead to changes in a later CL are real value; no time window, for simplicity. Over 36 weeks they were ~1% of comments (3,507 vs 340,823) and moved no large org's share; 1,472 reviewer–CL pairs were post-merge only. Recent weeks keep rising slightly as late comments arrive (58% within 1 day, 89% within 14 days). Spam is left open (see Open questions) |
| 2026-11-03 | Per-person data derived from public data may be committed and published; replaces "per-person data stays local" | User's policy: all of it is already public on Gerrit |
| 2026-11-03 | Drop the fold of orgs with fewer than 5 reviewers per week into `Other`; every org is reported (only `gmail.com` still folds) | User's instruction; the fold existed for privacy, which the policy change made moot |
| 2026-11-03 | Reviewer leaderboard: `summaries/reviewer_weekly.json` (each week's top 50 per metric; names and orgs, no emails), shown on the public site | User asked for a top-50 reviewer view |
| 2026-11-03 | Add reviewer emails to `reviewer_weekly.json` (`emails` map) and show them in the leaderboard's hover card | User's request; Gerrit emails are public (ground rule 3) |
| 2026-11-04 | Hover cards name reviewers by email alone, in place of name and organization (leaderboard rows, the per-reviewer strip plot, the heatmap's "Most active" line); a name only when no email is known (`reviewerHandle`). Visible labels keep names | User's request: names are hard to search for, and an email is shorter and stands for both name and affiliation |
| 2026-11-03 | Web UI: a date range (default: where review and usage data overlap) replaces the week selector and applies to every section; `reviewer_weekly.json` holds every reviewer per (week, org), not just each week's top 50, so range totals (leaderboard, distinct reviewers per org) are exact | User found the week selector confusing and asked for accurate range totals within a few MB compressed (a year is about 1.2 MB, 0.35 MB gzipped) |
| 2026-11-03 | Keep every downloaded byte losslessly (`raw.sqlite` bodies, full NoteDb meta-ref history); reduce only in derived data | User's intention: allow richer analysis later and an informed review of the fetching, without re-fetching. Costs about 3 GB/year (`storage-design.md` §3.8) |
| 2026-11-04 | Clarified: the rule is "keep whatever we download", not "download everything". Fetching less (a narrower query, a leaner fetch) is welcome if it still gets what we need | User's clarification: the point is never to re-download something we already put server load on |
| 2026-11-04 | NoteDb repo tuned: `fetch.hideRefs=refs/meta/`, `fetch.negotiationAlgorithm=noop`, packed refs + multi-pack index (`cosh notedb-maintain`) | Fetches were dominated by git's *local* connectivity walk over every local ref (63 of 90 s sampled at 119k refs), and that grew with each week; the server side was the smaller part |
| 2026-11-03 | Fetch comments via NoteDb `git fetch` in batches of 200, not REST `/comments` | Matches REST exactly on 856 of 856 CLs, with about 200 times fewer requests |
| 2026-11-03 | Defer the OWNER bit; plan to compute it from OWNERS files at the merge parent | The code-owners API uses the current OWNERS files, not those at review time |
| 2026-11-03 | Web UI: Vite + TypeScript, Chart.js only at runtime; the summary/Radar join runs in the browser (`web/src/data.ts`); tests use Vitest + puppeteer-core with the installed Chrome | Few dependencies, static GitHub Pages hosting, no generated files to commit |
| 2026-11-03 | Ratio axis: 1× in the vertical middle, linear 0–1 below and 1–max above | User's instruction; under- and over-contribution get equal visual weight |
| 2026-11-03 | Keep the 1× gridline highlighted but don't label or describe values above/below it as more/less than a fair share | User's instruction: the ratio is too rough an estimate, with too many other factors, for 1× to be a meaningful threshold |
| 2026-11-03 | Radar: `timeseries_groups/BROWSER`, human traffic, daily data aggregated to ISO weeks | See `radar-research.md` |
| 2026-11-03 | Keep Radar's `ChromeDerivative` in the Chromium denominator despite its 2026-09-09 jump | It may be real Chromium usage; the jump looks like Radar labeling previously unlabeled traffic, not taking share from Chrome (`radar-research.md`) |
| 2026-11-03 | Leave Radar's `ChromeDerivative` out of the value ratio's usage denominator for now (renormalize each org's share to the rest; `RATIO_EXCLUDED_BROWSERS` in `web/src/data.ts`); the usage chart still shows it. Replaces keeping it in | User's instruction: the 2026-W37 jump looks like a reporting change and is not yet explained |
| 2026-11-03 | The Chromium denominator includes Android WebView and all in-app browsers. `ChromeMobileWebview` → google.com, Facebook and Instagram → meta.com, Microsoft365 → microsoft.com, other in-app browsers → no org | User's instruction (replaces "WebViews and in-app browsers excluded") |
| 2026-11-03 | Exclude iOS from all Radar shares: subtract Radar's `os=IOS` browser series, weighted by iOS's share from `timeseries_groups/OS` | User's instruction: iOS browsers are all WebKit, so Chromium is barely used there. Radar can't exclude an OS directly (`radar-research.md` §2) |
| 2026-11-03 | Exclude brave.com from the ratio: no browser mapping in `config/org_browsers.csv`; the web UI lists it with usage "unknown" (`UNKNOWN_USAGE_ORGS` in `web/src/data.ts`) and explains why in a note | User's instruction. Radar has a `Brave` label but puts it at about 0.002% of Chromium usage (2025-W45..2026-W44 mean), roughly 1000× below Brave's real size (~100M MAU against ~3.5B Chrome users). Brave identifies itself only in `Sec-CH-UA`, so Radar evidently counts it as Chrome (`radar-research.md` §6) |
| 2026-11-03 | `fb.com` reviewers count as `meta.com` (`DOMAIN_ALIASES` in `cosh/orgs.py`), applied when `summarize` resolves orgs; fetched and derived data keep raw emails and need no re-run | User's instruction: Meta employees used fb.com addresses |
| 2026-11-04 | Keep the date filter and its per-week leaderboard data (`summaries/reviewer_weekly.json`); revisit client weight later (Open questions) | User's decision: the client is too small to worry about yet. On 2026-11-04 (38 weeks loaded) the page fetched about 400 KB gzipped (1.9 MB raw). `reviewer_weekly.json` was 257 KB of that, and one all-time total per reviewer would cut it to about 81 KB |
| 2026-11-04 | Gerrit links: the leaderboard links to `commentby:X -owner:X` plus the range's dates, not `reviewedby:X`. Each org segment in "Review by directory" (any tree level) links to `dir:D` + dates + `(commentby:A -owner:A) OR …` for that org's reviewers in the directory's subtree (top 100 by comments), from a new `summaries/area_reviewers.json` that the page fetches when the chart scrolls into view | `reviewedby:` isn't "reviewed by". Gerrit's `ChangeData.reviewedBy()` walks the messages newest-first and stops at the owner's latest message, so a CL drops out once its owner replies. Domain queries don't work for drill-down: `commentby:*@microsoft.com` matches nothing (no wildcards), and `commentby:microsoft.com` expands to every matching account and fails (906 terms, max 800). Regex `dir:^…`/`path:^…` is off on Chromium Gerrit, so `dir:` also matches the segments anywhere (`dir:content` hits `components/x/content/`), and dates can only bound when a CL last changed. The links are therefore supersets of the counted CLs |
| 2026-11-04 | Leaderboard: no "other organizations"; every org on it gets its own legend entry (with its reviewer count). Size selector (top 25 default, 50, 100, 200) and a "without google.com" toggle that fills the board from the other orgs; both in the URL (`lbn`, `lbg=0`) | User's request. Without google.com one view can hold about 30 orgs, more than the 8-colour palette, so the 8 orgs with the most reviewers get colours and the rest are named on their rows |
| 2026-11-04 | Addressed comments: an owner's stated agreement or intent to change the CL ("I'll rephrase this", "agree these are redundant") counts as addressed; a bare "Marked as resolved" after discussion is ambiguous. Production audit of 800 labels against Opus: precision 0.98, recall 0.99 (`comment-classifier.md`, "Production audit"), which the UI quotes | User's decision while adjudicating the audit; the other way would put precision at 0.94 |
| 2026-11-04 | Leave Android WebView (`ChromeMobileWebview`) out of the value ratio's usage denominator, like ChromeDerivative (`RATIO_EXCLUDED_BROWSERS` in `web/src/data.ts`), and credit it to no org (removed from google.com in `config/org_browsers.csv`); the usage chart and `chromium_share` still include it. Replaces crediting it to google.com | User's instruction: WebView is embedded by many different browsers and apps, so its usage can't be credited to any one org |
| 2026-11-05 | The UI always opens on addressed comments when any week is classified; before, it did so only when the whole default range was classified. A partly classified range shows its classified part with a note; no labels means review comments | User's instruction ("make addressed comments always the default"). The backfill had stretched the default range past the classified year, so it opened on review comments |
| 2026-11-04 | Leaderboard size selector gets "All" (`lbn=all`): every reviewer with a nonzero value in the range and org choice. The axis is sticky so the long board keeps its scale | User's request. `reviewer_weekly.json` (1.7 MB, already fetched at load for the leaderboard) holds every reviewer, so "All" needs no new data and no on-demand fetch |
| 2026-11-04 | Include brave.com again (brave.com → Brave in `config/org_browsers.csv`), reverting its 2026-11-03 exclusion; the usage card's note says Brave's usage is likely largely understated | User's instruction. Radar's Brave label is ~1000× below Brave's real size, but brave.com has essentially no reviews (no addressed comments, 2 comments and 2 reviewed CLs in 2023-W26..2026-W44), so the understatement doesn't affect the analysis |
| 2026-11-04 | One constant, `TOP_ORGS` (6, in `web/src/data.ts`), sets how many orgs the review charts name: the organization chart's series, the directory and heatmap legends, the per-reviewer rows, and the leaderboard and heatmap organization selectors. The selectors list those orgs, then "Other" (`lbo=*other`, `hm=*other`), which combines every org outside them. The value-ratio chart (orgs with a browser) and the per-org table (`TABLE_TOP_ORGS`) are unchanged | User's request: fewer named orgs, and a way to look at everyone else together |
| 2026-11-05 | The value charts (parity and ratio over time) show an org only when its browsers' mean weekly usage share over the selected range reaches `MIN_DERIVED_SHARE` (0.1%; `rangeChartedOrgs` in `web/src/data.ts`), the test the table and parity chart already used. Replaces the earlier rule (0.1% in any Radar week, whatever the range) and the same day's hardcoded amazon.com/alibaba-inc.com exclusion | User's decision. Amazon's Silk was above 0.1% in most of 2024–25 but averages 0.09% over the last 52 weeks, so it drops out of ranges within the last year. Over all of 2023-W26..2026-W44 (the default view once every week is classified) it averages 0.14% and Yandex 0.11%, so both show there. Alibaba's UC Browser is above 0.1% every week (0.30% mean over the last 52), so it stays |
| 2026-11-05 | **One org colour map for every chart, with 12 colours.** `orgColorSlots` replaces the separate ratio-chart and review maps: `--org-1..6` are six vivid hues for the 6 orgs with the most review comments over all the data; `--org-7..12` are the same hues muted, for the value charts' other orgs (samsung, meta, yandex, …) and then the next reviewers. No colour means two orgs any more | User's request: the ratio chart and "Review by organization" gave one colour to different orgs (samsung/intel, meta/igalia, yandex/bytedance), since 8 colours can't cover the 12 orgs the two want coloured. The user chose 12 colours over folding orgs into grey, accepting weaker CVD separation for the muted six |
| 2026-11-05 | The review charts name an org when it wrote at least `NAMED_ORG_MIN_SHARE` (0.25%) of review comments over the selected range, at most 8, so a legend never grows long (`namedOrgs` in `web/src/data.ts`), replacing the 2026-11-04 fixed `TOP_ORGS` (6). The set is decided by review comments whatever metric is selected, so switching metric doesn't reshuffle it; the same places use it (organization chart, directory and heatmap legends, per-reviewer rows, leaderboard and heatmap selectors and their "Other"). On the linear scale google.com is simply left out; no smaller org is promoted into its place | User's choice among options (share threshold, decided on review comments). Five orgs (Google, Microsoft, Intel, Opera, Igalia) have ≥0.4% in every range from 4 weeks to all 175; the next has ≤0.1% and changes with the range (ByteDance, Shopify, Datadog with 60 comments on 1 CL, a one-person domain), so a fixed 6th slot always showed a trivial org. A largest-gap rule fails (Google's dominance cuts after Microsoft), a per-metric activity rule fails on sparse metrics, and a minimum reviewer count would drop Opera (2 reviewers, ~1% of comments) |
| 2026-11-05 | **A named org without a colour is shown in grey, never folded into Other.** The review charts no longer require a colour to name an org: one over the 0.25% bar but outside the 12-colour map gets its own grey series (dashed in the organization chart), legend entry and row. A unit test on the committed summaries fails if any org named over 13+ weeks, or any value-chart org, lacks a colour, as the prompt to re-evaluate the palette after a data update | User's request: a new org contributing a lot must at least show up, and the fixed palette should be re-checked after major data updates. Before this, januschka.com, huawei.com and kernel.org were named in some 4-week ranges but hidden in Other |
| 2026-11-05 | **Org colours stay computed from the data, with no palette check.** The 12-colour map is worked out when the page loads (all-time review rank, then value-chart orgs), so a growing org takes a colour on its own and colours may shift when the data is updated. The real-data test that flagged orgs named in grey over 13+ weeks, and the CLAUDE.md step to act on it, are removed; a named org without a colour still shows in grey, never in Other | User's choice between a fixed org → colour list in config (kept stable by hand, with the test flagging when it needs updating) and a fully runtime map: runtime, accepting that colours may shift on data updates |
| 2026-11-05 | Exclude brave.com again (reverts the 2026-11-04 re-inclusion): no brave.com → Brave mapping, and the org table shows its usage as "unknown" and its ratio as "usage unknown" (`UNKNOWN_USAGE_ORGS` in `web/src/data.ts`), not "usage too small" | User's instruction: Radar's Brave label is ~1000× below Brave's real size, so its usage is unknown rather than small |
| 2026-11-05 | **The web UI names weeks by their dates, never by ISO week labels** (`2026-W44`) or as "ISO weeks", and captions don't repeat the selected range. Labels stay in URLs, data files and code. A browser test checks the page's text, hover titles and accessible names | User's instruction; a `2026-W14 to 2026-W44` label had crept back into the date picker's summary after the wording moved into `index.html` |
| 2026-11-06 | **cosh becomes a set of Chromium dashboards.** The value-ratio UI moves from `web/index.html` to `web/value.html`, titled "Chromium Open Source - Value Exchange". A new landing page `web/index.html` (no script; own sheet `web/src/home.css`) has an original illustration (no Chromium logo) and one card per dashboard. Vite builds both pages. The docs now describe more data sources: git history and bugs are planned, and each still needs approval before anything is fetched | User's instruction: generalize the repo to generate several dashboards from different Chromium data sources |
| 2026-11-06 | **Chromium git history fetched**: one bare clone of `chromium/src`, `main` only (`--single-branch --no-tags`), no dependencies, no working tree, **blob-less** (`--filter=blob:none`): every commit and tree, no file contents. In `data/private/git/chromium-src.git`: 1,861,715 commits (2001-08-24 .. 2026-11-06), 16.2M objects, 5.57 GiB packed. One connection under the extract lock, with cosh's `User-Agent` and `From` header. The server took about 6 min to prepare the pack and about 2 min to send it (~55 MiB/s), then 2 min of local delta resolution. Use it with `GIT_NO_LAZY_FETCH=1`, and with `log.mailmap false` set in its config, so no command fetches blobs one at a time (CLAUDE.md) | User's approval to fetch Chromium's git history (main only, chromium/src only). Blob-less because only the history is wanted: authors, dates, messages and files touched need commits and trees only. The server's pack estimate for the full repo was ~74 GiB, more than the 69 GB free on this shared disk; blob-less left 63 GB free |
| 2026-11-06 | **Path scope widened by OWNERS**: include `components/surface_embed/`, `chrome/browser/resources/webnn_internals/`, `chrome/browser/ui/webui/webnn_internals/` (added the same day on the user's request) and the `chrome/` accessibility directories (`chrome/renderer/accessibility/`, `chrome/browser/accessibility/`, `chrome/browser/ash/arc/accessibility/`, `chrome/browser/resources/accessibility/`, `chrome/browser/ui/{ash,aura,views,webui}/accessibility/`, `chrome/test/accessibility/ax_client/`) | User's instruction, after a search of OWNERS files at `main` for excluded directories with owners outside google.com and chromium.org (OWNERS blobs fetched for it; `extraction-v1.md`, Path scope). The accessibility directories include `ui/accessibility/OWNERS` (Microsoft owners); `surface_embed/` had 36% Microsoft review. Over 2025-W45..2026-W44: +1,160 in-scope comments, non-Google share 10.80% → 10.82% |
| 2026-11-06 | **Review-comment sentiment, aggregate only (ground rule 5).** `cosh.sentiment` collects human review comments with thread context but no identities, scores them with sandboxed Haiku (prompt `scripts/sentiment_prompts/v3.txt`) into `data/private/sentiment.sqlite`, and writes a monthly trend from a deterministic 5% sample to `summaries/sentiment_monthly.json` (3-month rolling points with 95% intervals). `praise` writes weekly per-person counts of praise given and received to `summaries/sentiment_praise.json`, attaching names only to comments scored as praise; `score --praise-only` scores just the comments with praise words, so a leaderboard can cover weeks that aren't fully scored. No tone figures by org | User's policy: publish as much as possible, but no public report points fingers at negative behaviour, the repo shouldn't make one trivial to build, and orgs get no tone figures. Praise may name people. The 5% sample (109k substantive comments, 2023-07 .. 2026-10) and the 3-month window cut the month-to-month wiggle in the mean about sixfold relative to a 1% monthly series |
| 2026-11-07 | **Review Tone dashboard** (`web/sentiment.html`, card on the landing page): the 3-year trend (mean, and glowing, angry and AI-friction shares, 3-month rolling with 95% bands), praise leaderboards (most given, most received; top 15) and sample comments. `samples` (`summaries/sentiment_samples.json`) draws 10 random praise comments (≥ +0.5, praise words, human recipient) with writer, recipient, date and Gerrit link, and 10 random grumpy ones (≤ −0.6, no URLs or handles) as text, score and month only, each passing a sandboxed screen (`screen_identifying`: no names, no accusations of misconduct, no specific tickets) and read before committing | User's request: sample praise and grumpiness, with CL links and names for the praise only. The +0.8 praise bar first tried gave only 3 comments in 8 weeks. The first screen let through an accusation of fraud and a dig at a specific ticket; the screen prompt now flags both |
| 2026-11-07 | **Patch-set pilot, 2026-W44**: every patch-set ref of the week's 7,645 closed CLs (36,179 refs) fetched blob-less with glob refspecs, 100 CLs per request under the extract lock. Transfer about 530 MB, 39 min; 96 MB on disk once packed on its own. Per-patch-set diffs (each patch set against its own parent, so rebases add nothing) need 123,177 distinct blobs, 113,452 for human-owned CLs. Fetching blobs by ID failed (2,000 IDs: 10 min of server time, then a 502), and a want-patch-set/have-parent fetch came back incomplete while `main` lacked blobs. Plan: fetch `main`'s blobs first, then patch sets with `main` as the have, so only blobs that never landed come over | User asked how much data comparing patch sets across a review needs |
| 2026-11-07 | **The Chromium clone moves to `~/projects/shared/chromium`** (argus's cross-project area) and gets full blobs (`fetch --refetch` without a filter). It stays a clean mirror of `main`. cosh's patch-set refs and their objects moved to a small repo at the old path, `data/private/git/chromium-src.git`, which reads `main` through git alternates. The fetch was one connection under the extract lock, 10:50–12:43. The server sent 27.9M objects, a 66.5 GB pack, at 5–24 MiB/s, then index-pack resolved 20.0M deltas locally (4 threads). Afterwards `rev-list --objects --missing=print main` finds nothing missing. The clone is 69 GB, including the older 5.5 GB pack, most of which duplicates commits and trees now also in the new pack. It's left in place, because a repack needs about 66 GB of scratch space. The clone stays bare: other projects that need files borrow its objects with `git clone --shared` (`~/projects/shared/README.md`). With `main`'s blobs local, W44's patch-set diffs lack only 43,095 of their 123,177 blobs (41,046 for human-owned CLs), the versions that never landed. A patch-set fetch with `main` as the have would now bring exactly those; not done yet, it needs approval | User's instruction: a 70 GB download should be shareable across projects |
| 2026-11-07 | **Ground rule 5 relaxed: the code may name people, our pages never do for negative tone.** `cosh.sentiment_people` (identities on every collected comment) and prompts v1/v2 are now public. The Review Tone page gains the last two months in full (tiles, week-by-week table, score distribution), "who makes whom happy" (CL authors who draw glowing comments from many reviewers, and vice versa: counts only), an anonymous AI-friction list (text, month, role; 313 of 535 flagged comments shown after the screen and length/link filters) and the prompt. The praise and happy boards switch between all scored weeks and the past month (last 4 weeks), top 15 or top 100 (shorter when fewer people qualify). `cosh.sentiment_recent` writes `summaries/sentiment_recent.json` | User's instruction: "it's ok if it's easy for others to modify it to point out specific people, we should just never do so in our UI". Gold sets and per-comment model reasons stay out of the repo, since they tie negative labels to specific comments |
| 2026-11-07 | **Patch-set fetch timing test**: 4 full (no filter) fetches of random W44 CLs into a new repo, `data/private/git/chromium-patchsets.git` (borrows `main` from the shared clone; the pilot repo already holds W44's commits, so git would skip them there). Glob refspecs, extract lock, 15 s apart, `scripts/patchset_fetch_timing.py`, logs in `data/private/patchset-timing-20261107*`. 100 CLs: 25 s and 29 s; 300: 92 s; 1,000 CLs (4,608 patch sets): **72 s**, 155 MiB. Of the 72 s, about 23 s is listing refs and negotiation (11 s of `ls-refs` alone for 100 CLs), 17 s the server counting objects, 21 s transfer at 5–7 MiB/s. The time per request is mostly fixed, so 1,000 CLs per request is about 4× faster per CL than 100. Nothing reachable from the 7,016 new refs is missing: every unlanded blob came over. Git sent `main`'s tip as the have, but the server excludes only what's in each patch set's parent tree, so it re-sent blobs and trees that landed later: `repack -a -d -l` shrank 245 MB (69k objects) to 67 MB (12k objects), about 9.5 KB per patch set. That repack took 4.6 min of local CPU. Extrapolated by patch-set count, untested on old weeks: all 3.45M patch sets ≈ 15 h of fetching, ≈ 120 GB over the wire, ≈ 33 GB on disk after repacking; CLs with human review (2.0M patch sets) ≈ 9 h, ≈ 70 GB, ≈ 19 GB. Arrival is ~3.7× the final size, so it needs a repack every ~30 GB. Untested idea for less wire: also send each merged CL's landed `main` commit as a have | User approved a timing test of 3–4 fetches after asking why this isn't as fast as a clone |
| 2026-11-07 | **Fetch every patch set of every reviewed CL, with blobs** (`python3 -m cosh patchsets --go`, `cosh/patchsets.py`): CLs with a comment from a human other than the owner, 282,235 CLs and 1,996,572 patch sets over all fetched weeks, into `data/private/git/chromium-patchsets.git` (reftable refs; `fetch.hideRefs` keeps our own refs out of negotiation and the connectivity check). Newest first, at most 1,000 CLs or 5,000 patch sets per fetch, 2 s apart, extract lock, resumable from the refs present plus `cosh-fetched.txt`. A smoke run of 3 fetches took 90–141 s each (about 13 h for all 400), brought 869 MB and repacked (`repack --geometric=2 -d -l`, 251 s) to about 20 KB per patch set, twice the W44 sample, so the full set is likely about 40 GB on disk. Nothing reachable from the 23,767 patch-set commits was missing afterwards. Full run started 20:58 UTC, log `data/private/patchsets-reviewed-20261107T2058.log` | User's instruction after the timing test: "Do the fetch for all the reviewed CLs only" |
| 2026-11-07 | **Landed commits as extra haves don't help.** Why the server re-sends objects already on `main`: it excludes only what's in each patch set's parent tree, so files and directories that landed later come again (about 65% of the bytes). A/B on the same 300 merged, reviewed 2025-W20 CLs (3,850 patch sets): `main`'s tip as the have (50 haves sent) and each CL's landed commit as an extra have (976 sent) gave byte-identical results, 39,801 objects and 125.34 MiB, with 1.27M objects counted on the server both times (113 s and 89 s). Fetching into the shared clone wouldn't help either: the server decides from the haves, not from where we store things. So the copies are dropped locally by `repack -l`. The disk was grown to 466 GB, so the run restarted at 21:38 UTC with `--repack-gb 1000`: no repacks until the end (or under 25 GB free), so fetches never wait on them. The 300 test CLs were copied locally into the real repo and the scratch repos removed | User asked whether the re-sent copies could be avoided and suggested deferring repacks once the disk was grown |
| 2026-11-07 | **Committer status from the listings we hold.** `derive` fills a new `committers` table: an account is a committer if Gerrit lets it vote Code-Review (`permitted_voting_range` on any listing), and not one if it lacks a range on an open or abandoned CL. Newest listing wins. It is the status when the listings were fetched (Nov 3–5), used for comments of every date. Last year: 98.7% of non-bot comments by committers, 0.9% by non-committers, 0.4% unknown. Details in `docs/committers.md` | User's choice of the snapshot over vote-dated status: about 1% of last year's comments may be misplaced (2.5% over 3 years, former committers). Spam comes from non-committers |
| 2026-11-07 | **Commits: a fifth Value Exchange metric, credited to the git author** (`docs/commits.md`). `cosh commits` (and the end of a full `derive`) reads `main`'s first-parent history from the local shared clone, offline, into derived.sqlite's `commits` and `commit_dirs` (about 1 min). A commit is a bot's if its CL is bot-owned or its git author matches `config/bots.txt` (a WebLayer builder authored 739 commits on human-owned CLs). `summarize` adds `commits`, `authors` and `share_commits` to `org_weekly` and writes `author_weekly.json`, `area_commits.json` and `area_authors.json`, which the page fetches only for Commits or Ratio (+31 KB gzipped on every visit; 1.8 MB, then 3.4 MB for links, on demand). Sections are renamed to fit either side and no heading changes with the metric: Contribution by organization / by directory / by directory over time / per person, Leaderboard, Review depth (was "<metric> per review"). The organization chart gets a **Ratio** toggle (Off by default): the review metric over commits, addressed comments over commits under Commits. Named orgs now need 0.25% of review comments *or* commits | User's instruction: "use commit author, count commits, show it as a 5th button", rename sections so they suit either, keep section names stable, add the Ratio toggle |

## Status

**Done**
- Commits, the author-side metric (2026-11-07): `cosh commits`, the
  summaries and the Commits button and Ratio toggle on the Value Exchange
  page. See `commits.md`.
- Addressed comments (metric_version 7), the primary metric: thread
  structure in `derive`, the `cosh classify` step (Haiku via `claude -p`,
  `labels.sqlite`), the summaries and the UI. The whole year 2025-W45 ..
  2026-W44 is classified (0 pending). See
  `comment-classifier.md`.
- W44 extracted, validated and summarized (`summaries/`).
- `extract`, `extract-open`, `derive`, `summarize`, `radar` and `backfill`
  commands.
- metric_version 6 (review comments only, in the week written, open CLs
  included, path scope from `config/paths.txt`, patchset-level comments
  placed on their author's own inline-commented file): see
  `extraction-v1.md`, "Metric definitions".
- One-year backfill done 2026-11-04: 2025-W45 .. 2026-W44, batch size 200,
  duty cycle 0.5, 18.8 h. Its log is `data/private/backfill-52w-*.log`. The
  open-CL snapshot followed (28,117 CLs, 6,967 NoteDb refs).
- Backfill to 2023-07-01 (2023-W26 .. 2025-W44, 123 more weeks) done
  2026-11-05 about 03:16 UTC, after starting 2026-11-04 with `backfill
  --weeks 175 --newest 2026-W44 --go` (duty cycle 1.0 after week 1; two
  restarts, one after a crash on a merged CL listed without `submitted`).
  Logs: `data/private/backfill-3y-*.log`. The open-CL snapshot followed
  (2026-11-05 04:21 UTC, since 2023-06-26: 47,329 CLs, 5,383 NoteDb refs),
  then a full `derive` (774,616 CLs, 1,538,620 comments, 11.5 min) and
  `summarize`: the summaries cover all 175 weeks, 2023-W26 .. 2026-W44.
- Cloudflare Radar: daily data from 2023-07-01 to now, aggregated to weeks
  and months in `data/public/radar_browser_share.csv`. Browser names are
  verified against the real data (`radar-research.md`, "Findings").

- First web UI in `web/` (see `web/README.md`). It has the value-ratio chart
  (1× in the middle), review counts by org (those with ≥0.25% of review comments, `namedOrgs`, plus Other), Radar usage
  per browser with the ChromeDerivative note, review by directory (volume
  and org split, with the path scope described), week totals including AI
  comments, and a per-org table. The summary/Radar join runs client-side.
  Not yet deployed:
  the repo has no GitHub remote, so `.github/workflows/pages.yml` is untested.
- Reviewer leaderboard in the web UI: the top 25, 50, 100 or 200 reviewers
  (default 25) over the selected date range, optionally without google.com's
  reviewers. Every org on it is named in the legend (no "other"); orgs beyond
  the 8 palette colours are also named on their rows. `summarize` writes every reviewer's weekly counts
  to `summaries/reviewer_weekly.json`; the UI totals any range from it.
- Reviews per reviewer in the web UI (above Per review and the leaderboard): a strip plot,
  one dot per reviewer on a log axis and one row per org (top 10 by total,
  then Other), with a box over each row's middle half and a median line;
  clicking a dot opens the reviewer's weekly chart. A table gives each org's
  quartiles and top 10% share. It replaced a histogram (first one with an org
  selector, then grouped bars per org) that hid the differences: Google's and
  Microsoft's distributions are nearly the same, and what differs is the
  smaller orgs, best seen reviewer by reviewer. From `reviewer_weekly.json`.
- Per review in the web UI (just below Reviews per reviewer, above the
  leaderboard, same org rows):
  each reviewer's metric ÷ their reviewed CLs over the range, as a strip plot
  with quartile boxes, and a table with each org's quartiles and pooled
  figure. Under the Reviewed CLs metric it shows review comments per review.
  Reviewers need 3+ reviewed CLs. Under addressed comments it is addressed
  comments per reviewed CL, how much change a review drove, not an
  acceptance rate (addressed ÷ comments). From `reviewer_weekly.json`, so a
  dot is a reviewer's average, not a single review: the data has no
  per-(reviewer, CL) rows.
- Web UI date range: From/To dates (whole weeks, Monday to Sunday) plus presets, applied to
  every chart, the tiles and the table (see `web/README.md`).

**Next steps, in order**
1. Have the user validate the UI (`cd web && npm run dev`).
2. Try to get Radar history before 2023-07, whose requests returned HTTP 500.
   (The September 2026 `ChromeDerivative` jump has been investigated; see
   Decisions and `radar-research.md`.)
3. Push to GitHub and enable Pages (Settings → Pages → Source: GitHub
   Actions).
4. UI follow-ups: monthly granularity; an AI-comments-over-time view once
   there are more weeks; reduce and file the Chrome-on-macOS bug where the
   sticky metric bar's buttons jitter while scrolling ("Known browser bugs"
   in `web/README.md`).
5. After the backfill (done for 2023-W26 .. 2026-W44, 2026-11-05):
   - done: `extract-open`, then `rm -f data/private/derived.sqlite &&
     python3 -m cosh derive && python3 -m cosh summarize`;
   - check the UI across the full 175 weeks.
   - Re-run `extract-open` before each later summary refresh, so recent
     weeks stay complete.
   - Consider telling Chromium infra (infra-dev@chromium.org) before any
     further backfill.
   - Try `--batch-size 500` on a later run to see whether the per-CL cost
     drops.
6. **Addressed comments, the primary metric.** v1 built
   2026-11-04, and 2026-W44 is classified (2,626 Haiku labels; 55.9% of the
   week's in-scope comments are addressed). Design and first-run numbers:
   `docs/comment-classifier.md`, "Design"; research in `review-impact.md`.
   - **Next:**
     - done 2026-11-05: the year 2025-W45 .. 2026-W44 is classified.
       The run labelled 84,051 threads in 842 calls (25.6M Haiku tokens,
       $6.01 API-equivalent, 41 min with `--jobs 8`), so 0 comments are
       pending. 54–61% of in-scope comments are addressed each week (58.6%
       for the year);
     - done 2026-11-05: all 175 weeks (2023-W26 .. 2026-W44) are
       classified. The main run labelled 243,747 threads in 2,440 calls
       (74.8M Haiku tokens, $17.64 API-equivalent, about 2 h with
       `--jobs 8`); after the full rebuild, 1 thread was left and is
       labelled, so `classify --dry-run` reports 0 pending;
     - done 2026-11-05: it is always the default headline (once any week
       is classified);
     - let the regex skip "[AI]" / "Maestro AI:" prefixes on owner replies;
     - **reminder for the user: recheck the classifier with Gemini** as a
       second, non-Claude judge. In the 2026-11-04 audit (precision 0.98,
       recall 0.99; `comment-classifier.md`, "Production audit"), Opus both
       judged the 800 threads and adjudicated the disagreements, so errors
       that Claude models share were checked only by a 60-thread read.
       - **Run:** the same 800 threads are committed as
         `docs/audits/classifier-2026-11-04-threads.jsonl`.
         `classifier_audit.py prompts` writes 32 ready-to-paste prompts
         (production definition included); `collect` reads the saved
         replies, or `judge --cmd` runs a Gemini CLI. Then `compare` shows
         the agreement with the final labels and lists every disagreement
         to read. Commands are in `comment-classifier.md`, "Production
         audit";
     - after the next full `derive` on the main DB, rerun `summarize`.
   - **The original plan, for reference:**
   - **Scoring:** one point per non-author comment in a review thread that
     led to a change, credited to that comment's author and their org. No
     points in threads that ended without a change, and none to the CL
     author side.
   - **Build:**
     - `derive`: add `parent_uuid`/`root_uuid` to comments, a `threads`
       table and the regex result;
     - a separate `cosh classify` step (regex first, then Haiku via
       headless `claude -p` for the ~39% left, about 0.97 accuracy and
       ~28M Haiku tokens a year), writing to a new, never-deleted
       `data/private/labels.sqlite` (compact layout: under 20 MB for 3
       years);
     - `summarize` reads the labels if they're present.
   - **UI:** it must work without labels or with only some. The addressed
     metric shows only fully classified weeks; the other metrics are
     unaffected; the headline falls back to comments for ranges not yet
     classified.
   - **First run:** one week, with `/usage` checked before and after, then
     backfill a few weeks at a time.
   - **Defaults to confirm:**
     - co-authors who uploaded patchsets count as the author side;
     - comments after the author's last reply in a thread score nothing;
     - labels aren't committed.
   - **Visualizations** (principle: see the 2026-11-04 decision on
     acceptance rate; show what review drove, never a rate as a score):
     - done: a "How review threads are classified" box. It shows the
       outcome breakdown for the range's classified weeks (not per org) and
       expandable example threads with Gerrit links
       (`summaries/thread_examples.json`, loaded on first open);
     - done: clicking a reviewer on the leaderboard opens their weekly
       review comments and addressed comments over the picked range, with
       the Gerrit link. It needs no extra data: `reviewer_weekly.json`
       already holds every reviewer's weekly counts, including addressed
       (1.5 MB, 0.42 MB gzipped, for 151 weeks);
     - candidates: a coverage strip on the time axes; who-changes-whose-code
       (reviewer org × CL-owner org, addressed comments). Not acceptance
       rates.
   - **Explore: value of a comment.** Enrich the classifier to say roughly
     how much each addressed thread was worth: small for nits (style,
     naming, typos), larger for tests, docs and correctness fixes, and
     largest for major design or architectural shifts. Points could then be
     weighted, or shown as a size breakdown, rather than one per comment.
     - **Why:** a plain count rewards easy asks. Nits are 13% of threads
       but 23% of "Done" threads. A hand-read sample of 50 Done threads was
       about 34% style or cleanup, 20% docs or commit message, 14% tests,
       14% design or structure, and 18% correctness or bugs
       (`review-impact.md`, §5).
     - **To explore:**
       - a small size scale (e.g. nit / minor / substantive / major), or
         categories (style, docs, test, correctness, design) mapped to
         weights;
       - asking the same Haiku call for it, at a few more output tokens per
         thread;
       - the free `nit:` / `optional:` prefix signal;
       - how consistently models and people agree on size, on a labelled
         sample like the 400-thread set, before any weighting goes into
         the headline. Size is more subjective than "addressed or not".
     - **Storage:** store it as a small integer column in
       `labels.sqlite`, with its own definition version.
7. **Author/reviewer balance page** (`web/balance.html`; design and first
   2026-W44 measurements in `docs/balance.md`). Per CL: change complexity,
   review difficulty and rework, each against what is typical for the
   directories it touches. Waiting on the user's decisions listed there
   (per-person views, patch-set fetches beyond W44, mechanical CLs).
8. **Commits** (`docs/commits.md`): built 2026-11-07 as the fifth metric,
   with the Ratio toggle. Open: lines changed as a size-weighted variant
   (about an hour of local `--numstat`), and whether authorship also belongs
   on the balance page.
9. Later:
   - the OWNER bit;
   - years 2–5 of backfill;
   - other repos and hosts (v8, devtools-frontend and skia are listed in
     `gerrit-api-research.md` §6);
   - exact CL file lists for the path scope, from a blob-less fetch of
     `main`'s commits and trees, mapped to CLs by their `Reviewed-on:`
     footers (needs approval; would place the comments that are now
     `(no file)`, and patchset-level comments on the CL's real files).
     Low priority: those comments are mostly approvals (`extraction-v1.md`,
     "Why `(no file)` stays excluded"), and a batched `CURRENT_FILES`
     query would be far cheaper than a git fetch if it's ever wanted.

## Open questions

- **Comment spam (partly handled by metric_version 6).** Accounts that
  never commented inline are now dropped, and patchset-level comments count
  only alongside the author's own inline review, which removed most
  drive-by spam (`extraction-v1.md`, "Why reviewer-only patchset comments
  are unplaced"). Still open: spam from accounts that also commented
  inline, and post-merge noise. Some human comments are
  spam or noise, not review: people posting their own names, pasted LLM
  prompts, bare thank-yous. It shows most in post-merge comments, which now
  count in the headline (since metric_version 2) with no time window. Over 36 weeks,
  post-merge comments were 43% of "Other"'s (mostly gmail.com) pre-merge
  comment count, against 0.75–2.6% for real orgs. Candidate fixes: a window
  after `closed_at` (14 days keeps 89% of post-merge comments), dropping
  accounts that never comment before merge anywhere, or a content filter.

- Why exactly did Radar's `ChromeDerivative` bucket jump on 2026-09-09?
  Cloudflare hasn't said; the evidence points to a browser-labeling change
  (see `radar-research.md`). Could ask the Radar team.
- Radar history starts at 2023-07, but the review backfill could cover 5
  years. Can older Radar data be fetched another way, or should the ratio
  start at 2023-07?

- **Client weight (deferred 2026-11-04).** `reviewer_weekly.json` grows by
  about 5 KB gzipped per week, because it keeps a row per (week, reviewer, org)
  so the leaderboard can total any date range. The rest of the page is about
  145 KB gzipped (JS bundle 67 KB, Radar CSV 63 KB, `org_weekly.json` 11 KB).
  Estimates, assuming growth stays linear: about 330 KB for that file at 52
  weeks and about 900 KB at the approved 175 weeks (back to 2023-W26). If it
  gets too heavy, don't drop the date filter. Ship precomputed totals for the
  presets instead (about 80 KB for all four), and lazy-load the per-week file,
  or split it by year, only when someone picks a custom range.
  `area_reviewers.json` (the directory chart's Gerrit links) is bigger still:
  2.7 MB, 807 KB gzipped at 68 weeks over the 10,000-directory tree, against
  2.1 MB and 644 KB for `area_weekly.json`. It's fetched after the first render
  (until 2026-11-05: when the chart neared the viewport), so it holds nothing up. If it grows too heavy,
  options are to split it by year, keep reviewers only for the tree's upper
  levels, or fetch one subtree's slice when a row is expanded.

- **Top CLs in the heatmap's hover text (deferred 2026-11-04).** A cell's
  hover text names its most active reviewers, but the single biggest CL is
  often the real story (one abandoned CL, 7858502, was 126 of Microsoft's
  summer comments in `components/services/storage/`). Naming CLs needs new
  derived data: every (week, directory bucket, org, CL, comments) entry is
  about 200k rows for 68 weeks, roughly 2.4 MB (0.8 MB gzipped), the size of
  `area_reviewers.json`, and would be lazy-loaded the same way. Exact
  per-cell top CLs need every entry, not a per-bucket top 3, because cells
  sum many buckets. CL subjects for its ~119k CLs would add about 7 MB, so
  show CL numbers linked to Gerrit, not subjects. No new fetching.
- **Self-review vs other-review view (idea, 2026-11-04; unsure it's
  meaningful).** Split each org's review into comments on its own orgs' CLs
  (owner in the same org) and on other orgs' CLs, perhaps as a toggle or a
  paired series on the org chart. Prompted by Microsoft's drop after
  2026-W36: comments on Microsoft-owned CLs fell from 228 to 146 a week
  (W29–W36 vs W37–W44) while its review of Google, Intel and other CLs held
  flat, so the headline change was almost all self-review winding down with
  a few projects. Before building it, decide whether the split says anything
  about value: reviewing a colleague's CL in a shared codebase is still real
  review, and the ratio as defined credits both alike. It may be more useful
  as an explanatory breakdown than as a metric. Would need the CL owner's
  org (`changes.owner_account`, resolved as of the comment's day) in the
  summaries; no new fetching.
- Vivaldi has no Radar label at all and counts as Chrome, like Brave (which is
  now excluded with a note). Estimate them somehow, e.g. re-split Chrome's
  share with published MAU?
- Should the UI show monthly as well as weekly data? Weekly Radar data may be
  noisy.
