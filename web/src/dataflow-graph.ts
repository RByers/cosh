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

/** The fallback for narrow screens: `flowDepth`'s layers, each ordered to
 * keep edges short (a few sweeps placing each node at the mean place of its
 * neighbours in the layer above, then below), then wrapped into even lines
 * of at most `perLine` nodes. Edges may pass behind boxes; `route` is the
 * drawing for screens wide enough. */
export function layout(g: Graph, keep: Set<string>, perLine = Infinity): Placed[] {
  const depth = flowDepth(g, keep);
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

/** Each kept node's layer, top to bottom, numbered without gaps: from
 * `layers`, with pages sharing the last, and config files (anything with
 * nothing upstream that isn't a source) just above their first reader, so
 * the top layer holds only sources and config. */
export function flowDepth(g: Graph, keep: Set<string>): Map<string, number> {
  const depth = layers(g, keep);
  const last = Math.max(0, ...depth.values());
  for (const id of depth.keys()) if (g.nodes.get(id)!.kind === 'page') depth.set(id, last);
  for (const id of depth.keys()) {
    const n = g.nodes.get(id)!;
    const outs = (g.out.get(id) ?? []).filter((o) => keep.has(o));
    // Sources stay at the top, except a source's per-reader copy (splitShared).
    if ((n.kind === 'source' && baseId(id) === id) || n.kind === 'page' || !outs.length) continue;
    if ((g.in.get(id) ?? []).some((i) => keep.has(i))) continue;
    depth.set(id, Math.max(0, Math.min(...outs.map((o) => depth.get(o)!)) - 1));
  }
  const used = [...new Set(depth.values())].sort((a, b) => a - b);
  const index = new Map(used.map((d, i) => [d, i]));
  for (const [id, d] of depth) depth.set(id, index.get(d)!);
  return depth;
}

export interface RouteSizes {
  nodeW: number;
  /** A chip: a config file or the model, drawn beside the step that reads it. */
  chipW: number;
  /** Space between a chip and its reader (where their link runs). */
  chipGap: number;
  /** Width a passing edge takes in a layer it crosses. */
  laneW: number;
  /** Least space between two neighbours in a layer. */
  gap: number;
}

export interface Routed {
  /** Centre x of each box, and its layer. */
  nodes: Map<string, { x: number; layer: number }>;
  /** Chips ("<id>@<reader>", from splitShared): centre x, the reader, and
   * the side of the reader it sits on. */
  chips: Map<string, { x: number; reader: string; side: 'left' | 'right' }>;
  /** Each edge between boxes: its x in each layer from the source's to the
   * target's (the middle ones are lanes between boxes). */
  edges: { from: string; to: string; xs: number[]; layer: number }[];
  /** Total width, and the number of layers. */
  width: number;
  layers: number;
  /** Pairs of edges that cross. */
  crossings: number;
  /** Each layer's items, left to right (lanes as "<from>><to>#<layer>"). */
  order: string[][];
}

/** What a copy made by `splitShared` stands for: "<id>@<reader>" -> id. */
export const baseId = (id: string) => {
  const at = id.indexOf('@', id.lastIndexOf('/') + 1);
  return at > 0 ? id.slice(0, at) : id;
};

/** A layered drawing in which no edge passes behind a box and, where the
 * graph allows, no two edges cross:
 * - Copies of shared inputs (`splitShared`) become chips beside their
 *   reader, alternately left and right, joined to it by a short link.
 * - An edge that skips layers gets a lane (a waypoint) in each layer it
 *   crosses, so it runs between boxes.
 * - Each layer is ordered to minimise crossings: barycentre sweeps, swaps
 *   of neighbours and sifting (each item to its best place in its layer),
 *   from several shuffled starts with a fixed seed, keeping the best.
 * - x positions are pulled to the mean of each item's neighbours, each
 *   layer placed as close to that as its order and `gap` allow (least
 *   squares, by pooling adjacent blocks), so chains run straight. */
export function route(g: Graph, keep: Set<string>, size: RouteSizes): Routed {
  const isChip = (id: string) => baseId(id) !== id && (g.out.get(id) ?? []).some((o) => keep.has(o));
  const chipsOf = new Map<string, string[]>();
  for (const id of [...keep].sort()) {
    if (!isChip(id)) continue;
    const reader = (g.out.get(id) ?? []).find((o) => keep.has(o))!;
    (chipsOf.get(reader) ?? chipsOf.set(reader, []).get(reader)!).push(id);
  }
  const boxes = new Set([...keep].filter((id) => !isChip(id)));
  const depth = flowDepth(g, boxes);
  const nLayers = Math.max(-1, ...depth.values()) + 1;
  // Extents of an item left and right of its box's centre: a box with its
  // chips (even ones on the left, odd on the right), or a lane.
  const side = (reader: string, k: number) => (k % 2 ? 'right' : 'left');
  const ext = (id: string, s: 'left' | 'right') => {
    if (!g.nodes.has(id)) return size.laneW / 2;
    const n = (chipsOf.get(id) ?? []).filter((_, k) => side(id, k) === s).length;
    return size.nodeW / 2 + n * (size.chipW + size.chipGap);
  };
  const layerOf = new Map<string, number>(depth);
  const down = new Map<string, string[]>();
  const up = new Map<string, string[]>();
  const link = (a: string, b: string) => {
    (down.get(a) ?? down.set(a, []).get(a)!).push(b);
    (up.get(b) ?? up.set(b, []).get(b)!).push(a);
  };
  const chains: { from: string; to: string; ids: string[] }[] = [];
  for (const [a, b] of g.edges) {
    if (!depth.has(a) || !depth.has(b) || depth.get(b)! <= depth.get(a)!) continue;
    const ids = [a];
    for (let l = depth.get(a)! + 1; l < depth.get(b)!; l++) {
      const lane = `${a}>${b}#${l}`;
      layerOf.set(lane, l);
      ids.push(lane);
    }
    ids.push(b);
    for (let i = 1; i < ids.length; i++) link(ids[i - 1], ids[i]);
    chains.push({ from: a, to: b, ids });
  }
  const rows: string[][] = Array.from({ length: nLayers }, () => []);
  for (const [id, l] of layerOf) rows[l].push(id);

  // ---- order
  const pos = new Map<string, number>();
  const number = (row: string[]) => row.forEach((id, i) => pos.set(id, i));
  rows.forEach(number);
  const crossBetween = (l: number) => {
    const segs: [number, number][] = [];
    for (const id of rows[l]) for (const b of down.get(id) ?? []) segs.push([pos.get(id)!, pos.get(b)!]);
    let n = 0;
    for (let i = 0; i < segs.length; i++) {
      for (let j = i + 1; j < segs.length; j++) {
        if ((segs[i][0] - segs[j][0]) * (segs[i][1] - segs[j][1]) < 0) n++;
      }
    }
    return n;
  };
  const total = () => {
    let n = 0;
    for (let l = 0; l + 1 < nLayers; l++) n += crossBetween(l);
    return n;
  };
  const local = (l: number) => (l > 0 ? crossBetween(l - 1) : 0) + (l + 1 < nLayers ? crossBetween(l) : 0);
  const sweep = (l: number, near: Map<string, string[]>) => {
    const row = rows[l];
    const want = new Map<string, number>();
    for (const id of row) {
      const ns = near.get(id) ?? [];
      want.set(id, ns.length ? ns.reduce((t, n) => t + pos.get(n)!, 0) / ns.length : pos.get(id)!);
    }
    row.sort((a, b) => want.get(a)! - want.get(b)! || pos.get(a)! - pos.get(b)!);
    number(row);
  };
  const transpose = () => {
    let better = true;
    for (let round = 0; better && round < 20; round++) {
      better = false;
      for (let l = 0; l < nLayers; l++) {
        const row = rows[l];
        for (let i = 0; i + 1 < row.length; i++) {
          const before = local(l);
          [row[i], row[i + 1]] = [row[i + 1], row[i]];
          number(row);
          if (local(l) < before) better = true;
          else {
            [row[i], row[i + 1]] = [row[i + 1], row[i]];
            number(row);
          }
        }
      }
    }
  };
  const sift = () => {
    let better = true;
    for (let round = 0; better && round < 10; round++) {
      better = false;
      for (let l = 0; l < nLayers; l++) {
        const row = rows[l];
        for (const id of [...row]) {
          const from = row.indexOf(id);
          row.splice(from, 1);
          let bestAt = from;
          let bestC = Infinity;
          for (let at = 0; at <= row.length; at++) {
            row.splice(at, 0, id);
            number(row);
            const c = local(l);
            if (c < bestC || (c === bestC && at === from)) {
              bestC = c;
              bestAt = at;
            }
            row.splice(at, 1);
          }
          row.splice(bestAt, 0, id);
          number(row);
          if (bestAt !== from) better = true;
        }
      }
    }
  };
  // As many shuffled starts as the graph's size allows; sifting only while
  // it's cheap. A fixed seed keeps the drawing the same on every load.
  const items = layerOf.size;
  const restarts = Math.max(1, Math.min(40, Math.floor(6000 / Math.max(1, items))));
  const cheap = items <= 160;
  let seed = 7;
  const rand = () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648;
  let best = rows.map((r) => [...r]);
  let bestN = total();
  for (let start = 0; start < restarts && bestN > 0; start++) {
    if (start > 0) {
      for (const row of rows) {
        for (let i = row.length - 1; i > 0; i--) {
          const j = Math.floor(rand() * (i + 1));
          [row[i], row[j]] = [row[j], row[i]];
        }
        number(row);
      }
    }
    for (let pass = 0; pass < 8 && bestN > 0; pass++) {
      for (let l = 1; l < nLayers; l++) sweep(l, up);
      for (let l = nLayers - 2; l >= 0; l--) sweep(l, down);
      transpose();
      if (cheap) sift();
      const n = total();
      if (n < bestN) {
        bestN = n;
        best = rows.map((r) => [...r]);
      }
    }
  }
  rows.splice(0, rows.length, ...best);
  rows.forEach(number);

  // ---- x positions (box centres)
  const x = new Map<string, number>();
  const sep = (a: string, b: string) => ext(a, 'right') + ext(b, 'left') + size.gap;
  for (const row of rows) {
    let at = 0;
    row.forEach((id, i) => {
      at = i ? at + sep(row[i - 1], id) : ext(id, 'left');
      x.set(id, at);
    });
  }
  const place = (row: string[], want: Map<string, number>) => {
    // The closest placement to `want` (least squares) that keeps the order
    // and `sep`: pool adjacent blocks while they would overlap, each block
    // at the mean of its members' wanted positions less their offsets.
    type Block = { start: number; sum: number; n: number; ids: string[]; offs: number[] };
    const blocks: Block[] = [];
    for (const id of row) {
      let b: Block = { start: want.get(id)!, sum: want.get(id)!, n: 1, ids: [id], offs: [0] };
      while (blocks.length) {
        const prev = blocks[blocks.length - 1];
        const shift = prev.offs[prev.offs.length - 1] + sep(prev.ids[prev.ids.length - 1], b.ids[0]);
        if (prev.start + shift <= b.start) break;
        blocks.pop();
        b = {
          start: 0,
          sum: prev.sum + b.sum - shift * b.n,
          n: prev.n + b.n,
          ids: [...prev.ids, ...b.ids],
          offs: [...prev.offs, ...b.offs.map((o) => o + shift)],
        };
        b.start = b.sum / b.n;
      }
      blocks.push(b);
    }
    for (const b of blocks) b.ids.forEach((id, k) => x.set(id, b.start + b.offs[k]));
  };
  const pull = (l: number, near: (id: string) => string[]) => {
    const want = new Map<string, number>();
    for (const id of rows[l]) {
      const ns = near(id);
      want.set(id, ns.length ? ns.reduce((t, n) => t + x.get(n)!, 0) / ns.length : x.get(id)!);
    }
    place(rows[l], want);
  };
  const both = (id: string) => [...(up.get(id) ?? []), ...(down.get(id) ?? [])];
  for (let it = 0; it < 40; it++) {
    for (let l = 1; l < nLayers; l++) pull(l, (id) => up.get(id) ?? []);
    for (let l = nLayers - 2; l >= 0; l--) pull(l, (id) => down.get(id) ?? []);
  }
  for (let it = 0; it < 20; it++) for (let l = 0; l < nLayers; l++) pull(l, both);
  let lo = Infinity;
  let hi = -Infinity;
  for (const [id, cx] of x) {
    lo = Math.min(lo, cx - ext(id, 'left'));
    hi = Math.max(hi, cx + ext(id, 'right'));
  }
  if (!x.size) lo = hi = 0;
  const nodes = new Map<string, { x: number; layer: number }>();
  for (const [id, l] of depth) nodes.set(id, { x: x.get(id)! - lo, layer: l });
  const chips = new Map<string, { x: number; reader: string; side: 'left' | 'right' }>();
  for (const [reader, list] of chipsOf) {
    if (!nodes.has(reader)) continue;
    const counts = { left: 0, right: 0 };
    list.forEach((id, k) => {
      const s = side(reader, k);
      const n = counts[s]++;
      const off = size.nodeW / 2 + size.chipGap + size.chipW / 2 + n * (size.chipW + size.chipGap);
      chips.set(id, { x: nodes.get(reader)!.x + (s === 'left' ? -off : off), reader, side: s });
    });
  }
  return {
    nodes,
    chips,
    edges: chains.map((c) => ({ from: c.from, to: c.to, layer: depth.get(c.from)!, xs: c.ids.map((id) => x.get(id)! - lo) })),
    width: hi - lo,
    layers: nLayers,
    crossings: bestN,
    order: rows.map((r) => [...r]),
  };
}

/** The drawn graph: like `g` over `keep`, but each shared input that isn't
 * data flow (a config file, the Claude model) is drawn once per reader, as
 * "<id>@<reader>" (a chip beside it, in `route`), so no long edge fans out
 * from it across the drawing. */
export function splitShared(g: Graph, keep: Set<string>): { g: Graph; keep: Set<string> } {
  const shared = (n: Node) =>
    (n.kind === 'store' && n.store!.tier === 'config') || (n.kind === 'source' && n.source!.kind === 'model');
  const nodes = new Map<string, Node>();
  const edges: [string, string][] = [];
  for (const id of keep) {
    const n = g.nodes.get(id)!;
    if (!shared(n)) nodes.set(id, n);
  }
  const copied = new Set<string>();
  for (const [a, b] of g.edges) {
    if (!keep.has(a) || !keep.has(b)) continue;
    const n = g.nodes.get(a)!;
    if (shared(n)) {
      const copy = `${a}@${b}`;
      nodes.set(copy, { ...n, id: copy });
      edges.push([copy, b]);
      copied.add(a);
    } else edges.push([a, b]);
  }
  // A shared input that nothing kept reads is still drawn, once.
  for (const id of keep) if (shared(g.nodes.get(id)!) && !copied.has(id)) nodes.set(id, g.nodes.get(id)!);
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
  return { g: { nodes, edges, out, in: inn, problems: [] }, keep: new Set(nodes.keys()) };
}
