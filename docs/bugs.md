# Bug-tracker metadata

Metadata of the Chromium bugs that commits on `main` name, from
issues.chromium.org. It lets the balance analysis (`docs/balance.md`) tell
what a CL was fixing: bug type, priority, severity, component, security
fixes, regressions and the CLs that fixed each bug. The user approved
fetching it on 2026-11-08. The exploration that led here is in
`docs/bugs-and-security.md`.

Code: `cosh/bugs.py`; tests: `tests/test_bugs.py` (no network).

## The source

- **issues.chromium.org** is Chromium's instance of the Google Issue
  Tracker (Buganizer). Chromium's tracker ID there is **157**. It replaced
  Monorail (bugs.chromium.org) in February 2024.
- We use the web app's own search endpoint, anonymously:
  `POST https://issues.chromium.org/action/issues/list` with the JSON body
  `[null,null,null,null,null,["157"],["id:(A | B | …)",null,50,"start_index:0"]]`.
  The reply is JSON behind a `)]}'` prefix line, holding up to 50 issues.
- **It is internal and undocumented.** Its shape may change without notice.
  The parser checks the shape of every reply and the fetch stops after three
  bad ones.
- **Anonymous visibility.** Restricted issues (security bugs before they
  open up, Google-internal ones) are left out of the reply without an
  error. Expect 40–60% of the IDs asked to come back. Security bugs open up
  about 14 weeks after their fix ships, so `--retry-missing` later picks
  up more.
- Search replies hold each issue's fields but **not** its description or
  comments. Each issue also carries the tracker's custom-field definitions
  (with the 1,259-entry component list), which is most of its ~100 KB;
  gzip takes that down to ~18 KB.
- **Monorail-era IDs** (below 1,600,000; crbug.com stopped near 1.53M) were
  renumbered in the migration, and `id:` doesn't find them. The old
  `bugs.chromium.org/p/chromium/issues/detail?id=<old>` page is a small stub
  whose script redirects to `issues.chromium.org/<new>`. `monorail` reads
  that stub, one request per ID, and `fetch` then asks for the new IDs.
  Old IDs that never existed in Monorail return 404.

## Which IDs

`python3 -m cosh.bugs ids` (offline) rebuilds the `wanted` table from:

1. `Bug:` and `Fixed:` footers of first-parent commits on chromium/src
   `main` since 2023-07-01 (the Gerrit analysis window), from the shared
   clone `~/projects/shared/chromium` (`git log` with
   `GIT_NO_LAZY_FETCH=1`; it never fetches);
2. every bug ID in `data/private/chrome_releases/security_fixes.json`
   (2020 on, `docs/bugs-and-security.md`).

Footer values are split on commas, semicolons and spaces. Accepted forms:
`123`, `chromium:123`, `crbug.com/123`, `crbug/123`, `https://crbug.com/123`,
`https://issues.chromium.org/issues/123` (and `g-issues.`), and the old
`bugs.chromium.org/p/chromium/issues/detail?id=123`. Skipped:

- `b:`/`b/`/`http://b/` and issuetracker.google.com IDs. They are
  Google-internal Buganizer bugs, almost all restricted; asking for the
  ~31k of them would cost ~600 requests for few visible bugs. They could be
  added later.
- Other projects' prefixes (`v8:`, `skia:`, `webrtc:`, `angleproject:`,
  `dawn:`, `chromedriver:`, `fuchsia:` …), which are other trackers.
- Numbers below 100,000 or above 10 digits (typos, `None`, `N/A`).

Counts on 2026-11-08:

| | IDs |
|---|---|
| wanted, all | 147,407 |
| in a footer | 145,486 |
| in a `Bug:` footer | 119,704 |
| in a `Fixed:` footer | 32,865 |
| security fixes | 5,606 |
| security fixes in no footer since 2023-07 | 1,921 |
| Monorail-era (to map first) | 21,264 |
| asked directly (`fetch`) | 125,896 |
| footer tokens skipped | 64,729 |

## Fetching politely

- **Serial**, one request at a time, at least `--interval` (default 2 s,
  never below 1 s) from the end of one request to the start of the next.
