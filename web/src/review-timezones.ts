// The Review Timezones page (review-timezones.html). Wording is in the HTML;
// this loads all.json (cosh/review_timezones.py), draws the chart of waits by
// working-hours overlap and fills the two tables. Aggregates only.
import { Chart, readTheme, withAlpha, type Theme } from './charts.ts';
import { fmtDay, fmtInt, fmtNum } from './format.ts';
import { quarterLabel, waitShade } from './load.ts';
import { fragment, msg, type Vars } from './text.ts';
import { showDataSpan, type DataSpan } from './data-span.ts';

/** [10th, 25th, 50th, 75th, 90th percentile] */
type P5 = [number, number, number, number, number];
export interface TzDir {
  d: string; n: number; listed: number; owners: [number, number, number]; unc: number;
  reg: string | null; mu: number | null; mc: number | null; extra: number;
}
export interface TzAll {
  quarters: string[];
  regions: string[];
  turns: number;
  cover_h: number;
  min_dir_turns: number;
  overlap: { lo: number; hi: number; n: number; p: P5 }[];
  by_region: Record<string, { n: number; wait: number; by: [number, number | null][] }>;
  people: number[];
  dirs: TzDir[];
  data_span?: DataSpan;
}

declare global {
  interface Window { __tz?: { all: TzAll | null; chart: Chart | null } }
}

const $ = <T extends Element = HTMLElement>(sel: string) => document.querySelector<T>(sel)!;
/** Rows of the directory table shown before "Show all". */
const FIRST_ROWS = 25;
const state = { all: null as TzAll | null, chart: null as Chart | null, allRows: false };
window.__tz = { all: null, chart: null };

const put = (target: Element, key: string, vars: Vars = {}) => target.replaceChildren(fragment(key, vars));
const ok = (v: number | null | undefined): v is number => typeof v === 'number' && Number.isFinite(v);
const fmtHours = (v: number | null | undefined) =>
  (ok(v) ? `${fmtNum(v, { maximumFractionDigits: v < 10 ? 1 : 0 })} h` : '–');
const fmtH = (v: number | null | undefined) => (ok(v) ? fmtNum(v, { maximumFractionDigits: v < 10 ? 1 : 0 }) : '');
const pct = (v: number) => fmtNum(v, { style: 'percent', maximumFractionDigits: 0 });

function el<K extends keyof HTMLElementTagNameMap>(tag: K, text?: string, cls?: string): HTMLElementTagNameMap[K] {
  const e = document.createElement(tag);
  if (text !== undefined) e.textContent = text;
  if (cls) e.className = cls;
  return e;
}

/** "none", "1–2 h", …: an overlap bin's label. */
export const overlapLabel = (lo: number, hi: number) =>
  (hi === 0 ? msg('overlap-none') : fragment('overlap-bin', { lo, hi }).textContent!.trim());

/** The first and last month of the quarters, and the day after the last (when the OWNERS files were read). */
function range(all: TzAll) {
  const first = all.quarters[0];
  const last = all.quarters.at(-1)!;
  const y = Number(last.slice(0, 4));
  const q = Number(last.slice(5));
  const end = new Date(Date.UTC(y, q * 3, 1) - 86400e3);
  return { from: quarterLabel(first), to: quarterLabel(last), at: fmtDay(end) };
}

// ---- the chart

function legend(target: Element, t: Theme) {
  const items = [['legend-median', t.text, ''], ['legend-mid', withAlpha(t.series[0], 0.6), 'swatch-band'],
    ['legend-wide', withAlpha(t.series[0], 0.25), 'swatch-band']] as const;
  target.replaceChildren(...items.map(([key, color, cls]) => {
    const li = el('li');
    const sw = el('span', undefined, `swatch ${cls}`.trim());
    sw.style.setProperty('--color', color);
    li.append(sw, document.createTextNode(msg(key)));
    return li;
  }));
}

