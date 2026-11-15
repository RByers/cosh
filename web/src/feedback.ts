// The Feedback Index page's data and arithmetic (feedback-index.html,
// docs/review-feedback.md), kept apart from the DOM so unit tests can run it.
// cosh/review_feedback.py writes one file per person, named by `personFile` of
// their address (the normalised address) and served from the R2 bucket (r2.ts),
// and peers.json with what the page compares a person with.
//
// The addressed feedback rate (AFR) of a set of changes is their addressed reviewer
// threads per 100 new or changed lines (insertions). The feedback index (FI) is a person's AFR
// over what their changes would be expected to draw: everyone's AFR at the same
// experience (CLs landed on main, in power-of-two bins), times the change's
// reviewer factor (how much feedback its approvers' approvals usually draw), both
// from everyone else's changes: `leaveOut` takes the person's own changes out of
// the sums in peers.json and reviewers.json (loaded with the person). A person's
// file holds no changes, only cells: their lines, reviewer threads and addressed
// threads per half-year, experience bin, directory and set of approvers, which is
// all every figure needs.

import { r2Url, THREADS } from './r2.ts';

/** A cell of a half-year (cosh/review_feedback.py `half_cells`): every change's share in one experience
 * bin, 3-level directory and set of approvers, as [bin, directory (index in `dirs`), approvers (indexes in
 * `revs`), changes in thousandths (each change split over its directories by lines), the landed commits'
 * inserted lines, reviewer threads, addressed threads]. */
export type FileCell = [number, number, number[], number, number, number, number];

/** One half-year of a person's file, with names listed once. */
export interface Half {
  dirs: string[];
  /** The approvers' addresses. */
  revs: string[];
  cells: FileCell[];
}

/** <name>.json: who the person is, and their changes as cells, per half-year. */
export interface PersonFile {
  v: 8;
  first: string | null;
  /** First commit on main, as a day number. */
  first_day: number | null;
  /** The org most of their changes were landed as. */
  org: string | null;
  /** When they reached each experience bin, as [day, exact]: the first bin on their first commit on
   * main, the others when their first change in the bin landed. Exact when that change was the bin's
   * first commit; otherwise they got there earlier (commits outside the data), by that day. null: no
   * change of theirs in the bin. */
  reached: ([number, boolean] | null)[];
  /** The days their first and last labelled change landed (null: none). */
  days: [number, number] | null;
  /** Each half-year ("2026H1") they landed labelled changes in. */
  halves: Record<string, Half>;
}

/** The half-years a person's file has, oldest first. */
export const halvesOf = (f: PersonFile) => Object.keys(f.halves).sort();

/** A cell as the page holds it: [half-year (index in `Person.halves`), experience bin, directory (index in
 * `Person.dirs`), approvers (indexes in `Person.revs`), changes in thousandths, lines, reviewer threads,
 * addressed threads]. */
export type Cell = [number, number, number, number[], number, number, number, number];

export interface Person {
  first: string | null;
  firstDay: number | null;
  org: string | null;
  reached: ([number, boolean] | null)[];
  days: [number, number] | null;
  halves: string[];
  dirs: string[];
  /** Everyone who approved one of the person's changes (Reviewed-by), and each one's reviewer factor
   * (from everyone else's changes; `attachReviewers`, 1 until then). */
  revs: string[];
  revF: number[];
  /** Everyone else's pooled AFR per experience bin and the factor of the person's changes without an
   * approver, the person's own changes left out (`leaveOut`; null until then: everyone's). */
  rateBin: number[] | null;
  revNone: number | null;
  cells: Cell[];
}

/** reviewers.json: per reviewer, by `reviewerKey` of their address, [their
 * factor, changes they approved (not shown), their observed and expected addressed threads]; `rev_none` is the factor
 * of changes without an approver, `none` their observed and expected threads. A factor is (observed +
 * `shrink`) / (expected + `shrink`) / `norm` (cosh/review_feedback.py `own_model`). */
export interface ReviewerTable {
  v: 2;
  rev_none: number;
  none: [number, number];
  norm: number;
  shrink: number;
  f: Record<string, [number, number, number, number]>;
}

/** Another address of someone: their file's name. */
export interface Alias {
  see: string;
}

export interface Dist {
  n: number;
  /** Quantiles at 0, 5, …, 100%; null when too few are in the group. */
  q: number[] | null;
}

/** One entry of everyone's directory table (cosh/review_feedback.py `dir_table`): [path, kind, lines,
 * reviewer threads, addressed threads, entries (kind 2)]. Kind 0: a directory; 1: the files directly in
 * it ("rest of"); 2: the smaller entries under it ("" for the top level), pooled. */
export type DirTableEntry = [string, 0 | 1 | 2, number, number, number, number?];

