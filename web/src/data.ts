// Pure data handling: parse the committed summaries and Radar CSV, and join
// them into value ratios. No DOM or Chart.js here so it can be unit-tested
// in Node.
//
// The review metrics come from review comments (bare votes don't count):
// summaries/org_weekly.json holds each org's comments, review characters and
// reviewed CLs per week, already filtered to the paths in config/paths.txt.
// summaries/area_weekly.json has every comment by directory.
//
// Commits are the author side (docs/commits.md): human commits on main that
// touch a counted path, by the git author's org, in org_weekly.json too. Per
// person and per directory they're in files of their own (author_weekly.json,
// area_commits.json, area_authors.json), loaded only when the Commits metric
// or the review chart's ratio needs them; authorBoard and commitBoard turn
// them into boards shaped like the review ones, so the same code reads both.
//
// Addressed comments (docs/comment-classifier.md) are the comments in review
// threads that led the CL owner to change the CL. They need an optional
// classification step, so a week has them only once its threads are
// classified: meta.addressed.coverage says how much of each week is decided,
// and the UI shows the metric only for weeks at meta.addressed.complete_at.

export type Metric = 'addressed' | 'comments' | 'chars' | 'cls' | 'commits';

/** Their names are in value.html (the metric buttons). */
export const METRICS: Metric[] = ['addressed', 'comments', 'chars', 'cls', 'commits'];

/** The metric the review chart's ratio divides by commits: the chosen one,
 * or addressed comments when commits are chosen (review comments if no week
 * is classified). */
export const ratioNumerator = (metric: Metric, addressed = true): Metric =>
  metric !== 'commits' ? metric : addressed ? 'addressed' : 'comments';

/** Orgs whose browsers have less Chromium usage share than this get no ratio:
 * dividing by ~0 makes the ratio meaningless. */
export const MIN_DERIVED_SHARE = 0.001;

/** Orgs whose browser usage Radar can't measure, so they are left out of the
 * ratio rather than shown with a misleading ~0% share. Brave sends Chrome's
 * User-Agent and names itself only in the Sec-CH-UA client hint, and Radar
 * reports it at about 0.002% of Chromium usage, roughly 1000x below Brave's
 * real size; its usage is almost certainly counted as Chrome. */
export const UNKNOWN_USAGE_ORGS: ReadonlyMap<string, string> = new Map([['brave.com', 'Brave']]);

export interface SummaryRow {
  iso_week: string;
  org: string;
  /** The org's share of the headline metric (comments unless summarize was told otherwise). */
  share: number;
  reviewers: number;
  reviewed_cls: number;
  comments: number;
  review_chars: number;
  ai_comments: number;
  post_merge_comments: number;
  share_cls: number;
  share_comments: number;
  share_chars: number;
  /** Absent in summaries written before the addressed metric. */
  addressed_comments?: number;
  pending_comments?: number;
  share_addressed?: number | null;
  /** Absent in summaries written before commits. */
  commits?: number;
  authors?: number;
  share_commits?: number | null;
}

/** Each metric's count and share columns in org_weekly. */
export const COUNT_COLUMN: Record<Metric, 'comments' | 'review_chars' | 'reviewed_cls' | 'addressed_comments' | 'commits'> = {
  addressed: 'addressed_comments',
  comments: 'comments',
  chars: 'review_chars',
  cls: 'reviewed_cls',
  commits: 'commits',
};
export const SHARE_COLUMN: Record<Metric, 'share_comments' | 'share_chars' | 'share_cls' | 'share_addressed' | 'share_commits'> = {
  addressed: 'share_addressed',
  comments: 'share_comments',
  chars: 'share_chars',
  cls: 'share_cls',
  commits: 'share_commits',
};

/** Whether the summary has commits (summaries written before them don't). */
export const hasCommits = (summary: Summary): boolean => !!summary.meta.commits;

export interface AddressedMeta {
  /** The model behind the labels, or null if no labels were used. */
  classifier: string | null;
  /** Week -> share of its in-scope comments whose point is decided. */
  coverage: Record<string, number>;
  /** Coverage at which a week counts as classified. */
  complete_at: number;
  rule?: string;
}

/** How a reviewer-started thread was decided (summaries' meta.addressed.thread_outcomes).
 * Their names are in value.html ("thread-outcome"). */
export type ThreadOutcome = 'done_reply' | 'model_addressed' | 'model_not' | 'no_reply' | 'pending';

/** Thread counts per outcome over some weeks, or null if the summary has none. */
export function threadBreakdown(summary: Summary, weeks: string[]): Map<ThreadOutcome, number> | null {
  const m = summary.meta.addressed as
    | { thread_outcomes?: ThreadOutcome[]; threads?: Record<string, number[]> }
    | undefined;
  if (!m?.thread_outcomes || !m.threads) return null;
  const out = new Map<ThreadOutcome, number>(m.thread_outcomes.map((o) => [o, 0]));
  for (const w of weeks) {
    const counts = m.threads[w];
    if (counts) m.thread_outcomes.forEach((o, i) => out.set(o, out.get(o)! + (counts[i] ?? 0)));
  }
  return out;
}

/** summaries/thread_examples.json: a few example threads per classified week and outcome. */
export interface ThreadExample {
  week: string;
  outcome: ThreadOutcome;
  cl: number;
  root: string;
  path: string;
  /** Replies beyond the ones shown. */
  more: number;
  messages: [role: 'reviewer' | 'owner' | 'other', text: string][];
}
export interface ThreadExamples {
  meta: { [k: string]: unknown };
  threads: ThreadExample[];
}

/** A thread on Gerrit, opened at its first comment. */
export const gerritCommentUrl = (cl: number, root: string) =>
  `https://chromium-review.googlesource.com/c/chromium/src/+/${cl}/comment/${encodeURIComponent(root)}/`;

/** The addressed metric's metadata, or null in summaries written before it. */
export function addressedMeta(summary: Summary): AddressedMeta | null {
  const m = summary.meta.addressed as AddressedMeta | undefined;
  return m && typeof m === 'object' && m.coverage ? m : null;
}

/** The weeks whose addressed metric is complete enough to show, sorted. */
export function addressedWeeks(summary: Summary): string[] {
  const m = addressedMeta(summary);
  if (!m) return [];
  return Object.entries(m.coverage)
    .filter(([, c]) => c >= m.complete_at)
    .map(([w]) => w)
    .sort(compareWeeks);
}

/** The classified weeks within a range, and the range from the first to the
 * last of them (null if the range has none). */
export function addressedRange(summary: Summary, range: WeekRange): { weeks: string[]; range: WeekRange | null } {
  const weeks = addressedWeeks(summary).filter((w) => compareWeeks(w, range.from) >= 0 && compareWeeks(w, range.to) <= 0);
  return { weeks, range: weeks.length ? { from: weeks[0], to: weeks[weeks.length - 1] } : null };
}

export interface PathRule {
  prefix: string;
  included: boolean;
}

export interface Summary {
  meta: { weeks: string[]; path_rules?: PathRule[]; [k: string]: unknown };
  rows: SummaryRow[];
}

export interface WeeklyTotals {
  iso_week: string;
  main_cls: number;
  merged_cls: number;
  abandoned_cls: number;
  human_cls: number;
  bot_cls: number;
  /** Human-owned CLs with at least one review comment from a non-owner, non-bot account (any path). */
  human_cls_with_comments: number;
}

/** Minimal RFC 4180 CSV parser: quoted fields, doubled quotes, CRLF. */
export function parseCsv(text: string): Record<string, string>[] {
  const records: string[][] = [];
  let field = '';
  let record: string[] = [];
  let inQuotes = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (inQuotes) {
      if (c === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i++;
        } else {
          inQuotes = false;
        }
      } else {
        field += c;
      }
    } else if (c === '"') {
      inQuotes = true;
    } else if (c === ',') {
      record.push(field);
      field = '';
    } else if (c === '\n' || c === '\r') {
      if (c === '\r' && text[i + 1] === '\n') i++;
      record.push(field);
      records.push(record);
      record = [];
      field = '';
    } else {
      field += c;
    }
  }
  if (field !== '' || record.length) {
    record.push(field);
    records.push(record);
  }
  const [header, ...body] = records.filter((r) => !(r.length === 1 && r[0] === ''));
  if (!header) return [];
  return body.map((r) => Object.fromEntries(header.map((h, i) => [h, r[i] ?? ''])));
}

/** org -> browsers, in file order (which is also the org colour order). */
export function parseOrgBrowsers(text: string): Map<string, string[]> {
  const out = new Map<string, string[]>();
  for (const r of parseCsv(text)) {
    const list = out.get(r.org_domain) ?? [];
    list.push(r.browser);
    out.set(r.org_domain, list);
  }
  return out;
}

export function parseWeeklyTotals(text: string): WeeklyTotals[] {
  return parseCsv(text).map((r) => ({
    iso_week: r.iso_week,
    main_cls: Number(r.main_cls),
    merged_cls: Number(r.merged_cls),
    abandoned_cls: Number(r.abandoned_cls),
    human_cls: Number(r.human_cls),
    bot_cls: Number(r.bot_cls),
    human_cls_with_comments: Number(r.human_cls_with_comments),
  }));
}

/** week -> browser -> share of Chromium browser usage (Radar `chromium_share`).
 * Only complete ISO weeks (days=7), device=all. */
export type RadarWeekly = Map<string, Map<string, number>>;

export function parseRadarWeekly(text: string): RadarWeekly {
  const out: RadarWeekly = new Map();
  for (const r of parseCsv(text)) {
    if (r.granularity !== 'week' || r.device !== 'all' || r.days !== '7') continue;
    if (r.chromium_share === '') continue; // non-Chromium, bots, TVs
    let m = out.get(r.period);
    if (!m) out.set(r.period, (m = new Map()));
    m.set(r.browser, Number(r.chromium_share));
  }
  return out;
}

/** Radar browser buckets left out of the ratio's usage denominator; the ratio
 * uses each org's share of the rest, and the usage chart still shows them.
 * - ChromeDerivative, Radar's unnamed-Chromium bucket, jumped from about 0.3%
 *   to about 10% of Chromium usage in 2026-W37. That looks like a reporting
 *   change Radar hasn't explained.
 * - ChromeMobileWebview, Android System WebView, is embedded by many different
 *   browsers and apps, so its usage can't be credited to any one org. */
export const RATIO_EXCLUDED_BROWSERS: readonly string[] = ['ChromeDerivative', 'ChromeMobileWebview'];

/** Sum of an org's browsers' Chromium usage share in one week, renormalized
 * to leave out RATIO_EXCLUDED_BROWSERS, or null if Radar has no complete data
 * for that week. */
export function derivedShare(radar: RadarWeekly, week: string, browsers: string[]): number | null {
  const m = radar.get(week);
  if (!m) return null;
  const sum = (bs: readonly string[]) => bs.reduce((s, b) => s + (m.get(b) ?? 0), 0);
  const rest = 1 - sum(RATIO_EXCLUDED_BROWSERS);
  if (rest <= 0) return null;
  return sum(browsers.filter((b) => !RATIO_EXCLUDED_BROWSERS.includes(b))) / rest;
}

export interface RatioPoint {
  week: string;
  org: string;
  /** Org's share of the chosen metric (0 if absent from the summary). */
  contribution: number;
  /** Org's browsers' share of Chromium browser usage; null if no Radar week. */
  derived: number | null;
  /** contribution / derived; null when undefined (no Radar data, or usage
   * share below MIN_DERIVED_SHARE). */
  ratio: number | null;
}

/** Value ratios for every (summary week, browser-owning org). `weeks`
 * narrows that to the weeks the metric has data for (the classified weeks,
 * for addressed comments): other weeks get no point at all, so smoothRatios
 * leaves them out of its window instead of averaging them in as zero. */
export function computeRatios(
  summary: Summary,
  radar: RadarWeekly,
  orgBrowsers: Map<string, string[]>,
  metric: Metric = 'comments',
  minDerived = MIN_DERIVED_SHARE,
  weeks: readonly string[] = summary.meta.weeks,
): RatioPoint[] {
  const col = SHARE_COLUMN[metric];
  const points: RatioPoint[] = [];
  const index = summaryRowIndex(summary);
  for (const week of weeks) {
    for (const [org, browsers] of orgBrowsers) {
      const row = index.get(week)?.get(org);
      const contribution = row ? Number(row[col] ?? 0) : 0;
      const derived = derivedShare(radar, week, browsers);
      const ratio = derived !== null && derived >= minDerived ? contribution / derived : null;
      points.push({ week, org, contribution, derived, ratio });
    }
  }
  return points;
}

