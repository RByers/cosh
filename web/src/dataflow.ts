// The Data flow page (dataflow.html): a graph of how config/dataflow.json's
// sources, steps, stores and pages connect, drawn top to bottom, the facts
// of whatever is picked, a planner for what to rerun, and tables of every
// item. The page filter narrows all of them to what the chosen pages need.
// Wording is in the HTML; this fills in values. Everything goes into the
// DOM as text or attributes (the CSP forbids HTML sinks), and scripts set
// classes and custom properties, never styles.
import dataUrl from '../../config/dataflow.json?url';
import {
  baseId,
  buildGraph,
  flowPages,
  layout,
  plan,
  reach,
  route,
  scope,
  splitShared,
  type Dataflow,
  type Graph,
  type Routed,
  type Node,
  type Step,
  type Store,
} from './dataflow-graph.ts';
import { fill } from './text.ts';

const SVG = 'http://www.w3.org/2000/svg';
const REPO = 'https://github.com/RByers/cosh/blob/main/';

// Graph geometry, in SVG user units (CSS pixels at 1:1; the SVG is never
// wider than its box, so it never scrolls sideways).
const NODE_W = 128;
const NODE_H = 22;
const CHIP_W = 112; // a config file or the model, beside the step that reads it
const CHIP_GAP = 10;
const LANE_W = 6; // an edge passing through a layer
const GAP_X = 16;
const LAYER_GAP = 28; // between layers, where the edges run
const LINE_GAP = 8; // between the lines of one wrapped layer
const PAD = 8;
const CHAR_W = 6.02; // the 10px monospace label font (0.6 em, a little spare)
const MIN_SCALE = 0.8; // shrink a routed drawing at most this far, else wrap

const $ = <T extends Element = HTMLElement>(sel: string): T => {
  const e = document.querySelector<T>(sel);
  if (!e) throw new Error(`dataflow.html: no ${sel}`);
  return e;
};

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  text?: string | null,
  cls?: string,
): HTMLElementTagNameMap[K] {
  const e = document.createElement(tag);
  if (text) e.textContent = text;
  if (cls) e.className = cls;
  return e;
}

function svg<K extends keyof SVGElementTagNameMap>(tag: K, attrs: Record<string, string | number> = {}) {
  const e = document.createElementNS(SVG, tag) as SVGElementTagNameMap[K];
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, String(v));
  return e;
}

let data: Dataflow;
let graph: Graph;
let selected: string | null = null;
/** What the page filter and the extras box leave in view. */
let shown = new Set<string>();

/** The class that colours a node: its kind, or a store's tier. */
const tone = (n: Node) => (n.kind === 'store' ? `k-${n.store!.tier}` : `k-${n.kind}`);

const kindText = (n: Node): string => {
  if (n.kind === 'store') return `${n.store!.tier} store (${n.store!.kind})`;
  if (n.kind === 'source') return `source (${n.source!.kind})`;
  return n.kind;
};

/** A node's full name: a store's path (or family name), else its label. */
const full = (n: Node) => (n.kind === 'store' ? (n.store!.name ?? n.store!.path) : n.label);

/** A button that selects a node, wherever it appears. `short` shows only
 * the label (a path's last part), with the full name as its hover title. */
function link(id: string, short = false): HTMLElement {
  const n = graph.nodes.get(id);
  if (!n) return el('span', id);
  const mono = n.kind === 'source' || n.kind === 'page' || n.store?.name ? '' : ' df-mono';
  const b = el('button', short ? n.label : full(n), `df-link ${tone(n)}${mono}`);
  b.type = 'button';
  b.dataset.node = id;
  if (short) b.title = full(n);
  return b;
}

function links(ids: string[], short = false): HTMLElement {
  const ul = el('ul', null, 'df-links');
  for (const id of ids) ul.appendChild(el('li')).append(link(id, short));
  return ul;
}

/** An off-site link (always a new tab) to a file in the repository. */
function repoLink(path: string): HTMLAnchorElement {
  const a = el('a', path, 'df-mono');
  a.href = REPO + path.split('/').map(encodeURIComponent).join('/');
  a.target = '_blank';
  a.rel = 'noopener';
  return a;
}

