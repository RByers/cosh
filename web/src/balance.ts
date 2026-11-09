// The Review Balance page (balance.html). Wording is in the HTML; this fills
// in the figures marked with data-src and draws the charts and tables, from
// summaries/balance.json (aggregates), balance_dirs.json and, for the
// authors section, balance_authors.json (one row per author: docs/balance.md).
import { BubbleController, Chart, Filler, type ChartDataset, type Plugin, type TooltipItem } from 'chart.js';
import balanceUrl from '../../summaries/balance.json?url';
import dirsUrl from '../../summaries/balance_dirs.json?url';
import authorsUrl from '../../summaries/balance_authors.json?url';
import type { DirRow } from './data.ts';
import { heatRowLabel, heatTable, node } from './heatmap.ts';
import { readTheme, type Theme } from './charts.ts';
import { fmtHoursBin, fmtNum, fmtQuarterMonth } from './format.ts';
import { fill, msg } from './text.ts';
import { initTerms } from './terms.ts';

Chart.register(Filler, BubbleController);

type Row = Record<string, string | number | null>;
interface BalanceData {
  generated: string;
  datasets: Record<string, Row[]>;
}

const $ = <T extends Element = HTMLElement>(sel: string) => document.querySelector<T>(sel)!;

const num = (digits: number) => (v: number) =>
  fmtNum(v, { minimumFractionDigits: digits, maximumFractionDigits: digits });
const pctOf = (digits: number) => (v: number) =>
  fmtNum(v, { style: 'percent', minimumFractionDigits: digits, maximumFractionDigits: digits });
const signed = (v: number) => (v > 0 ? '+' : v < 0 ? '−' : '') + num(3)(Math.abs(v));

/** Formats named by data-fmt in balance.html. */
export const FMT: Record<string, (v: number) => string> = {
  n0: num(0),
  n1: num(1),
  n2: num(2),
  n3: num(3),
  pct: pctOf(0),
  pct1: pctOf(1),
  x: (v) => `${num(2)(v)}×`,
  h: (v) => `${num(1)(v)} h`,
  habs: (v) => `${num(0)(Math.abs(v))} hours`,
  /** A difference of logs, as a relative change. */
  rel: (v) => `${v > 0 ? '+' : v < 0 ? '−' : ''}${num(0)(Math.abs(Math.expm1(v)) * 100)}%`,
  /** A difference of shares, in percentage points. */
  ptsabs: (v) => `${num(1)(Math.abs(v) * 100)} points`,
  abspct: (v) => pctOf(0)(Math.abs(Math.expm1(v))),
};

/** The row matching `where` ("k=v&k2=v2", compared as text). */
export function pick(rows: Row[], where: string): Row | undefined {
  const conds = where.split('&').filter(Boolean).map((kv) => {
    const i = kv.indexOf('=');
    return [kv.slice(0, i), kv.slice(i + 1)] as const;
  });
  return rows.find((r) => conds.every(([k, v]) => String(r[k]) === v));
}

/** Fills every figure placeholder; throws on one the data can't fill, so a
 * renamed field shows up in the tests rather than as a dash. */
function fillFigures(data: BalanceData) {
  for (const el of document.querySelectorAll<HTMLElement>('[data-src]')) {
    const { src, field, where = '', fmt = 'n1' } = el.dataset;
    const rows = data.datasets[src!];
    const row = rows && pick(rows, where);
    const v = row?.[field!];
    if (typeof v !== 'number') throw new Error(`no figure for ${src} ${field} ${where}`);
    el.textContent = FMT[fmt](v);
  }
}

// ---- charts

const LAST_QUARTER = '2026Q3';
const qLabel = (q: string) => q.replace('Q', ' Q');
const faint = (hex: string, alpha: string) => (/^#[0-9a-f]{6}$/i.test(hex) ? hex + alpha : hex);

/** A dashed horizontal line at `value` on the y axis (1.0 for the load
 * index, chance for growth). */
const refLine = (value: number, color: string): Plugin<'line' | 'bar'> => ({
  id: 'refLine',
  afterDatasetsDraw(chart) {
    const y = chart.scales.y.getPixelForValue(value);
    const { left, right } = chart.chartArea;
    const ctx = chart.ctx;
    ctx.save();
    ctx.strokeStyle = color;
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 3]);
    ctx.beginPath();
    ctx.moveTo(left, y);
    ctx.lineTo(right, y);
    ctx.stroke();
    ctx.restore();
  },
});

function axes(theme: Theme, fmt: (v: number) => string, opts: { zero?: boolean; max?: number } = {}) {
  const tick = { color: theme.muted, font: { family: theme.font } };
  return {
    x: { grid: { display: false }, border: { color: theme.baseline }, ticks: { ...tick, maxRotation: 0, autoSkipPadding: 12 } },
    y: {
      beginAtZero: !!opts.zero,
      max: opts.max,
      grid: { color: theme.grid },
      border: { display: false },
      ticks: { ...tick, maxTicksLimit: 6, callback: (v: number | string) => fmt(Number(v)) },
    },
  };
}

function options(theme: Theme, fmt: (v: number) => string, legend: boolean, title?: (i: number) => string) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    animation: false as const,
    interaction: { mode: 'index' as const, intersect: false },
    plugins: {
      legend: {
        display: legend,
        position: 'top' as const,
        align: 'start' as const,
        labels: { boxWidth: 14, boxHeight: 2, color: theme.text, font: { family: theme.font }, filter: (i: { text: string }) => !!i.text },
      },
      tooltip: {
        backgroundColor: theme.surface,
        titleColor: theme.parity,
        bodyColor: theme.parity,
        footerColor: theme.text,
        borderColor: theme.baseline,
        borderWidth: 1,
        boxWidth: 10,
        boxHeight: 2,
        filter: (i: TooltipItem<'line'>) => !!i.dataset.label,
        callbacks: {
          ...(title ? { title: (items: TooltipItem<'line'>[]) => (items.length ? title(items[0].dataIndex) : '') } : {}),
          label: (i: TooltipItem<'line'>) => `${i.dataset.label}: ${i.parsed.y === null ? '–' : fmt(i.parsed.y)}`,
        },
      },
    },
  };
}

interface SeriesSpec {
  field: string;
  label: string;
}

let charts: Chart[] = [];
let authorRows: AuthorRow[] = [];

function line(
  id: string,
  theme: Theme,
  labels: string[],
  series: { label: string; data: (number | null)[]; color: string; axis?: string }[],
  fmt: (v: number) => string,
  opts: {
    zero?: boolean; ref?: number; y2fmt?: (v: number) => string;
    /** Tooltip title and line text, for charts that say more than the value. */
    title?: (i: number) => string; tip?: (i: TooltipItem<'line'>) => string;
    /** Solid lines however many series (ordered series such as size tenths). */
    ramp?: boolean; pointRadius?: number;
  } = {},
) {
  const scales: Record<string, unknown> = axes(theme, fmt, opts);
  if (opts.y2fmt) {
    const f = opts.y2fmt;
    scales.y2 = {
      position: 'right',
      beginAtZero: true,
      grid: { display: false },
      border: { display: false },
      ticks: { color: theme.muted, font: { family: theme.font }, maxTicksLimit: 6, callback: (v: number | string) => f(Number(v)) },
    };
  }
  const o = options(theme, fmt, series.length > 1, opts.title);
  if (opts.tip) o.plugins.tooltip.callbacks.label = opts.tip;
  if (opts.y2fmt) {
    const f2 = opts.y2fmt;
    o.plugins.tooltip.callbacks.label = (i: TooltipItem<'line'>) =>
      `${i.dataset.label}: ${i.parsed.y === null ? '–' : (i.dataset.yAxisID === 'y2' ? f2 : fmt)(i.parsed.y)}`;
  }
  charts.push(new Chart($<HTMLCanvasElement>(`#${id}`), {
    type: 'line',
    data: {
      labels,
      // Past the palette's eight colours, lines repeat them dashed.
      datasets: series.map((s, i) => ({
        borderDash: i >= theme.series.length && !opts.ramp ? [5, 3] : [],
        label: s.label,
        data: s.data,
        yAxisID: s.axis ?? 'y',
        borderColor: s.color,
        backgroundColor: s.color,
        borderWidth: 2,
        pointRadius: opts.pointRadius ?? (labels.length > 12 ? 0 : 2.5),
        pointHoverRadius: 4,
        tension: 0,
        spanGaps: true,
      })),
    },
    options: { ...o, scales } as never,
    plugins: opts.ref === undefined ? [] : [refLine(opts.ref, theme.text)],
  }));
}