/** A summary's rows by week and org (the first row for each pair). */
const rowIndexes = new WeakMap<Summary, Map<string, Map<string, Summary['rows'][number]>>>();
function summaryRowIndex(summary: Summary) {
  let index = rowIndexes.get(summary);
  if (!index) {
    index = new Map();
    for (const r of summary.rows) {
      let byOrg = index.get(r.iso_week);
      if (!byOrg) index.set(r.iso_week, (byOrg = new Map()));
      if (!byOrg.has(r.org)) byOrg.set(r.org, r);
    }
    rowIndexes.set(summary, index);
  }
  return index;
}

/** The weeks of `weeks` that have both halves of a value ratio: a complete
 * Radar week (usage) and, if `dataWeeks` is given, review data for the
 * metric (the classified weeks, for addressed comments). The ratio views keep
 * only these, so a range never starts or ends on weeks with no ratio at all,
 * and range totals compare review and usage over the same weeks. */
export function ratioWeeks(weeks: readonly string[], radar: RadarWeekly, dataWeeks?: readonly string[]): string[] {
  const has = dataWeeks ? new Set(dataWeeks) : null;
  return weeks.filter((w) => radar.has(w) && (!has || has.has(w)));
}

/** Running-average choices for the value ratio chart, in weeks (1 = off). */
export const SMOOTHING_WEEKS = [1, 4, 13, 52] as const;
export type Smoothing = (typeof SMOOTHING_WEEKS)[number];
export const DEFAULT_SMOOTHING: Smoothing = 13;

/** A smoothing window's name as an adjective, e.g. "4-week" or "3-month"
 * (13 weeks), "1-year" (52 weeks). */
export function smoothingName(weeks: number): string {
  return weeks === 13 ? '3-month' : weeks === 52 ? '1-year' : `${weeks}-week`;
}

/** Trailing running average of ratios over `window` calendar weeks, ending at
 * each point's week. Averages the two shares separately and divides (mean
 * contribution ÷ mean usage), so a week with near-zero usage can't dominate
 * the way it would when averaging weekly ratios. Weeks with no Radar data, or
 * absent from `points`, are left out of the window. Pass every week, not just
 * the displayed range, so the first displayed weeks get a full window.
 *
 * With `fullWindows` (the default), a week whose window reaches back before
 * the first week with usage data gets no ratio: its average would cover only
 * the few weeks since the data starts, so one noisy week would swing it. */
export function smoothRatios(
  points: RatioPoint[],
  window: number,
  minDerived = MIN_DERIVED_SHARE,
  fullWindows = true,
): RatioPoint[] {
  if (window <= 1) return points;
  const byKey = new Map(points.map((p) => [`${p.org}|${p.week}`, p]));
  const first = points.reduce<string | null>(
    (m, p) => (p.derived !== null && (m === null || compareWeeks(p.week, m) < 0) ? p.week : m),
    null,
  );
  return points.map((p) => {
    if (fullWindows && first !== null && compareWeeks(addWeeks(p.week, 1 - window), first) < 0) {
      return { ...p, ratio: null };
    }
    let contribution = 0;
    let derived = 0;
    let n = 0;
    for (let i = 0; i < window; i++) {
      const q = byKey.get(`${p.org}|${addWeeks(p.week, -i)}`);
      if (!q || q.derived === null) continue;
      contribution += q.contribution;
      derived += q.derived;
      n++;
    }
    if (n === 0) return { ...p, derived: null, ratio: null };
    const c = contribution / n;
    const d = derived / n;
    return { ...p, contribution: c, derived: d, ratio: d >= minDerived ? c / d : null };
  });
}

/** Candidate orgs for the value charts, each with a fixed series (and
 * therefore a colour): their browsers reach minDerived in at least one Radar
 * week. Order follows org_browsers.csv, so colours never depend on the
 * selected metric or range. rangeChartedOrgs narrows them to a range. */
export function chartedOrgs(
  radar: RadarWeekly,
  orgBrowsers: Map<string, string[]>,
  minDerived = MIN_DERIVED_SHARE,
): string[] {
  const out: string[] = [];
  for (const [org, browsers] of orgBrowsers) {
    for (const week of radar.keys()) {
      if ((derivedShare(radar, week, browsers) ?? 0) >= minDerived) {
        out.push(org);
        break;
      }
    }
  }
  return out;
}

/** The candidates the value charts show for a range: those whose browsers'
 * mean weekly usage share over `weeks` reaches minDerived, the same test that
 * gives the table and parity chart a ratio. So an org above the threshold only
 * in other years (Amazon's Silk, before 2026) drops out of recent ranges. */
export function rangeChartedOrgs(
  radar: RadarWeekly,
  orgBrowsers: Map<string, string[]>,
  candidates: readonly string[],
  weeks: string[],
  minDerived = MIN_DERIVED_SHARE,
): string[] {
  return candidates.filter((org) => {
    const browsers = orgBrowsers.get(org);
    return !!browsers && (meanDerivedShare(radar, weeks, browsers) ?? 0) >= minDerived;
  });
}

export const OTHER = 'Other';

/** The contribution charts name an organization (a series, legend entry,
 * per-person row and organization-selector choice) when it wrote at least
 * this share of review comments, or of commits, over the selected range; the
 * rest are combined as OTHER (the selectors' "Other" choice). User's decision
 * (2026-11-05), replacing a fixed top 6: five orgs are at 0.4% or more in
 * every range, and the next is under 0.1% and changes with the range. */
export const NAMED_ORG_MIN_SHARE = 0.0025;

/** At most this many named organizations, so a legend never grows long. */
export const MAX_NAMED_ORGS = 8;

/** The organizations the charts name over the given weeks: those with at
 * least `minShare` of all review comments or of all commits (the summary's
 * "Other" row included in each total), by the larger of the two shares,
 * largest first, at most `max`. The same whatever metric is selected, so
 * switching metric never reshuffles the rows. */
export function namedOrgs(
  summary: Summary,
  weeks: string | string[],
  minShare = NAMED_ORG_MIN_SHARE,
  max = MAX_NAMED_ORGS,
): string[] {
  const share = new Map<string, number>();
  for (const metric of ['comments', 'commits'] as const) {
    const rows = topOrgCounts(summary, weeks, metric);
    const total = rows.reduce((s, r) => s + r.value, 0);
    if (!total) continue;
    for (const r of rows) share.set(r.org, Math.max(share.get(r.org) ?? 0, r.value / total));
  }
  return [...share]
    .filter(([org, s]) => org !== OTHER && s >= minShare)
    .sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : 1))
    .slice(0, max)
    .map(([org]) => org);
}

/** The `orgs` with at least `minShare` of `metric` over the week(s): an org
 * named for its commits, say, but with no review comments drops out of a
 * review-comment chart. */
export function orgsWithShare(
  summary: Summary,
  weeks: string | string[],
  metric: Metric,
  orgs: readonly string[],
  minShare = NAMED_ORG_MIN_SHARE,
): string[] {
  const rows = topOrgCounts(summary, weeks, metric);
  const total = rows.reduce((s, r) => s + r.value, 0);
  const value = new Map(rows.map((r) => [r.org, r.value]));
  return orgs.filter((o) => total > 0 && (value.get(o) ?? 0) / total >= minShare);
}

/** The metric summed over the given week(s): the top `n` orgs, then
 * everything else (including the summary's own "Other" row, e.g. gmail.com)
 * as a final "Other" entry. */
export function topOrgCounts(
  summary: Summary,
  weeks: string | string[],
  metric: Metric,
  n = Infinity,
): { org: string; value: number }[] {
  const col = COUNT_COLUMN[metric];
  const set = new Set(typeof weeks === 'string' ? [weeks] : weeks);
  const sums = new Map<string, number>();
  for (const r of summary.rows) {
    if (set.has(r.iso_week)) sums.set(r.org, (sums.get(r.org) ?? 0) + Number(r[col] ?? 0));
  }
  const rows = [...sums].map(([org, value]) => ({ org, value }));
  const named = rows.filter((r) => r.org !== OTHER).sort((a, b) => b.value - a.value);
  const top = named.slice(0, n);
  const rest = named.slice(n).reduce((s, r) => s + r.value, 0) +
    rows.filter((r) => r.org === OTHER).reduce((s, r) => s + r.value, 0);
  return rest > 0 || rows.some((r) => r.org === OTHER) ? [...top, { org: OTHER, value: rest }] : top;
}

/** Orgs by review comments over every week the summary holds, largest first
 * ("Other" left out): the order fixed org colours are handed out in, so
 * they never depend on the range, metric or a filter. */
export function orgsByAllTimeReview(summary: Summary): string[] {
  return topOrgCounts(summary, summary.meta.weeks, 'comments', Infinity)
    .map((r) => r.org)
    .filter((o) => o !== OTHER);
}

/** The page's one org → colour assignment, shared by every chart, as indexes
 * into the theme's org colours: `bright` vivid hues, then the same hues
 * muted. The `bright` orgs ranked first by review (`ranked`) get the vivid
 * ones, so the dominant orgs look unlike the rest. The muted ones go first to
 * the value charts' orgs (`ratioOrgs`) that have no vivid colour, so each of
 * those charts' lines has one, then to the next orgs by review. At most
 * `2 * bright` orgs get a colour, each a different one; any other org has
 * none: charts fold it into "Other" or show it muted and named. */
export function orgColorSlots(
  ranked: readonly string[],
  ratioOrgs: readonly string[],
  bright: number,
): Map<string, number> {
  const out = new Map<string, number>();
  for (const org of ranked.slice(0, bright)) out.set(org, out.size);
  for (const org of [...ratioOrgs, ...ranked]) {
    if (out.size >= 2 * bright) break;
    if (!out.has(org)) out.set(org, out.size);
  }
  return out;
}

/** How many orgs the value charts consider (chartedOrgs, in order). */
export const CHARTED_ORGS = 8;

/** Value Exchange's org → colour slot map (orgColorSlots over its ranked and
 * charted orgs), so other pages colour orgs exactly as it does. */
export function valueOrgColorSlots(
  summary: Summary,
  radar: RadarWeekly,
  orgBrowsers: Map<string, string[]>,
  bright: number,
): Map<string, number> {
  return orgColorSlots(orgsByAllTimeReview(summary), chartedOrgs(radar, orgBrowsers).slice(0, CHARTED_ORGS), bright);
}

/** Weekly counts of the metric for the `names` orgs (see namedOrgs), ranked by
 * their total over the given weeks, then everything else as a final "Other"
 * series. `values[i]` is the count in `weeks[i]`. With `smoothing` > 1, each
 * value is the trailing mean over that many calendar weeks ending at
 * `weeks[i]`, including weeks before the range; weeks outside the summary's
 * data are left out of the window, as in smoothRatios. Orgs in `exclude` are
 * dropped entirely (not folded into "Other"). `dataWeeks`, if given, are the only weeks
 * with data for the metric (the classified weeks, for addressed comments);
 * the running average skips the rest rather than counting them as zero.
 * With `nameable`, only orgs it accepts get a series of their own; the rest
 * are folded into "Other" (orgs without a fixed colour). */
