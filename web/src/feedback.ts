// The Feedback Index page's data and arithmetic (feedback-index.html,
// docs/review-feedback.md), kept apart from the DOM so unit tests can run it.
// cosh/review_feedback.py writes one file per person and half-year, named by
// `personKey` of their address, and peers.json with what the page compares a
// person with.
//
// The addressed feedback rate (AFR) of a set of changes is their addressed reviewer
// threads per 100 new or changed lines (insertions). The feedback index (FI) is a person's AFR
// over their peers': for each directory a change wrote lines in, the AFR of
// everyone else's lines there in the same half-year at the same experience (CLs
// landed on main, in power-of-two bins), or the parent directory's where that is
// too thin.

/** A change's lines in one 3-level directory: [directory index, the landed commit's inserted lines there]. */
export type Unit = [number, number];
/** A file of a change that drew reviewer threads: [file index, the landed commit's inserted lines in it
 * (0: the commit message, or a file it didn't change), threads, addressed, the unit its threads count in
 * (index in the change's units)]. */
export type FileFb = [number, number, number, number, number];
/** A change, as the page holds it: [change number, day landed (days since 1970), lines (Gerrit's
 * insertions), units, files that drew threads, the owner's earlier commits on main]. */
export type ClRow = [number, number, number, Unit[], FileFb[], number];

/** A change in a half-year file (cosh/review_feedback.py `shard`): [change number less the previous
 * change's (the first: itself), day landed less the previous change's (the first: days since 1970),
 * lines, earlier commits on main, units(, files)]. Units are [[directory, lines], ...], or the directory
 * alone for a change wholly in one. Files are [file, lines, threads, addressed]: only those that drew
 * reviewer threads; a file's threads count in its 3-level directory when that is one of the units, else
 * in the first. */
export type FileRow = [number, number, number, number, number | [number, number][], [number, number, number, number][]?];

/** u/<key>.json: who the person is and which half-year files they have. */
export interface Top {
  v: 6;
  first: string | null;
  /** First commit on main, as a day number. */
  first_day: number | null;
  /** The org most of their changes were landed as. */
  org: string | null;
  halves: string[];
}

/** <half>/<key>.json: one half-year's changes, with names listed once. */
export interface Shard {
  dirs: string[];
  files: string[];
  cls: FileRow[];
}

/** links/<half>/<key>.json, for half-years from `peers.links_from`, loaded when a file's changes are
 * shown (cosh/review_feedback.py `link_file`, written by a separate step): per change number, per file
 * entry (position in that change's files), its addressed threads oldest first, each a comment id or
 * [comment id, tone score (−1 .. +1)]. */
export interface LinkShard {
  cls: Record<string, [number, (string | [string, number])[]][]>;
}

/** A person's files merged. */
export interface Person {
  /** The first day (days since 1970) of the changes with addressed labels. */
  addrStart: number;
  first: string | null;
  firstDay: number | null;
  org: string | null;
  dirs: string[];
  files: string[];
  cls: ClRow[];
}

/** Another address of someone: their file's key. */
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

/** A rate cell's sums: [changes' worth, lines, addressed threads]. */
export type RateCell = [number, number, number];

