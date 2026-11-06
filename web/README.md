# cosh web UI

A static site (Vite + TypeScript, Chart.js as the only runtime dependency),
served from GitHub Pages by `.github/workflows/pages.yml`. It has one page
per dashboard plus a landing page; each is an entry in
`build.rolldownOptions.input` in `vite.config.ts`.

| Page | What | Script | Styles |
|---|---|---|---|
| `index.html` | Landing page: an illustration and one card per dashboard | none | `src/home.css` |
| `value.html` | Value Exchange dashboard (the rest of this file) | `src/main.ts` | `src/style.css` |

To add a dashboard, add its page and an `input` entry in the Vite config,
add a card in `index.html`, and add browser tests that open it. The landing
page's illustration is original: don't use the Chromium or Chrome logos.

## Value Exchange (`value.html`)

It reads only committed, public files, which Vite emits as hashed assets at
build time:

- `summaries/org_weekly.json` and `summaries/weekly_totals.csv`
- `summaries/reviewer_weekly.json` (every reviewer's weekly counts: the
  per-reviewer distribution, the leaderboard and distinct reviewer counts)
- `summaries/area_weekly.json` (every comment by directory and org, in scope
  or not, as a directory tree, plus the path rules: the "Review by directory"
  and "Review by directory over time" sections, and the organization chart
  when it shows one directory)
- `summaries/area_reviewers.json` (who wrote each directory bucket's comments:
  the Gerrit links and "most active" lines of both directory sections; fetched
  after the first render, so it holds nothing up)
- `data/public/radar_browser_share.csv`
- `config/org_browsers.csv`

Loading order: the header (title and intro) is static HTML, so it shows as
soon as the page arrives, with a "Loading…" note under it. `<main>` (the
controls and every section) stays hidden until all the files above except
`area_reviewers.json` have arrived; it's then revealed and rendered in one go,
so no empty chart boxes appear. `area_reviewers.json` is fetched after that
first render, and its arrival rebuilds the two directory sections with links.

The join (value ratio = review share ÷ usage share) happens in the browser, in
`src/data.ts`. Radar rows used: `granularity=week`, `device=all`, `days=7`,
`chromium_share`. That share includes Android WebView (credited to Google)
and in-app browsers (Facebook and Instagram credited to Meta, Microsoft 365 to Microsoft), and excludes
iOS; the usage card's fine print says so. Orgs whose browsers have under 0.1%
of Chromium usage get no ratio.

Addressed comments (comments in review threads that led the CL owner to
change the CL; `docs/comment-classifier.md`) is offered once some week is
classified with `cosh classify`. While it is selected, every section shows
only the classified weeks of the range, and a note under the metric picker
says so. It becomes the default once the whole default range is classified.

The contribution metric (review comments by default, or review characters or
reviewed CLs, all counted from comments) covers only the paths
`config/paths.txt` includes. Python applies the scope in `summarize`; the page
only reads the result.

The metric picker sits in a bar (`.metric-bar`) that sticks to the top of
the window (`position: sticky`), so the metric can be switched from anywhere
on the page. `scroll-padding-top` is set from the bar's measured height
(`--metric-bar-h`, kept current by a `ResizeObserver` in `src/main.ts`), so
anchor jumps land just below it.

### Known browser bugs

**Chrome on macOS: the stuck metric bar's buttons jitter while scrolling**
(found 2026-11-04, not yet reported or reduced; to follow up). On a Mac at
device scale factor 2, scrolling with the trackpad makes the toggle buttons
(Addressed comments, Review comments, …) jitter up and down a little, while
the "Contribution metric" legend in the same bar holds steady. Safari on the
same Mac is smooth. Nothing on the page moves the bar: it is plain
`position: sticky; top: 0`, and there are no scroll listeners.

What we know so far:

- Not reproducible in headless Chrome on Linux at 1x, 2x or 200% zoom, using
  wheel scrolling, `scrollTo` in ¼px steps (including with the bar's resting
  position forced to fractional offsets), or compositor-thread scroll
  gestures (`Input.synthesizeScrollGesture`) captured frame by frame. Every
  frame has the bar's text and border on the same device-pixel row. There,
  the bar gets its own composited layer, with a sticky position constraint.
- In the buttons, each `<label>` has `position: relative` and holds an
  `opacity: 0`, absolutely positioned radio stretched over it. Making the labels
  static and hiding the radios with a 1px clip instead (commit 0094ff6,
  reverted in f19167d) did not stop the jitter on the Mac.
