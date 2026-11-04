// Pure data handling: parse the committed summaries and Radar CSV, and join
// them into value ratios. No DOM or Chart.js here so it can be unit-tested
// in Node.

export type Metric = 'comments' | 'cls' | 'chars';

export const METRICS: { id: Metric; label: string; column: keyof SummaryRow }[] = [
  { id: 'comments', label: 'Review comments', column: 'share_comments' },
  { id: 'cls', label: 'Reviewed CLs', column: 'share_cls' },
  { id: 'chars', label: 'Review characters', column: 'share_chars' },
];

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
  share: number;
  reviewed_cls: number;
  reviewers: number;
  comments: number;
  review_chars: number;
  ai_comments: number;
  post_merge_comments: number;
  share_cls: number;
  share_comments: number;
  share_chars: number;
}

export interface Summary {
  meta: { weeks: string[]; headline_metric: string; [k: string]: unknown };
  rows: SummaryRow[];
}

export interface WeeklyTotals {
  iso_week: string;
  main_cls: number;
  merged_cls: number;
  abandoned_cls: number;
  human_cls: number;
  bot_cls: number;
  human_cls_with_review: number;
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
    human_cls_with_review: Number(r.human_cls_with_review),
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

/** Radar browser buckets left out of the ratio's usage denominator. Radar's
 * unnamed-Chromium bucket, ChromeDerivative, jumped from about 0.3% to about
 * 10% of Chromium usage in 2026-W37. That looks like a reporting change Radar
 * hasn't explained, so for now the ratio uses each org's share of the rest.
 * The usage chart still shows the bucket. */
export const RATIO_EXCLUDED_BROWSERS: readonly string[] = ['ChromeDerivative'];

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
  /** Org's share of the chosen review metric (0 if absent from the summary). */
  contribution: number;
  /** Org's browsers' share of Chromium browser usage; null if no Radar week. */
  derived: number | null;
  /** contribution / derived; null when undefined (no Radar data, or usage
   * share below MIN_DERIVED_SHARE). */
  ratio: number | null;
}

export function metricColumn(metric: Metric): keyof SummaryRow {
  return METRICS.find((m) => m.id === metric)!.column;
}

/** Value ratios for every (summary week, browser-owning org). */
export function computeRatios(
  summary: Summary,
  radar: RadarWeekly,
  orgBrowsers: Map<string, string[]>,
  metric: Metric,
  minDerived = MIN_DERIVED_SHARE,
): RatioPoint[] {
  const col = metricColumn(metric);
  const points: RatioPoint[] = [];
  for (const week of summary.meta.weeks) {
    for (const [org, browsers] of orgBrowsers) {
      const row = summary.rows.find((r) => r.iso_week === week && r.org === org);
      const contribution = row ? Number(row[col]) : 0;
      const derived = derivedShare(radar, week, browsers);
      const ratio = derived !== null && derived >= minDerived ? contribution / derived : null;
      points.push({ week, org, contribution, derived, ratio });
    }
  }
  return points;
}

/** Running-average choices for the value ratio chart, in weeks (1 = off). */
export const SMOOTHING_WEEKS = [1, 4, 12] as const;
export type Smoothing = (typeof SMOOTHING_WEEKS)[number];
export const DEFAULT_SMOOTHING: Smoothing = 4;

/** Trailing running average of ratios over `window` calendar weeks, ending at
 * each point's week. Averages the two shares separately and divides (mean
 * contribution ÷ mean usage), so a week with near-zero usage can't dominate
 * the way it would when averaging weekly ratios. Weeks with no Radar data, or
 * absent from `points`, are left out of the window. Pass every week, not just
 * the displayed range, so the first displayed weeks get a full window. */
