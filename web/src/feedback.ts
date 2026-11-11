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

/** A peer group: everyone, the person's tenure band, an org, or everyone
 * measured against the same directory experience. */
export type PeerChoice = 'all' | 'ten' | 'dirxp' | 'org:google' | 'org:microsoft' | 'org:igalia' | 'org:nongoogle';

export interface PeriodVals {
  cls: number;
  threads: number;
  addressed: number;
  /** Tenure band at the middle of the period's changes, null if unknown. */
  ten: string | null;
  /** The org most of the period's changes are attributed to. */
  org: string;
  /** Enough changes to count among peers. */
  ok: boolean;
  /** The measure; and the same against the directory-experience norm. */
  v: Record<Metric, number | null>;
  x: Record<Metric, number | null>;
}

/** [comment uuid, file index, days after the change landed, addressed (null:
 * not labelled), directory index, excerpt (last year only)]. */
export type Thread = [string, number, number | null, 0 | 1 | null, number, string?];
/** [directory index, share of the change's lines, the owner's earlier commits there]. */
export type Unit = [number, number, number];
/** [change number, day landed (days since 1970), lines, expected threads by
 * size, by size and directory, expected addressed by size, by size and
 * directory, units, threads]. */
export type ClRow = [number, number, number, number, number, number, number, Unit[], Thread[]];

export interface Person {
  v: 1;
  generated: string;
  first: string | null;
  periods: Record<string, PeriodVals>;
  tone: { received: number; praise: number; share: number | null; ten: string | null };
  /** [change number, uuid, day, excerpt], newest first. */
  praise: [number, string, number, string][];
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
  xp: string[];
  min_cls: number;
  min_exp: number;
  min_received: number;
  tone_weeks: [string, string];
  dist: Record<string, Record<string, Record<Metric, Dist>>>;
  bands: Record<string, Record<Metric, Band[]>>;
  tone: Record<string, Dist>;
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

/** The peer group's key in peers.json for a choice, given the person's period values. */
export function groupKey(choice: PeerChoice, vals: PeriodVals | undefined): string | null {
  if (choice === 'ten') return vals?.ten ? `ten:${vals.ten}` : null;
  return choice;
}

/** The person's value to set against a peer group's distribution. */
export const valueFor = (choice: PeerChoice, vals: PeriodVals | undefined, m: Metric) =>
  vals ? (choice === 'dirxp' ? vals.x[m] : vals.v[m]) ?? null : null;

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
