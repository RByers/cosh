import {
  BarController,
  BarElement,
  CategoryScale,
  Chart,
  Legend,
  LinearScale,
  LineController,
  LineElement,
  PointElement,
  Tooltip,
  type Plugin,
} from 'chart.js';
import type { RadarWeekly, RatioPoint } from './data.ts';
import { browserShare, OTHER } from './data.ts';
import { AXIS_MAX, AXIS_MIN, formatRatio, type PivotScale } from './scale.ts';

Chart.register(
  BarController,
  BarElement,
  LineController,
  LineElement,
  PointElement,
  LinearScale,
  CategoryScale,
  Tooltip,
  Legend,
);

export interface Theme {
  text: string;
  muted: string;
  grid: string;
  baseline: string;
  parity: string;
  surface: string;
  series: string[];
}

export function readTheme(el: Element = document.documentElement): Theme {
  const cs = getComputedStyle(el);
  const v = (name: string) => cs.getPropertyValue(name).trim();
  return {
    text: v('--text-secondary'),
    muted: v('--text-muted'),
    grid: v('--grid'),
    baseline: v('--baseline'),
    parity: v('--text-primary'),
    surface: v('--surface-1'),
    series: [1, 2, 3, 4, 5, 6, 7, 8].map((i) => v(`--series-${i}`)),
  };
}

const pct = (x: number) => `${(x * 100).toFixed(x < 0.01 ? 2 : 1)}%`;

function baseOptions(theme: Theme) {
  Chart.defaults.font.family = 'system-ui, -apple-system, "Segoe UI", sans-serif';
  Chart.defaults.color = theme.text;
  return {
    responsive: true,
    maintainAspectRatio: false,
    animation: false as const,
    interaction: { mode: 'index' as const, intersect: false },
    plugins: {
      legend: {
        position: 'top' as const,
        align: 'start' as const,
        labels: { boxWidth: 16, boxHeight: 2, color: theme.text },
      },
      tooltip: {
        backgroundColor: theme.surface,
        titleColor: theme.parity,
        bodyColor: theme.parity,
        borderColor: theme.baseline,
        borderWidth: 1,
        boxWidth: 12,
        boxHeight: 2,
        itemSort: (a: { raw: unknown }, b: { raw: unknown }) =>
          (((b.raw as { y?: number })?.y ?? -1) as number) - (((a.raw as { y?: number })?.y ?? -1) as number),
      },
    },
  };
}

function lineDataset<T>(label: string, color: string, theme: Theme, data: T[]) {
  return {
    label,
    data,
    borderColor: color,
    backgroundColor: color,
    borderWidth: 2,
    pointRadius: 4,
    pointHoverRadius: 6,
    pointBorderColor: theme.surface,
    pointBorderWidth: 2,
    spanGaps: false,
    tension: 0,
  };
}

interface RatioDatum {
  x: string;
  y: number | null;
  ratio: number | null;
  contribution: number;
  derived: number | null;
}

/** Labels the two halves of the ratio chart. */
const halvesPlugin = (theme: Theme): Plugin<'line'> => ({
  id: 'coshHalves',
  beforeDatasetsDraw(chart) {
    const { ctx, chartArea: a, scales } = chart;
    const mid = scales.y.getPixelForValue(1);
    ctx.save();
    ctx.font = '12px system-ui, -apple-system, "Segoe UI", sans-serif';
    ctx.fillStyle = theme.muted;
    ctx.textAlign = 'right';
    ctx.textBaseline = 'bottom';
    ctx.fillText('contributes more than its usage share ↑', a.right - 6, mid - 4);
    ctx.textBaseline = 'top';
    ctx.fillText('↓ contributes less than its usage share', a.right - 6, mid + 4);
    ctx.restore();
  },
});

