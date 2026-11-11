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
- **Peers** ("Compare with"): all authors; the same tenure band (under 1, 1–2,
  2–5, 5–10, 10+ years since the first commit on `main`, at the median of the
  person's CLs in the period); Google, Microsoft or Igalia (the org most of the
  period's CLs are attributed to, `cosh/orgs.py`); everyone outside Google;
  or **the same experience in each directory**. A person counts among peers
  for a period with 6+ CLs and 3+ expected threads. The page shows the peers'
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
- **Comments**: every reviewer thread, newest first, with file, date,
  addressed or not, and a Gerrit link. Text excerpts (200 characters) are
  included for threads in the year whose comment text is collected for tone,
  2025-W45 .. 2026-W44 (`data/private/sentiment/comments-*.jsonl`); older ones
  link to Gerrit only.
- **Praise received** in that year: comments to the person on their own CLs
  from someone else scored glowing (≥ +0.4, `cosh.sentiment.GLOWING`), the
  share of all comments to them, the peers' median share (all authors or the
  same tenure, 20+ comments received), and the praise comments with links.

## Ground rules

- **Tone is praise only** (`docs/plan.md`, ground rule 5). Nothing written
  marks a comment, a person or a group as negative: comments carry an
  addressed flag and a praise flag, never a score. Orgs get no tone figures,
  so with an org peer group the praise section compares with all authors.
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
site): `peers.json` (about 0.5 MB) and `u/<key>.json`, one per person (4,009
people and 64 address stubs on 2026-11-11; 124 MB in all, 45 MB gzipped; the
largest file 0.6 MB). The `u/` folder is replaced on each run.

**Not committed yet.** `web/public/review-feedback/` is gitignored: 45 MB
gzipped per refresh is a lot to add to the repository's permanent history,
so publishing it on GitHub Pages waits for the user's decision. Until then the
page works wherever the folder has been generated (`npm run serve` in the
main checkout), and the browser tests serve a made-up person
(`web/test/feedback-fixture.ts`).

## Caveats

- Tenure counts from the first commit on `main`; earlier commits in a
  directory count only from 2017.
- Reviewer threads include any thread a non-owner started, including
  drive-by and gardening comments, as the feedback index does.
- Peer groups mix very different roles, teams and kinds of work. A high or
  low figure is a prompt to look at the comments, not a conclusion.