- `will-change: transform` on the bar did not help on the Mac either. In
  headless Chrome it made things worse: during compositor scrolling the bar
  was drawn a device pixel low, with page content showing above it in about
  a third of frames, and its layer no longer reported a sticky constraint.
  So the bar has no `will-change`.

Next steps: reduce it to a minimal sticky bar with segmented radio labels,
check it in Chrome on macOS at 2x (trackpad, then mouse wheel), and file a
crbug with the reduction if it still reproduces.

## Date range

One date range (From / To, plus presets) applies to every section. Each date
selects the ISO week it falls in, so a range is always whole weeks; the inputs
snap to that week's Monday and Sunday. Week labels such as `2026-W44` are only
for the URL and the data: the page itself names weeks by their dates (see
"Text and styling"). The pickers span every week any data
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

## Text and styling

The page's wording lives in each page's HTML (`value.html`, `index.html`), so it can be reviewed and tweaked
there alone; presentation in `src/style.css` (`src/home.css` for the landing page).

- Fixed controls (the metric, smoothing and chart toggles, the range presets,
  the fixed select options, the tiles) are plain markup; the scripts only
  wire them up. The metric buttons also give each metric's name.
- Sentences that depend on the data (section subtitles, captions, notes) are
  `<template data-msg="…">` elements next to the element they fill, with
  `<slot name="…">` values and `data-if` conditions; `src/text.ts` renders
  them (`fill`, `msg`). The opening comment in `value.html` has the syntax.
- Short formats stay in the scripts: hover titles, chart tooltips and axis
  titles, legend counts such as `google.com (12)`, directory row names such
  as `3 more`.
- Name weeks and ranges by their dates, never by ISO week labels
  (`2026-W44`, `2026-W14 to 2026-W44`) or as "ISO weeks": `rangeDates` in
  `src/main.ts` gives `26 Oct – 1 Nov 2026`, `weekTitle` in `src/data.ts`
  gives tooltip titles, and a single week mid-sentence is `week of 26 Oct
  2026`. Labels stay in the URL, the data and the code. A browser test fails
  if one shows in the page's text, hover titles or accessible names.
- Captions don't repeat the selected range: the date picker shows it, and
  the axes and legends make it plain. Say "in the range" or "in this range".
- Scripts don't set inline styles. They set custom properties (`--color`,
  `--share`, `--fill`, `--at`, `--depth`, `--rows`, `--t`) that `style.css`
  turns into colours, widths and heights. Chart.js drawing options are the
  exception, though the charts take their colours and font from CSS.

## Layout