function row(body: HTMLElement, n: Node, cells: (string | Node[] | HTMLElement | null | undefined)[]): void {
  const tr = el('tr');
  tr.dataset.node = n.id;
  const th = el('th');
  th.scope = 'row';
  th.append(link(n.id));
  tr.append(th);
  for (const c of cells) {
    const td = el('td');
    if (typeof c === 'string') td.textContent = c;
    else if (Array.isArray(c)) td.append(links(c.map((x) => x.id), true));
    else if (c) td.append(c);
    tr.append(td);
  }
  // What "Find in the tables" searches: the row's text plus its id.
  tr.dataset.text = `${n.id} ${tr.textContent}`.toLowerCase();
  body.append(tr);
}

const nodesOf = (ids: string[]) => ids.map((id) => graph.nodes.get(id)!).filter(Boolean);
const madeBy = (id: string) => nodesOf(graph.in.get(id) ?? []);
const usedBy = (id: string) => nodesOf(graph.out.get(id) ?? []);
const num = (cell: HTMLElement) => {
  cell.classList.add('num');
  return cell;
};

function tables(): void {
  const by = <T extends { id: string }>(items: T[]) => items.map((i) => graph.nodes.get(i.id)!);
  for (const n of by(data.sources)) {
    const s = n.source!;
    row($('#sources-rows'), n, [s.purpose, s.coverage, s.load_rules]);
  }
  for (const n of by(data.stores)) {
    const s = n.store!;
    if (s.tier === 'published') {
      row($('#outputs-rows'), n, [num(el('span', s.size)), s.purpose, madeBy(n.id), usedBy(n.id).filter((u) => u.kind === 'page')]);
    } else {
      row($('#stores-rows'), n, [el('span', s.tier, `df-tag ${tone(n)}`), num(el('span', s.size)), s.purpose, madeBy(n.id)]);
    }
  }
  for (const n of by(data.steps)) {
    const s = n.step!;
    row($('#steps-rows'), n, [s.purpose, nodesOf(s.inputs), nodesOf(s.outputs), s.duration, s.token_cost, el('span', s.refresh, `df-tag r-${s.refresh}`)]);
  }
  for (const n of by(data.pages)) row($('#pages-rows'), n, [n.page!.purpose, nodesOf(n.page!.reads)]);
}

/** The pages ticked in the page filter. */
const chosen = () =>
  [...document.querySelectorAll<HTMLInputElement>('#pages-pick input:checked')].map((i) => i.value);

/** Hides the table rows outside the chosen pages' flow or not matching the search. */
function filterTables(): void {
  const words = $<HTMLInputElement>('#find').value.toLowerCase().split(/\s+/).filter(Boolean);
  let count = 0;
  for (const tr of document.querySelectorAll<HTMLElement>('main tbody tr[data-text]')) {
    const hide = !shown.has(tr.dataset.node!) || !words.every((w) => tr.dataset.text!.includes(w));
    tr.hidden = hide;
    if (!hide) count++;
  }
  for (const sec of document.querySelectorAll<HTMLElement>('#sources, #stores, #outputs, #steps, #pages')) {
    sec.hidden = !sec.querySelector('tbody tr:not([hidden])');
  }
  $('#no-match').hidden = count > 0;
}

/** A label cut to what fits `width` units of the 10px font. */
const clip = (s: string, width: number) => {
  const max = Math.max(4, Math.floor((width - 12) / CHAR_W));
  return s.length > max ? `${s.slice(0, max - 1)}…` : s;
};

let drawnWidth = 0;

/** One box: a node, or a chip (a config file or the model beside its reader). */
function box(id: string, x: number, y: number, w: number, chip = false): SVGGElement {
  const base = baseId(id);
  const n = graph.nodes.get(base)!;
  const g = svg('g', { class: `df-node ${tone(n)}${chip ? ' df-chip' : ''}`, transform: `translate(${x} ${y})` });
  g.dataset.node = base;
  const title = svg('title');
  title.textContent = `${full(n)}: ${(n.source ?? n.store ?? n.step ?? n.page)!.purpose}`;
  const round = n.kind === 'step' ? NODE_H / 2 : n.kind === 'store' ? 3 : 6;
  const text = svg('text', { x: 7, y: NODE_H / 2 });
  text.textContent = clip(n.label, w);
  g.append(title, svg('rect', { width: w, height: NODE_H, rx: round }), text);
  return g;
}

function edgePath(from: string, to: string, d: string): SVGPathElement {
  const path = svg('path', { class: 'df-edge', d });
  path.dataset.from = baseId(from);
  path.dataset.to = baseId(to);
  return path;
}

