// The data-flow inventory (config/dataflow.json) as a graph: what
// dataflow.html draws and what its "what to rerun" planner walks. No DOM
// here, so the unit tests can run it against the real file.
// scripts/dataflow.py does the same checks and planning for the command line.

export type Tier = 'raw' | 'labels' | 'derived' | 'analysis' | 'published' | 'config';
export type Refresh = 'routine' | 'optional' | 'one-off' | 'analysis' | 'automatic';

export interface Group {
  id: string;
  name: string;
  purpose: string;
}

export interface Source {
  id: string;
  group: string;
  name: string;
  url?: string;
  kind: string;
  purpose: string;
  access?: string;
  load_rules?: string;
  coverage?: string;
  notes?: string;
}

export interface TableInfo {
  name: string;
  rows?: number | null;
  rows_approx?: boolean;
  purpose: string;
}

export interface Store {
  id: string;
  group: string;
  path: string;
  /** A short name, for a store that is a family of files rather than one path. */
  name?: string;
  kind: string;
  tier: Tier;
  tracked_in_git: boolean;
  /** Globs of the tracked files, when the store is a family of them. */
  git_paths?: string[];
  rebuildable: boolean;
  never_delete?: boolean;
  size?: string | null;
  size_as_of?: string;
  tables?: TableInfo[];
  files?: string;
  purpose: string;
  notes?: string;
}

export interface Step {
  id: string;
  group: string;
  command: string;
  code: string[];
  purpose: string;
  inputs: string[];
  outputs: string[];
  network: boolean;
  lock?: string | null;
  incremental?: string;
  duration?: string | null;
  token_cost?: string | null;
  cost_source?: string | null;
  refresh: Refresh;
  approval?: string;
  notes?: string;
}

export interface PageInfo {
  id: string;
  group: string;
  path: string;
  title: string;
  purpose: string;
  entry_script?: string | null;
  reads: string[];
  sources_line?: string | null;
  notes?: string;
}

export interface Dataflow {
  schema_version: number;
  updated: string;
  about: string;
  groups: Group[];
  sources: Source[];
  stores: Store[];
  steps: Step[];
  pages: PageInfo[];
}

export type Kind = 'source' | 'store' | 'step' | 'page';

export interface Node {
  id: string;
  kind: Kind;
  group: string;
  /** Short name for the graph and for links. */
  label: string;
  source?: Source;
  store?: Store;
  step?: Step;
  page?: PageInfo;
}

export interface Graph {
  nodes: Map<string, Node>;
  /** Flow edges, [from, to]: input → step, step → output, store → page. */
  edges: [string, string][];
  out: Map<string, string[]>;
  in: Map<string, string[]>;
  /** What is wrong with the file: unknown ids, duplicates, bad enums. */
  problems: string[];
}

export const TIERS: Tier[] = ['raw', 'labels', 'derived', 'analysis', 'published', 'config'];
export const REFRESHES: Refresh[] = ['routine', 'optional', 'one-off', 'analysis', 'automatic'];

/** A path's last segment. A directory keeps its trailing slash and its
 * parent, so data/public/radar/raw/ and data/private/bugs/raw/ differ. */
export function baseName(path: string): string {
  const m = /((?:[^/]+\/)?[^/]+\/|[^/]+)$/.exec(path);
  return m ? m[1] : path;
}

export function buildGraph(d: Dataflow): Graph {
  const nodes = new Map<string, Node>();
  const problems: string[] = [];
  const groups = new Set(d.groups.map((g) => g.id));
  const add = (n: Node) => {
    if (nodes.has(n.id)) problems.push(`duplicate id ${n.id}`);
    if (!groups.has(n.group)) problems.push(`${n.id}: unknown group ${n.group}`);
    nodes.set(n.id, n);
  };
  for (const s of d.sources) add({ id: s.id, kind: 'source', group: s.group, label: s.name, source: s });
  for (const s of d.stores) {
    if (!TIERS.includes(s.tier)) problems.push(`${s.id}: unknown tier ${s.tier}`);
    add({ id: s.id, kind: 'store', group: s.group, label: s.name ?? baseName(s.path), store: s });
  }
  for (const s of d.steps) {
    if (!REFRESHES.includes(s.refresh)) problems.push(`${s.id}: unknown refresh ${s.refresh}`);
    add({ id: s.id, kind: 'step', group: s.group, label: s.id, step: s });
  }
  for (const p of d.pages) add({ id: p.id, kind: 'page', group: p.group, label: baseName(p.path), page: p });

  const edges: [string, string][] = [];
  const edge = (from: string, to: string, owner: string, want: Kind[]) => {
    const other = nodes.get(from === owner ? to : from);
    if (!other) problems.push(`${owner}: unknown id ${from === owner ? to : from}`);
    else if (!want.includes(other.kind)) problems.push(`${owner}: ${other.id} is a ${other.kind}`);
    else edges.push([from, to]);
  };
  for (const s of d.steps) {
    // A step that resumes from its own output (classify reading labels) is
    // drawn only as writing it, so the graph has no loop there.
    for (const i of s.inputs) if (!s.outputs.includes(i)) edge(i, s.id, s.id, ['source', 'store']);
    for (const o of s.outputs) edge(s.id, o, s.id, ['store']);
  }
  for (const p of d.pages) for (const r of p.reads) edge(r, p.id, p.id, ['store']);

  const out = new Map<string, string[]>();
  const inn = new Map<string, string[]>();
  for (const id of nodes.keys()) {
    out.set(id, []);
    inn.set(id, []);
  }
  for (const [a, b] of edges) {
    out.get(a)!.push(b);
    inn.get(b)!.push(a);
  }
  return { nodes, edges, out, in: inn, problems };
}