/** A quarterly line chart from one dataset, quarters up to LAST_QUARTER. */
function quarters(
  id: string, rows: Row[], theme: Theme, series: SeriesSpec[], fmt: (v: number) => string,
  opts: { zero?: boolean; ref?: number } = {},
) {
  const rs = rows.filter((r) => String(r.q) <= LAST_QUARTER);
  line(id, theme, rs.map((r) => qLabel(String(r.q))),
    series.map((s, i) => ({ label: s.label, data: rs.map((r) => r[s.field] as number | null), color: theme.series[i] })),
    fmt, opts);
}

/** Lines over ordered categories `xs` (labelled `xl`), one per group. */
function categories(
  id: string, rows: Row[], theme: Theme,
  spec: { x: string; g: string; v: string; xs: (string | number)[]; xl: (x: string | number) => string;
    groups: [string | number, string][] },
  fmt: (v: number) => string, opts: { zero?: boolean; ref?: number } = {},
) {
  const at = (g: string | number, x: string | number) =>
    rows.find((r) => String(r[spec.g]) === String(g) && String(r[spec.x]) === String(x));
  line(id, theme, spec.xs.map(spec.xl),
    spec.groups.map(([g, label], i) => ({
      label,
      data: spec.xs.map((x) => (at(g, x)?.[spec.v] as number | undefined) ?? null),
      color: theme.series[i % theme.series.length],
    })),
    fmt, opts);
}


/** A distribution over time: shaded bands from the 5th to the 95th
 * percentile (lighter) and the 25th to the 75th (darker), the median as a
 * line, and optionally a dashed line for an overall figure such as the mean.
 * `key` names fields key_p5 .. key_p95 in each row. The outer band reaches
 * p95 because 1 in 20 is still common (a slow review, a big CL); at the
 * bottom p5 is nearly always p10 (1 CL, no lines changed). */
function bands(
  id: string, rows: Row[], key: string, theme: Theme, fmt: (v: number) => string,
  opts: { label: string; x?: string; zero?: boolean; max?: number; extra?: { field: string; label: string } },
) {
  const x = opts.x ?? 'q';
  const c = theme.series[0];
  const col = (p: number) => rows.map((r) => (r[`${key}_p${p}`] as number | null) ?? null);
  const edge = (label: string, data: (number | null)[], fill: string | false, bg: string): ChartDataset<'line'> =>
    ({ label, data, borderWidth: 0, pointRadius: 0, pointHoverRadius: 0, backgroundColor: bg, fill, tension: 0 });
  const datasets: ChartDataset<'line'>[] = [
    edge('', col(95), '+3', faint(c, '1f')),
    edge('', col(75), '+1', faint(c, '40')),
    edge('', col(25), false, c),
    edge('', col(5), false, c),
    { label: opts.label, data: col(50), borderColor: c, backgroundColor: c, borderWidth: 2, pointRadius: 0,
      pointHoverRadius: 4, tension: 0, fill: false },
  ];
  if (opts.extra) {
    const e = opts.extra;
    datasets.push({ label: e.label, data: rows.map((r) => r[e.field] as number), borderColor: theme.text,
      backgroundColor: theme.text, borderWidth: 1.5, borderDash: [5, 3], pointRadius: 0, pointHoverRadius: 3,
      tension: 0, fill: false });
  }
  const labels = rows.map((r) => (x === 'q' ? qLabel(String(r.q)) : String(r[x])));
  const o = options(theme, fmt, true);
  o.plugins.tooltip.callbacks.label = (i: TooltipItem<'line'>) => {
    const r = rows[i.dataIndex];
    if (i.datasetIndex !== 4) return `${i.dataset.label}: ${fmt(i.parsed.y ?? 0)}`;
    const v = (p: number) => fmt(Number(r[`${key}_p${p}`]));
    return [`${opts.label}: ${v(50)}`, `  ${BAND_MID}: ${v(25)} to ${v(75)}`, `  ${BAND_WIDE}: ${v(5)} to ${v(95)}`] as unknown as string;
  };
  // The legend names the shaded bands too: lines as lines, bands as filled boxes.
  const item = (text: string, datasetIndex: number, style: 'line' | 'rect', color: string, lineWidth: number, lineDash: number[] = []) =>
    ({ text, datasetIndex, pointStyle: style, fillStyle: color, strokeStyle: color, lineWidth, lineDash, fontColor: theme.text });
  const legendItems = [
    item(opts.label, 4, 'line', c, 2),
    item(BAND_MID, 1, 'rect', faint(c, '57'), 0),
    item(BAND_WIDE, 0, 'rect', faint(c, '1f'), 0),
    ...(opts.extra ? [item(opts.extra.label, 5, 'line', theme.text, 1.5, [4, 2])] : []),
  ];
  const legend = {
    ...o.plugins.legend,
    labels: {
      ...o.plugins.legend.labels, usePointStyle: true, pointStyleWidth: 14, boxWidth: 14, boxHeight: 10,
      generateLabels: (chart: Chart) => legendItems.map((it) => ({ ...it, hidden: !chart.isDatasetVisible(it.datasetIndex) })),
    },
  };
  charts.push(new Chart($<HTMLCanvasElement>(`#${id}`), {
    type: 'line',
    data: { labels, datasets },
    options: { ...o, plugins: { ...o.plugins, legend }, scales: axes(theme, fmt, { zero: opts.zero, max: opts.max }) },
  } as never));
}

const BAND_MID = 'p25–p75';
const BAND_WIDE = 'p5–p95';

const PATHS: [string, string][] = [
  ['velocity', 'Velocity'], ['size', 'Size'], ['breadth', 'Breadth'], ['reviewing', 'Reviewing'], ['indep_threads', 'Independence'],
];
const CHANCE = 0.2;
const windowLabel = (w: string) => w.replace('-', '–20');

function growthBars(rows: Row[], theme: Theme) {
  const rs = rows.filter((r) => r.tenure === 'all' && r.window !== '2017-18');
  const o = options(theme, FMT.pct, true, (i) => windowLabel(String(rs[i].window)));
  o.plugins.tooltip.callbacks.label = (i: TooltipItem<'line'>) => {
    const r = rs[i.dataIndex];
    const key = PATHS[i.datasetIndex][0];
    return `${i.dataset.label}: ${FMT.pct(i.parsed.y ?? 0)} of ${FMT.n0(Number(r[`${key}_n`]))} people`;
  };
  (o.plugins.tooltip.callbacks as Record<string, unknown>).footer = (items: TooltipItem<'bar'>[]) =>
    items.length ? `Improving on none of the four git paths: ${FMT.pct(Number(rs[items[0].dataIndex].none_core4))}` : '';
  charts.push(new Chart($<HTMLCanvasElement>('#c-growth'), {
    type: 'bar',
    data: {
      labels: rs.map((r) => windowLabel(String(r.window))),
      datasets: PATHS.map(([k, label], i) => ({
        label, data: rs.map((r) => (r[k] as number | undefined) ?? null), backgroundColor: theme.series[i], borderRadius: 2,
      })),
    },
    options: { ...o, plugins: { ...o.plugins, legend: { ...o.plugins.legend, labels: { ...o.plugins.legend.labels, boxHeight: 10, boxWidth: 10 } } },
      scales: axes(theme, FMT.pct, { zero: true }) },
    plugins: [refLine(CHANCE, theme.text)],
  } as never));
}

/** Two periods' distributions side by side: shares of CLs per bin of hours. */
function yearHistogram(id: string, rows: Row[], summary: Row, theme: Theme) {
  const years = [
    { key: 'then', from: summary.then_from, to: summary.then_to, cls: summary.then_cls, color: theme.series[0] },
    { key: 'now', from: summary.now_from, to: summary.now_to, cls: summary.now_cls, color: theme.series[1] },
  ].map((y) => ({ ...y, label: msg('hist-range', { from: fmtQuarterMonth(String(y.from)), to: fmtQuarterMonth(String(y.to), true) }) }));
  const labels = rows.map((r) => fmtHoursBin(Number(r.lo), r.hi === null ? null : Number(r.hi)));
  const o = options(theme, FMT.pct, true, (i) => labels[i]);
  o.plugins.tooltip.callbacks.label = (i: TooltipItem<'line'>) =>
    `${i.dataset.label}: ${msg('hist-tip', { share: FMT.pct1(i.parsed.y ?? 0), cls: FMT.n0(Number(years[i.datasetIndex].cls)) })}`;
  charts.push(new Chart($<HTMLCanvasElement>(`#${id}`), {
    type: 'bar',
    data: {
      labels,
      datasets: years.map((y) => ({ label: y.label, data: rows.map((r) => r[y.key] as number), backgroundColor: y.color, borderRadius: 2 })),
    },
    options: { ...o, plugins: { ...o.plugins, legend: { ...o.plugins.legend, labels: { ...o.plugins.legend.labels, boxHeight: 10, boxWidth: 10 } } },
      scales: axes(theme, FMT.pct, { zero: true }) },
  } as never));
}

