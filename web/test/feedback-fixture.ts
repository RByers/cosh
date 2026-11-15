// A made-up person and peer file for the Review Feedback tests, shaped like
// cosh/review_feedback.py's output: one file per person, by half-year. The
// browser tests serve these instead of the committed data.
import type { PersonFile, Peers, ReviewerTable, Shard } from '../src/feedback.ts';

/** personFile('Test.Person@chromium.org'), as the Python script computes it. */
export const FIXTURE_EMAIL = 'Test.Person@chromium.org';
export const FIXTURE_KEY = 'test.person@google.com';
/** Another address of the same person, whose file points at FIXTURE_KEY. */
export const ALIAS_EMAIL = 'tp@example.com';
export const ALIAS_KEY = 'tp@example.com';

const q = (lo: number, hi: number) => Array.from({ length: 21 }, (_, i) => Math.round((lo + ((hi - lo) * i) / 20) * 1000) / 1000);
export const day = (s: string) => Math.floor(Date.parse(`${s}T00:00:00Z`) / 86_400_000);


/** Three changes, one per half-year. Each file lists its own names, in its own order. A change is
 * [number less the previous one's (the first: itself), day likewise, lines, earlier commits on main,
 * units, approvers, files that drew comments]; units are [[directory, the landed commit's lines there],
 * ...] or the directory alone; approvers are indexes in `revs`; files are [file, lines there, threads,
 * addressed], by name. The first change was approved by Alice, the second by Alice and Bob, the third by
 * no one. */
export const shards: Record<string, Shard> = {
  '2025H2': { dirs: ['chrome/browser/ui/'], files: ['/COMMIT_MSG', 'chrome/browser/ui/view.cc'],
    revs: ['alice@google.com'],
    cls: [[1000001, day('2025-10-01'), 40, 30, 0, [0], [[0, 0, 1, 0], [1, 30, 1, 1]]]] },
  '2026H1': { dirs: ['content/browser/', 'chrome/browser/ui/'], files: ['content/browser/frame.cc'],
    revs: ['alice@google.com', 'bob@igalia.com'],
    cls: [[1000002, day('2026-03-11'), 120, 80, [[0, 90], [1, 28]], [0, 1], [[0, 50, 1, 1]]]] },
  // A file in a subdirectory of its 3-level directory, and an unlabelled thread on the commit message.
  '2026H2': { dirs: ['third_party/blink/renderer/'], files: ['/COMMIT_MSG', 'third_party/blink/renderer/core/a.cc'],
    revs: [],
    cls: [[1000003, day('2026-09-03'), 10, 260, 0, [], [[0, 0, 1, 0], [1, 8, 1, 1]]]] },
};

/** The person's file: who they are and the three half-years above. */
export const top: PersonFile = {
  v: 7,
  first: '2022-03',
  first_day: day('2022-03-01'),
  org: 'google.com',
  halves: shards,
};

/** reviewers.json: Alice's approvals draw 1.2× what experience predicts, Bob's 0.6×, and changes
 * without an approver 0.5×; keyed by reviewerKey of their addresses. Their sums
 * are so large that leaving the person's three changes out moves no factor by more than 1e-9. */
export const reviewers: ReviewerTable = {
  v: 2,
  rev_none: 0.5,
  none: [0.5e12, 1e12],
  norm: 1,
  shrink: 50,
  f: { be7cd94b029a: [1.2, 900, 1.2e12, 1e12], e370b1ea692c: [0.6, 300, 0.6e12, 1e12] },
};

const periods = ['all', '2023H2', '2024H1', '2024H2', '2025H1', '2025H2', '2026H1', '2026H2'];
const refBin = [4, 3, 2.5, 2, 1.7, 1.3, 1, 0.8, 0.6, 0.43];
// A smoothed bell around -20% per doubling, on the script's grid (log2 -2 .. 1.5 in steps of 0.05).
const curve = Array.from({ length: 71 }, (_, i): [number, number] => {
  const x = -2 + 0.05 * i;
  return [Math.round(1000 * (2 ** x - 1)) / 10, Math.round(1000 * 5 * Math.exp(-0.5 * ((x + 0.32) / 0.5) ** 2)) / 1000];
});

