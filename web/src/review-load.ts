// The Review Load page (review-load.html). Wording is in the HTML; this
// loads all.json, draws the charts and the directory table, and looks a
// reviewer up by the address typed (never offering completions: their data
// is in a bucket that can't be listed) to add their figures. The
// address is never put in the URL.
import { Chart, Filler, type ChartDataset } from 'chart.js';
import { readTheme, withAlpha, type Theme } from './charts.ts';
import { isPersonFile, looksLikeEmail, personFile } from './feedback.ts';
import { fmtInt, fmtNum } from './format.ts';
import {
  buildPerson,
  change,
  dirRows,
  dirTree,
  logShade,
  meanLines,
  overallPct,
  reviewersPerCommit,
  ownRow,
  PCT_KEYS,
  pctHours,
  personSeries,
  quarterLabel,
  ratio,
  totalLines,
  waitShade,
  yearsOf,
  type All,
  type DirRow,
  type PctKey,
  type Person,
  type Spread,
  type PersonDir,
  type PersonFile,
  type PersonYear,
} from './load.ts';
import { LOAD_PEOPLE, r2Url } from './r2.ts';
import { fragment, msg, type Vars } from './text.ts';
import { showDataSpan } from './data-span.ts';
import { initAnchors } from './anchors.ts';

declare global {
  interface Window {
    __rl?: { all: All | null; person: Person | null; charts: Record<string, Chart> };
  }
}

Chart.register(Filler);

const $ = <T extends Element = HTMLElement>(sel: string) => document.querySelector<T>(sel)!;
const DATA = 'review-load/';
/** A table cell needs this many reviewer turns to show a percentile. */
const MIN_TURNS = 5;
/** The OWNERS table shows a share of non-committers' lines from this many. */
const MIN_NEW_LINES = 1000;

const state = {
  all: null as All | null,
  person: null as Person | null,
  expanded: new Set<string>(),
  ownersExpanded: new Set<string>(),
  /** The table's percentile. */
  pct: 'p90' as PctKey,
};
const charts: Record<string, Chart> = {};
window.__rl = { all: null, person: null, charts };

const put = (target: Element, key: string, vars: Vars = {}) => target.replaceChildren(fragment(key, vars));

async function getJson<T>(url: string): Promise<T | null> {
  const r = await fetch(url);
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return (await r.json()) as T;
}

function el<K extends keyof HTMLElementTagNameMap>(tag: K, text?: string, cls?: string): HTMLElementTagNameMap[K] {
  const e = document.createElement(tag);
  if (text !== undefined) e.textContent = text;
  if (cls) e.className = cls;
  return e;
}

const ok = (v: number | null | undefined): v is number => v !== null && v !== undefined && Number.isFinite(v);
const fmtBig = (v: number) =>
  fmtNum(v, { notation: 'compact', maximumFractionDigits: (v >= 1e3 && v < 1e4) || (v >= 1e6 && v < 1e7) ? 1 : 0 });
const fmtHours = (v: number | null | undefined) =>
  (ok(v) ? `${fmtNum(v, { maximumFractionDigits: v < 10 ? 1 : 0 })} h` : '–');
const fmtChange = (v: number | null | undefined) =>
  (ok(v) ? `${v >= 0 ? '+' : '−'}${fmtNum(Math.abs(v), { style: 'percent', maximumFractionDigits: 0 })}` : '–');

// ---- charts

const theme = () => readTheme();
const youColor = (t: Theme) => t.series[7];

function destroy(name: string) {
  charts[name]?.destroy();
  delete charts[name];
}

const axis = (t: Theme, title: string) => ({ grid: { color: t.grid }, title: { display: true, text: title, color: t.text },
  ticks: { color: t.text, font: { family: t.font } } });

interface Key { label: string; color: string; dash?: boolean; band?: boolean }

function legend(target: Element, items: Key[]) {
  target.replaceChildren(...items.map((l) => {
    const li = el('li');
    const sw = el('span', undefined, l.dash ? 'swatch swatch-dash' : l.band ? 'swatch swatch-band' : 'swatch');
    sw.style.setProperty('--color', l.color);
    li.append(sw, document.createTextNode(l.label));
    return li;
  }));
}

type Line = ChartDataset<'bar' | 'line', (number | null)[]>;
const line = (label: string, data: (number | null)[], color: string, more: object = {}): Line => ({
  type: 'line' as const, label, data, borderColor: color, backgroundColor: color, borderWidth: 2, pointRadius: 0, pointHoverRadius: 4,
  tension: 0, spanGaps: false, ...more });