function renderOverlap() {
  const all = state.all!;
  const t = readTheme();
  state.chart?.destroy();
  const bins = all.overlap;
  const labels = bins.map((b) => overlapLabel(b.lo, b.hi));
  const axis = (title: string) => ({ grid: { color: t.grid }, title: { display: true, text: title, color: t.text },
    ticks: { color: t.text, font: { family: t.font } } });
  legend($('#tz-overlap-legend'), t);
  state.chart = new Chart<'bar' | 'line', (number | [number, number])[], string>($<HTMLCanvasElement>('#tz-overlap'), {
    type: 'bar',
    data: {
      labels,
      datasets: [
        { type: 'line', label: msg('legend-median'), data: bins.map((b) => b.p[2]), borderColor: t.text,
          backgroundColor: t.text, borderWidth: 0, pointStyle: 'line', pointRadius: 18, pointBorderWidth: 3,
          pointHoverRadius: 18, showLine: false, order: 0 },
        { label: msg('legend-mid'), data: bins.map((b) => [b.p[1], b.p[3]] as [number, number]),
          backgroundColor: withAlpha(t.series[0], 0.6), grouped: false, barPercentage: 0.5, order: 1 },
        { label: msg('legend-wide'), data: bins.map((b) => [b.p[0], b.p[4]] as [number, number]),
          backgroundColor: withAlpha(t.series[0], 0.25), grouped: false, barPercentage: 0.5, order: 2 },
      ],
    },
    options: {
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: 'index', intersect: false },
      scales: {
        x: { ...axis(msg('axis-overlap')), grid: { display: false } },
        y: { ...axis(msg('axis-wait')), beginAtZero: true },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: (items) => {
              const b = bins[items[0].dataIndex];
              return `${labels[items[0].dataIndex]}: ${fmtInt(b.n)} ${msg('tip-turns')}`;
            },
            label: (i) => {
              const v = i.raw as number | [number, number];
              return `${i.dataset.label}: ${Array.isArray(v) ? `${fmtHours(v[0])}–${fmtHours(v[1])}` : fmtHours(v)}`;
            },
          },
        },
      },
    },
  });
  window.__tz!.chart = state.chart;
  const lowShare = bins.filter((b) => b.hi <= 2).reduce((s, b) => s + b.n, 0) / Math.max(1, all.turns);
  const { from, to } = range(all);
  put($('#tz-overlap-note'), 'overlap-note', { from, to, n: fmtInt(all.turns), none: fmtHours(bins[0].p[2]),
    full: fmtHours(bins.at(-1)!.p[2]), share: pct(lowShare) });
}

// ---- who reviews whom

function renderRegions() {
  const all = state.all!;
  $('#tz-regions-cols').replaceChildren(...all.regions.map((r) => el('th', msg(`region-${r}`), 'num')));
  const body = $('#tz-regions tbody');
  body.replaceChildren(...all.regions.map((ar) => {
    const g = all.by_region[ar];
    const tr = el('tr');
    tr.append(el('th', msg(`region-${ar}`)), el('td', fmtInt(g.n), 'num'), el('td', fmtHours(g.wait), 'num'));
    tr.firstElementChild!.setAttribute('scope', 'row');
    g.by.forEach(([n, wait], j) => {
      const td = el('td', '', 'num');
      td.append(fragment('share-wait', { share: pct(n / Math.max(1, g.n)), wait: fmtHours(wait) }));
      const shade = waitShade(wait, g.wait);
      if (shade && n) {
        td.classList.add(shade > 0 ? 'rf-ratio-hi' : 'rf-ratio-lo');
        td.style.setProperty('--rf-shade', String(Math.abs(shade)));
      }
      if (all.regions[j] === ar) td.classList.add('tz-own');
      tr.append(td);
    });
    return tr;
  }));
  const r = all.by_region;
  const ap = r.APAC;
  put($('#tz-regions-note'), 'regions-note', {
    last: quarterLabel(all.quarters.at(-1)!), am: fmtInt(all.people[0]), em: fmtInt(all.people[1]),
    ap: fmtInt(all.people[2]), apWait: fmtHours(ap?.wait), amWait: fmtHours(r.Americas?.wait),
    apOwn: ap ? pct(ap.by[all.regions.indexOf('APAC')][0] / Math.max(1, ap.n)) : '–',
  });
}