/** peers.json (cosh/review_feedback.py, version 9). */
export interface Peers {
  v: 9;
  generated: string;
  /** The changes covered, as day numbers: from `start` up to (not including) `end`.
   * Only changes from `addr_start` have addressed labels. */
  start: number;
  end: number;
  addr_start: number;
  /** The first half-year whose addressed comments link to the comment (links/); older ones to the change. */
  links_from: string;
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
   * line, for comparisons (the index uses `rates`). */
  ref_bin: (number | null)[];
  ref_all: number;
  /** A directory (3 levels, 2, 1, or "" for all) gets its own peers' rate at an experience bin with
   * this many changes' worth there. */
  min_rate_cls: number;
  /** A directory gets a row of its own in everyone's directory table with this many changes. */
  min_dir_cls: number;
  /** Per half-year, per directory, the sums of everyone's lines there per experience bin; null where too
   * few (`min_rate_cls`; "" always has them). The peers' rate is these less the person's own (`peerRate`). */
  rates: Record<string, Record<string, (RateCell | null)[]>>;
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

/** One identity per person, as scripts/balance_analysis.py `person` makes it:
 * lower case, an SVN-era `user@domain@uuid` cut to `user@domain`, and
 * chromium.org merged into google.com. */
export function normalizeEmail(raw: string): string {
  let e = raw.trim().toLowerCase();
  if ((e.match(/@/g) ?? []).length > 1) e = e.slice(0, e.lastIndexOf('@'));
  const at = e.indexOf('@');
  if (at < 0) return e;
  const local = e.slice(0, at);
  const dom = e.slice(at + 1);
  return dom === 'chromium.org' || dom === 'google.com' ? `${local}@google.com` : e;
}

/** Whether `raw` looks enough like an address to look up. */
export const looksLikeEmail = (raw: string) => /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(raw.trim());

/** The data file's name for an address (cosh/review_feedback.py `key`). */
export async function personKey(raw: string): Promise<string> {
  const bytes = new TextEncoder().encode(SALT + normalizeEmail(raw));
  const hash = new Uint8Array(await crypto.subtle.digest('SHA-256', bytes));
  return Array.from(hash, (b) => b.toString(16).padStart(2, '0')).join('').slice(0, 32);
}

/** A day number (days since 1970-01-01) as 'YYYY-MM-DD'. */
export const isoDay = (day: number) => new Date(day * DAY_MS).toISOString().slice(0, 10);

/** Whether a change landed on `day` falls in `period` ("all", "2025", "2025H2"). */
export function inPeriod(day: number, period: string): boolean {
  if (period === 'all') return true;
  const d = new Date(day * DAY_MS);
  const y = String(d.getUTCFullYear());
  if (period.length === 4) return period === y;
  return period === `${y}H${d.getUTCMonth() < 6 ? 1 : 2}`;
}

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

/** Each unit's fraction of its change's lines: by the lines there, or equally where the landed commit
 * inserted none (cosh/review_feedback.py `unit_fracs`). */
export function unitFracs(units: Unit[]): number[] {
  const s = units.reduce((a, u) => a + u[1], 0);
  return units.map((u) => (s > 0 ? u[1] / s : 1 / units.length));
}

/** The addressed threads on a change, and all its reviewer threads. */
export const addressedOn = (c: ClRow) => c[4].reduce((s, f) => s + f[3], 0);
export const threadsOn = (c: ClRow) => c[4].reduce((s, f) => s + f[2], 0);
/** A unit's threads and addressed threads: those of the files whose threads count in it. */
function unitCounts(c: ClRow, i: number): [number, number] {
  let t = 0;
  let a = 0;
  for (const f of c[4]) if (f[4] === i) (t += f[2], a += f[3]);
  return [t, a];
}

/** The changes landed in `period` that have addressed labels: the ones every measure counts. */
export const clsIn = (p: Person, period: string) => p.cls.filter((c) => c[1] >= p.addrStart && inPeriod(c[1], period));

/** A 3-level directory and its parents, deepest first, then "" (all of them)
 * (cosh/review_feedback.py `dir_levels`). */
export function dirLevels(d: string): string[] {
  const p = d.split('/').filter(Boolean);
  const out: string[] = [];
  for (let k = Math.min(3, p.length); k > 0; k--) out.push(`${p.slice(0, k).join('/')}/`);
  out.push('');
  return out;
}

/** The half-year ("2026H2") of a day number. */
export function halfOf(day: number): string {
  const d = new Date(day * DAY_MS);
  return `${d.getUTCFullYear()}H${d.getUTCMonth() < 6 ? 1 : 2}`;
}

/** A person's own sums in the rate cells, keyed `half|directory`, per experience bin
 * (cosh/review_feedback.py `rate_cells` of their rows): what their peers' rates leave out. */
export type OwnCells = Map<string, RateCell[]>;

const ownCache = new WeakMap<Person, OwnCells>();

/** The person's own sums over their labelled changes, each change's lines and addressed threads
 * split over its directories by lines. */
export function ownCells(p: Person, peers: Pick<Peers, 'bin_edges' | 'bins'>): OwnCells {
  let own = ownCache.get(p);
  if (own) return own;
  own = new Map();
  const nb = peers.bins.length;
  for (const c of p.cls) {
    if (c[1] < p.addrStart) continue;
    const h = halfOf(c[1]);
    const b = xbin(peers.bin_edges, c[5]);
    const fracs = unitFracs(c[3]);
    c[3].forEach((u, i) => {
      const a = unitCounts(c, i)[1];
      for (const k of dirLevels(p.dirs[u[0]])) {
        const key = `${h}|${k}`;
        let v = own!.get(key);
        if (!v) own!.set(key, (v = Array.from({ length: nb }, (): RateCell => [0, 0, 0])));
        const x = v[b];
        x[0] += fracs[i];
        x[1] += c[2] * fracs[i];
        x[2] += a;
      }
    });
  }
  ownCache.set(p, own);
  return own;
}

/** The AFR of everyone's lines in half-year `h`, directory `k` and bin `b` less the person's own, where
 * that leaves `min_rate_cls` changes' worth (always, without `need`; cosh/review_feedback.py
 * `cell_rate`). */
function cellRate(peers: Pick<Peers, 'rates' | 'min_rate_cls'>, own: OwnCells | null, h: string, k: string,
  b: number, need = true): number | null {
  const x = peers.rates[h]?.[k]?.[b];
  if (!x) return null;
  let [n, lines, a] = x;
  const o = own?.get(`${h}|${k}`);
  if (o) {
    n -= o[b][0];
    lines -= o[b][1];
    a -= o[b][2];
  }
  return (n >= peers.min_rate_cls || !need) && lines > 0 ? 100 * a / lines : null;
}

const halvesCache = new WeakMap<object, string[]>();

/** The peers' AFR for lines in directory `d` landed in half-year `h` at experience bin `b`, the person's
 * own (`own`) left out: the directory's, else its parent's, up to everyone's that half-year, else
 * everyone's in the nearest earlier half-year with enough, else that half-year's anyway
 * (cosh/review_feedback.py `peer_rate`). */
export function peerRate(peers: Pick<Peers, 'rates' | 'min_rate_cls'>, own: OwnCells | null, h: string,
  d: string, b: number): number {
  for (const k of dirLevels(d).slice(0, -1)) {
    const v = cellRate(peers, own, h, k, b);
    if (v !== null) return v;
  }
  let hs = halvesCache.get(peers.rates);
  if (!hs) halvesCache.set(peers.rates, (hs = Object.keys(peers.rates).sort().reverse()));
  for (const hh of hs.filter((x) => x <= h)) {
    const v = cellRate(peers, own, hh, '', b);
    if (v !== null) return v;
  }
  return cellRate(peers, own, h, '', b, false) ?? 0;
}

/** The addressed threads each unit of a change would draw at its peers' AFR (cosh/review_feedback.py
 * `unit_expected`): its lines / 100 × the peers' rate (`peerRate`: the same directory, half-year and
 * experience, the person's own lines left out) × the scale. */
export function unitExpected(p: Person, peers: Peers, c: ClRow): number[] {
  const b = xbin(peers.bin_edges, c[5]);
  const own = ownCells(p, peers);
  const h = halfOf(c[1]);
  const fr_ = unitFracs(c[3]);
  return c[3].map((u, i) => (c[2] * fr_[i] / 100) * peerRate(peers, own, h, p.dirs[u[0]], b) * peers.scale);
}

export const expectedOn = (p: Person, peers: Peers, c: ClRow) => unitExpected(p, peers, c).reduce((a, b) => a + b, 0);

export interface Sums {
  cls: number;
  addressed: number;
  lines: number;
  expected: number;
}

/** Totals over `cs`, with the expected addressed threads. */
export function sums(p: Person, peers: Peers, cs: ClRow[]): Sums {
  const s = { cls: 0, addressed: 0, lines: 0, expected: 0 };
  for (const c of cs) {
    s.cls += 1;
    s.addressed += addressedOn(c);
    s.lines += c[2];
    s.expected += expectedOn(p, peers, c);
  }
  return s;
}

/** The feedback index of some totals (null: nothing expected). */
export const fiOf = (s: Sums) => (s.expected > 0 ? s.addressed / s.expected : null);
export const frOf = (s: Sums) => fr(s.addressed, s.lines);

/** Totals per experience bin of the person's labelled changes in `period`. */
export function binSums(p: Person, peers: Peers, period: string): Sums[] {
  const out = peers.bins.map(() => ({ cls: 0, addressed: 0, lines: 0, expected: 0 }));
  for (const c of clsIn(p, period)) {
    const s = out[xbin(peers.bin_edges, c[5])];
    s.cls += 1;
    s.addressed += addressedOn(c);
    s.lines += c[2];
    s.expected += expectedOn(p, peers, c);
  }
  return out;
}

/** When the person reached each experience bin, as [day, exact]: the first bin on their first
 * commit on main, the others when their first change in the bin landed. Exact when that change
 * was the bin's first commit; otherwise they got there earlier (commits outside the data), by
 * that day. null: no change of theirs in the bin. */
export function binReached(p: Person, edges: number[]): ([number, boolean] | null)[] {
  const out: ([number, boolean] | null)[] = Array.from({ length: edges.length + 1 }, () => null);
  for (const c of p.cls) {
    const b = xbin(edges, c[5]);
    if (out[b]) continue;
    out[b] = b === 0 && p.firstDay !== null ? [p.firstDay, true] : [c[1], c[5] === (b ? edges[b - 1] : 0)];
  }
  return out;
}

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
 * they reached the newer bin (`binReached`). AFRs under `fr_floor` count as it. null: fewer than
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
    typical: r0 && r1 ? pct(r1 / r0) : null, reached: binReached(p, peers.bin_edges)[to] };
}

