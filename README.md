# cosh — Chromium Open Source Health

cosh measures how the organizations that depend on Chromium contribute back
to it, relative to how much they get out of it.

## The core metric: value ratio

For each stakeholder organization *O* and time period *t*:

```
value_ratio(O, t) = contribution_share(O, t) / derived_value_share(O, t)
```

- **Contribution share** is approximated by code review activity in Chromium:
  *O*'s share of review comments, reviewed CLs, or review characters written,
  across all reviews in the period. Each reviewer is attributed to an
  organization by email domain, plus a mapping table for exceptions such as
  `@chromium.org` accounts.
- **Derived value share** is approximated by browser usage from
  [Cloudflare Radar](https://radar.cloudflare.com/): *O*'s browser's share of
  all Chromium-based browser usage (Chrome for Google, Edge for Microsoft,
  Opera, Samsung Internet, Yandex, …). Brave is excluded: it identifies itself
  only in the `Sec-CH-UA` header, Radar counts it as Chrome, and so its usage is
  unknown.

**Example:** Google writes 90% of the review comments across Chromium, and
Google Chrome has 70% of Chromium-based browser usage on Cloudflare Radar.
Google's value ratio is 0.90 / 0.70 = 9/7 ≈ 1.29. A ratio above 1 means an
organization contributes more than its usage share; below 1 means it
contributes less.

The main visualization plots each organization's value ratio over time.

## Pipeline

1. **Extract** review data from Chromium Gerrit
   (`chromium-review.googlesource.com`). This is throttled and cached so we
   put as little load on the server as possible.
2. **Store** one row per review comment and per Code-Review vote, each in
   the week it happened (not the week the CL landed). Reviewed CLs are
   counted per CL, in the week the CL closed. Open CLs are included, so
   recent weeks aren't missing review on CLs that haven't landed yet. Raw
   responses and derived tables stay local.
3. **Aggregate** the rows into small per-org, per-period summaries.
4. **Join** the summaries with Cloudflare Radar browser share.
5. **Visualize** the result in a web front end that reads only the summaries.

## Status

One week (2026-W44) of review data and Radar data from 2023-07 onward are
collected, and a first web UI is in `web/`. A one-year review backfill
(2025-W45 .. 2026-W44) started on 2026-11-03. See [`docs/plan.md`](docs/plan.md).

## Usage

The code uses the Python standard library only. Data goes in
`data/private/`, which is not committed because of its size. Summaries,
per-org and per-reviewer, go in `summaries/` and are committed.

```
python3 -m cosh extract --week 2026-W44   # throttled Gerrit fetch, cached and resumable
python3 -m cosh extract-open              # snapshot open CLs and fetch their comments
python3 -m cosh derive                    # build derived.sqlite from the cache (offline)
python3 -m cosh summarize                 # write summaries/org_weekly.{csv,json}
python3 -m cosh radar                     # Cloudflare Radar browser share (source secrets.sh first)
python3 -m cosh backfill --weeks 52       # plan only; --go fetches (resumable)
python3 -m unittest tests.test_derive tests.test_extract tests.test_radar
cd web && npm ci && npm run dev           # web UI (see web/README.md); npm test for tests
```

## Docs

Design documents are in [`docs/`](docs/). Start with
[`docs/plan.md`](docs/plan.md) for the goal, rules, decisions log, status and next steps.

- [`docs/extraction-v1.md`](docs/extraction-v1.md): what is implemented,
  metric definitions, and open questions before the backfill.

- [`docs/gerrit-api-research.md`](docs/gerrit-api-research.md): Gerrit API,
  counting reviews, owner detection, and keeping server load low.
- [`docs/radar-research.md`](docs/radar-research.md): Cloudflare Radar browser
  share: API, auth, Chromium classification, licensing, and joining with the review data.
- [`docs/storage-design.md`](docs/storage-design.md): schema, size estimates,
  and storage format.