const youLine = (t: Theme, data: (number | null)[], more: object = {}): Line =>
  line(msg('legend-you'), data, youColor(t), { borderWidth: 3, pointRadius: 2.5, spanGaps: true, order: 0, ...more });

/** A chart over the quarters from index `from`; `format` writes a tooltip line's value, `extra`
 * adds to it (given the index into all the quarters). */
function draw(name: string, datasets: Line[], t: Theme,
  scales: Record<string, object>, format: (v: number, dataset: number) => string,
  extra?: (dataset: number, i: number) => string, from = 0) {
  destroy(name);
  const all = state.all!;
  for (const d of datasets) d.data = d.data.slice(from);
  charts[name] = new Chart<'bar' | 'line', (number | null)[], string>($<HTMLCanvasElement>(`#rl-${name}`), {
    type: 'line',
    data: { labels: all.quarters.slice(from).map(quarterLabel), datasets },
    options: {
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: 'index', intersect: false },
      font: { family: t.font },
      scales: { x: { ...axis(t, msg('axis-quarter')), grid: { display: false } }, ...scales },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (i) => {
              const v = i.parsed.y;
              if (!ok(v)) return '';
              return `${i.dataset.label}: ${format(v, i.datasetIndex)}${extra?.(i.datasetIndex, i.dataIndex + from) ?? ''}`;
            },
          },
        },
      },
    },
  });
}

/** The newest quarter and its index. */
const lastOf = (all: All) => ({ i: all.quarters.length - 1, q: quarterLabel(all.quarters.at(-1)!) });
/** The index of the first quarter with attention-set data. */
const attFrom = (all: All) => Math.max(0, all.quarters.indexOf(all.attention_from));

function renderCommits() {
  const all = state.all!;
  const p = state.person;
  const t = theme();
  const { i, q } = lastOf(all);
  const keys: Key[] = [{ label: msg('legend-commits'), color: t.series[0] }, { label: msg('legend-human'), color: t.series[2] }];
  const datasets: Line[] = [line(keys[0].label, all.commits, keys[0].color), line(keys[1].label, all.human, keys[1].color)];
  const scales: Record<string, object> = { y: { ...axis(t, msg('axis-commits')), beginAtZero: true } };
  if (p) {
    keys.push({ label: msg('legend-you-commits'), color: youColor(t) });
    datasets.push(youLine(t, personSeries(p, all.quarters, (v) => v[0]), { yAxisID: 'you' }));
    scales.you = { ...axis(t, msg('axis-you-commits')), position: 'right', beginAtZero: true, grid: { display: false } };
  }
  legend($('#rl-commits-legend'), keys);
  draw('commits', datasets, t, scales, (v) => fmtInt(v));
  const yoy = change(all.human[i], all.human[i - 4]);
  put($('#rl-commits-note'), 'commits-note', { from: quarterLabel(all.quarters[0]), to: q, last: q, n: fmtInt(all.commits[i]),
    human: fmtInt(all.human[i]), you: !!p,
    change: ok(yoy) ? `${fmtNum(Math.abs(yoy), { style: 'percent', maximumFractionDigits: 0 })} ${msg(yoy >= 0 ? 'more' : 'fewer')}` : '–' });
}

/** The datasets of a spread drawn as the Feedback Index draws one: the 10th–90th percentile and the
 * middle half shaded, the median a line (datasets 0–4); and its legend. */
function fan(sp: Spread, t: Theme): { datasets: Line[]; keys: Key[] } {
  const wide = withAlpha(t.series[0], 0.14);
  const mid = withAlpha(t.series[0], 0.3);
  const band = (label: string, data: (number | null)[], more: object): Line =>
    line(label, data, 'transparent', { borderWidth: 0, pointHoverRadius: 0, tension: 0.3, ...more });
  return {
    datasets: [
      band(msg('tip-p90'), sp.p90, { backgroundColor: wide, fill: '+1', order: 4 }),
      band(msg('tip-p10'), sp.p10, { fill: false, order: 4 }),
      band(msg('tip-p75'), sp.p75, { backgroundColor: mid, fill: '+1', order: 3 }),
      band(msg('tip-p25'), sp.p25, { fill: false, order: 3 }),
      line(msg('legend-median'), sp.p50, t.series[0], { borderWidth: 2.5, tension: 0.3, fill: false, order: 1 }),
    ],
    keys: [{ label: msg('legend-median'), color: t.series[0] },
      { label: msg('legend-mid'), color: mid, band: true }, { label: msg('legend-wide'), color: wide, band: true }],
  };
}

