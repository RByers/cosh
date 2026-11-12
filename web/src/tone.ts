// Data for the Review Tone page (sentiment.html): the summaries written by
// `python3 -m cosh.sentiment summary | praise | samples` (docs/sentiment.md).
// Ground rule 5: people are named only for praise; grumpy samples carry no
// names, links or dates finer than a month.
import { addWeeks, weekMonday, weekMonth, weekSunday } from './data.ts';
import { fmtDay } from './format.ts';

export type Interval = [number, number];

export interface TonePoint {
  n: number;
  mean: number;
  lo: number;
  hi: number;
  glowing: number;
  glowing_ci: Interval;
  angry: number;
  angry_ci: Interval;
  ai: number;
  ai_ci: Interval;
}

/** Whose comments a set of summaries counts: the page's "Comments by" switch. */
export const AUTHORS = ['committers', 'everyone', 'noncommitters'] as const;
export type Authors = (typeof AUTHORS)[number];

/** summaries/sentiment_monthly.json */
export interface ToneTrend {
  rate: number | null;
  window: number;
  thresholds: { glowing: number; angry: number };
  n: number;
  /** The first and last fully scored weeks, whose wholly covered months
   * use every comment instead of the sample. */
  full_weeks?: [string, string] | null;
  months: {
    m: string;
    /** This month uses every comment, not the sample. */
    full?: boolean;
    month: TonePoint;
    span: [string, string];
    /** `full`: every month in the span is. */
    rolling: TonePoint & { full?: boolean };
  }[];
}

/** A person on a net praise board: their praise scores, less their grumpy
 * ones; only positive totals are published. */
export interface NetRow {
  email: string;
  name: string;
  /** The net total. */
  score: number;
  /** How many praise comments went into it. */
  praise: number;
}

/** summaries/sentiment_praise.json */
export interface PraiseData {
  weeks: [string, string];
  people: Record<string, string>;
  /** Praise comment counts per person and week (the caption's totals). */
  weekly: { week: string; email: string; given: number; received: number }[];
  /** The boards: net praise per period (all, each year, each month),
   * highest first, positive totals only. */
  net: Record<Period, Record<'given' | 'received', NetRow[]>>;
  /** A net total this large gets a pill's full colour. */
  net_scale: number;
}

/** summaries/sentiment_samples.json: the samples of each period. */
export interface ToneSamples {
  weeks: [string, string];
  praise_min: number;
  grumpy_max: number;
  periods: Record<Period, {
    praise: { text: string; score: number; date: string; writer: string; recipient: string; url: string }[];
    grumpy: { text: string; score: number; month: string }[];
  }>;
}

export interface ToneStat {
  n: number;
  mean: number | null;
  glowing: number | null;
  angry: number | null;
  /** AI-friction comments (a count). */
  ai: number;
}

export interface HappyRow {
  name: string;
  email: string;
  /** Every glowing comment to them, repeats from one person included (the rank). */
  glowing: number;
  /** Distinct people who wrote those. */
  happy: number;
  counterparts: number;
}

/** One period's detail in summaries/sentiment_recent.json. */
export interface RecentPeriod {
  weeks: [string, string];
  n_trivial: number;
  total: ToneStat;
  dist: [number, number][];
  happy: { authors: HappyRow[]; reviewers: HappyRow[] };
  ai: { text: string; score: number; month: string; role: 'author' | 'reviewer' }[];
}

/** summaries/sentiment_recent.json (cosh/sentiment_recent.py) */
export interface ToneRecent {
  weeks: [string, string];
  thresholds: { glowing: number; angry: number };
  min_counterparts: number;
  weekly: (ToneStat & { week: string })[];
  monthly: (ToneStat & { month: string; weeks: [string, string] })[];
  periods: Record<Period, RecentPeriod>;
}

/** One praise or glowing comment behind a board, for a name popup. */
export interface PersonComment {
  text: string;
  date: string;
  week: string;
  score: number;
  writer: string;
  writer_email: string;
  recipient: string;
  recipient_email: string;
  /** Each one's role on the CL: "author" (its owner) or "reviewer". Missing
   * in files written before 2026-11-07. */
  writer_role?: Role;
  recipient_role?: Role;
  url: string;
}

export type Role = 'author' | 'reviewer';

/** How a popup comment relates to `email`: given or received, as change
 * author or as reviewer. Null when the file doesn't say. */
