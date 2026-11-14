// The Feedback Index page's data and arithmetic (feedback-index.html,
// docs/review-feedback.md), kept apart from the DOM so unit tests can run it.
// cosh/review_feedback.py writes one file per person, named by `personKey` of their
// address, and peers.json with what the page compares a person with.
//
// The addressed feedback rate (AFR) of a set of changes is their addressed reviewer
// threads per 100 new or changed lines (insertions). The feedback index (FI) is a person's AFR
// over their peers': for each directory a change wrote lines in, the AFR of
// everyone else's lines there in the same half-year at the same experience (CLs
// landed on main, in power-of-two bins), or the parent directory's where that is
// too thin, optionally with a factor for the org (`Norm`).

/** What the feedback index compares with: experience (e), directory (d) and org (o), in that order. */
export type Norm = '' | 'e' | 'd' | 'ed' | 'o' | 'eo' | 'do' | 'edo';

/** A reviewer thread, as the page holds it: [comment uuid (empty when there's
 * no excerpt: link the change instead), file index (-1: the file isn't kept,
 * in half-years before the comment text), days after the change landed,
 * addressed (null: not labelled), directory index, excerpt and tone score
 * (from the comment files, only where comment text is collected and
 * scored)]. */
export type Thread = [string, number, number | null, 0 | 1 | null, number, string?, number?];
/** [directory index, share of the change (lines + files), the owner's earlier commits there,
 * lines there (insertions, in the landed commit)]. */
export type Unit = [number, number, number, number];
/** A change, as the page holds it: [change number, day landed (days since
 * 1970), lines (Gerrit's insertions), units, threads, org index,
 * the owner's earlier commits on main]. */
export type ClRow = [number, number, number, Unit[], Thread[], number, number];

/** A change in a half-year file (cosh/review_feedback.py `shard`): [change
 * number, day landed, lines, expected threads by size and directory, expected
 * addressed by size and directory (both unused here), units, threads, org
 * index, earlier commits on main]. A unit is [directory, share, earlier
 * commits there, lines], or [directory, earlier commits there] for a change
 * wholly in one directory. Threads are [file, days after landing,
 * addressed], their directory told by the file, or [file, days, addressed,
 * unit] for a file that has moved since; in a file with `counts`,
 * [threads, addressed] per unit instead. */
export type FileRow = [number, number, number, number, number, FileUnit[], FileThread[] | [number, number][], number, number];
type FileUnit = [number, number] | [number, number, number, number];
type FileThread = [number, number | null, 0 | 1 | null] | [number, number | null, 0 | 1 | null, number];

/** u/<key>.json: who the person is and which half-year files they have. */
export interface Top {
  v: 5;
  first: string | null;
  /** First commit on main, as a day number. */
  first_day: number | null;
  halves: string[];
}

/** comments/<half>/<key>.json, for each half-year file without `counts`, read
 * only for the comment list (a separate step writes it:
 * cosh/review_feedback.py --part comments): per change number, one entry per
 * thread in the half-year file's order: 0 without text, else [comment uuid,
 * excerpt, tone score (−1 .. +1) where scored]. */
export interface CommentShard {
  cls: Record<string, (0 | [string, string] | [string, string, number])[]>;
}

/** <half>/<key>.json: one half-year's changes, with names listed once. */
export interface Shard {
  dirs: string[];
  files: string[];
  orgs: string[];
  /** 1: the changes carry thread counts per directory, not each thread. */
  counts?: 1;
  cls: FileRow[];
}