/** peers.json (cosh/review_feedback.py, version 11). */
export interface Peers {
  v: 12;
  generated: string;
  /** The changes covered, as day numbers: from `start` up to (not including) `end`.
   * Only changes from `addr_start` have addressed labels. */
  start: number;
  end: number;
  addr_start: number;
  /** "all" and the half-years. */
  periods: string[];
  min_peers: number;
  /** A feedback index counts among peers with this many changes. */
  min_cls: number;
  /** An AFR in one experience bin counts with this many changes. */
  min_bin_cls: number;
  min_cell_cls: number;
  min_growth_bins: number;
  /** AFRs below this count as this in the growth fit. */
  fr_floor: number;
  /** Experience bins by CLs landed on main, counting the change itself ("8": 8 or fewer, "16": 9–16, …),
   * and their edges in earlier commits (a change with `bin_edges[b]` earlier commits is in bin b + 1). */
  bins: string[];
  bin_edges: number[];
  /** The median AFR per experience bin (null: too few people), and everyone's: the opening chart's
   * line, for comparisons (the index uses `rate_bin`). */
  ref_bin: (number | null)[];
  ref_all: number;
  /** A directory gets a row of its own in everyone's directory table with this many changes. */
  min_dir_cls: number;
  /** Everyone's pooled AFR per experience bin: what a change is expected to draw, before its reviewer
   * factor; and its sums, [lines, addressed threads] per bin, from which `leaveOut` takes the person's own. */
  rate_bin: number[];
  rate_sums: [number, number][];
  /** The reviewer factor of changes without an approver. */
  rev_none: number;
  /** The methodology's comparison of peer groups: [model, deviance, % of the experience-only model's
   * deviance removed]; models "e" (experience), "d" (directory), "r" (reviewer), "dr" (both), "rd"
   * (reviewer per directory). */
  method: [string, number, number][];
  /** Reviewers within the busiest directories (2 levels): [directory, its factor, reviewers, their
   * factors there at the 10th, 25th, 50th, 75th and 90th percentiles]; factors against experience alone. */
  dir_revs: [string, number, number, [number, number, number, number, number]][];
  /** A reviewer counts in a directory in `dir_revs` with this many expected addressed comments there. */
  min_spread_exp: number;
  /** Per half-year: [half-year, changes, addressed over what experience and size expect, the same over
   * what experience, size, reviewers and authors expect]. */
  drift: [string, number, number, number][];
  /** The expected threads' scale, which makes the median contributor's index 1. */
  scale: number;
  /** Everyone's directory table, parents before their children, each level by lines. */
  dir_table: DirTableEntry[];
  /** Per experience bin, the spread of people's AFR there. */
  fr_bins: Dist[];
  /** Period -> the spread of people's feedback index. */
  fi: Record<string, Dist>;
  /** Per experience bin: [first-commit year, people, p10, p25, median, p75, p90] of people's AFR in that bin. */
  cohorts: [number, number, number | null, number | null, number | null, number | null, number | null][][];
  size_labels: string[];
  /** Per size bucket: [median AFR, median addressed threads per change, people]. */
  by_size: [number | null, number | null, number][];
  /** [directory or org, median AFR, people], highest first. */
  by_dir: [string, number, number][];
  by_org: [string, number, number][];
  /** People's growth rates (% change in AFR per doubling of changes landed). */
  growth: { n: number; median: number | null; q: number[] | null; curve: [number, number][] };
  /** Everyone's feedback index over all the data: how many, quantiles, and a smoothed curve of
   * [index, % of people per 0.1 of log2]. */
  fi_dist: { n: number; q: number[] | null; curve: [number, number][] };
}

export const GERRIT = 'https://chromium-review.googlesource.com';
const SALT = 'cosh-review-feedback-v1:';
const DAY_MS = 86_400_000;

/** An address as cosh/people.py `address` writes it: lower case, an SVN-era `user@domain@uuid` cut
 * to `user@domain`. No domains are merged: a person's other addresses find them through the
 * {"see": name} files the scripts write for every address of their identity (`Alias`). */
export function normalizeEmail(raw: string): string {
  const e = raw.trim().toLowerCase();
  return (e.match(/@/g) ?? []).length > 1 ? e.slice(0, e.lastIndexOf('@')) : e;
}

/** Whether `raw` looks enough like an address to look up. */
export const looksLikeEmail = (raw: string) => /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(raw.trim());

/** The per-person file's name for an address (cosh/review_feedback.py `file_name`): the
 * normalised address, each byte of any character outside a-z 0-9 . _ @ - written as ~xx. */
export function personFile(raw: string): string {
  return Array.from(normalizeEmail(raw), (c) => (/^[a-z0-9._@-]$/.test(c) ? c
    : Array.from(new TextEncoder().encode(c), (b) => `~${b.toString(16).padStart(2, '0')}`).join(''))).join('');
}

