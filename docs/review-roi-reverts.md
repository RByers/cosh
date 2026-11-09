# Revert study: what Chromium reverts are for, how fast, and what they cost

Work package 3 of `docs/review-roi.md`. Script: `scripts/review_roi_reverts.py`
(rerun commands in its docstring; whole pipeline about 5 minutes, the cost step
is 2.7 minutes). Numbers: `reverts_results.json`; interface for package 1:
`revert_reasons.tsv` (both in the job scratch directory `reverts/`). Nothing was
fetched; the one LLM pilot was not needed (see Methods, step 5).

## Summary in plain language

- From 2023-07-01 to 2026-11-09 there were **14,286 distinct commits on `main` that
  were later reverted** (one row per reverted commit; 26 were reverted twice).
  Per year of the revert: 2,014 (Jul-Dec 2023), 4,049 (2024), 4,004 (2025), 4,219
  (2026 to 9 Nov). That is about 34-38 reverts per 1,000 non-bot commits, with no
  trend upward or downward (38.0, 37.0, 38.2, 34.4).
- **Most reverts are CI breakage caught within a day.** The median revert comes
  11.5 hours after landing; 68% of reverts inside 30 days come within 24 hours.
  64% happen within 24 hours of landing, 1,256 (9%) in under an hour.
- **What for** (regex classes, 21% unknown): test failure 39.6%, crash or other
  functional bug 14.0%, compile or link failure 12.2%, flaky or unrelated 7.0%,
  dependent or requested 4.0%, perf or size 2.0%, policy 0.1%, security under 0.1%.
- **Who reverts:** a third party (sheriff, gardener, other engineer) 62.8%; the
  author 23.0%; a bot account 9.6%; an approver of the reverted CL 4.7%.
  71% of the revert CLs carry a `Bot-Commit` footer (Rubber Stamper approval).
- **Reland:** 30.8% of reverted commits are relanded (median 1.8 days after the
  revert, quartiles 0.75 and 5.0 days); 10.6% of those relands were reverted
  again.
- **Not preventable by review** (the negative control): flaky/unrelated plus
  dependent/requested is **11.0%** of reverts; adding policy/process 11.1%. The
  share is the same each year (11.6, 12.3, 10.2, 10.2%).
- **What a revert costs in review, mean (bootstrap 95% CI)**, from
  `balance.sqlite`: a revert plus its reland takes **53 reviewer attention hours
  (46-61), 30 owner attention hours (25-36), 1.8 review threads and 0.55 rounds**
  on average over the 3,692 pairs found; the medians are 6 h, 1.7 h, 1 thread
  and 0 rounds. The mean is dominated by a long tail of CLs left waiting, and
  *attention hours are waiting time in someone's attention set, not working
  time*. The revert CL itself (12,856) has human review in only 40% (30% of the
  bot-stamped ones, 65% of the others) and a mean 12.6 reviewer attention hours.
  The reverted CLs themselves were reviewed more heavily than same-size,
  same-directory CLs that stayed (mean +18 reviewer hours, +35 owner hours, +0.3
  threads, +45 hours from creation to landing), the usual "riskier CLs get more
  review" pattern.

## Methods

1. **Population.** `balance-git.sqlite` `gcommits`: every first-parent commit
   whose message has `This reverts commit <sha>` and which landed on or after
   2023-07-01, whose target is also in `gcommits`. One row per reverted commit
   (the first revert wins; 26 reverted again). Messages come from one pass of
   `git log main --first-parent` over the shared bare clone (12 s), read-only,
   `GIT_NO_LAZY_FETCH=1`, niced. 14,352 revert commits in the window; 14,286
   rows after joining.
2. **Reason text.** The text after `Reason for revert:` and before `Original
   change's description` (if there is no such label, the free text before the
   quoted original). 230 reverts have no reason text; they are `unknown`.
   Before matching, URLs, `crbug`/`crrev`/`b/` links, paths,
   `Cr-Commit-Position`, `Failure Link` and `Details` lines are stripped so that
   builder names such as `linux-chromeos-dbg` or a directory called `policy`
   cannot match.
