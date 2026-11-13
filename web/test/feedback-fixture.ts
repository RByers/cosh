// A made-up person and peer file for the Review Feedback tests, shaped like
// cosh/feedback.py's output: a top file and one file per
// half-year. The browser tests serve these instead of the committed data.
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
  v: 4,
  first: '2022-03',
  first_day: day('2022-03-01'),
  halves: ['2025H2', '2026H1', '2026H2'],
  tone: { received: 40, praise: 2, share: 0.05, ten: '2-5y', chg: '50-199' },
  praise: [[1000003, 'cccc_0003', day('2026-09-02'), 'Really nice cleanup, thanks!'],
    [1000002, 'bbbb_0002', day('2026-03-10'), 'Great test coverage <img src=x onerror=alert(1)>']],
};

/** Three changes, one per half-year. Each file lists its own names, in its own order. */
export const shards: Record<string, Shard> = {
  // A thread without an excerpt has no comment id. A thread's directory is its file's (or the first unit's).
  '2025H2': { dirs: ['chrome/browser/ui/'], files: ['chrome/browser/ui/view.cc', '/COMMIT_MSG'], orgs: ['google.com'],
    cls: [[1000001, day('2025-10-01'), 40, 2.5, 1.4, [[0, 1, 0, 38]],
      [['', 0, -1, 1], ['aaaa_0002', 1, 0, 0, 'Please add a test.']], 0, 30]] },
  '2026H1': { dirs: ['content/browser/', 'chrome/browser/ui/'], files: ['content/browser/frame.cc'], orgs: ['google.com'],
    cls: [[1000002, day('2026-03-11'), 120, 3, 2, [[0, 0.75, 7, 90], [1, 0.25, 1, 28]],
      [['bbbb_0002', 0, -1, 1, 'Great test coverage <img src=x onerror=alert(1)>']], 0, 80]] },
  // Wholly in one directory: [directory, earlier commits there].
  '2026H2': { dirs: ['third_party/blink/renderer/'], files: ['third_party/blink/renderer/core/a.cc', '/COMMIT_MSG'],
    orgs: ['google.com'],
    cls: [[1000003, day('2026-09-03'), 10, 1.5, 0.9, [[0, 150]],
      [['', 0, -2, 1], ['cccc_0003', 1, -1, null, 'Really nice cleanup, thanks!']], 0, 260]] },
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
  // The changes above are 40, 120 and 10 lines: size buckets 4, 5 and 2.
  size_norm: { t: [1, 1, 1, 1, 2, 3, 1, 1, 1, 1], a: [1, 1, 0.6, 1, 1.2, 2, 1, 1, 1, 1] },
  tenure: ['<1y', '1-2y', '2-5y', '5-10y', '10y+'],
  changes: ['<50', '50-199', '200-499', '500-999', '1000+'],
  min_peers: 10,
  xp: ['0', '1-4', '5-19', '20-99', '100+'],
  min_cls: 6,
  min_exp: 3,
  min_received: 20,
  tone_weeks: ['2025-W45', '2026-W44'],
  dist: Object.fromEntries(periods.map((p) => [p, groups()])),
  // The count tiles' peers in 2026H1, per org: 0..20 evenly (Google: 0..10), so the person's
  // one change there sits at 5% (10%), and none outside Google.
  count_half: '2026H1',
  counts_half: Object.fromEntries((['all', 'google', 'nongoogle'] as const).map((o) => {
    const d = { n: 120, q: q(0, o === 'google' ? 10 : 20) };
    return [o, { cls: d, threads: d, acls: d, addressed: d }];
  })),
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
  change_ratios: [0.3969, 0.5, 0.63, 0.7937, 1, 1.2599, 1.5874, 2, 2.5198],
  change: {
    all: each(() => ({ n: 5300, people: 1900, median: 16.2, counts: [350, 650, 950, 750, 950, 750, 380, 320, 150, 50] })),
    nongoogle: each(() => ({ n: 3, people: 2, median: -5, counts: [0, 0, 0, 0, 1, 1, 1, 0, 0, 0] })),
  },
  min_cohort_cls: 6,
  size_labels: ['<4', '4–7', '8–15', '16–31', '32–63', '64–127', '128–255', '256–511', '512–1,023', '1,024+'],
  // Unadjusted ("n") bars rise with size; adjusted ones are near flat. Directories come out of order,
  // and one has too few contributors.
  by_size: {
    all: each((m) => (m[1] === 'n' ? [0.09, 0.19, 0.31, 0.55, 1, 1.77, 3.08, 5.04, 6.25, 4.4] : [0.68, 0.79, 0.81, 0.86, 0.86, 0.83, 0.82, 0.82, 0.7, 0.56])
      .map((v, i): [number | null, number] => [i === 9 && m[0] === 'a' ? null : v, i === 9 && m[0] === 'a' ? 4 : 500])),
    google: each(() => Array.from({ length: 10 }, (): [number | null, number] => [0.8, 300])),
  },
  dir_names: ['chrome/browser/', 'third_party/blink/', 'ios/', 'tools/'],
  by_dir: {
    all: each((m) => (m[1] === 'n' ? [[2.24, 1360], [1.8, 576], [null, 6], [1.05, 887]] : [[0.93, 1360], [1.05, 576], [null, 6], [0.95, 887]]) as [number | null, number][]),
  },
  min_cell_cls: 10,
  // All against addressed: addressed starts higher and ends lower. Outside Google, addressed falls less.
  kind_labels: ['0–3 months', '3–6 months', '6–12 months', '1–2 years', '2–5 years', '5–10 years', '10+ years'],
  kinds: {
    all: { n: [], s: [], d: [[1.92, 2.03, 860], [1.75, 1.8, 400], [1.41, 1.46, 780], [1.21, 1.24, 1300],
      [0.9, 0.88, 3100], [0.67, 0.63, 2600], [0.55, 0.49, 1600]] },
    nongoogle: { n: [], s: [], d: [[1.4, 1.2, 140], [1.2, 1.1, 50], [1, 1, 90], [0.9, 0.9, 160], [0.8, 0.8, 300],
      [0.7, 0.75, 270], [0.6, 0.6, 60]] },
  },
  kind_share: { all: [0.84, 0.84, 0.83, 0.83, 0.8, 0.76, 0.74], nongoogle: [0.81, 0.82, 0.82, 0.84, 0.82, 0.82, 0.8] },
  // The same by changes landed before, the default tenure: bins of earlier changes, 2018 and 2023 start
  // in the first bin; outside Google only 2025.
  chg_labels: ['<10', '10–24', '25–49', '50–99', '100–199', '200–499', '500–999', '1,000+'],
  cohorts_chg: {
    all: each(() => ({ '2016': [[5, 0.8, 80], [6, 0.7, 90], [7, 0.6, 90]],
      '2018': [[0, 2.3, 300], [1, 1.8, 250], [2, 1.4, 240], [3, 1.1, 200]],
      '2023': [[0, 2.2, 150], [1, 1.7, 120], [2, 1.3, 90]] })),
    nongoogle: each(() => ({ '2025': [[0, 2.0, 25], [1, 1.5, 22], [2, 1.2, 20]] })),
  },
  doubling_from: 32,
  change_chg: {
    all: each(() => ({ n: 4100, people: 1500, median: 21.4, counts: [300, 600, 800, 700, 700, 500, 250, 180, 50, 20] })),
    nongoogle: each(() => ({ n: 4, people: 3, median: 7, counts: [0, 0, 0, 1, 2, 1, 0, 0, 0, 0] })),
  },
  kinds_chg: {
    all: { n: [], s: [], d: [[2.1, 2.4, 500], [1.8, 2, 700], [1.5, 1.6, 900], [1.2, 1.2, 1300], [1, 0.95, 1800],
      [0.8, 0.72, 2400], [0.65, 0.55, 1800], [0.5, 0.4, 1240]] },
    nongoogle: { n: [], s: [], d: [[1.5, 1.4, 100], [1.3, 1.2, 90], [1.1, 1, 100], [1, 0.95, 150], [0.9, 0.85, 200],
      [0.8, 0.78, 200], [0.7, 0.7, 150], [0.6, 0.6, 80]] },
  },
  kind_share_chg: { all: [0.86, 0.85, 0.84, 0.83, 0.81, 0.78, 0.75, 0.72], nongoogle: [0.8, 0.8, 0.8, 0.8, 0.8, 0.8, 0.8, 0.8] },
  tenure_cmp: {
    all: each(() => ({
      bands: {
        time: [[1.85, 90000], [1.26, 80000], [0.93, 200000], [0.71, 250000], [0.52, 300000]],
        changes: [[2, 100000], [1.13, 150000], [0.82, 200000], [0.63, 150000], [0.43, 300000]],
        dir: [[1.58, 300000], [1.4, 250000], [1.15, 200000], [0.85, 150000], [0.58, 100000]],
      },
      n: 5246, people: 1565, none: 16.2, time: 5.9, changes: 0.6, dir: 11.3,
    })),
    // Years overshoots least here, and changes landed overshoots (feedback grows once matched on it).
    nongoogle: each(() => ({
      bands: {
        time: [[1.33, 900], [1.08, 800], [0.9, 2000], [0.69, 2500], [0.47, 3000]],
        changes: [[1.45, 1000], [0.84, 1500], [0.62, 2000], [0.59, 1500], [0.37, 3000]],
        dir: [[1.46, 3000], [1.21, 2500], [1, 2000], [0.79, 1500], [0.44, 1000]],
      },
      n: 269, people: 109, none: 13.7, time: 0.4, changes: -4.9, dir: 7.6,
    })),
  },
};
