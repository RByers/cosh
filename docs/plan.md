# cosh plan, decisions and status

This is the entry point for anyone (human or a fresh Claude session) picking
the project up. Read this, then `README.md`, then `docs/extraction-v1.md`.

## Goal

For each organization *O* and period *t*, plot over time:

```
value_ratio(O, t) = O's share of Chromium review comments
                    / O's browser's share of Chromium-based browser usage
```

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
| 2026-11-04 | **Path scope** (`config/paths.txt`): exclude `chrome/`, `ios/`, `android_webview/`, `ash/`, `chromeos/` and `components/`, but include `chrome/browser/web_applications/`, `chrome/browser/webnn/` and `components/viz/`. Longest prefix wins. The value ratio, org chart, table and leaderboard count only in-scope comments; `area_weekly.json` and the "Review by directory" chart show every comment by directory, with a row for each re-included directory even when small | User's instruction (ash/, chromeos/ and components/ with components/viz/ added the same day): those trees are Google-specific products (Chrome, Chrome for iOS, Android WebView, ChromeOS), where review is mostly Google reviewing Google. The two exceptions are shared platform work with heavy Microsoft and Intel review. In a 60k-CL sample, `chrome/` held 41% of reviewer comments but only 7% of non-Google ones. Over a year, `components/` was 15.8% of comments and 1.85% non-Google; of its top ten subdirectories only `viz/` (11.6%) had real outside review (`extraction-v1.md`, Path scope) |
| 2026-11-04 | Place each comment on a file without fetching CL file lists: inline comments on their file, patchset-level comments on the CL's most-inline-commented file (owner replies included); comments on CLs with no inline comments are excluded as `(no file)` | No new fetching. Covers about 90% of comments (68% inline, 22% via the anchor). Exact file lists would need a blob-less git fetch of `main`, which isn't approved |
| 2026-11-03 | Report post-merge comments per org in summaries (`post_merge_comments`), excluded from the headline | User's instruction: post-merge review is still valuable; the headline measures review before landing. **Superseded by the next row** |
| 2026-11-03 | Post-merge comments count in the headline, however late (metric_version 2); `post_merge_comments` stays as the subset written after `closed_at` | User's instruction: post-merge comments that lead to changes in a later CL are real value; no time window, for simplicity. Over 36 weeks they were ~1% of comments (3,507 vs 340,823) and moved no large org's share; 1,472 reviewer–CL pairs were post-merge only. Recent weeks keep rising slightly as late comments arrive (58% within 1 day, 89% within 14 days). Spam is left open (see Open questions) |
| 2026-11-03 | Per-person data derived from public data may be committed and published; replaces "per-person data stays local" | User's policy: all of it is already public on Gerrit |
| 2026-11-03 | Drop the fold of orgs with fewer than 5 reviewers per week into `Other`; every org is reported (only `gmail.com` still folds) | User's instruction; the fold existed for privacy, which the policy change made moot |
| 2026-11-03 | Reviewer leaderboard: `summaries/reviewer_weekly.json` (each week's top 50 per metric; names and orgs, no emails), shown on the public site | User asked for a top-50 reviewer view |
| 2026-11-03 | Add reviewer emails to `reviewer_weekly.json` (`emails` map) and show them in the leaderboard's hover card | User's request; Gerrit emails are public (ground rule 3) |
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

## Status

**Done**
- W44 extracted, validated and summarized (`summaries/`).
- `extract`, `extract-open`, `derive`, `summarize`, `radar` and `backfill`
  commands.
- metric_version 5 (review comments only, in the week written, open CLs
  included, path scope from `config/paths.txt`): see `extraction-v1.md`,
  "Metric definitions".
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
- Reviewer leaderboard in the web UI: the top 50 reviewers over the selected
  date range. `summarize` writes every reviewer's weekly counts
  to `summaries/reviewer_weekly.json`; the UI totals any range from it.
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
   - Delete the obsolete `data/private/cosh.sqlite`.
   - Consider telling Chromium infra (infra-dev@chromium.org) before any
     further backfill.
   - Try `--batch-size 500` on a later run to see whether the per-CL cost
     drops.
6. Later:
   - the OWNER bit;
   - years 2–5 of backfill;
   - other repos and hosts (v8, devtools-frontend and skia are listed in
     `gerrit-api-research.md` §6);
   - exact CL file lists for the path scope, from a blob-less fetch of
     `main`'s commits and trees, mapped to CLs by their `Reviewed-on:`
     footers (needs approval; would place the ~10% of comments that are
     now `(no file)`, and patchset-level comments on the CL's real files).

## Open questions

- **Comment spam (open, deliberately untackled).** Some human comments are
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

- Vivaldi has no Radar label at all and counts as Chrome, like Brave (which is
  now excluded with a note). Estimate them somehow, e.g. re-split Chrome's
  share with published MAU?
- Should the UI show monthly as well as weekly data? Weekly Radar data may be
  noisy.
