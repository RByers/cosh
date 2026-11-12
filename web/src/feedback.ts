// The Review Feedback page's data and arithmetic (feedback-index.html,
// docs/review-feedback.md), kept apart from the DOM so unit tests can run it.
// scripts/review_feedback.py writes one file per person, named by `personKey`
// of their address, and peers.json with every peer group's percentiles.

/** What counts (every reviewer thread, or only addressed ones) and what it is
 * set against (n: changes; s: the 2023–24 norm for the size; d: for the size
 * and directory). */
export type Kind = 't' | 'a';
export type Corr = 'n' | 's' | 'd';
export type Metric = `${Kind}${Corr}`;

/** Peers always have the same tenure, by one of three measures: years since
 * the first commit on main, earlier commits on main, or experience in each
 * directory (everyone measured against what authors drew at the same number of
 * earlier commits in the directory). */
export type TenureBy = 'time' | 'changes' | 'dir';
/** Which authors of that tenure: everyone, Google, or everyone outside Google. */
export type PeerOrg = 'all' | 'google' | 'nongoogle';

export interface PeriodVals {
  cls: number;
  threads: number;
  /** Changes with addressed labels (landed from peers.json's addr_start), and their addressed threads. */
  acls: number;
  addressed: number;
  /** Tenure band at the middle of the period's changes, null if unknown. */
  ten: string | null;
  /** Earlier commits on main at the middle of the period's changes, and its band. */
  prior: number;
  chg: string;
  /** The org most of the period's changes are attributed to. */
  org: string;
  /** Enough changes to count among peers; for the addressed measures, enough labelled ones. */
  ok: boolean;
  ok_a: boolean;
  /** The measure; and the same against the directory-experience norm. */
  v: Record<Metric, number | null>;
  x: Record<Metric, number | null>;
}

/** [comment uuid (empty when there's no excerpt: link the change instead),
 * file index, days after the change landed, addressed (null: not labelled),
 * directory index, excerpt (only where comment text is collected)]. */
export type Thread = [string, number, number | null, 0 | 1 | null, number, string?];
/** [directory index, share of the change's lines, the owner's earlier commits there,
 * lines changed there (added + deleted, in the landed commit; missing in older files)]. */
export type Unit = [number, number, number, number?];
/** [change number, day landed (days since 1970), lines, expected threads by
 * size, by size and directory, expected addressed by size, by size and
 * directory, units, threads, org index, the owner's earlier commits on main]. */
export type ClRow = [number, number, number, number, number, number, number, Unit[], Thread[], number, number];

/** Tone received, with the person's tenure bands at the end of the tone year. */
type Tone = { received: number; praise: number; share: number | null; ten: string | null; chg: string | null };
type Praise = [number, string, number, string][];

/** u/<key>.json: who the person is and which half-year files they have. */
export interface Top {
  v: 3;
  first: string | null;
  /** First commit on main, as a day number. */
  first_day: number | null;
  halves: string[];
  tone: Tone;
  /** [change number, uuid, day, excerpt], newest first. */
  praise: Praise;
}

/** <half>/<key>.json: one half-year's changes, with names listed once. */
export interface Shard {
  dirs: string[];
  files: string[];
  orgs: string[];
  cls: ClRow[];
}

/** A person's files merged, with every period's values. */
export interface Person {
  /** The first day (days since 1970) of the changes the addressed measures count. */
  addrStart: number;
  first: string | null;
  firstDay: number | null;
  periods: Record<string, PeriodVals>;
  tone: Tone;
  praise: Praise;
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
  /** Quantiles at 0, 5, …, 100%; null when nobody is in the group. */
  q: number[] | null;
}

/** The counts peers.json has percentiles of. */
export type CountField = 'cls' | 'threads' | 'acls' | 'addressed';

export interface Band extends Dist {
  /** Everyone's feedback in the band, pooled, and that relative to everyone's overall. */
  pooled: number | null;
  rel: number | null;
}

