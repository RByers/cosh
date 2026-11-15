// The Review Load page's data and arithmetic (review-load.html,
// docs/review-load.md), kept apart from the DOM so unit tests can run it.
// cosh/review_load.py writes all.json (every quarter's figures and the
// directory table) and, per reviewer, a file per year and one per quarter of
// the table, named by the Feedback Index's `personKey` of their address.

/** A mean, median, 90th percentile and count per quarter (null where there is no data). */
export interface Series {
  mean: (number | null)[];
  median: (number | null)[];
  p90: (number | null)[];
  n: number[];
}

/** A directory of the table: [path, lines reviewed in each of `table_quarters`,
 * reviewers' weekday attention-set hours and turns in each of the last four]. */
export type DirEntry = [string, number[], number[], number[], OwnFigures?];
/** Who reviewed, against the OWNERS files, over the table's four quarters: [reviewers, how many of them did
 * half the review, people listed in an OWNERS file there or below, how many of those reviewed there, lines
 * reviewed by an owner of the file, lines of changes by people not yet committers, those two owners approved]. */
export type OwnFigures = [number, number, number, number, number, number, number];

export interface All {
  quarters: string[];
  /** The first quarter with attention-set figures. */
  attention_from: string;
  min_dir_lines: number;
  commits: number[];
  human: number[];
  reviewed: number[];
  reviewed_lines: number[];
  reviewers: number[];
  /** A reviewer's wait: entering the attention set to their first answer, in weekday hours. */
  reply: Series;
  attention: { hours: (number | null)[]; turns: (number | null)[]; reviewers: (number | null)[] };
  /** The table's quarters, oldest first: the one before its first, then its four. */
  table_quarters: string[];
  dirs: DirEntry[];
  /** Everything's OWNERS figures and the day of the OWNERS files read; null when they weren't. */
  owners?: { at: string; all: OwnFigures } | null;
}

/** A reviewer's quarter: [commits reviewed, lines reviewed, weekday hours in the attention set, turns in it,
 * weekday hours from asked to first answer (summed), answers]. */
export type PersonQuarter = [number, number, number, number, number, number];
/** A reviewer's year: its quarters by number ("1".."4"). */
export interface PersonYear {
  q: Record<string, PersonQuarter>;
}
/** A reviewer's directories in one quarter: [3-level directory, lines reviewed, attention hours, turns]. */
export type PersonDir = [string, number, number, number];
/** <name>.json (cosh/review_load.py): one reviewer's years, and their directories in the table's
 * quarters. */
export interface PersonFile {
  v: 2;
  years: Record<string, PersonYear>;
  dirs: Record<string, PersonDir[]>;
}

export interface Person {
  /** By quarter ("2026Q3"). */
  quarters: Map<string, PersonQuarter>;
  /** By table quarter, the files that exist. */
  dirs: Map<string, PersonDir[]>;
}

/** "2026Q3" as "Q3 2026". */
export const quarterLabel = (q: string) => `Q${q.slice(5)} ${q.slice(0, 4)}`;

/** The years `quarters` span, oldest first. */
export const yearsOf = (quarters: string[]) => [...new Set(quarters.map((q) => q.slice(0, 4)))];

/** A reviewer's files, merged; null when none of the years has one. */
export function buildPerson(all: Pick<All, 'quarters' | 'table_quarters'>, years: Map<string, PersonYear>,
  dirs: Map<string, PersonDir[]>): Person | null {
  const quarters = new Map<string, PersonQuarter>();
  for (const q of all.quarters) {
    const v = years.get(q.slice(0, 4))?.q?.[q.slice(5)];
    if (Array.isArray(v) && v.length === 6 && v.every((x) => Number.isFinite(x))) quarters.set(q, v);
  }
  if (!quarters.size) return null;
  const kept = new Map<string, PersonDir[]>();
  for (const q of all.table_quarters.slice(1)) {
    const rows = dirs.get(q);
    if (Array.isArray(rows)) kept.set(q, rows.filter((r) => Array.isArray(r) && typeof r[0] === 'string'));
  }
  return { quarters, dirs: kept };
}

export const ratio = (a: number | null | undefined, b: number | null | undefined) =>
  (a !== null && a !== undefined && b ? a / b : null);

/** Mean lines reviewed per reviewer, per quarter. */
export const meanLines = (all: Pick<All, 'reviewed_lines' | 'reviewers'>) =>
  all.reviewed_lines.map((v, i) => ratio(v, all.reviewers[i]));