/** Whether `s` is a name `personFile` can give (so it is safe in a URL path). */
export const isPersonFile = (s: string) => /^[a-z0-9._~-]+@[a-z0-9._@~-]+$/.test(s);

/** A reviewer's key in reviewers.json (cosh/review_feedback.py `reviewer_key`): a salted hash of the
 * normalised address, so the committed file lists no addresses. */
export async function reviewerKey(raw: string): Promise<string> {
  const bytes = new TextEncoder().encode(SALT + normalizeEmail(raw));
  const hash = new Uint8Array(await crypto.subtle.digest('SHA-256', bytes));
  return Array.from(hash.slice(0, 6), (b) => b.toString(16).padStart(2, '0')).join('');
}

/** A day number (days since 1970-01-01) as 'YYYY-MM-DD'. */
export const isoDay = (day: number) => new Date(day * DAY_MS).toISOString().slice(0, 10);

/** A period's days [from, to): all of `range` for "all", else the year or half-year cut to it. */
export function periodSpan(period: string, range: [number, number]): [number, number] {
  if (period === 'all') return range;
  const y = Number(period.slice(0, 4));
  const m0 = period.endsWith('H2') ? 6 : 0;
  const m1 = period.length === 4 || period.endsWith('H2') ? 12 : 6;
  const from = Date.UTC(y, m0, 1) / DAY_MS;
  const to = Date.UTC(y, m1, 1) / DAY_MS;
  return [Math.max(from, range[0]), Math.min(to, range[1])];
}

/** The share of a group whose value is below `v`, read off its quantiles. */
export function percentileOf(q: number[], v: number): number {
  const k = q.length - 1;
  if (v <= q[0]) return 0;
  if (v >= q[k]) return 1;
  // Where the value sits among equal quantiles, take the middle of the run.
  let lo = 0;
  while (lo < k && q[lo + 1] < v) lo++;
  let hi = lo + 1;
  if (q[hi] === v) {
    let end = hi;
    while (end < k && q[end + 1] === v) end++;
    return (hi + end) / 2 / k;
  }
  return (lo + (v - q[lo]) / (q[hi] - q[lo])) / k;
}

/** The value at fraction `p` (0–1) of a group's quantiles. */
export function quantile(q: number[], p: number): number {
  const i = p * (q.length - 1);
  const lo = Math.floor(i);
  const hi = Math.min(lo + 1, q.length - 1);
  return q[lo] + (q[hi] - q[lo]) * (i - lo);
}

/** Half-year periods in order, from peers.json's list. */
export const halves = (periods: string[]) => periods.filter((p) => /^\d{4}H[12]$/.test(p)).sort();

// ---- AFR and index

/** The experience bin (index in `peers.bins`) of `n` earlier commits on main. */
export function xbin(edges: number[], n: number): number {
  let b = 0;
  while (b < edges.length && n >= edges[b]) b++;
  return b;
}

/** Addressed threads per 100 lines (null without lines). */
export const fr = (addressed: number, lines: number) => (lines > 0 ? (100 * addressed) / lines : null);

/** A 3-level directory's first two levels, and its first. */
export function dir2(d: string): string {
  const p = d.split('/').filter(Boolean);
  return p.length ? `${p.slice(0, 2).join('/')}/` : d;
}
export function dir1(d: string): string {
  const p = d.split('/').filter(Boolean);
  return p.length ? `${p[0]}/` : d;
}

/** The person's cells in `period` ("all" or a half-year; a year takes its two halves). */
export const cellsIn = (p: Person, period: string) => (period === 'all' ? p.cells
  : p.cells.filter((c) => p.halves[c[0]] === period || (period.length === 4 && p.halves[c[0]].startsWith(period))));

/** A 3-level directory and its parents, deepest first, then "" (all of them)
 * (cosh/review_feedback.py `dir_levels`). */
export function dirLevels(d: string): string[] {
  const p = d.split('/').filter(Boolean);
  const out: string[] = [];
  for (let k = Math.min(3, p.length); k > 0; k--) out.push(`${p.slice(0, k).join('/')}/`);
  out.push('');
  return out;
}

/** A cell's reviewer factor: its approvers' mean factor, or `rev_none` without one
 * (cosh/review_feedback.py `rev_factor`), the person's own changes left out where their file says. */
export function revFactor(p: Person, peers: Pick<Peers, 'rev_none'>, c: Cell): number {
  const r = c[3];
  return r.length ? r.reduce((a, i) => a + p.revF[i], 0) / r.length : noneFactor(p, peers);
}

/** The factor of the person's changes without an approver. */
export const noneFactor = (p: Person, peers: Pick<Peers, 'rev_none'>) => p.revNone ?? peers.rev_none;