/** A fan with the looked-up reviewer's line (`you`, labelled `youKey`) on top. */
function fanWithYou(sp: Spread, t: Theme, you: (number | null)[] | null, youKey: string) {
  const f = fan(sp, t);
  if (you) {
    f.keys.unshift({ label: msg(youKey), color: youColor(t) });
    f.datasets.push(youLine(t, you, { label: msg(youKey) }));
  }
  return f;
}

function renderLines() {
  const all = state.all!;
  const p = state.person;
  const t = theme();
  const { i, q } = lastOf(all);
  const mean = meanLines(all);
  const s = all.reviewer_lines;
  const { datasets, keys } = fanWithYou(s, t, p ? personSeries(p, all.quarters, (v) => v[1]) : null, 'legend-you');
  legend($('#rl-lines-legend'), keys);
  // The median's and the reviewer's growth: each quarter against the one before and against a year before.
  const growth = (d: number, k: number) => {
    if (d < 4) return '';
    const v = datasets[d].data;
    const parts = [k >= 1 ? fmtChange(change(v[k], v[k - 1])) : '–', k >= 4 ? fmtChange(change(v[k], v[k - 4])) : '–'];
    return ` (${parts[0]} on the quarter before, ${parts[1]} on a year before)`;
  };
  draw('lines', datasets, t, { y: { ...axis(t, msg('axis-lines')), beginAtZero: true } }, (v) => fmtInt(Math.round(v)), growth);
  const lines = (v: number | null | undefined) => fmtInt(Math.round(v ?? 0));
  const split = reviewersPerCommit(all);
  put($('#rl-lines-note'), 'lines-note', { last: q, reviewers: fmtInt(all.reviewers[i]), median: lines(s.p50[i]),
    factor: fmtNum(split.perLine[i] ?? 0, { maximumFractionDigits: 2 }),
    every: fmtNum(split.perLineAll[i] ?? 0, { maximumFractionDigits: 2 }),
    p25: lines(s.p25[i]), p75: lines(s.p75[i]), p10: lines(s.p10[i]), p90: lines(s.p90[i]),
    qoq: fmtChange(change(s.p50[i], s.p50[i - 1])), yoy: fmtChange(change(s.p50[i], s.p50[i - 4])),
    mean: lines(mean[i]), meanYoy: fmtChange(change(mean[i], mean[i - 4])), you: !!p });
}

/** Methodology: reviewers per changed line, as estimated and had every reviewer read every file (the
 * bounds on lines reviewed), and reviewers per commit. */
function renderSplit() {
  const all = state.all!;
  const t = theme();
  const { i, q } = lastOf(all);
  const r = reviewersPerCommit(all);
  const keys: Key[] = [{ label: msg('legend-split-all'), color: t.series[1] }, { label: msg('legend-split-line'), color: t.series[0] },
    { label: msg('legend-split-commit'), color: t.series[2] }];
  legend($('#rl-split-legend'), keys);
  draw('split', [line(keys[0].label, r.perLineAll, keys[0].color), line(keys[1].label, r.perLine, keys[1].color),
    line(keys[2].label, r.perCommit, keys[2].color)], t,
  { y: { ...axis(t, msg('axis-split')), min: 1 } }, (v) => fmtNum(v, { maximumFractionDigits: 2 }));
  const f = (v: number | null | undefined) => fmtNum(v ?? 0, { maximumFractionDigits: 2 });
  const pct = (v: number | null | undefined) => fmtNum(v ?? 0, { style: 'percent', maximumFractionDigits: 0 });
  const est = r.perLine[i] ?? 1;
  put($('#rl-split-note'), 'split-note', { first: quarterLabel(all.quarters[0]), last: q,
    lineFirst: f(r.perLine[0]), lineLast: f(est), allFirst: f(r.perLineAll[0]), allLast: f(r.perLineAll[i]),
    over: pct(est - 1), under: pct((r.perLineAll[i] ?? est) / est - 1),
    commitFirst: f(r.perCommit[0]), commitLast: f(r.perCommit[i]), multiFirst: pct(r.multi[0]), multiLast: pct(r.multi[i]),
    drift: fmtChange(change(est, r.perLine[0])) });
}

