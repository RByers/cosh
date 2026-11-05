// Unit tests for the pure data/scale modules (no browser).
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { test } from 'vitest';
import {
  gerritCommentUrl,
  reviewerSeries,
  threadBreakdown,
  addressedMeta,
  addressedRange,
  addressedWeeks,
  addWeeks,
  barScale,
  dirRows,
  dirTotals,
  topDirOrgs,
  type DirBoard,
  chartedOrgs,
  clampRange,
  computeRatios,
  dataRanges,
  distinctReviewers,
  isoDate,
  isoWeekOf,
  derivedShare,
  meanDerivedShare,
  monthTicks,
  weekTitle,
  orgTotals,
  parseIsoDate,
  rangeLength,
  smoothRatios,
  type RatioPoint,
  weekMonday,
  weeksIn,
  weekSunday,
  OTHER,
  parseCsv,
  parseOrgBrowsers,
  parseRadarWeekly,
  topBrowsers,
  topOrgCounts,
  orgWeeklyCounts,
  gerritReviewsUrl,
  gerritDateTerms,
  gerritDirUrl,
  dirReviewerIndex,
  dirRowLink,
  dirNodeByPath,
  dirWeeklyCounts,
  heatBins,
  heatGrid,
  rowReviewers,
  topAccounts,
  type DirReviewers,
  MAX_LINK_REVIEWERS,
  niceTicks,
  topReviewers,
  reviewerTotals,
  quantile,
  orgSpreads,
  distributionStats,
  leaderboardOrgs,
  trimRanked,
  type PathRule,
  type ReviewerBoard,
  type ReviewerRow,
  type Summary,
} from '../src/data.ts';
import { formatRatio } from '../src/scale.ts';
import { logAxisFloor } from '../src/charts.ts';

const RADAR = `period,period_start,period_end,granularity,device,browser,is_chromium,kind,days,raw_share,chromium_share
2026-W44,2026-10-26,2026-11-01,week,all,Chrome,1,browser,7,0.4,0.5
2026-W44,2026-10-26,2026-11-01,week,all,ChromeMobile,1,browser,7,0.2,0.25
2026-W44,2026-10-26,2026-11-01,week,all,Edge,1,browser,7,0.1,0.2
2026-W44,2026-10-26,2026-11-01,week,all,Brave,1,browser,7,0.0001,0.0002
2026-W44,2026-10-26,2026-11-01,week,all,SamsungInternet,1,browser,7,0.03,0.05
2026-W44,2026-10-26,2026-11-01,week,all,ChromeMobileWebview,1,webview,7,0.08,0.1
2026-W44,2026-10-26,2026-11-01,week,all,Instagram,1,in_app,7,0.004,0.005
2026-W44,2026-10-26,2026-11-01,week,all,Firefox,0,browser,7,0.03,
2026-W45,2026-11-02,2026-11-08,week,all,Chrome,1,browser,2,0.4,0.9
2026-10,2026-10-01,2026-10-31,month,all,Chrome,1,browser,31,0.4,0.6
`;

const ORG_BROWSERS = `org_domain,browser,notes
google.com,Chrome,"Desktop Chrome, mostly."
google.com,ChromeMobile,""
google.com,ChromeMobileWebview,""
meta.com,Instagram,""
microsoft.com,Edge,""
samsung.com,SamsungInternet,""
tiny.example,Brave,"About 0%"
`;

const row = (org: string, share: number, comments: number) => ({
  iso_week: '2026-W44',
  org,
  share,
  reviewed_cls: comments,
  reviewers: 10,
  comments,
  review_chars: comments * 100,
  ai_comments: 0,
  post_merge_comments: 0,
  share_cls: share,
  share_comments: share,
  share_chars: share,
});

const SUMMARY: Summary = {
  meta: { weeks: ['2026-W44'], headline_metric: 'comments' },
  rows: [
    row('google.com', 0.9, 900),
    row('microsoft.com', 0.05, 50),
    row('igalia.com', 0.03, 30),
    row('gmail.com', 0.01, 10),
    row(OTHER, 0.01, 10),
  ],
};

test('parseCsv handles quoted commas and doubled quotes', () => {
  const rows = parseCsv('a,b\n"x, y","say ""hi"""\r\n1,\n');
  assert.deepEqual(rows, [
    { a: 'x, y', b: 'say "hi"' },
    { a: '1', b: '' },
  ]);
});

test('radar keeps complete weeks of Chromium browsers, WebViews and in-app browsers', () => {
  const radar = parseRadarWeekly(RADAR);
  assert.deepEqual([...radar.keys()], ['2026-W44']);
  assert.equal(radar.get('2026-W44')!.get('ChromeMobileWebview'), 0.1);
  assert.equal(radar.get('2026-W44')!.get('Instagram'), 0.005);
  assert.equal(radar.get('2026-W44')!.has('Firefox'), false);
  assert.equal(radar.get('2026-W44')!.get('Edge'), 0.2);
});

test('computeRatios divides contribution share by summed browser share', () => {
  const radar = parseRadarWeekly(RADAR);
  const ratios = computeRatios(SUMMARY, radar, parseOrgBrowsers(ORG_BROWSERS), 'comments');
  const by = Object.fromEntries(ratios.map((p) => [p.org, p]));
  // Google: Chrome + Chrome Android + Android WebView.
  assert.ok(Math.abs(by['google.com'].ratio! - 0.9 / 0.85) < 1e-12);
  // Meta: its in-app browser share, here 0.5%.
  assert.equal(by['meta.com'].derived, 0.005);
  assert.ok(Math.abs(by['microsoft.com'].ratio! - 0.25) < 1e-12);
  // Absent from the summary: contribution 0, ratio 0.
  assert.equal(by['samsung.com'].ratio, 0);
  // Usage share below the threshold: no ratio.
  assert.equal(by['tiny.example'].ratio, null);
});

test('derivedShare leaves ChromeDerivative out of the usage denominator', () => {
  const radar = parseRadarWeekly(`period,period_start,period_end,granularity,device,browser,is_chromium,kind,days,raw_share,chromium_share
2026-W40,2026-09-28,2026-10-04,week,all,Chrome,1,browser,7,0.5,0.6
2026-W40,2026-09-28,2026-10-04,week,all,Edge,1,browser,7,0.2,0.2
2026-W40,2026-09-28,2026-10-04,week,all,ChromeDerivative,1,browser,7,0.2,0.2
`);
  assert.ok(Math.abs(derivedShare(radar, '2026-W40', ['Chrome'])! - 0.75) < 1e-12);
  assert.ok(Math.abs(derivedShare(radar, '2026-W40', ['Edge'])! - 0.25) < 1e-12);
  // The bucket itself is credited to nobody, even if mapped.
  assert.equal(derivedShare(radar, '2026-W40', ['ChromeDerivative']), 0);
});