export function relation(c: PersonComment, email: string): `${'given' | 'received'}-${Role}` | null {
  if (c.writer_email === email) return c.writer_role ? `given-${c.writer_role}` : null;
  return c.recipient_role ? `received-${c.recipient_role}` : null;
}

/** summaries/sentiment_comments.json (cosh/sentiment_recent.py): the
 * comments behind the praise boards and the happy tables, loaded on the
 * first popup. Only praise and glowing comments. */
export interface PersonComments {
  weeks: [string, string];
  comments: Record<string, PersonComment>;
  /** Every praise comment, as counted on the praise boards. */
  praise: string[];
  /** The glowing comments of everyone in a happy table in some period, over
   * every week, by table. */
  happy: Record<'authors' | 'reviewers', Record<string, string[]>>;
}

const newestFirst = (a: PersonComment, b: PersonComment) => b.date.localeCompare(a.date) || b.score - a.score;

/** The praise comments `email` gave or received in `range`, newest first. */
export function praiseComments(d: PersonComments, email: string, key: 'given' | 'received', range: [string, string]): PersonComment[] {
  return d.praise
    .map((id) => d.comments[id])
    .filter((c) => c && within(c.week, range) && (key === 'given' ? c.writer_email : c.recipient_email) === email)
    .sort(newestFirst);
}

/** The glowing comments behind `email`'s row in a happy table (in `range`,
 * if given), newest first. */
export function happyComments(d: PersonComments, email: string, table: 'authors' | 'reviewers',
  range?: [string, string]): PersonComment[] {
  return (d.happy?.[table]?.[email] ?? []).map((id) => d.comments[id])
    .filter((c) => c && (!range || within(c.week, range))).sort(newestFirst);
}

/** The page's date choice: "all", a calendar year ("2026") or a calendar
 * month ("2026-10"). A week belongs to the month and year of its Thursday
 * (cosh.sentiment.periods). */
export type Period = string;

export const periodKind = (p: Period): 'all' | 'year' | 'month' =>
  p === 'all' ? 'all' : /^\d{4}$/.test(p) ? 'year' : 'month';

const weekKeys = (w: string) => {
  const { year, month } = weekMonth(w);
  return [String(year), `${year}-${String(month + 1).padStart(2, '0')}`];
};

/** The years and months the weeks of `range` fall in, oldest first. */
export function periodsOf([from, to]: [string, string]): { years: string[]; months: string[] } {
  const years = new Set<string>();
  const months = new Set<string>();
  for (let w = from; w <= to; w = addWeeks(w, 1)) {
    const [y, m] = weekKeys(w);
    years.add(y);
    months.add(m);
  }
  return { years: [...years], months: [...months] };
}

/** The weeks of `range` in `period`, or null when there are none. */
export function periodWeeks(range: [string, string], period: Period): [string, string] | null {
  if (period === 'all') return range;
  let first: string | null = null;
  let last: string | null = null;
  for (let w = range[0]; w <= range[1]; w = addWeeks(w, 1)) {
    if (weekKeys(w).includes(period)) {
      first ??= w;
      last = w;
    }
  }
  return first && last ? [first, last] : null;
}

const within = (week: string, [from, to]: [string, string]) => week >= from && week <= to;

/** A net praise board for `period`: the top `n` (or everyone, "all"), as
 * the data ranks them (highest net total first). */
export function netBoard(d: PraiseData, key: 'given' | 'received', period: Period, n: number | 'all' = 15): NetRow[] {
  const rows = d.net?.[period]?.[key] ?? [];
  return n === 'all' ? rows : rows.slice(0, n);
}

/** `email`'s place on a board (1-based, as the board numbers it) and the
 * board's length, or null when they aren't on it. */
export function boardRank(rows: { email: string }[], email: string): { rank: number; of: number } | null {
  const i = rows.findIndex((r) => r.email === email);
  return i < 0 ? null : { rank: i + 1, of: rows.length };
}

/** Every praise comment `email` gave or received (in `range`, if given),
 * newest first: the popup opened from the lookup box. */
export function allPraise(d: PersonComments, email: string, range?: [string, string]): PersonComment[] {
  return d.praise
    .map((id) => d.comments[id])
    .filter((c) => c && (!range || within(c.week, range)) && (c.writer_email === email || c.recipient_email === email))
    .sort(newestFirst);
}

/** Counts per month ("2026-10") of each list's items, by the month of their
 * week's Thursday, over every month of `range` (weeks). The popup charts
 * exactly the comments it lists (praise or glowing only, ground rule 5). */