function renderReply() {
  const all = state.all!;
  const p = state.person;
  const t = theme();
  const { i, q } = lastOf(all);
  const s = all.reply;
  const { datasets, keys } = fanWithYou(s, t, p ? personSeries(p, all.quarters, (v) => ratio(v[4], v[5])) : null,
    'legend-you-mean');
  legend($('#rl-reply-legend'), keys);
  draw('reply', datasets, t, { y: { ...axis(t, msg('axis-hours')), beginAtZero: true } }, (v) => fmtHours(v),
    undefined, attFrom(all));
  put($('#rl-reply-note'), 'reply-note', { last: q, n: fmtInt(s.n[i] ?? 0), median: fmtHours(s.p50[i]),
    p25: fmtHours(s.p25[i]), p75: fmtHours(s.p75[i]), p10: fmtHours(s.p10[i]), p90: fmtHours(s.p90[i]),
    mean: fmtHours(s.mean[i]), you: !!p });
}

/** Reviewer response time: every turn's working hours (the reviewer's). */
function renderTurns() {
  const all = state.all!;
  const p = state.person;
  const t = theme();
  const { i, q } = lastOf(all);
  const s = all.turns;
  const { datasets, keys } = fanWithYou(s, t, p ? all.quarters.map((x) => p.turns.get(x)?.[0] ?? null) : null,
    'legend-you-median');
  legend($('#rl-turns-legend'), keys);
  draw('turns', datasets, t, { y: { ...axis(t, msg('axis-hours')), beginAtZero: true } },
    (v) => fmtHours(v), undefined, attFrom(all));
  put($('#rl-turns-note'), 'turns-note', { last: q, n: fmtInt(s.n[i] ?? 0), median: fmtHours(s.p50[i]),
    p25: fmtHours(s.p25[i]), p75: fmtHours(s.p75[i]), p10: fmtHours(s.p10[i]), p90: fmtHours(s.p90[i]),
    mean: fmtHours(s.mean[i]), you: !!p });
}

// ---- the directory table

/** A cell shaded green (below `typical`) to red (above it). */
function waitCell(v: number | null, typical: number | null, cls = 'num'): HTMLTableCellElement {
  const td = el('td', ok(v) ? fmtNum(v, { maximumFractionDigits: v < 10 ? 1 : 0 }) : '', cls);
  const shade = waitShade(v, typical);
  if (shade) {
    td.classList.add(shade > 0 ? 'rf-ratio-hi' : 'rf-ratio-lo');
    td.style.setProperty('--rf-shade', String(Math.abs(shade)));
  }
  return td;
}

/** The lines-reviewed cell, shaded white to dark blue on a log scale from `lo` to `hi` lines. */
function heatCell(v: number, lo: number, hi: number): HTMLTableCellElement {
  const td = el('td', fmtBig(v), 'num rl-heat');
  const shade = logShade(v, lo, hi) ?? 0;
  td.style.setProperty('--rl-heat', shade.toFixed(3));
  td.classList.toggle('rl-heat-dark', shade > 0.5);
  return td;
}

/** A row with its directory cell: the name, indented, and the button that opens it (in `expanded`). */
function dirHead(r: DirRow, expanded: Set<string>, rerender: () => void, span: number): HTMLTableRowElement {
  const n = r.node;
  const tr = el('tr', undefined, `rf-dir-row rf-dir-${n ? n.kind : 'more'}`);
  tr.dataset.key = r.key;
  const th = el('th');
  th.setAttribute('scope', 'row');
  const label = el('span', undefined, 'rf-dir-label');
  label.style.setProperty('--depth', String(r.depth));
  const name = !n ? msg('dirs-more', { n: fmtInt(r.more!) })
    : n.kind === 'dir' ? n.name : n.path ? msg('dirs-other-in', { dir: n.path }) : msg('dirs-other');
  if (r.expandable) {
    const b = el('button', r.expanded ? '▾' : '▸', 'ar-toggle');
    b.type = 'button';
    b.setAttribute('aria-expanded', String(r.expanded));
    b.setAttribute('aria-label', `${r.expanded ? 'Collapse' : 'Expand'} ${n?.kind === 'dir' ? n.path : name}`);
    b.addEventListener('click', () => {
      if (expanded.has(r.key)) expanded.delete(r.key);
      else expanded.add(r.key);
      rerender();
    });
    label.append(b);
  } else {
    label.append(el('span', undefined, 'ar-toggle-space'));
  }
  const s = el('span', name, n?.kind === 'dir' ? 'rf-dir-name' : 'rf-dir-group');
  if (n?.kind === 'dir') s.title = n.path;
  label.append(s);
  th.append(label);
  tr.append(th);
  if (!n) {
    const td = el('td');
    td.colSpan = span;
    tr.append(td);
  }
  return tr;
}