test('chartedOrgs skips orgs whose browsers never reach the threshold', () => {
  const radar = parseRadarWeekly(RADAR);
  assert.deepEqual(chartedOrgs(radar, parseOrgBrowsers(ORG_BROWSERS)), ['google.com', 'meta.com', 'microsoft.com', 'samsung.com']);
});

test('topOrgCounts folds the tail and the summary Other row together', () => {
  const top = topOrgCounts(SUMMARY, '2026-W44', 'comments', 2);
  assert.deepEqual(top, [
    { org: 'google.com', value: 900 },
    { org: 'microsoft.com', value: 50 },
    { org: OTHER, value: 50 },
  ]);
  assert.equal(topOrgCounts(SUMMARY, '2026-W44', 'chars', 7)[0].value, 90000);
});

// orgs: 0 = x.com, 1 = y.com, 2 = gmail.com (folded into Other in org totals).
const board = (weeks: Record<string, ReviewerRow[]>): ReviewerBoard => ({
  meta: { fold_into_other: ['gmail.com'] },
  orgs: ['x.com', 'y.com', 'gmail.com'],
  accounts: { 1: 'n1', 2: 'n2', 3: 'n3' },
  emails: { 1: 'n1@x.com', 3: 'n3@x.com' },
  weeks,
});

test('topReviewers ranks one week by the chosen metric and drops zeros', () => {
  const b = board({ '2026-W44': [[1, 0, 9, 1, 50], [2, 0, 0, 4, 0], [3, 0, 9, 2, 80]] });
  assert.deepEqual(topReviewers(b, '2026-W44', 'comments').map((x) => [x.name, x.value]), [['n1', 9], ['n3', 9]]);
  assert.deepEqual(topReviewers(b, '2026-W44', 'cls', 2).map((x) => x.name), ['n2', 'n3']);
  assert.deepEqual(topReviewers(b, '2026-W44', 'chars')[0], { id: 3, name: 'n3', email: 'n3@x.com', org: 'x.com', value: 80 });
  // No email listed (or a file from before emails existed): null.
  assert.equal(topReviewers(b, '2026-W44', 'cls', 1)[0].email, null);
  assert.equal(topReviewers({ ...b, emails: undefined }, '2026-W44', 'chars')[0].email, null);
  assert.deepEqual(topReviewers(b, '2026-W01', 'comments'), []);
  // Input order is not mutated.
  assert.deepEqual(b.weeks['2026-W44'].map((x) => x[0]), [1, 2, 3]);
});

test('topReviewers totals a range exactly; org is where most of their comments were', () => {
  const b = board({
    '2026-W43': [[1, 1, 5, 3, 1], [2, 0, 9, 1, 1]],
    '2026-W44': [[1, 0, 4, 2, 1], [1, 1, 3, 1, 1]],
  });
  assert.deepEqual(topReviewers(b, ['2026-W44', '2026-W43'], 'comments'), [
    { id: 1, name: 'n1', email: 'n1@x.com', org: 'y.com', value: 12 },
    { id: 2, name: 'n2', email: null, org: 'x.com', value: 9 },
  ]);
  // The org doesn't change with the metric.
  assert.equal(topReviewers(b, ['2026-W44', '2026-W43'], 'cls')[0].org, 'y.com');
  assert.deepEqual(topReviewers(b, [], 'comments'), []);
});

test('reviewerTotals keeps reviewers with 0 of the metric, with their comments and main org', () => {
  const b = board({
    '2026-W43': [[1, 1, 5, 3, 1, 2], [2, 0, 9, 0, 1]],
    '2026-W44': [[1, 0, 4, 2, 1, 1]],
  });
  const t = reviewerTotals(b, ['2026-W43', '2026-W44'], 'addressed').sort((x, y) => x.id - y.id);
  assert.deepEqual(t, [{ id: 1, value: 3, comments: 9, org: 'y.com' }, { id: 2, value: 0, comments: 9, org: 'x.com' }]);
});

test('quantile interpolates between ranks', () => {
  assert.equal(quantile([1, 2, 3, 4], 0.5), 2.5);
  assert.equal(quantile([1, 2, 3, 4, 5], 0.25), 2);
  assert.equal(quantile([10, 20], 0.25), 12.5);
  assert.equal(quantile([7], 0.75), 7);
  assert.equal(quantile([], 0.5), 0);
});

test('distributionStats: quartiles and the top 10% share', () => {
  const v = [100, 1, 1, 1, 1, 1, 1, 1, 1, 2];
  assert.deepEqual(distributionStats(v), { n: 10, total: 110, q1: 1, median: 1, q3: 1, top10: 1, top10Share: 100 / 110 });
  assert.equal(distributionStats([1, 2, 3, 4]).median, 2.5);
  assert.deepEqual(distributionStats([]), { n: 0, total: 0, q1: 0, median: 0, q3: 0, top10: 0, top10Share: 0 });
});

test('orgSpreads: top orgs by total, folded orgs and the rest as Other, reviewers ascending', () => {
  let id = 0;
  const rows = [
    ...[5, 1, 3].map((value) => ({ id: ++id, value, org: 'a.com' })), // total 9
    ...[20].map((value) => ({ id: ++id, value, org: 'b.com' })), // total 20: one big reviewer ranks first
    ...[1, 1, 1, 1].map((value) => ({ id: ++id, value, org: 'gmail.com' })),
    ...[2].map((value) => ({ id: ++id, value, org: 'c.com' })),
  ];
  const s = orgSpreads(rows, ['gmail.com'], 2);
  assert.deepEqual(s.map((x) => [x.org, x.stats.n]), [['b.com', 1], ['a.com', 3], [OTHER, 5]]);
  assert.deepEqual(s[1].reviewers.map((r) => r.value), [1, 3, 5]);
  assert.equal(s[1].stats.median, 3);
  // Nothing left over: no Other row.
  assert.deepEqual(orgSpreads(rows.slice(0, 4), []).map((x) => x.org), ['b.com', 'a.com']);
  assert.deepEqual(orgSpreads([], []), []);
});

