// A made-up person and peer file for the Review Feedback tests, shaped like
// scripts/review_feedback.py's output. The real data is per person and isn't
// committed, so the browser tests serve these instead.
import type { Metric, Peers, Person } from '../src/feedback.ts';

/** personKey('Test.Person@chromium.org'), as the Python script computes it. */
export const FIXTURE_EMAIL = 'Test.Person@chromium.org';
export const FIXTURE_KEY = '2da4ec431edc6e08b535984c029f9a9d';
/** Another address of the same person, whose file points at FIXTURE_KEY. */
export const ALIAS_EMAIL = 'tp@example.com';
export const ALIAS_KEY = 'bbf27d6626ae4d5f589d68403ed10bab';

const METRICS: Metric[] = ['tn', 'ts', 'td', 'an', 'as', 'ad'];
const each = <T>(f: (m: Metric) => T) => Object.fromEntries(METRICS.map((m) => [m, f(m)])) as Record<Metric, T>;
const q = (lo: number, hi: number) => Array.from({ length: 21 }, (_, i) => Math.round((lo + ((hi - lo) * i) / 20) * 1000) / 1000);
const day = (s: string) => Math.floor(Date.parse(`${s}T00:00:00Z`) / 86_400_000);

const vals = (cls: number, threads: number, addressed: number, ten: string, ok = true) => ({
  cls, threads, addressed, ten, org: 'google.com', ok,
  v: each((m) => (m[0] === 't' ? 1.2 : 0.8)), x: each(() => 1.1),
});

export const person: Person = {
  v: 1,
  generated: '2026-11-11',
  first: '2021-03',
  periods: {
    all: vals(3, 5, 3, '2-5y'),
    '2025': vals(1, 2, 1, '2-5y', false),
    '2025H2': vals(1, 2, 1, '2-5y', false),
    '2026': vals(2, 3, 2, '5-10y', false),
    '2026H1': vals(1, 1, 1, '5-10y', false),
    '2026H2': vals(1, 2, 1, '5-10y', false),
  },
  tone: { received: 40, praise: 2, share: 0.05, ten: '5-10y' },
  praise: [[1000003, 'cccc_0003', day('2026-09-02'), 'Really nice cleanup, thanks!'],
    [1000002, 'bbbb_0002', day('2026-03-10'), 'Great test coverage <img src=x onerror=alert(1)>']],
  dirs: ['chrome/browser/ui/', 'content/browser/', 'third_party/blink/renderer/'],
  files: ['chrome/browser/ui/view.cc', '/PATCHSET_LEVEL', 'content/browser/frame.cc', 'third_party/blink/renderer/core/a.cc'],
  cls: [
    [1000001, day('2025-10-01'), 40, 2, 2.5, 1.2, 1.4, [[0, 1, 0]],
      [['aaaa_0001', 0, -1, 1, 0], ['aaaa_0002', 1, 0, 0, 0, 'Please add a test.']]],
    [1000002, day('2026-03-11'), 120, 3, 3, 2, 2, [[1, 0.75, 7], [0, 0.25, 1]],
      [['bbbb_0002', 2, -1, 1, 1, 'Great test coverage <img src=x onerror=alert(1)>']]],
    [1000003, day('2026-09-03'), 10, 1, 1.5, 0.6, 0.9, [[2, 1, 150]],
      [['cccc_0001', 3, -2, 1, 2, 'Nit: rename this.'], ['cccc_0003', 1, -1, null, 2]]],
  ],
};

const dist = (lo: number, hi: number) => each(() => ({ n: 120, q: q(lo, hi) }));
const groups = () => ({
  all: dist(0.4, 3), dirxp: dist(0.5, 2.5), 'ten:2-5y': dist(0.5, 2.8), 'ten:5-10y': dist(0.3, 2),
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
  tone: { all: { n: 900, q: q(0, 0.1) }, 'ten:5-10y': { n: 200, q: q(0, 0.08) } },
};