// ---- Threads per change

/** The threads-per-change histogram's columns, by their fewest addressed threads: 0, 1–2, 3–5, 6–10, 11–20, 21+. */
export const THREAD_BIN_FROM = [0, 1, 3, 6, 11, 21];
export const THREAD_BINS = THREAD_BIN_FROM.length;
/** Column `b`'s fewest and most threads (null: no upper end). */
export const threadBinRange = (b: number): [number, number | null] =>
  [THREAD_BIN_FROM[b], b + 1 < THREAD_BINS ? THREAD_BIN_FROM[b + 1] - 1 : null];
export function threadBinLabel(b: number): string {
  const [lo, hi] = threadBinRange(b);
  return hi === null ? `${lo}+` : lo === hi ? String(lo) : `${lo}–${hi}`;
}
export function threadBin(c: ClRow): number {
  const n = addressedOn(c);
  let b = 0;
  while (b + 1 < THREAD_BINS && n >= THREAD_BIN_FROM[b + 1]) b++;
  return b;
}

/** The changes `clsIn` gives, only those in histogram column `bin` (null: all). */
const clsPicked = (p: Person, period: string, bin: number | null) =>
  clsIn(p, period).filter((c) => bin === null || threadBin(c) === bin);

/** The person's changes landed in `period` by how many addressed threads each drew. */
export function threadHistogram(p: Person, period: string): number[] {
  const out = new Array<number>(THREAD_BINS).fill(0);
  for (const c of clsIn(p, period)) out[threadBin(c)] += 1;
  return out;
}

