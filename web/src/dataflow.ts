// The Data flow page (dataflow.html): tables of every source, store, step
// and page in config/dataflow.json, a graph of how they connect, and a
// planner for what to rerun. Wording is in the HTML; this fills in values.
// Everything goes into the DOM as text or attributes (the CSP forbids HTML
// sinks), and scripts set classes and custom properties, never styles.
import dataUrl from '../../config/dataflow.json?url';
import {
  buildGraph,
  layout,
  plan,
  reach,
  type Dataflow,
  type Graph,
  type Node,
  type Step,
  type Store,
} from './dataflow-graph.ts';
import { fill } from './text.ts';

const SVG = 'http://www.w3.org/2000/svg';
const REPO = 'https://github.com/RByers/cosh/blob/main/';

// Graph geometry, in SVG user units.
const NODE_W = 168;
const NODE_H = 26;
const COL_GAP = 52;
const ROW_GAP = 8;
const PAD = 8;
const LABEL_MAX = 23;

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

/** The class that colours a node: its kind, or a store's tier. */
const tone = (n: Node) => (n.kind === 'store' ? `k-${n.store!.tier}` : `k-${n.kind}`);

const kindText = (n: Node): string => {
  if (n.kind === 'store') return `${n.store!.tier} store (${n.store!.kind})`;
  if (n.kind === 'source') return `source (${n.source!.kind})`;
  return n.kind;
};

const groupName = (id: string) => data.groups.find((g) => g.id === id)?.name ?? id;

/** A node's full name: a store's path (or family name), else its label. */
const full = (n: Node) => (n.kind === 'store' ? (n.store!.name ?? n.store!.path) : n.label);

/** A button that selects a node, wherever it appears. `short` shows only
 * the label (a path's last part), with the full name as its hover title. */