export function byMonth(range: [string, string], lists: { week: string }[][]): { months: string[]; counts: number[][] } {
  const key = (w: string) => {
    const { year, month } = weekMonth(w);
    return `${year}-${String(month + 1).padStart(2, '0')}`;
  };
  const months: string[] = [];
  for (let m = key(range[0]); m <= key(range[1]); ) {
    months.push(m);
    const [y, mm] = m.split('-').map(Number);
    m = mm === 12 ? `${y + 1}-01` : `${y}-${String(mm + 1).padStart(2, '0')}`;
  }
  const at = new Map(months.map((m, i) => [m, i]));
  const counts = lists.map((items) => {
    const c = months.map(() => 0);
    for (const it of items) {
      const i = at.get(key(it.week));
      if (i !== undefined) c[i]++;
    }
    return c;
  });
  return { months, counts };
}

/** The person a lookup names: an email (any case), or a name that only one
 * person has. Null when no one in the data matches. */
export function findPerson(d: Pick<PraiseData, 'people'>, query: string): { email: string; name: string } | null {
  const q = query.trim().toLowerCase();
  if (!q) return null;
  const people = Object.entries(d.people);
  const byEmail = people.find(([e]) => e.toLowerCase() === q);
  if (byEmail) return { email: byEmail[0], name: byEmail[1] };
  const byName = people.filter(([, n]) => n.toLowerCase() === q);
  return byName.length === 1 ? { email: byName[0][0], name: byName[0][1] } : null;
}

/** The key in `people` for an address from elsewhere (a link from the Review
 * Feedback page): the same address, in any case, or with chromium.org and
 * google.com swapped, which other pages treat as one person. Unchanged when
 * none is there. */
export function resolveEmail(people: Record<string, string>, email: string): string {
  if (email in people) return email;
  const lower = new Map(Object.keys(people).map((e) => [e.toLowerCase(), e]));
  const e = email.trim().toLowerCase();
  const swap = e.replace(/@(chromium\.org|google\.com)$/, (_, d: string) => (d === 'google.com' ? '@chromium.org' : '@google.com'));
  return lower.get(e) ?? lower.get(swap) ?? email;
}

/** Up to `n` people whose name or email contains `query` (any case), those
 * starting with it first, then by name. None for an empty query. */
export function suggestPeople(d: Pick<PraiseData, 'people'>, query: string, n = 10): { email: string; name: string }[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  const starts = (e: string, name: string) => e.toLowerCase().startsWith(q) || name.toLowerCase().startsWith(q);
  return Object.entries(d.people)
    .filter(([e, name]) => e.toLowerCase().includes(q) || name.toLowerCase().includes(q))
    .map(([email, name]) => ({ email, name, first: starts(email, name) ? 0 : 1 }))
    .sort((a, b) => a.first - b.first || a.name.localeCompare(b.name))
    .slice(0, n)
    .map(({ email, name }) => ({ email, name }));
}

/** Praise comments in the data or in `range` (each counts once, as given). */
export const praiseTotal = (d: PraiseData, range?: [string, string]) =>
  d.weekly.filter((r) => !range || within(r.week, range)).reduce((s, r) => s + r.given, 0);

/** People who gave or received praise, in the data or in `range`. */
export const praisePeople = (d: PraiseData, range?: [string, string]) =>
  new Set(d.weekly.filter((r) => (!range || within(r.week, range)) && r.given + r.received > 0).map((r) => r.email)).size;

/** "7 Sep and 1 Nov 2026" for the weeks 2026-W37..2026-W44 (the UI names
 * weeks by their dates). */
export function weeksBetween([from, to]: [string, string]): string {
  const a = weekMonday(from);
  const b = weekSunday(to);
  return `${fmtDay(a, a.getUTCFullYear() !== b.getUTCFullYear())} and ${fmtDay(b)}`;
}

const monthFmt = new Intl.DateTimeFormat('en-GB', { month: 'short', year: 'numeric', timeZone: 'UTC' });

/** "2026-10" as "Oct 2026". */
export const monthLabel = (m: string) => monthFmt.format(new Date(`${m}-01T00:00:00Z`));

/** "2026-10-02" as "2 Oct 2026". */
export const dayLabel = (d: string) => fmtDay(new Date(`${d}T00:00:00Z`));

const GERRIT = 'https://chromium-review.googlesource.com/';

/** The link only if it points into Chromium's Gerrit over https. */
export const gerritLink = (u: string) => (typeof u === 'string' && u.startsWith(GERRIT) ? u : null);