test('topReviewers can leave an org out and still fill the board from the rest', () => {
  const b = board({ '2026-W44': [[1, 0, 9, 1, 0], [2, 1, 5, 1, 0], [3, 0, 1, 1, 0], [3, 1, 7, 3, 0]] });
  // n1 is x.com; most of n3's comments are y.com, so only n1 is left out.
  assert.deepEqual(topReviewers(b, '2026-W44', 'comments', 2).map((x) => x.name), ['n1', 'n3']);
  assert.deepEqual(topReviewers(b, '2026-W44', 'comments', 2, 'x.com').map((x) => x.name), ['n3', 'n2']);
  assert.equal(topReviewers(b, '2026-W44', 'comments', 5, 'nobody.com').length, 3);
});

test('leaderboardOrgs counts reviewers per org, most first, ties by rank', () => {
  const row = (org: string) => ({ id: 1, name: org, email: null, org, value: 1 });
  assert.deepEqual(leaderboardOrgs(['b', 'a', 'a', 'c', 'b', 'a'].map(row)), [
    { org: 'a', reviewers: 3 },
    { org: 'b', reviewers: 2 },
    { org: 'c', reviewers: 1 },
  ]);
  assert.deepEqual(leaderboardOrgs([]), []);
});

test('distinctReviewers counts people once over a range, per folded org', () => {
  const b = board({
    '2026-W43': [[1, 0, 5, 1, 1], [2, 2, 1, 1, 1]],
    '2026-W44': [[1, 0, 6, 1, 1], [1, 1, 1, 1, 1], [3, 2, 1, 1, 1]],
  });
  const d = distinctReviewers(b, ['2026-W43', '2026-W44']);
  assert.equal(d.total, 3);
  assert.deepEqual(Object.fromEntries(d.byOrg), { 'x.com': 1, 'y.com': 1, [OTHER]: 2 });
  assert.equal(distinctReviewers(b, '2026-W43').total, 2);
});

test('ISO weeks round-trip through dates, across year boundaries', () => {
  assert.equal(isoWeekOf(new Date('2026-10-26T00:00:00Z')), '2026-W44'); // Monday
  assert.equal(isoWeekOf(new Date('2026-11-01T00:00:00Z')), '2026-W44'); // Sunday
  assert.equal(isoWeekOf(new Date('2026-11-02T00:00:00Z')), '2026-W45');
  assert.equal(isoWeekOf(new Date('2021-01-03T00:00:00Z')), '2020-W53');
  assert.equal(isoWeekOf(new Date('2024-12-30T00:00:00Z')), '2025-W01');
  assert.equal(isoDate(weekMonday('2026-W44')), '2026-10-26');
  assert.equal(isoDate(weekSunday('2026-W44')), '2026-11-01');
  assert.equal(isoDate(weekMonday('2025-W01')), '2024-12-30');
  assert.equal(isoDate(weekMonday('2020-W53')), '2020-12-28');
  for (let t = Date.UTC(2019, 0, 1); t < Date.UTC(2028, 0, 1); t += 86_400_000) {
    const w = isoWeekOf(new Date(t));
    assert.ok(weekMonday(w).getTime() <= t && t <= weekSunday(w).getTime(), `${new Date(t).toISOString()} ${w}`);
  }
  assert.equal(addWeeks('2026-W02', -3), '2025-W51');
  assert.equal(rangeLength({ from: '2025-W45', to: '2026-W44' }), 52);
  assert.equal(rangeLength({ from: '2026-W44', to: '2026-W44' }), 1);
  assert.equal(parseIsoDate(''), null);
});

test('dataRanges: limits are the union, the default the overlap', () => {
  const r = dataRanges(['2026-W14', '2026-W44'], ['2023-W27', '2026-W40']);
  assert.deepEqual(r.full, { from: '2023-W27', to: '2026-W44' });
  assert.deepEqual(r.common, { from: '2026-W14', to: '2026-W40' });
  // No overlap: fall back to the review weeks.
  assert.deepEqual(dataRanges(['2026-W44'], ['2023-W27']).common, { from: '2026-W44', to: '2026-W44' });
  assert.deepEqual(clampRange({ from: '2027-W01', to: '2020-W01' }, r.full), { from: '2023-W27', to: '2026-W44' });
  assert.deepEqual(weeksIn(['2026-W44', '2026-W13', '2026-W20'], { from: '2026-W14', to: '2026-W44' }), ['2026-W20', '2026-W44']);
});

test('orgTotals sums counts over weeks and recomputes shares from the sums', () => {
  const two: Summary = {
    meta: { weeks: ['2026-W43', '2026-W44'], headline_metric: 'comments' },
    rows: [
      ...SUMMARY.rows,
      { ...row('google.com', 0.5, 100), iso_week: '2026-W43', reviewers: 30 },
      { ...row('microsoft.com', 0.5, 100), iso_week: '2026-W43' },
    ],
  };
  const t = Object.fromEntries(orgTotals(two, ['2026-W43', '2026-W44']).map((x) => [x.org, x]));
  assert.equal(t['google.com'].comments, 1000);
  assert.equal(t['microsoft.com'].comments, 150);
  assert.ok(Math.abs(t['google.com'].share_comments - 1000 / 1200) < 1e-12);
  // Without distinct counts, weekly reviewer counts are summed; with them, they're used as given.
  assert.equal(t['google.com'].reviewers, 40);
  const exact = orgTotals(two, ['2026-W43', '2026-W44'], new Map([['google.com', 35]]));
  assert.equal(exact.find((x) => x.org === 'google.com')!.reviewers, 35);
  assert.equal(exact.find((x) => x.org === 'igalia.com')!.reviewers, 0);
  const one = Object.fromEntries(orgTotals(two, ['2026-W44']).map((x) => [x.org, x]));
  assert.ok(Math.abs(one['google.com'].share_comments - 0.9) < 1e-12);
  assert.equal(topOrgCounts(two, ['2026-W43', '2026-W44'], 'comments', 1)[0].value, 1000);
});

test('orgWeeklyCounts gives one series per top org, with the rest as Other', () => {
  const series = orgWeeklyCounts(SUMMARY, ['2026-W43', '2026-W44'], 'comments', 2);
  assert.deepEqual(series.map((s) => s.org), ['google.com', 'microsoft.com', OTHER]);
  assert.deepEqual(series[0].values, [0, 900]);
  assert.deepEqual(series[2].values, [0, 50]);
});

