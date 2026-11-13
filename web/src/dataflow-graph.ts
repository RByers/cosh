// The data-flow inventory (config/dataflow.json) as a graph: what
// dataflow.html draws and what its "what to rerun" planner walks. No DOM
// here, so the unit tests can run it against the real file.
// scripts/dataflow.py does the same checks and planning for the command line.

export type Tier = 'raw' | 'labels' | 'derived' | 'analysis' | 'published' | 'config';
export type Refresh = 'routine' | 'optional' | 'one-off' | 'analysis' | 'maintenance';

export interface Source {
  id: string;
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
  /** What `python3 -m cosh update` runs, for a step it may run by itself. */
  run?: string;
  approval?: string;
  notes?: string;
}

export interface PageInfo {
  id: string;
  /** Words that name this page's analysis: nodes named with them feed only this page. */
  names?: string[];
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
  sources: Source[];
  stores: Store[];
  steps: Step[];
  pages: PageInfo[];
}

export type Kind = 'source' | 'store' | 'step' | 'page';

export interface Node {
  id: string;
  kind: Kind;
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
export const REFRESHES: Refresh[] = ['routine', 'optional', 'one-off', 'analysis', 'maintenance'];

/** A path's last segment. A directory keeps its trailing slash and its
 * parent, so data/public/radar/raw/ and data/private/bugs/raw/ differ. */
export function baseName(path: string): string {
  const m = /((?:[^/]+\/)?[^/]+\/|[^/]+)$/.exec(path);
  return m ? m[1] : path;
}

export function buildGraph(d: Dataflow): Graph {
  const nodes = new Map<string, Node>();
  const problems: string[] = [];
  const add = (n: Node) => {
    if (nodes.has(n.id)) problems.push(`duplicate id ${n.id}`);
    nodes.set(n.id, n);
  };
  for (const s of d.sources) add({ id: s.id, kind: 'source', label: s.name, source: s });
  for (const s of d.stores) {
    if (!TIERS.includes(s.tier)) problems.push(`${s.id}: unknown tier ${s.tier}`);
    add({ id: s.id, kind: 'store', label: s.name ?? baseName(s.path), store: s });
  }
  for (const s of d.steps) {
    if (!REFRESHES.includes(s.refresh)) problems.push(`${s.id}: unknown refresh ${s.refresh}`);
    add({ id: s.id, kind: 'step', label: s.id, step: s });
  }
  for (const p of d.pages) add({ id: p.id, kind: 'page', label: p.title, page: p });

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

/** Each node's layer: the longest path to it from a node with nothing
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
 * one-off backfills, analysis scripts and maintenance don't run as part of
 * an update. */
export function plan(g: Graph, changed: Iterable<string>): Plan {
  const runs = (n: Node, optional: boolean) =>
    n.kind !== 'step' || n.step!.refresh === 'routine' || (optional && n.step!.refresh === 'optional');
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

/** The pages the page filter offers: those that read something fetched
 * (not only config), in the inventory's order. */
export function flowPages(g: Graph): PageInfo[] {
  return [...g.nodes.values()]
    .filter((n) => n.kind === 'page' && [...reach(g, [n.id], 'in')].some((i) => g.nodes.get(i)!.kind === 'source'))
    .map((n) => n.page!);
}

/** The flow of `pages`: everything upstream of them, except maintenance
 * (which rewrites a store in place and so has nothing upstream). With
 * `extras`, also the steps no page needs (analyses, maintenance) that touch
 * it, with what they write and what they read; with `extras` and every
 * page, everything. */
export function scope(g: Graph, pages: string[], extras: boolean): Set<string> {
  const keep = reach(g, pages, 'in', (n) => n.step?.refresh !== 'maintenance');
  if (!extras) return keep;
  if (flowPages(g).every((p) => pages.includes(p.id))) return new Set(g.nodes.keys());
  const more: string[] = [];
  for (const n of g.nodes.values()) {
    if (n.kind !== 'step' || keep.has(n.id)) continue;
    if ([...n.step!.inputs, ...n.step!.outputs].some((i) => keep.has(i))) more.push(n.id);
  }
  for (const id of reach(g, more, 'in')) keep.add(id);
  for (const id of more) for (const o of g.out.get(id) ?? []) keep.add(o);
  return keep;
}

export interface Placed {
  id: string;
  /** Flow layer: 0 at the top (sources), the last for pages. */
  layer: number;
  /** Line from the top: a layer wider than `perLine` takes several. */
  line: number;
  /** Place within the line, and how many share it. */
  pos: number;
  of: number;
}

/** Layers from `layers`, top to bottom: pages share the last, and config
 * files (anything with nothing upstream that isn't a source) sit just above
 * their first reader, so the top layer holds only sources and config. Each
 * layer is ordered to keep edges short (a few sweeps placing each node at
 * the mean place of its neighbours in the layer above, then below), then
 * wrapped into even lines of at most `perLine` nodes. */
export function layout(g: Graph, keep: Set<string>, perLine = Infinity): Placed[] {
  const depth = layers(g, keep);
  const last = Math.max(0, ...depth.values());
  for (const id of depth.keys()) if (g.nodes.get(id)!.kind === 'page') depth.set(id, last);
  for (const id of depth.keys()) {
    const n = g.nodes.get(id)!;
    const outs = (g.out.get(id) ?? []).filter((o) => keep.has(o));
    if (n.kind === 'source' || n.kind === 'page' || !outs.length) continue;
    if ((g.in.get(id) ?? []).some((i) => keep.has(i))) continue;
    depth.set(id, Math.max(0, Math.min(...outs.map((o) => depth.get(o)!)) - 1));
  }
  const byDepth: string[][] = [];
  for (const [id, d] of depth) (byDepth[d] ??= []).push(id);
  const rows = byDepth.filter((r) => r?.length);
  // A node's place as a fraction of its layer's width, so layers of
  // different widths compare.
  const at = new Map<string, number>();
  const number = (row: string[]) => row.forEach((id, i) => at.set(id, (i + 0.5) / row.length));
  rows.forEach(number);
  const sweep = (row: string[], dir: 'in' | 'out') => {
    const want = new Map<string, number>();
    for (const id of row) {
      const near = (g[dir].get(id) ?? []).filter((n) => keep.has(n) && at.has(n));
      want.set(id, near.length ? near.reduce((s, n) => s + at.get(n)!, 0) / near.length : at.get(id)!);
    }
    row.sort((a, b) => want.get(a)! - want.get(b)! || at.get(a)! - at.get(b)!);
    number(row);
  };
  for (let pass = 0; pass < 4; pass++) {
    for (let r = 1; r < rows.length; r++) sweep(rows[r], 'in');
    for (let r = rows.length - 2; r >= 0; r--) sweep(rows[r], 'out');
  }
  const out: Placed[] = [];
  let line = 0;
  rows.forEach((row, layer) => {
    const lines = Math.max(1, Math.ceil(row.length / Math.max(1, perLine)));
    const size = Math.ceil(row.length / lines); // 7 in lines of 6: 4 and 3
    for (let k = 0; k < lines; k++) {
      const part = row.slice(k * size, (k + 1) * size);
      part.forEach((id, pos) => out.push({ id, layer, line, pos, of: part.length }));
      line++;
    }
  });
  return out;
}