export const peers: Peers = {
  v: 12,
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
  bins: ['8', '16', '32', '64', '128', '256', '512', '1k', '2k', '>2k'],
  bin_edges: [8, 16, 32, 64, 128, 256, 512, 1024, 2048],
  ref_bin: refBin,
  ref_all: 1.5,
  min_dir_cls: 100,
  // Everyone's rate per bin, and the factor of changes without an approver (reviewers.json has it too).
  rate_bin: refBin,
  // Its sums, large enough that leaving the person out barely moves it.
  rate_sums: refBin.map((r): [number, number] => [1e12, r * 1e10]),
  rev_none: 0.5,
  scale: 1,
  // The methodology: what each peer group predicts, how widely directories and reviewers differ, and
  // drift per half-year (steady, then 0.8 in the last).
  method: [['e', 3_000_000, 0], ['d', 2_830_000, 5.6], ['r', 2_700_000, 10], ['dr', 2_690_000, 10.2],
    ['rd', 2_670_000, 11]],
  dir_revs: [['chrome/browser/', 1.26, 833, [0.72, 0.89, 1.12, 1.39, 1.72]],
    ['third_party/blink/', 0.77, 372, [0.47, 0.65, 0.96, 1.25, 1.5]]],
  min_spread_exp: 50,
  drift: [['2025H1', 50_000, 1.05, 1.01], ['2025H2', 50_000, 0.98, 0.98], ['2026H1', 55_000, 0.9, 0.96],
    ['2026H2', 40_000, 0.77, 0.81]],
  // Everyone's directory table: third_party/blink/ is among third_party/'s smaller entries.
  dir_table: [
    ['third_party/', 0, 6_000_000, 50_000, 40_000],
    ['third_party/', 2, 500_000, 1_000, 800, 120],
    ['chrome/', 0, 5_000_000, 150_000, 120_000],
    ['chrome/browser/', 0, 4_000_000, 120_000, 100_000],
    ['chrome/browser/ui/', 0, 2_500_000, 80_000, 70_000],
    ['chrome/browser/', 1, 1_000, 30, 20],
    ['chrome/browser/', 2, 2_000, 40, 30, 7],
    ['content/', 0, 3_000_000, 90_000, 60_000],
    ['content/browser/', 0, 2_000_000, 70_000, 50_000],
    ['', 2, 1_000, 10, 5, 30],
  ],
  // The spread of everyone's rate per bin: a quarter to three times the median.
  fr_bins: refBin.map((r, i) => (i === 9 ? { n: 6, q: null } : { n: 3000 - 300 * i, q: q(r / 4, r * 3) })),
  // Everyone's index runs 0.3 .. 2.5 evenly, in every period; outside that, as noted.
  fi: Object.fromEntries(periods.map((p) => [p, { n: 2800, q: q(0.3, 2.5) }])),
  // Per experience bin, by start year; from bin 8 on, too few people for a median.
  cohorts: Array.from({ length: 10 }, (_, b) => [2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026]
    .slice(0, 9 - b).map((y, i): [number, number, number | null, number | null, number | null, number | null, number | null] =>
      (b >= 8 ? [y, 5, null, null, null, null, null] : [y, 300 + i - 30 * b, 1, 1.8, 3.7 + (i % 3) / 10 - b / 4, 6.5, 10]))),
  size_labels: ['<4', '4–7', '8–15', '16–31', '32–63', '64–127', '128–255', '256–511', '512–1k', '1k+'],
  by_size: [[2.82, 0.06, 1694], [2.86, 0.15, 1621], [2.43, 0.27, 1689], [2.14, 0.5, 1850], [2.09, 0.96, 1922],
    [1.97, 1.8, 1960], [1.75, 3.18, 1895], [1.46, 5.22, 1626], [1, 6.88, 1085], [0.23, 4.69, 527]],
  by_dir: [['components/autofill/', 2.43, 126], ['chrome/browser/', 1.74, 1885], ['third_party/blink/', 1.16, 918],
    ['testing/buildbot/', 0.11, 161]],
  by_org: [['microsoft.com', 2.24, 225], ['google.com', 1.72, 3168], ['igalia.com', 1.2, 50]],
  growth: { n: 2547, median: -20.9, q: q(-70, 60), curve },
  // A bell around 1 on a log scale, on the script's grid (log2 -3 .. 2.5).
  fi_dist: { n: 2843, q: q(0.3, 2.5), curve: Array.from({ length: 111 }, (_, i): [number, number] => {
    const x = -3 + 0.05 * i;
    return [Math.round(1000 * 2 ** x) / 1000, Math.round(1000 * 4 * Math.exp(-0.5 * (x / 0.8) ** 2)) / 1000];
  }) },
};