export interface Peers {
  generated: string;
  /** The changes covered, as day numbers: from `start` up to (not including) `end`. The
   * addressed measures count only changes from `addr_start`, where the labels begin. */
  start: number;
  end: number;
  addr_start: number;
  periods: string[];
  metrics: Metric[];
  tenure: string[];
  changes: string[];
  xp: string[];
  min_peers: number;
  min_cls: number;
  min_exp: number;
  min_received: number;
  tone_weeks: [string, string];
  dist: Record<string, Record<string, Record<Metric, Dist>>>;
  /** Period -> group -> the same peers' changes landed and reviewer threads (acls,
   * addressed: labelled changes and addressed threads, for the addressed measures). */
  counts?: Record<string, Record<string, Record<CountField, Dist>>>;
  bands: Record<string, Record<Metric, Band[]>>;
  tone: Record<string, Dist>;
  /** The opening card. Tenure bins of the cohort curves, in years, and the
   * fewest people a point stands for. */
  cohort_step: number;
  /** The first year whose newcomers have Gerrit data from their start. */
  cohort_from: number;
  min_cohort: number;
  /** Group -> measure -> year of first commit -> [tenure bin start, median, people]. */
  cohorts: Record<string, Record<Metric, Record<string, [number, number, number][]>>>;
  /** The histogram's bin edges, as ratios of a year's value to the year
   * before's, each paired with its reciprocal: len + 1 bins, from below the
   * first edge to the last edge and up. */
  change_ratios: number[];
  /** Group -> measure -> year-over-year changes: counts per bin, and the
   * median as % less feedback than the year before. */
  change: Record<string, Record<Metric, { n: number; people: number; median: number | null; counts: number[] }>>;
  /** A half-year counts towards a cohort curve with this many changes. */
  min_cohort_cls: number;
  /** The opening card's bar charts (scripts/review_feedback.py, median_breakdowns):
   * per "Peers" org and measure, the median contributor's value and how many
   * contributors, by size bucket (`size_labels`, changed lines) and by directory
   * (`dir_names`). A contributor counts with `min_cell_cls` changes there. */
  size_labels?: string[];
  by_size?: Record<string, Record<Metric, MedianBar[]>>;
  dir_names?: string[];
  by_dir?: Record<string, Record<Metric, MedianBar[]>>;
  min_cell_cls?: number;
  /** All against addressed feedback by tenure (`kind_labels`, years since the
   * first commit): per "Peers" org and adjustment, [median of all threads,
   * median of addressed threads (null: too few), contributor half-years], and
   * the share of threads addressed per bin (`kind_share`). */
  kind_labels?: string[];
  kinds?: Record<string, Record<Corr, [number | null, number | null, number][]>>;
  kind_share?: Record<string, (number | null)[]>;
  /** The three tenure measures compared: per "Peers" org and measure, the
   * pooled feedback per band relative to all bands ([value, changes]), and the
   * median yearly change in % less feedback, plain (`none`) and against the
   * same tenure by each measure, over the same `n` pairs of years. */
  tenure_cmp?: Record<string, Record<Metric, TenureCmp>>;
  /** The same opening-card charts with tenure in changes landed before (earlier
   * commits on main), the page's main tenure measure: the bins (`chg_labels`,
   * fewest first) of the cohort curves (`cohorts_chg`, bin index in place of
   * years) and of the all-against-addressed chart (`kinds_chg`,
   * `kind_share_chg`), and the histogram per doubling of changes landed from
   * `doubling_from` (`change_chg`, each ratio one doubling's value over the one
   * before). */
  chg_labels?: string[];
  cohorts_chg?: Record<string, Record<Metric, Record<string, [number, number, number][]>>>;
  kinds_chg?: Record<string, Record<Corr, [number | null, number | null, number][]>>;
  kind_share_chg?: Record<string, (number | null)[]>;
  doubling_from?: number;
  change_chg?: Record<string, Record<Metric, { n: number; people: number; median: number | null; counts: number[] }>>;
}