/** Draws the chosen pages' flow top to bottom. Where it fits the box (or
 * nearly: it may shrink a little), it is routed so that no edge passes
 * behind a box and edges cross as little as the graph allows; on a narrow
 * screen it wraps wide layers instead. */
function drawGraph(): void {
  const host = $('#graph-box');
  const avail = Math.max(NODE_W + 2 * PAD, host.clientWidth);
  drawnWidth = host.clientWidth;
  const split = splitShared(graph, shown);
  const r = route(split.g, split.keep, { nodeW: NODE_W, chipW: CHIP_W, chipGap: CHIP_GAP, laneW: LANE_W, gap: GAP_X });
  const natural = r.width + 2 * PAD;
  const root = natural / avail <= 1 / MIN_SCALE ? drawRouted(r, avail) : drawWrapped(split.g, split.keep, avail);
  host.replaceChildren(root);
  fill($('#graph-note'), { shown: shown.size, total: graph.nodes.size });
  highlight();
}

function drawRouted(r: Routed, avail: number): SVGSVGElement {
  // Drawn at 1:1 and centred when it fits, else shrunk to the box's width.
  const width = Math.max(avail, r.width + 2 * PAD);
  const left = (width - r.width) / 2;
  const top = (layer: number) => PAD + layer * (NODE_H + LAYER_GAP);
  const height = r.layers ? top(r.layers) - LAYER_GAP + PAD : 2 * PAD;
  const scale = avail / width;
  const root = svg('svg', {
    viewBox: `0 0 ${width} ${height}`, width: avail, height: height * scale, role: 'img', 'aria-labelledby': 'graph-title',
  });
  const edgeLayer = svg('g', { class: 'df-edges' });
  const nodeLayer = svg('g');
  // Ports: each edge leaves its box's bottom and enters the next box's top
  // at its own point, in the order of where it goes (or comes from), so no
  // two edges meet at a point or cross at a box.
  const portsOut = new Map<string, number>();
  const portsIn = new Map<string, number>();
  const spread = (ends: Map<string, Routed['edges']>, ports: Map<string, number>, toward: (e: Routed['edges'][0]) => number) => {
    for (const [id, list] of ends) {
      list.sort((a, b) => toward(a) - toward(b));
      const cx = left + r.nodes.get(id)!.x;
      const span = NODE_W * 0.7;
      list.forEach((e, k) => ports.set(`${e.from}>${e.to}`, cx - span / 2 + (span * (k + 1)) / (list.length + 1)));
    }
  };
  const byFrom = new Map<string, Routed['edges']>();
  const byTo = new Map<string, Routed['edges']>();
  for (const e of r.edges) {
    (byFrom.get(e.from) ?? byFrom.set(e.from, []).get(e.from)!).push(e);
    (byTo.get(e.to) ?? byTo.set(e.to, []).get(e.to)!).push(e);
  }
  spread(byFrom, portsOut, (e) => e.xs[1]);
  spread(byTo, portsIn, (e) => e.xs[e.xs.length - 2]);
  for (const e of r.edges) {
    const xs = e.xs.map((x) => left + x);
    xs[0] = portsOut.get(`${e.from}>${e.to}`)!;
    xs[xs.length - 1] = portsIn.get(`${e.from}>${e.to}`)!;
    let y = top(e.layer) + NODE_H;
    let d = `M${xs[0]} ${y}`;
    for (let i = 1; i < xs.length; i++) {
      const y2 = top(e.layer + i);
      const bend = (y2 - y) / 2;
      d += `C${xs[i - 1]} ${y + bend} ${xs[i]} ${y2 - bend} ${xs[i]} ${y2}`;
      // Through a lane: straight down past the layer's boxes.
      if (i < xs.length - 1) {
        y = y2 + NODE_H;
        d += `L${xs[i]} ${y}`;
      }
    }
    edgeLayer.append(edgePath(e.from, e.to, d));
  }
  for (const [id, p] of r.nodes) nodeLayer.append(box(id, left + p.x - NODE_W / 2, top(p.layer), NODE_W));
  for (const [id, c] of r.chips) {
    const reader = r.nodes.get(c.reader)!;
    const y = top(reader.layer);
    const cx = left + c.x;
    nodeLayer.append(box(id, cx - CHIP_W / 2, y, CHIP_W, true));
    // The chip's link to its reader, across the gap between them.
    const x1 = c.side === 'left' ? cx + CHIP_W / 2 : cx - CHIP_W / 2;
    const x2 = left + reader.x + (c.side === 'left' ? -NODE_W / 2 : NODE_W / 2);
    edgeLayer.append(edgePath(id, c.reader, `M${x1} ${y + NODE_H / 2}L${x2} ${y + NODE_H / 2}`));
  }
  root.append(edgeLayer, nodeLayer);
  return root;
}

