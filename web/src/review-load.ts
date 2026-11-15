// The Review Load page (review-load.html). Wording is in the HTML; this
// loads all.json, draws the charts and the directory table, and looks a
// reviewer up by the address typed (never offering completions: their data
// is in files named by a hash of the address) to add their figures. The
// address is never put in the URL.
import { Chart, type ChartDataset } from 'chart.js';
import { readTheme, type Theme } from './charts.ts';
import { looksLikeEmail, personKey } from './feedback.ts';
import { fmtInt, fmtNum } from './format.ts';
import {
  buildPerson,
  change,
  dirRows,
  dirTree,
  meanAttention,
  meanHours,
  meanLines,
  overallHours,
  personSeries,
  quarterLabel,
  ratio,
  totalLines,
  waitShade,
  yearsOf,
  type All,
  type DirRow,
  type Person,
  type PersonDir,
  type PersonYear,
} from './load.ts';
import { LOAD_PEOPLE, r2Url } from './r2.ts';
import { fragment, msg, type Vars } from './text.ts';

declare global {
  interface Window {
    __rl?: { all: All | null; person: Person | null; charts: Record<string, Chart> };
  }
}

const $ = <T extends Element = HTMLElement>(sel: string) => document.querySelector<T>(sel)!;
const DATA = 'review-load/';
/** A table cell needs this many reviewer turns to show a mean. */
const MIN_TURNS = 5;

const state = {
  all: null as All | null,
  person: null as Person | null,
  expanded: new Set<string>(),
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

/** A chart over the quarters; `format` writes a tooltip line's value, `extra` adds to it. */
function draw(name: string, datasets: Line[], t: Theme,
  scales: Record<string, object>, format: (v: number, dataset: number) => string,
  extra?: (dataset: number, i: number) => string) {
  destroy(name);
  const all = state.all!;
  charts[name] = new Chart<'bar' | 'line', (number | null)[], string>($<HTMLCanvasElement>(`#rl-${name}`), {
    type: 'line',
    data: { labels: all.quarters.map(quarterLabel), datasets },
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
              return `${i.dataset.label}: ${format(v, i.datasetIndex)}${extra?.(i.datasetIndex, i.dataIndex) ?? ''}`;
            },
          },
        },
      },
    },
  });
}

/** The newest quarter and its index. */
const lastOf = (all: All) => ({ i: all.quarters.length - 1, q: quarterLabel(all.quarters.at(-1)!) });