export function orgWeeklyCounts(
  all: Summary,
  weeks: string[],
  metric: Metric,
  names: readonly string[],
  smoothing = 1,
  exclude: readonly string[] = [],
  dataWeeks?: readonly string[],
  nameable?: (org: string) => boolean,
): { org: string; values: number[] }[] {
  const col = COUNT_COLUMN[metric];
  const allow = new Set(names);
  let rows = exclude.length ? all.rows.filter((r) => !exclude.includes(r.org)) : all.rows;
  if (nameable) rows = rows.map((r) => (r.org === OTHER || nameable(r.org) ? r : { ...r, org: OTHER }));
  const summary = rows === all.rows ? all : { ...all, rows };
  const named = new Set(topOrgCounts(summary, weeks, metric).map((r) => r.org).filter((o) => o !== OTHER && allow.has(o)));
  // Raw counts per (org, week) over every summary week.
  const raw = new Map<string, Map<string, number>>();
  let hasOther = false;
  const inWeeks = new Set(weeks);
  for (const r of summary.rows) {
    const key = named.has(r.org) ? r.org : OTHER;
    if (key === OTHER && inWeeks.has(r.iso_week)) hasOther = true;
    if (!raw.has(key)) raw.set(key, new Map());
    const m = raw.get(key)!;
    m.set(r.iso_week, (m.get(r.iso_week) ?? 0) + Number(r[col] ?? 0));
  }
  const known = new Set(dataWeeks ?? [...summary.meta.weeks, ...summary.rows.map((r) => r.iso_week)]);
  const orgs = [...named, ...(hasOther ? [OTHER] : [])];
  return orgs.map((org) => ({ org, values: weeks.map((w) => trailingMean(raw.get(org), w, smoothing, known)) }));
}

/** The mean of `counts` over the `window` weeks ending with `week`, skipping
 * weeks without data (not in `known`); a missing count in a known week is 0. */
function trailingMean(counts: Map<string, number> | undefined, week: string, window: number,
  known: ReadonlySet<string>): number {
  let sum = 0;
  let k = 0;
  for (let i = 0; i < Math.max(1, window); i++) {
    const w = addWeeks(week, -i);
    if (!known.has(w)) continue;
    sum += counts?.get(w) ?? 0;
    k++;
  }
  return k ? sum / k : 0;
}

/** A weekly series per org.  */
export type OrgSeries = { org: string; values: (number | null)[] }[];

/** The review chart's ratio: for each org, `num` ÷ `den` week by week (each
 * already a running mean, so this is the ratio of the means). The two must
 * come from the same weeks and org choices (see ratioOrgs); an org missing
 * from either is left out. A week is null (a gap) where the denominator is 0,
 * or, given `numKnown`, where the numerator has no data in its window of
 * `smoothing` weeks (unclassified weeks, for addressed comments). */
export function ratioSeries(
  num: OrgSeries,
  den: OrgSeries,
  weeks: readonly string[],
  smoothing = 1,
  numKnown?: ReadonlySet<string>,
): OrgSeries {
  const byOrg = new Map(den.map((s) => [s.org, s.values]));
  const known = weeks.map((w) => {
    if (!numKnown) return true;
    for (let i = 0; i < Math.max(1, smoothing); i++) if (numKnown.has(addWeeks(w, -i))) return true;
    return false;
  });
  return num
    .filter((s) => byOrg.has(s.org))
    .map((s) => {
      const d = byOrg.get(s.org)!;
      return {
        org: s.org,
        values: s.values.map((v, i) => (known[i] && v !== null && d[i] ? v / d[i]! : null)),
      };
    });
}

/** The orgs two series lists both name (OTHER aside): with only these
 * nameable, both lists fold the same orgs into OTHER, so their OTHER series
 * can be divided too. */
export function ratioOrgs(a: OrgSeries, b: OrgSeries): Set<string> {
  const inB = new Set(b.map((s) => s.org));
  return new Set(a.map((s) => s.org).filter((o) => o !== OTHER && inB.has(o)));
}

/** Browsers the usage chart always plots: Meta's in-app browsers are small
 * next to Chrome but are its whole usage credit, so they never fold into
 * "Other". */
export const ALWAYS_CHARTED_BROWSERS = ['Facebook', 'Instagram'];

/** Radar browsers to chart individually: `always` plus the `n` others with
 * the highest peak weekly share (peak, not mean, so a recent riser like
 * ChromeDerivative shows up), in descending order of peak. Everything else
 * is "Other". */
export function topBrowsers(radar: RadarWeekly, n = 6, always: string[] = ALWAYS_CHARTED_BROWSERS): string[] {
  const peak = new Map<string, number>();
  for (const m of radar.values()) {
    for (const [b, s] of m) peak.set(b, Math.max(peak.get(b) ?? 0, s));
  }
  const ranked = [...peak].sort((a, b) => b[1] - a[1]).map(([b]) => b);
  const top = ranked.filter((b) => !always.includes(b)).slice(0, n);
  return ranked.filter((b) => top.includes(b) || always.includes(b));
}

/** One browser's weekly share, or the remainder for OTHER. */
export function browserShare(radar: RadarWeekly, week: string, browser: string, top: string[]): number | null {
  const m = radar.get(week);
  if (!m) return null;
  if (browser !== OTHER) return m.get(browser) ?? 0;
  let rest = 0;
  for (const [b, s] of m) if (!top.includes(b)) rest += s;
  return rest;
}

/** Compare ISO week labels like 2026-W44. */
export function compareWeeks(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

/** summaries/reviewer_weekly.json: every reviewer's in-scope counts per
 * week, one row per (week, account, org). Compact: each row is
 * [account_id, index into `orgs`, comments, cls, chars]. Orgs are resolved
 * before org_weekly's fold of `meta.fold_into_other` into "Other". */
export type ReviewerRow = [account: number, org: number, comments: number, cls: number, chars: number,
  addressed?: number, commits?: number, files?: number];

/** Column of each metric in ReviewerRow and AreaBoard rows. Files written
 * before the addressed metric have no column 5; it reads as 0. Commits
 * (column 6) are only in the boards authorBoard and commitBoard build. */
const METRIC_INDEX: Record<Metric, 2 | 3 | 4 | 5 | 6> = { comments: 2, cls: 3, chars: 4, addressed: 5, commits: 6 };

/** summaries/author_weekly.json: [account, org, commits, files] rows per
 * week, with accounts, emails and orgs as in reviewer_weekly.json. files is
 * every file those commits change (absent in files written before it). */
export interface AuthorFile {
  meta: { fold_into_other: string[]; [k: string]: unknown };
  orgs: string[];
  accounts: Record<string, string>;
  emails?: Record<string, string>;
  weeks: Record<string, [account: number, org: number, commits: number, files?: number][]>;
}

/** The commit authors as a ReviewerBoard whose rows have only commits
 * (column 6) and the files they change (column 7), so the per-person
 * sections read it like the reviewers'. Every
 * row counts as the author's org: their org is the one most of their commits
 * resolve to. */
export function authorBoard(file: AuthorFile): ReviewerBoard {
  const weeks: Record<string, ReviewerRow[]> = {};
  for (const [w, rows] of Object.entries(file.weeks)) weeks[w] = rows.map(([a, o, n, k]) => [a, o, 0, 0, 0, 0, n, k ?? 0]);
  return { meta: { ...file.meta, authors: true }, orgs: file.orgs, accounts: file.accounts, emails: file.emails, weeks };
}

/** summaries/area_commits.json: [node, org, commits] rows per week, indexed
 * like the area_weekly.json it names. */
export interface AreaCommitsFile {
  meta: { areas_generated_at: string; [k: string]: unknown };
  weeks: Record<string, [node: number, org: number, commits: number][]>;
}

/** The commits by directory as a DirBoard sharing `areas`' tree, nodes and
 * orgs, whose rows have only commits (column 6). Null if the file was made
 * with another area_weekly.json, whose indexes may not match. */
export function commitBoard(areas: DirBoard, file: AreaCommitsFile): DirBoard | null {
  if (!areas.meta.generated_at || file.meta.areas_generated_at !== areas.meta.generated_at) return null;
  const weeks: DirBoard['weeks'] = {};
  for (const [w, rows] of Object.entries(file.weeks)) weeks[w] = rows.map(([n, o, c]) => [n, o, 0, 0, 0, 0, c]);
  const board = { ...areas, weeks };
  // The same tree: share its cached paths and children.
  const tree = treeCache.get(areas);
  if (tree) treeCache.set(board, tree);
  return board;
}

export interface ReviewerBoard {
  meta: { fold_into_other: string[]; [k: string]: unknown };
  orgs: string[];
  accounts: Record<string, string>;
  /** Account id -> Gerrit email (public). Absent in files written before
   * emails were added. */
  emails?: Record<string, string>;
  weeks: Record<string, ReviewerRow[]>;
}

export interface LeaderboardRow {
  /** Gerrit account id. */
  id: number;
  name: string;
  email: string | null;
  org: string;
  value: number;
}

/** Leaderboard lengths the page offers; the first is the default. 'all' is
 * every reviewer with a nonzero value: reviewer_weekly.json already holds
 * them all, so it needs no further data. */
export const LEADERBOARD_SIZES = [25, 50, 100, 200, 'all'] as const;
export type LeaderboardSize = (typeof LEADERBOARD_SIZES)[number];
export const LEADERBOARD_SIZE: LeaderboardSize = LEADERBOARD_SIZES[0];

/** The row limit a leaderboard size stands for. */
export const leaderboardLimit = (size: LeaderboardSize): number => (size === 'all' ? Infinity : size);

/** Axis ticks from 0 up to a round number at or above `max`: about six steps
 * of 1, 2 or 5 × 10ⁿ, as Chart.js picks them. The last tick is the axis end. */
export function niceTicks(max: number, target = 6): number[] {
  if (!(max > 0)) return [0, 1];
  const rough = max / target;
  const mag = 10 ** Math.floor(Math.log10(rough));
  const r = rough / mag;
  const step = (r <= 1 ? 1 : r <= 2 ? 2 : r <= 5 ? 5 : 10) * mag;
  const n = Math.ceil(max / step - 1e-9);
  return Array.from({ length: n + 1 }, (_, i) => Number((i * step).toPrecision(12)));
}

export const GERRIT = 'https://chromium-review.googlesource.com';

/** A Gerrit search page for the terms (ANDed). Each term is URL-encoded,
 * keeping `@ : / ( )` readable (Gerrit's UI takes them as is); spaces become
 * `+`, as in Gerrit's own links. */
export const gerritQueryUrl = (terms: string[]): string =>
  `${GERRIT}/q/` +
  terms
    .map((t) =>
      encodeURIComponent(t).replace(/%40/g, '@').replace(/%3A/g, ':').replace(/%2F/g, '/').replace(/%20/g, '+'),
    )
    .join('+');

/** Days after a range's end that its Gerrit links still look at. Gerrit can
 * only filter by when a CL last changed (`after:`/`before:`), not by when a
 * comment was written, and a CL reviewed in a range usually closes, its last
 * update, within a few weeks. */
export const LINK_SLACK_DAYS = 28;

/** Gerrit terms for CLs that changed during the range: from the day before
 * its Monday (time-zone leeway) to LINK_SLACK_DAYS after its Sunday, with no
 * end when that's still to come. None without a range. */
export function gerritDateTerms(range?: WeekRange, now = new Date()): string[] {
  if (!range) return [];
  const after = new Date(weekMonday(range.from).getTime() - DAY_MS);
  const before = new Date(weekSunday(range.to).getTime() + (1 + LINK_SLACK_DAYS) * DAY_MS);
  return [`after:${isoDate(after)}`, ...(before < now ? [`before:${isoDate(before)}`] : [])];
}

/** The CLs the reviewer commented on (votes count too) and doesn't own, on
 * Chromium Gerrit, or null without an email. Not `reviewedby:`, which only
 * matches CLs where the reviewer posted after the owner's latest message. */
export const gerritReviewsUrl = (email: string | null, range?: WeekRange, now?: Date): string | null =>
  email ? gerritQueryUrl([`commentby:${email}`, `-owner:${email}`, ...gerritDateTerms(range, now)]) : null;

const asList = (weeks: string | string[]) => (typeof weeks === 'string' ? [weeks] : weeks);

/** The top `n` reviewers by the metric, summed over the given week(s):
 * exact totals, since the board holds every reviewer. Ties are broken by
 * account id so the order is stable; reviewers with 0 for the metric are left
 * out. A reviewer's org is the one most of their comments in those weeks
 * resolve to (ties: alphabetical). Pass `n = Infinity` for every reviewer,
 * e.g. to filter by org before taking the top few. */
export function topReviewers(
  board: ReviewerBoard,
  weeks: string | string[],
  metric: Metric,
  n: number = leaderboardLimit(LEADERBOARD_SIZE),
): LeaderboardRow[] {
  return reviewerTotals(board, weeks, metric)
    .filter((r) => r.value > 0)
    .sort((x, y) => y.value - x.value || x.id - y.id)
    .slice(0, n)
    .map(({ id, value, org }) => ({
      id,
      name: board.accounts[id] ?? `Account ${id}`,
      email: board.emails?.[id] ?? null,
      org,
      value,
    }));
}

/** The orgs of leaderboard rows by their reviewers' summed value, largest
 * first (ties: alphabetical): the leaderboard's organization choices. */
export function orgsByValue(rows: { org: string; value: number }[]): string[] {
  const sum = new Map<string, number>();
  for (const r of rows) sum.set(r.org, (sum.get(r.org) ?? 0) + r.value);
  return [...sum].sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : 1)).map(([org]) => org);
}