test('orgWeeklyCounts can exclude an org entirely, letting the next one in', () => {
  const series = orgWeeklyCounts(SUMMARY, ['2026-W43', '2026-W44'], 'comments', 2, 1, ['google.com']);
  assert.deepEqual(series.map((s) => s.org), ['microsoft.com', 'igalia.com', OTHER]);
  // Other is gmail.com + Other; google.com isn't folded into it.
  assert.deepEqual(series[2].values, [0, 20]);
});

test('orgWeeklyCounts smoothing averages weeks before the range, skipping weeks without data', () => {
  const three: Summary = {
    meta: { weeks: ['2026-W42', '2026-W43', '2026-W44'], headline_metric: 'comments' },
    rows: [
      { ...SUMMARY.rows[0], iso_week: '2026-W42', comments: 300 },
      { ...SUMMARY.rows[0], iso_week: '2026-W43', comments: 600 },
      { ...SUMMARY.rows[0], iso_week: '2026-W44', comments: 900 },
    ],
  };
  // W44's 4-week window holds W41 (no data, skipped), W42, W43 and W44.
  const [google] = orgWeeklyCounts(three, ['2026-W44'], 'comments', 7, 4);
  assert.equal(google.org, 'google.com');
  assert.deepEqual(google.values, [600]);
  assert.deepEqual(orgWeeklyCounts(three, ['2026-W43', '2026-W44'], 'comments', 7, 1)[0].values, [600, 900]);
});

test('meanDerivedShare averages the weeks that have usage data', () => {
  const radar = parseRadarWeekly(RADAR);
  assert.equal(meanDerivedShare(radar, ['2026-W44', '2026-W43'], ['Edge']), 0.2);
  assert.equal(meanDerivedShare(radar, ['2026-W43'], ['Edge']), null);
});

test('topBrowsers ranks by peak share', () => {
  assert.deepEqual(topBrowsers(parseRadarWeekly(RADAR), 2, []), ['Chrome', 'ChromeMobile']);
});

test('topBrowsers always includes the given browsers, in peak order', () => {
  const top = topBrowsers(parseRadarWeekly(RADAR), 1, ['Instagram']);
  assert.deepEqual(top, ['Chrome', 'Instagram']);
});

test('formatRatio trims to two places and drops decimals from 10 up', () => {
  assert.equal(formatRatio(0), '0');
  assert.equal(formatRatio(0.25), '0.25');
  assert.equal(formatRatio(1), '1.0');
  assert.equal(formatRatio(1.5), '1.5');
  assert.equal(formatRatio(12.4), '12');
});

test('trimRanked keeps the top n plus later items that match', () => {
  const items = [1, 2, 3, 4, 5, 6];
  assert.deepEqual(trimRanked(items, 2, (x) => x % 2 === 0), [1, 2, 4, 6]);
  assert.deepEqual(trimRanked(items, 10, () => false), items);
  assert.deepEqual(trimRanked(items, 0, (x) => x === 5), [5]);
});

test('smoothRatios: trailing mean share ÷ mean usage, skipping weeks without usage data', () => {
  const pt = (week: string, contribution: number, derived: number | null): RatioPoint => ({
    week,
    org: 'a.com',
    contribution,
    derived,
    ratio: derived === null ? null : contribution / derived,
  });
  const points = [
    pt('2025-W51', 0.2, 0.1),
    pt('2025-W52', 0.4, 0.3),
    pt('2026-W01', 0.6, null), // no Radar week: left out of every window
    pt('2026-W02', 0.6, 0.2),
    { ...pt('2026-W02', 0.5, 0.5), org: 'b.com' }, // other org: not mixed in
  ];
  assert.equal(smoothRatios(points, 1), points);
  const s = smoothRatios(points, 4);
  // First week: a window of one.
  assert.ok(Math.abs(s[0].ratio! - 2) < 1e-12);
  // Across the year boundary: (0.2 + 0.4) / (0.1 + 0.3).
  assert.ok(Math.abs(s[1].ratio! - 1.5) < 1e-12);
  // A week with no usage data still gets a ratio from the weeks before it.
  assert.ok(Math.abs(s[2].ratio! - 1.5) < 1e-12);
  // W02 averages W51, W52 and W02: (0.2 + 0.4 + 0.6) / (0.1 + 0.3 + 0.2).
  assert.ok(Math.abs(s[3].ratio! - 2) < 1e-12);
  assert.ok(Math.abs(s[3].contribution - 0.4) < 1e-12);
  assert.ok(Math.abs(s[4].ratio! - 1) < 1e-12);
  // A window of 2 at W02 holds only W01 (no data) and W02.
  assert.ok(Math.abs(smoothRatios(points, 2)[3].ratio! - 3) < 1e-12);
  // Mean usage below the threshold: no ratio.
  assert.equal(smoothRatios([pt('2026-W02', 0.1, 0.0005)], 4)[0].ratio, null);
});

test('monthTicks labels month starts, with the year on the first tick and January', () => {
  const weeks = Array.from({ length: 52 }, (_, i) => addWeeks('2025-W45', i));
  const t = monthTicks(weeks, 12);
  // Months go by each week's Thursday: 2025-W45 (Thu Nov 6) starts November.
  assert.deepEqual(t.slice(0, 3).map((x) => [weeks[x.index], x.label]), [
    ['2025-W45', 'Nov 2025'],
    ['2025-W49', 'Dec'],
    ['2026-W01', 'Jan 2026'],
  ]);
  assert.equal(t.length, 12);
  // Starting mid-month: no tick until the next month starts.
  assert.deepEqual(monthTicks(weeks.slice(1), 12)[0], { index: 3, label: 'Dec 2025' });
  // Narrow axis: quarters or half-years, aligned to the calendar.
  assert.deepEqual(monthTicks(weeks, 4).map((x) => x.label), ['Jan 2026', 'Apr', 'Jul', 'Oct']);
  assert.deepEqual(monthTicks(weeks, 2).map((x) => x.label), ['Jan 2026', 'Jul']);
  // A range inside one month still gets a label.
  assert.deepEqual(monthTicks(['2026-W42', '2026-W43']), [{ index: 0, label: 'Oct 2026' }]);
  assert.deepEqual(monthTicks(['2026-W44']), [{ index: 0, label: 'Oct 2026' }]);
  assert.deepEqual(monthTicks([]), []);
});

test('weekTitle names the week and its dates', () => {
  assert.equal(weekTitle('2026-W44'), '2026-W44 (Oct 26 – Nov 1)');
});