/** The addressed threads a cell would draw (cosh/review_feedback.py `unit_expected`): its lines / 100 ×
 * everyone else's AFR at its experience × its reviewer factor × the scale. */
export const cellExpected = (p: Person, peers: Peers, c: Cell) =>
  (c[5] / 100) * (p.rateBin ?? peers.rate_bin)[c[1]] * revFactor(p, peers, c) * peers.scale;

/** Looks up the person's approvers in reviewers.json (by `reviewerKey`), then
 * leaves the person's own changes out of what theirs are compared with (`leaveOut`). */
export async function attachReviewers(p: Person, table: ReviewerTable, peers: Peers): Promise<void> {
  const keys = await Promise.all(p.revs.map((e) => reviewerKey(e)));
  const rows = keys.map((k) => table.f[k]);
  p.revF = rows.map((r) => r?.[0] ?? 1);
  leaveOut(p, peers, table, rows);
}

/** Takes the person's labelled changes out of everyone's sums (cosh/review_feedback.py `own_factors`):
 * the AFR per experience bin becomes everyone else's, and each of their reviewers' factors is refitted
 * without their changes, given their author factor as the published factors imply. A reviewer who approved
 * only the person's changes ends up at 1 / norm, the typical reviewer. `rows`: the person's approvers'
 * entries in reviewers.json, in `p.revs` order (`p.revF` still everyone's). */
export function leaveOut(p: Person, peers: Peers, table: ReviewerTable,
  rows: ([number, number, number, number] | undefined)[]): void {
  const mine = peers.rate_sums.map(() => [0, 0]);
  let addressed = 0;
  let expected = 0;
  for (const c of p.cells) {
    mine[c[1]][0] += c[5];
    mine[c[1]][1] += c[7];
    addressed += c[7];
    expected += c[5] / 100 * peers.rate_bin[c[1]] * revFactor(p, peers, c) * table.norm;
  }
  const k = table.shrink;
  const fa = (addressed + k) / (expected + k);
  // A change with several approvers counts a share for each, as in the fit.
  const obs = new Map<number, number>();
  const exp = new Map<number, number>();
  for (const c of p.cells) {
    const vs = c[3].length ? c[3] : [-1];
    for (const v of vs) {
      obs.set(v, (obs.get(v) ?? 0) + c[7] / vs.length);
      exp.set(v, (exp.get(v) ?? 0) + c[5] / 100 * peers.rate_bin[c[1]] * fa / vs.length);
    }
  }
  const factor = ([o, e]: [number, number], v: number) =>
    (Math.max(o - (obs.get(v) ?? 0), 0) + k) / (Math.max(e - (exp.get(v) ?? 0), 0) + k) / table.norm;
  p.revF = p.revF.map((f, i) => (obs.has(i) ? factor([rows[i]?.[2] ?? 0, rows[i]?.[3] ?? 0], i) : f));
  p.revNone = factor(table.none, -1);
  p.rateBin = peers.rate_sums.map(([lines, a], b) =>
    lines - mine[b][0] > 0 ? fr(a - mine[b][1], lines - mine[b][0])! : peers.rate_bin[b]);
}

/** One of the person's approvers, over the person's changes in a period. */
export interface ReviewerRow {
  email: string;
  factor: number;
  /** The person's changes they approved (with a directory filter, the share of them in it). */
  cls: number;
  lines: number;
  addressed: number;
  expected: number;
}

/** A filter to one row of the directory table: the 3-level directories counted there (`DirStats.dirs`). */
export type DirFilter = ReadonlySet<string>;

/** The cells of `period`, only those in `dir`'s row when one is given. */
export const cellsInDir = (p: Person, period: string, dir?: DirFilter | null) =>
  cellsIn(p, period).filter((c) => !dir || dir.has(p.dirs[c[2]]));

/** The person's approvers in `period`, most of the person's changes first (a change with several
 * approvers counts for each); with `dir`, only the lines and threads in that directory row. */
export function reviewerRows(p: Person, peers: Peers, period: string, dir?: DirFilter | null): ReviewerRow[] {
  const rows = new Map<number, ReviewerRow & { milli: number }>();
  for (const c of cellsInDir(p, period, dir)) {
    const e = cellExpected(p, peers, c);
    for (const i of c[3]) {
      let r = rows.get(i);
      if (!r) rows.set(i, (r = { email: p.revs[i], factor: p.revF[i], cls: 0, milli: 0,
        lines: 0, addressed: 0, expected: 0 }));
      r.milli += c[4];
      r.lines += c[5];
      r.addressed += c[7];
      r.expected += e;
    }
  }
  return [...rows.values()].map(({ milli, ...r }) => ({ ...r, cls: milli / 1000 }))
    .sort((x, y) => y.cls - x.cls || y.lines - x.lines || x.email.localeCompare(y.email));
}