function link(id: string, short = false): HTMLElement {
  const n = graph.nodes.get(id);
  if (!n) return el('span', id);
  const mono = n.kind === 'source' || n.store?.name ? '' : ' df-mono';
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
  tr.dataset.group = n.group;
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

/** Hides the table rows the pipeline choice and the search box exclude. */
function filterTables(): void {
  const group = $<HTMLSelectElement>('#group').value;
  const words = $<HTMLInputElement>('#find').value.toLowerCase().split(/\s+/).filter(Boolean);
  let shown = 0;
  for (const tr of document.querySelectorAll<HTMLElement>('main tbody tr[data-text]')) {
    const hide = (group !== '' && tr.dataset.group !== group) || !words.every((w) => tr.dataset.text!.includes(w));
    tr.hidden = hide;
    if (!hide) shown++;
  }
  for (const sec of document.querySelectorAll<HTMLElement>('#sources, #stores, #outputs, #steps, #pages')) {
    sec.hidden = !sec.querySelector('tbody tr:not([hidden])');
  }
  $('#no-match').hidden = shown > 0;
}

/** The nodes the graph draws: one pipeline's (with what they connect to),
 * without analysis scripts and backfills, and what only those touch,
 * unless asked for. */
function visible(): Set<string> {
  const group = $<HTMLSelectElement>('#group').value;
  const extras = $<HTMLInputElement>('#show-analysis').checked;
  const quiet = (n: Node) => n.kind === 'step' && (n.step!.refresh === 'analysis' || n.step!.refresh === 'one-off');
  const keep = new Set<string>();
  for (const n of graph.nodes.values()) {
    if (!extras && quiet(n)) continue;
    if (group !== '' && n.group !== group) continue;
    keep.add(n.id);
  }
  // A pipeline is drawn with its neighbours from other pipelines.
  if (group !== '') {
    for (const id of [...keep]) {
      for (const near of [...(graph.in.get(id) ?? []), ...(graph.out.get(id) ?? [])]) {
        const n = graph.nodes.get(near)!;
        if (extras || !quiet(n)) keep.add(near);
      }
    }
  }
  // Without the extras, drop what is left unconnected: stores only they use.
  if (!extras) {
    for (const id of [...keep]) {
      const n = graph.nodes.get(id)!;
      if (n.kind === 'step' || n.kind === 'page') continue;
      const near = [...(graph.in.get(id) ?? []), ...(graph.out.get(id) ?? [])];
      if (!near.some((x) => keep.has(x))) keep.delete(id);
    }
  }
  return keep;
}

const clip = (s: string) => (s.length > LABEL_MAX ? `${s.slice(0, LABEL_MAX - 1)}…` : s);

function drawGraph(): void {
  const keep = visible();
  const placed = layout(graph, keep);
  const cols = Math.max(0, ...placed.map((p) => p.col)) + 1;
  const perCol = Array.from({ length: cols }, (_, c) => placed.filter((p) => p.col === c).length);
  const rows = Math.max(1, ...perCol);
  const width = PAD * 2 + cols * NODE_W + (cols - 1) * COL_GAP;
  const height = PAD * 2 + rows * NODE_H + (rows - 1) * ROW_GAP;
  const at = new Map<string, { x: number; y: number }>();
  for (const p of placed) {
    // Each column is centred on the tallest one.
    const top = PAD + ((rows - perCol[p.col]) * (NODE_H + ROW_GAP)) / 2;
    at.set(p.id, { x: PAD + p.col * (NODE_W + COL_GAP), y: top + p.row * (NODE_H + ROW_GAP) });
  }

  const root = svg('svg', { viewBox: `0 0 ${width} ${height}`, width, height, role: 'img', 'aria-labelledby': 'graph-title' });
  const edgeLayer = svg('g', { class: 'df-edges' });
  for (const [a, b] of graph.edges) {
    const p = at.get(a);
    const q = at.get(b);
    if (!p || !q) continue;
    const x1 = p.x + NODE_W;
    const y1 = p.y + NODE_H / 2;
    const y2 = q.y + NODE_H / 2;
    const bend = Math.max(24, (q.x - x1) / 2);
    const path = svg('path', { class: 'df-edge', d: `M${x1} ${y1}C${x1 + bend} ${y1} ${q.x - bend} ${y2} ${q.x} ${y2}` });
    path.dataset.from = a;
    path.dataset.to = b;
    edgeLayer.append(path);
  }
  const nodeLayer = svg('g');
  for (const p of placed) {
    const n = graph.nodes.get(p.id)!;
    const { x, y } = at.get(p.id)!;
    const g = svg('g', { class: `df-node ${tone(n)}`, transform: `translate(${x} ${y})` });
    g.dataset.node = n.id;
    const title = svg('title');
    title.textContent = `${full(n)}:${(n.source ?? n.store ?? n.step ?? n.page)!.purpose}`;
    const round = n.kind === 'step' ? NODE_H / 2 : n.kind === 'store' ? 3 : 7;
    const text = svg('text', { x: 9, y: NODE_H / 2 });
    text.textContent = clip(n.label);
    g.append(title, svg('rect', { width: NODE_W, height: NODE_H, rx: round }), text);
    nodeLayer.append(g);
  }
  root.append(edgeLayer, nodeLayer);
  $('#graph-box').replaceChildren(root);
  const hidden = [...graph.nodes.values()].filter((n) => !keep.has(n.id) && ($<HTMLSelectElement>('#group').value === '' || n.group === $<HTMLSelectElement>('#group').value)).length;
  fill($('#graph-note'), { shown: placed.length, total: graph.nodes.size, hidden: $<HTMLInputElement>('#show-analysis').checked ? 0 : hidden });
  highlight();
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
  fact('group', groupName(n.group));
  fact('path', n.store && s.tracked_in_git && !/[*<]/.test(s.path!) ? repoLink(s.path!) : n.page ? repoLink(n.page.path) : s.path);
  fact('url', n.source?.url);
  fact('command', t.command ? el('code', t.command) : null);
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
  fact('reaches', n.kind === 'page' ? null : ends('out', (x) => x.kind === 'page' || (x.kind === 'store' && x.store!.tier === 'published')));

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
  if (selected && scroll) {
    $('#detail').scrollIntoView({ block: 'nearest' });
    revealInGraph();
  }
}

/** Scrolls the graph's own box (not the page) to the selected node. */
function revealInGraph(): void {
  const box = $('#graph-box');
  const node = box.querySelector<SVGGElement>('.df-node.sel');
  if (!node) return;
  const b = box.getBoundingClientRect();
  const r = node.getBoundingClientRect();
  box.scrollTo({
    left: box.scrollLeft + r.left - b.left - (b.width - r.width) / 2,
    top: box.scrollTop + r.top - b.top - (b.height - r.height) / 2,
  });
}

function showPlan(): void {
  const id = $<HTMLSelectElement>('#changed').value;
  const p = plan(graph, [id]);
  const body = $('#plan-steps');
  body.replaceChildren();
  for (const { step, afterOptional } of p.steps) {
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
  for (const s of p.commit) {
    const li = el('li');
    li.append(link(s.id));
    if (s.git_paths?.length) li.append(' ', el('span', s.git_paths.join(', '), 'df-mono df-dim'));
    commit.append(li);
  }
  if (!p.commit.length) commit.append(el('li', '—'));
  fill($('#plan-pages'), { pages: p.pages.map((x) => x.title).join(', ') });
  $('#plan-out').hidden = !p.steps.length;
  $('#plan-none').hidden = p.steps.length > 0;
}

function controls(): void {
  const group = $<HTMLSelectElement>('#group');
  for (const g of data.groups) {
    const o = el('option', g.name);
    o.value = g.id;
    o.title = g.purpose;
    group.append(o);
  }
  // What can have new data: every source, then the stores that are fetched
  // or labelled (derived ones only change when those do).
  const changed = $<HTMLSelectElement>('#changed');
  const pick = (label: string, nodes: Node[]) => {
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
  pick('Sources', all.filter((n) => n.kind === 'source'));
  for (const tier of ['raw', 'labels', 'config', 'derived'] as const) {
    pick(tier, all.filter((n) => n.store?.tier === tier));
  }
  changed.addEventListener('change', showPlan);
  group.addEventListener('change', () => {
    filterTables();
    drawGraph();
  });
  $('#find').addEventListener('input', filterTables);
  $('#show-analysis').addEventListener('change', drawGraph);
  document.addEventListener('click', (e) => {
    const hit = (e.target as Element).closest<HTMLElement | SVGElement>('[data-node]');
    if (!hit || hit.localName === 'tr') return;
    const id = hit.dataset.node!;
    const inGraph = !!hit.closest('#graph-box');
    select(inGraph && id === selected ? null : id, !inGraph);
  });
  window.addEventListener('hashchange', fromHash);
}

function fromHash(): void {
  const m = /^#n=(.+)$/.exec(location.hash);
  if (!m) return;
  selected = decodeURIComponent(m[1]);
  highlight();
  showDetail();
  revealInGraph();
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
  filterTables();
  drawGraph();
  showPlan();
  fromHash();
  $('main').removeAttribute('aria-busy');
  document.body.dataset.ready = '1';
}

main().catch((e) => {
  console.error(e);
  document.body.dataset.ready = 'error';
});
