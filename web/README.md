# cosh web UI

A static site (Vite + TypeScript, Chart.js as the only runtime dependency),
served from GitHub Pages by `.github/workflows/pages.yml`.

It reads only committed, public files, which Vite emits as hashed assets at
build time:

- `summaries/org_weekly.json` and `summaries/weekly_totals.csv`
- `summaries/reviewer_weekly.json` (every reviewer's weekly counts: the
  leaderboard and distinct reviewer counts)
- `summaries/area_weekly.json` (every comment by directory and org, in scope
  or not, plus the path rules: the "Review by directory" section)
- `data/public/radar_browser_share.csv`
- `config/org_browsers.csv`

The join (value ratio = review share ÷ usage share) happens in the browser, in
`src/data.ts`. Radar rows used: `granularity=week`, `device=all`, `days=7`,
`chromium_share`. That share includes Android WebView (credited to Google)
and in-app browsers (Facebook and Instagram credited to Meta, Microsoft 365 to Microsoft), and excludes
iOS; the usage card's fine print says so. Orgs whose browsers have under 0.1%
of Chromium usage get no ratio.

The contribution metric (review comments by default, or review characters or
reviewed CLs, all counted from comments) covers only the paths
`config/paths.txt` includes. Python applies the scope in `summarize`; the page
only reads the result.

## Date range

One date range (From / To, plus presets) applies to every section. Each date
selects the ISO week it falls in, so a range is always whole weeks; the inputs
snap to that week's Monday and Sunday. The pickers span every week any data
covers (Radar goes back to 2023), and the default is the range where review and
usage data both exist.

Over a range:

- Counts (comments, AI and post-merge comments, CLs) are summed.
- Review share = the org's summed count ÷ everyone's summed count.
- Usage share = the mean of the org's weekly usage shares, over the range's
  review weeks that have Radar data. Ratio = review share ÷ usage share.
- Reviewers are distinct people over the range, counted from
  `reviewer_weekly.json` (every reviewer, per week and org); a reviewer who
  reviewed for two orgs counts once in each org's row.
- Leaderboard totals are exact sums from the same file. A reviewer's org is
  the one most of their comments in the range resolve to.

## Layout

1. **Value ratio** per org per week in the range. 1× is the vertical middle: the
   lower half is linear 0–1×, the upper half linear 1×–max (`src/scale.ts`).
   Smoothing (default 4 weeks; also off or 12 weeks) plots a trailing running
   average: mean review share ÷ mean usage share over the weeks ending each
   week, using weeks before the range too (`smoothRatios` in `src/data.ts`).
   The usage denominator leaves out Radar's ChromeDerivative bucket
   (`RATIO_EXCLUDED_BROWSERS`), whose 2026-W37 jump is not yet explained.
2. **Review by organization**: weekly review comments over the range
   (smoothed like the ratio), one line each for the top 7 orgs and then
   "Other". A toggle switches from the default log axis to a linear axis with
   google.com left out entirely (the next-ranked org takes its slot).
3. **Review by directory** (`src/areas.ts`): every comment in the range, in
   scope or not, one row per directory for the selected metric: the 14
   largest, plus every directory an `include` rule brings back (e.g.
   `chrome/browser/webnn/`, shown even at 0), then the rest combined into an
   included and an excluded row. Each row has a bar for its volume on a
   shared scale (hatched and tagged "excluded" when the scope leaves it out),
   a 100% bar of its split across the top 7 orgs plus "Other", and the share
   not from google.com. For reviewed CLs, a CL with comments in two
   directories counts in both. A note lists the path rules
   (from the summary's metadata) and how comments are placed on files.
4. **Chromium browser usage** from Cloudflare Radar, per browser, over the range,
   with a marker and a note on the 2026-W37 ChromeDerivative jump.
5. Totals for the range, plus a table with every value shown in the charts.
6. **Reviewer leaderboard**: the top 50 reviewers by review comments over the
   range, one compact bar each, coloured by org.

The range, smoothing and review-chart scale are kept in the URL hash
(`#from=2026-W14&to=2026-W44&smooth=4`, plus `&rscale=linear` for the
linear review chart). Old `#week=2026-W44` links open that one week, and an
old `metric=` parameter is ignored.

## Commands

```
cd web
npm ci
npm run dev        # http://localhost:5190
npm run build      # -> web/dist
npm run preview    # serves web/dist at http://localhost:5191
npm test           # build + unit tests + headless Chrome tests
```

### Dev server ports

Ports follow `~/projects/argus-config/ports.md`. 5190 (dev) and 5191 (preview)
are cosh's user ports, forwarded to the laptop over SSH, with `strictPort` so
a clash fails loudly. Servers started under Claude Code (`CLAUDECODE=1`) get a
random port in 20000–39999 unless `DEV_PORT=user` is set. Use
`DEV_PORT=user npm run preview` to hand a server to the user. The browser
tests always use a random port in that range.

The browser tests use `puppeteer-core` with an installed Chrome
(`/usr/bin/google-chrome`, override with `CHROME_PATH`); they download no
browser. Run them with `SCREENSHOT_DIR=/some/dir` to also save light and dark
full-page screenshots. Vitest is capped at 4 workers, with test files run
serially.