/** The person's changes without an approver in `period` (in `dir`'s row, their share there). */
export const noApproverCls = (p: Person, period: string, dir?: DirFilter | null) =>
  cellsInDir(p, period, dir).reduce((a, c) => a + (c[3].length ? 0 : c[4]), 0) / 1000;

export interface Sums {
  cls: number;
  addressed: number;
  lines: number;
  expected: number;
}

/** Totals over `cs`, with the expected addressed threads. Changes add up in thousandths, so whole
 * half-years and bins give whole numbers. */
export function sums(p: Person, peers: Peers, cs: Cell[]): Sums {
  let milli = 0;
  const s = { cls: 0, addressed: 0, lines: 0, expected: 0 };
  for (const c of cs) {
    milli += c[4];
    s.addressed += c[7];
    s.lines += c[5];
    s.expected += cellExpected(p, peers, c);
  }
  s.cls = milli / 1000;
  return s;
}

/** The feedback index of some totals (null: nothing expected). */
export const fiOf = (s: Sums) => (s.expected > 0 ? s.addressed / s.expected : null);
export const frOf = (s: Sums) => fr(s.addressed, s.lines);

/** Totals per experience bin of the person's changes in `period`. */
export const binSums = (p: Person, peers: Peers, period: string): Sums[] =>
  peers.bins.map((_, b) => sums(p, peers, cellsIn(p, period).filter((c) => c[1] === b)));

/** A growth rate: the % change in AFR per doubling of changes landed, from a
 * least-squares line through log2 AFR (floored) by bin, weighted by changes, over
 * the bins with `min_bin_cls` changes; null with fewer than `min_growth_bins`
 * (cosh/review_feedback.py `growth`). */
export function growth(bins: Sums[], peers: Pick<Peers, 'min_bin_cls' | 'min_growth_bins' | 'fr_floor'>): number | null {
  const pts = bins.flatMap((s, b) => (s.cls >= peers.min_bin_cls && s.lines > 0
    ? [[b, Math.log2(Math.max(fr(s.addressed, s.lines)!, peers.fr_floor)), s.cls]] : []));
  if (pts.length < peers.min_growth_bins) return null;
  const w = pts.reduce((a, [, , n]) => a + n, 0);
  const mx = pts.reduce((a, [b, , n]) => a + b * n, 0) / w;
  const my = pts.reduce((a, [, y, n]) => a + y * n, 0) / w;
  const sxx = pts.reduce((a, [b, , n]) => a + n * (b - mx) ** 2, 0);
  const sxy = pts.reduce((a, [b, y, n]) => a + n * (b - mx) * (y - my), 0);
  return Math.round(1000 * (2 ** (sxy / sxx) - 1)) / 10;
}

/** The person's latest doubling: the change in AFR (%) from their second-newest to their newest
 * experience bin with `min_bin_cls` changes, per doubling where bins in between have too few
 * (`steps` > 1), with the typical change over the same bins (the median AFRs, `ref_bin`) and when
 * they reached the newer bin (`PersonFile.reached`). AFRs under `fr_floor` count as it. null: fewer than
 * two such bins. */
export interface Doubling {
  from: number;
  to: number;
  steps: number;
  change: number;
  typical: number | null;
  reached: [number, boolean] | null;
}

export function latestDoubling(p: Person, bins: Sums[], peers: Pick<Peers, 'min_bin_cls' | 'fr_floor' | 'ref_bin' | 'bin_edges'>): Doubling | null {
  const ok = bins.flatMap((s, b) => (s.cls >= peers.min_bin_cls && s.lines > 0 ? [b] : []));
  if (ok.length < 2) return null;
  const [from, to] = ok.slice(-2);
  const steps = to - from;
  const rate = (b: number) => Math.max(fr(bins[b].addressed, bins[b].lines)!, peers.fr_floor);
  const pct = (ratio: number) => Math.round(1000 * (ratio ** (1 / steps) - 1)) / 10;
  const r0 = peers.ref_bin[from];
  const r1 = peers.ref_bin[to];
  return { from, to, steps, change: pct(rate(to) / rate(from)),
    typical: r0 && r1 ? pct(r1 / r0) : null, reached: p.reached[to] ?? null };
}

// ---- Directory figures

/** The person's figures for one row of the directory table. */
export interface DirStats {
  /** Changes in it: each change's share there by lines. */
  cls: number;
  milli: number;
  /** The landed commits' inserted lines there. */
  lines: number;
  /** Reviewer threads there, addressed or not. */
  threads: number;
  addressed: number;
  /** Addressed threads expected there at the peers' AFR. */
  expected: number;
  /** The 3-level directories counted here: to filter "Your feedback" to this row (`DirFilter`). */
  dirs: Set<string>;
}

