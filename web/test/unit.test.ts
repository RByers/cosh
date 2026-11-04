// Unit tests for the pure data/scale modules (no browser).
import assert from 'node:assert/strict';
import { test } from 'vitest';
import {
  addWeeks,
  areaRows,
  OTHER_INCLUDED,
  topAreaOrgs,
  type AreaBoard,
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
  niceTicks,
  topReviewers,
  trimRanked,
  type ReviewerBoard,
  type ReviewerRow,
  type Summary,
} from '../src/data.ts';
import { formatRatio } from '../src/scale.ts';

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
  reviewers: 10,
  comments,
  ai_comments: 0,
  post_merge_comments: 0,
});

const SUMMARY: Summary = {
  meta: { weeks: ['2026-W44'] },
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
  const ratios = computeRatios(SUMMARY, radar, parseOrgBrowsers(ORG_BROWSERS));
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
  const top = topOrgCounts(SUMMARY, '2026-W44', 2);
  assert.deepEqual(top, [
    { org: 'google.com', value: 900 },
    { org: 'microsoft.com', value: 50 },
    { org: OTHER, value: 50 },
  ]);
});

// orgs: 0 = x.com, 1 = y.com, 2 = gmail.com (folded into Other in org totals).
const board = (weeks: Record<string, ReviewerRow[]>): ReviewerBoard => ({
  meta: { fold_into_other: ['gmail.com'] },
  orgs: ['x.com', 'y.com', 'gmail.com'],
  accounts: { 1: 'n1', 2: 'n2', 3: 'n3' },
  emails: { 1: 'n1@x.com', 3: 'n3@x.com' },
  weeks,
});

test('topReviewers ranks one week by comments and drops zeros', () => {
  const b = board({ '2026-W44': [[1, 0, 9], [2, 0, 0], [3, 0, 12]] });
  assert.deepEqual(topReviewers(b, '2026-W44').map((x) => [x.name, x.value]), [['n3', 12], ['n1', 9]]);
  assert.deepEqual(topReviewers(b, '2026-W44', 1)[0], { name: 'n3', email: 'n3@x.com', org: 'x.com', value: 12 });
  // No email listed (or a file from before emails existed): null.
  assert.equal(topReviewers({ ...b, emails: undefined }, '2026-W44')[0].email, null);
  assert.deepEqual(topReviewers(b, '2026-W01'), []);
  // Input order is not mutated.
  assert.deepEqual(b.weeks['2026-W44'].map((x) => x[0]), [1, 2, 3]);
});

test('topReviewers totals a range exactly; org is where most of their comments were', () => {
  const b = board({
    '2026-W43': [[1, 1, 5], [2, 0, 9]],
    '2026-W44': [[1, 0, 4], [1, 1, 3]],
  });
  assert.deepEqual(topReviewers(b, ['2026-W44', '2026-W43']), [
    { name: 'n1', email: 'n1@x.com', org: 'y.com', value: 12 },
    { name: 'n2', email: null, org: 'x.com', value: 9 },
  ]);
  assert.deepEqual(topReviewers(b, []), []);
});

