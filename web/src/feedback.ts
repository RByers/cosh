// The Review Feedback page's data and arithmetic (review-feedback.html,
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
  addressed: number;
  /** Tenure band at the middle of the period's changes, null if unknown. */
  ten: string | null;
  /** Earlier commits on main at the middle of the period's changes, and its band. */
  prior: number;
  chg: string;
  /** The org most of the period's changes are attributed to. */
  org: string;
  /** Enough changes to count among peers. */
  ok: boolean;
  /** The measure; and the same against the directory-experience norm. */
  v: Record<Metric, number | null>;
  x: Record<Metric, number | null>;
}

/** [comment uuid (empty when there's no excerpt: link the change instead),
 * file index, days after the change landed, addressed (null: not labelled),
 * directory index, excerpt (only where comment text is collected)]. */
export type Thread = [string, number, number | null, 0 | 1 | null, number, string?];
/** [directory index, share of the change's lines, the owner's earlier commits there]. */
export type Unit = [number, number, number];
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

export interface Band extends Dist {
  /** Everyone's feedback in the band, pooled, and that relative to everyone's overall. */
  pooled: number | null;
  rel: number | null;
}

export interface Peers {
  generated: string;
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
  bands: Record<string, Record<Metric, Band[]>>;
  tone: Record<string, Dist>;
  /** The opening card. Tenure bins of the cohort curves, in years, and the
   * fewest people a point stands for. */
  cohort_step: number;
  min_cohort: number;
  /** Group -> measure -> year of first commit -> [tenure bin start, median, people]. */
  cohorts: Record<string, Record<Metric, Record<string, [number, number, number][]>>>;
  /** Histogram bin edges, % less feedback a year: the first bin takes
   * everything below edges[1], the last everything from edges[-2] on. */
  change_edges: number[];
  /** Group -> measure -> people's yearly reduction in feedback. */
  change: Record<string, Record<Metric, { n: number; median: number | null; counts: number[] }>>;
}

/** The opening card's group: the "Peers" org, measured against directory
 * experience when tenure is by directory. Years and changes both show plain
 * values (the card's own axis is years). */
export function trendGroup(by: TenureBy, org: PeerOrg): string {
  return by === 'dir' ? `dir:${org}` : org;
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
  for (const c of clsIn(p, period)) {
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

export interface DirRow {
  dir: string;
  /** Changes touching the directory. */
  cls: number;
  threads: number;
  /** Expected threads there (size and directory norm, by line share). */
  expected: number;
  /** The person's earlier commits there before their latest change in the period. */
  prior: number;
  index: number;
}

/** The person's directories in `period`, most changes first. */
export function dirTable(p: Person, period: string, kind: Kind): DirRow[] {
  const rows = new Map<number, DirRow>();
  const m: Metric = `${kind}d`;
  for (const c of clsIn(p, period)) {
    const per = new Map<number, number>();
    for (const t of c[8]) per.set(t[4], (per.get(t[4]) ?? 0) + counts(t, kind));
    for (const [d, w, prior] of c[7]) {
      let r = rows.get(d);
      if (!r) rows.set(d, (r = { dir: p.dirs[d], cls: 0, threads: 0, expected: 0, prior: 0, index: d }));
      r.cls += 1;
      r.threads += per.get(d) ?? 0;
      r.expected += w * expected(c, m);
      r.prior = Math.max(r.prior, prior);
    }
  }
  return [...rows.values()].sort((a, b) => b.cls - a.cls || b.threads - a.threads || a.dir.localeCompare(b.dir));
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
 * optionally only addressed ones, in one directory, or praise. */
export function threadRows(p: Person, period: string, kind: Kind, dir: number | null, praiseOnly: boolean): ThreadRow[] {
  const praise = new Set(p.praise.map(([n, u]) => `${n}/${u}`));
  const out: ThreadRow[] = [];
  for (const c of clsIn(p, period)) {
    for (const t of c[8]) {
      if (kind === 'a' && !t[3]) continue;
      if (dir !== null && t[4] !== dir) continue;
      const isPraise = praise.has(`${c[0]}/${t[0]}`);
      if (praiseOnly && !isPraise) continue;
      out.push({ cl: c[0], uuid: t[0], file: p.files[t[1]], day: c[1] + (t[2] ?? 0), addressed: t[3], dir: t[4],
        text: t[5] ?? null, praise: isPraise });
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
/** Calendar-year periods in order. */
export const years = (periods: string[]) => periods.filter((p) => /^\d{4}$/.test(p)).sort();

// ---- Merging a person's files, and their values per period

/** The half-year files merged into one person, names re-indexed. */
export function mergePerson(top: Top, shards: Shard[]): Omit<Person, 'periods'> {
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
      const units = c[7].map(([di, w, prior]): Unit => [d[di], w, prior]);
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
  const exp = { ts: 0, td: 0, as: 0, ad: 0 };
  const orgCount = new Map<number, number>();
  for (const c of cs) {
    threads += c[8].length;
    addressed += c[8].filter((t) => t[3]).length;
    exp.ts += c[3];
    exp.td += c[4];
    exp.as += c[5];
    exp.ad += c[6];
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
    const num = m[0] === 't' ? threads : addressed;
    const den = m[1] === 'n' ? cs.length : exp[m as keyof typeof exp];
    v[m] = den ? r3(num / den) : null;
    let xe = 0;
    for (const c of cs)
      for (const [, w, prior] of c[7]) xe += (m[1] === 'n' ? w : w * expected(c, m)) * (bands?.[m]?.[xpBand(prior)]?.rel ?? 1);
    x[m] = xe ? r3(num / xe) : null;
  }
  return { cls: cs.length, threads, addressed, ten, prior, chg: changesBand(prior), org: p.orgs[org], ok: cs.length >= peers.min_cls && exp.td >= peers.min_exp,
    v, x };
}

/** A person ready for the page: merged, with values for every period they have changes in. */
export function buildPerson(top: Top, shards: Shard[], peers: Peers): Person {
  const base = mergePerson(top, shards);
  const periods: Record<string, PeriodVals> = {};
  for (const period of peers.periods) {
    const vals = periodVals(base, peers, period);
    if (vals) periods[period] = vals;
  }
  return { ...base, periods };
}