3. **Classes.** Ordered rules, first match wins (listed under "Rules"). Test
   failure sits after compile and perf and before crash; the weak hedges
   ("suspected", "culprit", "bisect", "maybe") are checked last, only when no
   concrete symptom matched. A message with a build error and a test failure is
   called compile; the class is the first symptom in rule order, not a
   judgement.
4. **Who, when, reland.** *Who:* `bot` if the revert's author address looks like
   a service account or roller, else `author` if it is the reverted commit's
   author, else `approver` if in its `Reviewed-by`, else `third_party`. The
   `Bot-Commit` footer is reported separately (it only means Rubber Stamper
   approved the revert CL; the person who authored it is still a person).
   *Hours to revert:* revert commit time minus reverted commit time (committer
   dates). *Reland:* a later first-parent commit that says `reland of` and
   names the reverted sha (or the revert's sha) in that sentence, 4,002; else
   names the reverted CL number, 108; else a title `Reland "X"` of `Revert "X"`
   by the same author within 90 days, 294. The first such commit after the
   revert is the reland. `is_reland` in `gcommits` is only "subject starts with
   Reland" (`cosh/balance.py`), so it was used as a candidate filter, not as
   the link. A reland is "reverted again" if its sha is itself a reverted sha in
   the table. Reverts of reverts (17.3% of the reverted commits are themselves
   reverts) are a way of relanding that is *not* counted as a reland here, so the
   reland share is a lower bound.
5. **LLM pilot: skipped.** The unknown class is 21.0% (3,007 of 14,286), under
   the 25% threshold, so no model was called. If wanted later: a pass over
   3,007 reasons (about 90 characters each after cleaning, roughly 25 tokens
   each plus a ~250-token prompt) in batches of 50 is about 60 calls; with
   Haiku at the throughput measured in `docs/comment-classifier.md` that is
   minutes, and about 150-200k tokens in total. This is an estimate, not
   measured. 230 of the unknown have no text at all and cannot be helped.
6. **Cost.** `balance.sqlite` `cl` joined by change number (13,239 reverted CLs,
   4,343 relands, 353,344 control CLs; merged, human-owned, under 100 files).
   Controls: merged CLs closed 2023-07 .. 30 days before the data end that are
   neither reverts nor relands and were not reverted. Match key: size bucket
   (10 log2 buckets of landed lines, as `balance_growth.size10`) by the first two
   directory levels of the CL's largest directory (`cl_dirs`), falling back to
   the size bucket where a cell has under 20 controls. "Excess" is a CL's value
   minus the control mean of its cell; confidence intervals are 400-resample
   percentile bootstraps over CLs (not author-clustered, so too narrow if
   authors repeat). Reviewer attention hours are the sum of `cl_attention.hours`
   (each non-owner human's time in the attention set); owner attention hours are
   `owner_wait_h`; "life" is creation to landing. A revert-reland *cycle* is the
   reland CL's value plus the revert CL's value (both present, 3,692 pairs). The
   original CL's review is not added: it would have happened anyway.

## Results

### Reason classes (all 14,286)

| class | reverts | share | median hours to revert | of 30-day reverts, within 24 h | relanded |
|---|---|---|---|---|---|
| compile_or_link | 1,740 | 12.2% | 1.6 | 91% | 44.9% |
| test_failure | 5,664 | 39.6% | 7.2 | 79% | 40.7% |
| crash_or_functional | 1,994 | 14.0% | 30.2 | 49% | 23.5% |
| flaky_or_unrelated | 1,001 | 7.0% | 14.8 | 63% | 29.1% |
| dependent_or_requested | 571 | 4.0% | 40.8 | 49% | 10.7% |
| perf_or_size_regression | 285 | 2.0% | 73.4 | 37% | 18.2% |
| policy_or_process | 20 | 0.1% | 134.8 | 35% | 15.0% |
| security | 4 | 0.0% | 527 | 0% | 0% |
| unknown | 3,007 | 21.0% | 42.7 | 49% | 14.8% |

`test_failure` is a broad class: any CI or test failure that the compile rules do
not claim, including generic "failing on <builder>" reasons. `security` is
nearly empty because security-motivated reverts rarely say so in public
messages (and the word "security" in test names is excluded). Classes were
spot-read on about 90 samples drawn while building the rules: most placements
were plausible; the misfires seen were builder-failure reasons landing in
`dependent_or_requested` through words such as "pending", test-named reasons
landing in `perf` through "leak", and "Reland with ..." messages (reverts of
relands) landing in `dependent_or_requested`. Treat class shares as good to a few
percentage points for the big classes and rough for the small ones.

### Hours from landing to revert, by class (counts)

| class | <1 h | 1-6 h | 6-24 h | 1-7 d | 7-30 d | 30 d+ |
|---|---|---|---|---|---|---|
| compile_or_link | 682 | 659 | 245 | 122 | 25 | 7 |
| test_failure | 144 | 2364 | 1937 | 958 | 191 | 70 |
| policy_or_process | 2 | 1 | 4 | 3 | 10 | 0 |
| security | 0 | 0 | 0 | 1 | 1 | 2 |
| dependent_or_requested | 23 | 81 | 141 | 174 | 79 | 73 |
| flaky_or_unrelated | 62 | 246 | 305 | 265 | 85 | 38 |
| perf_or_size_regression | 2 | 37 | 52 | 104 | 48 | 42 |
| crash_or_functional | 119 | 359 | 428 | 630 | 281 | 177 |
| unknown | 222 | 512 | 571 | 822 | 512 | 368 |
| **all** | 1,256 | 4,259 | 3,683 | 3,079 | 1,232 | 777 |

Of the 13,509 reverts within 30 days, 68.1% come within 24 hours. Those are
mostly CI-caught; review competes with CI for them.

### By year (year of the revert)

| year | reverts | per 1,000 non-bot commits | within 24 h | not preventable (strict) | relanded |
|---|---|---|---|---|---|
| 2023 (Jul-Dec) | 2,014 | 38.0 | 63.6% | 11.6% | 32.7% |
| 2024 | 4,049 | 37.0 | 61.4% | 12.3% | 30.6% |
| 2025 | 4,004 | 38.2 | 64.8% | 10.2% | 30.5% |
| 2026 (to 9 Nov) | 4,219 | 34.4 | 67.3% | 10.2% | 30.4% |

Class shares by year are in `reverts_results.json` (`timing.by_year`); test
failure rises from 36.6% (2023) to 43.4% (2026) and compile falls from 14.4% to
12.3%; the rest are within a point or two. The relanded share of recent reverts
is not censored enough to matter (median 1.8 days). "Strict" means flaky or
unrelated plus dependent or requested.

### Who reverts

| role | share | median hours to revert |
|---|---|---|
| third party | 62.8% | 8.3 |
| author | 23.0% | 59.6 |
| bot account | 9.6% | 4.5 |
| approver | 4.7% | 42.2 |

Authors revert late (median 2.5 days: they notice a bug or change their mind);
third parties revert fast (sheriffs). 71% of revert CLs are `Bot-Commit`.

### Reland

4,404 of 14,286 (30.8%) were relanded: median 1.76 days after the revert (25th to
75th percentile 0.75 to 4.96 days). 467 (10.6%) of the relands were reverted
again. Reland share by class: compile 45%, test 41%, flaky 29%, crash 24%, perf
18%, policy 15%, unknown 15%, dependent 11%.

### Cost of a revert in review time

Mean with bootstrap 95% CI in brackets (median in parentheses). All "hours" are
attention-set hours (waiting), not effort.

| | n | reviewer attention h | owner attention h | threads | rounds | creation to landing h |
|---|---|---|---|---|---|---|
| control CLs (same period, not reverted) | 353,344 | 60.3 (3.7) | 54.4 (2.2) | 2.92 (1) | 0.77 (0) | 122.4 (24.0) |
| reverted CLs | 13,239 | 95.8 [88.5-102.8] (4.9) | 104.5 [95.7-115.8] (4.1) | 4.16 (1) | 1.0 (0) | 193.8 [180-209] (27.0) |
| ... excess over same size and directory | | +18.5 [11.2-25.5] | +34.9 [25.9-46.3] | +0.29 [0.15-0.46] | +0.04 | +44.7 [31.0-59.8] |
| relands | 4,343 | 49.6 [43.6-56.2] (5.2) | 29.1 [25.1-35.3] (1.6) | 1.55 (1) | 0.5 (0) | 70.5 [63.5-81.1] (20.8) |
| revert CLs (all) | 12,856 | 12.6 [10.8-14.8] (0) | 7.2 [5.8-9.1] (0) | | | 19.9 [15.1-28.1] (0.8) |
| revert CLs, not Bot-Commit | 3,774 | 35.9 [29.5-43.8] (1.1) | 22.2 [17.4-28.1] (0.3) | | | 59.5 [43.6-87.7] (5.6) |
| revert CLs, Bot-Commit | 9,082 | 2.9 [2.5-3.3] (0) | 1.0 [0.9-1.2] (0) | | | 3.5 [3.1-3.8] (0.2) |
| **cycle: reland + revert CL** | 3,692 | **52.9 [46.0-60.9] (6.0)** | **29.8 [24.7-36.5] (1.7)** | 1.77 [1.68-1.87] (1) | 0.55 (0) | 73.3 [63.8-86.2] (21.3) |

Reading it. The tails are long (means are 10-20 times the medians): a few CLs sit
in someone's attention set for weeks. The typical cycle is therefore small
(about 6 reviewer hours waiting, one thread), the average is large. The median
of the excess column is not shown because it compares each CL with a cell
*mean*, which is skewed above the median (the medians come out negative for
every group and say nothing about extra review). Human review of the revert CL
itself exists for 40% (threads or attention hours above zero): 30% of
Bot-Commit reverts, 65% of the others; when reviewed, the median is 2.4
reviewer attention hours and one thread (5,124 CLs).

Relands get less review per CL than same-size peers (excess negative on every
measure), plausibly because the code was already reviewed once; the relanded
cycle's extra review is the reland plus the revert, not the original.

Not measured: sheriff and gardener time to find the culprit, CI machine time
for the failed and rerun builds, other engineers' blocked or rebased work, the
time the tree was closed, users affected, and the work of the author to fix the
problem before the reland (only visible partly as reland rounds). Time to
revert is the only proxy for how long a breakage lasted.

### Use as a negative control (D8)

`revert_reasons.tsv` carries `reason_class`. Strictly not-preventable by review:
`flaky_or_unrelated` and `dependent_or_requested`, 1,572 reverts, 11.0%. Adding
`policy_or_process`: 11.1%. `unknown` (21%) is a mix and should be left out of
both arms or shown as its own line. A caveat for D8: "flaky or unrelated" is a
claim made in a hurry by a sheriff and may hide real causes; and dependent
reverts depend on another CL that review could have caught. The negative control
is thus noisy toward "preventable", which makes it a conservative control.

## Caveats

- Classes come from regexes on a sheriff's one-line reason, not from root cause
  analysis. The 21% unknown includes 230 empty reasons.
- Only the first revert of each commit is kept; reverts whose target landed
  before 2017 (not in `gcommits`) are dropped, with the 26 repeat reverts (66 of 14,352 revert commits found).
- Reland detection depends on the reland message naming the original; manual
  relands under another title are missed, so 30.8% is a lower bound.
- `reverter_role` `bot` is by address pattern; a human authoring a revert through
  an automation account would be missed.
- Revert hours use committer timestamps; negative or sub-minute values
  (reverted before the first-parent commit time) are counted in the first bin.
- Cost CIs resample CLs, not authors; the real uncertainty is wider.
- Costs are attention-set hours, which include waiting. They are not effort.
- 2026 ends 2026-11-09; its relanded share has had less time to accumulate
  (the median reland is under 2 days, so the effect is small).

## Rules (first match wins; applied to the cleaned, lowercased reason)

The authoritative list is `RULES` in `scripts/review_roi_reverts.py`. In order:
a LUCI Bisection build-failure line is compile, and its test-failure line is
test; then `policy_or_process`, `security`, `dependent_or_requested`,
strong hedges (`flaky_or_unrelated`: flaky, unrelated, speculative, "to check
if", "not the culprit", infra, OOM), `compile_or_link`, `perf_or_size_regression`,
`test_failure`, `crash_or_functional`, and last the weak hedges (suspect,
culprit, bisect, "not sure", maybe), again `flaky_or_unrelated`; no match is
`unknown`.

## Runtimes

`parse` 12 s; `table` about 10 s; `timing` a few seconds; `cost` 2 min 40 s (the
bootstrap dominates); peak memory under 1 GB. No LLM calls.

## Sample reasons per class (10 random, 100 characters, links and addresses masked)

Seeded draw (`samples` command). Read these to judge the regexes.


### compile_or_link (1740)

- `b/377969311 Breaks ChromeOS compile.`
- `Triggered compile step failures. First failure: <url>`
- `compile issue crbug.com/405220075`
- `Failing cast build: <url>`
- `This fixes the original build failure by removing the lingering #include.`
- `LUCI Bisection identified this CL as the culprit of a build failure. See the analysis: <url>`
- `Caused build failure. Failure Link: <url>`
- `LUCI Bisection has identified this change as the culprit of a build failure. See the analysis: https`
- `fails to compile on chromeos-arm64-generic-rel stacktrace_aarch64-inl.inc:196:26: error: implicit co`
- `Build fails on android-arm-rel-ready.`


### test_failure (5664)

- `This cl has caused test failures on 'android-desktop-17-x64-rel-brya-tests' Failure Link: <url>`
- `LUCI Bisection has identified this change as the cause of a test failure. See the analysis: https://`
- `Test started to fail consistently <url>`
- `Suspect of failing builder "win-arm64-rel"`
- `Likely broke win64-rel-ready. First failure: <url>`
- `This is causing a DCHECK: FATAL chrome[296968:1]: [agent.cc(100)] Check failed: is_isolated_context `
- `Fix test error for testAllSettingsFragmentSubclassesAreInEnum. The new settings fragments are added `
- `LUCI Bisection has identified this change as the cause of a test failure. See the analysis: https://`
- `Best suspect for persistent crostini tast test failures on chromeos-eve-chrome since <url>`
- `Multiple tests started to fail consistently: <url>`


### policy_or_process (20)

- `Should not have landed without a chromestatus entry`
- `not ready to launch.`
- `We had some accesses to mock objects and TestingBrowserProcess that didn't have any effect, but shou`
- `Should not have been submitted initially, builders not healthy enough.`
- `Turned off orderfiles by accident`
- `See patchset 1 for the pure revert, and subsequent patchsets for the fix. Mac browsertests need to w`
- `Revert "Reland "chrome/browser/updater: Create a cleaner public interface"" Revert "browser/updater:`
- `Fixes compilation error for fuzzer_util.cc which broke on ios-catalyst bot. In addition, a new ios_s`
- `Feature not ready for launch in M143`
- `It's going to be reverted by Sherrifs since there's still some scripts which are automatically makin`


### security (4)

- `Paraphrasing [addr] from the original CL <url> this is a low-risk security issu`
- `These unit tests should run unconditionally. The reason is two-fold. First, the tests exist to make `
- `A blocking security issue was discovered on these GPUs. Failure Link: <url>`
- `CHECK is getting hit a little too often, and the previous behavior is not a security issue`


### dependent_or_requested (571)

- `Reason for reland: Drop the private monkey_patch_calls_in_scope_ test accessor in ScriptAncestryTrac`
- `We validated that the original removal of V1 metrics control path was not the primary cause of jank `
- `The change removes `cursorColor` accessibility API which is actively used by Kiosk chrome apps. This`
- `Relanding after fixing use of uninitialized variable. PlatformDelegate was accessing `owner_->profil`
- `False positive. The CL was reverted based on the hypothesis that it caused multiple tests failure ht`
- `ApplicationLocaleStorage::Set is only called once during startup, before RegisterOnLocaleChangedCall`
- `The bad Siso rollout was reverted <url>`
- `Dev blocker crbug.com/409566073`
- `Needs more discussion`
- `we expect cherry picks. Reverting until the cherry picks are done, will reland later`


### flaky_or_unrelated (1001)

- `Likely culprit of <url>`
- `not migrating PwaRestoreBottomSheetIntegrationTest PwaRestoreBottomSheetIntegrationTest seems to hav`
- `test is flaky on <url> Example: ht`
- `SupervisedUserIncognitoBrowserTest is flaky (failing a lot) in multiple bots, even the MegaCQ has so`
- `still flaky: <url>`
- `Not the root cause of the issue`
- `The tests in this suite are generally very flaky, and the newly introduced tests appear to suffer th`
- `Disable flaky test after talking to owner.`
- `Tests become flaky`
- `Speculative fix for <url>`


### perf_or_size_regression (285)

- `See discussion on the associated bug. A more recent time range shows a plausible guardrail metrics r`
- `Performance regressions (example: crbug/369236535)`
- `perf regressions Failure Link: <url>`
- `causes android-pixel10_webview-perf-pgo-heapdump to fail consistently Failure Link: <url>`
- `This CL causes chrome_junit_tests runtime to go from about 22min to 45 min. This increase in time ca`
- `Regression in jetstream and v8. browsing_mobile crbug.com/428022215`
- `The original bug was: clicking starter packs like [addr] did not enter keyword mode. 2 CLs (crrev.c`
- `Breaks all tests on android-pixel4_webview-perf(-pgo). See tryjob in comments.`
- `this shows regression on pinpoint (see b/448759753), while this is weird considering the nature of t`
- `Regresses Jetstream`


### crash_or_functional (1994)

- `Crashes on MSAN builds: See <url>`
- `Broke `generate_build_files` for: <url>`
- `Broke fuchsia-x64-dbg builder`
- `This broke ToT. The DEPS revision does not match the submodule revision. [DEPS] src/third_party/ffmp`
- `Crash after Clank restart if signed in`
- `ASAN on android x64 doesn't work.`
- `Break internal builder <url>`
- `Bots have greened. Our best explanation is that this just caused corrupt .o files to be regenerated,`
- `This is crashing on MSAN with use-of-uninitialized-value`
- `Broke Arabic text, crbug.com/413307117`


### unknown (3007)

- `I don't think this is helping <url>`
- `Changed the refactor plan, so this cl is not needed.`
- `Erasing an item from the map may trigger a GC sweep if the hash-map shrinks. This would mutate `decr`
- `Mistake on my side. For the finch configuration we actually need the previous version. Again, this i`
- `Previous missing inputs were fixed.`
- `cog fix will not roll out until monday`
- `This CL changed which baselines `//BUILD.gn` isolates, which causes some baseline mismatches: https:`
- `Cause of multiple clank CQ breakages see crbug.com/1520510`
- `possible tree-closer (see comments)`
- `with fix window builder.`