/** Everything reachable from `start` along (dir 'out') or against ('in')
 * the flow, `start` included. `via` can refuse to pass through a node. */
export function reach(
  g: Graph,
  start: Iterable<string>,
  dir: 'out' | 'in',
  via: (n: Node) => boolean = () => true,
): Set<string> {
  const seen = new Set<string>(start);
  const todo = [...seen];
  while (todo.length) {
    const id = todo.pop()!;
    for (const next of g[dir].get(id) ?? []) {
      if (seen.has(next) || !via(g.nodes.get(next)!)) continue;
      seen.add(next);
      todo.push(next);
    }
  }
  return seen;
}

/** Each node's column: the longest path to it from a node with nothing
 * upstream, over the nodes in `keep`. Edges that would close a cycle are
 * ignored, so a loop in the file still gets drawn. */
export function layers(g: Graph, keep: Set<string> = new Set(g.nodes.keys())): Map<string, number> {
  const depth = new Map<string, number>();
  const open = new Set<string>();
  const visit = (id: string): number => {
    const known = depth.get(id);
    if (known !== undefined) return known;
    open.add(id);
    let d = 0;
    for (const p of g.in.get(id) ?? []) {
      if (!keep.has(p) || open.has(p)) continue;
      d = Math.max(d, visit(p) + 1);
    }
    open.delete(id);
    depth.set(id, d);
    return d;
  };
  for (const id of g.nodes.keys()) if (keep.has(id)) visit(id);
  return depth;
}

export interface PlanStep {
  step: Step;
  /** Reached only through a step that costs tokens or needs approval. */
  afterOptional: boolean;
}

export interface Plan {
  steps: PlanStep[];
  /** Tracked stores the steps write: what to commit. */
  commit: Store[];
  pages: PageInfo[];
}

/** What to rerun, in order, when the nodes in `changed` have new data, and
 * what that changes in git. Routine and optional steps carry the change on;
 * one-off backfills and analysis scripts don't run as part of an update. */
export function plan(g: Graph, changed: Iterable<string>): Plan {
  const runs = (n: Node, optional: boolean) =>
    n.kind !== 'step' || n.step!.refresh === 'routine' || n.step!.refresh === 'automatic' ||
    (optional && n.step!.refresh === 'optional');
  const start = [...changed];
  const all = reach(g, start, 'out', (n) => runs(n, true));
  const sure = reach(g, start, 'out', (n) => runs(n, false));
  const depth = layers(g);
  const order = [...g.nodes.keys()];
  const byFlow = (a: string, b: string) =>
    depth.get(a)! - depth.get(b)! || order.indexOf(a) - order.indexOf(b);
  const ids = [...all].filter((id) => !start.includes(id)).sort(byFlow);
  const of = (kind: Kind) => ids.map((id) => g.nodes.get(id)!).filter((n) => n.kind === kind);
  return {
    steps: of('step').map((n) => ({ step: n.step!, afterOptional: !sure.has(n.id) })),
    commit: of('store').map((n) => n.store!).filter((s) => s.tracked_in_git),
    pages: of('page').map((n) => n.page!),
  };
}

export interface Placed {
  id: string;
  col: number;
  row: number;
}

/** Columns from `layers`, then rows ordered to keep edges short: a few
 * sweeps placing each node at the mean row of its neighbours in the column
 * before (then after). */
export function layout(g: Graph, keep: Set<string>): Placed[] {
  const depth = layers(g, keep);
  // Pages share the last column. Then whatever has nothing upstream and
  // isn't a source (config files, a store whose writer is hidden) moves
  // right, to just before its first reader, leaving column 0 to the sources.
  const last = Math.max(0, ...depth.values());
  for (const id of depth.keys()) if (g.nodes.get(id)!.kind === 'page') depth.set(id, last);
  for (const id of depth.keys()) {
    const n = g.nodes.get(id)!;
    const outs = (g.out.get(id) ?? []).filter((o) => keep.has(o));
    if (n.kind === 'source' || n.kind === 'page' || !outs.length) continue;
    if ((g.in.get(id) ?? []).some((i) => keep.has(i))) continue;
    depth.set(id, Math.max(0, Math.min(...outs.map((o) => depth.get(o)!)) - 1));
  }
  const cols: string[][] = [];
  for (const [id, c] of depth) (cols[c] ??= []).push(id);
  for (let c = 0; c < cols.length; c++) cols[c] ??= [];
  const row = new Map<string, number>();
  const number = (col: string[]) => col.forEach((id, i) => row.set(id, i));
  cols.forEach(number);
  const sweep = (col: string[], dir: 'in' | 'out') => {
    const want = new Map<string, number>();
    for (const id of col) {
      const near = (g[dir].get(id) ?? []).filter((n) => keep.has(n) && row.has(n));
      want.set(id, near.length ? near.reduce((s, n) => s + row.get(n)!, 0) / near.length : row.get(id)!);
    }
    col.sort((a, b) => want.get(a)! - want.get(b)! || row.get(a)! - row.get(b)!);
    number(col);
  };
  for (let pass = 0; pass < 4; pass++) {
    for (let c = 1; c < cols.length; c++) sweep(cols[c], 'in');
    for (let c = cols.length - 2; c >= 0; c--) sweep(cols[c], 'out');
  }
  return cols.flatMap((col, c) => col.map((id, r) => ({ id, col: c, row: r })));
}
