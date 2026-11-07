// Data for the Review Tone page (sentiment.html): the summaries written by
// `python3 -m cosh.sentiment summary | praise | samples` (docs/sentiment.md).
// Ground rule 5: people are named only for praise; grumpy samples carry no
// names, links or dates finer than a month.
import { weekMonday, weekSunday } from './data.ts';
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

/** summaries/sentiment_monthly.json */
export interface ToneTrend {
  rate: number | null;
  window: number;
  thresholds: { glowing: number; angry: number };
  n: number;
  months: { m: string; month: TonePoint; span: [string, string]; rolling: TonePoint }[];
}

/** summaries/sentiment_praise.json */
export interface PraiseData {
  weeks: [string, string];
  people: Record<string, string>;
  weekly: { week: string; email: string; given: number; received: number }[];
}

/** summaries/sentiment_samples.json */
export interface ToneSamples {
  weeks: [string, string];
  praise_min: number;
  grumpy_max: number;
  praise: { text: string; score: number; date: string; writer: string; recipient: string; url: string }[];
  grumpy: { text: string; score: number; month: string }[];
}

export interface BoardRow {
  email: string;
  name: string;
  count: number;
}

/** The top `n` people by praise given or received, summed over the weeks;
 * ties by name. People with none are left out. */
export function praiseBoard(d: PraiseData, key: 'given' | 'received', n = 15): BoardRow[] {
  const sums = new Map<string, number>();
  for (const r of d.weekly) sums.set(r.email, (sums.get(r.email) ?? 0) + r[key]);
  return [...sums]
    .filter(([, c]) => c > 0)
    .map(([email, count]) => ({ email, name: d.people[email] ?? email, count }))
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name))
    .slice(0, n);
}

/** Praise comments in the data (each counts once as given). */
export const praiseTotal = (d: PraiseData) => d.weekly.reduce((s, r) => s + r.given, 0);

/** People who gave or received praise. */
export const praisePeople = (d: PraiseData) => new Set(d.weekly.map((r) => r.email)).size;

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