/** `t` (0..1) of the way from hex colour `a` to `b`. */
function mix(a: string, b: string, t: number): string {
  const rgb = (h: string) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const [x, y] = [rgb(a), rgb(b)];
  return '#' + x.map((v, i) => Math.round(v + (y[i] - v) * t).toString(16).padStart(2, '0')).join('');
}

/** "Defined: the review load index": one line per tenth of CLs by size, the
 * share of its CLs by reviewer threads, on a one-hue ramp from small to big. */
function loadDefinition(hist: Row[], deciles: Row[], theme: Theme) {
  const cs = getComputedStyle(document.documentElement);
  const lo = cs.getPropertyValue('--seq-lo').trim();
  const hi = cs.getPropertyValue('--seq-hi').trim();
  // One point per thread count; the open-ended last bin is left off (the caption gives its share).
  const bins = hist.filter((r) => r.decile === deciles[0].decile && r.hi !== null);
  const labels = bins.map((b) => (b.hi === b.lo ? String(b.lo) : `${b.lo}–${b.hi}`));
  const last = deciles.length - 1;
  const series = deciles.map((d, i) => ({
    label: i === last ? msg('loaddef-top', { lo: FMT.n0(Number(d.lo)) })
      : msg('loaddef-decile', { lo: FMT.n0(Number(d.lo)), hi: FMT.n0(Number(d.hi)) }),
    data: bins.map((b) => (hist.find((r) => r.decile === d.decile && r.bin === b.bin)?.share as number | undefined) ?? null),
    color: /^#[0-9a-f]{6}$/i.test(lo) && /^#[0-9a-f]{6}$/i.test(hi) ? mix(lo, hi, i / last) : theme.series[0],
  }));
  line('c-loaddef', theme, labels, series, FMT.pct, {
    zero: true, ramp: true, pointRadius: 1.5,
    title: (i) => msg('loaddef-bin', { threads: labels[i] }),
    tip: (i) => `${i.dataset.label}: ${msg('loaddef-tip', {
      share: FMT.pct1(i.parsed.y ?? 0), mean: FMT.n1(Number(deciles[i.datasetIndex].mean_threads)) })}`,
  });
}

const TENURE_BANDS: [string, string][] = [['lt2', 'Under 2 years'], ['y2_5', '2–5 years'], ['y5_10', '5–10 years'], ['y10p', '10+ years']];

function newcomerStack(rows: Row[], theme: Theme) {
  const o = options(theme, FMT.pct, true, (i) => `${rows[i].year}: ${FMT.n0(Number(rows[i].approvals))} newcomer approvals`);
  const scales = axes(theme, FMT.pct, { zero: true, max: 1 });
  charts.push(new Chart($<HTMLCanvasElement>('#c-newcomer'), {
    type: 'bar',
    data: {
      labels: rows.map((r) => String(r.year)),
      datasets: TENURE_BANDS.map(([k, label], i) => ({
        label, data: rows.map((r) => r[k] as number), backgroundColor: theme.series[i],
      })),
    },
    options: { ...o, plugins: { ...o.plugins, legend: { ...o.plugins.legend, labels: { ...o.plugins.legend.labels, boxHeight: 10, boxWidth: 10 } } },
      scales: { x: { ...scales.x, stacked: true }, y: { ...scales.y, stacked: true } } },
  } as never));
}

const HIST_QUARTERS = ['2023Q3', LAST_QUARTER];

/** Reviewers binned by load (`by` is "cls" or "threads"), one bar per quarter in HIST_QUARTERS. */
function loadHistogram(id: string, rows: Row[], by: string, theme: Theme) {
  const rs = rows.filter((r) => r.by === by);
  const bins = [...new Set(rs.map((r) => String(r.bin)))];
  const at = (q: string, b: string) => rs.find((r) => r.q === q && r.bin === b);
  const unit = by === 'cls' ? 'CLs reviewed' : 'threads';
  const o = options(theme, FMT.pct, true, (i) => `${bins[i].replace('-', '–')} ${by === 'cls' ? 'CLs' : 'threads'}`);
  const scales = axes(theme, FMT.pct, { zero: true });
  o.plugins.tooltip.callbacks.label = (i: TooltipItem<'line'>) => {
    const r = at(HIST_QUARTERS[i.datasetIndex], bins[i.dataIndex]);
    if (!r) return `${i.dataset.label}: –`;
    return `${i.dataset.label}: ${FMT.pct(Number(r.share))} of reviewers (${FMT.n0(Number(r.reviewers))}), ` +
      `${FMT.pct(Number(r.load_share))} of ${unit}`;
  };
  charts.push(new Chart($<HTMLCanvasElement>(`#${id}`), {
    type: 'bar',
    data: {
      labels: bins.map((b) => b.replace('-', '–')),
      datasets: HIST_QUARTERS.map((q, i) => ({
        label: qLabel(q), data: bins.map((b) => (at(q, b)?.share as number | undefined) ?? null),
        backgroundColor: theme.series[i], borderRadius: 2,
      })),
    },
    options: { ...o, plugins: { ...o.plugins, legend: { ...o.plugins.legend, labels: { ...o.plugins.legend.labels, boxHeight: 10, boxWidth: 10 } } },
      scales: { ...scales, x: { ...scales.x, ticks: { ...scales.x.ticks, autoSkip: false } } } },
  } as never));
}

/** Years since joining drawn in the review-share histogram. Year 1 is left out: most approve nothing. */
const SHARE_YEARS = [2, 3, 5, 8];
const shareBin = (b: number) => (b === 0 ? 'None' : `${(b - 1) * 10}–${b * 10}%`);

/** People binned by review share, one bar per year since joining, all join years pooled. */
function shareHistogram(rows: Row[], theme: Theme) {
  const bins = [...Array(11).keys()];
  const at = (y: number, b: number) => rows.find((r) => r.year === y && r.bin === b);
  const o = options(theme, FMT.pct, true, (i) => `Review share: ${shareBin(bins[i]).replace('None', 'none')}`);
  const scales = axes(theme, FMT.pct, { zero: true });
  o.plugins.tooltip.callbacks.label = (i: TooltipItem<'line'>) => {
    const r = at(SHARE_YEARS[i.datasetIndex], bins[i.dataIndex]);
    return r ? `${i.dataset.label}: ${FMT.pct(Number(r.share))} of people (${FMT.n0(Number(r.people))})` : `${i.dataset.label}: –`;
  };
  charts.push(new Chart($<HTMLCanvasElement>('#c-share-hist'), {
    type: 'bar',
    data: {
      labels: bins.map(shareBin),
      datasets: SHARE_YEARS.map((y, i) => ({
        label: `Year ${y}`, data: bins.map((b) => (at(y, b)?.share as number | undefined) ?? null),
        backgroundColor: theme.series[i], borderRadius: 2,
      })),
    },
    // Labels thin out on narrow screens; the hover card names every bin.
    options: { ...o, plugins: { ...o.plugins, legend: { ...o.plugins.legend, labels: { ...o.plugins.legend.labels, boxHeight: 10, boxWidth: 10 } } },
      scales: { ...scales, x: { ...scales.x, ticks: { ...scales.x.ticks, autoSkip: true, maxRotation: 0 } } } },
  } as never));
}

const ALWAYS_MECHANICAL =new Set(['100-199', '200-499', '500+']);

function mechanicalBars(rows: Row[], theme: Theme) {
  const o = options(theme, FMT.n3, false, (i) => `${rows[i].files} files`);
  o.plugins.tooltip.callbacks.label = (i: TooltipItem<'line'>) => `Threads per file: ${FMT.n3(i.parsed.y ?? 0)}`;
  (o.plugins.tooltip.callbacks as Record<string, unknown>).afterBody = (items: TooltipItem<'bar'>[]) => {
    const r = rows[items[0].dataIndex];
    return [`CLs: ${FMT.n0(Number(r.cls))}`, `Reverted within 30 days: ${FMT.pct1(Number(r.reverted))}`];
  };
  const tick = { color: theme.muted, font: { family: theme.font } };
  charts.push(new Chart($<HTMLCanvasElement>('#c-mechfiles'), {
    type: 'bar',
    data: {
      labels: rows.map((r) => String(r.files)),
      datasets: [{
        label: 'Threads per file',
        data: rows.map((r) => r.threads_per_file as number),
        backgroundColor: rows.map((r) => (ALWAYS_MECHANICAL.has(String(r.files)) ? theme.baseline : theme.series[0])),
        borderRadius: 2,
      }],
    },
    options: {
      ...o,
      scales: {
        x: { grid: { display: false }, border: { color: theme.baseline }, ticks: { ...tick, maxRotation: 0 } },
        y: {
          type: 'logarithmic', min: 0.0008, max: 1.2, grid: { color: theme.grid }, border: { display: false },
          afterBuildTicks: (axis: { ticks: { value: number }[] }) => { axis.ticks = [0.001, 0.01, 0.1, 1].map((value) => ({ value })); },
          ticks: { ...tick, callback: (v: number | string) => String(Number(v)) },
        },
      },
    },
  } as never));
}