function addTo(s: DirStats, dir: string, c: Cell, exp: number) {
  s.milli += c[4];
  s.cls = s.milli / 1000;
  s.lines += c[5];
  s.threads += c[6];
  s.addressed += c[7];
  s.expected += exp;
  s.dirs.add(dir);
}

/** The index cell's shade: -1 (a quarter of typical or less) .. 0 (typical) .. 1 (4× or more), on a log scale. */
export function ratioShade(ratio: number): number {
  if (!(ratio > 0)) return -1;
  return Math.max(-1, Math.min(1, Math.log2(ratio) / 2));
}

/** An AFR's shade in the directory tables: 0 (a quarter per 100 lines or less) .. 1 (8 or more), on a log scale. */
export function afrShade(v: number): number {
  if (!(v > 0)) return 0;
  return Math.max(0, Math.min(1, Math.log2(v / 0.25) / 5));
}

// ---- Everyone's directory table

/** Everyone's figures for a row of the directory table. */
export interface AllStats {
  lines: number;
  threads: number;
  addressed: number;
}

/** A row of everyone's directory table (`peers.dir_table`): a directory, the files directly in it
 * ("rest"), or its smaller entries pooled ("other"), with everyone's figures and, once someone is
 * looked up, theirs. */
export interface TableNode {
  /** "d:path", "r:path" or "o:path" (`path` "" for the top level's "Other"). */
  key: string;
  kind: 'dir' | 'rest' | 'other';
  path: string;
  /** The last part of the path ("browser/"); "" for the others. */
  name: string;
  all: AllStats;
  you: DirStats;
  /** Entries pooled in an "other" row. */
  count?: number;
  children: TableNode[];
}

const emptyStats = (): DirStats => ({ cls: 0, milli: 0, lines: 0, threads: 0, addressed: 0, expected: 0, dirs: new Set() });

/** Everyone's directory table as a tree, with the person's cells in `period` (if any) added: each to
 * its directory, its parents, and to "rest of" or a level's "Other" where the table has no row of its
 * own for it. Parents add up their children, so the index of a row is its addressed threads over its
 * expected ones whether it is open or not. */
export function dirTable(peers: Peers, p: Person | null, period: string): TableNode[] {
  const roots: TableNode[] = [];
  const byKey = new Map<string, TableNode>();
  const name = (path: string) => {
    const parts = path.split('/').filter(Boolean);
    return parts.length ? `${parts.at(-1)}/` : path;
  };
  for (const [path, kind, lines, threads, addr, count] of peers.dir_table) {
    const k = kind === 0 ? 'dir' : kind === 1 ? 'rest' : 'other';
    const n: TableNode = { key: `${k[0]}:${path}`, kind: k, path, name: kind === 0 ? name(path) : '',
      all: { lines, threads, addressed: addr }, you: emptyStats(), children: [] };
    if (count !== undefined) n.count = count;
    byKey.set(n.key, n);
    const parent = kind === 0 ? dirLevels(path)[1] : path;
    const into = parent ? byKey.get(`d:${parent}`) : undefined;
    (into ? into.children : roots).push(n);
  }
  if (!p) return roots;
  for (const c of cellsIn(p, period)) {
    const path = p.dirs[c[2]];
    const exp = cellExpected(p, peers, c);
    const put = (n: TableNode) => addTo(n.you, path, c, exp);
    // Top level first: each level's own row, or that level's "Other", where the walk stops.
    let parent = '';
    let last: TableNode | null = null;
    for (const k of dirLevels(path).slice(0, -1).reverse()) {
      const n = byKey.get(`d:${k}`);
      if (!n) {
        const o = byKey.get(`o:${parent}`);
        if (o) put(o);
        last = null;
        break;
      }
      put(n);
      last = n;
      parent = k;
    }
    // Files directly in a directory that has subdirectories.
    const rest = last && last.path === path ? byKey.get(`r:${path}`) : undefined;
    if (rest) put(rest);
  }
  return roots;
}

/** One visible row of everyone's directory table: a node, or a level's "show more" row (`more`: how many
 * directories it hides). */
export interface TableRowView {
  key: string;
  node: TableNode | null;
  more?: number;
  depth: number;
  expandable: boolean;
  expanded: boolean;
  /** Everyone's AFR; the person's AFR and index there (null under `minCls` of their changes). */
  fr: number | null;
  youFr: number | null;
  youFi: number | null;
}

/** The rows to show of `dirTable`'s tree, given which are open (`expanded`, by key): each level
 * by lines, the person's first when `byYou` (then everyone's), with "rest of" and "Other" last. A level
 * lists its first `shown` directories and a "more" row (key "m:" + the parent's key) that shows the
 * rest. The person's AFR and index show only with `minCls` of their changes in the row. */
