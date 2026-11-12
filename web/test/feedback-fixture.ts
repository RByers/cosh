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
  v: 2,
  first: '2022-03',
  first_day: day('2022-03-01'),
  halves: ['2025H2', '2026H1', '2026H2'],
  tone: { received: 40, praise: 2, share: 0.05, ten: '2-5y' },
  praise: [[1000003, 'cccc_0003', day('2026-09-02'), 'Really nice cleanup, thanks!'],
    [1000002, 'bbbb_0002', day('2026-03-10'), 'Great test coverage <img src=x onerror=alert(1)>']],
};

/** Three changes, one per half-year. Each file lists its own names, in its own order. */
export const shards: Record<string, Shard> = {
  // A thread without an excerpt has no comment id.
  '2025H2': { dirs: ['chrome/browser/ui/'], files: ['chrome/browser/ui/view.cc', '/PATCHSET_LEVEL'], orgs: ['google.com'],
    cls: [[1000001, day('2025-10-01'), 40, 2, 2.5, 1.2, 1.4, [[0, 1, 0]],
      [['', 0, -1, 1, 0], ['aaaa_0002', 1, 0, 0, 0, 'Please add a test.']], 0]] },
  '2026H1': { dirs: ['content/browser/', 'chrome/browser/ui/'], files: ['content/browser/frame.cc'], orgs: ['google.com'],
    cls: [[1000002, day('2026-03-11'), 120, 3, 3, 2, 2, [[0, 0.75, 7], [1, 0.25, 1]],
      [['bbbb_0002', 0, -1, 1, 0, 'Great test coverage <img src=x onerror=alert(1)>']], 0]] },
  '2026H2': { dirs: ['third_party/blink/renderer/'], files: ['third_party/blink/renderer/core/a.cc', '/PATCHSET_LEVEL'],
    orgs: ['google.com'],
    cls: [[1000003, day('2026-09-03'), 10, 1, 1.5, 0.6, 0.9, [[0, 1, 150]],
      [['', 0, -2, 1, 0], ['cccc_0003', 1, -1, null, 0, 'Really nice cleanup, thanks!']], 0]] },
};

const dist = (lo: number, hi: number) => each(() => ({ n: 120, q: q(lo, hi) }));
const groups = () => ({
  all: dist(0.4, 3), dirxp: dist(0.2, 2.2), 'ten:2-5y': dist(0.5, 2.8), 'ten:5-10y': dist(0.3, 2),
  'org:google': dist(0.4, 2.9), 'org:microsoft': dist(0.6, 3.5), 'org:igalia': { ...dist(0.5, 3), td: { n: 0, q: null } },
  'org:nongoogle': dist(0.5, 3.2),
});
const bands = () => each(() => [2.1, 1.6, 1.2, 0.9, 0.7].map((pooled) => ({ pooled, rel: pooled, n: 50, q: q(pooled / 2, pooled * 2) })));
const periods = ['all', '2023', '2024', '2025', '2026', '2023H2', '2024H1', '2024H2', '2025H1', '2025H2', '2026H1', '2026H2'];

export const peers: Peers = {
  generated: '2026-11-11',
  periods,
  metrics: METRICS,
  tenure: ['<1y', '1-2y', '2-5y', '5-10y', '10y+'],
  xp: ['0', '1-4', '5-19', '20-99', '100+'],
  min_cls: 6,
  min_exp: 3,
  min_received: 20,
  tone_weeks: ['2025-W45', '2026-W44'],
  dist: Object.fromEntries(periods.map((p) => [p, groups()])),
  bands: Object.fromEntries(periods.map((p) => [p, bands()])),
  tone: { all: { n: 900, q: q(0, 0.1) }, 'ten:2-5y': { n: 200, q: q(0, 0.08) } },
};
