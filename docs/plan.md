# cosh plan, decisions and status

This is the entry point for anyone (human or a fresh Claude session) picking
the project up. Read this, then `README.md`, then `docs/extraction-v1.md`.

## Goal

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
- The result is a static web UI on GitHub Pages that reads only
  `summaries/` and `data/public/radar_browser_share.csv`.

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
   - Identify ourselves with the contact address, `rick@rbyers.net`.
3. **Per-person data derived from public data may be committed and
   published** (user's policy, 2026-11-03). Gerrit reviews, names, emails
   and affiliations are already public, so per-reviewer summaries can go in
   `summaries/` and on the site.
   - `data/private/` stays gitignored because of its size (raw caches, NoteDb
     repos, rebuildable DBs), not for privacy.
   - Data that is *not* from a public source, such as manual employer
     guesses that aren't backed by a public record, still needs the user's
     approval before it's committed.
4. **Credentials:** `secrets.sh` (gitignored, mode 600) exports
   `CLOUDFLARE_API_TOKEN`. Load it with `source secrets.sh`, and never print
   or commit the token.

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

## Status

**Done**
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
- Backfill to 2023-07-01 (2023-W26 .. 2025-W44, 123 more weeks) started
  2026-11-04 with `backfill --weeks 175 --newest 2026-W44 --go`. It was
  restarted at duty cycle 1.0 after week 1; about 15 min/week, so ~31 h. Log
  in `data/private/backfill-3y-*.log`; rerun the same command to resume. When
  it's done, rerun `extract-open` (its `since` becomes 2023-06-26), `derive`
  and `summarize`.
- Cloudflare Radar: daily data from 2023-07-01 to now, aggregated to weeks
  and months in `data/public/radar_browser_share.csv`. Browser names are
  verified against the real data (`radar-research.md`, "Findings").

- First web UI in `web/` (see `web/README.md`). It has the value-ratio chart
  (1× in the middle), review counts by org (top 7 plus Other), Radar usage
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
- Review per reviewer in the web UI (above the leaderboard): a strip plot,
  one dot per reviewer on a log axis and one row per org (top 10 by total,
  then Other), with a box over each row's middle half and a median line;
  clicking a dot opens the reviewer's weekly chart. A table gives each org's
  quartiles and top 10% share. It replaced a histogram (first one with an org
  selector, then grouped bars per org) that hid the differences: Google's and
  Microsoft's distributions are nearly the same, and what differs is the
  smaller orgs, best seen reviewer by reviewer. From `reviewer_weekly.json`.
- Per review in the web UI (just above Review per reviewer, same org rows):
  each reviewer's metric ÷ their reviewed CLs over the range, as a strip plot
  with quartile boxes, and a table with each org's quartiles and pooled
  figure. Under the Reviewed CLs metric it shows review comments per review.
  Reviewers need 3+ reviewed CLs. Under addressed comments it is addressed
  comments per reviewed CL, how much change a review drove, not an
  acceptance rate (addressed ÷ comments). From `reviewer_weekly.json`, so a
  dot is a reviewer's average, not a single review: the data has no
  per-(reviewer, CL) rows.
- Web UI date range: From/To dates (whole ISO weeks) plus presets, applied to
  every chart, the tiles and the table (see `web/README.md`).

**Next steps, in order**
1. Have the user validate the UI (`cd web && npm run dev`).
2. Try to get Radar history before 2023-07, whose requests returned HTTP 500.
   (The September 2026 `ChromeDerivative` jump has been investigated; see
   Decisions and `radar-research.md`.)
3. Push to GitHub and enable Pages (Settings → Pages → Source: GitHub
   Actions).
4. UI follow-ups: monthly granularity; an AI-comments-over-time view once
   there are more weeks.
5. When the one-year backfill finishes:
   - run `python3 -m cosh extract-open` (open-CL snapshot, approved);
   - then `rm -f data/private/derived.sqlite && python3 -m cosh derive &&
     python3 -m cosh summarize`;
   - check the UI across the full year.
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
     - classify older backfilled weeks the same way when wanted, about
       0.5M tokens and under a minute a week: `python3 -m cosh classify
       --week W ...`, `--dry-run` first;
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
7. Later:
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
  2.1 MB and 644 KB for `area_weekly.json`. It's fetched only when the chart
  scrolls near the viewport, so it holds nothing up. If it grows too heavy,
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
- Vivaldi has no Radar label at all and counts as Chrome, like most of Brave
  (whose own label is largely understated; noted in the UI). Estimate them somehow, e.g. re-split Chrome's
  share with published MAU?
- Should the UI show monthly as well as weekly data? Weekly Radar data may be
  noisy.