/** The narrow-screen drawing: layers wrapped into lines that fit, chips as
 * boxes above their reader. Edges may pass behind boxes here. */
function drawWrapped(g: Graph, keep: Set<string>, width: number): SVGSVGElement {
  const perLine = Math.max(1, Math.floor((width - 2 * PAD + GAP_X) / (NODE_W + GAP_X)));
  const placed = layout(g, keep, perLine);
  const tops: number[] = [];
  let y = PAD;
  let prevLayer = -1;
  for (const p of [...placed].sort((a, b) => a.line - b.line)) {
    if (tops[p.line] !== undefined) continue;
    if (prevLayer >= 0) y += NODE_H + (p.layer === prevLayer ? LINE_GAP : LAYER_GAP);
    tops[p.line] = y;
    prevLayer = p.layer;
  }
  const height = (placed.length ? y + NODE_H : 0) + PAD;
  const at = new Map<string, { x: number; y: number }>();
  for (const p of placed) {
    const left = (width - (p.of * NODE_W + (p.of - 1) * GAP_X)) / 2;
    at.set(p.id, { x: left + p.pos * (NODE_W + GAP_X), y: tops[p.line] });
  }
  const root = svg('svg', { viewBox: `0 0 ${width} ${height}`, width, height, role: 'img', 'aria-labelledby': 'graph-title' });
  const edgeLayer = svg('g', { class: 'df-edges' });
  for (const [a, b] of g.edges) {
    const p = at.get(a);
    const q = at.get(b);
    if (!p || !q) continue;
    const x1 = p.x + NODE_W / 2;
    const y1 = p.y + NODE_H;
    const x2 = q.x + NODE_W / 2;
    const bend = Math.max(12, (q.y - y1) / 2);
    edgeLayer.append(edgePath(a, b, `M${x1} ${y1}C${x1} ${y1 + bend} ${x2} ${q.y - bend} ${x2} ${q.y}`));
  }
  const nodeLayer = svg('g');
  for (const p of placed) nodeLayer.append(box(p.id, at.get(p.id)!.x, at.get(p.id)!.y, NODE_W));
  root.append(edgeLayer, nodeLayer);
  return root;
}

/** Lights up the selected node's lineage in the graph. */
function highlight(): void {
  const root = document.querySelector('#graph-box svg');
  if (!root) return;
  const on = selected && graph.nodes.has(selected)
    ? new Set([...reach(graph, [selected], 'in'), ...reach(graph, [selected], 'out')])
    : null;
  const up = on ? reach(graph, [selected!], 'in') : null;
  const down = on ? reach(graph, [selected!], 'out') : null;
  root.classList.toggle('has-sel', !!on);
  for (const g of root.querySelectorAll<SVGGElement>('.df-node')) {
    g.classList.toggle('on', !!on?.has(g.dataset.node!));
    g.classList.toggle('sel', g.dataset.node === selected);
  }
  for (const p of root.querySelectorAll<SVGPathElement>('.df-edge')) {
    const { from, to } = p.dataset;
    // An edge is lit only when it lies on a path through the selection.
    p.classList.toggle('on', !!((up?.has(from!) && up.has(to!)) || (down?.has(from!) && down.has(to!))));
  }
}

function fact(field: string, value: string | HTMLElement | DocumentFragment | null | undefined): void {
  const box = $(`#detail-facts [data-field="${field}"]`);
  const dd = box.querySelector('dd')!;
  dd.replaceChildren();
  const empty = value === null || value === undefined || value === '';
  if (!empty) dd.append(value);
  box.hidden = empty;
}

const idsOrNull = (ids: string[]) => (ids.length ? links(ids) : null);

