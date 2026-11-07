# Author/reviewer balance: design notes

Status: design and first measurements (2026-11-07). Nothing is built in
`derive`, `summarize` or the web UI yet. The page will be `web/balance.html`.
Everything here comes from data already on disk; nothing was fetched.

## The question

The user's note *Agents and Accountability of Authors and Reviewers*
([Google doc](https://docs.google.com/document/d/1Zwq7exQ52CK34nGY8PrnWniOui5B7lsGSveZgqBpiFw/edit?usp=sharing))
argues that agentic tools make CLs cheap to write but not cheap to review,
which moves effort from authors to scarce expert reviewers. It asks both
sides to keep the exchange proportionate:

1. Authors own the correctness and reviewability of their work.
2. Reviewers owe timely feedback.
3. Authors should learn from feedback, so their CLs need less review over
   time.
4. Reviewers should get a return on their time.

Among the author measures it suggests: how small the CLs are, and how many
land with few substantive changes.

To show that balance, the page needs three per-CL estimates, each compared
with what is typical for the code it touches:

- **Change complexity:** how big and hard the change is, before review.
- **Review difficulty:** how much reviewer effort it took.
- **Rework:** how much the CL had to change before it could land.

## Data available

| Source | What it gives | Coverage |
|---|---|---|
| `changes` (listing) | final insertions and deletions, patch-set count, created and submitted times | every CL, all 175 weeks |
| `comments`, `threads`, `labels.sqlite` | reviewer comments per file, threads, addressed or not | every CL, all 175 weeks |
| NoteDb meta refs | each upload's time, uploader, commit SHA and Gerrit's change kind (rework, trivial rebase, message only, no change); votes; attention-set changes with reasons; code-owner approvals listing the files each vote approved | every CL, all 175 weeks |
| Patch-set commits (`refs/patchsets/<CL>/<ps>`, blob-less) | per patch set, the files changed and their blob ids, so we can tell which files changed between two patch sets | **2026-W44 only** (the pilot, 7,639 CLs) |
| `main` history (blob-less now; full blobs being fetched, approved 2026-11-06) | files of each landed commit; reverts and relands; with blobs, per-file line counts and OWNERS files | all of `main` |

What we can't get without new fetching:
- **Line counts per file**, or between patch sets, need blobs. The full blob
  fetch of `main` covers each landed CL's final diff, but blobs that exist
  only in earlier patch sets are not on `main`.
- **Patch-set file lists beyond 2026-W44** need the patch-set commits for
  those weeks. The pilot measured about 530 MB transferred per week for
  commits and trees (57 MB on disk after repack). This needs approval.

## First measurements (2026-W44)

`scripts/balance_explore.py` computes the measures below for the 4,327
merged, human-owned CLs that closed in 2026-W44, all of which have their
patch sets locally. It runs in about 10 s. It reads no comment text and
writes no comment text.

```
COSH_DATA_DIR=<main checkout>/data/private \
  python3 scripts/balance_explore.py --week 2026-W44 --out <scratch>/balance-w44.jsonl
```

**Distributions per CL**

| Measure | p25 | p50 | p75 | p90 | p99 |
|---|---:|---:|---:|---:|---:|
| lines changed (insertions + deletions) | 17 | 68 | 203 | 461 | 1,971 |
| files | 2 | 3 | 7 | 13 | 46 |
| patch sets | 3 | 4 | 7 | 12 | 31 |
| rework uploads after the first review | 0 | 1 | 3 | 5 | 13 |
| reviewer threads | 0 | 1 | 3 | 6 | 20 |
| addressed threads | 0 | 0 | 1 | 4 | 15 |
| reviewers who commented | 0 | 1 | 1 | 2 | 4 |
| files edited after the first review (base unchanged) | 0 | 0 | 1 | 2 | 8 |
| hours from upload to first review comment | 5.6 | 23 | 81 | 194 | 1,141 |
| hours from first review comment to submit | 3.3 | 19 | 65 | 171 | 1,109 |

2,580 of the CLs (60%) got at least one reviewer comment. The rest landed
on a vote alone.

**Rank correlations (Spearman, all 4,327 CLs)**

| | ρ |
|---|---:|
| lines ~ files | +0.72 |
| lines ~ reviewer threads | +0.47 |
| files ~ reviewer threads | +0.36 |
| reviewer threads ~ addressed threads | +0.83 |
| addressed threads ~ rework uploads | +0.72 |
| addressed threads ~ files edited after review | +0.69 |
| lines ~ files edited after review | +0.43 |
| reviewer threads ~ hours from first review to submit | +0.54 |
| lines ~ hours from first review to submit | +0.31 |

**By size**

| Lines changed | CLs | Reviewed | Mean threads | Mean addressed | Files edited after review |
|---|---:|---:|---:|---:|---:|
| < 10 | 691 | 34% | 0.48 | 0.12 | 8% |
| 10–49 | 1,190 | 47% | 0.82 | 0.32 | 18% |
| 50–249 | 1,570 | 68% | 2.20 | 1.29 | 43% |
| 250–999 | 751 | 83% | 5.16 | 3.61 | 63% |
| ≥ 1,000 | 125 | 77% | 6.59 | 4.89 | 57% |

The ≥ 1,000 bucket is less reviewed than 250–999 because it holds
mechanical CLs: of the 35 CLs with ≥ 50 files, 12 got no reviewer comment
(one is a third_party/grpc import of 5,863 files).

**What the numbers say**

1. **Size explains only part of review effort, and the path explains about
   as much again.** For log(1 + threads), the share of variance explained
   by group means is 0.23 for the size bucket, 0.14 for the CL's main
   directory (2 levels), and 0.42 for the two together (inflated by small
   cells). At the same size, `content/browser/` CLs got more threads than
   `ios/chrome/` ones (1.57 vs 0.49 at 10–49 lines), and
   `components/autofill/` 8.4 at 250–999 lines against 5.2 for
   `chrome/browser/`. Baselines therefore need both size and path.
2. **Author habits show through.** After subtracting the (size, directory)
   mean, an owner's residual threads in odd-numbered CLs correlate
   r = 0.58 with their even-numbered ones (171 owners with ≥ 3 CLs in each
   half, one week). That is a stable trait, but it mixes the author with
   the reviewers they pick and the areas they work in.
3. **File-level rework from tree diffs works, and it agrees with the
   classifier.** For each file of the final diff, the script compares its
   blob with the patch set the first reviewer comment was written on. Over
   24,199 files in reviewed CLs:

   | File after review | Files | With an addressed thread | With only unaddressed threads |
   |---|---:|---:|---:|
   | unchanged | 15,823 | 60 | 207 |
   | edited, base unchanged | 2,926 | 1,617 | 69 |
   | edited, base also moved (may be only a rebase) | 3,869 | 795 | 116 |
   | added after review | 1,581 | 174 | 20 |

   98% of files with an addressed thread changed, and most files whose only
   threads were not addressed did not. 55% of the clean edits had an
   addressed thread on the file; the rest is the author's own iteration,
   in line with `review-impact.md` (only about 21% of post-review uploads
   tie to an addressed thread).
4. **Rebases are the main noise.** When a file's base also changed, a tree
   diff can't tell an edit from a rebase onto a newer `main`. Blobs would
   settle it, by comparing the two patch sets' diffs rather than their
   files. Until then, count only clean edits and added files.
5. **Reverts are visible in `main` alone.** October 2026 had 23,286
   commits, 421 reverts (`This reverts commit`) and 224 relands. A revert
   is the clearest sign that a CL landed before it was ready (principle 1),
   and it needs no new data.

## Proposed measures

Each measure is per CL, from data we have unless marked. Bot-owned CLs,
bot accounts and mechanical CLs (rule to be decided; see Open decisions)
are left out.

### Change complexity (the author's side)

| Measure | Definition | Data |
|---|---|---|
| **lines** | insertions + deletions of the final patch set | listing, now |
| **files**, **directories** | files in the final diff, and distinct directories (2 and 3 levels) | patch-set trees (W44), or the landed commit on `main` (all weeks) |
| **owner directories** | OWNERS files whose approval it needed, from the code-owner approval messages in NoteDb or OWNERS at the parent commit | NoteDb now; OWNERS blobs with the blob fetch |
| **new files** | files added | trees, now |
| **lines per file** | per-file insertions and deletions, so per-path size is exact | blobs of `main` (being fetched) |
| **share of tests, generated and vendored files** | by path patterns (`*_unittest.cc`, `*_browsertest.cc`, `web_tests/`, `tools/metrics/`, `third_party/<vendored>/`, golden files) | trees, now |

Lines stay the headline size. Lines ~ files is 0.72, so the file count adds
little except for the mechanical CLs, where it flags them.

### Review difficulty (the reviewers' side)

| Measure | Definition | Data |
|---|---|---|
| **threads** | reviewer-started threads, excluding bots | now |
| **addressed threads** | threads that led to a change (`comment-classifier.md`) | now |
| **comments**, **chars** | reviewer comments and characters, quotes removed | now |
| **reviewers** | distinct human reviewers who commented | now |
| **rounds** | times the CL went back to the author after review: owner rework uploads that follow a reviewer comment, counted once per batch | NoteDb, now |
| **reviewer wait** | time the CL sat in a reviewer's attention set, and time to first review | NoteDb attention set, now |
| **comment size** (later) | nit / minor / substantive / major per addressed thread, the "value of a comment" idea in `plan.md` | a classifier extension |

Threads is the headline. It tracks addressed threads at 0.83 and time to
land at 0.54, and it is where reviewer effort is visible.

### Rework (how much the CL had to change)

| Measure | Definition | Data |
|---|---|---|
| **rework uploads after review** | uploads Gerrit marked as rework, after the first reviewer comment | NoteDb, all weeks |
| **files edited after review** | files of the final diff whose blob differs from the first reviewed patch set, base unchanged, plus files added after review | patch-set trees: W44 now, other weeks need approval |
| **review-driven share** | of those files, the share with an addressed thread on them | trees + labels |
| **interdiff lines** | lines that differ between the first reviewed and final patch set's diffs, rebases removed | patch-set blobs: needs approval |
| **reverted** | a later `main` commit reverts it (within N days) | `main` history, now |

The first reviewed patch set should be the one the first *substantive*
reviewer thread was written on, not the first comment of any kind: a lone
"LGTM" on the final patch set would otherwise count as review with no
rework. The prototype uses the first comment; that refinement is next.

## Path baselines

Review comments are placed on files (inline comments on their file;
patchset-level ones on their author's most-commented file, as in
metric_version 6). So each measure can be split by directory, and each CL
compared with what is typical for the directories it touches.

- **Unit:** a (CL, directory) pair. Weight CLs equally within a directory,
  not files, so a 5,863-file import doesn't swamp `third_party/`.
- **Directories:** the same tree as `area_weekly.json` (10,000 busiest
  directories; rarer ones roll up into their nearest kept ancestor), so the
  page can share the drill-down tree.
- **Per directory and period:** the median and quartiles of lines per CL
  (in that directory), threads per CL, addressed threads per CL, and the
  share of its files edited after review.
- **Expected value of a CL:** for threads and rework, the mean over its
  directories (weighted by its lines or files in each) of the directory's
  typical value at the CL's size bucket, falling back to the parent
  directory when a cell has fewer than about 30 CLs. A CL's **review load
  index** is observed ÷ expected. Over many CLs, the sum of observed over
  the sum of expected is more stable than a mean of ratios.

## What the page could show

These follow the principles of `plan.md` (2026-11-04, "acceptance rate is
not a citizenship signal"): show where effort went, not scores that make
people avoid asking questions.

1. **The exchange over time:** reviewer threads per 100 changed lines, and
   the share of CLs landing with few substantive changes, project-wide.
   Watch whether agentic tools move them.
2. **By directory:** typical size, review load and rework, as a tree like
   "Review complexity by directory over time" on the Value Exchange page.
3. **Size vs review:** a scatter or binned chart of lines against threads,
   with the path baseline, so very large or very contested CLs stand out.
4. **Learning over time (principle 3):** for cohorts of authors by tenure,
   review load index by month since their first CL. Aggregate by cohort;
   see Open decisions for anything per person.
5. **Timeliness (principle 2):** time to first review and reviewer wait,
   by directory.
6. **Org view:** by the owner's org, review load index and reverts,
   alongside how much review each org gives (from Value Exchange).

## Open decisions for the user

1. **Per-person views.** Ground rule 3 allows per-person data from public
   sources, but "this author's CLs need twice the usual review" judges a
   person more directly than a review count does. Options: aggregate only
   (project, directory, org, tenure cohort); per-author figures shown only
   when someone looks themselves up; or full per-author tables. Proposed:
   start aggregate and decide per-person views as a separate step.
2. **Fetching patch-set commits beyond 2026-W44** (about 530 MB a week
   over the wire, blob-less), for file-level rework over more than one
   week. Without it, rework rests on Gerrit's rework-upload count, which is
   available for all weeks but counts uploads, not how much changed.
3. **Fetching patch-set blobs** for interdiff lines and rebase-proof
   rework, after the full `main` blob fetch finishes. The pilot measured
   123k distinct blobs for W44 (113k for human-owned CLs); fetching by
   blob id loads the server badly, so it needs the "truthful haves" fetch
   the pilot describes.
4. **Mechanical CLs:** exclude by rule (e.g. ≥ 50 files with no reviewer
   thread, vendored `third_party/` imports, generated-only diffs), or keep
   them and show them separately.
5. **How far back:** NoteDb measures (rework uploads, rounds, wait times)
   cover all 175 weeks now; per-file measures cover W44 until more patch
   sets are fetched.

## Next steps

1. Refine "first reviewed patch set" to the first substantive thread, and
   add rounds, reviewer wait and reverts to the script.
2. Build path baselines over W44 and check how stable they are week to
   week, using what can be computed for all weeks (lines from the listing,
   files from the landed commit on `main`, threads, rework uploads).
3. Once blobs of `main` are local: lines per file, so per-directory size is
   exact.
4. With the user's decisions above: derived tables in `derive`
   (`cl_metrics`, `cl_files`), summaries (`balance_*.json`), then the page.
