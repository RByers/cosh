// A made-up person and peer file for the Review Feedback tests, shaped like
// cosh/review_feedback.py's output: a top file and one file per
// half-year. The browser tests serve these instead of the committed data.
import type { Norm, Peers, Shard, Top } from '../src/feedback.ts';

/** personKey('Test.Person@chromium.org'), as the Python script computes it. */
export const FIXTURE_EMAIL = 'Test.Person@chromium.org';
export const FIXTURE_KEY = '2da4ec431edc6e08b535984c029f9a9d';
/** Another address of the same person, whose file points at FIXTURE_KEY. */
export const ALIAS_EMAIL = 'tp@example.com';
export const ALIAS_KEY = 'bbf27d6626ae4d5f589d68403ed10bab';

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

const periods = ['all', '2023H2', '2024H1', '2024H2', '2025H1', '2025H2', '2026H1', '2026H2'];
const norms: Norm[] = ['', 'e', 'd', 'ed', 'o', 'eo', 'do', 'edo'];
const refBin = [4, 3, 2.5, 2, 1.7, 1.3, 1, 0.8, 0.6, 0.43];
// A smoothed bell around -20% per doubling, on the script's grid (log2 -2 .. 1.5 in steps of 0.05).
const curve = Array.from({ length: 71 }, (_, i): [number, number] => {
  const x = -2 + 0.05 * i;
  return [Math.round(1000 * (2 ** x - 1)) / 10, Math.round(1000 * 5 * Math.exp(-0.5 * ((x + 0.32) / 0.5) ** 2)) / 1000];
});

export const peers: Peers = {
  v: 5,
  generated: '2026-11-14',
  start: day('2023-07-01'),
  end: day('2026-11-01'),
  addr_start: day('2023-07-01'),
  periods,
  min_peers: 10,
  // Small minimums, so the person's three changes count: as many as needed among peers, one per bin.
  min_cls: 2,
  min_bin_cls: 1,
  min_cell_cls: 10,
  min_growth_bins: 3,
  fr_floor: 0.1,
  bins: ['<8', '8–15', '16–31', '32–63', '64–127', '128–255', '256–511', '512–1k', '1k–2k', '2k+'],
  bin_edges: [8, 16, 32, 64, 128, 256, 512, 1024, 2048],
  norms,
  ref_bin: refBin,
  ref_all: 1.5,
  f_dir: { '': { 'chrome/browser/': 1.1, 'content/': 0.9 }, e: { 'chrome/browser/': 1.2, 'content/': 0.8, 'third_party/blink/': 0.5 } },
  f_org: { '': { 'google.com': 0.9, '*': 1.3 }, e: { 'google.com': 1, '*': 1.05 }, d: { 'google.com': 0.95, '*': 1.2 },
    ed: { 'google.com': 1.1, '*': 1 } },
  // The spread of everyone's rate per bin: a quarter to three times the median.
  fr_bins: refBin.map((r, i) => (i === 9 ? { n: 6, q: null } : { n: 3000 - 300 * i, q: q(r / 4, r * 3) })),
  // Everyone's index runs 0.3 .. 2.5 evenly, in every period and norm; outside that, as noted.
  fi: Object.fromEntries(norms.map((nm) => [nm, Object.fromEntries(periods.map((p) => [p, { n: 2800, q: q(0.3, 2.5) }]))])),
  newcomer_cls: 10,
  newcomers: [2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026].map((y, i) =>
    [y, 300 + i, 1, 1.8, 3.7 + (i % 3) / 10, 6.5, 10]),
  size_labels: ['<4', '4–7', '8–15', '16–31', '32–63', '64–127', '128–255', '256–511', '512–1k', '1k+'],
  by_size: [[2.82, 0.06, 1694], [2.86, 0.15, 1621], [2.43, 0.27, 1689], [2.14, 0.5, 1850], [2.09, 0.96, 1922],
    [1.97, 1.8, 1960], [1.75, 3.18, 1895], [1.46, 5.22, 1626], [1, 6.88, 1085], [0.23, 4.69, 527]],
  by_dir: [['components/autofill/', 2.43, 126], ['chrome/browser/', 1.74, 1885], ['third_party/blink/', 1.16, 918],
    ['testing/buildbot/', 0.11, 161]],
  by_org: [['microsoft.com', 2.24, 225], ['google.com', 1.72, 3168], ['igalia.com', 1.2, 50]],
  growth: { n: 2547, median: -20.9, q: q(-70, 60), curve },
};