function showDetail(): void {
  const n = selected ? graph.nodes.get(selected) : undefined;
  $('#detail').hidden = !n;
  for (const tr of document.querySelectorAll<HTMLElement>('main tbody tr[data-node]')) {
    tr.toggleAttribute('aria-selected', tr.dataset.node === selected);
  }
  if (!n) return;
  const item = (n.source ?? n.store ?? n.step ?? n.page)!;
  $('#detail-title').textContent = full(n);
  $('#detail-purpose').textContent = item.purpose;
  const s: Partial<Store> = n.store ?? {};
  const t: Partial<Step> = n.step ?? {};
  const msgOf = (key: string, vars = {}) => {
    const span = el('span');
    fill(span, vars, key);
    return span;
  };
  fact('kind', kindText(n));
  fact('path', n.store && s.tracked_in_git && !/[*<{+]/.test(s.path!) ? repoLink(s.path!) : n.page ? repoLink(n.page.path) : s.path);
  fact('url', n.source?.url);
  fact('command', t.command ? el('code', t.command) : null);
  fact('run', t.run ? el('code', t.run) : null);
  const code = [...(t.code ?? []), ...(n.page?.entry_script ? [n.page.entry_script] : [])];
  if (code.length) {
    const ul = el('ul', null, 'df-links');
    for (const c of code) ul.appendChild(el('li')).append(repoLink(c));
    fact('code', ul);
  } else fact('code', null);
  fact('size', s.size ? `${s.size}${s.size_as_of ? ` (${s.size_as_of})` : ''}` : null);
  fact('files', s.files);
  fact('git', n.store ? (s.tracked_in_git ? msgOf('git-yes', { paths: (s.git_paths ?? []).join(', ') }) : msgOf('git-no')) : null);
  fact('rebuild', n.store ? (s.rebuildable ? msgOf('rebuild-yes') : msgOf('rebuild-no', { keep: !!s.never_delete })) : null);
  fact('coverage', n.source?.coverage);
  fact('access', n.source?.access);
  fact('load_rules', n.source?.load_rules);
  fact('refresh', t.refresh ? el('span', t.refresh, `df-tag r-${t.refresh}`) : null);
  fact('duration', t.duration);
  fact('token_cost', t.token_cost);
  fact('cost_source', t.cost_source);
  fact('incremental', t.incremental);
  fact('network', n.step ? msgOf(t.network ? 'network-yes' : 'network-no') : null);
  fact('lock', t.lock);
  fact('approval', t.approval);
  fact('sources_line', n.page?.sources_line);
  fact('notes', item.notes);
  fact('inputs', n.step ? idsOrNull(t.inputs!) : n.page ? idsOrNull(n.page.reads) : null);
  fact('outputs', n.step ? idsOrNull(t.outputs!) : null);
  fact('made_by', n.kind === 'store' ? idsOrNull(graph.in.get(n.id)!) : null);
  fact('used_by', n.kind === 'store' || n.kind === 'source' ? idsOrNull(graph.out.get(n.id)!) : null);
  const ends = (dir: 'in' | 'out', want: (x: Node) => boolean) =>
    idsOrNull([...reach(graph, [n.id], dir)].filter((id) => id !== n.id && want(graph.nodes.get(id)!)));
  fact('origin', n.kind === 'source' ? null : ends('in', (x) => x.kind === 'source'));
  fact('reaches', n.kind === 'page' ? null : ends('out', (x) => x.kind === 'page'));

  const tbody = $('#detail-tables');
  tbody.replaceChildren();
  for (const tb of s.tables ?? []) {
    const tr = el('tr');
    const th = el('th', tb.name, 'df-mono');
    th.scope = 'row';
    const rows = tb.rows == null ? '' : `${tb.rows_approx ? '~' : ''}${tb.rows.toLocaleString('en')}`;
    tr.append(th, el('td', rows, 'num'), el('td', tb.purpose));
    tbody.append(tr);
  }
  $('#detail-tables-box').hidden = !s.tables?.length;
}

function select(id: string | null, scroll: boolean): void {
  selected = id && graph.nodes.has(id) ? id : null;
  history.replaceState(null, '', selected ? `#n=${encodeURIComponent(selected)}` : location.pathname + location.search);
  highlight();
  showDetail();
  if (selected && scroll) $('#detail').scrollIntoView({ block: 'nearest' });
}

/** The plan for the chosen "new data", narrowed to the chosen pages' flow. */
function showPlan(): void {
  const id = $<HTMLSelectElement>('#changed').value;
  const p = plan(graph, [id]);
  const steps = p.steps.filter((s) => shown.has(s.step.id));
  const body = $('#plan-steps');
  body.replaceChildren();
  for (const { step, afterOptional } of steps) {
    const tr = el('tr');
    const th = el('th');
    th.scope = 'row';
    th.append(link(step.id));
    const when = el('td');
    when.append(el('span', step.refresh, `df-tag r-${step.refresh}`));
    if (afterOptional && step.refresh !== 'optional') when.append(' ', el('span', 'after optional', 'df-tag r-after'));
    const cmd = el('td');
    cmd.append(el('code', step.command));
    tr.append(th, cmd, el('td', step.duration), el('td', step.token_cost), when);
    body.append(tr);
  }
  const commit = $('#plan-commit');
  commit.replaceChildren();
  for (const s of p.commit.filter((x) => shown.has(x.id))) {
    const li = el('li');
    li.append(link(s.id));
    // The files to commit: a family's globs, or a named store's path.
    const paths = s.git_paths ?? (s.name ? [s.path] : []);
    if (paths.length) li.append(' ', el('span', paths.join(', '), 'df-mono df-dim'));
    commit.append(li);
  }
  if (!commit.children.length) commit.append(el('li', '—'));
  fill($('#plan-pages'), { pages: p.pages.filter((x) => shown.has(x.id)).map((x) => x.title).join(', ') });
  $('#plan-out').hidden = !steps.length;
  $('#plan-none').hidden = steps.length > 0;
}

/** Recomputes what is in view and redraws everything that depends on it. */
function refilter(): void {
  shown = scope(graph, chosen(), $<HTMLInputElement>('#show-analysis').checked);
  filterTables();
  drawGraph();
  showPlan();
}

function controls(): void {
  const pick = $('#pages-pick');
  for (const p of flowPages(graph)) {
    const label = el('label', null, 'df-check');
    const box = el('input');
    box.type = 'checkbox';
    box.value = p.id;
    box.checked = true;
    label.title = p.purpose;
    label.append(box, p.title);
    pick.append(label);
  }
  // What can have new data: every source, then the stores that are fetched
  // or labelled (derived ones only change when those do).
  const changed = $<HTMLSelectElement>('#changed');
  const option = (label: string, nodes: Node[]) => {
    const og = el('optgroup');
    og.label = label;
    for (const n of nodes) {
      const o = el('option', full(n));
      o.value = n.id;
      og.append(o);
    }
    if (nodes.length) changed.append(og);
  };
  const all = [...graph.nodes.values()];
  option('Sources', all.filter((n) => n.kind === 'source'));
  for (const tier of ['raw', 'labels', 'config', 'derived'] as const) {
    option(tier, all.filter((n) => n.store?.tier === tier));
  }
  changed.addEventListener('change', showPlan);
  pick.addEventListener('change', refilter);
  $('#find').addEventListener('input', filterTables);
  $('#show-analysis').addEventListener('change', refilter);
  document.addEventListener('click', (e) => {
    const hit = (e.target as Element).closest<HTMLElement | SVGElement>('[data-node]');
    if (!hit || hit.localName === 'tr') return;
    const id = hit.dataset.node!;
    const inGraph = !!hit.closest('#graph-box');
    select(inGraph && id === selected ? null : id, !inGraph);
  });
  window.addEventListener('hashchange', fromHash);
  // The graph is as wide as its box: redraw when the box's width changes.
  let pending = 0;
  new ResizeObserver(() => {
    if ($('#graph-box').clientWidth === drawnWidth || pending) return;
    pending = requestAnimationFrame(() => {
      pending = 0;
      drawGraph();
    });
  }).observe($('#graph-box'));
}

function fromHash(): void {
  const m = /^#n=(.+)$/.exec(location.hash);
  if (!m) return;
  selected = decodeURIComponent(m[1]);
  highlight();
  showDetail();
}

async function main(): Promise<void> {
  data = (await (await fetch(dataUrl)).json()) as Dataflow;
  graph = buildGraph(data);
  for (const p of graph.problems) console.error(`config/dataflow.json: ${p}`);
  fill($('#counts'), {
    sources: data.sources.length,
    stores: data.stores.length,
    published: data.stores.filter((s) => s.tier === 'published').length,
    steps: data.steps.length,
    pages: data.pages.length,
    updated: data.updated,
  });
  controls();
  tables();
  refilter();
  fromHash();
  $('main').removeAttribute('aria-busy');
  document.body.dataset.ready = '1';
}

main().catch((e) => {
  console.error(e);
  document.body.dataset.ready = 'error';
});
