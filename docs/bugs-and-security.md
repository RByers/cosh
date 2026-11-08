# Bugs and security fixes

Two sources that can tell the balance analysis (`docs/balance.md`) what review
was guarding against: the Chromium bug tracker (issues.chromium.org), and the
security fixes listed in Chrome Releases posts. Explored on 2026-11-08 with
the user's go-ahead to test the bug tracker and fetch the release posts.
Fetching the bug tracker at scale still needs approval.

## Bug IDs we already have (no fetch)

Commits on `main` carry `Bug:` and `Fixed:` footers. Since 2024-01-01
(first-parent, bots included):

| | |
|---|---|
| Commits | 496,745 |
| with a `Bug:` or `Fixed:` footer | 268,834 (54%) |
| distinct bug IDs | 131,890 |
| of which in `Fixed:` | 30,500 |
| in reverts | 8,592 |
| in relands | 4,596 |
| in reverts or relands | 9,156 |

## The bug tracker: what was tested

About 25 anonymous requests in all, serial, 1.5–2 s apart, with a generic
User-Agent and no identity. No throttling was seen: every reply was a 200,
403 or 405 in 0.2–1.2 s, with no 429, captcha or sign-in redirect. That is too
few requests to show the real limit.

| Option | Result |
|---|---|
| Issue page `issues.chromium.org/issues/<id>` | 200, 185 KB of HTML that loads data by script. Not useful directly. |
| `GET /action/issues/<id>` (the web app's JSON) | 200, about 100 KB per issue, with a `)]}'` prefix. It holds the full record: component ID, type, status, priority, severity, title, reporter (masked as `th...@gmail.com`), created/modified/resolved times, hotlists, custom fields (CVE, Security_Release, Introduced In, Milestone, OS, Flaky-Test, ReleaseBlock, vrp-reward, **Fixed By Code Changes** with Gerrit URLs), and the comment thread. Restricted bugs return **403** "Unsigned-in user does not have permission", as they should: 2 of 3 recent `Fixed:` IDs from October 2026 did. |
| `POST /action/issues/list` (the app's search) | 200 with JSON body `[null,null,null,null,null,["157"],["<query>",null,<page size>,"start_index:0"]]` (157 is Chromium's tracker ID). Queries use the tracker's search language: `id:(A \| B \| …)` fetched **50 IDs in one request** (2 MB, 0.8 s); `componentid:… created>…` works too. Results leave out restricted issues silently. |
| `GET` batch or list endpoints | 405 (POST only). |
| `/action/issues/<id>/events` | 404. |
| Old Monorail URL `bugs.chromium.org/p/chromium/issues/detail?id=` | 200 with a stub page that sends the browser to issues.chromium.org. There is no separate archive to read. |
| chromiumdash `fetch_releases` | 200 JSON. Release versions, branch positions and hashes, but no bugs. |
| BigQuery or a public export | None found. Not tested further (it would need credentials). |

**Visibility.** A sample of 50 `Fixed:` IDs from March 2025: one OR-search
returned 21. Of the 29 missing, 4 of the 5 checked one by one were 403
(restricted: security, or Google-internal), and 1 was visible but outside
tracker 157. So expect anonymous access to see roughly **40–60%** of the IDs
in footers. Security bugs open up about 14 weeks after their fix ships, so
older ones are visible.

**Field codes** (enum numbers in the JSON, inferred, check before relying on
them):
- core `[component, type, status, priority, severity, title, …]`;
- type 1 Bug, 2 Feature request, 4 Cleanup, 6 Vulnerability, 15 Task(?);
- status 1 New, 4 Fixed, 5 Verified, 8 Obsolete;
- priority 2 = P1, 3 = P2 (P0 = 1);
- severity 3 = S2.

### Recommendation

Use the anonymous **search endpoint with `id:(…)` OR queries of 50 IDs per
request**, serial at ≥ 1 s, and keep each response as fetched, losslessly
(`data/private/bugs/raw/`). Parse it into a small table: ID, component,
type, priority, severity, status, created/resolved, CVE, Introduced In,
Fixed By Code Changes, and whether the bug is a regression (hotlists or
labels). Rerun later for IDs that were restricted, as they open up.

- **Cost for 20k–50k IDs:** 400–1,000 requests, 7–17 min at 1 request/s,
  about 0.8–2 GB of responses. They carry descriptions, which we'd keep but
  never read with tools. Per-issue GETs would take 6–14 h and 2–5 GB, so use
  them only for single IDs.
- **Risks:**
  - The endpoint is internal and undocumented, so it may change shape.
  - The real anonymous rate limit is unknown. Start with a few hundred
    requests at 2 s and back off on the first 429.
  - Response text is untrusted: parse it with code only.
- **Needs the user's approval** (a new data source at scale).

## Chrome Releases security fixes (fetched)

`scripts/chrome_releases.py` (standard library only):

```bash
COSH_DATA_DIR=/home/rbagent/projects/cosh/data/private python3 scripts/chrome_releases.py all
```

- **`fetch`:** the Blogger JSON feed of chromereleases.googleblog.com from
  2020 on, 150 posts a page, 2 s apart. That was 26 requests for 3,507 posts.
  Raw pages are kept in `data/private/chrome_releases/raw/`; a rerun fetches
  only pages it lacks (or everything with `--refresh`).
- **`parse`:** extracts both layouts:
  - `[$reward][bug] Severity CVE-…: title. Reported by … on date` (prose);
  - `bug Severity CVE-… title` (table rows).
  
  The result is `security_fixes.json`, one record per CVE (first listing,
  plus every post it appeared in). The CVE lines left unparsed (316) are
  ChromeOS kernel advisories and "exploit exists in the wild" notes, which
  aren't Chromium fixes.
- **`join`:** finds commits on `main` (first-parent, since mid-2019) whose
  `Bug:`/`Fixed:` trailers name a security bug, with each commit's main
  1- and 2-level directory by changed lines. It writes
  `fixing_commits.json` and `summary.json`. It streams git's output, because
  whole commit messages since 2019 didn't fit in memory.

### Figures (2026-11-08)

- 5,607 CVEs (5,606 bug IDs). 4,619 bugs (82%) matched 5,924 fixing commits
  on `main`, including 186 reverts and 106 relands.
- The share of each year's bugs with a matching commit:

  | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
  |---|---|---|---|---|---|---|
  | 76% | 79% | 83% | 80% | 56% | 70% | 86% |

  The rest were fixed in other repos (V8, Skia, ANGLE) and reach `main`
  through `DEPS` rolls, so a CL's footer names the roll, not the bug.
- **CVEs per year:**

  | | Critical | High | Medium | Low | Total |
  |---|---|---|---|---|---|
  | 2020 | 4 | 141 | 97 | 48 | 290 |
  | 2021 | 4 | 193 | 116 | 37 | 350 |
  | 2022 | 7 | 198 | 143 | 32 | 380 |
  | 2023 | 5 | 119 | 103 | 35 | 262 |
  | 2024 | 5 | 142 | 78 | 23 | 248 |
  | 2025 | 4 | 85 | 65 | 41 | 195 |
  | 2026 (to Nov 8) | 223 | 1,331 | 1,538 | 790 | 3,882 |
- **The 2026 jump is real, not a parsing artefact.** From March 2026 the
  posts list hundreds of CVEs a month: 1,017 in June and 731 in October.
  3,017 of 2026's are credited "Google", and others are credited to
  AI-assisted research (e.g. "(Anthropic)", "OpenAI Codex Security"). This
  looks like AI-driven vulnerability discovery, and it is a large shift in
  the security workload that 2026's review and fix CLs carry.
- **Fixing commits by main directory:**
  - top level: `chrome/` 1,450, `third_party/` 1,131, `content/` 779,
    root 554 (mostly `DEPS` rolls), `components/` 505, `ui/` 203, `ios/` 201,
    `gpu/` 181, `media/` 180, `services/` 151;
  - two levels: `chrome/browser/` 1,166, `third_party/blink/` 986,
    `content/browser/` 716, `gpu/command_buffer/` 166, `ios/chrome/` 149.

## What this would add to the balance analysis

- **Review depth against risk.** Directories with many security fixes
  (`content/browser`, `third_party/blink`, `gpu/command_buffer`) can be
  compared with leaf UI, like for like, on load index, first-review wait
  and approver tenure. Does review stay deep where the risk is, as CLs grow?
- **Security-fix CLs as their own class.** Their review (threads, rounds,
  latency, who approves) in 2026, when their number jumped about fifteen-fold,
  against 2023–25. This is a direct new load on reviewers, separate from
  authors using AI to write ordinary code.
- **Regressions and post-land fixes** (with bug metadata, if approved): bugs
  marked as regressions with a `Fixed:` CL, traced back to the CL that
  introduced them (Introduced In, revert links), by era and by the original
  CL's review load index. That turns "reverts didn't rise" into "did
  regressions rise?".
- **Rework from the bug side:** `Fixed By Code Changes` lists every CL for
  a bug, so we can count follow-up CLs per bug by era.

Files: `scripts/chrome_releases.py`, and `data/private/chrome_releases/`
(raw, `security_fixes.json`, `fixing_commits.json`, `summary.json`). Probe
responses are in `data/private/bugs/probe/`.