/** Results of a pure function of a (never mutated) board, keyed by `key`;
 * the last few per board and function are kept. A render asks for the same
 * sums several times (e.g. reviewer totals for the spread, per-review and
 * leaderboard sections), and switching back to a metric asks for them again.
 * Callers must not mutate what they get. */
const memoStore = new WeakMap<object, Map<string, unknown>>();
const MEMO_SIZE = 24;
function memo<R>(board: object, fn: string, key: string, make: () => R): R {
  let m = memoStore.get(board);
  if (!m) memoStore.set(board, (m = new Map()));
  const k = `${fn}|${key}`;
  if (m.has(k)) {
    const v = m.get(k) as R;
    m.delete(k);
    m.set(k, v);
    return v;
  }
  const v = make();
  m.set(k, v);
  if (m.size > MEMO_SIZE) m.delete(m.keys().next().value!);
  return v;
}

/** Every reviewer with a row in the given week(s), with their total for the
 * metric (possibly 0), their review comments, and their org: the one most of
 * their comments in those weeks resolve to (ties: alphabetical). Unordered.
 * `reviews` is their reviewed CLs (CLs they commented on, in the week each
 * closed). A row can have 0 comments: reviewed CLs count in the week the CL
 * closed. */
export function reviewerTotals(
  board: ReviewerBoard,
  weeks: string | string[],
  metric: Metric,
): { id: number; value: number; comments: number; reviews: number; org: string }[] {
  const list = asList(weeks);
  return memo(board, 'reviewerTotals', `${metric}|${list.join()}`, () => computeReviewerTotals(board, list, metric)).slice();
}

function computeReviewerTotals(
  board: ReviewerBoard,
  weeks: string[],
  metric: Metric,
): { id: number; value: number; comments: number; reviews: number; org: string }[] {
  const col = METRIC_INDEX[metric];
  const by = new Map<number, { value: number; comments: number; reviews: number; orgCount: Map<number, number> }>();
  for (const w of weeks) {
    for (const r of board.weeks[w] ?? []) {
      let t = by.get(r[0]);
      if (!t) by.set(r[0], (t = { value: 0, comments: 0, reviews: 0, orgCount: new Map() }));
      t.value += r[col] ?? 0;
      t.comments += r[2];
      t.reviews += r[3];
      t.orgCount.set(r[1], (t.orgCount.get(r[1]) ?? 0) + r[2] + (r[6] ?? 0));
    }
  }
  const orgOf = (orgCount: Map<number, number>) => {
    let best = -1;
    let bestN = -1;
    for (const [o, c] of orgCount) {
      if (c > bestN || (c === bestN && board.orgs[o] < board.orgs[best])) [best, bestN] = [o, c];
    }
    return board.orgs[best];
  };
  return [...by].map(([id, t]) => ({
    id,
    value: t.value,
    comments: t.comments,
    reviews: t.reviews,
    org: orgOf(t.orgCount),
  }));
}

/** Quantile `p` (0–1) of ascending `sorted`, interpolated between ranks. */
export function quantile(sorted: readonly number[], p: number): number {
  if (!sorted.length) return 0;
  const i = (sorted.length - 1) * p;
  const lo = Math.floor(i);
  const hi = Math.ceil(i);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (i - lo);
}

/** Summary of per-reviewer values: how many, the quartiles, and how much of
 * the total the top 10% of reviewers (at least one) account for. */
export function distributionStats(values: readonly number[]): {
  n: number;
  total: number;
  q1: number;
  median: number;
  q3: number;
  top10: number;
  top10Share: number;
} {
  const sorted = [...values].sort((a, b) => a - b);
  const n = sorted.length;
  const total = sorted.reduce((s, v) => s + v, 0);
  const top10 = n ? Math.max(1, Math.round(n / 10)) : 0;
  const topSum = sorted.slice(n - top10).reduce((s, v) => s + v, 0);
  return {
    n,
    total,
    q1: quantile(sorted, 0.25),
    median: quantile(sorted, 0.5),
    q3: quantile(sorted, 0.75),
    top10,
    top10Share: total ? topSum / total : 0,
  };
}

export interface OrgSpread {
  org: string;
  /** The org's reviewers, by value ascending. */
  reviewers: { id: number; value: number }[];
  stats: ReturnType<typeof distributionStats>;
}

/** Reviewers grouped by org for the per-reviewer spread: the `names` orgs
 * (see namedOrgs) that have reviewers, by their total (ties: more reviewers,
 * then name), never one folded into Other, largest first; then OTHER for
 * everyone else if anyone is left.
 * With `order`, its orgs that have reviewers get rows instead, in that order
 * (so two spreads can share rows), and everyone else is OTHER. */
export function orgSpreads(
  rows: readonly { id: number; value: number; org: string }[],
  fold: readonly string[] = [],
  names: readonly string[] = [],
  order?: readonly string[],
): OrgSpread[] {
  const folded = new Set(fold);
  const by = new Map<string, { id: number; value: number }[]>();
  for (const r of rows) {
    const org = folded.has(r.org) ? OTHER : r.org;
    const list = by.get(org);
    if (list) list.push({ id: r.id, value: r.value });
    else by.set(org, [{ id: r.id, value: r.value }]);
  }
  const sum = (l: { value: number }[]) => l.reduce((s, r) => s + r.value, 0);
  const ranked = [...by]
    .filter(([org]) => org !== OTHER)
    .sort((a, b) => sum(b[1]) - sum(a[1]) || b[1].length - a[1].length || (a[0] < b[0] ? -1 : 1));
  const top = order
    ? order.filter((o) => o !== OTHER && by.has(o)).map((o) => [o, by.get(o)!] as [string, { id: number; value: number }[]])
    : ranked.filter(([o]) => names.includes(o));
  const shown = new Set(top.map(([o]) => o));
  const rest = [...(by.get(OTHER) ?? []), ...ranked.filter(([o]) => !shown.has(o)).flatMap(([, l]) => l)];
  const groups = [...top, ...(rest.length ? [[OTHER, rest] as [string, typeof rest]] : [])];
  return groups.map(([org, list]) => {
    const reviewers = [...list].sort((a, b) => a.value - b.value || a.id - b.id);
    return { org, reviewers, stats: distributionStats(reviewers.map((r) => r.value)) };
  });
}

/** Reviewers need at least this many reviewed CLs over the range to get a
 * per-review figure: with fewer, one CL's thread decides it. */
export const PER_REVIEW_MIN = 3;

/** What the per-review spread divides by reviewed CLs: the metric itself,
 * or review comments when the metric is reviewed CLs. */
export const perReviewMetric = (metric: Metric): Metric =>
  metric === 'cls' || metric === 'commits' ? 'comments' : metric;

export interface OrgPerReviewSpread extends OrgSpread {
  /** The row's pooled figure: its reviewers' summed metric ÷ their summed
   * reviewed CLs, i.e. per review rather than per reviewer. */
  pooled: number;
}

/** Each reviewer's metric per review over the weeks (see perReviewMetric),
 * grouped into the given org rows (see orgSpreads `order`). A review is one
 * reviewer's comments on one CL, so a CL two reviewers commented on is two
 * reviews. Reviewers with under `minReviews` reviewed CLs, or with no review
 * comments in the weeks, are left out. Comments count in the week written
 * and reviewed CLs in the week closed, so a range's edges are approximate. */
export function orgPerReviewSpreads(
  board: ReviewerBoard,
  weeks: string | string[],
  metric: Metric,
  order: readonly string[],
  minReviews = PER_REVIEW_MIN,
): OrgPerReviewSpread[] {
  const rows = reviewerTotals(board, weeks, perReviewMetric(metric)).filter(
    (r) => r.reviews >= minReviews && r.comments > 0,
  );
  const byId = new Map(rows.map((r) => [r.id, r]));
  const spreads = orgSpreads(
    rows.map((r) => ({ id: r.id, value: r.value / r.reviews, org: r.org })),
    board.meta.fold_into_other ?? [],
    [],
    order,
  );
  return spreads.map((s) => {
    let num = 0;
    let den = 0;
    for (const { id } of s.reviewers) {
      const r = byId.get(id)!;
      num += r.value;
      den += r.reviews;
    }
    return { ...s, pooled: den ? num / den : 0 };
  });
}

/** Each author's files changed per commit over the weeks (an author board,
 * see authorBoard), grouped into the given org rows like
 * orgPerReviewSpreads: a rough measure of how big their changes are. Authors
 * with under `minCommits` commits are left out; `pooled` is a row's files
 * over its commits. */
export function orgFilesPerCommitSpreads(
  authors: ReviewerBoard,
  weeks: string | string[],
  order: readonly string[],
  minCommits = PER_REVIEW_MIN,
): OrgPerReviewSpread[] {
  const files = new Map<number, number>();
  for (const w of asList(weeks)) for (const r of authors.weeks[w] ?? []) files.set(r[0], (files.get(r[0]) ?? 0) + (r[7] ?? 0));
  const rows = reviewerTotals(authors, weeks, 'commits').filter((r) => r.value >= minCommits);
  const commitsOf = new Map(rows.map((r) => [r.id, r.value]));
  const spreads = orgSpreads(
    rows.map((r) => ({ id: r.id, value: (files.get(r.id) ?? 0) / r.value, org: r.org })),
    authors.meta.fold_into_other ?? [],
    [],
    order,
  );
  return spreads.map((s) => {
    let num = 0;
    let den = 0;
    for (const { id } of s.reviewers) {
      num += files.get(id) ?? 0;
      den += commitsOf.get(id)!;
    }
    return { ...s, pooled: den ? num / den : 0 };
  });
}

/** One calendar month of monthlyTotals. */
export interface MonthTotal {
  /** "Mar 2026". */
  label: string;
  total: number;
  /** Index of its middle week in the weeks given. */
  at: number;
  /** Its first week in the weeks given. */
  week: string;
  /** Only part of the month is in the weeks given (a range starting or ending mid-month). */
  partial: boolean;
}

/** Weekly counts (`values[i]` in `weeks[i]`, consecutive weeks) as calendar
 * months, by each week's Thursday (weekMonth): each month's total, and for
 * each week the index of its month. */
export function monthlyTotals(
  weeks: readonly string[],
  values: readonly number[],
): { months: MonthTotal[]; monthOf: number[] } {
  const months: (MonthTotal & { first: number; last: number })[] = [];
  const monthOf: number[] = [];
  let key = '';
  weeks.forEach((w, i) => {
    const m = weekMonth(w);
    const k = `${m.year}-${m.month}`;
    if (k !== key) {
      key = k;
      months.push({ label: `${MONTHS[m.month]} ${m.year}`, total: 0, at: i, week: w, partial: false,
        first: i, last: i });
    }
    const cur = months[months.length - 1];
    cur.total += values[i] ?? 0;
    cur.last = i;
    monthOf.push(months.length - 1);
  });
  months.forEach((m) => {
    m.at = Math.floor((m.first + m.last) / 2);
    const same = (w: string) => { const x = weekMonth(w); const y = weekMonth(weeks[m.first]); return x.month === y.month && x.year === y.year; };
    m.partial = (m.first === 0 && same(addWeeks(weeks[0], -1))) ||
      (m.last === weeks.length - 1 && same(addWeeks(weeks[m.last], 1)));
  });
  return { months: months.map(({ first: _f, last: _l, ...m }) => m), monthOf };
}

/** A person the leaderboard's search box offers. */
export interface PersonMatch {
  id: number;
  name: string;
  email: string | null;
  /** Review comments plus commits over the weeks given: how matches are ranked. */
  activity: number;
}

/** Most people the search box suggests. */
export const SEARCH_MAX = 10;