- **50 IDs per request** (the search's page size), newest IDs first.
- **Identity:** the usual cosh `User-Agent` and `From` header with the
  contact e-mail from `cosh/contact.py` (never hardcoded).
- **Stop rules:**
  - a captcha, sign-in or "unusual traffic" page (HTML instead of JSON, or a
    redirect off issues.chromium.org / bugs.chromium.org): stop at once;
  - HTTP 401/403 on the search, 400 or another 4xx: stop at once;
  - HTTP 429, 5xx or a network error: back off 5, 15, then 30 min, and stop
    if it still fails;
  - three replies with an unexpected shape in a row: stop.

  A stop exits with status 2 and a `STOP:` line in the log.
- **Lock:** `data/private/bugs/fetch.lock`, so two bug fetches never run
  at once. It is not `extract.lock`: that one serialises Gerrit and
  googlesource fetches, and this is a different host.
- **Resumable:** each request is logged and its IDs recorded in `asked`
  before the next one. A rerun asks only IDs never asked. A request that
  stopped half-way leaves its IDs unasked, so they are asked again.
- **`--retry-missing`** re-asks IDs that weren't visible and were last
  asked at least `--older-than` days ago (default 30).
- `--limit N` caps a run at N requests. Without `--go`, `fetch` and
  `monorail` only print what they would do.

## Storage

Everything is in `data/private/bugs/` (gitignored):

- `raw/list/<YYYY-MM>/<seq>.json.gz`: each search reply exactly as
  received (the gzip body the server sent; if it came uncompressed, gzip of
  it). Never stripped or truncated.
- `raw/monorail/<YYYY-MM>/<seq>.html.gz`: each Monorail stub, likewise.
- `bugs.sqlite`:
  - `wanted`: `id`, `bug_commits` and `fixed_commits` (first-parent commits
    naming it in each footer), `security` (1 if in security_fixes.json),
    `first_commit`, `last_commit` (committer dates). Rebuilt by `ids`.
  - `monorail_map`: `old_id`, `new_id` (NULL if the stub named none),
    `http_status`, `fetched_at`, `request_seq`.
  - `requests`: one row per HTTP request: `seq`, `kind` (`list` or
    `monorail`), `started_at`, `elapsed_s`, `http_status`, `final_url`,
    response `headers` (JSON), `request_body` (the query, so the IDs
    asked), `wire_bytes`, `body_bytes`, `file` (under `bugs/`), `n_asked`,
    `n_returned`, `outcome` (`ok`, `http`, `shape`, `blocked`, `net`).
  - `asked`: per tracker ID: `visible` (1 returned, 0 not), `first_asked`,
    `last_asked`, `times`, `request_seq`.
  - `bugs`: one row per visible issue, parsed by code from `raw/`.
    `python3 -m cosh.bugs parse` rebuilds it offline.

### `bugs` columns

Positions are in the issue list `i` and its core list `c = i[2]`.

| Column | From | Confidence |
|---|---|---|
| `id` | `i[1]` | certain |
| `tracker` | `i[41]` (157, sometimes null) | medium |
| `component_id` | `c[0]` | high |
| `component_path` | custom field "Component Tags", e.g. `Blink>Layout` | high |
| `type`, `type_name` | `c[1]` | see below |
| `status`, `status_name` | `c[2]` | high |
| `priority` | `c[3]`, 1..5 → P0..P4 | high |
| `severity` | `c[4]`, 1..5 → S0..S4 | high |
| `title` | `c[5]` (**untrusted**) | certain |
| `created`, `modified` | `i[4]`, `i[5]` (seconds, nanos), UTC | high |
| `resolved` | `i[6]`; set exactly when the status is closed (4–10) | high |
| `verified` | `i[7]`; seen only on Verified issues | medium |
| `cve`, `introduced_in`, `milestone`, `security_release`, `os`, `labels`, `fixed_by_field` | custom fields "CVE", "Introduced In", "Milestone", "Security_Release", "OS", "Chromium Labels", "Fixed By Code Changes", display value | high (by field name) |
| `found_in` | `c[16]`, JSON list of milestones | medium |
| `hotlists` | `c[13]`, JSON list of hotlist IDs | medium |
| `fixed_by` | `c[34]`, `[host, project, change, ?]` → `host/project/change` | high |
| `regression` | 1 if "Chromium Labels" mentions "regression" or "Introduced In" is set | low (heuristic) |
| `custom` | every custom field, `{name: display value}` as JSON | high |
| `raw_file`, `fetched_at` | where and when it came from | |

Custom-field names come from the field definitions in each issue (`i[14]`:
`[id, …, type, …, name, …]`), so they don't depend on field IDs. A value is
`c[14]` entry `[field id, …, display (index 9), …]`.

**Enums.** They match the public `google.devtools.issuetracker.v1` API and
what the trial showed:

- status: 1 New, 2 Assigned, 3 Accepted, 4 Fixed, 5 Verified, 6 Not
  reproducible, 7 Intended behavior, 8 Obsolete, 9 Infeasible, 10
  Duplicate. High: the closed ones (4–10) are exactly those with a resolved
  time, and 10 carries an extra element (the duplicate's target).
- type: 1 Bug, 2 Feature request, 3 Customer issue, 4 Internal cleanup,
  5 Process, 6 Vulnerability. High for 1, 2, 4, 6; 15 (probably Task) and
  other values are kept as numbers with no name.
- priority and severity: high.

**Regression** is weak: in the trial no label said "regression" and few
bugs set "Introduced In". Chromium marks regressions with hotlists, whose
names aren't in the reply. Mapping hotlist IDs to names would need a
separate lookup (not done).

## Commands

From the main checkout (or a worktree with
`COSH_DATA_DIR=/home/rbagent/projects/cosh/data/private`):

```bash
python3 -m cosh.bugs ids                    # offline, ~10 s
python3 -m cosh.bugs fetch                  # dry run: IDs, requests, hours
nice -n 5 python3 -m cosh.bugs fetch --go   # resumable
nice -n 5 python3 -m cosh.bugs monorail --go
nice -n 5 python3 -m cosh.bugs fetch --go   # asks the newly mapped IDs
python3 -m cosh.bugs status                 # counts and enum histograms only
python3 -m cosh.bugs fetch --retry-missing --go   # months later
```

The full run started on 2026-11-08 chains the three `--go` steps in one
background job (`fetch`, `monorail`, `fetch`), log
`data/private/bugs/fetch-*.log`, process group ID in
`data/private/bugs/fetch.pid` (`kill -- -$(cat …/fetch.pid)` stops it;
rerunning the chain resumes).

## Cost

Trial on 2026-11-08: 5 requests, 250 IDs (the newest), 120 visible (48%),
0.8 s per request, 443 KB per request on the wire (gzip), 2.3 MB
uncompressed. Monorail stubs are ~2 KB.

Estimate for the full run: ~2,520 search requests (~2 h at 2 s) and ~21,300
Monorail lookups (~14 h), then ~430 searches for the mapped IDs; about
1.2 GB on disk, nearly all in `raw/list/`.

## Untrusted content

Bug titles, custom-field values and anything else in the replies are
written by the public and may contain prompt injections (`SECURITY.md`).
Code parses them; sessions print only counts, IDs and enum fields
(`status` is built that way). A few titles while debugging the parser are
fine as data. Anything that reads them in bulk with a model goes through
`cosh.sandbox.Sandbox`.