// ---- Where your feedback comes from

/** Figures for one row of the person's directory table. */
export interface DirStats {
  /** Changes in it, each change once however many of its files and directories are below it. */
  cls: number;
  /** The changes' lines there: each change's lines times its fraction there (a file's share of the
   * landed commit's insertions). */
  lines: number;
  /** Reviewer threads there, addressed or not. */
  threads: number;
  addressed: number;
  /** Addressed threads expected there at the peers' AFR. */
  expected: number;
  /** The changes counted in `cls`, so that a group of entries can count each change once. */
  ids: Set<number>;
}

/** One change on a file, for the list under the file's row. */
export interface FileChange {
  cl: number;
  day: number;
  threads: number;
  addressed: number;
  /** The file's position in the change's files: the key into its link file (`LinkShard`). */
  entry: number;
}

/** A row of the person's tree: a directory (its own data's 3-level directories, their parents, and
 * the directories between them and the files that drew comments), a file that drew comments, or a
 * directory's "other files" (its lines that drew no comments). */
export interface DirNode extends DirStats {
  /** "d:" + path for a directory, "f:" + its directory + "|" + path for a file, "r:" + path for "other files". */
  key: string;
  kind: 'dir' | 'file' | 'rest';
  /** Full path; a file's in full, "other files" its directory's. */
  path: string;
  /** What the row shows: the last part of the path ("browser/", "view.cc"). */
  name: string;
  children: DirNode[];
  /** A file's changes, newest first. */
  changes?: FileChange[];
}