/** People whose name or email matches `query` (case-insensitive), from the
 * reviewer board and, if loaded, the author board: first those whose name or
 * email starts with it, then those with a word that does, then any other
 * containing it. Within each, the most active over `weeks` first (review
 * comments plus commits), then by name. At most `max`; none for a blank query. */
export function findPeople(
  reviewers: ReviewerBoard,
  authors: ReviewerBoard | undefined,
  query: string,
  weeks: readonly string[],
  max = SEARCH_MAX,
): PersonMatch[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  const activity = memo(reviewers, 'searchActivity', `${authors ? 1 : 0}|${weeks.join()}`, () => {
    const out = new Map<number, number>();
    for (const w of weeks) {
      for (const r of reviewers.weeks[w] ?? []) out.set(r[0], (out.get(r[0]) ?? 0) + r[2]);
      for (const r of authors?.weeks[w] ?? []) out.set(r[0], (out.get(r[0]) ?? 0) + (r[6] ?? 0));
    }
    return out;
  });
  const ids = new Set([...Object.keys(reviewers.accounts), ...Object.keys(authors?.accounts ?? {})]);
  const found: (PersonMatch & { tier: number })[] = [];
  for (const key of ids) {
    const id = Number(key);
    const name = reviewers.accounts[key] ?? authors?.accounts[key] ?? `Account ${id}`;
    const email = reviewers.emails?.[key] ?? authors?.emails?.[key] ?? null;
    const fields = [name.toLowerCase(), (email ?? '').toLowerCase()];
    let tier = 3;
    if (fields.some((f) => f.startsWith(q))) tier = 0;
    else if (fields.some((f) => f.split(/[\s.@_+-]+/).some((word) => word.startsWith(q)))) tier = 1;
    else if (fields.some((f) => f.includes(q))) tier = 2;
    if (tier < 3) found.push({ id, name, email, activity: activity.get(id) ?? 0, tier });
  }
  found.sort((a, b) => a.tier - b.tier || b.activity - a.activity || (a.name < b.name ? -1 : a.name > b.name ? 1 : a.id - b.id));
  return found.slice(0, max).map(({ tier: _t, ...m }) => m);
}

/** How hover cards name a reviewer: their Gerrit email, which is shorter
 * than a name plus affiliation and can be searched for directly; their name
 * if no email is known (files from before emails were added). */
export function reviewerHandle(board: ReviewerBoard, account: number): string {
  return board.emails?.[account] ?? board.accounts[account] ?? `Account ${account}`;
}

/** One person's weekly review comments and addressed comments over `weeks`
 * (addressed is null for weeks not in `classified`), their commits if
 * `authors` is given (else null), and their org: the one most of their
 * comments and commits in those weeks resolve to. */
export function reviewerSeries(
  board: ReviewerBoard,
  account: number,
  weeks: string[],
  classified: ReadonlySet<string>,
  authors?: ReviewerBoard,
): { name: string; email: string | null; org: string | null; comments: number[]; addressed: (number | null)[];
  commits: number[] | null } {
  const orgCount = new Map<string, number>();
  const comments: number[] = [];
  const addressed: (number | null)[] = [];
  const commits: number[] = [];
  for (const w of weeks) {
    let c = 0;
    let a = 0;
    let k = 0;
    for (const r of board.weeks[w] ?? []) {
      if (r[0] !== account) continue;
      c += r[2];
      a += r[5] ?? 0;
      orgCount.set(board.orgs[r[1]], (orgCount.get(board.orgs[r[1]]) ?? 0) + r[2]);
    }
    for (const r of authors?.weeks[w] ?? []) {
      if (r[0] !== account) continue;
      k += r[6] ?? 0;
      orgCount.set(authors!.orgs[r[1]], (orgCount.get(authors!.orgs[r[1]]) ?? 0) + (r[6] ?? 0));
    }
    comments.push(c);
    addressed.push(classified.has(w) ? a : null);
    commits.push(k);
  }
  let org: string | null = null;
  let best = -1;
  for (const [o, c] of orgCount) {
    if (c > best || (c === best && org !== null && o < org)) [org, best] = [o, c];
  }
  return {
    name: board.accounts[account] ?? authors?.accounts[account] ?? `Account ${account}`,
    email: board.emails?.[account] ?? authors?.emails?.[account] ?? null,
    org,
    comments,
    addressed,
    commits: authors ? commits : null,
  };
}

/** The orgs on a leaderboard, most reviewers first (ties: the org whose
 * first reviewer ranks higher), with how many reviewers each has. */
export function leaderboardOrgs(rows: LeaderboardRow[]): { org: string; reviewers: number }[] {
  const count = new Map<string, number>();
  for (const r of rows) count.set(r.org, (count.get(r.org) ?? 0) + 1);
  return [...count].map(([org, reviewers]) => ({ org, reviewers })).sort((a, b) => b.reviewers - a.reviewers);
}

/** Distinct reviewers over the given week(s): in total, and per org as
 * org_weekly.json reports orgs (fold_into_other folded into "Other"). A
 * reviewer who reviewed for two orgs counts once in each. */
export function distinctReviewers(
  board: ReviewerBoard,
  weeks: string | string[],
): { total: number; byOrg: Map<string, number> } {
  const list = asList(weeks);
  const r = memo(board, 'distinctReviewers', list.join(), () => computeDistinctReviewers(board, list));
  return { total: r.total, byOrg: new Map(r.byOrg) };
}

function computeDistinctReviewers(board: ReviewerBoard, weeks: string[]): { total: number; byOrg: Map<string, number> } {
  const fold = new Set(board.meta.fold_into_other ?? []);
  const orgName = board.orgs.map((o) => (fold.has(o) ? OTHER : o));
  const all = new Set<number>();
  const sets = new Map<string, Set<number>>();
  for (const w of weeks) {
    for (const r of board.weeks[w] ?? []) {
      all.add(r[0]);
      const org = orgName[r[1]];
      let s = sets.get(org);
      if (!s) sets.set(org, (s = new Set()));
      s.add(r[0]);
    }
  }
  return { total: all.size, byOrg: new Map([...sets].map(([o, s]) => [o, s.size])) };
}

// ---------------------------------------------------------------------------
// Date ranges. Every view on the page covers one inclusive range of ISO weeks.

export interface WeekRange {
  from: string;
  to: string;
}

const DAY_MS = 86_400_000;

/** ISO week label (e.g. 2026-W44) of a date, read in UTC. */
export function isoWeekOf(d: Date): string {
  const day = (d.getUTCDay() + 6) % 7; // Monday = 0
  const thursday = Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate() - day + 3);
  const year = new Date(thursday).getUTCFullYear();
  const week = Math.floor((thursday - Date.UTC(year, 0, 1)) / DAY_MS / 7) + 1;
  return `${year}-W${String(week).padStart(2, '0')}`;
}

/** weekMonday's results (ms): it's called many times per render, for a few hundred weeks. */
const mondayCache = new Map<string, number>();

/** Monday (UTC midnight) of an ISO week label. */
export function weekMonday(week: string): Date {
  let t = mondayCache.get(week);
  if (t === undefined) {
    const m = /^(\d{4})-W(\d{2})$/.exec(week);
    if (!m) throw new Error(`not an ISO week: ${week}`);
    const jan4 = Date.UTC(Number(m[1]), 0, 4);
    const jan4Day = (new Date(jan4).getUTCDay() + 6) % 7;
    t = jan4 + (Number(m[2]) * 7 - 7 - jan4Day) * DAY_MS;
    mondayCache.set(week, t);
  }
  return new Date(t);
}

/** Sunday (UTC midnight) of an ISO week label. */
export const weekSunday = (week: string) => new Date(weekMonday(week).getTime() + 6 * DAY_MS);

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const shortDate = (d: Date) => `${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}`;

/** Tooltip title for a week, e.g. "Oct 26 – Nov 1, 2026". */
export const weekTitle = (week: string) =>
  `${shortDate(weekMonday(week))} – ${shortDate(weekSunday(week))}, ${weekSunday(week).getUTCFullYear()}`;

/** Year and month a week belongs to, by its Thursday (as for ISO years). */
export function weekMonth(week: string): { year: number; month: number } {
  const t = new Date(weekMonday(week).getTime() + 3 * DAY_MS);
  return { year: t.getUTCFullYear(), month: t.getUTCMonth() };
}

/** Month labels for a weekly time axis: the indices of `weeks` that start a
 * month (by Thursday), with labels like "Nov 2025", "Dec", "Jan 2026". The
 * year is shown on the first tick and wherever it changes. Months are thinned
 * to every 2, 3, 6 or 12 (aligned to the calendar, so quarters start in Jan,
 * Apr, …) to keep at most `maxTicks`, or evenly when no tick would land on
 * such a month. A range inside one month gets one tick on
 * its first week. */
export function monthTicks(weeks: string[], maxTicks = 12): { index: number; label: string }[] {
  const starts: { index: number; year: number; month: number }[] = [];
  weeks.forEach((w, i) => {
    const m = weekMonth(w);
    const prev = i > 0 ? weekMonth(weeks[i - 1]) : null;
    if (!prev || prev.month !== m.month || prev.year !== m.year) starts.push({ index: i, ...m });
  });
  // The first week opens a month only if it's that month's first week.
  if (starts.length && weekMonth(addWeeks(weeks[0], -1)).month === starts[0].month && starts.length > 1) {
    starts.shift();
  }
  const step = [1, 2, 3, 6, 12].find((s) => starts.filter((x) => x.month % s === 0).length <= maxTicks) ?? 12;
  let kept = step === 1 ? starts : starts.filter((x) => x.month % step === 0);
  // Ticks that never land on a calendar-aligned month (e.g. quarters starting in
  // November): thin them evenly instead.
  if (!kept.length) {
    const every = Math.ceil(starts.length / Math.max(1, maxTicks));
    kept = starts.filter((_, i) => i % every === 0);
  }
  // The year goes on the first tick and wherever it changes.
  return kept.map((x, i) => ({
    index: x.index,
    label: i === 0 || x.year !== kept[i - 1].year ? `${MONTHS[x.month]} ${x.year}` : MONTHS[x.month],
  }));
}

/** yyyy-mm-dd, the value format of <input type="date">. */
export const isoDate = (d: Date) => d.toISOString().slice(0, 10);

/** Parse an <input type="date"> value as a UTC date; null if empty or invalid. */
export function parseIsoDate(s: string): Date | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(s)) return null;
  const d = new Date(`${s}T00:00:00Z`);
  return Number.isNaN(d.getTime()) ? null : d;
}

export const isWeek = (s: string | null): s is string => !!s && /^\d{4}-W\d{2}$/.test(s);

export const inRange = (week: string, r: WeekRange) => week >= r.from && week <= r.to;

/** The weeks of a list that fall in the range, sorted. */
export const weeksIn = (weeks: Iterable<string>, r: WeekRange) =>
  [...weeks].filter((w) => inRange(w, r)).sort(compareWeeks);

/** Number of ISO weeks in a range, counting both ends. */
export const rangeLength = (r: WeekRange) =>
  Math.round((weekMonday(r.to).getTime() - weekMonday(r.from).getTime()) / (7 * DAY_MS)) + 1;

/** The week `n` weeks after (or before, if negative) `week`. */
export const addWeeks = (week: string, n: number) =>
  isoWeekOf(new Date(weekMonday(week).getTime() + n * 7 * DAY_MS));

/** `full`: the widest range any data covers (the pickers' limits).
 * `common`: the range where review and usage data both exist (the default).
 * Falls back to the review weeks if the two don't overlap. */
export function dataRanges(reviewWeeks: string[], usageWeeks: string[]): { full: WeekRange; common: WeekRange } {
  const r = [...reviewWeeks].sort(compareWeeks);
  const u = [...usageWeeks].sort(compareWeeks);
  const all = [...r, ...u].sort(compareWeeks);
  const full = { from: all[0], to: all[all.length - 1] };
  if (!r.length || !u.length) return { full, common: r.length ? { from: r[0], to: r[r.length - 1] } : full };
  const from = r[0] > u[0] ? r[0] : u[0];
  const to = r[r.length - 1] < u[u.length - 1] ? r[r.length - 1] : u[u.length - 1];
  return { full, common: from <= to ? { from, to } : { from: r[0], to: r[r.length - 1] } };
}