export type TenureMeasure = 'time' | 'changes' | 'dir';

export interface TenureCmp {
  bands: Record<TenureMeasure, [number | null, number][]>;
  n: number;
  people: number;
  none: number | null;
  time: number | null;
  changes: number | null;
  dir: number | null;
}

/** The tenure measure that leaves the least of each contributor's yearly
 * change unexplained (closest to zero), or null without data. */
export function bestTenure(c: TenureCmp): TenureMeasure | null {
  const ms = (['time', 'changes', 'dir'] as const).filter((m) => c[m] !== null);
  if (!ms.length) return null;
  return ms.reduce((a, b) => (Math.abs(c[b]!) < Math.abs(c[a]!) ? b : a));
}

/** [median (null: too few contributors), contributors]. */
export type MedianBar = [number | null, number];

/** The histogram's bins as words ("fell 60%+", "fell 50–60%" … "grew 152%+"),
 * and whether each is a fall. */
export function ratioBins(edges: number[]): { label: string; fell: boolean }[] {
  const p = (x: number) => Math.round(Math.abs(x) * 100);
  return Array.from({ length: edges.length + 1 }, (_, i) => {
    const lo = i === 0 ? 0 : edges[i - 1];
    const hi = i === edges.length ? Infinity : edges[i];
    if (hi <= 1) return { fell: true, label: i === 0 ? `fell ${p(1 - hi)}%+` : `fell ${p(1 - hi)}–${p(1 - lo)}%` };
    return { fell: false, label: i === edges.length ? `grew ${p(lo - 1)}%+` : `grew ${p(lo - 1)}–${p(hi - 1)}%` };
  });
}

/** The opening card's group: the "Peers" org, measured against directory
 * experience when tenure is by directory. Years and changes both show plain
 * values (the card's axis is `introAxis`). */
export function trendGroup(by: TenureBy, org: PeerOrg): string {
  return by === 'dir' ? `dir:${org}` : org;
}

/** The opening card's tenure axis: years only when "Same tenure by" is years,
 * changes landed before otherwise (directory experience has no axis of its own). */
export function introAxis(by: TenureBy): 'time' | 'changes' {
  return by === 'time' ? 'time' : 'changes';
}

/** The first-commit years the opening card draws: those from `from` on whose
 * curve starts at tenure 0 and has 3 or more points, every other one from the
 * oldest when there are more than `max`, always keeping the newest. */
export function cohortYears(curves: Record<string, [number, number, number][]>, from: number, max = 5): number[] {
  const ys = Object.keys(curves).map(Number).filter((y) => y >= from && curves[y].length >= 3 && curves[y][0][0] === 0)
    .sort((a, b) => a - b);
  return ys.length > max ? ys.filter((_, i) => i % 2 === 0 || i === ys.length - 1) : ys;
}

export const GERRIT ='https://chromium-review.googlesource.com';
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

/** The data file's name for an address (scripts/review_feedback.py `key`). */
export async function personKey(raw: string): Promise<string> {
  const bytes = new TextEncoder().encode(SALT + normalizeEmail(raw));
  const hash = new Uint8Array(await crypto.subtle.digest('SHA-256', bytes));
  return Array.from(hash, (b) => b.toString(16).padStart(2, '0')).join('').slice(0, 32);
}

export const metricOf = (kind: Kind, corr: Corr): Metric => `${kind}${corr}`;

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

/** The days a measure of `kind` covers: the addressed ones start where the labels do. */
export const rangeOf = (peers: Peers, kind: Kind): [number, number] =>
  [kind === 'a' ? peers.addr_start : peers.start, peers.end];

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

/** The person's tenure band in a period by one measure (null: unknown, or by directory). */
export function bandOf(by: TenureBy, vals: PeriodVals | undefined): string | null {
  if (!vals) return null;
  return by === 'time' ? vals.ten : by === 'changes' ? vals.chg : null;
}