const stats = (): DirStats => ({ cls: 0, lines: 0, threads: 0, addressed: 0, expected: 0, ids: new Set() });

function addTo(s: DirStats, cl: number, lines: number, threads: number, a: number, exp: number) {
  s.lines += lines;
  s.threads += threads;
  s.addressed += a;
  s.expected += exp;
  if (!s.ids.has(cl)) (s.ids.add(cl), s.cls += 1);
}

/** Path prefixes of `path` ("a/b/c.cc" -> "a/", "a/b/"), and the last part. */
function pathParts(path: string): [string[], string] {
  const parts = path.split('/');
  const name = parts.pop()!;
  const dirs: string[] = [];
  let at = '';
  for (const x of parts) {
    if (!x) continue;
    at += `${x}/`;
    dirs.push(at);
  }
  return [dirs, name];
}

/** The person's changes in `period` as a tree, each level most changes first: directories down to the
 * files that drew reviewer threads, each directory's other lines in an "other files" row. A change's
 * lines go to its 3-level directories by the landed commit's insertions, and within one to its files
 * the same way; its threads go to their files. Each row's expected threads are its share of its
 * directory's. `bin` keeps only the changes in that threads-per-change column. */
export function dirTree(p: Person, peers: Peers, period: string, bin: number | null = null): DirNode[] {
  const nodes = new Map<string, DirNode>();
  const roots: DirNode[] = [];
  const node = (key: string, kind: DirNode['kind'], path: string, name: string, parent: DirNode | null) => {
    let n = nodes.get(key);
    if (!n) {
      nodes.set(key, (n = { key, kind, path, name, ...stats(), children: [] }));
      (parent ? parent.children : roots).push(n);
    }
    return n;
  };
  const dirNode = (path: string) => {
    let parent: DirNode | null = null;
    for (const d of pathParts(path.slice(0, -1) + '/x')[0]) parent = node(`d:${d}`, 'dir', d, pathParts(d.slice(0, -1))[1] + '/', parent);
    return parent!;
  };
  for (const c of clsPicked(p, period, bin)) {
    const fracs = unitFracs(c[3]);
    const exps = unitExpected(p, peers, c);
    c[3].forEach(([d, git], i) => {
      const dir = p.dirs[d];
      const lines = c[2] * fracs[i];
      const [threads, a] = unitCounts(c, i);
      // The directory and its parents.
      const top = dirNode(dir);
      for (const k of dirLevels(dir).slice(0, -1)) addTo(nodes.get(`d:${k}`)!, c[0], lines, threads, a, exps[i]);
      // Its files that drew comments, under the directories between, and its other lines.
      let restLines = lines;
      let restExp = exps[i];
      c[4].forEach((f, entry) => {
        if (f[4] !== i) return;
        const path = p.files[f[0]];
        const fl = git > 0 ? (lines * f[1]) / git : 0;
        const fe = git > 0 ? (exps[i] * f[1]) / git : 0;
        restLines -= fl;
        restExp -= fe;
        // A file under its directory keeps its path there; any other (the commit message, a file the
        // landed commit didn't change) sits directly under the directory, named in full.
        const under = path.startsWith(dir) && dir !== '(root)/';
        const rel = under ? path.slice(dir.length) : path;
        let parent = top;
        if (under) {
          for (const sub of pathParts(rel)[0]) {
            const full = dir + sub;
            parent = node(`d:${full}`, 'dir', full, pathParts(sub.slice(0, -1))[1] + '/', parent);
            addTo(parent, c[0], fl, f[2], f[3], fe);
          }
        }
        const leaf = node(`f:${parent.path}|${path}`, 'file', path, under ? pathParts(rel)[1] : path, parent);
        addTo(leaf, c[0], fl, f[2], f[3], fe);
        (leaf.changes ??= []).push({ cl: c[0], day: c[1], threads: f[2], addressed: f[3], entry });
      });
      if (restLines > 1e-9) addTo(node(`r:${dir}`, 'rest', dir, '', top), c[0], restLines, 0, 0, Math.max(restExp, 0));
    });
  }
  for (const n of nodes.values()) n.changes?.sort((a, b) => b.day - a.day || b.cl - a.cl);
  return roots;
}