test('niceTicks steps by 1, 2 or 5 × 10ⁿ up to a round axis end', () => {
  assert.deepEqual(niceTicks(5321), [0, 1000, 2000, 3000, 4000, 5000, 6000]);
  assert.deepEqual(niceTicks(6000), [0, 1000, 2000, 3000, 4000, 5000, 6000]);
  assert.deepEqual(niceTicks(130), [0, 50, 100, 150]);
  assert.deepEqual(niceTicks(0.7), [0, 0.2, 0.4, 0.6, 0.8]);
  assert.deepEqual(niceTicks(0), [0, 1]);
});

const Q = 'https://chromium-review.googlesource.com/q/';
const NOW = new Date('2026-11-04T12:00:00Z');

test('gerritReviewsUrl links to the CLs the reviewer commented on and does not own', () => {
  // Not reviewedby:, which drops a CL once its owner replies after the review.
  assert.equal(gerritReviewsUrl('jkeitel@google.com'), `${Q}commentby:jkeitel@google.com+-owner:jkeitel@google.com`);
  assert.equal(gerritReviewsUrl('a+b@x.org'), `${Q}commentby:a%2Bb@x.org+-owner:a%2Bb@x.org`);
  assert.equal(gerritReviewsUrl(null), null);
  // With a range: CLs changed from the day before its Monday on; no end bound
  // while the range's end plus the slack is still to come...
  assert.equal(gerritReviewsUrl('r@x.org', { from: '2026-W41', to: '2026-W44' }, NOW),
    `${Q}commentby:r@x.org+-owner:r@x.org+after:2026-10-04`);
  // ...and 28 days after its Sunday once that has passed.
  assert.equal(gerritReviewsUrl('r@x.org', { from: '2025-W40', to: '2025-W41' }, NOW),
    `${Q}commentby:r@x.org+-owner:r@x.org+after:2025-09-28+before:2025-11-10`);
});

test('gerritDateTerms bounds a range by when CLs changed', () => {
  assert.deepEqual(gerritDateTerms(undefined, NOW), []);
  assert.deepEqual(gerritDateTerms({ from: '2026-W01', to: '2026-W01' }, NOW), ['after:2025-12-28', 'before:2026-02-02']);
});

test('gerritDirUrl searches the directory for the reviewers’ CLs, most comments first', () => {
  const range = { from: '2026-W41', to: '2026-W44' };
  const link = gerritDirUrl('components/services/storage/', new Map([[11, 2], [22, 9], [33, 2]]), range, NOW)!;
  assert.equal(link.url, `${Q}dir:components/services/storage+after:2026-10-04+` +
    '((commentby:22+-owner:22)+OR+(commentby:11+-owner:11)+OR+(commentby:33+-owner:33))');
  assert.deepEqual([link.path, link.shown, link.total], ['components/services/storage/', 3, 3]);
  // One reviewer: no grouping needed.
  assert.equal(gerritDirUrl('base/', new Map([[5, 1]]), range, NOW)!.url,
    `${Q}dir:base+after:2026-10-04+commentby:5+-owner:5`);
  // At most MAX_LINK_REVIEWERS, keeping those with the most comments.
  const many = new Map(Array.from({ length: MAX_LINK_REVIEWERS + 5 }, (_, i) => [1000 + i, i] as [number, number]));
  const capped = gerritDirUrl('ui/', many, range, NOW)!;
  assert.deepEqual([capped.shown, capped.total], [MAX_LINK_REVIEWERS, MAX_LINK_REVIEWERS + 5]);
  assert.ok(capped.url.includes('commentby:1104+') && !capped.url.includes('commentby:1004+'));
  // Paths dir: can't name, and segments with nobody behind them.
  assert.equal(gerritDirUrl('(no file)', new Map([[5, 1]]), range, NOW), null);
  assert.equal(gerritDirUrl('(top-level files)', new Map([[5, 1]]), range, NOW), null);
  assert.equal(gerritDirUrl('base/', new Map(), range, NOW), null);
  assert.equal(gerritDirUrl('base/', undefined, range, NOW), null);
});

test('dirReviewerIndex sums reviewers up the tree; dirRowLink picks subtree or own bucket', () => {
  // Nodes as in DIRS: 1 chrome/, 2 chrome/browser/, 3 chrome/browser/ui/, 4 content/, 5 content/browser/.
  const who: DirReviewers = {
    meta: { areas_generated_at: 'T' },
    weeks: {
      '2026-W43': [[3, 0, 7, 20]],
      '2026-W44': [[2, 0, 8, 10], [3, 0, 7, 6, 9, 4], [5, 1, 11, 4], [4, 0, 12, 2], [0, 0, 13, 5]],
    },
  };
  const board: DirBoard = { ...DIRS, meta: { ...DIRS.meta, generated_at: 'T' } };
  const idx = dirReviewerIndex(board, who, W, ['google.com'])!;
  assert.deepEqual(Object.fromEntries(idx.total[1]!.get('google.com')!), { 7: 26, 8: 10, 9: 4 });
  assert.deepEqual(Object.fromEntries(idx.own[2]!.get('google.com')!), { 8: 10 });
  // microsoft.com isn't named, so it's in Other.
  assert.deepEqual(Object.fromEntries(idx.total[4]!.get(OTHER)!), { 11: 4 });
  // Only the weeks asked for.
  assert.deepEqual(Object.fromEntries(dirReviewerIndex(board, who, ['2026-W43'], ['google.com'])!.total[1]!.get('google.com')!),
    { 7: 20 });
  // A file from another summarize run is not used: its indexes may not match.
  assert.equal(dirReviewerIndex({ ...DIRS, meta: { ...DIRS.meta, generated_at: 'U' } }, who, W, []), null);
  assert.equal(dirReviewerIndex(DIRS, who, W, []), null);

  const t = dirTotals(board, W, ['google.com'], 'comments');
  const rows = dirRows(board, t, new Set(['d1', 'd2']), 20);
  const row = (key: string) => rows.find((r) => r.key === key)!;
  const range = { from: '2026-W43', to: '2026-W44' };
  // A directory row: its subtree's reviewers, most comments first.
  assert.equal(dirRowLink(board, idx, row('d1'), 'google.com', range, NOW)!.url,
    `${Q}dir:chrome+after:2026-10-18+((commentby:7+-owner:7)+OR+(commentby:8+-owner:8)+OR+(commentby:9+-owner:9))`);
  // "rest of chrome/browser/": only its own bucket's reviewers.
  assert.equal(dirRowLink(board, idx, row('r2'), 'google.com', range, NOW)!.url,
    `${Q}dir:chrome/browser+after:2026-10-18+commentby:8+-owner:8`);
  // Nothing for an org with no reviewers there, for "(no file)", or for "other" groups.
  assert.equal(dirRowLink(board, idx, row('d1'), OTHER, range, NOW), null);
  assert.equal(dirRowLink(board, idx, row('d0'), 'google.com', range, NOW), null);
  const other = dirRows(board, t, new Set(), 1).find((r) => r.kind === 'other')!;
  assert.equal(dirRowLink(board, idx, other, 'google.com', range, NOW), null);
});

