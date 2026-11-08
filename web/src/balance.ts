// The Review Balance page (balance.html). Wording is in the HTML; this fills
// in the figures marked with data-src and draws the charts and tables, all
// from summaries/balance.json (aggregates only: docs/balance.md).
import { Chart, Filler, type ChartDataset, type Plugin, type TooltipItem } from 'chart.js';
import balanceUrl from '../../summaries/balance.json?url';
import { readTheme, type Theme } from './charts.ts';
import { fmtNum } from './format.ts';
import { fill } from './text.ts';

Chart.register(Filler);

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

function line(
  id: string,
  theme: Theme,
  labels: string[],
  series: { label: string; data: (number | null)[]; color: string; axis?: string }[],
  fmt: (v: number) => string,
  opts: { zero?: boolean; ref?: number; y2fmt?: (v: number) => string } = {},
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
  const o = options(theme, fmt, series.length > 1);
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
        borderDash: i >= theme.series.length ? [5, 3] : [],
        label: s.label,
        data: s.data,
        yAxisID: s.axis ?? 'y',
        borderColor: s.color,
        backgroundColor: s.color,
        borderWidth: 2,
        pointRadius: labels.length > 12 ? 0 : 2.5,
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

function ftrBands(rows: Row[], theme: Theme) {
  const rs = rows.filter((r) => String(r.q) <= LAST_QUARTER);
  const c = theme.series[0];
  const col = (k: string) => rs.map((r) => r[k] as number);
  const band = (label: string, data: number[], bg: string | undefined, fillTo: string | false): ChartDataset<'line'> =>
    ({ label, data, borderWidth: 0, pointRadius: 0, pointHoverRadius: 0, backgroundColor: bg ?? c, borderColor: c, fill: fillTo, tension: 0 });
  const fmt = FMT.h;
  const o = options(theme, fmt, false);
  o.plugins.tooltip.callbacks.label = (i: TooltipItem<'line'>) => `${i.dataset.label}: ${fmt(i.parsed.y ?? 0)}`;
  charts.push(new Chart($<HTMLCanvasElement>('#c-ftr'), {
    type: 'line',
    data: {
      labels: rs.map((r) => qLabel(String(r.q))),
      datasets: [
        band('90th percentile', col('ftr_p90'), faint(c, '22'), '+2'),
        band('75th percentile', col('ftr_p75'), faint(c, '44'), '+1'),
        band('25th percentile', col('ftr_p25'), undefined, false),
        { label: 'Median', data: col('ftr_p50'), borderColor: c, backgroundColor: c, borderWidth: 2, pointRadius: 2.5,
          pointHoverRadius: 4, tension: 0, fill: false },
      ],
    },
    options: { ...o, scales: axes(theme, (v) => `${num(0)(v)} h`, { zero: true }) },
  }));
}

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

const ALWAYS_MECHANICAL = new Set(['100-199', '200-499', '500+']);

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

// ---- the page

function render(data: BalanceData) {
  fillFigures(data);
  const d = data.datasets;
  const theme = readTheme();
  for (const c of charts) c.destroy();
  charts = [];

  quarters('c-velocity', d.exchange, theme, [{ field: 'cls_per_author', label: 'CLs per author' }], FMT.n1);
  quarters('c-size', d.exchange, theme, [{ field: 'median_lines', label: 'Median lines' }], FMT.n0);
  quarters('c-load', d.exchange, theme, [{ field: 'load_index', label: 'Load index' }], FMT.n2, { ref: 1 });
  const longrun = d.git_quarters.filter((r) => String(r.q) <= LAST_QUARTER);
  line('c-longrun', theme, longrun.map((r) => qLabel(String(r.q))), [
    { label: 'Commits per author per month', data: longrun.map((r) => r.per_author_month as number), color: theme.series[0] },
    { label: 'Median lines (right axis)', data: longrun.map((r) => r.median_lines as number), color: theme.series[1], axis: 'y2' },
  ], FMT.n1, { zero: true, y2fmt: FMT.n0 });

  quarters('c-perreviewer', d.reviewer_quarters, theme, [{ field: 'cls_per_reviewer', label: 'CLs per reviewer' }], FMT.n1, { zero: true });
  quarters('c-top10', d.git_quarters, theme, [{ field: 'top10_share', label: 'Busiest tenth' }], FMT.pct);

  ftrBands(d.exchange, theme);
  quarters('c-waits', d.exchange, theme, [
    { field: 'reviewer_wait_wd_p50', label: 'Reviewer, weekdays' }, { field: 'owner_wait_p50', label: 'Author' },
  ], FMT.h, { zero: true });

  quarters('c-interdiff', d.exchange, theme, [{ field: 'interdiff_share', label: 'Changed after review' }], FMT.pct, { zero: true });
  quarters('c-reverted', d.exchange, theme, [{ field: 'reverted', label: 'Reverted within 30 days' }], FMT.pct1, { zero: true });

  table('t-areas', d.areas, [
    ['area', text], ['y24_cls', FMT.n0], ['now_cls', FMT.n0], ['y24_median_lines', FMT.n0], ['now_median_lines', FMT.n0],
    ['y24_threads_per_100', FMT.n1], ['now_threads_per_100', FMT.n1], ['y24_load_index', FMT.n2], ['now_load_index', FMT.n2],
    ['y24_ftr_p50', FMT.n1], ['now_ftr_p50', FMT.n1, (r) => waitChange(r.y24_ftr_p50 as number | null, r.now_ftr_p50 as number | null)],
    ['y24_newcomer_share', FMT.pct1], ['now_newcomer_share', FMT.pct1],
  ]);

  const eras: [string, string][] = [['2023H2-2024', '2023 H2–2024'], ['2025', '2025'], ['2026 (to Sep)', '2026 to September']];
  const tenureXl: Record<string, string> = { '0-3': '0–3 mo', '3-6': '3–6', '6-12': '6–12', '12-24': '1–2 y', '24-60': '2–5 y', '60-120': '5–10 y', '120-999': '10 y+' };
  categories('c-tenure', d.learning, theme, { x: 'bucket', g: 'era', v: 'load_index', groups: eras,
    xs: Object.keys(tenureXl), xl: (x) => tenureXl[x] }, FMT.n2, { ref: 1 });
  const famXl: Record<string, string> = { 'fam 0': 'None', 'fam 1-4': '1–4', 'fam 5-19': '5–19', 'fam 20-99': '20–99', 'fam 100+': '100+' };
  categories('c-fam', d.learning, theme, { x: 'bucket', g: 'era', v: 'load_index', groups: eras,
    xs: Object.keys(famXl), xl: (x) => famXl[x] }, FMT.n2, { ref: 1 });

  const cohorts: [string, string][] = [['joined 2023', 'Joined 2023'], ['joined 2024', 'Joined 2024'], ['joined 2025', 'Joined 2025']];
  const months = ['0-3', '3-6', '6-9', '9-12', '12-18', '18-24', '24-36'];
  const monthXl = (x: string | number) => `${String(x).replace('-', '–')} mo`;
  categories('c-co-load', d.cohort_curves, theme, { x: 'months', g: 'cohort', v: 'load_index', groups: cohorts, xs: months, xl: monthXl }, FMT.n2, { ref: 1 });
  categories('c-co-vel', d.cohort_curves, theme, { x: 'months', g: 'cohort', v: 'cls_per_person_month', groups: cohorts, xs: months, xl: monthXl }, FMT.n1, { zero: true });
  categories('c-co-rev', d.cohort_curves, theme, { x: 'months', g: 'cohort', v: 'reviews_per_person_month', groups: cohorts, xs: months, xl: monthXl }, FMT.n1, { zero: true });
  const years = [2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025];
  categories('c-gitco', d.git_cohorts, theme, { x: 'year', g: 'cohort', v: 'review_share',
    groups: years.map((y) => [y, `Joined ${y}`]), xs: [1, 2, 3, 4, 5, 6, 7, 8, 9], xl: (x) => `Year ${x}` }, FMT.pct, { zero: true });
  table('t-tenure', d.reviewers_by_tenure, [
    ['half', text], ['band', text], ['reviews', FMT.n0], ['resp_p50', FMT.n1], ['resp_p75', FMT.n1],
    ['threads_per_review', FMT.n2], ['addressed_per_review', FMT.n2], ['newcomer_share', FMT.pct],
  ]);

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

  table('t-ai', d.ai_paired, [['metric', text], ['diff', signed], ['lo', signed], ['hi', signed], ['n', FMT.n0]]);

  mechanicalBars(d.mechanical_files, theme);
  table('t-mech', d.mechanical_repetition, [
    ['repetition', text], ['cls', FMT.n0], ['with_thread', FMT.pct], ['threads_per_file', FMT.n3], ['median_files', FMT.n0],
  ]);
}

async function main() {
  const main = $('main');
  try {
    const r = await fetch(balanceUrl);
    if (!r.ok) throw new Error(`${balanceUrl}: ${r.status}`);
    const data = (await r.json()) as BalanceData;
    render(data);
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