// ---- tables

// ---- growth signals, patterns and security fixes

const SIGNAL_ERAS: [string, string][] = [['2023H2-2024', '2023 H2–2024'], ['2025', '2025'], ['2026', '2026 to October']];
const SIGNAL_TENURE: Record<string, string> = { '0-3': '0–3 mo', '3-6': '3–6', '6-12': '6–12', '12-24': '1–2 y', '24-60': '2–5 y', '60-120': '5–10 y', '120+': '10 y+' };
/** Signed, with the sign taken from the rounded value (no "−0.0"). */
const signedBy = (digits: number, scale = 1, unit = '') => (v: number) => {
  const r = Number((v * scale).toFixed(digits));
  return `${r > 0 ? '+' : r < 0 ? '−' : ''}${num(digits)(Math.abs(r))}${unit}`;
};
const pts = signedBy(1, 100, ' pts');
const rel = FMT.rel;
const plus = (digits: number) => signedBy(digits);

/** How each same-people panel measure is shown: [change format, raw format]. */
const PANEL_FMT: Record<string, [(v: number) => string, ((v: number) => string) | null]> = {
  reviewer_log1p_threads: [rel, FMT.n2],
  reviewer_neg_vote: [pts, FMT.pct1],
  author_log1p_threads_received: [rel, null],
  author_rounds: [plus(2), FMT.n2],
  author_interdiff_share: [pts, FMT.pct],
  author_reverted_30d: [pts, FMT.pct1],
  author_abandoned: [pts, FMT.pct1],
  author_pre_send_uploads: [plus(2), FMT.n2],
  author_neg_received: [pts, FMT.pct1],
};

/** A panel row's change and 95% interval as shares of its 2024 level: log
 * measures as relative changes, the rest divided by the 2024 figure. */
export function relChange(r: Row): [number, number, number] {
  const log = String(r.key).includes('log1p');
  const base = Number(r.raw_2024);
  const f = (v: number) => (log ? Math.expm1(v) : v / base);
  return [f(Number(r.change)), f(Number(r.lo)), f(Number(r.hi))];
}

/** A share as a signed whole percentage ("+52%", "0%"). */
const relPct = signedBy(0, 100, '%');

/** "Arriving better equipped, or easing off?": each same-people measure's change since 2024
 * as a dot and an interval on one shared scale, faded where the interval crosses zero. */
function forest(rows: Row[]) {
  const root = $('#forest');
  const rel = rows.map(relChange);
  const step = 0.25;
  const lo = Math.min(0, Math.floor(Math.min(...rel.map((x) => x[1])) / step) * step);
  const hi = Math.max(0, Math.ceil(Math.max(...rel.map((x) => x[2])) / step) * step);
  const at = (v: number) => String((v - lo) / (hi - lo));
  root.style.setProperty('--zero', at(0));
  const ticks = root.querySelector('.forest-ticks')!;
  const tickEls: HTMLElement[] = [];
  for (let k = 0; lo + k * step <= hi + 1e-9; k++) {
    const v = lo + k * step;
    const t = document.createElement('span');
    t.textContent = relPct(v);
    t.style.setProperty('--at', at(v));
    tickEls.push(t);
  }
  ticks.replaceChildren(...tickEls);
  const el = (tag: string, cls: string, text = '') => {
    const e = document.createElement(tag);
    e.className = cls;
    e.textContent = text;
    return e;
  };
  for (const ul of root.querySelectorAll<HTMLElement>('.forest-rows')) {
    ul.replaceChildren(...ul.dataset.keys!.split(' ').map((k) => {
      const i = rows.findIndex((r) => r.key === k);
      if (i < 0) throw new Error(`no panel row ${k}`);
      const r = rows[i];
      const [v, l, h] = rel[i];
      const [f, raw] = PANEL_FMT[k] ?? [signed, null];
      const clear = Number(r.lo) > 0 || Number(r.hi) < 0;
      const li = el('li', clear ? 'clear' : 'faded');
      li.style.setProperty('--lo', at(l));
      li.style.setProperty('--hi', at(h));
      li.style.setProperty('--v', at(v));
      const track = el('span', 'forest-track');
      track.append(el('i', 'forest-ci'), el('i', 'forest-dot'));
      li.append(el('span', 'forest-label', String(r.measure)), track, el('span', 'forest-val', relPct(v)));
      const years = raw ? `2024: ${raw(Number(r.raw_2024))}, 2026: ${raw(Number(r.raw_2026))}. ` : '';
      li.title = `${years}Change ${f(Number(r.change))}, 95% interval ${f(Number(r.lo))} to ${f(Number(r.hi))}; `
        + `${FMT.n0(Number(r.n))} ${r.side === 'reviewer' ? 'reviewers' : 'authors'}.`;
      return li;
    }));
  }
}

const MATCHED_ARMS: [string, string][] = [['joined 2024', 'Joined 2024'], ['joined 2025', 'Joined 2025']];
const MATCHED_MONTHS = ['0-3', '3-6', '6-9', '9-12'];

/** Matched cohorts: one small chart per measure, the 2025 joiners against their 2024 matches,
 * coloured as in the cohort charts above. */
function matchedCharts(rows: Row[], theme: Theme) {
  const at = (arm: string, m: string) => rows.find((r) => r.arm === arm && r.months === m);
  const chart = (id: string, field: string, fmt: (v: number) => string, opts: { zero?: boolean; ref?: number } = {}) =>
    line(id, theme, MATCHED_MONTHS.map((m) => `${m.replace('-', '–')} mo`),
      MATCHED_ARMS.map(([arm, label], i) => ({
        label, color: theme.series[i + 1],
        data: MATCHED_MONTHS.map((m) => (at(arm, m)?.[field] as number | undefined) ?? null),
      })), fmt, {
        ...opts,
        tip: (i) => {
          const r = at(MATCHED_ARMS[i.datasetIndex][0], MATCHED_MONTHS[i.dataIndex]);
          const v = i.parsed.y === null ? '–' : fmt(i.parsed.y);
          return r ? `${i.dataset.label}: ${v} (${FMT.n0(Number(r.active))} of ${FMT.n0(Number(r.people))} still active)`
            : `${i.dataset.label}: –`;
        },
      });
  chart('c-m-cls', 'cls_per_active_month', FMT.n1, { zero: true });
  chart('c-m-rev', 'reviews_given_per_active_month', FMT.n1, { zero: true });
  chart('c-m-load', 'load_index', FMT.n2, { zero: true, ref: 1 });
  chart('c-m-resid', 'threads_resid', FMT.n1, { zero: true });
  chart('c-m-interdiff', 'interdiff_p50', FMT.pct, { zero: true });
  chart('c-m-abandon', 'abandon_rate', FMT.pct1, { zero: true });
}

const RT_BANDS: [string, string][] = [['<2y', 'Under 2 years'], ['2-5y', '2–5 years'], ['5-10y', '5–10 years'], ['10y+', '10+ years']];

/** Reviewers by tenure: one chart per measure over half-years, a line per tenure band (the
 * same colours as the approvals-by-tenure chart). 2023 H1 is left off: only a few hundred
 * reviews, before the fetched history starts in earnest. */
function reviewerTenure(rows: Row[], theme: Theme) {
  const halves = [...new Set(rows.map((r) => String(r.half)))].filter((h) => h >= '2023H2').sort();
  const at = (band: string, h: string) => rows.find((r) => r.band === band && r.half === h);
  const chart = (id: string, field: string, fmt: (v: number) => string, extra?: (r: Row) => string) =>
    line(id, theme, halves.map((h) => h.replace('H', ' H')),
      RT_BANDS.map(([band, label], i) => ({
        label, color: theme.series[i],
        data: halves.map((h) => (at(band, h)?.[field] as number | undefined) ?? null),
      })), fmt, {
        zero: true,
        tip: (i) => {
          const r = at(RT_BANDS[i.datasetIndex][0], halves[i.dataIndex]);
          const v = i.parsed.y === null ? '–' : fmt(i.parsed.y);
          return r ? `${i.dataset.label}: ${v}${extra ? extra(r) : ''}, ${FMT.n0(Number(r.reviews))} CLs` : `${i.dataset.label}: –`;
        },
      });
  chart('c-rt-resp', 'resp_p50', FMT.h, (r) => ` (p75 ${FMT.h(Number(r.resp_p75))})`);
  chart('c-rt-threads', 'threads_per_review', FMT.n2);
  chart('c-rt-addressed', 'addressed_per_review', FMT.n2);
  chart('c-rt-newcomer', 'newcomer_share', FMT.pct);
}