// A small directory tree. Rows are [node, org, comments, cls, chars] for each
// node's own bucket.
const DIRS: DirBoard = {
  meta: {
    path_rules: [{ prefix: 'chrome/', included: false }, { prefix: 'chrome/browser/webnn/', included: true }],
    unplaced: '(no file)', root_files: '(top-level files)', dir_limit: 10000,
  },
  orgs: ['google.com', 'microsoft.com'],
  nodes: [
    [-1, '(no file)', 0], // 0
    [-1, 'chrome/', 0], // 1
    [1, 'browser/', 0], // 2
    [2, 'ui/', 0], // 3
    [-1, 'content/', 1], // 4
    [4, 'browser/', 1], // 5
    [4, 'renderer/', 1], // 6
    [2, 'webnn/', 1], // 7: re-included inside an excluded parent
  ],
  weeks: {
    '2026-W43': [[3, 0, 20, 1, 200]],
    '2026-W44': [[2, 0, 10, 1, 100], [3, 0, 10, 1, 100], [5, 0, 6, 1, 60], [5, 1, 4, 1, 40], [6, 0, 3, 1, 30],
      [4, 0, 2, 1, 20], [0, 0, 5, 1, 50], [7, 1, 4, 1, 40]],
  },
};
const W = ['2026-W43', '2026-W44'];

test('dirTotals sums each bucket into its ancestors, and what is in scope', () => {
  const t = dirTotals(DIRS, W, ['google.com'], 'comments');
  assert.deepEqual([t.total[1], t.total[2], t.own[2], t.total[3], t.total[4], t.own[4]], [44, 44, 10, 30, 15, 2]);
  // chrome/ is excluded but holds the re-included webnn/.
  assert.deepEqual([t.inc[1], t.inc[2], t.inc[7], t.inc[4], t.inc[0]], [4, 4, 4, 15, 0]);
  // Orgs outside the list count as Other.
  assert.deepEqual(Object.fromEntries(t.byOrg[4]!), { 'google.com': 11, [OTHER]: 4 });
  assert.equal(dirTotals(DIRS, W, ['google.com'], 'chars').total[1], 440);
  assert.equal(dirTotals(DIRS, ['2026-W44'], ['google.com'], 'cls').total[4], 4);
  assert.deepEqual(topDirOrgs(DIRS, W, 'comments'), ['google.com', 'microsoft.com']);
});

test('dirRows lists a page per level, and expands and collapses', () => {
  const t = dirTotals(DIRS, W, ['google.com', 'microsoft.com'], 'comments');
  const show = (open: string[], page = 2) =>
    dirRows(DIRS, t, new Set(open), page).map((r) => `${'  '.repeat(r.depth)}${r.label} ${r.value}${r.expandable ? (r.expanded ? ' -' : ' +') : ''}`);
  // Top level: the 2 largest, then "other". Re-included directories stay inside their parents.
  assert.deepEqual(show([]), ['chrome/ 44 +', 'content/ 15 +', '1 more 5 +']);
  // A directory opens into its subdirectories plus "rest of" its own files; children add up.
  assert.deepEqual(show(['d1', 'd2']), ['chrome/ 44 -', '  browser/ 44 -', '    ui/ 30', '    rest of browser/ 10',
    '    1 more 4 +', 'content/ 15 +', '1 more 5 +']);
  assert.deepEqual(show(['o:root:2']).slice(-2), ['1 more 5 -', '  (no file) 5']);
  // Page size 1: each "other" reveals one more entry, one level deeper, and
  // keeps an "other" for the rest.
  assert.deepEqual(show(['o:root:1', 'd4', 'o:d4:1', 'o:o:d4:1:2'], 1), [
    'chrome/ 44 +', '2 more 20 -',
    '  content/ 15 -', '    browser/ 10', '    2 more 5 -', '      renderer/ 3', '      1 more 2 -',
    '        rest of content/ 2',
    '  1 more 5 +',
  ]);
  // Collapsing a parent hides everything below it, whatever else is open.
  assert.deepEqual(show(['d4', 'o:d4:1', 'o:o:d4:1:2'], 1), ['chrome/ 44 +', '2 more 20 +']);
  // Each row carries the share of its value that is in scope.
  const top = dirRows(DIRS, t, new Set(), 1);
  assert.deepEqual(top.map((r) => r.included), [4 / 44, 0.75]);
  assert.equal(top[1].count, 2);
  const inBrowser = dirRows(DIRS, t, new Set(['d1', 'd2']), 5).slice(2, 5);
  assert.deepEqual(inBrowser.map((r) => [r.label, r.included]), [['ui/', 0], ['rest of browser/', 0], ['webnn/', 1]]);
});

test('barScale breaks the axis only when a few bars dwarf the rest', () => {
  // chrome/ is over 2x the next: the scale ends at 1.25x the second bar.
  assert.deepEqual(barScale([15425, 4925, 4566, 2665]), { max: 4925 * 1.25, broken: 1 });
  // Two huge bars, then a gap.
  assert.deepEqual(barScale([900, 800, 100, 90]), { max: 125, broken: 2 });
  // No big gap among the top bars: a plain scale.
  assert.deepEqual(barScale([100, 60, 40, 30]), { max: 100, broken: 0 });
  // A gap below the 3rd bar still counts; below the 4th it doesn't (maxBroken = 3).
  assert.deepEqual(barScale([100, 90, 80, 10]), { max: 12.5, broken: 3 });
  assert.deepEqual(barScale([100, 90, 80, 70, 1]), { max: 100, broken: 0 });
  assert.deepEqual(barScale([]), { max: 0, broken: 0 });
  assert.deepEqual(barScale([5, 0]), { max: 5, broken: 0 });
});

