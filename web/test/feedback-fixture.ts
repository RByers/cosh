// A made-up person and peer file for the Review Feedback tests, shaped like
// scripts/review_feedback.py's output: a top file and one file per
// half-year. The real data is per person and isn't committed, so the browser
// tests serve these instead.
import type { Metric, Peers, Shard, Top } from '../src/feedback.ts';

/** personKey('Test.Person@chromium.org'), as the Python script computes it. */
export const FIXTURE_EMAIL = 'Test.Person@chromium.org';
export const FIXTURE_KEY = '2da4ec431edc6e08b535984c029f9a9d';
/** Another address of the same person, whose file points at FIXTURE_KEY. */
export const ALIAS_EMAIL = 'tp@example.com';
export const ALIAS_KEY = 'bbf27d6626ae4d5f589d68403ed10bab';

const METRICS: Metric[] = ['tn', 'ts', 'td', 'an', 'as', 'ad'];
const each = <T>(f: (m: Metric) => T) => Object.fromEntries(METRICS.map((m) => [m, f(m)])) as Record<Metric, T>;
const q = (lo: number, hi: number) => Array.from({ length: 21 }, (_, i) => Math.round((lo + ((hi - lo) * i) / 20) * 1000) / 1000);
export const day = (s: string) => Math.floor(Date.parse(`${s}T00:00:00Z`) / 86_400_000);

export const top: Top = {
  v: 3,
  first: '2022-03',
  first_day: day('2022-03-01'),
  halves: ['2025H2', '2026H1', '2026H2'],
  tone: { received: 40, praise: 2, share: 0.05, ten: '2-5y', chg: '50-199' },
  praise: [[1000003, 'cccc_0003', day('2026-09-02'), 'Really nice cleanup, thanks!'],
    [1000002, 'bbbb_0002', day('2026-03-10'), 'Great test coverage <img src=x onerror=alert(1)>']],
};

/** Three changes, one per half-year. Each file lists its own names, in its own order. */
export const shards: Record<string, Shard> = {
  // A thread without an excerpt has no comment id.
  '2025H2': { dirs: ['chrome/browser/ui/'], files: ['chrome/browser/ui/view.cc', '/PATCHSET_LEVEL'], orgs: ['google.com'],
    cls: [[1000001, day('2025-10-01'), 40, 2, 2.5, 1.2, 1.4, [[0, 1, 0]],
      [['', 0, -1, 1, 0], ['aaaa_0002', 1, 0, 0, 0, 'Please add a test.']], 0, 30]] },
  '2026H1': { dirs: ['content/browser/', 'chrome/browser/ui/'], files: ['content/browser/frame.cc'], orgs: ['google.com'],
    cls: [[1000002, day('2026-03-11'), 120, 3, 3, 2, 2, [[0, 0.75, 7], [1, 0.25, 1]],
      [['bbbb_0002', 0, -1, 1, 0, 'Great test coverage <img src=x onerror=alert(1)>']], 0, 80]] },
  '2026H2': { dirs: ['third_party/blink/renderer/'], files: ['third_party/blink/renderer/core/a.cc', '/PATCHSET_LEVEL'],
    orgs: ['google.com'],
    cls: [[1000003, day('2026-09-03'), 10, 1, 1.5, 0.6, 0.9, [[0, 1, 150]],
      [['', 0, -2, 1, 0], ['cccc_0003', 1, -1, null, 0, 'Really nice cleanup, thanks!']], 0, 260]] },
};

const dist = (lo: number, hi: number) => each(() => ({ n: 120, q: q(lo, hi) }));
// Keys: '<tenure by>:<band>:<org>', or 'dir:<org>'. Too few authors outside
// Google of the person's years for 'td' to have percentiles.
const groups = () => ({
  'time:2-5y:all': dist(0.4, 3), 'time:2-5y:google': dist(0.4, 2.9),
  'time:2-5y:nongoogle': { ...dist(0.5, 3), td: { n: 4, q: null } }, 'time:5-10y:all': dist(0.3, 2),
  'changes:50-199:all': dist(0.5, 2.8), 'changes:50-199:google': dist(0.5, 2.6), 'changes:50-199:nongoogle': dist(0.6, 3),
  'dir:all': dist(0.2, 2.2), 'dir:google': dist(0.2, 2), 'dir:nongoogle': dist(0.3, 2.4),
});
const bands = () => each(() => [2.1, 1.6, 1.2, 0.9, 0.7].map((pooled) => ({ pooled, rel: pooled, n: 50, q: q(pooled / 2, pooled * 2) })));
const periods = ['all', '2023H2', '2024H1', '2024H2', '2025H1', '2025H2', '2026H1', '2026H2'];

export const peers: Peers = {
  generated: '2026-11-11',
  start: day('2023-07-01'),
  end: day('2026-11-01'),
  addr_start: day('2023-07-01'),
  periods,
  metrics: METRICS,
  tenure: ['<1y', '1-2y', '2-5y', '5-10y', '10y+'],
  changes: ['<50', '50-199', '200-499', '500-999', '1000+'],
  min_peers: 10,
  xp: ['0', '1-4', '5-19', '20-99', '100+'],
  min_cls: 6,
  min_exp: 3,
  min_received: 20,
  tone_weeks: ['2025-W45', '2026-W44'],
  dist: Object.fromEntries(periods.map((p) => [p, groups()])),
  // Every group's counts: 0..20 evenly, so 3 changes sit at 15% and 5 threads at 25%.
  counts: Object.fromEntries(periods.map((p) => [p, Object.fromEntries(Object.keys(groups()).map((g) => [g,
    { cls: { n: 120, q: q(0, 20) }, threads: { n: 120, q: q(0, 20) }, acls: { n: 120, q: q(0, 20) },
      addressed: { n: 120, q: q(0, 20) } }]))])),
  bands: Object.fromEntries(periods.map((p) => [p, bands()])),
  tone: { all: { n: 900, q: q(0, 0.1) }, 'time:2-5y': { n: 200, q: q(0, 0.08) }, 'changes:50-199': { n: 150, q: q(0, 0.06) } },
  cohort_step: 0.5,
  cohort_from: 2018,
  min_cohort: 20,
  // Two first-commit years that start at tenure 0 for everyone; 2016 starts later, so it isn't drawn.
  // Outside Google only 2024 has three points.
  cohorts: {
    all: each(() => ({ '2016': [[4, 0.9, 80], [4.5, 0.85, 90], [5, 0.8, 90]],
      '2019': [[0, 1.9, 300], [0.5, 1.5, 200], [1, 1.3, 190]], '2024': [[0, 2.1, 170], [0.5, 1.7, 100], [1, 1.2, 90]] })),
    nongoogle: each(() => ({ '2022': [[0, 2.2, 30]], '2024': [[0, 2, 20], [0.5, 1.6, 20], [1, 1.1, 20]] })),
  },
  change_edges: [-40, -30, -20, -10, 0, 10, 20, 30, 40, 50, 60, 70, 80],
  change: {
    all: each(() => ({ n: 5300, people: 1900, median: 16.2, counts: [400, 200, 300, 450, 700, 800, 750, 600, 450, 300, 200, 150] })),
    nongoogle: each(() => ({ n: 3, people: 2, median: -5, counts: [0, 0, 0, 1, 1, 1, 0, 0, 0, 0, 0, 0] })),
  },
  min_year_cls: 12,
};