/** The peer group's key in peers.json, given the person's period values. */
export function groupKey(by: TenureBy, org: PeerOrg, vals: PeriodVals | undefined): string | null {
  if (by === 'dir') return `dir:${org}`;
  const band = bandOf(by, vals);
  return band ? `${by}:${band}:${org}` : null;
}

/** The peer group for each of the half-years `hs`, including those the person landed no
 * changes in: their tenure is known then too, so the trend's peer band covers them all.
 * Years since the first commit at the half-year's middle, or the earlier commits on main
 * there (one more than at their last change before it, else as many as at their first
 * change after it). Null before they started contributing (the half-years that end
 * before their first commit, else their first change), and for tenure in years when the
 * first commit is unknown. */
export function halfGroups(by: TenureBy, org: PeerOrg, p: Pick<Person, 'periods' | 'firstDay' | 'cls'>,
  hs: string[]): (string | null)[] {
  const cls = [...p.cls].sort((a, b) => a[1] - b[1]);
  const start = p.firstDay ?? cls[0]?.[1] ?? Infinity;
  return hs.map((h) => {
    const [a, b] = periodSpan(h, [-Infinity, Infinity]);
    if (b <= start && !p.periods[h]) return null;
    if (by === 'dir') return `dir:${org}`;
    let band = bandOf(by, p.periods[h]);
    const mid = (a + b) / 2;
    if (!band && by === 'time' && p.firstDay !== null) band = tenureBand(Math.max(0, mid - p.firstDay) / 365.25);
    if (!band && by === 'changes') {
      const before = cls.filter((c) => c[1] < mid).pop();
      const after = cls.find((c) => c[1] >= mid);
      band = before ? changesBand(before[10] + 1) : after ? changesBand(after[10]) : null;
    }
    return band ? `${by}:${band}:${org}` : null;
  });
}

/** The person's value to set against a peer group's distribution. */
export const valueFor = (by: TenureBy, vals: PeriodVals | undefined, m: Metric) =>
  vals ? (by === 'dir' ? vals.x[m] : vals.v[m]) ?? null : null;

/** Earlier-commit bands, as scripts/review_feedback.py `changes_band`. */
export const changesBand = (n: number) =>
  n < 50 ? '<50' : n < 200 ? '50-199' : n < 500 ? '200-499' : n < 1000 ? '500-999' : '1000+';

/** Directory-experience bands, by earlier commits in the directory. */
export const xpBand = (prior: number) => (prior === 0 ? 0 : prior < 5 ? 1 : prior < 20 ? 2 : prior < 100 ? 3 : 4);

const expected = (c: ClRow, m: Metric) => {
  const [, , , ts, td, as, ad] = c;
  if (m[1] === 'n') return 1;
  return m === 'ts' ? ts : m === 'td' ? td : m === 'as' ? as : ad;
};

const counts = (t: Thread, kind: Kind) => (kind === 't' ? 1 : t[3] ? 1 : 0);

/** The changes landed in `period`. */
export const clsIn = (p: Person, period: string) => p.cls.filter((c) => inPeriod(c[1], period));
/** The changes landed in `period` that a measure of `kind` counts: the addressed ones need labels. */
export const clsFor = (p: Person, period: string, kind: Kind) =>
  clsIn(p, period).filter((c) => kind === 't' || c[1] >= p.addrStart);

/** The threads-per-change histogram's columns, by their fewest threads: 0, 1–2, 3–5, 6–10,
 * 11–20, 21+. Over all changes since July 2023 they hold 56, 23, 10, 6, 3 and 2% (2026-11-12). */
export const THREAD_BIN_FROM = [0, 1, 3, 6, 11, 21];
export const THREAD_BINS = THREAD_BIN_FROM.length;
/** Column `b`'s fewest and most threads (null: no upper end). */
export const threadBinRange = (b: number): [number, number | null] =>
  [THREAD_BIN_FROM[b], b + 1 < THREAD_BINS ? THREAD_BIN_FROM[b + 1] - 1 : null];
