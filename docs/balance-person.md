# Private per-person balance profiles

A profile compares one person with peers of the same tenure, in the same
period, on the measures of the public Review Balance page. It is for the
user's own understanding of individual paths (examples of the cohorts and
clusters found in aggregate), **not for publication**.

## Privacy rules

- A profile names a person, so it lives only in `data/private/balance_people/`
  (gitignored) and in **private** claude.ai artifacts. It is never committed,
  never linked from the site, and never shared without the person's consent.
- All inputs are public (Chromium Gerrit and git), but a side-by-side
  comparison of one person with their peers is still sensitive. Percentiles
  describe activity, not quality or worth, and each page says so.
- Review tone (`cosh.sentiment`) is never included (ground rule 5).

## Generate

From the worktree or main checkout, with the inputs `balance_report.py` uses
(first-commit dates, OWNERS additions, AI markers, mechanical CLs, all from
`commits.sqlite`; see `docs/balance.md`, "Data and how it's built"):

```
COSH_DATA_DIR=<main>/data/private \
  nice -n 5 python3 scripts/balance_person.py \
    --person blundell@chromium.org \
    --person yoavweiss@chromium.org=yoav@yoav.ws,yoavweiss@google.com,yoav.weiss@shopify.com
```

- `--person email[=alias,alias]` names a person; aliases add addresses the
  identity merge misses (it already merges chromium.org/google.com, SVN-era
  addresses, and the Gerrit owner and git author of the same CL). Check a
  name first: `yoav@chromium.org` doesn't exist; that person commits as
  `yoavweiss@chromium.org`.
- One load (a minute or two, a few GB) serves every `--person`; run heavy
  jobs one at a time on argus.
- Output: `<out-dir>/<user>.json` (the numbers) and `<user>.html` (the
  page), default `data/private/balance_people/`.
- The broader AI marker (`data/private/ai_marked_broad.txt`, from
  `scripts/balance_ai.py`) and the clusters
  (`data/private/balance_clusters/people.json`, from
  `scripts/balance_clusters.py`) are used when present.

Publish each page as a **private** artifact (the Artifact tool, one per
person), and check it renders. The URLs of published profiles are kept in
`data/private/balance_people/artifacts.json`. On a rerun, update each one
by passing its URL, so links stay the same. To change only the layout,
rebuild the pages from the saved JSON without reloading the data:
`python3 scripts/balance_person.py --rerender [dir]`.

## What a profile shows

- **Facts:** first commit, tenure, first OWNERS file, first year with 60+
  approvals (a "regular reviewer"), newcomers mentored, AI-marked commits.
- **2017–2026 from git**, per year, against peers in the same tenure band
  (people with 6+ commits and approvals that year):
  - commits a month;
  - approvals given a month;
  - review share;
  - approvals of newcomers' CLs;
  - median lines;
  - directories touched.
- **Since mid-2023 from Gerrit**, per half-year:
  - their CLs' feedback index, hours to first review, lines changed after
    first review, and the share abandoned after review;
  - as a reviewer: CLs reviewed, median weekday response, threads per CL,
    and newcomer share.
- **Charts:** each puts the person's line over the peers' median, middle
  half and 10th–90th percentile.
- **Mentoring:** how many people who joined since 2017 had them among the top
  two approvers of their first ten CLs, and how many of those became regular
  reviewers, OWNERS or mentors.
- **In brief:** a few generated, factual sentences with percentiles. No
  judgements.
- **Terms:** wording follows the public Review Balance page, and each
  measure, fact and term links to the section that defines it on
  `https://cosh.rbyers.ca/balance.html` (`DASHBOARD` and `term()` in the
  script; the exemplars page uses the same helper). When the page renames a
  term or a section anchor, update the script and rerender. The clusters'
  "trajectory" is shown as a "path between patterns", since the page's
  "Growth trajectories" mean something else.

## Caveats

- Tenure counts from the first commit on `main`, so people who arrived with
  experience elsewhere (or worked in other repos) look newer than they are.
- Gerrit measures start in July 2023, and the 2020–23 backfill (running
  from 2026-11-08) will extend them.
- Approvals come from `Reviewed-by` footers (since mid-2017), so commenting
  without approving shows only in the Gerrit reviewer measures.
- Peer bands mix very different roles (TLs, area owners, part-time
  contributors), so a low or high percentile is a prompt to look, not a
  conclusion.

## Cluster exemplars

`scripts/balance_exemplars.py` writes one private page naming a few clear
examples of each activity pattern (people in that pattern for most of
2025–26, mid-range activity) and of each trajectory (the longest records).
It reads `data/private/balance_clusters/people.json`, so run
`scripts/balance_clusters.py` first (`docs/balance-clusters.md`).

```
COSH_DATA_DIR=<main>/data/private python3 scripts/balance_exemplars.py [--per 3]
```

Output: `data/private/balance_people/exemplars.html`, published as a
private artifact. Its URL is in `artifacts.json` under `exemplars`. The
same privacy rules apply as for profiles.