function dirRow(r: DirRow, typical: (number | null)[], you: boolean, lo: number, hi: number): HTMLTableRowElement {
  const n = r.node;
  const tr = dirHead(r, state.expanded, renderDirs, you ? 11 : 9);
  if (!n) return tr;
  tr.append(heatCell(totalLines(n), lo, hi));
  n.lines.slice(1).forEach((v, i) => {
    const c = v + n.lines[i] >= state.all!.min_dir_lines / 4 ? change(v, n.lines[i]) : null;
    tr.append(el('td', ok(c) ? fmtChange(c) : '', i ? 'num' : 'num rl-group'));
  });
  pctHours(n, state.pct, MIN_TURNS).forEach((v, i) => tr.append(waitCell(v, typical[i], i ? 'num' : 'num rl-group')));
  if (you) {
    const y = n.you.row;
    const k = PCT_KEYS.indexOf(state.pct);
    tr.append(el('td', n.you.lines ? fmtBig(n.you.lines) : '', 'num rf-you-col rf-you-start'),
      waitCell(y && y[3] >= MIN_TURNS ? y[k] : null, n.all4?.[k] ?? null, 'num rf-you-col'));
  }
  return tr;
}

function renderDirs() {
  const all = state.all!;
  const p = state.person;
  const tq = all.table_quarters.slice(1);
  const head = $('#rl-dirs-quarters');
  const th = (text: string, cls: string, title?: string) => {
    const h = el('th', text, cls);
    h.setAttribute('scope', 'col');
    if (title) h.title = title;
    return h;
  };
  head.replaceChildren(
    ...tq.map((q, i) => th(quarterLabel(q), i ? 'num' : 'num rl-group')),
    ...tq.map((q, i) => th(quarterLabel(q), i ? 'num' : 'num rl-group')),
    th(msg('col-you-lines'), 'num rf-you-col rf-you-start', msg('title-you-lines')),
    th(msg('col-you-hours'), 'num rf-you-col', msg('title-you-hours')));
  const roots = dirTree(all, p);
  const typical = overallPct(all, state.pct);
  // The heat map's scale: from the table's threshold to its biggest directory.
  const lo = all.min_dir_lines;
  const hi = Math.max(lo * 10, ...roots.map(totalLines));
  $('#rl-dirs').classList.toggle('rf-with-you', !!p);
  $('#rl-dirs tbody').replaceChildren(...dirRows(roots, state.expanded, !!p).map((r) => dirRow(r, typical, !!p, lo, hi)));
  put($('#rl-dirs-note'), 'dirs-note', { from: quarterLabel(tq[0]), to: quarterLabel(tq.at(-1)!),
    minLines: fmtInt(all.min_dir_lines), minTurns: fmtInt(MIN_TURNS), you: !!p, pct: msg(`pct-${state.pct}`) });
}

// ---- the OWNERS table

const fmtShare = (a: number, b: number, min: number) =>
  (b >= min ? fmtNum(a / b, { style: 'percent', maximumFractionDigits: 0 }) : '');

function ownersRow(r: DirRow): HTMLTableRowElement {
  const n = r.node;
  const tr = dirHead(r, state.ownersExpanded, renderOwners, 6);
  if (!n) return tr;
  const o = n.own;
  const lines = totalLines(n);
  const of = (a: number | null, b: number | null) => (ok(a) && ok(b) && b ? msg('own-of', { n: fmtInt(a), of: fmtInt(b) }) : '');
  tr.append(el('td', fmtBig(lines), 'num'),
    el('td', o ? of(o.half, o.reviewers) : '', 'num'),
    el('td', o ? of(o.active, o.listed) : '', 'num'),
    el('td', o ? fmtShare(o.ownerLines, lines, 1) : '', 'num'),
    el('td', o && o.newLines ? fmtBig(o.newLines) : '', 'num rl-group'),
    el('td', o ? fmtShare(o.newTwo, o.newLines, MIN_NEW_LINES) : '', 'num'));
  return tr;
}