/** Clamp a range into `bounds`, swapping the ends if they're reversed. */
export function clampRange(r: WeekRange, bounds: WeekRange): WeekRange {
  const clamp = (w: string) => (w < bounds.from ? bounds.from : w > bounds.to ? bounds.to : w);
  const a = clamp(r.from);
  const b = clamp(r.to);
  return a <= b ? { from: a, to: b } : { from: b, to: a };
}

/** One org's counts summed over some weeks, with shares recomputed from the
 * sums (as summarize.py does per week: org count ÷ the sum over all orgs).
 * Each CL closes in exactly one week, so summing CL counts is exact. Reviewer
 * counts are distinct per week and can't be summed (the
 * same person reviews in many weeks): pass `reviewers`, the distinct count per
 * org from distinctReviewers(). Without it, `reviewers` is the sum of the
 * weekly counts, which is exact only for a single week. */
export interface OrgTotals {
  org: string;
  reviewers: number;
  reviewed_cls: number;
  comments: number;
  review_chars: number;
  ai_comments: number;
  post_merge_comments: number;
  share_cls: number;
  share_comments: number;
  share_chars: number;
  addressed_comments: number;
  pending_comments: number;
  share_addressed: number;
  commits: number;
  share_commits: number;
}

export function orgTotals(summary: Summary, weeks: string[], reviewers?: Map<string, number>): OrgTotals[] {
  const set = new Set(weeks);
  const by = new Map<string, OrgTotals>();
  for (const r of summary.rows) {
    if (!set.has(r.iso_week)) continue;
    let t = by.get(r.org);
    if (!t) {
      t = {
        org: r.org, reviewers: 0, reviewed_cls: 0, comments: 0, review_chars: 0, ai_comments: 0,
        post_merge_comments: 0, share_cls: 0, share_comments: 0, share_chars: 0,
        addressed_comments: 0, pending_comments: 0, share_addressed: 0, commits: 0, share_commits: 0,
      };
      by.set(r.org, t);
    }
    t.reviewers += r.reviewers;
    t.reviewed_cls += r.reviewed_cls;
    t.comments += r.comments;
    t.review_chars += r.review_chars;
    t.ai_comments += r.ai_comments;
    t.post_merge_comments += r.post_merge_comments ?? 0;
    t.addressed_comments += r.addressed_comments ?? 0;
    t.pending_comments += r.pending_comments ?? 0;
    t.commits += r.commits ?? 0;
  }
  const out = [...by.values()];
  const sum = (k: 'reviewed_cls' | 'comments' | 'review_chars' | 'addressed_comments' | 'commits') =>
    out.reduce((s, t) => s + t[k], 0);
  const [cls, comments, chars, addressed, commits] =
    [sum('reviewed_cls'), sum('comments'), sum('review_chars'), sum('addressed_comments'), sum('commits')];
  for (const t of out) {
    if (reviewers) t.reviewers = reviewers.get(t.org) ?? 0;
    t.share_cls = cls ? t.reviewed_cls / cls : 0;
    t.share_comments = comments ? t.comments / comments : 0;
    t.share_chars = chars ? t.review_chars / chars : 0;
    t.share_addressed = addressed ? t.addressed_comments / addressed : 0;
    t.share_commits = commits ? t.commits / commits : 0;
  }
  return out;
}

/** Mean of an org's weekly usage share over the weeks with Radar data; null
 * if none have any. */
export function meanDerivedShare(radar: RadarWeekly, weeks: string[], browsers: string[]): number | null {
  const vals = weeks.map((w) => derivedShare(radar, w, browsers)).filter((v): v is number => v !== null);
  return vals.length ? vals.reduce((s, v) => s + v, 0) / vals.length : null;
}

type TotalCounts = Omit<WeeklyTotals, 'iso_week'>;

/** Weekly totals summed over some weeks; null if none of them have data. */
export function sumWeeklyTotals(totals: WeeklyTotals[], weeks: string[]): TotalCounts | null {
  const set = new Set(weeks);
  const rows = totals.filter((t) => set.has(t.iso_week));
  if (!rows.length) return null;
  const keys = ['main_cls', 'merged_cls', 'abandoned_cls', 'human_cls', 'bot_cls', 'human_cls_with_comments'] as const;
  return Object.fromEntries(keys.map((k) => [k, rows.reduce((s, r) => s + r[k], 0)])) as TotalCounts;
}

/** The "by organization" table shows the top TABLE_TOP_ORGS orgs plus every
 * org with a browser line in config/org_browsers.csv, wherever it ranks. */
export const TABLE_TOP_ORGS = 20;

/** Keep the first `n` of `items` (already in rank order) and, after them, any
 * later item for which `keep` is true. Order is preserved. */
export function trimRanked<T>(items: T[], n: number, keep: (item: T) => boolean): T[] {
  return items.filter((it, i) => i < n || keep(it));
}

/** Scale for the directory chart's volume bars, with a broken axis when a
 * few bars dwarf the rest. Looking at the largest values in descending order,
 * if one of the top `maxBroken` is more than `gap` times the next, the scale
 * ends at `headroom` times that next value and the bars above it are drawn
 * truncated (torn). Returns the scale's maximum and how many of the largest
 * values exceed it (0: a plain scale ending at the largest value). */
export function barScale(
  values: number[],
  { gap = 2, maxBroken = 3, headroom = 1.25 } = {},
): { max: number; broken: number } {
  const v = [...values].sort((a, b) => b - a);
  for (let j = 1; j <= Math.min(maxBroken, v.length - 1); j++) {
    if (v[j] > 0 && v[j - 1] > gap * v[j]) return { max: v[j] * headroom, broken: j };
  }
  return { max: v[0] ?? 0, broken: 0 };
}

// ---------------------------------------------------------------------------
// Contribution by directory (summaries/area_weekly.json): a tree to drill into.

/** Every review comment, in scope or not, as a directory tree. Roots are the
 * top-level directories, plus `area` prefixes from config/paths.txt (e.g.
 * third_party/blink/), "(no file)" and "(top-level files)"; below them, the directories with the
 * most comments (meta.dir_limit) and their ancestors. Each week's rows are
 * [node, org, comments, cls, chars] for a node's own bucket: files directly in
 * it, or in a directory below it that isn't in the tree. A node's total is
 * the sum over its subtree, so children add up to their parent; reviewed CLs
 * count (CL, bucket) pairs. Orgs are folded like org_weekly. */
export interface DirBoard {
  meta: {
    path_rules: PathRule[];
    unplaced: string;
    root_files: string;
    dir_limit: number;
    generated_at?: string;
    [k: string]: unknown;
  };
  orgs: string[];
  /** [parent index or -1, label (a root's path, else the segment below its parent), included]. */
  nodes: [parent: number, label: string, included: 0 | 1][];
  weeks: Record<string, [node: number, org: number, comments: number, cls: number, chars: number, addressed?: number,
    commits?: number][]>;
}

/** Rows each tree level shows before an "other" row, and how many more each
 * expansion of "other" reveals. */
export const DIR_PAGE = 20;

/** The board's full paths and child lists, computed once per board. */
const treeCache = new WeakMap<DirBoard, { paths: string[]; children: number[][]; roots: number[] }>();

export function dirTree(board: DirBoard) {
  let t = treeCache.get(board);
  if (!t) {
    const paths: string[] = [];
    const children: number[][] = board.nodes.map(() => []);
    const roots: number[] = [];
    board.nodes.forEach(([parent, label], i) => {
      paths.push(parent < 0 ? label : paths[parent] + label);
      if (parent < 0) roots.push(i);
      else children[parent].push(i);
    });
    t = { paths, children, roots };
    treeCache.set(board, t);
  }
  return t;
}

export interface DirTotals {
  /** Per node: its subtree's total and per-org split. */
  total: Float64Array;
  byOrg: (node: number) => Map<string, number> | undefined;
  /** Per node: its own bucket's total and per-org split. */
  own: Float64Array;
  ownByOrg: (node: number) => Map<string, number> | undefined;
  /** Per node: the part of its subtree's total that is in scope. */
  inc: Float64Array;
}

/** Sum the metric over the given weeks into every node's subtree. Orgs outside
 * `orgs` count as OTHER. `only`, if given, keeps just the orgs it accepts
 * (others aren't counted at all).
 *
 * Fast path (this runs many times per render, over ~70k rows a year): each
 * row goes into its node's own bucket only, per output org in a flat array;
 * subtree sums are then one bottom-up pass, since a parent always precedes
 * its children in `board.nodes`. The per-org maps are built on demand. */
export function dirTotals(
  board: DirBoard,
  weeks: string[],
  orgs: readonly string[],
  metric: Metric,
  only?: (org: string) => boolean,
): DirTotals {
  const col = METRIC_INDEX[metric];
  // Output orgs: the named ones, then OTHER. slotOf maps a board org index to
  // its output slot, or -1 when `only` drops it.
  const names = [...new Set(orgs)].filter((o) => o !== OTHER);
  names.push(OTHER);
  const S = names.length;
  const named = new Map(names.map((o, i) => [o, i]));
  const slotOf = board.orgs.map((o) => (only && !only(o) ? -1 : named.get(o) ?? S - 1));
  const nodes = board.nodes;
  const n = nodes.length;
  const own = new Float64Array(n);
  const ownSlots = new Float64Array(n * S);
  for (const w of weeks) {
    const rows = board.weeks[w];
    if (!rows) continue;
    for (let r = 0; r < rows.length; r++) {
      const row = rows[r];
      const v = row[col];
      if (!v) continue;
      const slot = slotOf[row[1]];
      if (slot < 0) continue;
      const i = row[0];
      own[i] += v;
      ownSlots[i * S + slot] += v;
    }
  }
  const total = own.slice();
  const slots = ownSlots.slice();
  // A node's own bucket is wholly in or out of scope (every rule directory is a node).
  const inc = new Float64Array(n);
  for (let i = 0; i < n; i++) if (nodes[i][2] === 1) inc[i] = own[i];
  for (let i = n - 1; i >= 0; i--) {
    const p = nodes[i][0];
    if (p < 0 || !total[i]) continue;
    total[p] += total[i];
    inc[p] += inc[i];
    for (let k = 0; k < S; k++) slots[p * S + k] += slots[i * S + k];
  }
  const mapper = (arr: Float64Array, sums: Float64Array) => {
    const cache = new Map<number, Map<string, number> | undefined>();
    return (i: number) => {
      if (cache.has(i)) return cache.get(i);
      let m: Map<string, number> | undefined;
      if (sums[i]) {
        m = new Map();
        for (let k = 0; k < S; k++) if (arr[i * S + k]) m.set(names[k], arr[i * S + k]);
      }
      cache.set(i, m);
      return m;
    };
  };
  return { total, byOrg: mapper(slots, total), own, ownByOrg: mapper(ownSlots, own), inc };
}

/** The `names` orgs (see namedOrgs) with rows in the given weeks across
 * every directory, in scope or not, ranked by the metric there, largest
 * first. With `nameable`, only orgs it accepts are kept. */
export function topDirOrgs(
  board: DirBoard,
  weeks: string[],
  metric: Metric,
  names: readonly string[],
  nameable?: (org: string) => boolean,
): string[] {
  // Per board org index; the same sums serve every `names` and `nameable`.
  const sums = memo(board, 'dirOrgSums', `${metric}|${weeks.join()}`, () => {
    const col = METRIC_INDEX[metric];
    const out = new Float64Array(board.orgs.length);
    const seen = new Uint8Array(board.orgs.length);
    for (const w of weeks) {
      const rows = board.weeks[w];
      if (!rows) continue;
      for (let r = 0; r < rows.length; r++) {
        const row = rows[r];
        out[row[1]] += row[col] ?? 0;
        seen[row[1]] = 1;
      }
    }
    return board.orgs.map((o, i) => [o, out[i], seen[i]] as const).filter(([, , s]) => s).map(([o, v]) => [o, v] as [string, number]);
  });
  return sums
    .filter(([org]) => org !== OTHER && names.includes(org) && (!nameable || nameable(org)))
    .sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : 1))
    .map(([org]) => org);
}