/** One visible row of the person's directory table: a tree row, a level's smaller entries ("other"), or
 * one change under a file ("change"). */
export interface DirRowView {
  key: string;
  kind: 'dir' | 'file' | 'rest' | 'other' | 'change';
  depth: number;
  node?: DirNode;
  change?: FileChange;
  stats: DirStats;
  expandable: boolean;
  expanded: boolean;
  /** The AFR and index there, or null where the row has fewer than `minCls` changes (too few to say
   * much). */
  fr: number | null;
  fi: number | null;
  /** Entries in an "other" row. */
  count?: number;
}

/** The rows to show of `dirTree`'s tree, given which rows are open (`expanded`, by row key). Each
 * level lists its directories and files with at least `minCls` changes, most changes first, at most
 * `shown` of them, then "other files", and puts the rest in one "other" row that opens into them; a
 * level where none has `minCls` changes lists its first `shown` entries instead. Every directory
 * opens, and a file opens into its changes. Rows with fewer than `minCls` changes get no rate or index. */
export function dirRows(roots: DirNode[], expanded: ReadonlySet<string>, minCls: number, shown = 15): DirRowView[] {
  const out: DirRowView[] = [];
  const big = (s: DirStats) => s.cls >= minCls;
  const rate = (s: DirStats) => ({ fr: big(s) ? fr(s.addressed, s.lines) : null,
    fi: big(s) && s.expected > 0 ? s.addressed / s.expected : null });
  const order = (a: DirNode, b: DirNode) => (a.kind === 'rest' ? 1 : 0) - (b.kind === 'rest' ? 1 : 0) ||
    b.cls - a.cls || b.addressed - a.addressed || (a.path < b.path ? -1 : a.path > b.path ? 1 : 0);
  const emit = (n: DirNode, depth: number) => {
    const key = n.key;
    const expandable = n.kind === 'dir' ? n.children.length > 0 : n.kind === 'file';
    const open = expandable && expanded.has(key);
    out.push({ key, kind: n.kind, depth, node: n, stats: n, expandable, expanded: open, ...rate(n) });
    if (!open) return;
    if (n.kind === 'file') {
      for (const ch of n.changes ?? []) {
        out.push({ key: `c:${n.key}:${ch.cl}`, kind: 'change', depth: depth + 1, change: ch, expandable: false,
          expanded: false, fr: null, fi: null,
          stats: { cls: 1, lines: 0, threads: ch.threads, addressed: ch.addressed, expected: 0, ids: new Set([ch.cl]) } });
      }
      return;
    }
    group([...n.children].sort(order), depth + 1, key);
  };
  const group = (items: DirNode[], depth: number, parentKey: string) => {
    const rest = items.filter((n) => n.kind === 'rest');
    const entries = items.filter((n) => n.kind !== 'rest');
    const plain = !entries.some(big);
    const head = (plain ? entries : entries.filter(big)).slice(0, shown);
    const tail = entries.filter((n) => !head.includes(n));
    for (const n of head) emit(n, depth);
    if (tail.length) {
      const key = `o:${parentKey}`;
      const open = expanded.has(key);
      const ids = new Set<number>();
      for (const n of tail) for (const id of n.ids) ids.add(id);
      const s: DirStats = { cls: ids.size, ids, lines: tail.reduce((x, n) => x + n.lines, 0),
        threads: tail.reduce((x, n) => x + n.threads, 0), addressed: tail.reduce((x, n) => x + n.addressed, 0),
        expected: tail.reduce((x, n) => x + n.expected, 0) };
      out.push({ key, kind: 'other', depth, stats: s, expandable: true, expanded: open, count: tail.length, ...rate(s) });
      if (open) {
        for (const n of tail) emit(n, depth + 1);
      }
    }
    for (const n of rest) emit(n, depth);
  };
  group([...roots].sort(order), 0, 'root');
  return out;
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

const emptyStats = (): DirStats => ({ cls: 0, lines: 0, threads: 0, addressed: 0, expected: 0, ids: new Set() });

/** Everyone's directory table as a tree, with the person's changes in `period` (if any) added: each
 * unit to its directory, its parents, and to "rest of" or a level's "Other" where the table has no row
 * of its own for it. Parents add up their children, counting each change once, so the index of a row
 * is its addressed threads over its expected ones whether it is open or not. */
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
  for (const c of clsIn(p, period)) {
    const fracs = unitFracs(c[3]);
    const exps = unitExpected(p, peers, c);
    c[3].forEach(([d], i) => {
      const path = p.dirs[d];
      const [threads, a] = unitCounts(c, i);
      const lines = c[2] * fracs[i];
      const put = (n: TableNode) => addTo(n.you, c[0], lines, threads, a, exps[i]);
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
    });
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

// ---- Links to comments

/** A Gerrit link to one comment (or to the change, without a uuid). The parts
 * come from data, so they are encoded. */
export function commentUrl(cl: number, uuid?: string): string {
  const base = `${GERRIT}/c/chromium/src/+/${Math.trunc(cl)}`;
  return uuid ? `${base}/comment/${encodeURIComponent(uuid)}/` : base;
}

/** A change's comment links on one file, from the link files: [comment id, tone score or null], oldest
 * first; empty when the half-year has no links (before `links_from`). */
export function linksOf(links: Map<number, LinkShard['cls'][string]>, cl: number, entry: number): [string, number | null][] {
  const e = links.get(cl)?.find((x) => x[0] === entry);
  return e ? e[1].map((x) => (typeof x === 'string' ? [x, null] : [x[0], x[1]])) : [];
}

/** The link files merged: change number -> its entries. */
export function mergeLinks(shards: (LinkShard | null)[]): Map<number, LinkShard['cls'][string]> {
  const out = new Map<number, LinkShard['cls'][string]>();
  for (const s of shards) for (const [n, e] of Object.entries(s?.cls ?? {})) out.set(Number(n), e);
  return out;
}

// ---- Merging a person's files

/** balance_growth.size10: ten log-spaced size buckets of changed lines, <4, <8, …, <1024, 1024+. */
export const size10 = (lines: number) => Math.min(9, Math.max(0, 30 - Math.clz32(Math.max(lines, 1))));

/** balance_analysis.dir_of(path, 3): a file's directory, three levels deep. */
export function dirOf(path: string): string {
  const parts = path.split('/').slice(0, -1);
  return parts.length ? `${parts.slice(0, 3).join('/')}/` : '(root)/';
}

/** The half-year files merged into one person, names re-indexed and deltas undone. */
export function buildPerson(top: Top, shards: Shard[], peers: Pick<Peers, 'addr_start'>): Person {
  const tables = { dirs: new Map<string, number>(), files: new Map<string, number>() };
  const at = (t: Map<string, number>, name: string) => {
    let i = t.get(name);
    if (i === undefined) t.set(name, (i = t.size));
    return i;
  };
  const cls: ClRow[] = [];
  for (const s of shards) {
    const d = s.dirs.map((x) => at(tables.dirs, x));
    const f = s.files.map((x) => at(tables.files, x));
    let n = 0;
    let day = 0;
    for (const [dn, dd, lines, prior, fileUnits, fileFb] of s.cls) {
      n += dn;
      day += dd;
      const local: [number, number][] = typeof fileUnits === 'number' ? [[fileUnits, lines]] : fileUnits;
      const units = local.map((u): Unit => [d[u[0]], u[1]]);
      // A file's threads count in its 3-level directory when that is one of the units, else in the first.
      const pos = new Map(local.map((u, i) => [s.dirs[u[0]], i]));
      const files = (fileFb ?? []).map(([fi, fl, t, a]): FileFb => {
        const path = s.files[fi];
        const own = path && !path.startsWith('/') ? pos.get(dirOf(path)) : undefined;
        return [f[fi], fl, t, a, own ?? 0];
      });
      cls.push([n, day, lines, units, files, prior]);
    }
  }
  cls.sort((a, b) => a[1] - b[1] || a[0] - b[0]);
  return { addrStart: peers.addr_start, first: top.first, firstDay: top.first_day, org: top.org,
    dirs: [...tables.dirs.keys()], files: [...tables.files.keys()], cls };
}
