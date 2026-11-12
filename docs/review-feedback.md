# Review Feedback: a personal view of the feedback index

`web/review-feedback.html` lets anyone type an email address and study the
review feedback on that person's Chromium changes against their peers'. It is
a learning guide, and the page says so at the top: "This analysis is imperfect
and is intended as a learning guide only". It isn't linked from the landing
page yet, and it carries `noindex`.

## What it shows

For merged, human-owned, non-mechanical CLs on `main` that landed from
2023-07-01 to 2026-11-01 (the same set as the Review Balance page's feedback
index, `docs/balance.md` section 4; mechanical CLs from `mech.jsonl`):

- **The measure**, from three switches:
  - *Feedback:* every reviewer thread (a thread started by a human other than
    the owner), or only the threads the owner **addressed** (regex plus the
    Haiku labels in `labels.sqlite`, `docs/comment-classifier.md`).
  - *Adjusted for:* nothing (threads per CL), CL size (÷ the 2023–24 mean for
    the CL's size bucket, 10 log buckets), or size and directory (÷ the
    2023–24 mean for size × top 2-level directory, groups of 30+, else size
    alone). Size and directory with all threads is exactly the Balance page's
    feedback index: the script recomputes those norms the same way as
    `balance_growth.cl_residuals`, and its thread counts match the `cl`
    table's for every CL.
  - *Dates:* everything, a calendar year or a half-year.
- **Peers always have the same tenure**, because feedback falls steeply with
  it (about 1.7× under a year or under 50 earlier commits, against 0.6× at
  10+ years or 1,000+). Two selectors pick the group:
  - *Same tenure by:* years since the first commit on `main` (under 1, 1–2,
    2–5, 5–10, 10+); earlier commits on `main` (from 2017, reverts left out:
    under 50, 50–199, 200–499, 500–999, 1,000+); or **experience in each
    directory** (below). The band is taken at the median of the person's CLs
    in the period, so the over-time chart follows the person from band to
    band.
  - *Peers:* all authors, Google, or everyone outside Google (the org most
    of the period's CLs are attributed to, `cosh/orgs.py`).

  peers.json has a distribution per period, measure and group:
  `time:<band>:<org>`, `changes:<band>:<org>` and `dir:<org>`. A person
  counts among peers for a period with 6+ CLs and 3+ expected threads; a
  group of fewer than 10 (`min_peers`) gets no percentiles, which happens to
  most non-Google groups past 200 earlier commits. The page shows the peers'
  median and middle half and the share of peers with less feedback.
- **Directory experience.** Each CL is split over the 3-level directories its
  landed commit changed (`cl_dirs`, weighted by lines + files), and each
  reviewer thread goes to the directory of its file (patch-set and commit
  message threads, and files outside those directories, go to the CL's main
  directory). Experience is the owner's earlier commits on `main` touching that
  directory (from 2017, `balance-git.sqlite`), banded 0, 1–4, 5–19, 20–99,
  100+. Everyone's feedback is pooled per band; the "same experience" view
  divides a person's threads by the sum, over their CL-directory pieces, of
  expected threads × that band's pooled rate relative to everyone's. So 1.00×
  is typical *for the experience the person had in the directories they
  worked in*, which credits people who work across more of the codebase. A
  chart and table give the person's feedback per band against everyone's.
- **Directories**: CLs, threads, expected threads and earlier commits per
  directory; selecting one filters the comment list.
- **Comments**: every reviewer thread, newest first, with file, date and
  addressed or not. Threads whose text has been collected (every week in
  `data/private/sentiment/comments-*.jsonl`, 2025-W45 on today) get a
  200-character excerpt and a link to the comment itself; the others get
  neither, and link to their CL (their comment ids would be 29% of the data,
  2026-11-11).
- **Praise received** in that year: comments to the person on their own CLs
  from someone else scored glowing (≥ +0.4, `cosh.sentiment.GLOWING`), the
  share of all comments to them, the peers' median share (all authors of the
  same tenure in years, or in earlier commits when that is chosen, at the end
  of the year; 20+ comments received), and the praise comments with links.

