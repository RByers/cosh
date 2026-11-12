// Unit tests for the pure data/scale modules (no browser).
import { lineDataset, linearStep } from '../src/charts.ts';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { test } from 'vitest';
import {
  authorBoard,
  commitBoard,
  ratioNumerator,
  ratioOrgs,
  ratioSeries,
  gerritAuthoredUrl,
  orgFilesPerCommitSpreads,
  monthlyTotals,
  findPeople,
  complexityGrid,
  complexityScale,
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
  rowAmount,
  topDirOrgs,
  type DirBoard,
  chartedOrgs,
  rangeChartedOrgs,
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
  ratioWeeks,
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
  namedOrgs,
  orgsWithShare,
  NAMED_ORG_MIN_SHARE,
  orgWeeklyCounts,
  orgsByAllTimeReview,
  orgColorSlots,
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
  leaderboardLimit,
  orgsByValue,
  reviewerTotals,
  reviewerHandle,
  quantile,
  orgSpreads,
  orgPerReviewSpreads,
  perReviewMetric,
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
  // Shares are renormalized to leave out Android WebView (10% here).
  // Google: Chrome + Chrome Android.
  assert.ok(Math.abs(by['google.com'].derived! - 0.75 / 0.9) < 1e-12);
  assert.ok(Math.abs(by['google.com'].ratio! - 0.9 / (0.75 / 0.9)) < 1e-12);
  // Meta: its in-app browser share, here 0.5%.
  assert.ok(Math.abs(by['meta.com'].derived! - 0.005 / 0.9) < 1e-12);
  assert.ok(Math.abs(by['microsoft.com'].ratio! - 0.05 / (0.2 / 0.9)) < 1e-12);
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

test('derivedShare leaves Android WebView out of the usage denominator', () => {
  const radar = parseRadarWeekly(`period,period_start,period_end,granularity,device,browser,is_chromium,kind,days,raw_share,chromium_share
2026-W40,2026-09-28,2026-10-04,week,all,Chrome,1,browser,7,0.5,0.6
2026-W40,2026-09-28,2026-10-04,week,all,ChromeDerivative,1,browser,7,0.1,0.1
2026-W40,2026-09-28,2026-10-04,week,all,ChromeMobileWebview,1,webview,7,0.1,0.1
2026-W40,2026-09-28,2026-10-04,week,all,Edge,1,browser,7,0.2,0.2
`);
  // Both excluded buckets come out: Chrome 0.6 of the remaining 0.8.
  assert.ok(Math.abs(derivedShare(radar, '2026-W40', ['Chrome'])! - 0.75) < 1e-12);
  assert.ok(Math.abs(derivedShare(radar, '2026-W40', ['Edge'])! - 0.25) < 1e-12);
  // WebView is credited to nobody, even if mapped.
  assert.ok(Math.abs(derivedShare(radar, '2026-W40', ['Chrome', 'ChromeMobileWebview'])! - 0.75) < 1e-12);
});

test('chartedOrgs skips orgs whose browsers never reach the threshold', () => {
  const radar = parseRadarWeekly(RADAR);
  assert.deepEqual(chartedOrgs(radar, parseOrgBrowsers(ORG_BROWSERS)), ['google.com', 'meta.com', 'microsoft.com', 'samsung.com']);
});

test('rangeChartedOrgs keeps candidates whose mean usage over the range reaches the threshold', () => {
  const radar = parseRadarWeekly(RADAR);
  const ob = parseOrgBrowsers(ORG_BROWSERS);
  const weeks = [...radar.keys()];
  const all = chartedOrgs(radar, ob);
  assert.deepEqual(rangeChartedOrgs(radar, ob, all, weeks), all);
  // A threshold above meta.com's mean drops it but keeps the larger orgs.
  const meta = meanDerivedShare(radar, weeks, ob.get('meta.com')!)!;
  const kept = rangeChartedOrgs(radar, ob, all, weeks, meta * 1.01);
  assert.ok(!kept.includes('meta.com') && kept.includes('google.com'));
  // No usage data for the range: nothing to chart.
  assert.deepEqual(rangeChartedOrgs(radar, ob, all, ['1999-W01']), []);
});

test('namedOrgs: orgs with enough of the review comments, largest first, capped', () => {
  // 1000 comments: google.com 900, microsoft.com 50, igalia.com 30, gmail.com 10, Other 10.
  assert.deepEqual(namedOrgs(SUMMARY, '2026-W44'), ['google.com', 'microsoft.com', 'igalia.com', 'gmail.com']);
  assert.deepEqual(namedOrgs(SUMMARY, '2026-W44', 0.02), ['google.com', 'microsoft.com', 'igalia.com']);
  // The summary's Other row counts toward the total: 50 of 1000 is under 5.01%.
  assert.deepEqual(namedOrgs(SUMMARY, '2026-W44', 0.0501), ['google.com']);
  assert.deepEqual(namedOrgs(SUMMARY, '2026-W44', 0.0025, 2), ['google.com', 'microsoft.com']);
  // Decided by review comments whatever the metric; no weeks, no orgs.
  assert.deepEqual(namedOrgs(SUMMARY, ['1999-W01']), []);
  assert.equal(NAMED_ORG_MIN_SHARE, 0.0025);
});

test('orgsWithShare keeps the orgs with enough of one metric', () => {
  // Of 1000 comments: microsoft.com 5%, igalia.com 3%, gmail.com 1%; nova.com has none.
  const orgs = ['google.com', 'microsoft.com', 'igalia.com', 'gmail.com', 'nova.com'];
  assert.deepEqual(orgsWithShare(SUMMARY, '2026-W44', 'comments', orgs), ['google.com', 'microsoft.com', 'igalia.com', 'gmail.com']);
  assert.deepEqual(orgsWithShare(SUMMARY, '2026-W44', 'comments', orgs, 0.02), ['google.com', 'microsoft.com', 'igalia.com']);
  // No data for the metric or weeks: none.
  assert.deepEqual(orgsWithShare(SUMMARY, ['1999-W01'], 'comments', orgs), []);
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
  assert.deepEqual(t, [
    { id: 1, value: 3, comments: 9, reviews: 5, org: 'y.com' },
    { id: 2, value: 0, comments: 9, reviews: 0, org: 'x.com' },
  ]);
});

test('reviewerHandle: the email, else the name, else the account id', () => {
  const b = board({});
  assert.equal(reviewerHandle(b, 1), 'n1@x.com');
  assert.equal(reviewerHandle(b, 2), 'n2');
  assert.equal(reviewerHandle({ ...b, emails: undefined }, 3), 'n3');
  assert.equal(reviewerHandle(b, 9), 'Account 9');
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

test('orgSpreads: named orgs by total, folded orgs and the rest as Other, reviewers ascending', () => {
  let id = 0;
  const rows = [
    ...[5, 1, 3].map((value) => ({ id: ++id, value, org: 'a.com' })), // total 9
    ...[20].map((value) => ({ id: ++id, value, org: 'b.com' })), // total 20: one big reviewer ranks first
    ...[1, 1, 1, 1].map((value) => ({ id: ++id, value, org: 'gmail.com' })),
    ...[2].map((value) => ({ id: ++id, value, org: 'c.com' })),
  ];
  const s = orgSpreads(rows, ['gmail.com'], ['a.com', 'b.com']);
  assert.deepEqual(s.map((x) => [x.org, x.stats.n]), [['b.com', 1], ['a.com', 3], [OTHER, 5]]);
  assert.deepEqual(s[1].reviewers.map((r) => r.value), [1, 3, 5]);
  assert.equal(s[1].stats.median, 3);
  // Nothing left over: no Other row.
  assert.deepEqual(orgSpreads(rows.slice(0, 4), [], ['a.com', 'b.com']).map((x) => x.org), ['b.com', 'a.com']);
  // No named orgs: everyone is Other.
  assert.deepEqual(orgSpreads(rows.slice(0, 4), []).map((x) => x.org), [OTHER]);
  assert.deepEqual(orgSpreads([], []), []);
});

test('orgSpreads with an order: those orgs that have reviewers, in that order, then Other', () => {
  const rows = [
    { id: 1, value: 1, org: 'a.com' },
    { id: 2, value: 9, org: 'b.com' },
    { id: 3, value: 4, org: 'c.com' },
    { id: 4, value: 2, org: 'gmail.com' },
  ];
  const s = orgSpreads(rows, ['gmail.com'], [], ['a.com', 'z.com', 'c.com', OTHER]);
  assert.deepEqual(s.map((x) => [x.org, x.reviewers.map((r) => r.id)]), [['a.com', [1]], ['c.com', [3]], [OTHER, [4, 2]]]);
});

test('orgPerReviewSpreads: each reviewer\'s metric per reviewed CL, pooled per row', () => {
  const b = board({
    '2026-W43': [[1, 0, 8, 2, 300, 2], [3, 1, 10, 2, 50, 1]],
    '2026-W44': [[1, 0, 4, 2, 100, 0], [2, 0, 6, 3, 90, 0], [4, 2, 9, 3, 10]],
  });
  const weeks = ['2026-W43', '2026-W44'];
  const order = ['y.com', 'x.com'];
  // n3 (y.com) has only 2 reviewed CLs: left out, so y.com gets no row.
  const c = orgPerReviewSpreads(b, weeks, 'comments', order);
  assert.deepEqual(c.map((s) => [s.org, s.reviewers]), [
    ['x.com', [{ id: 2, value: 2 }, { id: 1, value: 3 }]],
    [OTHER, [{ id: 4, value: 3 }]],
  ]);
  assert.equal(c[0].stats.median, 2.5);
  assert.equal(c[0].pooled, 18 / 7);
  // Reviewed CLs as the metric: review comments per review.
  assert.deepEqual(orgPerReviewSpreads(b, weeks, 'cls', order), c);
  assert.equal(perReviewMetric('cls'), 'comments');
  assert.equal(perReviewMetric('chars'), 'chars');
  // Addressed: reviewers with none addressed stay, at 0.
  const a = orgPerReviewSpreads(b, weeks, 'addressed', order);
  assert.deepEqual(a[0].reviewers, [{ id: 2, value: 0 }, { id: 1, value: 0.5 }]);
  assert.equal(a[0].pooled, 2 / 7);
  assert.deepEqual(orgPerReviewSpreads(b, weeks, 'chars', order)[0].reviewers.map((r) => r.value), [30, 100]);
  // A lower minimum lets n3 in.
  assert.deepEqual(orgPerReviewSpreads(b, weeks, 'comments', order, 2).map((s) => s.org), ['y.com', 'x.com', OTHER]);
  assert.deepEqual(orgPerReviewSpreads(b, [], 'comments', order), []);
});

test('orgsByValue ranks orgs by their reviewers\' totals, each reviewer under their main org', () => {
  const b = board({ '2026-W44': [[1, 0, 9, 1, 0], [2, 1, 5, 1, 0], [3, 0, 1, 1, 0], [3, 1, 7, 3, 0]] });
  // n1 is x.com (9); most of n3's comments are y.com, so y.com has 5 + 8.
  const all = topReviewers(b, '2026-W44', 'comments', Infinity);
  assert.equal(all.length, 3);
  assert.deepEqual(orgsByValue(all), ['y.com', 'x.com']);
  assert.deepEqual(orgsByValue([]), []);
  assert.deepEqual(orgsByValue([{ org: 'b.com', value: 1 }, { org: 'a.com', value: 1 }]), ['a.com', 'b.com']);
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

test('orgWeeklyCounts gives one series per named org, with the rest as Other', () => {
  const series = orgWeeklyCounts(SUMMARY, ['2026-W43', '2026-W44'], 'comments', ['microsoft.com', 'google.com']);
  assert.deepEqual(series.map((s) => s.org), ['google.com', 'microsoft.com', OTHER]);
  assert.deepEqual(series[0].values, [0, 900]);
  assert.deepEqual(series[2].values, [0, 50]);
});

test('orgWeeklyCounts can exclude an org entirely, the other named orgs staying', () => {
  const series = orgWeeklyCounts(SUMMARY, ['2026-W43', '2026-W44'], 'comments', ['google.com', 'microsoft.com'], 1, ['google.com']);
  assert.deepEqual(series.map((s) => s.org), ['microsoft.com', OTHER]);
  // Other is igalia.com + gmail.com + Other; google.com isn't folded into it.
  assert.deepEqual(series[1].values, [0, 50]);
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
  const [google] = orgWeeklyCounts(three, ['2026-W44'], 'comments', ['google.com'], 4);
  assert.equal(google.org, 'google.com');
  assert.deepEqual(google.values, [600]);
  assert.deepEqual(orgWeeklyCounts(three, ['2026-W43', '2026-W44'], 'comments', ['google.com'], 1)[0].values, [600, 900]);
});

test('orgWeeklyCounts with dataWeeks skips weeks that have no data for the metric', () => {
  const three: Summary = {
    meta: { weeks: ['2026-W42', '2026-W43', '2026-W44'], headline_metric: 'comments' },
    rows: [
      { ...SUMMARY.rows[0], iso_week: '2026-W42', addressed_comments: 0 },
      { ...SUMMARY.rows[0], iso_week: '2026-W43', addressed_comments: 60 },
      { ...SUMMARY.rows[0], iso_week: '2026-W44', addressed_comments: 90 },
    ],
  };
  // W42 is unclassified: its 0 is missing data, not a zero week.
  const [google] = orgWeeklyCounts(three, ['2026-W43', '2026-W44'], 'addressed', ['google.com'], 4, [], ['2026-W43', '2026-W44']);
  assert.deepEqual(google.values, [60, 75]);
  // Without dataWeeks the 0 is averaged in.
  assert.deepEqual(orgWeeklyCounts(three, ['2026-W43', '2026-W44'], 'addressed', ['google.com'], 4)[0].values, [30, 50]);
});

test('computeRatios with weeks gives no points for other weeks, so smoothing skips them', () => {
  const radar = parseRadarWeekly(RADAR);
  const orgs = parseOrgBrowsers(ORG_BROWSERS);
  const two: Summary = {
    meta: { weeks: ['2026-W43', '2026-W44'], headline_metric: 'comments' },
    rows: [...SUMMARY.rows, ...SUMMARY.rows.map((r) => ({ ...r, iso_week: '2026-W43', share_comments: 0 }))],
  };
  // The radar fixture has W44 only; reuse it for W43.
  radar.set('2026-W43', radar.get('2026-W44')!);
  const only = computeRatios(two, radar, orgs, 'comments', undefined, ['2026-W44']);
  assert.ok(only.every((p) => p.week === '2026-W44'));
  const g = (pts: ReturnType<typeof computeRatios>) =>
    smoothRatios(pts, 4, undefined, false).find((p) => p.org === 'google.com' && p.week === '2026-W44')!.ratio!;
  // Google's usage share, renormalized without Android WebView: 0.75 / 0.9.
  const google = 0.75 / 0.9;
  assert.ok(Math.abs(g(only) - 0.9 / google) < 1e-12);
  // With W43 included its zero share halves the average.
  assert.ok(Math.abs(g(computeRatios(two, radar, orgs, 'comments')) - 0.45 / google) < 1e-12);
});

test('ratioWeeks keeps weeks with complete usage data and, if given, metric data', () => {
  // The fixture has a complete Radar week for 2026-W44 only.
  const radar = parseRadarWeekly(RADAR);
  const weeks = ['2026-W42', '2026-W43', '2026-W44'];
  assert.deepEqual(ratioWeeks(weeks, radar), ['2026-W44']);
  radar.set('2026-W42', radar.get('2026-W44')!);
  assert.deepEqual(ratioWeeks(weeks, radar), ['2026-W42', '2026-W44']);
  assert.deepEqual(ratioWeeks(weeks, radar, ['2026-W43', '2026-W44']), ['2026-W44']);
  assert.deepEqual(ratioWeeks([], radar), []);
});

test('meanDerivedShare averages the weeks that have usage data', () => {
  const radar = parseRadarWeekly(RADAR);
  // Edge's 0.2, renormalized without Android WebView (0.1).
  assert.ok(Math.abs(meanDerivedShare(radar, ['2026-W44', '2026-W43'], ['Edge'])! - 0.2 / 0.9) < 1e-12);
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
  // Without fullWindows, so the first weeks average what they have.
  const s = smoothRatios(points, 4, undefined, false);
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
  assert.ok(Math.abs(smoothRatios(points, 2, undefined, false)[3].ratio! - 3) < 1e-12);
  // Mean usage below the threshold: no ratio.
  assert.equal(smoothRatios([pt('2026-W02', 0.1, 0.0005)], 4, undefined, false)[0].ratio, null);
});

test('smoothRatios gives no ratio until the window is full of data', () => {
  const pt = (week: string, org = 'a.com', derived: number | null = 0.1): RatioPoint => ({
    week,
    org,
    contribution: 0.1,
    derived,
    ratio: derived === null ? null : 0.1 / derived,
  });
  // Usage data starts at W50 (W49 has none); W01 is the first week whose
  // 4-week window (W50..W01) doesn't reach back before it, for every org.
  const points = [pt('2025-W49', 'a.com', null), pt('2025-W50'), pt('2025-W51'), pt('2025-W52'), pt('2026-W01'), pt('2026-W02', 'b.com')];
  const s = smoothRatios(points, 4);
  assert.deepEqual(
    s.map((p) => p.ratio !== null),
    [false, false, false, false, true, true],
  );
  assert.ok(Math.abs(s[4].ratio! - 1) < 1e-12);
  assert.equal(smoothRatios(points, 1), points);
});

test('monthTicks labels month starts, with the year on the first tick and wherever it changes', () => {
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
  // Quarterly starts off the calendar's quarters (3-month heatmap columns): the
  // year shows where it changes, even when no tick is in January. (2023-W45 is
  // mid-November, so it gets no tick.)
  const quarters = Array.from({ length: 12 }, (_, i) => addWeeks('2023-W45', 13 * i));
  assert.deepEqual(monthTicks(quarters, 12).map((x) => x.label), [
    'Feb 2024', 'May', 'Aug', 'Nov', 'Feb 2025', 'May', 'Aug', 'Nov', 'Feb 2026', 'May', 'Aug',
  ]);
  // Too many for 4 ticks and none on Jan/Apr/Jul/Oct: thinned evenly instead.
  assert.deepEqual(monthTicks(quarters, 4).map((x) => x.label), ['Feb 2024', 'Nov', 'Aug 2025', 'May 2026']);
  // Yearly starts: every tick is a new year.
  const years = Array.from({ length: 3 }, (_, i) => addWeeks('2023-W44', 52 * i));
  assert.deepEqual(monthTicks(years, 12).map((x) => x.label), ['Nov 2023', 'Oct 2024', 'Oct 2025']);
});

test('weekTitle names the week by its dates', () => {
  assert.equal(weekTitle('2026-W44'), 'Oct 26 – Nov 1, 2026');
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
/** The named orgs in the directory fixtures. */
const DN = ['google.com', 'microsoft.com'];

test('orgWeeklyCounts with nameable folds the other orgs into Other', () => {
  const series = orgWeeklyCounts(SUMMARY, ['2026-W44'], 'comments', ['google.com', 'microsoft.com', 'igalia.com'], 1, [], undefined, (o) => o !== 'microsoft.com');
  assert.deepEqual(series.map((s) => s.org), ['google.com', 'igalia.com', OTHER]);
  // Other is microsoft.com + gmail.com + Other.
  assert.deepEqual(series[2].values, [70]);
});

test('orgsByAllTimeReview ranks orgs over every summary week, Other left out', () => {
  assert.deepEqual(orgsByAllTimeReview(SUMMARY), ['google.com', 'microsoft.com', 'igalia.com', 'gmail.com']);
});

test('orgColorSlots: vivid colours for the top orgs, muted ones for value-chart orgs, then the next', () => {
  const ranked = ['g.com', 'i.com', 'm.com', 'b.com', 'x.com', 'z.com'];
  const slots = orgColorSlots(ranked, ['g.com', 's.com', 'm.com', 'y.com'], 2);
  // g.com and i.com take the vivid 0 and 1; s.com, m.com (not in the top 2)
  // take the muted 2 and 3; y.com and the rest have none.
  assert.deepEqual(Object.fromEntries(slots), { 'g.com': 0, 'i.com': 1, 's.com': 2, 'm.com': 3 });
  // Spare muted colours go to the next orgs by review.
  assert.deepEqual(Object.fromEntries(orgColorSlots(ranked, ['g.com'], 2)), { 'g.com': 0, 'i.com': 1, 'm.com': 2, 'b.com': 3 });
  assert.deepEqual(Object.fromEntries(orgColorSlots(['a.com'], [], 6)), { 'a.com': 0 });
});

test('dirTotals sums each bucket into its ancestors, and what is in scope', () => {
  const t = dirTotals(DIRS, W, ['google.com'], 'comments');
  assert.deepEqual([t.total[1], t.total[2], t.own[2], t.total[3], t.total[4], t.own[4]], [44, 44, 10, 30, 15, 2]);
  // chrome/ is excluded but holds the re-included webnn/.
  assert.deepEqual([t.inc[1], t.inc[2], t.inc[7], t.inc[4], t.inc[0]], [4, 4, 4, 15, 0]);
  // Orgs outside the list count as Other.
  assert.deepEqual(Object.fromEntries(t.byOrg(4)!), { 'google.com': 11, [OTHER]: 4 });
  assert.equal(dirTotals(DIRS, W, ['google.com'], 'chars').total[1], 440);
  assert.equal(dirTotals(DIRS, ['2026-W44'], ['google.com'], 'cls').total[4], 4);
  assert.deepEqual(topDirOrgs(DIRS, W, 'comments', ['microsoft.com', 'google.com']), ['google.com', 'microsoft.com']);
  assert.deepEqual(topDirOrgs(DIRS, W, 'comments', ['microsoft.com']), ['microsoft.com']);
  assert.deepEqual(topDirOrgs(DIRS, W, 'comments', DN, (o) => o !== 'google.com'), ['microsoft.com']);
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

test('complexityGrid: comments over reviews per directory and week, rows by reviews, (no file) left out', () => {
  // Every fixture row is one reviewed CL, so a node's reviews are its row count.
  const range = { from: '2026-W43', to: '2026-W44' };
  const g = complexityGrid(DIRS, range, 1, 'comments', new Set(), 2);
  assert.deepEqual(g.bins, [{ from: '2026-W43', to: '2026-W43' }, { from: '2026-W44', to: '2026-W44' }]);
  // chrome/ and content/ tie on 4 reviews (path order); (no file) isn't listed, so no "more" row.
  assert.deepEqual(g.rows.map((r) => r.label), ['chrome/', 'content/']);
  assert.deepEqual(g.cells, [
    [{ num: 20, reviews: 1 }, { num: 24, reviews: 3 }],
    [{ num: 0, reviews: 0 }, { num: 15, reviews: 4 }],
  ]);
  assert.deepEqual(g.totals, [{ num: 44, reviews: 4 }, { num: 15, reviews: 4 }]);
  assert.deepEqual(g.overall, { num: 59, reviews: 8 });
  // Expanded: ui/ has the most reviews; webnn/ ties with "rest of browser/" (a
  // directory first), which lands in "1 more".
  const open = complexityGrid(DIRS, range, 2, 'comments', new Set(['d1', 'd2']), 2);
  assert.deepEqual(open.rows.map((r) => r.label).slice(0, 5), ['chrome/', 'browser/', 'ui/', 'webnn/', '1 more']);
  assert.deepEqual(open.totals.slice(2, 5), [{ num: 30, reviews: 2 }, { num: 4, reviews: 1 }, { num: 10, reviews: 1 }]);
});

test('complexityScale: 5th to 95th percentile of the cells with enough reviews', () => {
  const cell = (v: number, reviews = 10) => ({ num: v * reviews, reviews });
  const cells = [Array.from({ length: 20 }, (_, i) => cell(i + 1)), [cell(1000, 9), cell(0, 0)]];
  const grid = { bins: [], rows: [], cells, totals: [], overall: cell(1) };
  // 20 shaded cells, 1..20: the 5th percentile is the 2nd, the 95th the 20th;
  // the cell with 9 reviews doesn't count.
  assert.deepEqual(complexityScale(grid), { lo: 2, hi: 20 });
  assert.deepEqual(complexityScale({ ...grid, cells: [[cell(3, 1)]] }), { lo: 0, hi: 0 });
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

// The "Which paths count" list in value.html is written by hand; it must name
// exactly the include/exclude rules in config/paths.txt, each in its group,
// with Excluded first.
test('scope list in value.html matches config/paths.txt', () => {
  const read = (p: string) => readFileSync(fileURLToPath(new URL(p, import.meta.url)), 'utf8');
  const config = { included: [] as string[], excluded: [] as string[] };
  for (const raw of read('../../config/paths.txt').split('\n')) {
    const [kind, prefix] = raw.split('#')[0].trim().split(/\s+/);
    if (kind === 'include') config.included.push(prefix);
    if (kind === 'exclude') config.excluded.push(prefix);
  }
  assert.ok(config.included.length && config.excluded.length, 'no rules read from config/paths.txt');
  const html = read('../value.html');
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

test('dirWeeklyCounts: a series per named org in one subtree, the rest as Other', () => {
  // chrome/ holds chrome/browser/, its ui/ and the re-included webnn/: every comment counts.
  assert.deepEqual(dirWeeklyCounts(DIRS, 1, W, 'comments', DN), [
    { org: 'google.com', values: [20, 20] },
    { org: 'microsoft.com', values: [0, 4] },
  ]);
  assert.deepEqual(dirWeeklyCounts(DIRS, 1, W, 'comments', ['google.com']).map((s) => s.org), ['google.com', OTHER]);
  // Leaving google.com out drops it entirely: no Other made of it.
  assert.deepEqual(dirWeeklyCounts(DIRS, 1, W, 'comments', DN, 1, ['google.com']),
    [{ org: 'microsoft.com', values: [0, 4] }]);
  assert.deepEqual(dirWeeklyCounts(DIRS, 4, ['2026-W44'], 'chars', DN), [
    { org: 'google.com', values: [110] },
    { org: 'microsoft.com', values: [40] },
  ]);
  // Smoothing averages the weeks before the range too.
  assert.deepEqual(dirWeeklyCounts(DIRS, 1, ['2026-W44'], 'comments', DN, 2).map((s) => s.values), [[20], [2]]);
  // An org with nothing in the range isn't named, though it has data elsewhere.
  assert.deepEqual(dirWeeklyCounts(DIRS, 1, ['2026-W43'], 'comments', DN).map((s) => s.org), ['google.com']);
  // Orgs nameable rejects fold into Other.
  assert.deepEqual(dirWeeklyCounts(DIRS, 1, W, 'comments', DN, 1, [], undefined, (o) => o === 'google.com'), [
    { org: 'google.com', values: [20, 20] },
    { org: OTHER, values: [0, 4] },
  ]);
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
  assert.deepEqual(Object.fromEntries(t.byOrg(4)!), { [OTHER]: 4 });
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

test('heatGrid cells equal each row\'s rowAmount in a full dirTotals of its bin', () => {
  // heatGrid sums only the nodes its rows show; dirTotals sums the whole tree.
  const range = { from: '2026-W43', to: '2026-W44' };
  const filters = [undefined, (o: string) => o !== 'google.com', (o: string) => o === 'microsoft.com'];
  for (const metric of ['comments', 'chars', 'cls'] as const) {
    for (const only of filters) {
      for (const expanded of [new Set<string>(), new Set(['d1', 'd2', 'd3']), new Set(['d1', 'o::1'])]) {
        for (const orgs of [['google.com'], ['google.com', 'microsoft.com'], []]) {
          const g = heatGrid(DIRS, range, 1, metric, orgs, expanded, { only, page: 1 });
          g.rows.forEach((r, ri) =>
            g.binWeeks.forEach((w, bi) => {
              const want = rowAmount(dirTotals(DIRS, w, orgs, metric, only), r);
              const got = g.cells[ri][bi];
              assert.deepEqual([got.value, Object.fromEntries(got.byOrg)], [want.value, Object.fromEntries(want.byOrg)],
                `${metric} ${r.key} bin ${bi}`);
            }),
          );
        }
      }
    }
  }
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

test('lineDataset draws no dots except for a week with gaps on both sides', () => {
  assert.deepEqual(lineDataset('a', '#000', [1, 2, 3]).pointRadius, [0, 0, 0]);
  assert.deepEqual(lineDataset('a', '#000', [1, null, 3, 4, null]).pointRadius, [2, 0, 0, 0, 0]);
  assert.deepEqual(lineDataset('a', '#000', [{ y: null }, { y: 5 }, { y: null }]).pointRadius, [0, 2, 0]);
  assert.equal(lineDataset('a', '#000', [1]).pointHoverRadius, 4);
});

test("leaderboard size 'all' takes every reviewer with a nonzero value", () => {
  assert.equal(leaderboardLimit(50), 50);
  assert.equal(leaderboardLimit('all'), Infinity);
  const b = board({ '2026-W44': [[1, 0, 9, 1, 0], [2, 1, 5, 1, 0], [3, 0, 0, 1, 0], [4, 1, 7, 3, 0]] });
  assert.deepEqual(topReviewers(b, '2026-W44', 'comments', leaderboardLimit('all')).map((x) => x.value), [9, 7, 5]);
});

test('Review Tone: praise boards, dates and Gerrit links', async () => {
  const { netBoard, praiseTotal, praisePeople, weeksBetween, monthLabel, dayLabel, gerritLink } = await import(
    '../src/tone.ts'
  );
  const d = {
    weeks: ['2026-W37', '2026-W44'] as [string, string],
    people: { 'a@x.org': 'Ann', 'b@x.org': 'Bo', 'c@x.org': 'Cy' },
    weekly: [
      { week: '2026-W37', email: 'a@x.org', given: 2, received: 0 },
      { week: '2026-W38', email: 'a@x.org', given: 1, received: 1 },
      { week: '2026-W37', email: 'b@x.org', given: 0, received: 2 },
      { week: '2026-W38', email: 'c@x.org', given: 1, received: 1 },
    ],
    net_scale: 5,
    net: {
      all: {
        given: [{ email: 'a@x.org', name: 'Ann', score: 1.4, praise: 3 }, { email: 'c@x.org', name: 'Cy', score: 0.5, praise: 1 }],
        received: [{ email: 'b@x.org', name: 'Bo', score: 1.1, praise: 2 }, { email: 'a@x.org', name: 'Ann', score: 0.4, praise: 1 }],
      },
      month: { given: [], received: [{ email: 'a@x.org', name: 'Ann', score: 0.4, praise: 1 }] },
    },
  };
  assert.deepEqual(netBoard(d, 'given', 'all').map((r) => [r.name, r.score]), [['Ann', 1.4], ['Cy', 0.5]]);
  assert.deepEqual(netBoard(d, 'received', 'all', 1).map((r) => r.name), ['Bo']);
  assert.deepEqual(netBoard(d, 'received', 'all', 'all').map((r) => r.name), ['Bo', 'Ann']);
  assert.deepEqual(netBoard(d, 'given', 'month'), []);
  assert.deepEqual(netBoard(d, 'received', 'month').map((r) => r.name), ['Ann']);
  assert.equal(praiseTotal(d), 4);
  assert.equal(praisePeople(d), 3);
  assert.equal(weeksBetween(['2026-W37', '2026-W44']), '7 Sept and 1 Nov 2026'.replace('Sept', fmtMonthShort(8)));
  assert.equal(weeksBetween(['2025-W52', '2026-W02']), `22 Dec 2025 and 11 Jan 2026`);
  assert.equal(monthLabel('2026-10'), 'Oct 2026');
  assert.equal(dayLabel('2026-10-02'), '2 Oct 2026');
  assert.equal(gerritLink('https://chromium-review.googlesource.com/c/chromium/src/+/1/comment/x/'),
    'https://chromium-review.googlesource.com/c/chromium/src/+/1/comment/x/');
  assert.equal(gerritLink('javascript:alert(1)'), null);
  assert.equal(gerritLink('https://chromium-review.googlesource.com.evil.example/'), null);
});

test('Review Tone: periods and ranges', async () => {
  const { periodWeeks, periodsOf, periodKind, happyComments, praiseTotal, praisePeople } = await import('../src/tone.ts');
  // Weeks go to the month and year of their Thursday: 2026-W01's is 1 Jan 2026.
  assert.deepEqual(periodsOf(['2025-W45', '2026-W02']),
    { years: ['2025', '2026'], months: ['2025-11', '2025-12', '2026-01'] });
  assert.deepEqual(periodWeeks(['2025-W45', '2026-W44'], 'all'), ['2025-W45', '2026-W44']);
  assert.deepEqual(periodWeeks(['2025-W45', '2026-W44'], '2025'), ['2025-W45', '2025-W52']);
  assert.deepEqual(periodWeeks(['2025-W45', '2026-W44'], '2026'), ['2026-W01', '2026-W44']);
  assert.deepEqual(periodWeeks(['2025-W45', '2026-W44'], '2026-01'), ['2026-W01', '2026-W05']);
  assert.deepEqual(periodWeeks(['2025-W45', '2026-W44'], '2026-10'), ['2026-W40', '2026-W44']);
  assert.equal(periodWeeks(['2025-W45', '2026-W44'], '2024'), null);
  assert.deepEqual(['all', '2026', '2026-10'].map(periodKind), ['all', 'year', 'month']);
  const c = (week: string) => ({ text: '', date: '', week, score: 0.5, writer: '', writer_email: '', recipient: '',
    recipient_email: 'a@x.org', url: '' });
  const pc = { weeks: ['2026-W40', '2026-W44'] as [string, string], praise: [],
    comments: { x: c('2026-W40'), y: c('2026-W44') }, happy: { authors: { 'a@x.org': ['x', 'y'] }, reviewers: {} } };
  assert.equal(happyComments(pc, 'a@x.org', 'authors').length, 2);
  assert.deepEqual(happyComments(pc, 'a@x.org', 'authors', ['2026-W41', '2026-W44']).map((x) => x.week), ['2026-W44']);
  assert.deepEqual(happyComments(pc, 'b@x.org', 'authors'), []);
  const d = {
    weeks: ['2026-W37', '2026-W44'] as [string, string],
    people: { 'a@x.org': 'Ann', 'b@x.org': 'Bo' },
    weekly: [
      { week: '2026-W37', email: 'a@x.org', given: 5, received: 0 },
      { week: '2026-W44', email: 'b@x.org', given: 1, received: 0 },
      { week: '2026-W44', email: 'a@x.org', given: 0, received: 1 },
    ],
    net_scale: 5,
    net: { all: { given: [], received: [] } },
  };
  const month: [string, string] = ['2026-W41', '2026-W44'];
  assert.equal(praiseTotal(d, month), 1);
  assert.equal(praisePeople(d, month), 2);
});

test('Review Tone: counts per month and the lookup box', async () => {
  const { byMonth, findPerson } = await import('../src/tone.ts');
  const d = {
    people: { 'a@x.org': 'Ann', 'b@x.org': 'Bo', 'B@y.org': 'Bo' },
  };
  // 2026-W01's Thursday is 1 Jan; 2026-W05's is 29 Jan; February has none.
  const given = [{ week: '2025-W52' }, { week: '2025-W52' }, { week: '2026-W01' }, { week: '2027-W01' }];
  const received = [{ week: '2026-W05' }];
  assert.deepEqual(byMonth(['2025-W52', '2026-W09'], [given, received]),
    { months: ['2025-12', '2026-01', '2026-02'], counts: [[2, 1, 0], [0, 1, 0]] });
  assert.deepEqual(byMonth(['2025-W52', '2026-W09'], [[]]).counts, [[0, 0, 0]]);
  assert.deepEqual(findPerson(d, ' A@X.org '), { email: 'a@x.org', name: 'Ann' });
  assert.deepEqual(findPerson(d, 'ann'), { email: 'a@x.org', name: 'Ann' });
  assert.equal(findPerson(d, 'Bo'), null, 'two people share the name');
  assert.equal(findPerson(d, ''), null);
});

test('Review Tone: how a popup comment relates to its person', async () => {
  const { relation } = await import('../src/tone.ts');
  const c = { text: '', date: '', week: '2026-W44', score: 0.5, writer: 'A', writer_email: 'a@x.org', recipient: 'B',
    recipient_email: 'b@x.org', url: '', writer_role: 'reviewer' as const, recipient_role: 'author' as const };
  assert.equal(relation(c, 'a@x.org'), 'given-reviewer');
  assert.equal(relation(c, 'b@x.org'), 'received-author');
  assert.equal(relation({ ...c, writer_role: undefined }, 'a@x.org'), null, 'older files have no roles');
});

test('Review Tone: lookup suggestions', async () => {
  const { suggestPeople } = await import('../src/tone.ts');
  const people: Record<string, string> = { 'zed@x.org': 'Ann Zed', 'ann@x.org': 'Ann', 'bo@x.org': 'Bo Annis' };
  for (let i = 0; i < 20; i++) people[`p${i}@y.org`] = `Person ${i}`;
  assert.deepEqual(suggestPeople({ people }, ''), []);
  assert.deepEqual(suggestPeople({ people }, '  '), []);
  // Starts-with first (by name), then contains.
  assert.deepEqual(suggestPeople({ people }, 'ANN').map((p) => p.email), ['ann@x.org', 'zed@x.org', 'bo@x.org']);
  assert.equal(suggestPeople({ people }, 'y.org').length, 10);
  assert.equal(suggestPeople({ people }, 'y.org', 3).length, 3);
});

/** en-GB's short name for a month (0-based): "Sept" or "Sep" depending on ICU. */
function fmtMonthShort(m: number): string {
  return new Intl.DateTimeFormat('en-GB', { month: 'short', timeZone: 'UTC' }).format(Date.UTC(2026, m, 1));
}

// ---------------------------------------------------------------------------
// Commits (docs/commits.md): the author-side metric.

test('namedOrgs also names orgs with enough of the commits, by the larger share', () => {
  const withCommits: Summary = {
    ...SUMMARY,
    rows: SUMMARY.rows.map((r) => ({ ...r, commits: r.org === 'google.com' ? 80 : r.org === 'igalia.com' ? 2 : 0 })),
  };
  withCommits.rows.push({ ...row('solo.dev', 0, 0), commits: 18 });
  // solo.dev reviews nothing but wrote 18% of the commits.
  assert.deepEqual(namedOrgs(withCommits, '2026-W44'), ['google.com', 'solo.dev', 'microsoft.com', 'igalia.com', 'gmail.com']);
  // Without commits in the summary, review comments alone decide.
  assert.deepEqual(namedOrgs(SUMMARY, '2026-W44'), ['google.com', 'microsoft.com', 'igalia.com', 'gmail.com']);
});

test('orgTotals sums commits and their shares', () => {
  const s: Summary = { ...SUMMARY, rows: SUMMARY.rows.map((r, i) => ({ ...r, commits: [6, 3, 1, 0, 0][i] })) };
  const t = orgTotals(s, ['2026-W44']);
  assert.deepEqual(t.filter((r) => r.commits).map((r) => [r.org, r.commits, r.share_commits]),
    [['google.com', 6, 0.6], ['microsoft.com', 3, 0.3], ['igalia.com', 1, 0.1]]);
});

test('ratioNumerator and perReviewMetric for commits', () => {
  assert.equal(ratioNumerator('comments'), 'comments');
  assert.equal(ratioNumerator('commits'), 'addressed');
  assert.equal(ratioNumerator('commits', false), 'comments');
  assert.equal(perReviewMetric('commits'), 'comments');
});

test('ratioSeries divides week by week; gaps for no commits or no review data', () => {
  const weeks = ['2026-W42', '2026-W43', '2026-W44'];
  const num = [{ org: 'a.com', values: [4, 6, 9] }, { org: 'b.com', values: [1, 1, 1] }, { org: OTHER, values: [2, 2, 2] }];
  const den = [{ org: 'a.com', values: [2, 0, 3] }, { org: OTHER, values: [1, 1, 4] }];
  assert.deepEqual(ratioSeries(num, den, weeks), [
    { org: 'a.com', values: [2, null, 3] },
    { org: OTHER, values: [2, 2, 0.5] },
  ]);
  // Unclassified weeks (no addressed data in the window) are gaps too.
  assert.deepEqual(ratioSeries(num, den, weeks, 1, new Set(['2026-W44']))[0].values, [null, null, 3]);
  assert.deepEqual(ratioSeries(num, den, weeks, 2, new Set(['2026-W42']))[0].values, [2, null, null]);
  assert.deepEqual([...ratioOrgs(num, den)], ['a.com']);
});

test('authorBoard reads like a reviewer board, commits in column 6', () => {
  const b = authorBoard({
    meta: { fold_into_other: ['gmail.com'] },
    orgs: ['x.com', 'gmail.com'],
    accounts: { 7: 'n7', 8: 'n8' },
    emails: { 7: 'n7@x.com' },
    weeks: { '2026-W44': [[7, 0, 5], [8, 1, 2]], '2026-W43': [[7, 0, 1]] },
  });
  assert.deepEqual(topReviewers(b, ['2026-W43', '2026-W44'], 'commits').map((r) => [r.name, r.org, r.value]),
    [['n7', 'x.com', 6], ['n8', 'gmail.com', 2]]);
  assert.deepEqual(topReviewers(b, '2026-W44', 'comments'), []);
  // A person's monthly chart adds their commits.
  const r = board({ '2026-W44': [[1, 0, 3, 1, 10, 1]] });
  const s = reviewerSeries(r, 7, ['2026-W43', '2026-W44'], new Set(), b);
  assert.deepEqual([s.name, s.email, s.org, s.comments, s.commits], ['n7', 'n7@x.com', 'x.com', [0, 0], [1, 5]]);
  assert.equal(reviewerSeries(r, 1, ['2026-W44'], new Set()).commits, null);
});

test('commitBoard shares the directory tree; null for another area file', () => {
  const areas: DirBoard = { ...DIRS, meta: { ...DIRS.meta, generated_at: 'T' } };
  const file = { meta: { areas_generated_at: 'T' }, weeks: { '2026-W44': [[3, 0, 2], [5, 1, 1], [7, 1, 4]] as [number, number, number][] } };
  const b = commitBoard(areas, file)!;
  assert.equal(b.nodes, areas.nodes);
  const t = dirTotals(b, W, DN, 'commits');
  // chrome/ holds ui/ (2) and webnn/ (4); content/ holds browser/ (1).
  assert.deepEqual([t.total[1], t.total[4], t.inc[1]], [6, 1, 4]);
  assert.equal(dirTotals(areas, W, DN, 'commits').total[1], 0);
  assert.equal(commitBoard(areas, { ...file, meta: { areas_generated_at: 'other' } }), null);
});

test('gerritDirUrl for authors searches their merged CLs; gerritAuthoredUrl a person\'s', () => {
  const range = { from: '2026-W41', to: '2026-W44' };
  const link = gerritDirUrl('base/', new Map([[11, 2], [22, 9]]), range, NOW, true)!;
  assert.equal(link.url, `${Q}dir:base+after:2026-10-04+status:merged+(owner:22+OR+owner:11)`);
  assert.equal(link.authors, true);
  assert.equal(gerritDirUrl('base/', new Map([[5, 1]]), range, NOW, true)!.url,
    `${Q}dir:base+after:2026-10-04+status:merged+owner:5`);
  assert.equal(gerritAuthoredUrl('a@x.com', range, NOW), `${Q}owner:a@x.com+status:merged+after:2026-10-04`);
  assert.equal(gerritAuthoredUrl(null, range, NOW), null);
});

// SECURITY.md, "Script injection on the public site": names, emails, paths
// and comment text from Gerrit are attacker-controlled, so no script may
// turn a string into markup or code.
test('no script parses strings as HTML or code', async () => {
  const { readdirSync } = await import('node:fs');
  const dir = fileURLToPath(new URL('../src/', import.meta.url));
  const sinks =
    /\.(innerHTML|outerHTML|srcdoc)\b|insertAdjacentHTML|document\.write|createContextualFragment|DOMParser|setHTMLUnsafe|parseHTMLUnsafe|\beval\s*\(|new\s+Function\b|javascript:/;
  const files = readdirSync(dir).filter((f) => f.endsWith('.ts'));
  assert.ok(files.length > 5);
  for (const f of files) {
    readFileSync(dir + f, 'utf8').split('\n').forEach((line, i) => {
      assert.doesNotMatch(line, sinks, `${f}:${i + 1}`);
    });
  }
  // Nor do the pages carry inline handlers or scripts, which the CSP blocks.
  const web = fileURLToPath(new URL('../', import.meta.url));
  for (const f of readdirSync(web).filter((f) => f.endsWith('.html'))) {
    const html = readFileSync(web + f, 'utf8');
    assert.doesNotMatch(html, /<[^>]*\son[a-z]+\s*=/i, `${f}: inline event handler`);
    assert.doesNotMatch(html, /<script(?![^>]*\ssrc=)[^>]*>/i, `${f}: inline script`);
    assert.doesNotMatch(html, /\sstyle\s*=|<style/i, `${f}: inline style`);
  }
});

test('Gerrit links stay on Gerrit whatever the data says', () => {
  const evil = 'javascript:alert(1)//"><img src=x onerror=alert(1)>';
  for (const url of [
    gerritReviewsUrl(evil)!,
    gerritAuthoredUrl(evil)!,
    gerritCommentUrl(1, evil),
    gerritCommentUrl(1, '../../../../evil'),
    gerritDirUrl(`${evil}/`, new Map([[1, 1]]))!.url,
  ]) {
    assert.ok(url.startsWith('https://chromium-review.googlesource.com/'), url);
    assert.doesNotMatch(url, /["<> ]/, url);
    assert.equal(new URL(url).origin, 'https://chromium-review.googlesource.com');
  }
  assert.doesNotMatch(gerritCommentUrl(1, '../../evil'), /\/\.\.\//);
});

test('orgFilesPerCommitSpreads: files over commits per author, authors with too few commits left out', () => {
  const b = authorBoard({
    meta: { fold_into_other: ['gmail.com'] },
    orgs: ['x.com', 'gmail.com'],
    accounts: { 7: 'n7', 8: 'n8', 9: 'n9' },
    weeks: { '2026-W43': [[7, 0, 2, 10], [9, 0, 1, 1]], '2026-W44': [[7, 0, 2, 2], [8, 1, 4, 40]] },
  });
  const s = orgFilesPerCommitSpreads(b, ['2026-W43', '2026-W44'], ['x.com'], 3);
  // n7: 12 files / 4 commits; n8 (gmail.com) is Other; n9 has one commit.
  assert.deepEqual(s.map((r) => [r.org, r.reviewers.map((x) => [x.id, x.value]), r.pooled]),
    [['x.com', [[7, 3]], 3], [OTHER, [[8, 10]], 10]]);
});

test('monthlyTotals: calendar months by Thursday, each week\'s month', () => {
  // 2026-W40 starts on Sep 28, but its Thursday is Oct 1, so it is October's.
  const weeks = ['2026-W39', '2026-W40', '2026-W41', '2026-W44', '2026-W45', '2026-W49'];
  const m = monthlyTotals(weeks, [1, 2, 3, 4, 5, 6]);
  assert.deepEqual(m.months.map((x) => [x.label, x.total]),
    [['Sep 2026', 1], ['Oct 2026', 9], ['Nov 2026', 5], ['Dec 2026', 6]]);
  assert.deepEqual(m.monthOf, [0, 1, 1, 1, 2, 3]);
  assert.deepEqual(m.months.map((x) => x.at), [0, 2, 4, 5]);
  assert.deepEqual(m.months.map((x) => x.week), ['2026-W39', '2026-W40', '2026-W45', '2026-W49']);
  // September starts before the weeks given, and December runs on past them.
  assert.deepEqual(m.months.map((x) => x.partial), [true, false, false, true]);
});

test('findPeople: nothing for a blank query; prefix, then word, then substring; busiest first; at most 10', () => {
  const r: ReviewerBoard = {
    meta: { fold_into_other: [] },
    orgs: ['x.com'],
    accounts: { 1: 'Ann Lee', 2: 'Lee Ann', 3: 'Joanne Park', 4: 'Bob Stone' },
    emails: { 1: 'ann@x.com', 2: 'lee@x.com', 3: 'jo@x.com', 4: 'annex@x.com' },
    weeks: { '2026-W44': [[1, 0, 1, 0, 0], [2, 0, 5, 0, 0], [3, 0, 9, 0, 0], [4, 0, 2, 0, 0]] },
  };
  assert.deepEqual(findPeople(r, undefined, '  ', ['2026-W44']), []);
  // "ann": Ann Lee and Bob Stone (annex@) start with it (Bob busier), Lee Ann has
  // a word starting with it, Joanne only contains it.
  assert.deepEqual(findPeople(r, undefined, 'ANN', ['2026-W44']).map((m) => m.name),
    ['Bob Stone', 'Ann Lee', 'Lee Ann', 'Joanne Park']);
  assert.deepEqual(findPeople(r, undefined, 'zz', ['2026-W44']), []);
  // Commit authors count once loaded, their commits as activity.
  const a = authorBoard({ meta: { fold_into_other: [] }, orgs: ['x.com'], accounts: { 9: 'Annie Dev' },
    emails: { 9: 'annie@x.com' }, weeks: { '2026-W44': [[9, 0, 50]] } });
  assert.deepEqual(findPeople(r, a, 'ann', ['2026-W44']).map((m) => [m.name, m.activity])[0], ['Annie Dev', 50]);
  // At most 10.
  const many: ReviewerBoard = { ...r, accounts: Object.fromEntries(Array.from({ length: 30 }, (_, i) => [i + 10, `Sam ${i}`])) };
  assert.equal(findPeople(many, undefined, 'sam', ['2026-W44']).length, 10);
});

test('linearStep: a round step giving at most 10 ticks from 0', () => {
  assert.equal(linearStep(1), 0.1);
  assert.equal(linearStep(0.09), 0.01);
  assert.equal(linearStep(0.12), 0.02);
  assert.equal(linearStep(0.2), 0.02);
  assert.equal(linearStep(0.4), 0.05);
  assert.equal(linearStep(0.03), 0.005);
});

test('fmtHoursBin names histogram bins in the low edge\'s unit; fmtQuarterMonth names a quarter\'s months', async () => {
  const { fmtHoursBin, fmtQuarterMonth } = await import('../src/format.ts');
  const edges = [0, 1, 2, 4, 8, 16, 24, 48, 96, 168, 336];
  assert.deepEqual(edges.map((lo, i) => fmtHoursBin(lo, edges[i + 1] ?? null)),
    ['< 1 h', '1–2 h', '2–4 h', '4–8 h', '8–16 h', '16–24 h', '1–2 d', '2–4 d', '4–7 d', '1–2 wk', '2 wk+']);
  assert.equal(fmtQuarterMonth('2025Q4'), 'Oct 2025');
  assert.equal(fmtQuarterMonth('2026Q3', true), 'Sept 2026');
});

// ---- Review Feedback (src/feedback.ts)

test('review feedback: addresses normalise and hash as scripts/review_feedback.py key() does', async () => {
  const { normalizeEmail, personKey, looksLikeEmail } = await import('../src/feedback.ts');
  assert.equal(normalizeEmail('  Foo.Bar@Chromium.org '), 'foo.bar@google.com');
  assert.equal(normalizeEmail('user@chromium.org@0039d316-1c4b-4281-b951-d872f2087c98'), 'user@google.com');
  assert.equal(normalizeEmail('a@Microsoft.com'), 'a@microsoft.com');
  // Values printed by the Python script's key().
  assert.equal(await personKey('Foo.Bar@Chromium.org'), 'fb3b9e32f56a8f89c2ea38de91844541');
  assert.equal(await personKey('foo.bar@google.com'), 'fb3b9e32f56a8f89c2ea38de91844541');
  assert.equal(await personKey('  someone@microsoft.com '), '5005b7c30306573a80bf031dd778435d');
  assert.equal(await personKey('user@chromium.org@0039d316-1c4b-4281-b951-d872f2087c98'), 'aa541a61ff13d7a7b67c4ed4ed491ce4');
  const { FIXTURE_EMAIL, FIXTURE_KEY, ALIAS_EMAIL, ALIAS_KEY } = await import('./feedback-fixture.ts');
  assert.equal(await personKey(FIXTURE_EMAIL), FIXTURE_KEY);
  assert.equal(await personKey(ALIAS_EMAIL), ALIAS_KEY);
  assert.ok(looksLikeEmail('a@b.org'));
  assert.ok(!looksLikeEmail('alice'));
  assert.ok(!looksLikeEmail('a@b'));
});

test('review feedback: percentiles and quantiles read off 21 quantiles', async () => {
  const { percentileOf, quantile } = await import('../src/feedback.ts');
  const q = Array.from({ length: 21 }, (_, i) => i / 10);       // 0 .. 2 evenly
  assert.equal(percentileOf(q, -1), 0);
  assert.equal(percentileOf(q, 5), 1);
  assert.ok(Math.abs(percentileOf(q, 1) - 0.5) < 1e-9);
  assert.ok(Math.abs(percentileOf(q, 1.05) - 0.525) < 1e-9);
  assert.equal(quantile(q, 0.5), 1);
  assert.ok(Math.abs(quantile(q, 0.25) - 0.5) < 1e-9);
  // A run of equal quantiles: the middle of the run.
  const flat = [0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 3];
  assert.equal(percentileOf(flat, 1), (5 + 15) / 2 / 20);
});

test('review feedback: half-year files merge, and every period gets the values the script computes', async () => {
  const F = await import('../src/feedback.ts');
  const { top, shards, peers, day } = await import('./feedback-fixture.ts');
  const person = F.buildPerson(top, top.halves.map((h) => shards[h]), peers);
  // Names re-indexed across files.
  assert.deepEqual(person.dirs, ['chrome/browser/ui/', 'content/browser/', 'third_party/blink/renderer/']);
  assert.deepEqual(person.cls.map((c) => c[7].map(([d]) => person.dirs[d])),
    [['chrome/browser/ui/'], ['content/browser/', 'chrome/browser/ui/'], ['third_party/blink/renderer/']]);
  assert.deepEqual(person.cls[2][8].map((t) => person.files[t[1]]), ['third_party/blink/renderer/core/a.cc', '/PATCHSET_LEVEL']);
  assert.deepEqual(Object.keys(person.periods).sort(), ['2025', '2025H2', '2026', '2026H1', '2026H2', 'all']);
  const all = person.periods.all;
  assert.deepEqual([all.cls, all.threads, all.addressed, all.ten, all.org, all.ok], [3, 5, 3, '2-5y', 'google.com', false]);
  // 5 threads over 3 CLs, over 2.5 + 3 + 1.5 expected; 3 addressed over 1.4 + 2 + 0.9.
  assert.deepEqual([all.v.tn, all.v.td, all.v.an, all.v.ad], [1.667, 0.714, 1, 0.698]);
  // Against the band rates: 2.5 × 2.1 + 0.75 × 3 × 1.2 + 0.25 × 3 × 1.6 + 1.5 × 0.7 = 10.2.
  assert.equal(all.x.td, 0.49);
  assert.equal(person.periods['2026H1'].v.td, 0.333);
  assert.equal(person.periods['2026'].cls, 2);
  // Six CLs with three expected threads count among peers.
  const six = F.buildPerson(top, [{ ...shards['2026H1'], cls: Array(6).fill(shards['2026H1'].cls[0]) }], peers);
  assert.equal(six.periods.all.ok, true);
  assert.deepEqual(['<1y', '1-2y', '2-5y', '5-10y', '10y+'], [0.5, 1.5, 4.9, 5, 12].map(F.tenureBand));

  assert.ok(F.inPeriod(day('2026-03-11'), '2026H1'));
  assert.ok(!F.inPeriod(day('2026-07-01'), '2026H1'));
  assert.ok(F.inPeriod(day('2026-07-01'), '2026'));
  assert.ok(F.inPeriod(day('2020-01-01'), 'all'));
  assert.equal(F.isoDay(day('2026-03-11')), '2026-03-11');
  assert.deepEqual([0, 1, 4, 5, 19, 20, 99, 100].map(F.xpBand), [0, 1, 1, 2, 2, 3, 3, 4]);
  // Experience bands: CL 1 (no earlier commits, 2 threads in its one directory), CL 2 (7 earlier
  // in content/: 0.75 of it and its thread; 1 earlier in chrome/: 0.25), CL 3 (150 earlier: 2 threads).
  const xp = F.xpBreakdown(person, 'all', 'td');
  assert.deepEqual(xp.map((b) => b.cls), [1, 0.25, 0.75, 0, 1]);
  assert.deepEqual(xp.map((b) => b.obs), [2, 0, 1, 0, 2]);
  assert.ok(Math.abs(xp[2].den - 0.75 * 3) < 1e-9);
  assert.deepEqual(F.xpBreakdown(person, 'all', 'ad').map((b) => b.obs), [1, 0, 1, 0, 1]);
  assert.deepEqual(F.xpBreakdown(person, 'all', 'tn').map((b) => b.den), [1, 0.25, 0.75, 0, 1]);
  const dirs = F.dirTable(person, 'all', 't');
  assert.deepEqual(dirs.map((d) => [d.dir, d.cls, d.threads, d.prior]),
    [['chrome/browser/ui/', 2, 2, 1], ['third_party/blink/renderer/', 1, 2, 150], ['content/browser/', 1, 1, 7]]);
  assert.ok(Math.abs(dirs[0].expected - (2.5 + 0.25 * 3)) < 1e-9);
  // Comments: newest first; addressed only; one directory; praise only.
  const rows = F.threadRows(person, 'all', 't', null, false);
  assert.deepEqual(rows.map((r) => `${r.cl}/${r.uuid}`),
    ['1000003/cccc_0003', '1000003/', '1000002/bbbb_0002', '1000001/aaaa_0002', '1000001/']);
  assert.equal(rows[0].file, '/PATCHSET_LEVEL');
  assert.equal(F.isoDay(rows[1].day), '2026-09-01');
  assert.deepEqual(F.threadRows(person, 'all', 'a', null, false).map((r) => r.cl), [1000003, 1000002, 1000001]);
  assert.deepEqual(F.threadRows(person, '2026H1', 't', null, false).map((r) => r.uuid), ['bbbb_0002']);
  assert.deepEqual(F.threadRows(person, 'all', 't', 2, false).map((r) => r.uuid), ['cccc_0003', '']);
  assert.deepEqual(F.threadRows(person, 'all', 't', null, true).map((r) => r.uuid), ['cccc_0003', 'bbbb_0002']);
  // Links are encoded and always go to Gerrit; without a comment id, to the change.
  assert.equal(F.commentUrl(5, 'a/b'), 'https://chromium-review.googlesource.com/c/chromium/src/+/5/comment/a%2Fb/');
  assert.equal(F.commentUrl(5, ''), 'https://chromium-review.googlesource.com/c/chromium/src/+/5');
  // Peer groups: tenure needs a band; the experience group reads the adjusted value.
  assert.equal(F.groupKey('ten', all), 'ten:2-5y');
  assert.equal(F.groupKey('org:igalia', all), 'org:igalia');
  assert.equal(F.valueFor('dirxp', all, 'td'), 0.49);
  assert.equal(F.valueFor('all', all, 'ad'), 0.698);
  assert.deepEqual(F.halves(['all', '2026H2', '2025', '2023H2']), ['2023H2', '2026H2']);
});