export function tableRows(roots: TableNode[], expanded: ReadonlySet<string>, byYou: boolean, minCls: number,
  shown = 12): TableRowView[] {
  const out: TableRowView[] = [];
  const rank = (n: TableNode) => (n.kind === 'dir' ? 0 : n.kind === 'rest' ? 1 : 2);
  const order = (a: TableNode, b: TableNode) => rank(a) - rank(b) || (byYou ? b.you.lines - a.you.lines : 0) ||
    b.all.lines - a.all.lines || (a.key < b.key ? -1 : 1);
  const walk = (ns: TableNode[], depth: number, parentKey: string) => {
    const sorted = [...ns].sort(order);
    const dirs = sorted.filter((n) => n.kind === 'dir').length;
    const moreKey = `m:${parentKey}`;
    const all = dirs <= shown + 1 || expanded.has(moreKey);
    sorted.forEach((n, i) => {
      if (!all && i === shown) {
        out.push({ key: moreKey, node: null, more: dirs - shown, depth, expandable: true, expanded: false,
          fr: null, youFr: null, youFi: null });
      }
      if (!all && i >= shown && n.kind === 'dir') return;
      const expandable = n.children.length > 0;
      const open = expandable && expanded.has(n.key);
      const big = n.you.cls >= minCls;
      out.push({ key: n.key, node: n, depth, expandable, expanded: open, fr: fr(n.all.addressed, n.all.lines),
        youFr: big ? fr(n.you.addressed, n.you.lines) : null,
        youFi: big && n.you.expected > 0 ? n.you.addressed / n.you.expected : null });
      if (open) walk(n.children, depth + 1, n.key);
    });
  };
  walk(roots, 0, 'root');
  return out;
}

// ---- Merging a person's files

/** A person's file with its half-years merged, names re-indexed. */
export function buildPerson(file: PersonFile): Person {
  const dirs = new Map<string, number>();
  const revs = new Map<string, number>();
  const at = (t: Map<string, number>, name: string) => {
    let i = t.get(name);
    if (i === undefined) t.set(name, (i = t.size));
    return i;
  };
  const hs = halvesOf(file);
  const cells: Cell[] = [];
  hs.forEach((h, hi) => {
    const f = file.halves[h];
    const d = f.dirs.map((x) => at(dirs, x));
    const r = f.revs.map((x) => at(revs, x));
    for (const [b, di, vs, milli, lines, threads, a] of f.cells) cells.push([hi, b, d[di], vs.map((i) => r[i]), milli, lines, threads, a]);
  });
  return { first: file.first, firstDay: file.first_day, org: file.org, reached: file.reached, days: file.days,
    halves: hs, dirs: [...dirs.keys()], revs: [...revs.keys()], revF: [...revs.keys()].map(() => 1),
    rateBin: null, revNone: null, cells };
}

// ---- downloading your comments (cosh/review_threads.py, served from the R2 bucket)

/** review-feedback/threads/v3/<key>.json (cosh/review_threads.py, version 4): the threads on the
 * person's changes that landed in the past year. Comment text is untrusted: it goes only into the
 * downloaded file, never into the page. */
export interface ThreadFile {
  v: 4;
  /** The changes' landing days, YYYY-MM-DD, inclusive: the 52 weeks up to the data's end. */
  from: string;
  to: string;
  /** Names (else addresses), indexed by `owner` and each comment's first element. */
  people: string[];
  /** Which approver each of them is, as the person's file names approvers (`Person.revs`,
   * `ReviewerRow.email`), tied to their Gerrit account by the Reviewed-by addresses; null for others. */
  reviewers: (string | null)[];
  cls: ThreadCl[];
}

export interface ThreadCl {
  n: number;
  /** The half-year the Feedback Index counts it in ("2026H1"). */
  half: string;
  project: string;
  subject: string;
  /** YYYY-MM-DD. */
  landed: string;
  lines: number | null;
  owner: number;
  threads: Thread[];
}

export interface Thread {
  /** The first comment's uuid. */
  id: string;
  /** A file, "/COMMIT_MSG" or "/PATCHSET_LEVEL" (a comment on the whole change). */
  path: string;
  line: number | null;
  ps: number | null;
  /** Whether the owner changed the change in response; null for change-level threads and threads
   * not yet labelled. */
  addressed: boolean | null;
  resolved: boolean;
  /** The 3-level directory the Feedback Index counts it in (null: a comment on the whole change). */
  dir: string | null;
  /** [people index, "YYYY-MM-DDTHH:MMZ", text]. */
  comments: [number, string, string][];
}

/** The URL of one person's threads of the past year: one gzipped JSON file per person in the R2
 * bucket (too big for git), fetched only when someone downloads their comments or opens a
 * reviewer. `name` is their `personFile`; `v` (the data's end) skips cached older copies. */
export function threadsUrl(name: string, v: number, host?: string): string {
  if (!isPersonFile(name)) throw new Error('bad name');
  return r2Url(THREADS, `${name}.json`, v, host);
}