// ---- the directory table

/** The OWNERS file of a directory, on Chromium Code Search. */
export const ownersUrl = (d: string) =>
  `https://source.chromium.org/chromium/chromium/src/+/main:${d === '/' ? '' : d}OWNERS`;

function dirRow(r: TzDir, maxExtra: number): HTMLTableRowElement {
  const tr = el('tr');
  const th = el('th');
  th.setAttribute('scope', 'row');
  const a = el('a', r.d, 'rf-dir-name');
  a.href = ownersUrl(r.d);
  a.target = '_blank';
  a.rel = 'noopener';
  th.append(a);
  tr.append(th, el('td', fmtInt(r.n), 'num'));
  const active = r.owners.reduce((s, x) => s + x, 0);
  r.owners.forEach((x, i) => {
    const td = el('td', String(x), i === 0 ? 'num rl-group' : 'num');
    td.classList.toggle('tz-none', x === 0);
    td.title = fragment('title-owners-of', { n: active, of: r.listed }).textContent!.trim();
    tr.append(td);
  });
  tr.append(el('td', pct(r.unc / r.n), 'num rl-group'), el('td', r.reg ? msg(`region-short-${r.reg}`) : ''));
  const unc = el('td', fmtH(r.mu), 'num rl-group');
  const shade = waitShade(r.mu, r.mc);
  if (shade) {
    unc.classList.add(shade > 0 ? 'rf-ratio-hi' : 'rf-ratio-lo');
    unc.style.setProperty('--rf-shade', String(Math.abs(shade)));
  }
  tr.append(unc, el('td', fmtH(r.mc), 'num'));
  const extra = el('td', r.extra ? fmtInt(r.extra) : '', 'num rl-group rl-heat');
  const heat = maxExtra > 0 ? r.extra / maxExtra : 0;
  extra.style.setProperty('--rl-heat', heat.toFixed(3));
  extra.classList.toggle('rl-heat-dark', heat > 0.5);
  tr.append(extra);
  return tr;
}

function renderDirs() {
  const all = state.all!;
  $('#tz-dirs-cols').replaceChildren(
    ...['col-am', 'col-em', 'col-ap'].map((k, i) => el('th', msg(k), i === 0 ? 'num rl-group' : 'num')),
    el('th', msg('col-outside'), 'num rl-group'), el('th', msg('col-inside'), 'num'));
  const rows = state.allRows ? all.dirs : all.dirs.slice(0, FIRST_ROWS);
  const maxExtra = Math.max(0, ...all.dirs.map((r) => r.extra));
  $('#tz-dirs tbody').replaceChildren(...rows.map((r) => dirRow(r, maxExtra)));
  const more = $<HTMLButtonElement>('#tz-dirs-more');
  more.hidden = state.allRows || all.dirs.length <= FIRST_ROWS;
  put(more, 'dirs-more', { n: fmtInt(all.dirs.length) });
  put($('#tz-dirs-note'), 'dirs-note', { at: range(all).at, cover: all.cover_h, minTurns: fmtInt(all.min_dir_turns) });
}

function render() {
  if (!state.all) return;
  renderOverlap();
  renderRegions();
  renderDirs();
}

function init() {
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => state.all && renderOverlap());
  $('#tz-dirs-more').addEventListener('click', () => {
    state.allRows = true;
    renderDirs();
  });
  void fetch('review-timezones/all.json').then(async (r) => {
    if (!r.ok) throw new Error(`all.json: ${r.status}`);
    const a = (await r.json()) as TzAll;
    state.all = a;
    window.__tz!.all = a;
    showDataSpan(a.data_span);
    render();
  }).catch(() => {}).finally(() => {
    document.body.dataset.ready = '1';
  });
}

init();