1. **Value ratio**: one dot per browser-owning org, its share of the
   selected metric (addressed comments by default) over the range against its
   mean usage share, both on log axes over the same decades in a square plot
   (`renderParityChart`). The diagonal y = x is a 1.0× ratio: above it, more
   review than usage share. Orgs with none of the metric in the range (e.g.
   samsung.com's addressed comments in some short ranges) still get a dot: as
   on the review chart, both axes then start a power of ten lower and that
   bottom y tick, labelled 0, holds them. Labels dodge each other and the
   dots. Same numbers as the
   table (`orgRangeShares` in `src/main.ts`); smoothing doesn't apply.
2. **Value ratio over time** per org per week in the range. 1× is the vertical middle: the
   lower half is linear 0–1×, the upper half linear 1×–max (`src/scale.ts`).
   Smoothing (default 4 weeks; also off or 3 months, i.e. 13 weeks) plots a trailing running
   average: mean review share ÷ mean usage share over the weeks ending each
   week, using weeks before the range too (`smoothRatios` in `src/data.ts`).
   The usage denominator leaves out Radar's ChromeDerivative bucket
   (`RATIO_EXCLUDED_BROWSERS`), whose 2026-W37 jump is not yet explained.
3. **Review by organization**: weekly review comments over the range
   (smoothed like the ratio), one line each for the top 7 orgs and then
   "Other". A toggle switches from the default log axis to a linear axis with
   google.com left out entirely (the next-ranked org takes its slot). The
   Directory field limits the chart to one directory and everything below it
   (`dirWeeklyCounts`): typed with or without the trailing slash, or picked
   from the 3,000 busiest. It then counts every comment there from
   `area_weekly.json`, in scope or not, and the subtitle says how much of it
   the rest of the page leaves out. For reviewed CLs, a CL with comments in
   two of its subdirectories counts in each.
4. **Chromium browser usage** from Cloudflare Radar, per browser, over the range,
   with a marker and a note on the 2026-W37 ChromeDerivative jump.
5. Totals for the range, plus a table with every value shown in the charts.
6. **Review by directory** (`src/areas.ts`, `dirRows` in `src/data.ts`):
   every comment in the range, in scope or not, as a tree for the selected
   metric. The top level lists the 20 largest top-level directories (plus
   `area` prefixes from `config/paths.txt`, such as `third_party/blink/`),
   then an "N more" row. Re-included directories such as `components/viz/`
   stay inside their parents. ▸ opens a directory into its subdirectories, plus a "rest of"
   row for files directly in it and subdirectories too small to keep, so
   children add up to their parent. Each level lists 20 entries, then
   "N more"; opening that lists the next 20 one level deeper (and another
   "more" if any are left). ▾ closes anything again; what is open isn't kept
   in the URL. Each row has a bar for its volume on a shared scale set by the
   top level, solid for the part in scope and hatched for the part the scope
   leaves out (a partly included directory, like `components/`, has both;
   each name is tagged "included", "excluded" or "mixed"), a
   100% bar of its split across the top 7 coloured orgs plus "Other", and the share
   not from google.com. For reviewed CLs, a CL with comments in two
   directories counts in each. A note lists the path rules (from the
   summary's metadata) and how comments are placed on files.
7. **Review by directory over time** (`src/heatmap.ts`, `heatGrid` in
   `src/data.ts`): the same drill-down rows against time bins of 1 week, 4
   weeks (default), 3 months (13 weeks) or 1 year (52 weeks), lined up
   with the range's end. The Organization selector picks every org, every org but google.com, or one org (the 25
   busiest in the range); rows are ranked by what it selects. With several
   orgs each cell is a small stacked column of the org mix, its height the
   cell's volume against the row's busiest bin ("Volume") or full height
   ("Share"). With one org each cell is shaded in that org's colour by its
   volume against the busiest cell, on a square-root scale, or by its share of
   the directory's review. A cell's hover text gives the numbers and the
   emails of its three most active reviewers; clicking it opens those reviewers' CLs in the
   directory and weeks on Gerrit (`gerritDirUrl`). Each directory row's
   "chart" button shows it in the organization chart. A table, so cells have
   row and column headers; the directory column stays put while the bins
   scroll sideways on narrow screens.
8. **Review complexity by directory over time** (`src/complexity.ts`,
   `complexityGrid` in `src/data.ts`): just above Per review, to show how
   review complexity varies across the codebase. The same table, month ticks
   and expandable directory rows as Review by directory over time (shared
   helpers in `src/heatmap.ts`). Each cell is the metric per review in that
   directory and time bin; under Reviewed CLs the metric is review comments,
   as in Per review. A review is one org's comments on one CL in the
   directory: area_weekly's `cls` column, summed over orgs. Cells shade from
   the surface to the accent colour, on a scale from the 5th to the 95th
   percentile of the shaded cells (`complexityScale`): the figures sit in a
   narrow band well above 0. Cells with under 10 reviews (`COMPLEXITY_MIN`)
   stay grey. Rows are ordered by reviews over the range, and each shows its
   figure over the whole range. Columns default to 3 months (`cxb` in the
   URL), as weekly figures rest on few reviews. Show: Complexity (the
   default) or Volume (`cxv=volume`), which shades each cell by its reviews
   against the busiest cell on a square-root scale, like the org heatmap's
   Volume, and totals rows in reviews: what the figures rest on. The legend
   is only the ramp; the grey cells are explained in the caption. It covers every directory,
   in scope or not, but leaves out `(no file)`: those comments are mostly
   sign-offs and a third of all reviews. Comments count in the week written,
   CLs in the week closed. From `area_weekly.json`; no extra data.
9. **Per review** (`orgPerReviewSpreads` in `src/data.ts`, the same
   `renderSpreadChart`, on a linear axis from 0): just above the per-reviewer
   spread and on the same org rows, each reviewer's metric over the range divided by their reviewed
   CLs (CLs they commented on), or review comments per review under the
   Reviewed CLs metric; the title follows (“Review comments per review”).
   Only reviewers with at least 3 reviewed CLs (`PER_REVIEW_MIN`) and a
   review comment count; under addressed comments those with none addressed
   sit at 0. The table gives each row's reviewers, quartiles and “All
   reviews”, the row's pooled total ÷ its reviews. Comments count in the
   week written and CLs in the week closed, so a range's edges are
   approximate. From `reviewer_weekly.json`; no extra data.
10. **Review per reviewer** (`orgSpreads` in `src/data.ts`,
   `renderSpreadChart` in `src/charts.ts`): a strip plot of each reviewer's
   total for the metric over the range, one dot per reviewer on a log axis,
   one row per org: the 10 orgs with the largest total, then everyone else
   (gmail.com included) as Other. Each row with at least 5 reviewers has a
   box over its middle half (25th to 75th percentile) and a line at the
   median. Hovering a dot gives the reviewer's email; clicking it opens their weekly
   chart, as on the leaderboard. A table under the chart gives each org's
   reviewers, quartiles, top 10%'s share and total. Reviewers with 0 of the
   metric are left out, except under addressed comments, where everyone who
   wrote a review comment counts and those with none addressed sit at 0.
   From `reviewer_weekly.json`; no extra data.
11. **Reviewer leaderboard**: the top 25 (or 50, 100, 200, or all) reviewers by review
   comments over the range, for every organization, all but google.com, or
   one organization (the 25 with the most review in the range), one
   compact bar each, coloured by org. Orgs with a colour get a legend
   entry; the rest are muted and named on their rows, not in the legend. Clicking a
   reviewer opens their weekly chart over the picked range: review comments,
   with addressed comments filled in for classified weeks. The chart comes
   from `reviewer_weekly.json` (no extra data) and has the link to the CLs
   they commented on, on Gerrit.
12. **How review threads are classified** (once some week is classified):
   one bar splitting the range's classified reviewer-started threads by how
   each was decided (owner's "Done", Haiku addressed, Haiku no change, no
   owner reply), and example threads per outcome with Gerrit links. The
   examples come from `summaries/thread_examples.json`, which is fetched
   the first time a list is opened. It never shows an acceptance rate:
   threads without a change aren't bad review (`docs/comment-classifier.md`,
   "UI principle").

