// Data for the Review Tone page (sentiment.html): the summaries written by
// `python3 -m cosh.sentiment summary | praise | samples` (docs/sentiment.md).
// Ground rule 5: people are named only for praise; grumpy samples carry no
// names, links or dates finer than a month.
import { addWeeks, weekMonday, weekSunday } from './data.ts';
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
  months: { m: string; month: TonePoint; span: [string, string]; rolling: TonePoint }[];
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
  /** The boards: net praise per period, highest first, positive totals only. */
  net: Record<Period, Record<'given' | 'received', NetRow[]>>;
  /** A net total this large gets a pill's full colour. */
  net_scale: number;
}

/** summaries/sentiment_samples.json */
export interface ToneSamples {
  weeks: [string, string];
  praise_min: number;
  grumpy_max: number;
  praise: { text: string; score: number; date: string; writer: string; recipient: string; url: string }[];
  grumpy: { text: string; score: number; month: string }[];
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

/** summaries/sentiment_recent.json (cosh/sentiment_recent.py) */
export interface ToneRecent {
  weeks: [string, string];
  month_weeks: [string, string];
  thresholds: { glowing: number; angry: number };
  min_counterparts: number;
  n_trivial: number;
  total: ToneStat;
  weekly: (ToneStat & { week: string })[];
  dist: [number, number][];
  happy: Record<Period, { authors: HappyRow[]; reviewers: HappyRow[] }>;
  ai: { text: string; score: number; month: string; role: 'author' | 'reviewer' }[];
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
  url: string;
}

/** summaries/sentiment_comments.json (cosh/sentiment_recent.py): the
 * comments behind the praise boards and the happy tables, loaded on the
 * first popup. Only praise and glowing comments. */
export interface PersonComments {
  weeks: [string, string];
  comments: Record<string, PersonComment>;
  /** Every praise comment, as counted on the praise boards. */
  praise: string[];
  /** Each listed person's glowing comments, by period and table. */
  happy: Record<Period, Record<'authors' | 'reviewers', Record<string, string[]>>>;
}

const newestFirst = (a: PersonComment, b: PersonComment) => b.date.localeCompare(a.date) || b.score - a.score;

/** The praise comments `email` gave or received in `range`, newest first. */
export function praiseComments(d: PersonComments, email: string, key: 'given' | 'received', range: [string, string]): PersonComment[] {
  return d.praise
    .map((id) => d.comments[id])
    .filter((c) => c && within(c.week, range) && (key === 'given' ? c.writer_email : c.recipient_email) === email)
    .sort(newestFirst);
}

/** The glowing comments behind `email`'s row in a happy table, newest first. */
export function happyComments(d: PersonComments, email: string, table: 'authors' | 'reviewers', period: Period): PersonComment[] {
  return (d.happy[period]?.[table]?.[email] ?? []).map((id) => d.comments[id]).filter(Boolean).sort(newestFirst);
}

/** The leaderboards' periods: every scored week, or the last four. */
export type Period = 'all' | 'month';
export const MONTH_WEEKS = 4;

/** The weeks of `range` that `period` covers. */
export function periodWeeks(range: [string, string], period: Period): [string, string] {
  return period === 'all' ? range : [maxWeek(range[0], addWeeks(range[1], 1 - MONTH_WEEKS)), range[1]];
}

const maxWeek = (a: string, b: string) => (a > b ? a : b);

const within = (week: string, [from, to]: [string, string]) => week >= from && week <= to;

/** A net praise board for `period`: the top `n` (or everyone, "all"), as
 * the data ranks them (highest net total first). */
export function netBoard(d: PraiseData, key: 'given' | 'received', period: Period, n: number | 'all' = 15): NetRow[] {
  const rows = d.net?.[period]?.[key] ?? [];
  return n === 'all' ? rows : rows.slice(0, n);
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