/** A Gerrit link to a thread, by its change's project. */
export function threadUrl(project: string, cl: number, uuid: string): string {
  return `${GERRIT}/c/${project.split('/').map(encodeURIComponent).join('/')}/+/${Math.trunc(cl)}/comment/${encodeURIComponent(uuid)}/`;
}

/** Every comment line of `text` quoted for Markdown. */
const quoted = (text: string) => text.replace(/\r\n?/g, '\n').trim().split('\n').map((l) => (l ? `> ${l}` : '>')).join('\n');
/** Inline code that survives backticks in the content. */
const code = (s: string) => {
  const ticks = '`'.repeat(Math.max(0, ...(s.match(/`+/g) ?? []).map((t) => t.length)) + 1);
  return `${ticks}${ticks.length > 1 ? ' ' : ''}${s}${ticks.length > 1 ? ' ' : ''}${ticks}`;
};
/** One line of untrusted text for a heading: no line breaks, no leading Markdown markers. */
const oneLine = (s: string) => s.replace(/\s+/g, ' ').trim();

/** Labels the Markdown uses, from the page's templates. */
export interface MdLabels {
  owner: string;
  addressed: string;
  notAddressed: string;
  unresolved: string;
  change: string;
  commitMsg: string;
  line: (n: number) => string;
  patchSet: (n: number) => string;
  landed: (day: string, lines: string) => string;
}

/** The threads as Markdown: one section per change, oldest first, each thread with where it was
 * left, whether it was addressed, a link to it in Gerrit, and every comment quoted. */
export function threadsMarkdown(files: ThreadFile[], l: MdLabels): { md: string; cls: number; threads: number } {
  const out: string[] = [];
  let cls = 0;
  let threads = 0;
  const all = files.flatMap((f) => f.cls.map((c) => ({ f, c }))).sort((x, y) => x.c.landed.localeCompare(y.c.landed) || x.c.n - y.c.n);
  for (const { f, c } of all) {
    if (!c.threads.length) continue;
    cls++;
    out.push(`## ${oneLine(c.subject) || `${l.change} ${c.n}`}`, '',
      `[${l.change} ${c.n}](${GERRIT}/c/${c.project.split('/').map(encodeURIComponent).join('/')}/+/${c.n}) · ${l.landed(c.landed, c.lines === null ? '?' : String(c.lines))}`, '');
    for (const t of c.threads) {
      threads++;
      const where = t.path === '/PATCHSET_LEVEL' ? l.change : t.path === '/COMMIT_MSG' ? l.commitMsg : code(t.path);
      const bits = [where];
      if (t.line) bits.push(l.line(t.line));
      if (t.ps) bits.push(l.patchSet(t.ps));
      if (t.addressed !== null) bits.push(t.addressed ? l.addressed : l.notAddressed);
      if (!t.resolved) bits.push(l.unresolved);
      out.push(`### ${bits.join(' · ')} · [Gerrit](${threadUrl(c.project, c.n, t.id)})`, '');
      for (const [who, at, text] of t.comments) {
        const name = oneLine(f.people[who] ?? '?');
        out.push(`**${name}${who === c.owner ? ` (${l.owner})` : ''}**, ${at.slice(0, 10)}:`, '', quoted(text), '');
      }
    }
  }
  return { md: out.join('\n'), cls, threads };
}

/** One addressed comment under a reviewer in "Your feedback": a thread they started. */
export interface ReviewerComment {
  cl: number;
  project: string;
  /** The thread's first comment's uuid. */
  id: string;
  /** YYYY-MM-DD of that comment. */
  day: string;
  path: string;
}

/** The addressed threads approver `rev` (a `ReviewerRow.email`) started on the person's changes in
 * `files`, newest first, only those counted in `dir`'s row and on changes of half-year `half` if
 * given. A thread counts when its first comment's author is that approver (`ThreadFile.reviewers`). */
export function reviewerComments(files: ThreadFile[], rev: string, dir?: DirFilter | null, half?: string | null): ReviewerComment[] {
  const out: ReviewerComment[] = [];
  for (const f of files) {
    const mine = new Set(f.reviewers.flatMap((r, i) => (r === rev ? [i] : [])));
    if (!mine.size) continue;
    for (const c of f.cls) {
      if (half && c.half !== half) continue;
      for (const t of c.threads) {
        const first = t.comments[0];
        if (t.addressed === true && first && mine.has(first[0]) && (!dir || (t.dir !== null && dir.has(t.dir))))
          out.push({ cl: c.n, project: c.project, id: t.id, day: first[1].slice(0, 10), path: t.path });
      }
    }
  }
  return out.sort((x, y) => y.day.localeCompare(x.day) || y.cl - x.cl || x.id.localeCompare(y.id));
}