## Ground rules

- **Tone is praise only** (`docs/plan.md`, ground rule 5). Nothing written
  marks a comment, a person or a group as negative: comments carry an
  addressed flag and a praise flag, never a score. Orgs get no tone figures,
  so with Google or outside Google chosen the praise section compares with
  all authors of the same tenure.
- **No completions, no browsing.** The input has `autocomplete="off"`, no
  datalist and no name. Data files are named by
  `sha256("cosh-review-feedback-v1:" + normalised address)[:32]`
  (`key` in the script, `personKey` in `web/src/feedback.ts`; unit tests check
  they agree), so the folder lists no addresses and the page finds only
  someone whose address you type. Normalising follows
  `balance_analysis.person`: lower case, `chromium.org` = `google.com`.
  Other addresses of the same person (from the identity merge) get a stub
  `{"see": <key>}`. The address never goes into the URL.
- Everything comes from public Gerrit and git data, so per-person files may be
  published (ground rule 3). Comment text is untrusted: the script copies it
  without a model seeing it, and the page renders it only as text.

## Generate

Offline, about 2 minutes and 3 GB:

```
I=<dir with first_commit.txt and mech.jsonl, as for scripts/balance_report.py>
COSH_DATA_DIR=<main>/data/private nice -n 5 python3 scripts/review_feedback.py \
    --first-commit $I/first_commit.txt --mech $I/mech.jsonl [--out DIR]
```

Output (default `web/public/review-feedback/`, which Vite copies into the
site), with `<key>` the hash of the person's address:

- `peers.json`: every peer group's quantiles per period and measure, and
  everyone's pooled feedback per directory-experience band.
- `u/<key>.json`: first commit, which half-years the person has files for,
  and praise received. Small (0.8 MB gzipped for everyone) and rewritten on
  every run. Each other address of the person is a stub `{"see": <key>}`.
- `<half-year>/<key>.json` (`2023H2` … `2026H2`): that half-year's CLs, with
  their directory splits, threads and excerpts, and the directory, file and
  org names listed once (`shard` in the script).

The page computes everything else from these, the same way the script does
for the peer groups: totals for any period, tenure, org, whether the person
counts among peers, the measures, and the same-experience measure (from
`peers.json`'s rounded `rel` per band). To keep the two in step, the script
rounds the norms and line shares where it computes them, and counts tenure
in whole days. `--check FILE` writes the script's values for 300 people;
on 2026-11-11 the page's matched all 54,126 of them to the last digit.

So a half-year's files don't change once it is over, as long as the inputs
don't (the 2023–24 norms, labels, mechanical list, identity merge and
collected comment text): git stores them once. Each run rewrites the
current half-year, `u/` and `peers.json`.

Sizes on 2026-11-11 (4,009 people, 64 stubs), gzipped file by file as git
stores them: 2.6–2.9 MB per half-year for 2023 H2 – 2025 H1, 4.8 MB for 2025
H2, 12.5 and 10.7 MB for 2026 H1 and H2 (those have the excerpts), 0.9 MB for
`u/` and `peers.json`: 40 MB in all, 110 MB unpacked. The script replaces
`u/` and every half-year folder on each run.

**Not committed yet.** `web/public/review-feedback/` is gitignored, so
publishing it on GitHub Pages waits for the user's decision. Until then the
page works wherever the folder has been generated (`npm run serve` in the
main checkout), and the browser tests serve a made-up person
(`web/test/feedback-fixture.ts`). The inputs used on 2026-11-11 are kept in
`data/private/review_feedback_inputs/`.

## Caveats

- Tenure in years counts from the first commit on `main`; earlier commits,
  on `main` or in a directory, count only from 2017, so people who were
  active before then are undercounted (most are in the top band anyway).
- Reviewer threads include any thread a non-owner started, including
  drive-by and gardening comments, as the feedback index does.
- Peer groups mix very different roles, teams and kinds of work. A high or
  low figure is a prompt to look at the comments, not a conclusion.