const SEVERITIES: [string, string][] = [['critical', 'Critical'], ['high', 'High'], ['medium', 'Medium'], ['low', 'Low']];

function securityBars(rows: Row[], theme: Theme) {
  const o = options(theme, FMT.n0, true, (i) => `${rows[i].year}: ${FMT.n0(Number(rows[i].total))} CVEs`);
  const scales = axes(theme, FMT.n0, { zero: true });
  charts.push(new Chart($<HTMLCanvasElement>('#c-security'), {
    type: 'bar',
    data: {
      labels: rows.map((r) => (r.year === 2026 ? '2026 (to Nov)' : String(r.year))),
      datasets: SEVERITIES.map(([k, label], i) => ({
        label, data: rows.map((r) => r[k] as number), backgroundColor: theme.series[i],
      })),
    },
    options: { ...o, plugins: { ...o.plugins, legend: { ...o.plugins.legend, labels: { ...o.plugins.legend.labels, boxHeight: 10, boxWidth: 10 } } },
      scales: { x: { ...scales.x, stacked: true }, y: { ...scales.y, stacked: true } } },
  } as never));
}

// ---- authors in the last year (balance_authors.json)

type AuthorRow = [email: string, cls: number, dirs: number, load: number | null, tenure: number | null];
interface AuthorData {
  summary: Row;
  authors: AuthorRow[];
}

/** Bins of directories touched: tens up to 150, then 150 or more. */
const DIR_BINS = [...Array(15).keys()].map((i) => [i * 10, i * 10 + 9] as const);
const dirBin = ([lo, hi]: readonly [number, number]) => (lo === 0 ? `1–${hi}` : `${lo}–${hi}`);

function authorDirs(rows: AuthorRow[], theme: Theme) {
  const counts = [...DIR_BINS.map(() => 0), 0];
  for (const r of rows) counts[Math.min(DIR_BINS.length, Math.floor(r[2] / 10))]++;
  const labels = [...DIR_BINS.map(dirBin), `${DIR_BINS.length * 10}+`];
  const o = options(theme, FMT.n0, false, (i) => `${labels[i]} directories`);
  o.plugins.tooltip.callbacks.label = (i: TooltipItem<'line'>) =>
    `${FMT.n0(counts[i.dataIndex])} authors (${FMT.pct(counts[i.dataIndex] / rows.length)})`;
  const scales = axes(theme, FMT.n0, { zero: true });
  charts.push(new Chart($<HTMLCanvasElement>('#c-author-dirs'), {
    type: 'bar',
    data: { labels, datasets: [{ label: 'Authors', data: counts, backgroundColor: theme.series[0], borderRadius: 2 }] },
    options: { ...o, scales: { ...scales, x: { ...scales.x, ticks: { ...scales.x.ticks, autoSkip: true } } } },
  } as never));
}

/** Tenure bands for the scatter, in years at the end of the period; the same labels and colours as
 * the other tenure charts on the page. */
const AUTHOR_TENURE: [number, number, string][] = [[0, 2, 'Under 2 years'], [2, 5, '2–5 years'], [5, 10, '5–10 years'], [10, Infinity, '10+ years']];
/** The load index axis starts here: the few authors whose CLs drew no threads sit on the floor. */
const LOAD_FLOOR = 0.1;
/** Dot radius in px: area grows with CLs landed. */
const dotRadius = (cls: number) => 1.5 + Math.sqrt(cls) * 0.35;

function authorScatter(rows: AuthorRow[], theme: Theme) {
  const tenureOf = (t: number) => AUTHOR_TENURE.findIndex(([lo, hi]) => t >= lo && t < hi);
  // Big dots first, so small ones stay on top and can be hovered.
  const sorted = rows.filter((r) => r[3] !== null && r[4] !== null).sort((a, b) => b[1] - a[1]);
  const datasets = AUTHOR_TENURE.map(([, , label], i) => {
    const pts = sorted.filter((r) => tenureOf(r[4]!) === i);
    return {
      label,
      data: pts.map((r) => ({ x: r[2], y: Math.max(LOAD_FLOOR, r[3]!), r: dotRadius(r[1]) })),
      rows: pts,
      backgroundColor: faint(theme.series[i], '99'),
      borderColor: theme.series[i],
      borderWidth: 1,
      hoverBorderColor: theme.parity,
      hoverBorderWidth: 2,
    };
  });
  const o = options(theme, FMT.n2, true);
  const tick = { color: theme.muted, font: { family: theme.font } };
  const logTicks = (keep: number[], fmt: (v: number) => string) => (v: number | string) =>
    keep.includes(Number(v)) ? fmt(Number(v)) : '';
  const rowAt = (i: TooltipItem<'line'>) => (datasets[i.datasetIndex].rows as AuthorRow[])[i.dataIndex];
  charts.push(new Chart($<HTMLCanvasElement>('#c-author-scatter'), {
    type: 'bubble',
    data: { datasets },
    plugins: [refLine(1, theme.muted)],
    options: {
      ...o,
      interaction: { mode: 'nearest' as const, intersect: true },
      plugins: {
        ...o.plugins,
        legend: { ...o.plugins.legend, labels: { ...o.plugins.legend.labels, boxHeight: 10, boxWidth: 10 } },
        tooltip: {
          ...o.plugins.tooltip,
          callbacks: {
            title: (items: TooltipItem<'line'>[]) => (items.length ? rowAt(items[0])[0] : ''),
            label: (i: TooltipItem<'line'>) => {
              const [, cls, dirs, load, tenure] = rowAt(i);
              return msg('author-tip', { cls: FMT.n0(cls), dirs: FMT.n0(dirs), load: FMT.n2(load!),
                tenure: `${FMT.n1(tenure!)} years` });
            },
          },
        },
      },
      scales: {
        x: {
          type: 'logarithmic', min: 1,
          title: { display: true, text: 'Directories touched', color: theme.muted, font: { family: theme.font } },
          grid: { color: theme.grid }, border: { color: theme.baseline },
          ticks: { ...tick, autoSkip: false, maxRotation: 0, callback: logTicks([1, 2, 5, 10, 20, 50, 100, 200, 500, 1000], FMT.n0) },
        },
        y: {
          type: 'logarithmic', min: LOAD_FLOOR,
          title: { display: true, text: 'Review load index', color: theme.muted, font: { family: theme.font } },
          grid: { color: theme.grid }, border: { display: false },
          ticks: { ...tick, autoSkip: false, callback: logTicks([0.1, 0.2, 0.5, 1, 2, 5, 10], (v) => String(v)) },
        },
      },
    },
  } as never));
}

type Col = [field: string, fmt: (v: number) => string, cls?: (r: Row) => string];

function table(id: string, rows: Row[], cols: Col[]) {
  $<HTMLTableElement>(`#${id}`).tBodies[0].replaceChildren(...rows.map((r) => {
    const tr = document.createElement('tr');
    cols.forEach(([k, f, cls], i) => {
      const td = document.createElement(i === 0 ? 'th' : 'td');
      const v = r[k];
      td.textContent = v === null || v === undefined ? '–' : typeof v === 'number' ? f(v) : v;
      const c = cls?.(r);
      if (c) td.className = c;
      tr.append(td);
    });
    return tr;
  }));
}

const text = (v: number) => String(v);

/** "worse" where the wait grew by more than a tenth, "better" where it shrank by more. */
export const waitChange = (before: number | null, now: number | null) =>
  before === null || now === null || !before ? '' : (now - before) / before > 0.1 ? 'worse' : (now - before) / before < -0.1 ? 'better' : '';

// ---- across the codebase

/** Measures of the directory table, each a 2024 and a now column on one shared shading scale. */
const AREA_COLS: [string, (v: number) => string][] = [
  ['cls', FMT.n0], ['median_lines', FMT.n0], ['threads_per_100', FMT.n1], ['load_index', FMT.n2],
  ['ftr_p50', FMT.n1], ['review_time_p50', FMT.n1], ['newcomer_share', FMT.pct1],
];

/** Shading, 0..1, for each measure: CLs on a log scale (directories span three levels), the rest
 * linear from the 5th to the 95th percentile of every directory's two values. */
export function areaScales(rows: Row[]): Record<string, (v: number) => number> {
  const out: Record<string, (v: number) => number> = {};
  for (const [m] of AREA_COLS) {
    const xs = rows.flatMap((r) => [r[`y24_${m}`], r[`now_${m}`]])
      .filter((v): v is number => typeof v === 'number').sort((a, b) => a - b);
    const clamp = (t: number) => Math.min(1, Math.max(0, t));
    if (m === 'cls') {
      const lo = Math.log(Math.max(1, xs[0])), hi = Math.log(xs[xs.length - 1]);
      out[m] = (v) => clamp(hi > lo ? (Math.log(Math.max(1, v)) - lo) / (hi - lo) : 0.5);
    } else {
      const lo = quantile(xs, 0.05), hi = quantile(xs, 0.95);
      out[m] = (v) => clamp(hi > lo ? (v - lo) / (hi - lo) : 0.5);
    }
  }
  return out;
}

