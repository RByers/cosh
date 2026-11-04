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
 * dividing by ~0 makes the ratio meaningless (e.g. Brave, which Radar counts
 * as Chrome). */
export const MIN_DERIVED_SHARE = 0.001;

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
  meta: { weeks: string[]; headline_metric: string; min_reviewers_per_org: number; [k: string]: unknown };
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
    if (r.chromium_share === '') continue; // webview, in-app, non-Chromium
    let m = out.get(r.period);
    if (!m) out.set(r.period, (m = new Map()));
    m.set(r.browser, Number(r.chromium_share));
  }
  return out;
}

/** Sum of an org's browsers' Chromium usage share in one week, or null if
 * Radar has no complete data for that week. */
export function derivedShare(radar: RadarWeekly, week: string, browsers: string[]): number | null {
  const m = radar.get(week);
  if (!m) return null;
  return browsers.reduce((sum, b) => sum + (m.get(b) ?? 0), 0);
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

/** Raw review counts for one week: the top `n` orgs by the metric, then
 * everything else (including the summary's own privacy-folded "Other" row)
 * as a final "Other" entry. */
export function topOrgCounts(
  summary: Summary,
  week: string,
  metric: Metric,
  n = 7,
): { org: string; value: number }[] {
  const col = COUNT_COLUMN[metric];
  const rows = summary.rows
    .filter((r) => r.iso_week === week)
    .map((r) => ({ org: r.org, value: Number(r[col]) }));
  const named = rows.filter((r) => r.org !== OTHER).sort((a, b) => b.value - a.value);
  const top = named.slice(0, n);
  const rest = named.slice(n).reduce((s, r) => s + r.value, 0) +
    rows.filter((r) => r.org === OTHER).reduce((s, r) => s + r.value, 0);
  return rest > 0 || rows.some((r) => r.org === OTHER) ? [...top, { org: OTHER, value: rest }] : top;
}

/** Radar browsers to chart individually: the `n` with the highest peak
 * weekly share (peak, not mean, so a recent riser like ChromeDerivative
 * shows up), in descending order of peak. Everything else is "Other". */
export function topBrowsers(radar: RadarWeekly, n = 7): string[] {
  const peak = new Map<string, number>();
  for (const m of radar.values()) {
    for (const [b, s] of m) peak.set(b, Math.max(peak.get(b) ?? 0, s));
  }
  return [...peak].sort((a, b) => b[1] - a[1]).slice(0, n).map(([b]) => b);
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

/** One reviewer in one week (summaries/reviewer_weekly.json). */
export interface ReviewerRow {
  account_id: number;
  name: string;
  org: string;
  comments: number;
  cls: number;
  chars: number;
}

export interface ReviewerBoard {
  meta: { top_n: number; [k: string]: unknown };
  weeks: Record<string, ReviewerRow[]>;
}

export const LEADERBOARD_SIZE = 50;

/** The week's top `n` reviewers by the metric. Ties are broken by account id
 * so the order is stable; reviewers with 0 for the metric are left out. */
export function topReviewers(
  board: ReviewerBoard,
  week: string,
  metric: Metric,
  n = LEADERBOARD_SIZE,
): { name: string; org: string; value: number }[] {
  return [...(board.weeks[week] ?? [])]
    .filter((r) => r[metric] > 0)
    .sort((a, b) => b[metric] - a[metric] || a.account_id - b.account_id)
    .slice(0, n)
    .map((r) => ({ name: r.name, org: r.org, value: r[metric] }));
}