// The "Which paths count" list in index.html is written by hand; it must name
// exactly the include/exclude rules in config/paths.txt, each in its group,
// with Excluded first.
test('scope list in index.html matches config/paths.txt', () => {
  const read = (p: string) => readFileSync(fileURLToPath(new URL(p, import.meta.url)), 'utf8');
  const config = { included: [] as string[], excluded: [] as string[] };
  for (const raw of read('../../config/paths.txt').split('\n')) {
    const [kind, prefix] = raw.split('#')[0].trim().split(/\s+/);
    if (kind === 'include') config.included.push(prefix);
    if (kind === 'exclude') config.excluded.push(prefix);
  }
  assert.ok(config.included.length && config.excluded.length, 'no rules read from config/paths.txt');
  const html = read('../index.html');
  const group = (included: boolean) => {
    const m = html.match(new RegExp(`<dl class="scope-list" data-included="${included}">([\\s\\S]*?)</dl>`));
    assert.ok(m, `no ${included ? 'Included' : 'Excluded'} list`);
    const dts = [...m[1].matchAll(/<dt>([\s\S]*?)<\/dt>\s*<dd>[^<\s]/g)].map((d) => d[1]);
    // Every <dt> is followed by a non-empty reason.
    assert.equal(dts.length, (m[1].match(/<dt>/g) ?? []).length, 'a path has no reason');
    return dts.map((d) => d.match(/^<code>([^<]+)<\/code>$/)?.[1] ?? d);
  };
  const sorted = (xs: string[]) => [...xs].sort();
  assert.deepEqual(group(false), sorted(config.excluded));
  assert.deepEqual(group(true), [...sorted(config.included), 'Everything else']);
  assert.ok(html.indexOf('data-included="false"') < html.indexOf('data-included="true"'), 'Excluded comes first');
  // The committed summaries were built with the same rules.
  for (const f of ['org_weekly.json', 'area_weekly.json']) {
    const rules = (JSON.parse(read(`../../summaries/${f}`)) as { meta: { path_rules: PathRule[] } }).meta.path_rules;
    const pick = (inc: boolean) => sorted(rules.filter((r) => r.included === inc).map((r) => r.prefix));
    assert.deepEqual(pick(false), sorted(config.excluded), f);
    assert.deepEqual(pick(true), sorted(config.included), f);
  }
});

test('dirNodeByPath finds a directory with or without its trailing slash', () => {
  assert.equal(dirNodeByPath(DIRS, 'chrome/browser/'), 2);
  assert.equal(dirNodeByPath(DIRS, 'chrome/browser'), 2);
  assert.equal(dirNodeByPath(DIRS, ' content/renderer/ '), 6);
  assert.equal(dirNodeByPath(DIRS, '(no file)'), 0);
  assert.equal(dirNodeByPath(DIRS, 'chrome/brow'), null);
  assert.equal(dirNodeByPath(DIRS, ''), null);
});

test('dirWeeklyCounts: a series per top org in one subtree, the rest as Other', () => {
  // chrome/ holds chrome/browser/, its ui/ and the re-included webnn/: every comment counts.
  assert.deepEqual(dirWeeklyCounts(DIRS, 1, W, 'comments'), [
    { org: 'google.com', values: [20, 20] },
    { org: 'microsoft.com', values: [0, 4] },
  ]);
  assert.deepEqual(dirWeeklyCounts(DIRS, 1, W, 'comments', 1).map((s) => s.org), ['google.com', OTHER]);
  // Leaving google.com out drops it entirely: no Other made of it.
  assert.deepEqual(dirWeeklyCounts(DIRS, 1, W, 'comments', 7, 1, ['google.com']),
    [{ org: 'microsoft.com', values: [0, 4] }]);
  assert.deepEqual(dirWeeklyCounts(DIRS, 4, ['2026-W44'], 'chars'), [
    { org: 'google.com', values: [110] },
    { org: 'microsoft.com', values: [40] },
  ]);
  // Smoothing averages the weeks before the range too.
  assert.deepEqual(dirWeeklyCounts(DIRS, 1, ['2026-W44'], 'comments', 7, 2).map((s) => s.values), [[20], [2]]);
  // An org with nothing in the range isn't named, though it has data elsewhere.
  assert.deepEqual(dirWeeklyCounts(DIRS, 1, ['2026-W43'], 'comments').map((s) => s.org), ['google.com']);
});

test('heatBins line up with the range end; only the first may be short', () => {
  assert.deepEqual(heatBins({ from: '2026-W30', to: '2026-W44' }, 4), [
    { from: '2026-W30', to: '2026-W32' },
    { from: '2026-W33', to: '2026-W36' },
    { from: '2026-W37', to: '2026-W40' },
    { from: '2026-W41', to: '2026-W44' },
  ]);
  assert.deepEqual(heatBins({ from: '2026-W43', to: '2026-W44' }, 1),
    [{ from: '2026-W43', to: '2026-W43' }, { from: '2026-W44', to: '2026-W44' }]);
  assert.deepEqual(heatBins({ from: '2025-W51', to: '2026-W02' }, 2),
    [{ from: '2025-W51', to: '2025-W52' }, { from: '2026-W01', to: '2026-W02' }]);
  assert.deepEqual(heatBins({ from: '2026-W44', to: '2026-W44' }, 13), [{ from: '2026-W44', to: '2026-W44' }]);
});

test('dirTotals can count only some orgs', () => {
  const t = dirTotals(DIRS, W, ['google.com'], 'comments', (o) => o === 'microsoft.com');
  assert.deepEqual([t.total[1], t.total[4], t.total[0]], [4, 4, 0]);
  assert.deepEqual(Object.fromEntries(t.byOrg[4]!), { [OTHER]: 4 });
});

