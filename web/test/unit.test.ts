// Unit tests for the pure data/scale modules (no browser).
import assert from 'node:assert/strict';
import { test } from 'vitest';
import {
  chartedOrgs,
  computeRatios,
  OTHER,
  parseCsv,
  parseOrgBrowsers,
  parseRadarWeekly,
  topBrowsers,
  topOrgCounts,
  topReviewers,
  type Summary,
} from '../src/data.ts';
import { pivotScale } from '../src/scale.ts';

const RADAR = `period,period_start,period_end,granularity,device,browser,is_chromium,kind,days,raw_share,chromium_share,chromium_share_all
2026-W44,2026-10-26,2026-11-01,week,all,Chrome,1,browser,7,0.4,0.5,0.4
2026-W44,2026-10-26,2026-11-01,week,all,ChromeMobile,1,browser,7,0.2,0.25,0.2
2026-W44,2026-10-26,2026-11-01,week,all,Edge,1,browser,7,0.1,0.2,0.1
2026-W44,2026-10-26,2026-11-01,week,all,Brave,1,browser,7,0.0001,0.0002,0.0001
2026-W44,2026-10-26,2026-11-01,week,all,SamsungInternet,1,browser,7,0.03,0.05,0.03
2026-W44,2026-10-26,2026-11-01,week,all,ChromeMobileWebview,1,webview,7,0.08,,0.09
2026-W45,2026-11-02,2026-11-08,week,all,Chrome,1,browser,2,0.4,0.9,0.4
2026-10,2026-10-01,2026-10-31,month,all,Chrome,1,browser,31,0.4,0.6,0.4
`;

const ORG_BROWSERS = `org_domain,browser,notes
google.com,Chrome,"Desktop Chrome, mostly."
google.com,ChromeMobile,""
microsoft.com,Edge,""
samsung.com,SamsungInternet,""
brave.com,Brave,"About 0%"
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

test('radar keeps only complete weeks with a chromium_share', () => {
  const radar = parseRadarWeekly(RADAR);
  assert.deepEqual([...radar.keys()], ['2026-W44']);
  assert.equal(radar.get('2026-W44')!.has('ChromeMobileWebview'), false);
  assert.equal(radar.get('2026-W44')!.get('Edge'), 0.2);
});

test('computeRatios divides contribution share by summed browser share', () => {
  const radar = parseRadarWeekly(RADAR);
  const ratios = computeRatios(SUMMARY, radar, parseOrgBrowsers(ORG_BROWSERS), 'comments');
  const by = Object.fromEntries(ratios.map((p) => [p.org, p]));
  assert.ok(Math.abs(by['google.com'].ratio! - 0.9 / 0.75) < 1e-12);
  assert.ok(Math.abs(by['microsoft.com'].ratio! - 0.25) < 1e-12);
  // Absent from the summary: contribution 0, ratio 0.
  assert.equal(by['samsung.com'].ratio, 0);
  // Usage share below the threshold: no ratio.
  assert.equal(by['brave.com'].ratio, null);
});

test('chartedOrgs skips orgs whose browsers never reach the threshold', () => {
  const radar = parseRadarWeekly(RADAR);
  assert.deepEqual(chartedOrgs(radar, parseOrgBrowsers(ORG_BROWSERS)), ['google.com', 'microsoft.com', 'samsung.com']);
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

test('topReviewers ranks one week by the chosen metric and drops zeros', () => {
  const r = (account_id: number, comments: number, cls: number, chars: number) => ({
    account_id, name: `n${account_id}`, org: 'x.com', comments, cls, chars,
  });
  const board = { meta: { top_n: 50 }, weeks: { '2026-W44': [r(1, 9, 1, 50), r(2, 0, 4, 0), r(3, 9, 2, 80)] } };
  assert.deepEqual(topReviewers(board, '2026-W44', 'comments').map((x) => [x.name, x.value]), [['n1', 9], ['n3', 9]]);
  assert.deepEqual(topReviewers(board, '2026-W44', 'cls', 2).map((x) => x.name), ['n2', 'n3']);
  assert.deepEqual(topReviewers(board, '2026-W44', 'chars')[0], { name: 'n3', org: 'x.com', value: 80 });
  assert.deepEqual(topReviewers(board, '2026-W01', 'comments'), []);
  // Input order is not mutated.
  assert.deepEqual(board.weeks['2026-W44'].map((x) => x.account_id), [1, 2, 3]);
});

test('topBrowsers ranks by peak share', () => {
  assert.deepEqual(topBrowsers(parseRadarWeekly(RADAR), 2), ['Chrome', 'ChromeMobile']);
});

test('pivotScale puts 1.0 in the middle and keeps both halves linear', () => {
  const s = pivotScale(1.24);
  assert.equal(s.toAxis(0), 0);
  assert.equal(s.toAxis(0.5), 0.5);
  assert.equal(s.toAxis(1), 1);
  assert.equal(s.toAxis(s.upper), 2);
  assert.ok(s.upper >= 1.24 * 1.05);
  assert.deepEqual(s.ticks.slice(0, 5), [0, 0.25, 0.5, 0.75, 1]);
  for (const r of [0, 0.3, 1, 1.2, s.upper]) assert.ok(Math.abs(s.fromAxis(s.toAxis(r)) - r) < 1e-12);
});

test('pivotScale picks a nice step for large maxima', () => {
  const s = pivotScale(7.3);
  assert.equal(s.upper, 9);
  assert.equal(s.upperStep, 2);
  assert.ok(s.ticks.length <= 9);
  // Ratios at or below 1 never get a scale smaller than 1.25.
  assert.equal(pivotScale(0.4).upper, 1.25);
  assert.equal(pivotScale(0).upper, 1.25);
});
