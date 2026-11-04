# cosh web UI

A static site (Vite + TypeScript, Chart.js as the only runtime dependency),
served from GitHub Pages by `.github/workflows/pages.yml`.

It reads only committed, public files, which Vite emits as hashed assets at
build time:

- `summaries/org_weekly.json` and `summaries/weekly_totals.csv`
- `summaries/reviewer_weekly.json` (the leaderboard)
- `data/public/radar_browser_share.csv`
- `config/org_browsers.csv`

The join (value ratio = review share ÷ usage share) happens in the browser, in
`src/data.ts`. Radar rows used: `granularity=week`, `device=all`, `days=7`,
`chromium_share`. Orgs whose browsers have under 0.1% of Chromium usage get no
ratio.

## Layout

1. **Value ratio** per org per week. Parity (1×) is the vertical middle: the
   lower half is linear 0–1×, the upper half linear 1×–max (`src/scale.ts`).
2. **Review by organization**: raw counts for the selected week and metric, with
   the top 7 orgs and then "Other".
3. **Reviewer leaderboard**: the top 50 reviewers for
   the selected week and metric, one compact bar each, coloured by org.
4. **Chromium browser usage** from Cloudflare Radar, per browser, with a marker
   and a note on the 2026-W37 ChromeDerivative jump.
5. Week totals, plus a table with every value shown in the charts.

The metric and week are kept in the URL hash (`#metric=cls&week=2026-W44`).

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