**Org colours are worked out from the data, and the same in every chart.** One
map (`orgColorSlots`) colours orgs everywhere: the value charts and table,
and every review section (the organization chart, both directory charts,
the per-review and per-reviewer spreads, the leaderboard and the reviewer
chart). It has 12 colours, `--org-1..12` in `style.css`: six vivid hues for
the 6 orgs with the most review comments over all the data, then the same
six hues muted. The muted ones go first to the value charts' orgs without a
vivid colour, then to the next orgs by review comments. No two orgs share a
colour, and the range, metric and filters never repaint an org. An org the
review charts name (`namedOrgs`: at least 0.25% of review comments over the
range) but that has no colour is never folded into "Other": it gets its own
series, legend entry and row in grey, dashed in the organization chart so it
reads apart from "Other". With today's data that happens only in short
ranges (4 weeks or less), for small orgs such as januschka.com.

The map is computed when the page loads, from the data the page ships with,
so it is fixed for a given data build but not across builds: an org that
grows enough over all the data takes a colour on its own, and that can move
other orgs' colours. That is deliberate (user's choice, 2026-11-05) over a
hand-kept org → colour list.

The metric, range, smoothing and review-chart scale are kept in the URL hash
(`#metric=cls&from=2026-W14&to=2026-W44&smooth=4`; `from`/`to` are left out
while "All data" is picked, so that link follows new data, plus `&rscale=linear` for
the linear review chart, `&lbn=100` (or `&lbn=all`) for a longer leaderboard, `&lbo=<org>` for
its organization (`*-google.com` for all but google.com; old `&lbg=0` links
still work), `&dir=<path>` for the organization chart's directory,
and `&hm=<org>` (`*-google.com` for all but google.com), `&hmb=1|13|52` and
`&hmv=share` for the heatmap, and
`&lbr=<account id>` for the reviewer chart). Old `#week=2026-W44` links open that one week, and
an old `dirs=` parameter is ignored.

## Commands

```
cd web
npm ci
npm run dev        # http://localhost:5190 (landing page), /value.html (Value Exchange)
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
full-page screenshots, or with `CPU_THROTTLE=6` to slow each page down 6x,
like a GitHub Actions runner, to catch timing races that only show up there.
Vitest is capped at 4 workers, with test files run
serially.