function areaTable(rows: Row[]) {
  const body = $<HTMLTableElement>('#t-areas').tBodies[0];
  const byPath = new Map(rows.map((r) => [String(r.area), r]));
  const kids = new Map<string | null, string[]>();
  for (const r of rows) {
    // Under the nearest directory that's in the table.
    let up = parentDir(String(r.area));
    while (up && !byPath.has(up)) up = parentDir(up);
    if (!kids.has(up)) kids.set(up, []);
    kids.get(up)!.push(String(r.area));
  }
  const size = (p: string) => (byPath.get(p)!.y24_cls as number) + (byPath.get(p)!.now_cls as number);
  for (const list of kids.values()) list.sort((a, b) => size(b) - size(a));
  const scale = areaScales(rows);
  const expanded = new Set<string>();

  const draw = () => {
    const trs: HTMLTableRowElement[] = [];
    const walk = (parent: string | null, depth: number) => {
      for (const path of kids.get(parent) ?? []) {
        const r = byPath.get(path)!;
        const open = expanded.has(path);
        const row: DirRow = {
          key: path, kind: 'dir', depth, label: depth ? path.slice((parent ?? '').length) : path, title: path,
          included: 1, value: size(path), byOrg: new Map(), expandable: kids.has(path), expanded: open,
        };
        const tr = node('tr', 'hm-row');
        tr.dataset.key = path;
        const th = heatRowLabel(row, path, '', (key) => {
          if (expanded.has(key)) expanded.delete(key);
          else expanded.add(key);
          draw();
        });
        th.title = path;
        tr.append(th);
        for (const [m, fmt] of AREA_COLS) {
          for (const era of ['y24', 'now']) {
            const v = r[`${era}_${m}`];
            const td = node('td', `area-cell area-${era}`, typeof v === 'number' ? fmt(v) : '–');
            if (typeof v === 'number') td.style.setProperty('--t', String(scale[m](v)));
            if ((m === 'ftr_p50' || m === 'review_time_p50') && era === 'now') {
              const c = waitChange(r[`y24_${m}`] as number | null, r[`now_${m}`] as number | null);
              if (c) td.classList.add(c);
            }
            tr.append(td);
          }
        }
        trs.push(tr);
        if (open) walk(path, depth + 1);
      }
    };
    walk(null, 0);
    body.replaceChildren(...trs);
  };
  draw();
}

// ---- directories over time

interface DirData {
  quarters: string[];
  fields: string[];
  dirs: { path: string; cls: number; q: ((number | null)[] | null)[] }[];
}

/** Cells resting on fewer CLs stay grey. */
export const DIR_CELL_MIN = 20;

const DIR_FMT: Record<string, (v: number) => string> = {
  load_index: (v) => `${num(2)(v)}×`,
  threads_per_100: num(1),
  ftr_p50: (v) => `${num(1)(v)} h`,
  review_time_p50: (v) => `${num(1)(v)} h`,
  interdiff_p50: pctOf(0),
  newcomer_share: pctOf(1),
  median_lines: num(0),
  cls: num(0),
};
const DIR_UNIT: Record<string, string> = {
  load_index: 'load index',
  threads_per_100: 'threads per 100 lines',
  ftr_p50: 'median hours to first review',
  review_time_p50: 'median review time',
  interdiff_p50: 'median share changed after review',
  newcomer_share: 'of CLs from newcomers',
  median_lines: 'median lines',
  cls: 'CLs',
};

/** A directory's parent path ("chrome/browser/" for "chrome/browser/ui/"), or null at the top. */
export const parentDir = (path: string) => {
  const parts = path.split('/').filter(Boolean);
  return parts.length > 1 ? parts.slice(0, -1).join('/') + '/' : null;
};

/** The p-th percentile of sorted values. */
const quantile = (xs: number[], p: number) => xs[Math.min(xs.length - 1, Math.floor(p * xs.length))];

function dirMap(data: DirData) {
  const box = $('#dir-chart');
  const byPath = new Map(data.dirs.map((d) => [d.path, d]));
  const kids = new Map<string | null, string[]>();
  for (const d of data.dirs) {
    const p = parentDir(d.path);
    // A directory whose parent was left out (too few CLs) goes under its nearest kept ancestor.
    let up = p;
    while (up && !byPath.has(up)) up = parentDir(up);
    if (!kids.has(up)) kids.set(up, []);
    kids.get(up)!.push(d.path);
  }
  for (const list of kids.values()) list.sort((a, b) => byPath.get(b)!.cls - byPath.get(a)!.cls);
  const expanded = new Set<string>();
  const metric = () => document.querySelector<HTMLInputElement>('input[name="dir-metric"]:checked')!.value;
  const field = (m: string) => data.fields.indexOf(m);
  const ncls = field('cls');

  const draw = () => {
    const m = metric();
    const fi = field(m);
    const fmt = DIR_FMT[m];
    const values = data.dirs.flatMap((d) => d.q.flatMap((c) =>
      c && (c[ncls] ?? 0) >= DIR_CELL_MIN && c[fi] !== null ? [c[fi]!] : [])).sort((a, b) => a - b);
    const volume = m === 'cls';
    const lo = volume ? 0 : quantile(values, 0.05);
    const hi = volume ? values[values.length - 1] : quantile(values, 0.95);
    const t = (v: number) => (volume ? Math.sqrt(v / hi) : hi > lo ? (v - lo) / (hi - lo) : 0.5);
    fill($('#dir-note'), { m });
    fill($('#dir-legend'), { lo: fmt(lo), hi: fmt(hi) });

    const rows: DirRow[] = [];
    const walk = (parent: string | null, depth: number) => {
      for (const path of kids.get(parent) ?? []) {
        const d = byPath.get(path)!;
        const open = expanded.has(path);
        rows.push({
          key: path, kind: 'dir', depth, label: depth ? path.slice((parent ?? '').length) : path, title: path,
          included: 1, value: d.cls, byOrg: new Map(), expandable: kids.has(path), expanded: open,
        });
        if (open) walk(path, depth + 1);
      }
    };
    walk(null, 0);

    const table = heatTable('dir-table', data.quarters.length);
    const head = node('thead');
    const hr = node('tr');
    const corner = node('th', 'hm-corner', msg('hm-corner'));
    corner.scope = 'col';
    hr.append(corner);
    data.quarters.forEach((q, i) => {
      const th = node('th', 'hm-bin');
      th.scope = 'col';
      const title = qLabel(q);
      // A tick at each year's first column.
      if (i === 0 || q.endsWith('Q1')) th.append(node('span', 'hm-tick', q.slice(0, 4)));
      th.append(node('span', 'visually-hidden', title));
      th.title = title;
      hr.append(th);
    });
    head.append(hr);
    const body = node('tbody');
    for (const r of rows) {
      const d = byPath.get(r.key)!;
      const tr = node('tr', 'hm-row hm-dir');
      tr.dataset.key = r.key;
      const th = heatRowLabel(r, r.title, num(0)(d.cls), (key) => {
        if (expanded.has(key)) expanded.delete(key);
        else expanded.add(key);
        draw();
      });
      th.title = `${r.title}: ${num(0)(d.cls)} CLs since July 2023`;
      tr.append(th);
      d.q.forEach((c, i) => {
        const td = node('td', 'hm-cell');
        const cell = node('span', 'hm-box');
        const n = c?.[ncls] ?? 0;
        const v = c?.[fi] ?? null;
        const lines = [`${r.title}, ${qLabel(data.quarters[i])}`, `${num(0)(n)} CLs`];
        if (c && n >= DIR_CELL_MIN && v !== null) {
          cell.classList.add('hm-shade');
          cell.style.setProperty('--t', String(Math.min(1, Math.max(0, t(v)))));
          if (!volume) lines.push(`${fmt(v)} ${DIR_UNIT[m]}`);
          cell.append(node('span', 'visually-hidden', `${fmt(v)} ${DIR_UNIT[m]}`));
        } else {
          cell.classList.add('hm-zero');
          if (n) lines.push('Too few CLs to shade');
          cell.append(node('span', 'visually-hidden', n ? 'too few CLs' : 'no CLs'));
        }
        cell.title = lines.join('\n');
        td.append(cell);
        tr.append(td);
      });
      body.append(tr);
    }
    table.append(head, body);
    box.replaceChildren(table);
  };
  for (const i of document.querySelectorAll<HTMLInputElement>('input[name="dir-metric"]')) i.addEventListener('change', draw);
  draw();
}

// ---- the page

// ---- the map of activity patterns

/** Colour order of the six patterns: fixed, so a pattern keeps its colour on
 * both maps and in the rules table (docs/balance-clusters.md). */