/** One visible row of the directory chart. */
export interface DirRow {
  /** Stable id, used to expand and collapse: "d<node>" for a directory,
   * "r<node>" for a directory's own bucket, "o:<parent key>:<offset>" for an
   * "other" group. */
  key: string;
  kind: 'dir' | 'rest' | 'other';
  /** The tree node a dir or rest row shows (none for "other"). */
  node?: number;
  depth: number;
  /** What the row shows: a root's path, a subdirectory's name, "rest of …"
   * or "N more". */
  label: string;
  /** Full path, or a description for rest and other rows. */
  title: string;
  /** The share of `value` that is in scope: 1, 0, or in between for a
   * directory (or "other" group) that is partly included. */
  included: number;
  value: number;
  byOrg: Map<string, number>;
  expandable: boolean;
  expanded: boolean;
  /** For "other": how many entries it holds, and which. */
  count?: number;
  members?: { kind: 'dir' | 'rest'; node: number }[];
}

interface Item {
  kind: 'dir' | 'rest';
  node: number;
  value: number;
  inc: number;
  byOrg: Map<string, number>;
}

/** The rows to show, given which keys are expanded. Each level lists its
 * entries largest first: DIR_PAGE of them, then an "other" row holding the
 * rest; expanding "other" lists its next DIR_PAGE entries (and a further
 * "other" if any are left), one level deeper. A directory with subdirectories
 * expands into them, plus a "rest of" row for its own bucket, so its children
 * add up to it. Each row carries the share of its value that is in scope. */
export function dirRows(board: DirBoard, t: DirTotals, expanded: ReadonlySet<string>, page = DIR_PAGE): DirRow[] {
  const { paths, children, roots } = dirTree(board);
  const out: DirRow[] = [];
  const byValue = (a: Item, b: Item) =>
    b.value - a.value || (a.kind === b.kind ? (paths[a.node] < paths[b.node] ? -1 : 1) : a.kind === 'dir' ? -1 : 1);
  const hasKids = (i: number) => children[i].some((c) => t.total[c] > 0);
  const empty = new Map<string, number>();
  const share = (it: Item) => (it.value ? it.inc / it.value : board.nodes[it.node][2]);
  const dirItem = (c: number): Item =>
    ({ kind: 'dir', node: c, value: t.total[c], inc: t.inc[c], byOrg: t.byOrg(c) ?? empty });

  const emit = (item: Item, depth: number) => {
    const i = item.node;
    if (item.kind === 'rest') {
      out.push({
        key: `r${i}`, kind: 'rest', node: i, depth, label: `rest of ${board.nodes[i][1]}`,
        title: `${paths[i]}: files directly in this directory, and subdirectories too small to list`,
        included: share(item), value: item.value, byOrg: item.byOrg, expandable: false, expanded: false,
      });
      return;
    }
    const key = `d${i}`;
    const expandable = hasKids(i);
    const open = expandable && expanded.has(key);
    out.push({
      key, kind: 'dir', node: i, depth, label: board.nodes[i][1], title: paths[i], included: share(item),
      value: item.value, byOrg: item.byOrg, expandable, expanded: open,
    });
    if (open) {
      const items: Item[] = children[i]
        .filter((c) => t.total[c] > 0)
        .map((c) => dirItem(c));
      if (t.own[i] > 0) {
        items.push({ kind: 'rest', node: i, value: t.own[i], inc: board.nodes[i][2] ? t.own[i] : 0,
          byOrg: t.ownByOrg(i) ?? empty });
      }
      group(items.sort(byValue), depth + 1, key, 0);
    }
  };

  // Lists `items` (sorted) from `offset`: a page of them, then "other".
  const group = (items: Item[], depth: number, parentKey: string, offset: number) => {
    const head = items.slice(0, page);
    const tail = items.slice(page);
    for (const it of head) emit(it, depth);
    if (!tail.length) return;
    const key = `o:${parentKey}:${offset + page}`;
    const byOrg = new Map<string, number>();
    for (const it of tail) for (const [o, v] of it.byOrg) byOrg.set(o, (byOrg.get(o) ?? 0) + v);
    const value = tail.reduce((s, it) => s + it.value, 0);
    const inc = tail.reduce((s, it) => s + it.inc, 0);
    const open = expanded.has(key);
    out.push({
      key, kind: 'other', depth, label: `${tail.length} more`, title: `${tail.length} more, smaller entries`,
      included: value ? inc / value : 0,
      value, byOrg, expandable: true, expanded: open, count: tail.length,
      members: tail.map((it) => ({ kind: it.kind, node: it.node })),
    });
    if (open) group(tail, depth + 1, key, offset + page);
  };

  const top: Item[] = roots.filter((r) => t.total[r] > 0).map(dirItem);
  group(top.sort(byValue), 0, 'root', 0);
  return out;
}

// ---------------------------------------------------------------------------
// Gerrit links for the directory chart (summaries/area_reviewers.json).

/** Who wrote each (week, node, org) bucket's comments in a DirBoard. Rows are
 * [node, org, account, comments, account, comments, ...], indexed like the
 * DirBoard whose generated_at is `areas_generated_at`. */
export interface DirReviewers {
  meta: { areas_generated_at: string; [k: string]: unknown };
  weeks: Record<string, number[][]>;
}

/** Account id → comments, per segment org (an org in `orgs`, else OTHER). */
export type SegmentReviewers = Map<string, Map<number, number>>;

export interface DirReviewerIndex {
  /** Per node: the reviewers of its subtree (a dir row) and of its own bucket (its rest row). */
  total: (SegmentReviewers | undefined)[];
  own: (SegmentReviewers | undefined)[];
}

const addReviewers = (maps: (SegmentReviewers | undefined)[], i: number, org: string, row: number[]) => {
  let m = maps[i];
  if (!m) maps[i] = m = new Map();
  let people = m.get(org);
  if (!people) m.set(org, (people = new Map()));
  for (let k = 2; k + 1 < row.length; k += 2) people.set(row[k], (people.get(row[k]) ?? 0) + row[k + 1]);
};

/** Sums the reviewers over the weeks into every node's subtree, like
 * dirTotals. Null if `who` was built with a different DirBoard, whose node
 * and org indexes may not match. */
export function dirReviewerIndex(
  board: DirBoard,
  who: DirReviewers,
  weeks: string[],
  orgs: readonly string[],
): DirReviewerIndex | null {
  if (!board.meta.generated_at || who.meta.areas_generated_at !== board.meta.generated_at) return null;
  const keep = new Set(orgs);
  const n = board.nodes.length;
  const idx: DirReviewerIndex = { total: new Array(n), own: new Array(n) };
  for (const w of weeks) {
    for (const row of who.weeks[w] ?? []) {
      const org = board.orgs[row[1]];
      if (row[0] >= n || org === undefined) continue;
      const seg = keep.has(org) ? org : OTHER;
      addReviewers(idx.own, row[0], seg, row);
      for (let i = row[0]; i >= 0; i = board.nodes[i][0]) addReviewers(idx.total, i, seg, row);
    }
  }
  return idx;
}

/** Most reviewers one directory link names, by most comments: each costs
 * two of Gerrit's 800 query terms, and the URL grows with each. */
export const MAX_LINK_REVIEWERS = 100;

export interface DirLink {
  url: string;
  /** The directory searched. */
  path: string;
  /** Reviewers (or authors) the search names, and how many there were in all. */
  shown: number;
  total: number;
  /** The search is for the people's own CLs (commits), not those they reviewed. */
  authors?: boolean;
}

/** A Gerrit search for the CLs in a directory that the reviewers commented
 * on, other than their own, in the range (gerritDateTerms): the
 * MAX_LINK_REVIEWERS with the most comments. `dir:` matches CLs whose current
 * patch set touches the directory, subdirectories included (or any path with
 * those segments: Chromium Gerrit has no regex search to anchor it), so the
 * list is a superset of the CLs behind the count. Null for paths `dir:` can't
 * name: "(no file)" and "(top-level files)". */
export function gerritDirUrl(
  path: string,
  reviewers: Map<number, number> | undefined,
  range?: WeekRange,
  now?: Date,
  authors = false,
): DirLink | null {
  if (!reviewers?.size || !path.endsWith('/') || path.startsWith('(')) return null;
  const ids = [...reviewers]
    .sort((a, b) => b[1] - a[1] || a[0] - b[0])
    .slice(0, MAX_LINK_REVIEWERS)
    .map(([id]) => id);
  // Authors: their own merged CLs. Commits are credited to the git author,
  // which is the CL owner for nearly every commit.
  const who = authors
    ? ['status:merged', ids.length === 1 ? `owner:${ids[0]}` : `(${ids.map((id) => `owner:${id}`).join(' OR ')})`]
    : ids.length === 1
      ? [`commentby:${ids[0]}`, `-owner:${ids[0]}`]
      : [`(${ids.map((id) => `(commentby:${id} -owner:${id})`).join(' OR ')})`];
  return {
    url: gerritQueryUrl([`dir:${path.slice(0, -1)}`, ...gerritDateTerms(range, now), ...who]),
    path,
    shown: ids.length,
    total: reviewers.size,
    ...(authors ? { authors: true } : {}),
  };
}

/** The link for one org's segment of a chart row: a directory row searches
 * its subtree's reviewers, a "rest of" row its own bucket's; "other" groups
 * get none. */
export function dirRowLink(
  board: DirBoard,
  idx: DirReviewerIndex,
  row: DirRow,
  org: string,
  range?: WeekRange,
  now?: Date,
  authors = false,
): DirLink | null {
  if (row.node === undefined || row.kind === 'other') return null;
  const reviewers = (row.kind === 'dir' ? idx.total : idx.own)[row.node]?.get(org);
  return gerritDirUrl(dirTree(board).paths[row.node], reviewers, range, now, authors);
}

/** A person's own merged CLs on Chromium Gerrit over the range, or null
 * without an email: what their commits link to. */
export const gerritAuthoredUrl = (email: string | null, range?: WeekRange, now?: Date): string | null =>
  email ? gerritQueryUrl([`owner:${email}`, 'status:merged', ...gerritDateTerms(range, now)]) : null;

// ---------------------------------------------------------------------------
// One directory in the organization chart, and the directory heatmap. Both
// read the DirBoard, so they count every comment in a directory, in scope or
// not, like the directory chart.

const pathIndex = new WeakMap<DirBoard, Map<string, number>>();

/** The tree node for a directory path, with or without its trailing slash;
 * null if the tree has no such node. */
export function dirNodeByPath(board: DirBoard, path: string): number | null {
  let m = pathIndex.get(board);
  if (!m) {
    m = new Map(dirTree(board).paths.map((p, i) => [p, i]));
    pathIndex.set(board, m);
  }
  const p = path.trim();
  if (!p) return null;
  return m.get(p) ?? m.get(`${p}/`) ?? null;
}

/** Marks `node` and every node below it. */
function subtree(board: DirBoard, node: number): Uint8Array {
  const { children } = dirTree(board);
  const mark = new Uint8Array(board.nodes.length);
  const stack = [node];
  while (stack.length) {
    const i = stack.pop()!;
    mark[i] = 1;
    stack.push(...children[i]);
  }
  return mark;
}

/** Like orgWeeklyCounts, for one directory and everything below it: a series
 * per `names` org with some of the metric there over `weeks`, largest first
 * (the rest as OTHER), each a trailing mean over `smoothing` weeks. `exclude` leaves orgs
 * out entirely. Reviewed CLs count (CL, directory) pairs, so a CL with
 * comments in two subdirectories counts in each. `dataWeeks` is as in
 * orgWeeklyCounts, and so is `nameable`. */