function renderOwners() {
  const all = state.all!;
  const section = $('#owners');
  section.hidden = !all.owners;
  if (!all.owners) return;
  const tq = all.table_quarters.slice(1);
  const o = ownRow(all.owners.all);
  const lines = all.reviewed_lines.slice(-tq.length).reduce((a, b) => a + b, 0);
  $('#rl-owners tbody').replaceChildren(...dirRows(dirTree(all, null), state.ownersExpanded, false).map(ownersRow));
  const pct = (a: number, b: number) => fmtNum(b ? a / b : 0, { style: 'percent', maximumFractionDigits: 0 });
  put($('#rl-owners-note'), 'owners-note', { from: quarterLabel(tq[0]), to: quarterLabel(tq.at(-1)!),
    at: new Date(`${all.owners.at}T00:00:00Z`).toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric', timeZone: 'UTC' }),
    reviewers: fmtInt(o.reviewers ?? 0), half: fmtInt(o.half ?? 0), listed: fmtInt(o.listed ?? 0), active: fmtInt(o.active ?? 0),
    idle: fmtInt((o.listed ?? 0) - (o.active ?? 0)), owner: pct(o.ownerLines, lines),
    newLines: fmtBig(o.newLines), two: pct(o.newTwo, o.newLines), twoLines: fmtBig(o.newTwo), minNew: fmtInt(MIN_NEW_LINES) });
}

function render() {
  if (!state.all) return;
  renderCommits();
  renderLines();
  renderSplit();
  renderReply();
  renderTurns();
  renderDirs();
  renderOwners();
  for (const id of ['#rl-att-from', '#rl-att-from-2']) $(id).textContent = quarterLabel(state.all.attention_from);
}

// ---- lookup

async function lookup(raw: string) {
  const note = $('#rl-find-note');
  const all = state.all;
  const range = all ? { from: quarterLabel(all.quarters[0]), to: quarterLabel(all.quarters.at(-1)!) } : { from: '', to: '' };
  if (!all || !looksLikeEmail(raw)) {
    put(note, 'find-none', range);
    return;
  }
  put(note, 'find-loading');
  try {
    const years = yearsOf(all.quarters);
    const tq = all.table_quarters.slice(1);
    // The per-reviewer files live in the R2 bucket, one per reviewer; they change only when a
    // quarter completes, so the newest quarter names their copies.
    const v = all.quarters.at(-1)!;
    let f = await getJson<PersonFile | { see: string }>(r2Url(LOAD_PEOPLE, `${personFile(raw)}.json`, v));
    // Another address of the reviewer points at their file (cosh/review_load.py).
    if (f && 'see' in f) f = isPersonFile(f.see) ? await getJson<PersonFile>(r2Url(LOAD_PEOPLE, `${f.see}.json`, v)) : null;
    if (f && 'see' in f) f = null;
    const found = f ? buildPerson(all,
      new Map(years.flatMap((y) => (f.years?.[y] ? [[y, f.years[y]] as [string, PersonYear]] : []))),
      new Map(tq.flatMap((q) => (f.dirs?.[q] ? [[q, f.dirs[q]] as [string, PersonDir[]]] : []))), f.turns, f.rows) : null;
    if (!found) {
      put(note, 'find-none', range);
      return;
    }
    state.person = found;
    window.__rl!.person = found;
    state.expanded = new Set();
    const qs = [...found.quarters.keys()];
    const total = (j: number) => [...found.quarters.values()].reduce((a, v) => a + v[j], 0);
    put(note, 'find-done', { n: fmtInt(qs.length), from: quarterLabel(qs[0]), to: quarterLabel(qs.at(-1)!),
      commits: fmtInt(total(0)), lines: fmtInt(total(1)) });
    render();
    document.body.dataset.person = '1';
  } catch (e) {
    put(note, 'find-error', { error: String(e instanceof Error ? e.message : e) });
  }
}

// ---- wiring

function init() {
  const input = $<HTMLInputElement>('#rl-email');
  $<HTMLFormElement>('#rl-find').addEventListener('submit', (e) => {
    e.preventDefault();
    void lookup(input.value);
  });
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => render());
  $('#rl-pct').addEventListener('change', (e) => {
    const v = (e.target as HTMLInputElement).value as PctKey;
    if (!PCT_KEYS.includes(v)) return;
    state.pct = v;
    if (state.all) renderDirs();
  });
  void getJson<All>(`${DATA}all.json`).then((a) => {
    state.all = a;
    window.__rl!.all = a;
    if (a) showDataSpan(a.data_span);
    render();
  }).catch(() => {}).finally(() => {
    document.body.dataset.ready = '1';
  });
  initAnchors();
}

init();