export const PATTERNS = [
  'authors who also review a lot', 'steady authors', 'newcomers ramping up',
  'mostly reviewing', 'early-career, light activity', 'reviewer-mentors',
];
const patternColor = (theme: Theme, p: string) => theme.series[Math.max(0, PATTERNS.indexOf(p))];
/** Axis ranges in PCA units, wide enough for every cell. */
const MAP_X: [number, number] = [-3.75, 4.25];
const MAP_Y: Record<string, [number, number]> = { pc2: [-4, 2.75], pc3: [-2.75, 3.25] };
const sentence = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/** Shade of a cell: more person-halves, more opaque (log scale). */
export function cellAlpha(n: number, max: number): number {
  return 0.12 + 0.68 * Math.log(n) / Math.log(Math.max(2, max));
}

/** An ellipse's outline points, for drawing and tests. */
export function ellipsePoints(e: { cx: number; cy: number; rx: number; ry: number; angle: number }, steps = 72) {
  const c = Math.cos(e.angle), s = Math.sin(e.angle);
  return Array.from({ length: steps + 1 }, (_, i) => {
    const t = (2 * Math.PI * i) / steps;
    const u = e.rx * Math.cos(t), v = e.ry * Math.sin(t);
    return { x: e.cx + u * c - v * s, y: e.cy + u * s + v * c };
  });
}

function patternMap(id: string, view: string, cells: Row[], ellipses: Row[], bin: number, theme: Theme) {
  const mine = cells.filter((r) => r.view === view);
  const max = Math.max(...mine.map((r) => Number(r.n)));
  const rgb = (hex: string, a: number) => faint(hex, Math.round(a * 255).toString(16).padStart(2, '0'));
  const datasets = PATTERNS.map((p) => ({
    label: sentence(p),
    pattern: p,
    data: mine.filter((r) => r.pattern === p).map((r) => ({ x: Number(r.x), y: Number(r.y), n: Number(r.n), share: Number(r.share) })),
    backgroundColor: patternColor(theme, p),
    borderColor: patternColor(theme, p),
    pointRadius: 0,
    pointHoverRadius: 0,
    pointHitRadius: 6,
  }));
  // Cells under the datasets, ellipses over them; both skip hidden patterns.
  const draw: Plugin<'scatter'> = {
    id: 'patternMap',
    beforeDatasetsDraw(chart) {
      const { x, y } = chart.scales;
      const ctx = chart.ctx;
      const { left, top, width, height } = chart.chartArea;
      ctx.save();
      ctx.beginPath();
      ctx.rect(left, top, width, height);
      ctx.clip();
      const w = Math.abs(x.getPixelForValue(bin) - x.getPixelForValue(0));
      const h = Math.abs(y.getPixelForValue(bin) - y.getPixelForValue(0));
      datasets.forEach((ds, i) => {
        if (!chart.isDatasetVisible(i)) return;
        for (const c of ds.data) {
          ctx.fillStyle = rgb(patternColor(theme, ds.pattern), cellAlpha(c.n, max));
          ctx.fillRect(x.getPixelForValue(c.x) - w / 2, y.getPixelForValue(c.y) - h / 2, w, h);
        }
      });
      // Centre lines: the average person active that half-year.
      ctx.strokeStyle = theme.baseline;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x.getPixelForValue(0), top);
      ctx.lineTo(x.getPixelForValue(0), top + height);
      ctx.moveTo(left, y.getPixelForValue(0));
      ctx.lineTo(left + width, y.getPixelForValue(0));
      ctx.stroke();
      ctx.restore();
    },
    afterDatasetsDraw(chart) {
      const { x, y } = chart.scales;
      const ctx = chart.ctx;
      ctx.save();
      for (const e of ellipses.filter((r) => r.view === view)) {
        const i = PATTERNS.indexOf(String(e.pattern));
        if (i < 0 || !chart.isDatasetVisible(i)) continue;
        const pts = ellipsePoints(e as unknown as { cx: number; cy: number; rx: number; ry: number; angle: number });
        const path = new Path2D();
        pts.forEach((p, j) => (j ? path.lineTo : path.moveTo).call(path, x.getPixelForValue(p.x), y.getPixelForValue(p.y)));
        // A surface halo keeps each outline readable over the cells.
        ctx.strokeStyle = theme.surface;
        ctx.lineWidth = 4;
        ctx.stroke(path);
        ctx.strokeStyle = patternColor(theme, String(e.pattern));
        ctx.lineWidth = 2;
        ctx.stroke(path);
        const cx = x.getPixelForValue(Number(e.cx)), cy = y.getPixelForValue(Number(e.cy));
        ctx.fillStyle = patternColor(theme, String(e.pattern));
        ctx.strokeStyle = theme.surface;
        ctx.beginPath();
        ctx.arc(cx, cy, 4, 0, 2 * Math.PI);
        ctx.fill();
        ctx.stroke();
      }
      ctx.restore();
    },
  };
  const tick = { display: false };
  const [x0, x1] = MAP_X, [y0, y1] = MAP_Y[view];
  const base = options(theme, FMT.n0, true);
  charts.push(new Chart($<HTMLCanvasElement>(`#${id}`), {
    type: 'scatter',
    data: { datasets },
    options: {
      ...base,
      interaction: { mode: 'nearest' as const, intersect: true },
      scales: {
        x: { type: 'linear', min: x0, max: x1, grid: { display: false }, border: { color: theme.baseline }, ticks: tick },
        y: { type: 'linear', min: y0, max: y1, grid: { display: false }, border: { color: theme.baseline }, ticks: tick },
      },
      plugins: {
        ...base.plugins,
        legend: { ...base.plugins.legend, labels: { ...base.plugins.legend.labels, boxHeight: 10, boxWidth: 10 } },
        tooltip: {
          ...base.plugins.tooltip,
          boxHeight: 10,
          filter: () => true,
          callbacks: {
            label: (i: TooltipItem<'scatter'>) => {
              const r = i.raw as { n: number; share: number };
              return `${i.dataset.label}: ${msg('map-tip', { n: FMT.n0(r.n), share: FMT.pct(r.share) })}`;
            },
          },
        },
      },
    },
    plugins: [draw],
  } as never));
}

/** Colour swatches beside the patterns in the rules table. */
function patternSwatches(theme: Theme) {
  for (const el of document.querySelectorAll<HTMLElement>('.swatch[data-pattern]')) {
    el.style.setProperty('--swatch', patternColor(theme, el.dataset.pattern!));
  }
}

