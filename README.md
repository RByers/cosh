# cosh — Chromium Open Source Health

cosh measures how the organizations that depend on Chromium contribute back
to it, relative to how much they get out of it.

## The core metric: value ratio

For each stakeholder organization *O* and time period *t*:

```
value_ratio(O, t) = contribution_share(O, t) / derived_value_share(O, t)
```

- **Contribution share** is approximated by code review in Chromium that
  changed the code: *O*'s share of the **addressed review comments** written
  in the period.
  - **What counts:** comments in a review thread that led the CL's owner to
    change the CL, one point per comment to its author
    ([`docs/comment-classifier.md`](docs/comment-classifier.md)).
  - **How it's decided:** a thread counts if the owner replied "Done" or
    similar, or if Claude Haiku reads the thread as having led to a change.
  - **Weeks not yet classified** fall back to all review comments.
  - **Other selectable measures:** all review comments, review characters
    and reviewed CLs.
  - **Not counted:** reviews without a comment (a bare +1), since their value
    can't be judged. Only comments on the shared engine count: `chrome/`, `ios/`,
  `android_webview/`, `ash/` and `chromeos/` (Google's own products) and
  `components/` (mostly Chrome browser features) are left out, apart from two
  shared directories in `chrome/`, `components/viz/` and
  `components/services/storage/` (`config/paths.txt`). Each reviewer is
  attributed to an organization by email domain, plus a mapping table for
  exceptions such as `@chromium.org` accounts.
- **Derived value share** is approximated by browser usage from
  [Cloudflare Radar](https://radar.cloudflare.com/): *O*'s browser's share of
  all Chromium-based browser usage (Chrome for Google, Edge for Microsoft,
  Opera, Samsung Internet, Yandex, Brave, …). Brave's share is largely understated:
  it identifies itself only in the `Sec-CH-UA` header, so Radar counts most of
  it as Chrome. That doesn't matter here, since brave.com has essentially no
  reviews.

**Example:** Google writes 90% of the addressed review comments, and
Google Chrome has 70% of Chromium-based browser usage on Cloudflare Radar.
Google's value ratio is 0.90 / 0.70 = 9/7 ≈ 1.29. A ratio above 1 means an
organization contributes more than its usage share; below 1 means it
contributes less.

The main visualization plots each organization's value ratio over time.

## Pipeline

1. **Extract** review data from Chromium Gerrit
   (`chromium-review.googlesource.com`). This is throttled and cached so we
   put as little load on the server as possible.
2. **Store** one row per review comment, with its file, its thread and the
   week it was written (not the week the CL landed). Open CLs are included,
   so recent weeks aren't missing review on CLs that haven't landed yet. Raw
   responses and derived tables stay local.
3. **Classify** which review threads led to a change. A regex on the owner's
   first reply ("Done", "Fixed", …) settles about 60% of the threads the
   owner answered, for free. Claude
   Haiku, run headless with `claude -p`, reads the rest in batches. Labels
   are kept in `data/private/labels.sqlite` and are never deleted. This step
   is optional: everything else works without it.
4. **Aggregate** the in-scope comments into small per-org, per-period
   summaries (all comments and addressed comments), plus every comment by
   directory.
5. **Join** the summaries with Cloudflare Radar browser share.
6. **Visualize** the result in a web front end that reads only the summaries.

## Status

Review data from 2023-W50 to 2026-W44 has been collected so far; a
backfill to 2023-07 is in progress. Radar data covers 2023-07 onward. The
web UI is in `web/`. Addressed comments (metric_version 7) are classified
for 2026-W44 so far; more weeks are added with `cosh classify`. See
[`docs/plan.md`](docs/plan.md).

## Usage

The code uses the Python standard library only. Data goes in
`data/private/`, which is not committed because of its size. Summaries,
per-org and per-reviewer, go in `summaries/` and are committed.

```
python3 -m cosh extract --week 2026-W44   # throttled Gerrit fetch, cached and resumable
python3 -m cosh extract-open              # snapshot open CLs and fetch their comments
python3 -m cosh derive                    # build derived.sqlite from the cache (offline)
python3 -m cosh classify --week 2026-W44  # optional: Haiku labels for threads the regex doesn't settle
python3 -m cosh summarize                 # write summaries/org_weekly.{csv,json}
python3 -m cosh radar                     # Cloudflare Radar browser share (source secrets.sh first)
python3 -m cosh backfill --weeks 52       # plan only; --go fetches (resumable)
python3 -m unittest tests.test_derive tests.test_extract tests.test_radar tests.test_classify
cd web && npm ci && npm run dev           # web UI (see web/README.md); npm test for tests
```

## Docs

Design documents are in [`docs/`](docs/). Start with
[`docs/plan.md`](docs/plan.md) for the goal, rules, decisions log, status and next steps.

- [`docs/extraction-v1.md`](docs/extraction-v1.md): what is implemented,
  metric definitions, and open questions before the backfill.
- [`docs/comment-classifier.md`](docs/comment-classifier.md): the addressed
  comments metric. It covers the classifier, its measured precision and
  recall, its cost, storage (`labels.sqlite`) and how to run it.
- [`docs/review-impact.md`](docs/review-impact.md): the research behind it,
  on which review leads to a change and which signals detect that.

- [`docs/gerrit-api-research.md`](docs/gerrit-api-research.md): Gerrit API,
  counting reviews, owner detection, and keeping server load low.
- [`docs/radar-research.md`](docs/radar-research.md): Cloudflare Radar browser
  share: API, auth, Chromium classification, licensing, and joining with the review data.
- [`docs/storage-design.md`](docs/storage-design.md): schema, size estimates,
  and storage format.

## License

BSD 3-Clause; see [`LICENSE`](LICENSE).