/** A person's files merged. */
export interface Person {
  /** The first day (days since 1970) of the changes with addressed labels. */
  addrStart: number;
  first: string | null;
  firstDay: number | null;
  dirs: string[];
  files: string[];
  orgs: string[];
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

/** peers.json (cosh/review_feedback.py, version 8). */
export interface Peers {
  v: 8;
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
  norms: Norm[];
  /** The median AFR per experience bin (null: too few people), and everyone's: the opening chart's
   * line, for comparisons (the index uses `rates`). */
  ref_bin: (number | null)[];
  ref_all: number;
  /** A directory (3 levels, 2, 1, or "" for all) gets its own peers' rate at an experience bin with
   * this many changes' worth there. */
  min_rate_cls: number;
  /** A directory gets a row of its own in everyone's directory table with this many changes. */
  min_dir_cls: number;
  /** Per half-year, per directory, the sums of everyone's lines there per experience bin, then at any
   * experience (the last); null where too few (`min_rate_cls`; "" always has them). The peers' rate is
   * these less the person's own (`peerRate`). */
  rates: Record<string, Record<string, (RateCell | null)[]>>;
  /** Per norm without "o": the expected threads' scale, which makes the median contributor's index 1. */
  scale: Record<'' | 'e' | 'd' | 'ed', number>;
  /** Org factors per norm without "o"; "*" for the smaller orgs. */
  f_org: Record<'' | 'e' | 'd' | 'ed', Record<string, number>>;
  /** Everyone's directory table, parents before their children, each level by lines. */
  dir_table: DirTableEntry[];
  /** Per experience bin, the spread of people's AFR there. */
  fr_bins: Dist[];
  /** Norm -> period -> the spread of people's feedback index. */
  fi: Record<string, Record<string, Dist>>;
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
  /** Everyone's feedback index under `fi_norm` over all the data: how many, quantiles, and a
   * smoothed curve of [index, % of people per 0.1 of log2]. */
  fi_norm: Norm;
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

/** Each unit's fraction of its change's lines: by the lines there, or by share
 * where the landed commit changed none (cosh/review_feedback.py `unit_fracs`). */
export function unitFracs(units: Unit[]): number[] {
  const s = units.reduce((a, u) => a + u[3], 0);
  return units.map((u) => (s > 0 ? u[3] / s : u[1]));
}

/** Whether a thread counts as addressed. */
const addressed = (t: Thread) => (t[3] ? 1 : 0);
/** The addressed threads on a change. */
export const addressedOn = (c: ClRow) => c[4].reduce((s, t) => s + addressed(t), 0);

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

/** A person's own sums in the rate cells, keyed `half|directory`, per experience bin and then at any
 * experience (cosh/review_feedback.py `rate_cells` of their rows): what their peers' rates leave out. */
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
    const b = xbin(peers.bin_edges, c[6]);
    const fracs = unitFracs(c[3]);
    c[3].forEach((u, i) => {
      const a = c[4].reduce((s, t) => s + (t[4] === u[0] ? addressed(t) : 0), 0);
      for (const k of dirLevels(p.dirs[u[0]])) {
        const key = `${h}|${k}`;
        let v = own!.get(key);
        if (!v) own!.set(key, (v = Array.from({ length: nb + 1 }, (): RateCell => [0, 0, 0])));
        for (const x of [v[b], v[nb]]) {
          x[0] += fracs[i];
          x[1] += c[2] * fracs[i];
          x[2] += a;
        }
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

/** The peers' AFR for lines in directory `d` landed in half-year `h` at experience bin `b`
 * (`bins.length`: any experience), the person's own (`own`) left out: the directory's, else its
 * parent's, up to everyone's that half-year, else everyone's in the nearest earlier half-year with
 * enough, else that half-year's anyway (cosh/review_feedback.py `peer_rate`). */
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

/** The addressed threads each unit of a change would draw at its peers' AFR, under `norm`
 * (cosh/review_feedback.py `unit_expected`): its lines / 100 × the peers' rate (`peerRate`: the same
 * half-year, the person's own lines left out) in its directory ("d") at the change's experience ("e")
 * × the norm's scale × the org's factor ("o"). */
export function unitExpected(p: Person, peers: Peers, c: ClRow, norm: Norm): number[] {
  const base = norm.replace('o', '') as '' | 'e' | 'd' | 'ed';
  let s = peers.scale[base];
  if (norm.includes('o')) {
    const t = peers.f_org[base];
    s *= t[p.orgs[c[5]]] ?? t['*'] ?? 1;
  }
  const b = norm.includes('e') ? xbin(peers.bin_edges, c[6]) : peers.bins.length;
  const own = ownCells(p, peers);
  const h = halfOf(c[1]);
  const fr_ = unitFracs(c[3]);
  return c[3].map((u, i) => (c[2] * fr_[i] / 100) * peerRate(peers, own, h, norm.includes('d') ? p.dirs[u[0]] : '', b) * s);
}

export const expectedOn = (p: Person, peers: Peers, c: ClRow, norm: Norm) =>
  unitExpected(p, peers, c, norm).reduce((a, b) => a + b, 0);

export interface Sums {
  cls: number;
  addressed: number;
  lines: number;
  expected: number;
}

/** Totals over `cs`, with the expected addressed threads under `norm`. */
export function sums(p: Person, peers: Peers, cs: ClRow[], norm: Norm): Sums {
  const s = { cls: 0, addressed: 0, lines: 0, expected: 0 };
  for (const c of cs) {
    s.cls += 1;
    s.addressed += addressedOn(c);
    s.lines += c[2];
    s.expected += expectedOn(p, peers, c, norm);
  }
  return s;
}

/** The feedback index of some totals (null: nothing expected). */
export const fiOf = (s: Sums) => (s.expected > 0 ? s.addressed / s.expected : null);
export const frOf = (s: Sums) => fr(s.addressed, s.lines);

/** Totals per experience bin of the person's labelled changes in `period`. */
export function binSums(p: Person, peers: Peers, period: string, norm: Norm): Sums[] {
  const out = peers.bins.map(() => ({ cls: 0, addressed: 0, lines: 0, expected: 0 }));
  for (const c of clsIn(p, period)) {
    const s = out[xbin(peers.bin_edges, c[6])];
    s.cls += 1;
    s.addressed += addressedOn(c);
    s.lines += c[2];
    s.expected += expectedOn(p, peers, c, norm);
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
    const b = xbin(edges, c[6]);
    if (out[b]) continue;
    out[b] = b === 0 && p.firstDay !== null ? [p.firstDay, true] : [c[1], c[6] === (b ? edges[b - 1] : 0)];
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

// ---- Directories

/** Figures for one directory, or for a directory's own files ("rest of"). */
export interface DirStats {
  /** Changes touching it, each change once however many directories below it the change touches. */
  cls: number;
  /** The changes' lines there: each change's lines times its fraction there. */
  lines: number;
  /** Reviewer threads there, addressed or not. */
  threads: number;
  addressed: number;
  /** Addressed threads expected there at the peers' AFR (the norm chosen). */
  expected: number;
  /** The person's earlier commits there before their latest change in the period:
   * for a parent, the most in any one directory below it. */
  prior: number;
  /** The changes counted in `cls`, so that a group of entries can count each change once. */
  ids: Set<number>;
}

/** A directory in the tree: the data's 3-level directories and their parents. */
export interface DirNode extends DirStats {
  /** Full path, ending in "/". */
  path: string;
  /** The last part of the path, e.g. "browser/". */
  name: string;
  children: DirNode[];
  /** Files directly in this directory, when it also has subdirectories. */
  own: DirStats | null;
}

const dirOrder = (a: DirNode, b: DirNode) =>
  b.cls - a.cls || b.addressed - a.addressed || (a.path < b.path ? -1 : a.path > b.path ? 1 : 0);

/** The person's directories in `period` as a tree, each level most changes
 * first. A parent adds up its subdirectories (and own files), counting each
 * change once. `bin` keeps only the changes in that threads-per-change column. */
export function dirTree(p: Person, peers: Peers, period: string, norm: Norm, bin: number | null = null): DirNode[] {
  const nodes = new Map<string, DirNode>();
  const roots: DirNode[] = [];
  const stats = (): DirStats => ({ cls: 0, lines: 0, threads: 0, addressed: 0, expected: 0, prior: 0, ids: new Set() });
  const add = (s: DirStats, lines: number, a: number, exp: number, prior: number, t: number) => {
    s.lines += lines;
    s.threads += t;
    s.addressed += a;
    s.expected += exp;
    s.prior = Math.max(s.prior, prior);
  };
  for (const c of clsPicked(p, period, bin)) {
    const per = new Map<number, number>();
    const every = new Map<number, number>();
    for (const t of c[4]) {
      per.set(t[4], (per.get(t[4]) ?? 0) + addressed(t));
      every.set(t[4], (every.get(t[4]) ?? 0) + 1);
    }
    const fracs = unitFracs(c[3]);
    const exps = unitExpected(p, peers, c, norm);
    const touched = new Set<DirNode>();
    c[3].forEach(([d, , prior], i) => {
      const path = p.dirs[d];
      const lines = c[2] * fracs[i];
      const a = per.get(d) ?? 0;
      const all = every.get(d) ?? 0;
      let parent: DirNode | null = null;
      for (let at = 0; at < path.length;) {
        const slash = path.indexOf('/', at);
        const end = slash < 0 ? path.length : slash + 1;
        const key = path.slice(0, end);
        let n = nodes.get(key);
        if (!n) {
          nodes.set(key, (n = { path: key, name: path.slice(at, end), ...stats(), children: [], own: null }));
          (parent ? parent.children : roots).push(n);
        }
        add(n, lines, a, exps[i], prior, all);
        touched.add(n);
        if (end === path.length) {
          n.own ??= stats();
          if (!n.own.ids.has(c[0])) (n.own.cls += 1, n.own.ids.add(c[0]));
          add(n.own, lines, a, exps[i], prior, all);
        }
        parent = n;
        at = end;
      }
    });
    for (const n of touched) (n.cls += 1, n.ids.add(c[0]));
  }
  for (const n of nodes.values()) {
    n.children.sort(dirOrder);
    // Without subdirectories, its own files are the whole directory.
    if (!n.children.length) n.own = null;
  }
  return roots.sort(dirOrder);
}

/** One visible row of the directory table: a directory, a directory's own
 * files ("rest of"), or a level's other entries ("Other"). */
export interface DirRowView {
  key: string;
  kind: 'dir' | 'rest' | 'other';
  depth: number;
  node?: DirNode;
  stats: DirStats;
  expandable: boolean;
  expanded: boolean;
  /** The AFR and index there, or null where the row has fewer than
   * `minCls` changes (too few to say much). */
  fr: number | null;
  fi: number | null;
  /** Entries in an "Other" row. */
  count?: number;
}

type DirItem = { kind: 'dir' | 'rest'; node: DirNode; stats: DirStats };

/** The rows to show of `dirTree`'s tree, given which rows are open
 * (`expanded`, by row key). Each level lists its entries with at least
 * `minCls` changes, at most `shown` of them, and puts the rest in one "Other"
 * row that opens into them; a level where none has `minCls` changes lists
 * its first `shown` entries instead. Any directory with subdirectories opens
 * (into them plus a "rest of" row for its own files), however small. Rows with
 * fewer than `minCls` changes get no rate or index. */
export function dirRows(roots: DirNode[], expanded: ReadonlySet<string>, minCls: number, shown = 15): DirRowView[] {
  const out: DirRowView[] = [];
  const big = (s: DirStats) => s.cls >= minCls;
  const row = (r: Omit<DirRowView, 'fr' | 'fi'>): DirRowView => ({ ...r,
    fr: big(r.stats) ? fr(r.stats.addressed, r.stats.lines) : null,
    fi: big(r.stats) && r.stats.expected > 0 ? r.stats.addressed / r.stats.expected : null });
  const order = (a: DirItem, b: DirItem) => b.stats.cls - a.stats.cls || b.stats.addressed - a.stats.addressed ||
    (a.kind === b.kind ? (a.node.path < b.node.path ? -1 : 1) : a.kind === 'dir' ? -1 : 1);
  const emit = (it: DirItem, depth: number) => {
    if (it.kind === 'rest') {
      out.push(row({ key: `r:${it.node.path}`, kind: 'rest', depth, node: it.node, stats: it.stats, expandable: false, expanded: false }));
      return;
    }
    const n = it.node;
    const key = `d:${n.path}`;
    const expandable = n.children.length > 0;
    const open = expandable && expanded.has(key);
    out.push(row({ key, kind: 'dir', depth, node: n, stats: n, expandable, expanded: open }));
    if (!open) return;
    const items: DirItem[] = n.children.map((c) => ({ kind: 'dir', node: c, stats: c }));
    if (n.own) items.push({ kind: 'rest', node: n, stats: n.own });
    group(items.sort(order), depth + 1, key, !items.some((it) => big(it.stats)));
  };
  // `plain`: list the first `shown` entries, whatever their size.
  const group = (items: DirItem[], depth: number, parentKey: string, plain: boolean) => {
    const head = (plain ? items : items.filter((it) => big(it.stats))).slice(0, shown);
    const tail = items.filter((it) => !head.includes(it));
    for (const it of head) emit(it, depth);
    if (!tail.length) return;
    const key = `o:${parentKey}`;
    const open = expanded.has(key);
    const ids = new Set<number>();
    for (const it of tail) for (const id of it.stats.ids) ids.add(id);
    out.push(row({
      key, kind: 'other', depth, expandable: true, expanded: open, count: tail.length,
      stats: {
        cls: ids.size,
        ids,
        lines: tail.reduce((s, it) => s + it.stats.lines, 0),
        threads: tail.reduce((s, it) => s + it.stats.threads, 0),
        addressed: tail.reduce((s, it) => s + it.stats.addressed, 0),
        expected: tail.reduce((s, it) => s + it.stats.expected, 0),
        prior: Math.max(...tail.map((it) => it.stats.prior)),
      },
    }));
    if (open) group(tail, depth + 1, key, true);
  };
  const top = roots.map((n): DirItem => ({ kind: 'dir', node: n, stats: n })).sort(order);
  group(top, 0, 'root', !top.some((it) => big(it.stats)));
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

const emptyStats = (): DirStats => ({ cls: 0, lines: 0, threads: 0, addressed: 0, expected: 0, prior: 0, ids: new Set() });

/** Everyone's directory table as a tree, with the person's changes in `period` (if any) added under
 * `norm`: each unit to its directory, its parents, and to "rest of" or a level's "Other" where the
 * table has no row of its own for it. Parents add up their children, counting each change once, so
 * the index of a row is its addressed threads over its expected ones whether it is open or not. */
export function dirTable(peers: Peers, p: Person | null, period: string, norm: Norm): TableNode[] {
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
  const add = (n: TableNode, cl: number, lines: number, threads: number, a: number, exp: number) => {
    const s = n.you;
    s.lines += lines;
    s.threads += threads;
    s.addressed += a;
    s.expected += exp;
    if (!s.ids.has(cl)) (s.ids.add(cl), s.cls += 1);
  };
  for (const c of clsIn(p, period)) {
    const per = new Map<number, [number, number]>();
    for (const t of c[4]) {
      const x = per.get(t[4]) ?? [0, 0];
      x[0] += 1;
      x[1] += addressed(t);
      per.set(t[4], x);
    }
    const fracs = unitFracs(c[3]);
    const exps = unitExpected(p, peers, c, norm);
    c[3].forEach(([d], i) => {
      const path = p.dirs[d];
      const [threads, a] = per.get(d) ?? [0, 0];
      const lines = c[2] * fracs[i];
      const put = (n: TableNode) => add(n, c[0], lines, threads, a, exps[i]);
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

// ---- Comments

export interface ThreadRow {
  cl: number;
  uuid: string;
  file: string;
  /** Day the thread started, or the change landed when unknown. */
  day: number;
  dir: number;
  text: string | null;
  /** The comment's tone score, −1 .. +1, where it was scored. */
  score: number | null;
  /** Set on a row that stands for this many threads in one directory of a
   * change, from a half-year whose files keep only counts (no file or day). */
  count?: number;
}

/** Addressed reviewer threads on the changes landed in `period`, newest
 * first, optionally only in directories under `dir` (a path prefix such as
 * "chrome/" or "chrome/browser/ui/"), and only on the changes in
 * threads-per-change column `bin`. Threads kept only as counts come as one
 * row per change and directory. */
export function threadRows(p: Person, period: string, dir: string | null, bin: number | null = null): ThreadRow[] {
  const out: ThreadRow[] = [];
  for (const c of clsPicked(p, period, bin)) {
    const groups = new Map<number, ThreadRow>();
    for (const t of c[4]) {
      if (!t[3]) continue;
      if (dir !== null && !p.dirs[t[4]].startsWith(dir)) continue;
      if (t[1] < 0) {
        const g = groups.get(t[4]);
        if (g) g.count! += 1;
        else groups.set(t[4], { cl: c[0], uuid: '', file: p.dirs[t[4]], day: c[1], dir: t[4], text: null, score: null, count: 1 });
        continue;
      }
      out.push({ cl: c[0], uuid: t[0], file: p.files[t[1]], day: c[1] + (t[2] ?? 0), dir: t[4],
        text: t[5] ?? null, score: t[6] ?? null });
    }
    out.push(...groups.values());
  }
  return out.sort((a, b) => b.day - a.day || b.cl - a.cl);
}

/** How many threads rows stand for. */
export const threadsIn = (rows: ThreadRow[]) => rows.reduce((s, r) => s + (r.count ?? 1), 0);

/** A Gerrit link to one comment (or to the change, without a uuid). The parts
 * come from data, so they are encoded. */
export function commentUrl(cl: number, uuid?: string): string {
  const base = `${GERRIT}/c/chromium/src/+/${Math.trunc(cl)}`;
  return uuid ? `${base}/comment/${encodeURIComponent(uuid)}/` : base;
}

// ---- Merging a person's files

/** balance_growth.size10: ten log-spaced size buckets of changed lines, <4, <8, …, <1024, 1024+. */
export const size10 = (lines: number) => Math.min(9, Math.max(0, 30 - Math.clz32(Math.max(lines, 1))));

/** balance_analysis.dir_of(path, 3): a file's directory, three levels deep. */
export function dirOf(path: string): string {
  const parts = path.split('/').slice(0, -1);
  return parts.length ? `${parts.slice(0, 3).join('/')}/` : '(root)/';
}

/** The half-year files merged into one person, names re-indexed. `comments`
 * has each shard's comment file, if any (missing ones leave the threads
 * without text). */
export function buildPerson(top: Top, shards: Shard[], peers: Pick<Peers, 'addr_start'>,
  comments: (CommentShard | null)[] = []): Person {
  const tables = { dirs: new Map<string, number>(), files: new Map<string, number>(), orgs: new Map<string, number>() };
  const at = (t: Map<string, number>, name: string) => {
    let i = t.get(name);
    if (i === undefined) t.set(name, (i = t.size));
    return i;
  };
  const cls: ClRow[] = [];
  shards.forEach((s, si) => {
    const com = comments[si]?.cls ?? {};
    const d = s.dirs.map((x) => at(tables.dirs, x));
    const f = s.files.map((x) => at(tables.files, x));
    const o = s.orgs.map((x) => at(tables.orgs, x));
    for (const [n, day, lines, , , fileUnits, fileThreads, org, prior] of s.cls) {
      const units = fileUnits.map((u): Unit => (u.length === 2 ? [d[u[0]], 1, u[1], lines] : [d[u[0]], u[1], u[2], u[3]]));
      const threads: Thread[] = [];
      if (s.counts) {
        // Counts per unit: as many threads in each directory, without their files or days.
        (fileThreads as [number, number][]).forEach(([all, addr], i) => {
          for (let k = 0; k < all; k++) threads.push(['', -1, null, k < addr ? 1 : 0, units[i][0]]);
        });
      } else {
        // A thread's directory is its file's, if the change has a unit there, else the first unit's.
        const unitDirs = new Map(fileUnits.map((u) => [s.dirs[u[0]], d[u[0]]]));
        // The two files come from separate steps: a change whose thread count differs gets no text.
        const listed = com[String(n)] ?? [];
        const texts = listed.length === fileThreads.length ? listed : [];
        (fileThreads as FileThread[]).forEach((t, ti) => {
          const path = s.files[t[0]];
          const own = t.length > 3 ? units[t[3]!][0]
            : path && !path.startsWith('/') ? unitDirs.get(dirOf(path)) : undefined;
          const c = texts[ti];
          const r: Thread = [c ? c[0] : '', f[t[0]], t[1], t[2], own ?? units[0][0]];
          if (c) {
            r.push(c[1]);
            if (c.length > 2) r.push(c[2]);
          }
          threads.push(r);
        });
      }
      cls.push([n, day, lines, units, threads, o[org], prior]);
    }
  });
  cls.sort((a, b) => a[1] - b[1] || a[0] - b[0]);
  return { addrStart: peers.addr_start, first: top.first, firstDay: top.first_day,
    dirs: [...tables.dirs.keys()], files: [...tables.files.keys()], orgs: [...tables.orgs.keys()], cls };
}

/** The org most of `cs` are attributed to (ties: the first seen). */
export function usualOrg(p: Person, cs: ClRow[]): string | null {
  const n = new Map<number, number>();
  for (const c of cs) n.set(c[5], (n.get(c[5]) ?? 0) + 1);
  let best: number | null = null;
  for (const [o, k] of n) if (best === null || k > n.get(best)!) best = o;
  return best === null ? null : p.orgs[best];
}