function render(data: BalanceData) {
  fillFigures(data);
  const d = data.datasets;
  const theme = readTheme();
  for (const c of charts) c.destroy();
  charts = [];

  const exq = d.exchange.filter((r) => String(r.q) <= LAST_QUARTER);
  bands('c-velocity', exq, 'cls_per_author', theme, FMT.n1,
    { label: 'Median author', zero: true, extra: { field: 'cls_per_author', label: 'Mean' } });
  bands('c-size', exq, 'lines', theme, FMT.n0, { label: 'Median CL', zero: true });
  quarters('c-load', d.exchange, theme, [{ field: 'load_index', label: 'Load index' }], FMT.n2, { ref: 1 });
  const git = d.git_quarters.filter((r) => String(r.q) <= LAST_QUARTER);
  bands('c-longrun', git, 'per_author_month', theme, FMT.n1,
    { label: 'Median author', zero: true, extra: { field: 'per_author_month', label: 'Mean' } });
  bands('c-longlines', git, 'lines', theme, FMT.n0, { label: 'Median commit', zero: true });

  bands('c-perreviewer', d.reviewer_quarters.filter((r) => String(r.q) <= LAST_QUARTER), 'reviewed', theme, FMT.n0,
    { label: 'Median reviewer', zero: true, extra: { field: 'cls_per_reviewer', label: 'Merged CLs ÷ commenting reviewers' } });
  quarters('c-top10', d.git_quarters, theme, [{ field: 'top10_share', label: 'Busiest tenth' }], FMT.pct);
  loadHistogram('c-hist-cls', d.reviewer_load_hist, 'cls', theme);
  loadHistogram('c-hist-threads', d.reviewer_load_hist, 'threads', theme);

  bands('c-ftr', exq, 'ftr', theme, (v) => `${num(1)(v)} h`, { label: 'Median CL', zero: true });
  bands('c-waits', exq, 'review_time', theme, FMT.h,
    { label: 'Median CL', zero: true, extra: { field: 'review_time_p90', label: 'p90' } });
  yearHistogram('c-ftr-hist', d.ftr_hist, d.ftr_hist_summary[0], theme);
  yearHistogram('c-wait-hist', d.wait_hist, d.wait_hist_summary[0], theme);

  bands('c-interdiff', exq, 'interdiff_cl', theme, FMT.pct, { label: 'Median reviewed CL', zero: true, max: 1 });
  quarters('c-reverted', d.exchange, theme, [{ field: 'reverted', label: 'Reverted within 30 days' }], FMT.pct1, { zero: true });

  areaTable(d.areas);
  authorDirs(authorRows, theme);
  authorScatter(authorRows, theme);

  const eras: [string, string][] = [['2023H2-2024', '2023 H2–2024'], ['2025', '2025'], ['2026 (to Sep)', '2026 to September']];
  const tenureXl: Record<string, string> = { '0-3': '0–3 mo', '3-6': '3–6', '6-12': '6–12', '12-24': '1–2 y', '24-60': '2–5 y', '60-120': '5–10 y', '120-999': '10 y+' };
  categories('c-tenure', d.learning, theme, { x: 'bucket', g: 'era', v: 'load_index', groups: eras,
    xs: Object.keys(tenureXl), xl: (x) => tenureXl[x] }, FMT.n2, { ref: 1 });
  const famXl: Record<string, string> = { 'fam 0': 'None', 'fam 1-4': '1–4', 'fam 5-19': '5–19', 'fam 20-99': '20–99', 'fam 100+': '100+' };
  categories('c-fam', d.learning, theme, { x: 'bucket', g: 'era', v: 'load_index', groups: eras,
    xs: Object.keys(famXl), xl: (x) => famXl[x] }, FMT.n2, { ref: 1 });
  const rates: [string, string][] = [['prolific', 'Prolific (top fifth)'], ['average', 'Average (middle fifth)']];
  const pracTenureXl: Record<string, string> = { '0-3': '0–3 mo', '3-6': '3–6', '6-12': '6–12', '12-24': '1–2 y', '24-48': '2–4 y', '48+': '4 y+' };
  categories('c-prac-tenure', d.learning_practice.filter((r) => r.by === 'tenure'), theme, { x: 'bucket', g: 'group',
    v: 'load_index', groups: rates, xs: Object.keys(pracTenureXl), xl: (x) => pracTenureXl[x] }, FMT.n2, { ref: 1 });
  const landedXl: Record<string, string> = { '0-10': '0–9', '10-30': '10–29', '30-100': '30–99', '100-300': '100–299', '300-1000': '300–999', '1000+': '1,000+' };
  categories('c-prac-landed', d.learning_practice.filter((r) => r.by === 'practice'), theme, { x: 'bucket', g: 'group',
    v: 'load_index', groups: rates, xs: Object.keys(landedXl), xl: (x) => landedXl[x] }, FMT.n2, { ref: 1 });

  const cohorts: [string, string][] = [['joined 2023', 'Joined 2023'], ['joined 2024', 'Joined 2024'], ['joined 2025', 'Joined 2025']];
  const months = ['0-3', '3-6', '6-9', '9-12', '12-18', '18-24', '24-36'];
  const monthXl = (x: string | number) => `${String(x).replace('-', '–')} mo`;
  categories('c-co-load', d.cohort_curves, theme, { x: 'months', g: 'cohort', v: 'load_index', groups: cohorts, xs: months, xl: monthXl }, FMT.n2, { ref: 1 });
  categories('c-co-vel', d.cohort_curves, theme, { x: 'months', g: 'cohort', v: 'cls_per_person_month', groups: cohorts, xs: months, xl: monthXl }, FMT.n1, { zero: true });
  categories('c-co-rev', d.cohort_curves, theme, { x: 'months', g: 'cohort', v: 'reviews_per_person_month', groups: cohorts, xs: months, xl: monthXl }, FMT.n1, { zero: true });
  shareHistogram(d.review_share_hist, theme);
  const years = [2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025];
  categories('c-gitco', d.git_cohorts, theme, { x: 'year', g: 'cohort', v: 'review_share',
    groups: years.map((y) => [y, `Joined ${y}`]), xs: [1, 2, 3, 4, 5, 6, 7, 8, 9], xl: (x) => `Year ${x}` }, FMT.pct, { zero: true });
  reviewerTenure(d.reviewers_by_tenure, theme);

  growthBars(d.growth_windows, theme);

  newcomerStack(d.newcomer_review, theme);
  const pipe = d.pipeline;
  line('c-pipeline', theme, pipe.map((r) => String(r.year)), [
    { label: 'New regular reviewers', data: pipe.map((r) => r.new_regular_reviewers as number), color: theme.series[0] },
    { label: 'First added to OWNERS', data: pipe.map((r) => r.new_owners as number), color: theme.series[1] },
    { label: 'New authors', data: pipe.map((r) => r.new_authors as number), color: theme.series[2] },
  ], FMT.n0, { zero: true });
  line('c-mentors', theme, d.mentorship.map((r) => String(r.year)),
    [{ label: 'Became mentors within 4 years', data: d.mentorship.map((r) => r.became_mentors as number), color: theme.series[0] }],
    FMT.pct, { zero: true });
  const owner = d.promotion.filter((r) => r.years === 3 && Number(r.cohort) >= 2014);
  line('c-owner', theme, owner.map((r) => String(r.cohort)),
    [{ label: 'OWNER within 3 years', data: owner.map((r) => r.owner as number), color: theme.series[0] }], FMT.pct, { zero: true });

  categories('c-neg', d.signals_tenure, theme, { x: 'tenure_months', g: 'era', v: 'neg_index', groups: SIGNAL_ERAS,
    xs: Object.keys(SIGNAL_TENURE), xl: (x) => SIGNAL_TENURE[x] }, FMT.n2, { ref: 1, zero: true });
  categories('c-abandon', d.signals_tenure, theme, { x: 'tenure_months', g: 'era', v: 'abandon_index', groups: SIGNAL_ERAS,
    xs: Object.keys(SIGNAL_TENURE), xl: (x) => SIGNAL_TENURE[x] }, FMT.n2, { ref: 1, zero: true });
  const eraName = Object.fromEntries(SIGNAL_ERAS);
  table('t-signals', d.signals_era.map((r) => ({ ...r, era: eraName[String(r.era)] ?? r.era })), [
    ['era', text], ['cls', FMT.n0], ['abandon_rate', FMT.pct1], ['neg_share', FMT.pct1], ['after_neg_abandoned', FMT.pct],
  ]);
  forest(d.panels);
  matchedCharts(d.matched, theme);

  table('t-patterns', d.patterns, [
    ['pattern', text], ['share_pre', FMT.pct], ['share_recent', FMT.pct], ['tenure', FMT.n1], ['commits', FMT.n0],
    ['approvals', FMT.n0], ['owner', FMT.pct],
  ]);
  const mapSummary = d.pattern_map_summary[0];
  patternMap('c-map-pc2', 'pc2', d.pattern_cells, d.pattern_ellipses, Number(mapSummary.bin), theme);
  patternMap('c-map-pc3', 'pc3', d.pattern_cells, d.pattern_ellipses, Number(mapSummary.bin), theme);
  patternSwatches(theme);
  table('t-joiners', d.joiner_paths.map((r) => ({ ...r, cohort: String(r.cohort).replace('-', '–') })), [
    ['cohort', text], ['people', FMT.n0], ['light → reviewer', FMT.pct], ['ramping up to author', FMT.pct], ['stays light', FMT.pct],
  ]);
  table('t-transitions', d.transitions, [
    ['window', text], ['light_review', FMT.pct], ['light_author', FMT.pct], ['author_review', FMT.pct], ['review_review', FMT.pct],
  ]);

  securityBars(d.security_years, theme);

  table('t-ai', d.ai_paired, [['metric', text], ['diff', signed], ['lo', signed], ['hi', signed], ['n', FMT.n0]]);

  loadDefinition(d.load_def_hist, d.load_def_deciles, theme);

  mechanicalBars(d.mechanical_files, theme);
  table('t-mech', d.mechanical_repetition, [
    ['repetition', text], ['cls', FMT.n0], ['with_thread', FMT.pct], ['threads_per_file', FMT.n3], ['median_files', FMT.n0],
  ]);
}

async function main() {
  const main = $('main');
  try {
    const get = async <T,>(url: string) => {
      const r = await fetch(url);
      if (!r.ok) throw new Error(`${url}: ${r.status}`);
      return (await r.json()) as T;
    };
    const [data, dirs, authors] = await Promise.all([
      get<BalanceData>(balanceUrl), get<DirData>(dirsUrl), get<AuthorData>(authorsUrl)]);
    data.datasets.authors_summary = [authors.summary];
    authorRows = authors.authors;
    render(data);
    dirMap(dirs);
    initTerms();
    // Charts read their colours from CSS: redraw when the colour scheme flips.
    matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => render(data));
  } catch (e) {
    const err = $('#error');
    fill(err, { error: String(e) });
    err.hidden = false;
  } finally {
    main.removeAttribute('aria-busy');
    document.body.dataset.ready = '1';
  }
}

void main();