test('distinctReviewers counts people once over a range, per folded org', () => {
  const b = board({
    '2026-W43': [[1, 0, 5], [2, 2, 1]],
    '2026-W44': [[1, 0, 6], [1, 1, 1], [3, 2, 1]],
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
    meta: { weeks: ['2026-W43', '2026-W44'] },
    rows: [
      ...SUMMARY.rows,
      { ...row('google.com', 0.5, 100), iso_week: '2026-W43', reviewers: 30 },
      { ...row('microsoft.com', 0.5, 100), iso_week: '2026-W43' },
    ],
  };
  const t = Object.fromEntries(orgTotals(two, ['2026-W43', '2026-W44']).map((x) => [x.org, x]));
  assert.equal(t['google.com'].comments, 1000);
  assert.equal(t['microsoft.com'].comments, 150);
  assert.ok(Math.abs(t['google.com'].share - 1000 / 1200) < 1e-12);
  // Without distinct counts, weekly reviewer counts are summed; with them, they're used as given.
  assert.equal(t['google.com'].reviewers, 40);
  const exact = orgTotals(two, ['2026-W43', '2026-W44'], new Map([['google.com', 35]]));
  assert.equal(exact.find((x) => x.org === 'google.com')!.reviewers, 35);
  assert.equal(exact.find((x) => x.org === 'igalia.com')!.reviewers, 0);
  const one = Object.fromEntries(orgTotals(two, ['2026-W44']).map((x) => [x.org, x]));
  assert.ok(Math.abs(one['google.com'].share - 0.9) < 1e-12);
  assert.equal(topOrgCounts(two, ['2026-W43', '2026-W44'], 1)[0].value, 1000);
});

test('orgWeeklyCounts gives one series per top org, with the rest as Other', () => {
  const series = orgWeeklyCounts(SUMMARY, ['2026-W43', '2026-W44'], 2);
  assert.deepEqual(series.map((s) => s.org), ['google.com', 'microsoft.com', OTHER]);
  assert.deepEqual(series[0].values, [0, 900]);
  assert.deepEqual(series[2].values, [0, 50]);
});

test('orgWeeklyCounts can exclude an org entirely, letting the next one in', () => {
  const series = orgWeeklyCounts(SUMMARY, ['2026-W43', '2026-W44'], 2, 1, ['google.com']);
  assert.deepEqual(series.map((s) => s.org), ['microsoft.com', 'igalia.com', OTHER]);
  // Other is gmail.com + Other; google.com isn't folded into it.
  assert.deepEqual(series[2].values, [0, 20]);
});

test('orgWeeklyCounts smoothing averages weeks before the range, skipping weeks without data', () => {
  const three: Summary = {
    meta: { weeks: ['2026-W42', '2026-W43', '2026-W44'] },
    rows: [
      { ...SUMMARY.rows[0], iso_week: '2026-W42', comments: 300 },
      { ...SUMMARY.rows[0], iso_week: '2026-W43', comments: 600 },
      { ...SUMMARY.rows[0], iso_week: '2026-W44', comments: 900 },
    ],
  };
  // W44's 4-week window holds W41 (no data, skipped), W42, W43 and W44.
  const [google] = orgWeeklyCounts(three, ['2026-W44'], 7, 4);
  assert.equal(google.org, 'google.com');
  assert.deepEqual(google.values, [600]);
  assert.deepEqual(orgWeeklyCounts(three, ['2026-W43', '2026-W44'], 7, 1)[0].values, [600, 900]);
});

// areas: 0 = chrome/ (excluded), 1 = content/, 2 = (no file) (excluded), 3 = base/, 4 = ui/.
const AREAS: AreaBoard = {
  meta: { path_rules: [{ prefix: 'chrome/', included: false }], unplaced: '(no file)' },
  areas: [
    { area: 'chrome/', included: false },
    { area: 'content/', included: true },
    { area: '(no file)', included: false },
    { area: 'base/', included: true },
    { area: 'ui/', included: true },
  ],
  orgs: ['google.com', 'microsoft.com', 'opera.com', OTHER],
  weeks: {
    '2026-W43': [[0, 0, 50], [1, 1, 5]],
    '2026-W44': [[0, 0, 40], [0, 1, 2], [1, 0, 20], [1, 2, 3], [2, 0, 9], [3, 0, 4], [4, 3, 1]],
  },
};

test('areaRows totals each directory over the range, then combines the rest', () => {
  const orgs = topAreaOrgs(AREAS, ['2026-W43', '2026-W44'], 1);
  assert.deepEqual(orgs, ['google.com']);
  const rows = areaRows(AREAS, ['2026-W43', '2026-W44'], orgs, 3);
  assert.deepEqual(rows.map((r) => [r.area, r.included, r.comments, r.combined]), [
    ['chrome/', false, 92, undefined],
    ['content/', true, 28, undefined],
    ['(no file)', false, 9, undefined],
    [OTHER_INCLUDED, true, 5, 2],
  ]);
  // Orgs beyond the named ones count as Other.
  assert.deepEqual(Object.fromEntries(rows[1].byOrg), { 'google.com': 20, [OTHER]: 8 });
  assert.deepEqual(areaRows(AREAS, ['2026-W01'], orgs), []);
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

test('gerritReviewsUrl links to the reviewer query, keeping @ readable', () => {
  assert.equal(
    gerritReviewsUrl('jkeitel@google.com'),
    'https://chromium-review.googlesource.com/q/reviewedby:jkeitel@google.com',
  );
  assert.equal(gerritReviewsUrl('a+b@x.org'), 'https://chromium-review.googlesource.com/q/reviewedby:a%2Bb@x.org');
  assert.equal(gerritReviewsUrl(null), null);
});