export function dirWeeklyCounts(
  board: DirBoard,
  node: number,
  weeks: string[],
  metric: Metric,
  names: readonly string[],
  smoothing = 1,
  exclude: readonly string[] = [],
  dataWeeks?: readonly string[],
  nameable?: (org: string) => boolean,
): { org: string; values: number[] }[] {
  const col = METRIC_INDEX[metric];
  const inside = subtree(board, node);
  const skip = new Set(exclude);
  const shown = new Set(weeks);
  const raw = new Map<string, Map<string, number>>();
  const sums = new Map<string, number>();
  for (const [w, rows] of Object.entries(board.weeks)) {
    for (const row of rows) {
      const v = row[col];
      const org = board.orgs[row[1]];
      if (!v || !inside[row[0]] || skip.has(org)) continue;
      let m = raw.get(org);
      if (!m) raw.set(org, (m = new Map()));
      m.set(w, (m.get(w) ?? 0) + v);
      if (shown.has(w)) sums.set(org, (sums.get(org) ?? 0) + v);
    }
  }
  const named = [...sums]
    .filter(([org, v]) => org !== OTHER && v > 0 && names.includes(org) && (!nameable || nameable(org)))
    .sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : 1))
    .map(([org]) => org);
  const keep = new Set(named);
  const other = new Map<string, number>();
  let hasOther = false;
  for (const [org, m] of raw) {
    if (keep.has(org)) continue;
    if (sums.get(org)) hasOther = true;
    for (const [w, v] of m) other.set(w, (other.get(w) ?? 0) + v);
  }
  const known = new Set(dataWeeks ?? Object.keys(board.weeks));
  const series = named.map((org) => ({ org, counts: raw.get(org) }));
  if (hasOther) series.push({ org: OTHER, counts: other });
  return series.map(({ org, counts }) => ({
    org,
    values: weeks.map((w) => trailingMean(counts, w, smoothing, known)),
  }));
}

/** Heatmap column widths, in weeks. */
export const HEAT_BIN_SIZES = [1, 4, 13, 52] as const;
export type HeatBinSize = (typeof HEAT_BIN_SIZES)[number];
export const DEFAULT_HEAT_BIN: HeatBinSize = 4;

/** Splits a range into consecutive bins of `size` weeks, oldest first. They
 * line up with the range's end, so the latest bin is whole and only the first
 * may be short. */
export function heatBins(range: WeekRange, size: number): WeekRange[] {
  const out: WeekRange[] = [];
  for (let to = range.to; to >= range.from; to = addWeeks(to, -size)) {
    const from = addWeeks(to, 1 - size);
    out.push({ from: from < range.from ? range.from : from, to });
  }
  return out.reverse();
}

/** What one heatmap cell holds: the metric in total and per org. */
export interface HeatCell {
  value: number;
  byOrg: Map<string, number>;
}

/** A row's value in `t`: a directory's subtree, a "rest of" row's own bucket,
 * or the sum of an "other" row's entries. */
export function rowAmount(t: DirTotals, row: DirRow): HeatCell {
  const parts =
    row.kind === 'other' ? row.members ?? [] : row.node === undefined ? [] : [{ kind: row.kind, node: row.node }];
  if (parts.length === 1) {
    const { kind, node } = parts[0];
    return kind === 'dir'
      ? { value: t.total[node], byOrg: t.byOrg(node) ?? new Map() }
      : { value: t.own[node], byOrg: t.ownByOrg(node) ?? new Map() };
  }
  const byOrg = new Map<string, number>();
  let value = 0;
  for (const p of parts) {
    const c = rowAmount(t, { ...row, kind: p.kind, node: p.node, members: undefined });
    value += c.value;
    for (const [o, v] of c.byOrg) byOrg.set(o, (byOrg.get(o) ?? 0) + v);
  }
  return { value, byOrg };
}

export interface HeatGrid {
  bins: WeekRange[];
  /** The board's weeks in each bin. */
  binWeeks: string[][];
  rows: DirRow[];
  /** cells[row][bin]. */
  cells: HeatCell[][];
}

/** The heatmap: the directory rows (dirRows, ranked by what `rankOnly`
 * accepts over the whole range) against time bins, each cell the metric for
 * the orgs `only` accepts (all, if not given), split into `orgs` and OTHER. */
export function heatGrid(
  board: DirBoard,
  range: WeekRange,
  binSize: number,
  metric: Metric,
  orgs: readonly string[],
  expanded: ReadonlySet<string>,
  { only, rankOnly = only, page = DIR_PAGE }: {
    only?: (org: string) => boolean;
    rankOnly?: (org: string) => boolean;
    page?: number;
  } = {},
): HeatGrid {
  const all = Object.keys(board.weeks);
  const rows = dirRows(board, dirTotals(board, weeksIn(all, range), orgs, metric, rankOnly), expanded, page);
  const bins = heatBins(range, binSize);
  const binWeeks = bins.map((b) => weeksIn(all, b));
  return { bins, binWeeks, rows, cells: rowCells(board, rows, binWeeks, orgs, metric, only) };
}

/** A complexity cell is shaded only with at least this many reviews: with
 * fewer, one long thread decides it. */
export const COMPLEXITY_MIN = 10;

/** One figure: the metric over a number of reviews. */
export interface PerReview {
  num: number;
  reviews: number;
}

export const perReview = (p: PerReview) => (p.reviews ? p.num / p.reviews : 0);

export interface ComplexityGrid {
  bins: WeekRange[];
  rows: DirRow[];
  /** cells[row][bin]. */
  cells: PerReview[][];
  /** Each row over the whole range. */
  totals: PerReview[];
  /** Every directory together over the range. */
  overall: PerReview;
}

/** Review complexity by directory over time: the metric per review in each
 * directory and time bin. A review is one org's comments on one CL in a
 * directory bucket (the board's cls column, summed over orgs), so a CL two
 * orgs commented on is two reviews and a CL in two directories counts in
 * each. Rows are dirRows laid out by reviews over the range, so the busiest
 * directories lead. "(no file)" is left out: comments that can't be placed
 * are mostly sign-offs, and they would be a third of all reviews. */
export function complexityGrid(
  board: DirBoard,
  range: WeekRange,
  binSize: number,
  metric: Metric,
  expanded: ReadonlySet<string>,
  page = DIR_PAGE,
): ComplexityGrid {
  const all = Object.keys(board.weeks);
  const weeks = weeksIn(all, range);
  const t = dirTotals(board, weeks, [], 'cls');
  const unplaced = dirTree(board).roots.filter((r) => board.nodes[r][1] === board.meta.unplaced);
  // A node with no total isn't listed (dirRows).
  const listed = { ...t, total: t.total.map((v, i) => (unplaced.includes(i) ? 0 : v)) };
  const rows = dirRows(board, listed, expanded, page);
  const bins = heatBins(range, binSize);
  const binWeeks = bins.map((b) => weeksIn(all, b));
  const pair = (groups: string[][]) => {
    const r = rowCells(board, rows, groups, [], 'cls');
    const n = rowCells(board, rows, groups, [], metric);
    return r.map((row, i) => row.map((c, j) => ({ num: n[i][j].value, reviews: c.value })));
  };
  const nums = dirTotals(board, weeks, [], metric);
  const roots = dirTree(board).roots.filter((r) => !unplaced.includes(r));
  return {
    bins,
    rows,
    cells: pair(binWeeks),
    totals: pair([weeks]).map((r) => r[0]),
    overall: {
      num: roots.reduce((s, r) => s + nums.total[r], 0),
      reviews: roots.reduce((s, r) => s + t.total[r], 0),
    },
  };
}

/** The shading scale: from the 5th to the 95th percentile of the cells
 * resting on enough reviews. Figures sit in a narrow band well above 0, so a
 * scale from 0 would shade every cell alike; and a few outliers would wash
 * out the rest. Cells past either end get that end's colour. */
export function complexityScale(grid: ComplexityGrid): { lo: number; hi: number } {
  const v = grid.cells
    .flat()
    .filter((c) => c.reviews >= COMPLEXITY_MIN)
    .map(perReview)
    .sort((a, b) => a - b);
  if (!v.length) return { lo: 0, hi: 0 };
  const at = (q: number) => v[Math.min(v.length - 1, Math.floor(v.length * q))];
  return { lo: at(0.05), hi: at(0.95) };
}

/** Each row's HeatCell in each group of weeks: what rowAmount would give on
 * dirTotals(board, weeks, orgs, metric, only), but summing only the nodes the
 * rows show. dirTotals sums every node of the tree (~14k) for every org, which
 * is most of the cost when it runs once per bin; the rows need a few dozen. */
export function rowCells(
  board: DirBoard,
  rows: readonly DirRow[],
  groups: readonly string[][],
  orgs: readonly string[],
  metric: Metric,
  only?: (org: string) => boolean,
): HeatCell[][] {
  const col = METRIC_INDEX[metric];
  const names = [...new Set(orgs)].filter((o) => o !== OTHER);
  names.push(OTHER);
  const S = names.length;
  const named = new Map(names.map((o, i) => [o, i]));
  const slotOf = board.orgs.map((o) => (only && !only(o) ? -1 : named.get(o) ?? S - 1));
  const nodes = board.nodes;
  const n = nodes.length;
  // The nodes whose subtree (dir) or own bucket (rest) some row needs.
  const parts = rows.map((r) =>
    r.kind === 'other' ? r.members ?? [] : r.node === undefined ? [] : [{ kind: r.kind, node: r.node }],
  );
  const dirIdx = new Int32Array(n).fill(-1);
  const ownIdx = new Int32Array(n).fill(-1);
  let D = 0;
  let O = 0;
  for (const ps of parts) {
    for (const p of ps) {
      if (p.kind === 'dir') {
        if (dirIdx[p.node] < 0) dirIdx[p.node] = D++;
      } else if (ownIdx[p.node] < 0) ownIdx[p.node] = O++;
    }
  }
  // up[i]: the nearest wanted dir node at or above i (-1 if none); a parent
  // precedes its children, so one pass top-down fills it.
  const up = new Int32Array(n);
  for (let i = 0; i < n; i++) {
    const p = nodes[i][0];
    up[i] = dirIdx[i] >= 0 ? i : p >= 0 ? up[p] : -1;
  }
  const nextUp = (i: number) => (nodes[i][0] >= 0 ? up[nodes[i][0]] : -1);

  const perGroup = groups.map((weeks) => {
    const dirSum = new Float64Array(D * S);
    const ownSum = new Float64Array(O * S);
    for (const w of weeks) {
      const data = board.weeks[w];
      if (!data) continue;
      for (let r = 0; r < data.length; r++) {
        const row = data[r];
        const v = row[col];
        if (!v) continue;
        const slot = slotOf[row[1]];
        if (slot < 0) continue;
        const node = row[0];
        if (ownIdx[node] >= 0) ownSum[ownIdx[node] * S + slot] += v;
        for (let a = up[node]; a >= 0; a = nextUp(a)) dirSum[dirIdx[a] * S + slot] += v;
      }
    }
    return { dirSum, ownSum };
  });

  return parts.map((ps) =>
    perGroup.map(({ dirSum, ownSum }) => {
      const sums = new Float64Array(S);
      for (const p of ps) {
        const [arr, at] = p.kind === 'dir' ? [dirSum, dirIdx[p.node] * S] : [ownSum, ownIdx[p.node] * S];
        for (let k = 0; k < S; k++) sums[k] += arr[at + k];
      }
      const byOrg = new Map<string, number>();
      let value = 0;
      for (let k = 0; k < S; k++) {
        if (!sums[k]) continue;
        byOrg.set(names[k], sums[k]);
        value += sums[k];
      }
      return { value, byOrg };
    }),
  );
}

/** A row's reviewers in a DirReviewerIndex, summed over the segment orgs
 * `keep` accepts: account id → comments, and each account's segment org.
 * Undefined for "other" rows, which aren't one directory. */
export function rowReviewers(
  idx: DirReviewerIndex,
  row: DirRow,
  keep: (org: string) => boolean = () => true,
): { comments: Map<number, number>; org: Map<number, string> } | undefined {
  if (row.node === undefined || row.kind === 'other') return undefined;
  const seg = (row.kind === 'dir' ? idx.total : idx.own)[row.node];
  const comments = new Map<number, number>();
  const org = new Map<number, string>();
  const most = new Map<number, number>();
  for (const [o, people] of seg ?? []) {
    if (!keep(o)) continue;
    for (const [id, n] of people) {
      comments.set(id, (comments.get(id) ?? 0) + n);
      // Someone who changed org within the range goes under the org with most of their comments.
      if (n > (most.get(id) ?? 0)) {
        most.set(id, n);
        org.set(id, o);
      }
    }
  }
  return { comments, org };
}

/** The `n` accounts with the most comments, most first (ties by id). */
export function topAccounts(comments: Map<number, number>, n: number): [id: number, comments: number][] {
  return [...comments].sort((a, b) => b[1] - a[1] || a[0] - b[0]).slice(0, n);
}