export function smoothRatios(points: RatioPoint[], window: number, minDerived = MIN_DERIVED_SHARE): RatioPoint[] {
  if (window <= 1) return points;
  const byKey = new Map(points.map((p) => [`${p.org}|${p.week}`, p]));
  return points.map((p) => {
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

/** Orgs that get a series (and therefore a colour): their browsers reach
 * minDerived in at least one Radar week. Order follows org_browsers.csv, so
 * colours never depend on the selected metric or week. */
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

const COUNT_COLUMN: Record<Metric, keyof SummaryRow> = {
  comments: 'comments',
  cls: 'reviewed_cls',
  chars: 'review_chars',
};

export const OTHER = 'Other';

/** Raw review counts summed over the given week(s): the top `n` orgs by the metric, then
 * everything else (including the summary's own "Other" row, e.g. gmail.com)
 * as a final "Other" entry. */
export function topOrgCounts(
  summary: Summary,
  weeks: string | string[],
  metric: Metric,
  n = 7,
): { org: string; value: number }[] {
  const col = COUNT_COLUMN[metric];
  const set = new Set(typeof weeks === 'string' ? [weeks] : weeks);
  const sums = new Map<string, number>();
  for (const r of summary.rows) {
    if (set.has(r.iso_week)) sums.set(r.org, (sums.get(r.org) ?? 0) + Number(r[col]));
  }
  const rows = [...sums].map(([org, value]) => ({ org, value }));
  const named = rows.filter((r) => r.org !== OTHER).sort((a, b) => b.value - a.value);
  const top = named.slice(0, n);
  const rest = named.slice(n).reduce((s, r) => s + r.value, 0) +
    rows.filter((r) => r.org === OTHER).reduce((s, r) => s + r.value, 0);
  return rest > 0 || rows.some((r) => r.org === OTHER) ? [...top, { org: OTHER, value: rest }] : top;
}

/** Weekly review counts for the top `n` orgs over the given weeks (ranked by
 * their total, as in topOrgCounts), then everything else as a final "Other"
 * series. `values[i]` is the count in `weeks[i]`. With `smoothing` > 1, each
 * value is the trailing mean over that many calendar weeks ending at
 * `weeks[i]`, including weeks before the range; weeks outside the summary's
 * data are left out of the window, as in smoothRatios. Orgs in `exclude` are
 * dropped entirely (not folded into "Other"), so the next-ranked org takes
 * their place among the top `n`. */
export function orgWeeklyCounts(
  all: Summary,
  weeks: string[],
  metric: Metric,
  n = 7,
  smoothing = 1,
  exclude: readonly string[] = [],
): { org: string; values: number[] }[] {
  const col = COUNT_COLUMN[metric];
  const summary = exclude.length ? { ...all, rows: all.rows.filter((r) => !exclude.includes(r.org)) } : all;
  const named = new Set(topOrgCounts(summary, weeks, metric, n).map((r) => r.org).filter((o) => o !== OTHER));
  // Raw counts per (org, week) over every summary week.
  const raw = new Map<string, Map<string, number>>();
  let hasOther = false;
  for (const r of summary.rows) {
    const key = named.has(r.org) ? r.org : OTHER;
    if (key === OTHER && weeks.includes(r.iso_week)) hasOther = true;
    if (!raw.has(key)) raw.set(key, new Map());
    const m = raw.get(key)!;
    m.set(r.iso_week, (m.get(r.iso_week) ?? 0) + Number(r[col]));
  }
  const known = new Set([...summary.meta.weeks, ...summary.rows.map((r) => r.iso_week)]);
  const window = Math.max(1, smoothing);
  const valueAt = (counts: Map<string, number> | undefined, week: string) => {
    let sum = 0;
    let k = 0;
    for (let i = 0; i < window; i++) {
      const w = addWeeks(week, -i);
      if (!known.has(w)) continue;
      sum += counts?.get(w) ?? 0;
      k++;
    }
    return k ? sum / k : 0;
  };
  const orgs = [...named, ...(hasOther ? [OTHER] : [])];
  return orgs.map((org) => ({ org, values: weeks.map((w) => valueAt(raw.get(org), w)) }));
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

/** summaries/reviewer_weekly.json: every reviewer's counts per week, one row
 * per (week, account, org). Compact: each row is
 * [account_id, index into `orgs`, comments, cls, chars]. Orgs are resolved
 * before org_weekly's fold of `meta.fold_into_other` into "Other". */
export type ReviewerRow = [account: number, org: number, comments: number, cls: number, chars: number];

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
  name: string;
  email: string | null;
  org: string;
  value: number;
}

const METRIC_INDEX: Record<Metric, 2 | 3 | 4> = { comments: 2, cls: 3, chars: 4 };

export const LEADERBOARD_SIZE = 50;

/** The reviewer's reviews on Chromium Gerrit, or null without an email. */
export const gerritReviewsUrl = (email: string | null): string | null =>
  email ? `https://chromium-review.googlesource.com/q/reviewedby:${encodeURIComponent(email).replace('%40', '@')}` : null;

const asList = (weeks: string | string[]) => (typeof weeks === 'string' ? [weeks] : weeks);

/** The top `n` reviewers by the metric, summed over the given week(s): exact
 * totals, since the board holds every reviewer. Ties are broken by account id
 * so the order is stable; reviewers with 0 for the metric are left out. A
 * reviewer's org is the one most of their reviewed CLs in those weeks
 * resolve to (ties: alphabetical). */
export function topReviewers(
  board: ReviewerBoard,
  weeks: string | string[],
  metric: Metric,
  n = LEADERBOARD_SIZE,
): LeaderboardRow[] {
  const col = METRIC_INDEX[metric];
  const by = new Map<number, { value: number; orgCls: Map<number, number> }>();
  for (const w of asList(weeks)) {
    for (const r of board.weeks[w] ?? []) {
      let t = by.get(r[0]);
      if (!t) by.set(r[0], (t = { value: 0, orgCls: new Map() }));
      t.value += r[col];
      t.orgCls.set(r[1], (t.orgCls.get(r[1]) ?? 0) + r[3]);
    }
  }
  const orgOf = (orgCls: Map<number, number>) => {
    let best = -1;
    let bestCls = -1;
    for (const [o, c] of orgCls) {
      if (c > bestCls || (c === bestCls && board.orgs[o] < board.orgs[best])) [best, bestCls] = [o, c];
    }
    return board.orgs[best];
  };
  return [...by]
    .filter(([, t]) => t.value > 0)
    .sort(([a, x], [b, y]) => y.value - x.value || a - b)
    .slice(0, n)
    .map(([id, t]) => ({
      name: board.accounts[id] ?? `Account ${id}`,
      email: board.emails?.[id] ?? null,
      org: orgOf(t.orgCls),
      value: t.value,
    }));
}

/** Distinct reviewers over the given week(s): in total, and per org as
 * org_weekly.json reports orgs (fold_into_other folded into "Other"). A
 * reviewer who reviewed for two orgs counts once in each. */
export function distinctReviewers(
  board: ReviewerBoard,
  weeks: string | string[],
): { total: number; byOrg: Map<string, number> } {
  const fold = new Set(board.meta.fold_into_other ?? []);
  const orgName = board.orgs.map((o) => (fold.has(o) ? OTHER : o));
  const all = new Set<number>();
  const sets = new Map<string, Set<number>>();
  for (const w of asList(weeks)) {
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

/** Monday (UTC midnight) of an ISO week label. */
export function weekMonday(week: string): Date {
  const m = /^(\d{4})-W(\d{2})$/.exec(week);
  if (!m) throw new Error(`not an ISO week: ${week}`);
  const jan4 = Date.UTC(Number(m[1]), 0, 4);
  const jan4Day = (new Date(jan4).getUTCDay() + 6) % 7;
  return new Date(jan4 + (Number(m[2]) * 7 - 7 - jan4Day) * DAY_MS);
}

/** Sunday (UTC midnight) of an ISO week label. */
export const weekSunday = (week: string) => new Date(weekMonday(week).getTime() + 6 * DAY_MS);

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const shortDate = (d: Date) => `${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}`;

/** Tooltip title for a week, e.g. "2026-W44 (Oct 26 – Nov 1)". */
export const weekTitle = (week: string) =>
  `${week} (${shortDate(weekMonday(week))} – ${shortDate(weekSunday(week))})`;

/** Year and month a week belongs to, by its Thursday (as for ISO years). */
function weekMonth(week: string): { year: number; month: number } {
  const t = new Date(weekMonday(week).getTime() + 3 * DAY_MS);
  return { year: t.getUTCFullYear(), month: t.getUTCMonth() };
}

/** Month labels for a weekly time axis: the indices of `weeks` that start a
 * month (by Thursday), with labels like "Nov 2025", "Dec", "Jan 2026". The
 * year is shown on the first tick and on each January. Months are thinned to
 * every 2, 3, 6 or 12 (aligned to the calendar, so quarters start in Jan, Apr,
 * …) to keep at most `maxTicks`. A range inside one month gets one tick on
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
  if (!kept.length) kept = starts.slice(0, 1);
  return kept.map((x, i) => ({
    index: x.index,
    label: i === 0 || x.month === 0 ? `${MONTHS[x.month]} ${x.year}` : MONTHS[x.month],
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

/** One org's review counts summed over some weeks, with shares recomputed
 * from the sums (as summarize.py does per week: org count ÷ the sum over all
 * orgs). Each CL closes in exactly one week, so summing CL counts over weeks
 * is exact. Reviewer counts are distinct per week and can't be summed (the
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
}

export function orgTotals(summary: Summary, weeks: string[], reviewers?: Map<string, number>): OrgTotals[] {
  const set = new Set(weeks);
  const by = new Map<string, OrgTotals>();
  for (const r of summary.rows) {
    if (!set.has(r.iso_week)) continue;
    let t = by.get(r.org);
    if (!t) {
      t = {
        org: r.org, reviewers: 0, reviewed_cls: 0, comments: 0, review_chars: 0,
        ai_comments: 0, post_merge_comments: 0, share_cls: 0, share_comments: 0, share_chars: 0,
      };
      by.set(r.org, t);
    }
    t.reviewers += r.reviewers;
    t.reviewed_cls += r.reviewed_cls;
    t.comments += r.comments;
    t.review_chars += r.review_chars;
    t.ai_comments += r.ai_comments;
    t.post_merge_comments += r.post_merge_comments ?? 0;
  }
  const out = [...by.values()];
  const sum = (k: 'reviewed_cls' | 'comments' | 'review_chars') => out.reduce((s, t) => s + t[k], 0);
  const [cls, comments, chars] = [sum('reviewed_cls'), sum('comments'), sum('review_chars')];
  for (const t of out) {
    if (reviewers) t.reviewers = reviewers.get(t.org) ?? 0;
    t.share_cls = cls ? t.reviewed_cls / cls : 0;
    t.share_comments = comments ? t.comments / comments : 0;
    t.share_chars = chars ? t.review_chars / chars : 0;
  }
  return out;
}

export const SHARE_COLUMN: Record<Metric, 'share_cls' | 'share_comments' | 'share_chars'> = {
  comments: 'share_comments',
  cls: 'share_cls',
  chars: 'share_chars',
};

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
  const keys = ['main_cls', 'merged_cls', 'abandoned_cls', 'human_cls', 'bot_cls', 'human_cls_with_review'] as const;
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