export function renderRatioChart(
  canvas: HTMLCanvasElement,
  weeks: string[],
  orgs: string[],
  colors: Map<string, string>,
  points: RatioPoint[],
  scale: PivotScale,
  theme: Theme,
): Chart<'line', RatioDatum[]> {
  const datasets = orgs.map((org) => {
    const data: RatioDatum[] = weeks.map((week) => {
      const p = points.find((q) => q.week === week && q.org === org);
      const ratio = p?.ratio ?? null;
      return {
        x: week,
        y: ratio === null ? null : scale.toAxis(ratio),
        ratio,
        contribution: p?.contribution ?? 0,
        derived: p?.derived ?? null,
      };
    });
    return lineDataset(org, colors.get(org)!, theme, data);
  }).filter((d) => d.data.some((p) => p.ratio !== null));
  const isParity = (v: number) => Math.abs(v - 1) < 1e-9;
  const base = baseOptions(theme);

  return new Chart<'line', RatioDatum[]>(canvas, {
    type: 'line',
    data: { labels: weeks, datasets },
    plugins: [halvesPlugin(theme)],
    options: {
      ...base,
      plugins: {
        ...base.plugins,
        tooltip: {
          ...base.plugins.tooltip,
          callbacks: {
            label: (ctx) => {
              const d = ctx.raw as RatioDatum;
              if (d.ratio === null) return `${ctx.dataset.label}: no ratio`;
              return `${formatRatio(d.ratio)}  ${ctx.dataset.label}  (${pct(d.contribution)} of review ÷ ${pct(d.derived ?? 0)} of usage)`;
            },
          },
        },
      },
      scales: {
        x: {
          offset: true,
          grid: { display: false },
          border: { color: theme.baseline },
          ticks: { color: theme.muted },
        },
        y: {
          type: 'linear',
          min: AXIS_MIN,
          max: AXIS_MAX,
          title: { display: true, text: 'value ratio', color: theme.muted },
          border: { display: false },
          afterBuildTicks: (axis) => {
            axis.ticks = scale.ticks.map((r) => ({ value: scale.toAxis(r) }));
          },
          ticks: {
            color: (ctx) => (isParity(ctx.tick?.value ?? NaN) ? theme.parity : theme.muted),
            font: (ctx) => ({ weight: isParity(ctx.tick?.value ?? NaN) ? 'bold' : 'normal' }),
            callback: (v) => `${formatRatio(scale.fromAxis(Number(v)))}×`,
          },
          grid: {
            color: (ctx) => (isParity(ctx.tick?.value ?? NaN) ? theme.parity : theme.grid),
            lineWidth: (ctx) => (isParity(ctx.tick?.value ?? NaN) ? 2 : 1),
          },
        },
      },
    },
  });
}

/** Draws a value label at the end of each horizontal bar. */
const barLabelsPlugin = (theme: Theme, format: (v: number) => string, size = 12): Plugin<'bar'> => ({
  id: 'coshBarLabels',
  afterDatasetsDraw(chart) {
    const { ctx } = chart;
    const meta = chart.getDatasetMeta(0);
    const data = chart.data.datasets[0].data as number[];
    ctx.save();
    ctx.font = `${size}px system-ui, -apple-system, "Segoe UI", sans-serif`;
    ctx.fillStyle = theme.text;
    ctx.textBaseline = 'middle';
    meta.data.forEach((bar, i) => {
      ctx.fillText(format(data[i]), bar.x + 6, bar.y);
    });
    ctx.restore();
  },
});

/** Raw review counts per org for one week: top orgs plus "Other". */
export function renderReviewChart(
  canvas: HTMLCanvasElement,
  rows: { org: string; value: number }[],
  metricLabel: string,
  theme: Theme,
): Chart<'bar'> {
  const fmt = (v: number) => v.toLocaleString('en-US');
  const base = baseOptions(theme);
  return new Chart(canvas, {
    type: 'bar',
    data: {
      labels: rows.map((r) => r.org),
      datasets: [
        {
          label: metricLabel,
          data: rows.map((r) => r.value),
          backgroundColor: rows.map((r) => (r.org === OTHER ? theme.muted : theme.series[0])),
          borderRadius: { topRight: 4, bottomRight: 4 },
          borderSkipped: 'start',
          barPercentage: 0.7,
          categoryPercentage: 1,
          minBarLength: 2,
        },
      ],
    },
    plugins: [barLabelsPlugin(theme, fmt)],
    options: {
      ...base,
      indexAxis: 'y',
      interaction: { mode: 'nearest', axis: 'y', intersect: false },
      layout: { padding: { right: 64 } },
      plugins: {
        ...base.plugins,
        legend: { display: false },
        tooltip: {
          ...base.plugins.tooltip,
          itemSort: undefined,
          callbacks: { label: (ctx) => `${fmt(ctx.raw as number)} ${metricLabel.toLowerCase()}` },
        },
      },
      scales: {
        x: {
          min: 0,
          border: { display: false },
          grid: { color: theme.grid },
          ticks: { color: theme.muted, callback: (v) => fmt(Number(v)) },
        },
        y: {
          grid: { display: false },
          border: { color: theme.baseline },
          ticks: { color: theme.text },
        },
      },
    },
  });
}

/** Pixels per leaderboard row; the canvas height is rows × this plus axes. */
export const LEADERBOARD_ROW_PX = 15;

const truncate = (s: string, n: number) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);

/** Top reviewers for one week, one compact horizontal bar each. Bars take the
 * org's series colour (the same as the ratio chart and table); orgs without
 * one are drawn in the muted neutral. */