export function threadBinLabel(b: number): string {
  const [lo, hi] = threadBinRange(b);
  return hi === null ? `${lo}+` : lo === hi ? String(lo) : `${lo}–${hi}`;
}
/** The reviewer threads on a change that a measure of `kind` counts. */
export const threadsOn = (c: ClRow, kind: Kind) => c[8].reduce((s, t) => s + counts(t, kind), 0);
export function threadBin(c: ClRow, kind: Kind): number {
  const n = threadsOn(c, kind);
  let b = 0;
  while (b + 1 < THREAD_BINS && n >= THREAD_BIN_FROM[b + 1]) b++;
  return b;
}

/** The changes `clsFor` gives, only those in histogram column `bin` (null: all). */
const clsPicked = (p: Person, period: string, kind: Kind, bin: number | null) =>
  clsFor(p, period, kind).filter((c) => bin === null || threadBin(c, kind) === bin);

/** The person's changes landed in `period` by how many reviewer threads each drew. */
export function threadHistogram(p: Person, period: string, kind: Kind): number[] {
  const out = new Array<number>(THREAD_BINS).fill(0);
  for (const c of clsFor(p, period, kind)) out[threadBin(c, kind)] += 1;
  return out;
}

/** Whether the person counts among peers for a measure of `kind`. */
export const okFor = (vals: PeriodVals | undefined, kind: Kind) => (kind === 't' ? vals?.ok : vals?.ok_a) ?? false;
/** The changes a measure of `kind` counts. */
export const clsOf = (vals: PeriodVals | undefined, kind: Kind) => (kind === 't' ? vals?.cls : vals?.acls) ?? 0;

export interface Sums {
  /** Changes, counted by their share of lines (whole changes for a person's total). */
  cls: number;
  obs: number;
  den: number;
}

/** Feedback by directory-experience band: what each band's share of the
 * person's changes drew, against the metric's denominator. */
export function xpBreakdown(p: Person, period: string, m: Metric): Sums[] {
  const out = Array.from({ length: 5 }, () => ({ cls: 0, obs: 0, den: 0 }));
  for (const c of clsFor(p, period, m[0] as Kind)) {
    const per = new Map<number, number>();
    for (const t of c[8]) per.set(t[4], (per.get(t[4]) ?? 0) + counts(t, m[0] as Kind));
    for (const [d, w, prior] of c[7]) {
      const b = out[xpBand(prior)];
      b.cls += w;
      b.obs += per.get(d) ?? 0;
      b.den += w * expected(c, m);
    }
  }
  return out;
}

/** Feedback by changes landed before: what the person's changes drew in each
 * of `labels` (peers.json's `changes`, the `changesBand` bands), by the earlier
 * commits on main each change had, against the metric's denominator. */
export function chgBreakdown(p: Person, period: string, m: Metric, labels: string[]): Sums[] {
  const out = labels.map(() => ({ cls: 0, obs: 0, den: 0 }));
  for (const c of clsFor(p, period, m[0] as Kind)) {
    const b = out[labels.indexOf(changesBand(c[10]))];
    if (!b) continue;
    b.cls += 1;
    b.obs += threadsOn(c, m[0] as Kind);
    b.den += expected(c, m);
  }
  return out;
}