function renderCommits() {
  const all = state.all!;
  const p = state.person;
  const t = theme();
  const { i, q } = lastOf(all);
  const keys: Key[] = [{ label: msg('legend-commits'), color: t.series[0] }, { label: msg('legend-human'), color: t.series[1] }];
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

function renderLines() {
  const all = state.all!;
  const p = state.person;
  const t = theme();
  const { i, q } = lastOf(all);
  const mean = meanLines(all);
  const keys: Key[] = [{ label: msg('legend-mean-lines'), color: t.series[0] }];
  const datasets: Line[] = [line(keys[0].label, mean, keys[0].color, { pointRadius: 2 })];
  if (p) {
    keys.push({ label: msg('legend-you'), color: youColor(t) });
    datasets.push(youLine(t, personSeries(p, all.quarters, (v) => v[1])));
  }
  legend($('#rl-lines-legend'), keys);
  // The growth: each quarter against the one before and against a year before.
  const growth = (d: number, k: number) => {
    const s = datasets[d].data;
    const parts = [k >= 1 ? fmtChange(change(s[k], s[k - 1])) : '–', k >= 4 ? fmtChange(change(s[k], s[k - 4])) : '–'];
    return ` (${parts[0]} on the quarter before, ${parts[1]} on a year before)`;
  };
  draw('lines', datasets, t, { y: { ...axis(t, msg('axis-lines')), beginAtZero: true } }, (v) => fmtInt(Math.round(v)), growth);
  put($('#rl-lines-note'), 'lines-note', { last: q, mean: fmtInt(Math.round(mean[i] ?? 0)), reviewers: fmtInt(all.reviewers[i]),
    qoq: fmtChange(change(mean[i], mean[i - 1])), yoy: fmtChange(change(mean[i], mean[i - 4])),
    first: fmtInt(Math.round(mean[0] ?? 0)), firstQ: quarterLabel(all.quarters[0]) });
}

function renderFirst() {
  const all = state.all!;
  const p = state.person;
  const t = theme();
  const { i, q } = lastOf(all);
  const keys: Key[] = [{ label: msg('legend-first-mean'), color: t.series[0] },
    { label: msg('legend-first-median'), color: t.series[0], dash: true },
    { label: msg('legend-reply-mean'), color: t.series[2] }];
  const datasets: Line[] = [line(keys[0].label, all.first.mean, keys[0].color),
    line(keys[1].label, all.first.median, keys[1].color, { borderDash: [5, 4], borderWidth: 1.5 }),
    line(keys[2].label, all.reply.mean, keys[2].color)];
  if (p) {
    keys.push({ label: msg('legend-you'), color: youColor(t) });
    datasets.push(youLine(t, personSeries(p, all.quarters, (v) => ratio(v[4], v[5]))));
  }
  legend($('#rl-first-legend'), keys);
  draw('first', datasets, t, { y: { ...axis(t, msg('axis-hours')), beginAtZero: true } }, (v) => fmtHours(v));
  put($('#rl-first-note'), 'first-note', { last: q, mean: fmtHours(all.first.mean[i]), median: fmtHours(all.first.median[i]),
    reply: fmtHours(all.reply.mean[i]), attFrom: quarterLabel(all.attention_from), you: !!p });
}

function renderAttention() {
  const all = state.all!;
  const p = state.person;
  const t = theme();
  const { i, q } = lastOf(all);
  const mean = meanAttention(all);
  const keys: Key[] = [{ label: msg('legend-attention-total'), color: t.grid, band: true },
    { label: msg('legend-attention-mean'), color: t.series[0] }];
  const datasets: Line[] = [
    { type: 'bar', label: keys[0].label, data: all.attention.hours, backgroundColor: t.grid, yAxisID: 'y', order: 2 },
    line(keys[1].label, mean, keys[1].color, { yAxisID: 'each', pointRadius: 2, order: 1 })];
  if (p) {
    keys.push({ label: msg('legend-you-right'), color: youColor(t) });
    datasets.push(youLine(t, personSeries(p, all.quarters, (v) => (v[3] ? v[2] : null)), { yAxisID: 'each' }));
  }
  legend($('#rl-attention-legend'), keys);
  draw('attention', datasets, t, {
    y: { ...axis(t, msg('axis-attention-total')), beginAtZero: true, grid: { display: false },
      ticks: { color: t.text, font: { family: t.font }, callback: (v: number | string) => fmtBig(Number(v)) } },
    each: { ...axis(t, msg('axis-attention-mean')), position: 'right', beginAtZero: true },
  }, (v, d) => (d === 0 ? `${fmtInt(Math.round(v))} h` : fmtHours(v)));
  put($('#rl-attention-note'), 'attention-note', { last: q, attFrom: quarterLabel(all.attention_from),
    reviewers: fmtInt(all.attention.reviewers[i] ?? 0), total: fmtInt(all.attention.hours[i] ?? 0),
    mean: fmtInt(Math.round(mean[i] ?? 0)), turn: fmtNum(ratio(all.attention.hours[i], all.attention.turns[i]) ?? 0,
      { maximumFractionDigits: 1 }), you: !!p });
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

function dirRow(r: DirRow, typical: (number | null)[], you: boolean): HTMLTableRowElement {
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
      if (state.expanded.has(r.key)) state.expanded.delete(r.key);
      else state.expanded.add(r.key);
      renderDirs();
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
    td.colSpan = you ? 11 : 9;
    tr.append(td);
    return tr;
  }
  tr.append(el('td', fmtBig(totalLines(n)), 'num'));
  n.lines.slice(1).forEach((v, i) => {
    const c = v + n.lines[i] >= state.all!.min_dir_lines / 4 ? change(v, n.lines[i]) : null;
    tr.append(el('td', ok(c) ? fmtChange(c) : '', i ? 'num' : 'num rl-group'));
  });
  meanHours(n, MIN_TURNS).forEach((v, i) => tr.append(waitCell(v, typical[i], i ? 'num' : 'num rl-group')));
  if (you) {
    const y = n.you;
    const all4 = ratio(n.hours.reduce((a, b) => a + b, 0), n.turns.reduce((a, b) => a + b, 0));
    tr.append(el('td', y.lines ? fmtBig(y.lines) : '', 'num rf-you-col rf-you-start'),
      waitCell(y.turns >= MIN_TURNS ? y.hours / y.turns : null, all4, 'num rf-you-col'));
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
  const typical = overallHours(roots, all.table_quarters.length);
  $('#rl-dirs').classList.toggle('rf-with-you', !!p);
  $('#rl-dirs tbody').replaceChildren(...dirRows(roots, state.expanded, !!p).map((r) => dirRow(r, typical, !!p)));
  put($('#rl-dirs-note'), 'dirs-note', { from: quarterLabel(tq[0]), to: quarterLabel(tq.at(-1)!),
    minLines: fmtInt(all.min_dir_lines), minTurns: fmtInt(MIN_TURNS), you: !!p });
}

function render() {
  if (!state.all) return;
  renderCommits();
  renderLines();
  renderFirst();
  renderAttention();
  renderDirs();
  $('#rl-att-from').textContent = quarterLabel(state.all.attention_from);
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
    const k = await personKey(raw);
    const years = yearsOf(all.quarters);
    const tq = all.table_quarters.slice(1);
    // The per-reviewer files live in the R2 bucket; they change only when a quarter
    // completes, so the newest quarter names their copies.
    const v = all.quarters.at(-1)!;
    const [ys, ds] = await Promise.all([
      Promise.all(years.map((y) => getJson<PersonYear>(r2Url(LOAD_PEOPLE, `${y}/${k}.json`, v)))),
      Promise.all(tq.map((q) => getJson<PersonDir[]>(r2Url(LOAD_PEOPLE, `dirs/${q}/${k}.json`, v)))),
    ]);
    const found = buildPerson(all,
      new Map(years.flatMap((y, i) => (ys[i] ? [[y, ys[i]!] as [string, PersonYear]] : []))),
      new Map(tq.flatMap((q, i) => (ds[i] ? [[q, ds[i]!] as [string, PersonDir[]]] : []))));
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
  void getJson<All>(`${DATA}all.json`).then((a) => {
    state.all = a;
    window.__rl!.all = a;
    render();
  }).catch(() => {}).finally(() => {
    document.body.dataset.ready = '1';
  });
}

init();