/** Mean weekday hours in the attention set per reviewer, per quarter. */
export const meanAttention = (all: Pick<All, 'attention'>) =>
  all.attention.hours.map((v, i) => ratio(v, all.attention.reviewers[i]));

/** `v`'s place on a log scale from `lo` (0) to `hi` (1), clamped; null without a positive `v`. */
export function logShade(v: number, lo: number, hi: number): number | null {
  if (!(v > 0) || !(lo > 0) || !(hi > lo)) return null;
  return Math.min(1, Math.max(0, Math.log(v / lo) / Math.log(hi / lo)));
}

/** The change from `prev` to `v`, as a fraction (0.1: 10% more); null without both. */
export const change = (v: number | null | undefined, prev: number | null | undefined) =>
  (v !== null && v !== undefined && prev ? v / prev - 1 : null);

/** A reviewer's figure per quarter of `quarters` (null where they have none). */
export function personSeries(p: Person, quarters: string[], f: (q: PersonQuarter) => number | null): (number | null)[] {
  return quarters.map((q) => {
    const v = p.quarters.get(q);
    return v ? f(v) : null;
  });
}

// ---- The directory table

/** A row's sums over the table's quarters. */
export interface DirStats {
  /** Lines reviewed in each of the five `table_quarters`. */
  lines: number[];
  /** Weekday attention-set hours and turns in each of the last four. */
  hours: number[];
  turns: number[];
}

export interface DirNode extends DirStats {
  /** "d:<path>" for a directory, "o:<path>" for a directory's unlisted rest. */
  key: string;
  kind: 'dir' | 'other';
  path: string;
  name: string;
  children: DirNode[];
  /** The looked-up reviewer's lines and attention there, over the last four quarters. */
  you: { lines: number; hours: number; turns: number };
  /** The OWNERS figures; an "Other" row has only the lines (its head counts are null). */
  own: OwnRow | null;
}

/** A row of the OWNERS table. */
export interface OwnRow {
  reviewers: number | null;
  half: number | null;
  listed: number | null;
  active: number | null;
  /** Lines reviewed by an owner of the file. */
  ownerLines: number;
  /** Lines of changes by people not yet committers, and those two owners approved. */
  newLines: number;
  newTwo: number;
}

export const ownRow = (f: OwnFigures): OwnRow => ({ reviewers: f[0], half: f[1], listed: f[2], active: f[3],
  ownerLines: f[4], newLines: f[5], newTwo: f[6] });

const zeros = (n: number) => Array.from({ length: n }, () => 0);
const parentOf = (path: string) => path.replace(/[^/]+\/$/, '');

/** The table's tree: the listed directories under their parents, each with an "Other" child for what
 * its listed children don't cover (the smaller directories and the files directly in it), and a root
 * "Other" likewise. With `p`, each node also carries that reviewer's figures over the four quarters:
 * a directory of theirs that isn't listed counts in its nearest listed parent's "Other". */
export function dirTree(all: Pick<All, 'dirs' | 'table_quarters'>, p: Person | null): DirNode[] {
  const nq = all.table_quarters.length;
  const nodes = new Map<string, DirNode>();
  const node = (key: string, kind: DirNode['kind'], path: string, s?: DirEntry): DirNode => ({ key, kind, path,
    name: kind === 'other' ? '' : path.replace(/^(?:.*\/)?([^/]+\/)$/, '$1'), children: [],
    lines: s ? [...s[1]] : zeros(nq), hours: s ? [...s[2]] : zeros(nq - 1), turns: s ? [...s[3]] : zeros(nq - 1),
    you: { lines: 0, hours: 0, turns: 0 }, own: s?.[4] ? ownRow(s[4]) : null });
  for (const e of all.dirs) nodes.set(e[0], node(`d:${e[0]}`, 'dir', e[0], e));
  const roots: DirNode[] = [];
  for (const n of nodes.values()) {
    const parent = nodes.get(parentOf(n.path));
    (parent ? parent.children : roots).push(n);
  }
  // What a directory's listed children leave: its "Other".
  const others = new Map<string, DirNode>();
  for (const n of nodes.values()) {
    if (!n.children.length) continue;
    const o = node(`o:${n.path}`, 'other', n.path);
    o.lines = n.lines.map((v, i) => Math.max(0, v - n.children.reduce((s, c) => s + c.lines[i], 0)));
    o.hours = n.hours.map((v, i) => Math.max(0, v - n.children.reduce((s, c) => s + c.hours[i], 0)));
    o.turns = n.turns.map((v, i) => Math.max(0, v - n.children.reduce((s, c) => s + c.turns[i], 0)));
    if (n.own && n.children.every((c) => c.own)) {
      const left = (f: (r: OwnRow) => number) => Math.max(0, f(n.own!) - n.children.reduce((s, c) => s + f(c.own!), 0));
      o.own = { reviewers: null, half: null, listed: null, active: null, ownerLines: left((r) => r.ownerLines),
        newLines: left((r) => r.newLines), newTwo: left((r) => r.newTwo) };
    }
    others.set(n.path, o);
  }
  if (p) {
    const add = (n: DirNode, r: PersonDir) => {
      n.you.lines += r[1];
      n.you.hours += r[2];
      n.you.turns += r[3];
    };
    let rootOther: DirNode | null = null;
    for (const rows of p.dirs.values()) {
      for (const r of rows) {
        // Every listed ancestor counts it; the deepest one's "Other" does when the directory itself isn't listed.
        let path = r[0];
        let deepest: DirNode | null = null;
        for (; path; path = parentOf(path)) {
          const n = nodes.get(path);
          if (!n) continue;
          deepest ??= n;
          add(n, r);
        }
        if (!deepest) {
          rootOther ??= node('o:', 'other', '');
          add(rootOther, r);
        } else if (deepest.path !== r[0]) {
          const o = others.get(deepest.path);
          if (o) add(o, r);
        }
      }
    }
    if (rootOther) roots.push(rootOther);
  }
  for (const [path, o] of others) {
    if (o.lines.some((v) => v > 0) || o.turns.some((v) => v > 0) || o.you.lines || o.you.turns) nodes.get(path)!.children.push(o);
  }
  return roots;
}