/** Figures for one directory, or for a directory's own files ("rest of"). */
export interface DirStats {
  /** Changes touching it, each change once however many directories below it the change touches. */
  cls: number;
  /** Lines changed there (added + deleted), summed over the changes. */
  lines: number;
  threads: number;
  /** Expected threads there (size and directory norm, by line share). */
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
  b.cls - a.cls || b.threads - a.threads || (a.path < b.path ? -1 : a.path > b.path ? 1 : 0);

/** The person's directories in `period` as a tree, each level most changes
 * first. A parent adds up its subdirectories (and own files), counting each
 * change once. `bin` keeps only the changes in that threads-per-change column. */
export function dirTree(p: Person, period: string, kind: Kind, bin: number | null = null): DirNode[] {
  const nodes = new Map<string, DirNode>();
  const roots: DirNode[] = [];
  const stats = (): DirStats => ({ cls: 0, lines: 0, threads: 0, expected: 0, prior: 0, ids: new Set() });
  const add = (s: DirStats, lines: number, threads: number, exp: number, prior: number) => {
    s.lines += lines;
    s.threads += threads;
    s.expected += exp;
    s.prior = Math.max(s.prior, prior);
  };
  const m: Metric = `${kind}d`;
  for (const c of clsPicked(p, period, kind, bin)) {
    const per = new Map<number, number>();
    for (const t of c[8]) per.set(t[4], (per.get(t[4]) ?? 0) + counts(t, kind));
    const touched = new Set<DirNode>();
    for (const [d, w, prior, dirLines] of c[7]) {
      const path = p.dirs[d];
      const lines = dirLines ?? Math.round(w * c[2]);
      const threads = per.get(d) ?? 0;
      const exp = w * expected(c, m);
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
        add(n, lines, threads, exp, prior);
        touched.add(n);
        if (end === path.length) {
          n.own ??= stats();
          if (!n.own.ids.has(c[0])) (n.own.cls += 1, n.own.ids.add(c[0]));
          add(n.own, lines, threads, exp, prior);
        }
        parent = n;
        at = end;
      }
    }
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
  /** Entries in an "Other" row. */
  count?: number;
}

type DirItem = { kind: 'dir' | 'rest'; node: DirNode; stats: DirStats };

/** The rows to show of `dirTree`'s tree, given which rows are open
 * (`expanded`, by row key). Each level lists its entries with at least
 * `minCls` changes, at most `shown` of them, and puts the rest in one "Other"
 * row that opens into them, `shown` at a time. A directory opens (into its
 * subdirectories plus a "rest of" row for its own files) only when one of
 * those has `minCls` changes. Only the top level, when none of it has
 * `minCls` changes, lists its first `shown` entries instead. */
export function dirRows(roots: DirNode[], expanded: ReadonlySet<string>, minCls: number, shown = 15): DirRowView[] {
  const out: DirRowView[] = [];
  const order = (a: DirItem, b: DirItem) => b.stats.cls - a.stats.cls || b.stats.threads - a.stats.threads ||
    (a.kind === b.kind ? (a.node.path < b.node.path ? -1 : 1) : a.kind === 'dir' ? -1 : 1);
  const emit = (it: DirItem, depth: number) => {
    if (it.kind === 'rest') {
      out.push({ key: `r:${it.node.path}`, kind: 'rest', depth, node: it.node, stats: it.stats, expandable: false, expanded: false });
      return;
    }
    const n = it.node;
    const key = `d:${n.path}`;
    const big = (x: DirStats | null) => x !== null && x.cls >= minCls;
    const expandable = n.children.some(big) || (n.children.length > 0 && big(n.own));
    const open = expandable && expanded.has(key);
    out.push({ key, kind: 'dir', depth, node: n, stats: n, expandable, expanded: open });
    if (!open) return;
    const items: DirItem[] = n.children.map((c) => ({ kind: 'dir', node: c, stats: c }));
    if (n.own) items.push({ kind: 'rest', node: n, stats: n.own });
    group(items.sort(order), depth + 1, key, false);
  };
  // `plain`: list the first `shown` entries, whatever their size.
  const group = (items: DirItem[], depth: number, parentKey: string, plain: boolean) => {
    const head = (plain ? items : items.filter((it) => it.stats.cls >= minCls)).slice(0, shown);
    const tail = items.filter((it) => !head.includes(it));
    for (const it of head) emit(it, depth);
    if (!tail.length) return;
    const key = `o:${parentKey}`;
    const open = expanded.has(key);
    const ids = new Set<number>();
    for (const it of tail) for (const id of it.stats.ids) ids.add(id);
    out.push({
      key, kind: 'other', depth, expandable: true, expanded: open, count: tail.length,
      stats: {
        cls: ids.size,
        ids,
        lines: tail.reduce((s, it) => s + it.stats.lines, 0),
        threads: tail.reduce((s, it) => s + it.stats.threads, 0),
        expected: tail.reduce((s, it) => s + it.stats.expected, 0),
        prior: Math.max(...tail.map((it) => it.stats.prior)),
      },
    });
    if (open) group(tail, depth + 1, key, true);
  };
  const top = roots.map((n): DirItem => ({ kind: 'dir', node: n, stats: n })).sort(order);
  group(top, 0, 'root', !top.some((it) => it.stats.cls >= minCls));
  return out;
}

/** The ratio cell's shade: -1 (a quarter of typical or less) .. 0 (typical) .. 1 (4× or more), on a log scale. */
export function ratioShade(ratio: number): number {
  if (!(ratio > 0)) return -1;
  return Math.max(-1, Math.min(1, Math.log2(ratio) / 2));
}

export interface ThreadRow {
  cl: number;
  uuid: string;
  file: string;
  /** Day the thread started, or the change landed when unknown. */
  day: number;
  addressed: 0 | 1 | null;
  dir: number;
  text: string | null;
  praise: boolean;
}

/** Reviewer threads on the changes landed in `period`, newest first,
 * optionally only addressed ones, only in directories under `dir` (a
 * path prefix such as "chrome/" or "chrome/browser/ui/"), and only on the
 * changes in threads-per-change column `bin`. */
export function threadRows(p: Person, period: string, kind: Kind, dir: string | null, bin: number | null = null): ThreadRow[] {
  const praise = new Set(p.praise.map(([n, u]) => `${n}/${u}`));
  const out: ThreadRow[] = [];
  for (const c of clsPicked(p, period, kind, bin)) {
    for (const t of c[8]) {
      if (kind === 'a' && !t[3]) continue;
      if (dir !== null && !p.dirs[t[4]].startsWith(dir)) continue;
      out.push({ cl: c[0], uuid: t[0], file: p.files[t[1]], day: c[1] + (t[2] ?? 0), addressed: t[3], dir: t[4],
        text: t[5] ?? null, praise: praise.has(`${c[0]}/${t[0]}`) });
    }
  }
  return out.sort((a, b) => b.day - a.day || b.cl - a.cl);
}

/** A Gerrit link to one comment (or to the change, without a uuid). The parts
 * come from data, so they are encoded. */
export function commentUrl(cl: number, uuid?: string): string {
  const base = `${GERRIT}/c/chromium/src/+/${Math.trunc(cl)}`;
  return uuid ? `${base}/comment/${encodeURIComponent(uuid)}/` : base;
}

/** Half-year periods in order, from peers.json's list. */
export const halves = (periods: string[]) => periods.filter((p) => /^\d{4}H[12]$/.test(p)).sort();

// ---- Merging a person's files, and their values per period

/** The half-year files merged into one person, names re-indexed. */
export function mergePerson(top: Top, shards: Shard[]): Omit<Person, 'periods' | 'addrStart'> {
  const tables = { dirs: new Map<string, number>(), files: new Map<string, number>(), orgs: new Map<string, number>() };
  const at = (t: Map<string, number>, name: string) => {
    let i = t.get(name);
    if (i === undefined) t.set(name, (i = t.size));
    return i;
  };
  const cls: ClRow[] = [];
  for (const s of shards) {
    const d = s.dirs.map((x) => at(tables.dirs, x));
    const f = s.files.map((x) => at(tables.files, x));
    const o = s.orgs.map((x) => at(tables.orgs, x));
    for (const c of s.cls) {
      const units = c[7].map(([di, ...rest]): Unit => [d[di], ...rest]);
      const threads = c[8].map((t): Thread => {
        const r: Thread = [t[0], f[t[1]], t[2], t[3], d[t[4]]];
        if (t.length > 5) r.push(t[5]);
        return r;
      });
      cls.push([c[0], c[1], c[2], c[3], c[4], c[5], c[6], units, threads, o[c[9]], c[10]]);
    }
  }
  cls.sort((a, b) => a[1] - b[1] || a[0] - b[0]);
  return { first: top.first, firstDay: top.first_day, tone: top.tone, praise: top.praise,
    dirs: [...tables.dirs.keys()], files: [...tables.files.keys()], orgs: [...tables.orgs.keys()], cls };
}

const r3 = (x: number) => Math.round(x * 1000) / 1000;
const METRICS: Metric[] = ['tn', 'ts', 'td', 'an', 'as', 'ad'];

function median(xs: number[]): number {
  const s = [...xs].sort((a, b) => a - b);
  const m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

export const tenureBand = (y: number) => (y < 1 ? '<1y' : y < 2 ? '1-2y' : y < 5 ? '2-5y' : y < 10 ? '5-10y' : '10y+');

/** A person's values for one period, as scripts/review_feedback.py
 * `person_period` computes them for the peer groups: totals, tenure (years
 * and earlier commits) at the median change, the most common org, whether they count among peers, the
 * measures, and the same measures against everyone's feedback at the same
 * directory experience (peers.json's pooled `rel` per band). */
export function periodVals(p: Omit<Person, 'periods'>, peers: Peers, period: string): PeriodVals | undefined {
  const cs = clsIn(p as Person, period);
  if (!cs.length) return undefined;
  let threads = 0;
  let addressed = 0;
  let acls = 0;
  // Expected threads; tdA: expected threads on the labelled changes, for ok_a.
  const exp = { ts: 0, td: 0, as: 0, ad: 0, tdA: 0 };
  const orgCount = new Map<number, number>();
  const labelled = (c: ClRow) => c[1] >= p.addrStart;
  for (const c of cs) {
    threads += c[8].length;
    exp.ts += c[3];
    exp.td += c[4];
    if (labelled(c)) {
      acls += 1;
      addressed += c[8].filter((t) => t[3]).length;
      exp.as += c[5];
      exp.ad += c[6];
      exp.tdA += c[4];
    }
    orgCount.set(c[9], (orgCount.get(c[9]) ?? 0) + 1);
  }
  // Most common org; ties go to the one seen first (Python's Counter.most_common).
  let org = cs[0][9];
  for (const [o, n] of orgCount) if (n > orgCount.get(org)!) org = o;
  const ten = p.firstDay === null ? null : tenureBand(median(cs.map((c) => (c[1] - p.firstDay!) / 365.25)));
  const prior = median(cs.map((c) => c[10]));
  const v = {} as Record<Metric, number | null>;
  const x = {} as Record<Metric, number | null>;
  const bands = peers.bands[period];
  for (const m of METRICS) {
    const isT = m[0] === 't';
    const num = isT ? threads : addressed;
    const den = m[1] === 'n' ? (isT ? cs.length : acls) : exp[m as 'ts' | 'td' | 'as' | 'ad'];
    v[m] = den ? r3(num / den) : null;
    let xe = 0;
    for (const c of cs) {
      if (!isT && !labelled(c)) continue;
      for (const [, w, prior] of c[7]) xe += (m[1] === 'n' ? w : w * expected(c, m)) * (bands?.[m]?.[xpBand(prior)]?.rel ?? 1);
    }
    x[m] = xe ? r3(num / xe) : null;
  }
  return { cls: cs.length, threads, acls, addressed, ten, prior, chg: changesBand(prior), org: p.orgs[org],
    ok: cs.length >= peers.min_cls && exp.td >= peers.min_exp, ok_a: acls >= peers.min_cls && exp.tdA >= peers.min_exp, v, x };
}

/** A person ready for the page: merged, with values for every period they have changes in. */
export function buildPerson(top: Top, shards: Shard[], peers: Peers): Person {
  const base = { ...mergePerson(top, shards), addrStart: peers.addr_start };
  const periods: Record<string, PeriodVals> = {};
  for (const period of peers.periods) {
    const vals = periodVals(base, peers, period);
    if (vals) periods[period] = vals;
  }
  return { ...base, periods };
}