test('heatGrid: directory rows against time bins, "N more" rows summing their entries', () => {
  const orgs = ['google.com', 'microsoft.com'];
  const range = { from: '2026-W43', to: '2026-W44' };
  const g = heatGrid(DIRS, range, 1, 'comments', orgs, new Set(), { page: 2 });
  assert.deepEqual(g.binWeeks, [['2026-W43'], ['2026-W44']]);
  assert.deepEqual(g.rows.map((r) => r.label), ['chrome/', 'content/', '1 more']);
  assert.deepEqual(g.cells.map((row) => row.map((c) => c.value)), [[20, 24], [0, 15], [0, 5]]);
  assert.deepEqual(Object.fromEntries(g.cells[0][1].byOrg), { 'google.com': 20, 'microsoft.com': 4 });
  // A "rest of" row is its directory's own bucket.
  const open = heatGrid(DIRS, range, 1, 'comments', orgs, new Set(['d1', 'd2']));
  const rest = open.rows.findIndex((r) => r.key === 'r2');
  assert.deepEqual(open.cells[rest].map((c) => c.value), [0, 10]);
  // Ranked by one org, counted for all: only directories that org reviewed, ties by path.
  const ms = heatGrid(DIRS, range, 2, 'comments', ['microsoft.com'], new Set(), {
    rankOnly: (o) => o === 'microsoft.com',
  });
  assert.deepEqual(ms.rows.map((r) => [r.label, r.value]), [['chrome/', 4], ['content/', 4]]);
  assert.deepEqual(ms.cells.map((row) => row.map((c) => [c.value, c.byOrg.get('microsoft.com') ?? 0])),
    [[[44, 4]], [[15, 4]]]);
  // Counting only some orgs leaves the rest out of the cells too.
  const noG = heatGrid(DIRS, range, 2, 'comments', ['microsoft.com'], new Set(), { only: (o) => o !== 'google.com' });
  assert.deepEqual(noG.cells.map((row) => row[0].value), [4, 4]);
});

test('rowReviewers merges the kept segments; topAccounts ranks them', () => {
  const who: DirReviewers = {
    meta: { areas_generated_at: 'T' },
    weeks: { '2026-W44': [[3, 0, 7, 6, 9, 4], [2, 0, 8, 10], [7, 1, 7, 2, 11, 4]] },
  };
  const board: DirBoard = { ...DIRS, meta: { ...DIRS.meta, generated_at: 'T' } };
  const idx = dirReviewerIndex(board, who, W, ['google.com', 'microsoft.com'])!;
  const rows = dirRows(board, dirTotals(board, W, [], 'comments'), new Set(['d1']), 1);
  const chrome = rows.find((r) => r.key === 'd1')!;
  const all = rowReviewers(idx, chrome)!;
  // Account 7 reviewed for both orgs here; it's listed under the one with more of its comments.
  assert.deepEqual(Object.fromEntries(all.comments), { 7: 8, 8: 10, 9: 4, 11: 4 });
  assert.equal(all.org.get(7), 'google.com');
  assert.deepEqual(topAccounts(all.comments, 2), [[8, 10], [7, 8]]);
  const ms = rowReviewers(idx, chrome, (o) => o === 'microsoft.com')!;
  assert.deepEqual(Object.fromEntries(ms.comments), { 7: 2, 11: 4 });
  assert.equal(rowReviewers(idx, rows.find((r) => r.kind === 'other')!), undefined);
});

test('addressed weeks: only weeks at the coverage threshold; ranges narrow to them', () => {
  const rows = [
    { iso_week: '2026-W43', org: 'a.com', comments: 10, addressed_comments: 2, pending_comments: 8 },
    { iso_week: '2026-W44', org: 'a.com', comments: 10, addressed_comments: 6, pending_comments: 0 },
    { iso_week: '2026-W44', org: 'b.com', comments: 10, addressed_comments: 2, pending_comments: 0 },
  ].map((r) => ({ share: 0, reviewers: 1, reviewed_cls: 1, review_chars: 1, ai_comments: 0,
    post_merge_comments: 0, share_cls: 0, share_comments: 0, share_chars: 0, ...r }));
  const summary = {
    meta: { weeks: ['2026-W42', '2026-W43', '2026-W44'],
      addressed: { classifier: 'm', complete_at: 0.99, coverage: { '2026-W44': 1, '2026-W43': 0.2, '2026-W42': 0.995 } } },
    rows,
  } as unknown as Summary;
  assert.deepEqual(addressedWeeks(summary), ['2026-W42', '2026-W44']);
  assert.deepEqual(addressedRange(summary, { from: '2026-W43', to: '2026-W44' }),
    { weeks: ['2026-W44'], range: { from: '2026-W44', to: '2026-W44' } });
  assert.deepEqual(addressedRange(summary, { from: '2026-W43', to: '2026-W43' }), { weeks: [], range: null });
  // Summaries from before the metric have no addressed meta at all.
  assert.equal(addressedMeta({ meta: { weeks: [] }, rows: [] }), null);
  assert.deepEqual(addressedWeeks({ meta: { weeks: [] }, rows: [] }), []);
  const t = orgTotals(summary, ['2026-W44']);
  assert.deepEqual(t.map((r) => [r.org, r.addressed_comments, r.share_addressed]), [['a.com', 6, 0.75], ['b.com', 2, 0.25]]);
});

test('reviewerSeries: one reviewer per week; addressed only for classified weeks', () => {
  const b = board({
    '2026-W43': [[1, 1, 5, 3, 1, 2], [2, 0, 9, 1, 1, 4]],
    '2026-W44': [[1, 0, 4, 2, 1, 3], [1, 1, 3, 1, 1, 1]],
  });
  const s = reviewerSeries(b, 1, ['2026-W42', '2026-W43', '2026-W44'], new Set(['2026-W44']));
  assert.deepEqual(s.comments, [0, 5, 7]);
  assert.deepEqual(s.addressed, [null, null, 4]);
  assert.equal(s.org, 'y.com');
  assert.equal(s.email, 'n1@x.com');
});

test('threadBreakdown sums outcomes over weeks; null without the data', () => {
  const summary = { meta: { weeks: [], addressed: { thread_outcomes: ['done_reply', 'model_addressed', 'model_not',
    'no_reply', 'pending'], threads: { W1: [1, 2, 3, 4, 0], W2: [10, 0, 0, 1, 5] } } }, rows: [] } as unknown as Summary;
  assert.deepEqual([...threadBreakdown(summary, ['W1', 'W2', 'W3'])!], [['done_reply', 11], ['model_addressed', 2],
    ['model_not', 3], ['no_reply', 5], ['pending', 5]]);
  assert.equal(threadBreakdown({ meta: { weeks: [] }, rows: [] }, ['W1']), null);
  assert.match(gerritCommentUrl(5, 'ab_cd'), /\/c\/chromium\/src\/\+\/5\/comment\/ab_cd\/$/);
});

test('logAxisFloor: a power of ten below every positive value, where zeros are drawn', () => {
  assert.equal(logAxisFloor([0, 3, 40]), 1);
  assert.equal(logAxisFloor([0, 1, 5]), 0.1);
  assert.equal(logAxisFloor([10, 0]), 1);
  assert.equal(logAxisFloor([1 / 13, 2]), 0.01);
  assert.equal(logAxisFloor([0, 0]), 1);
  assert.equal(logAxisFloor([]), 1);
});