export function renderLeaderboardChart(
  canvas: HTMLCanvasElement,
  rows: { name: string; org: string; value: number }[],
  metricLabel: string,
  colors: Map<string, string>,
  theme: Theme,
): Chart<'bar'> {
  const fmt = (v: number) => v.toLocaleString('en-US');
  const base = baseOptions(theme);
  const small = { size: 11 };
  // Phones: rank and a short name only (org stays in the colour and tooltip),
  // or Chart.js clips the labels on the left.
  const narrow = (canvas.parentElement?.clientWidth ?? 1000) < 560;
  const label = (r: { name: string; org: string }, i: number) =>
    narrow ? `${i + 1}. ${truncate(r.name, 15)}` : `${i + 1}. ${truncate(r.name, 26)} · ${truncate(r.org, 22)}`;
  return new Chart(canvas, {
    type: 'bar',
    data: {
      labels: rows.map(label),
      datasets: [
        {
          label: metricLabel,
          data: rows.map((r) => r.value),
          backgroundColor: rows.map((r) => colors.get(r.org) ?? theme.muted),
          borderRadius: { topRight: 3, bottomRight: 3 },
          borderSkipped: 'start',
          barPercentage: 0.8,
          categoryPercentage: 1,
          minBarLength: 2,
        },
      ],
    },
    plugins: [barLabelsPlugin(theme, fmt, 11)],
    options: {
      ...base,
      indexAxis: 'y',
      interaction: { mode: 'nearest', axis: 'y', intersect: false },
      layout: { padding: { right: 56 } },
      plugins: {
        ...base.plugins,
        legend: { display: false },
        tooltip: {
          ...base.plugins.tooltip,
          itemSort: undefined,
          callbacks: {
            title: (items) => {
              const r = rows[items[0].dataIndex];
              return `${items[0].dataIndex + 1}. ${r.name} (${r.org})`;
            },
            label: (ctx) => `${fmt(ctx.raw as number)} ${metricLabel.toLowerCase()}`,
          },
        },
      },
      scales: {
        x: {
          min: 0,
          position: 'top',
          border: { display: false },
          grid: { color: theme.grid },
          ticks: { color: theme.muted, font: small, callback: (v) => fmt(Number(v)) },
        },
        y: {
          grid: { display: false },
          border: { color: theme.baseline },
          ticks: { color: theme.text, font: small, autoSkip: false, padding: 4 },
        },
      },
    },
  });
}

/** Vertical marker on a category week, e.g. the ChromeDerivative jump. */
const weekMarkerPlugin = (theme: Theme, week: string, text: string): Plugin<'line'> => ({
  id: 'coshWeekMarker',
  beforeDatasetsDraw(chart) {
    const idx = (chart.data.labels as string[]).indexOf(week);
    if (idx < 0) return;
    const { ctx, chartArea: a } = chart;
    const x = chart.scales.x.getPixelForValue(idx);
    ctx.save();
    ctx.strokeStyle = theme.baseline;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x, a.top);
    ctx.lineTo(x, a.bottom);
    ctx.stroke();
    ctx.font = '12px system-ui, -apple-system, "Segoe UI", sans-serif';
    ctx.fillStyle = theme.muted;
    ctx.textAlign = 'right';
    ctx.textBaseline = 'top';
    ctx.fillText(text, x - 4, a.top + 2);
    ctx.restore();
  },
});

/** Radar share of Chromium browser usage per browser, every complete week. */
export function renderUsageChart(
  canvas: HTMLCanvasElement,
  radar: RadarWeekly,
  browsers: string[],
  marker: { week: string; text: string } | null,
  theme: Theme,
): Chart<'line'> {
  const weeks = [...radar.keys()].sort();
  const series = [...browsers, OTHER];
  const datasets = series.map((b, i) => {
    const color = b === OTHER ? theme.muted : theme.series[i];
    const data = weeks.map((w) => browserShare(radar, w, b, browsers));
    return { ...lineDataset(b, color, theme, data), pointRadius: 0, pointHoverRadius: 4 };
  });
  const base = baseOptions(theme);
  return new Chart(canvas, {
    type: 'line',
    data: { labels: weeks, datasets },
    plugins: marker ? [weekMarkerPlugin(theme, marker.week, marker.text)] : [],
    options: {
      ...base,
      plugins: {
        ...base.plugins,
        tooltip: {
          ...base.plugins.tooltip,
          itemSort: (a, b) => (b.raw as number) - (a.raw as number),
          callbacks: { label: (ctx) => `${pct(ctx.raw as number)}  ${ctx.dataset.label}` },
        },
      },
      scales: {
        x: {
          grid: { display: false },
          border: { color: theme.baseline },
          ticks: { color: theme.muted, maxRotation: 0, autoSkip: true, autoSkipPadding: 24 },
        },
        y: {
          min: 0,
          title: { display: true, text: 'share of Chromium browser usage', color: theme.muted },
          border: { display: false },
          grid: { color: theme.grid },
          ticks: { color: theme.muted, callback: (v) => `${Math.round(Number(v) * 100)}%` },
        },
      },
    },
  });
}

export { Chart };
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type AnyChart = Chart<any, any, any>;