/** One visible row of the table: a node, or a level's "N more" row. */
export interface DirRow {
  key: string;
  node: DirNode | null;
  more?: number;
  depth: number;
  expandable: boolean;
  expanded: boolean;
}

const sum = (xs: number[]) => xs.reduce((a, b) => a + b, 0);
/** A node's lines reviewed over the table's four quarters. */
export const totalLines = (n: DirStats) => sum(n.lines.slice(1));

/** The rows to show, given which are open (`expanded`, by key): each level by lines reviewed, the
 * reviewer's first when `byYou`, "Other" last. A level lists its first `shown` directories and a
 * "more" row (key "m:" + the parent's key) that shows the rest. */
export function dirRows(roots: DirNode[], expanded: ReadonlySet<string>, byYou: boolean, shown = 12): DirRow[] {
  const out: DirRow[] = [];
  const order = (a: DirNode, b: DirNode) => Number(a.kind === 'other') - Number(b.kind === 'other') ||
    (byYou ? b.you.lines - a.you.lines : 0) || totalLines(b) - totalLines(a) || (a.key < b.key ? -1 : 1);
  const walk = (ns: DirNode[], depth: number, parentKey: string) => {
    const sorted = [...ns].sort(order);
    const dirs = sorted.filter((n) => n.kind === 'dir').length;
    const moreKey = `m:${parentKey}`;
    const all = dirs <= shown + 1 || expanded.has(moreKey);
    sorted.forEach((n, i) => {
      if (!all && i === shown) out.push({ key: moreKey, node: null, more: dirs - shown, depth, expandable: true, expanded: false });
      if (!all && i >= shown && n.kind === 'dir') return;
      const expandable = n.children.length > 0;
      const open = expandable && expanded.has(n.key);
      out.push({ key: n.key, node: n, depth, expandable, expanded: open });
      if (open) walk(n.children, depth + 1, n.key);
    });
  };
  walk(roots, 0, 'root');
  return out;
}

/** Mean weekday hours a reviewer had a change there in their attention set, per quarter (null under
 * `minTurns` turns). */
export const meanHours = (n: DirStats, minTurns = 5) =>
  n.hours.map((h, i) => (n.turns[i] >= minTurns ? h / n.turns[i] : null));

/** Everyone's mean hours per turn in each of the table's four quarters, from the top-level rows. */
export function overallHours(roots: DirNode[], nq: number): (number | null)[] {
  return Array.from({ length: nq - 1 }, (_, i) => ratio(sum(roots.map((n) => n.hours[i])), sum(roots.map((n) => n.turns[i]))));
}

/** A wait's shade against the typical one: -1 (half or less: green) .. 0 (typical) .. 1 (twice or more: red). */
export function waitShade(v: number | null, typical: number | null): number {
  if (v === null || !typical || !(v > 0)) return 0;
  return Math.max(-1, Math.min(1, Math.log2(v / typical)));
}
