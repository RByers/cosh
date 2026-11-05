import {
  BarController,
  BarElement,
  CategoryScale,
  Chart,
  Legend,
  LinearScale,
  LogarithmicScale,
  LineController,
  LineElement,
  PointElement,
  Tooltip,
  type Plugin,
  type Scale,
  type Tick,
} from 'chart.js';
import type { RadarWeekly, RatioPoint } from './data.ts';
import { browserShare, monthTicks, OTHER, weekTitle } from './data.ts';
import { formatRatio } from './scale.ts';

Chart.register(
  BarController,
  BarElement,
  LineController,
  LineElement,
  PointElement,
  LinearScale,
  LogarithmicScale,
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

/** X axis for a weekly series: categories stay ISO weeks (tooltips name the
 * week), but ticks sit on month starts, labelled "Nov 2025", "Dec", …, and are
 * thinned to fit the axis width. */
function weekAxis(theme: Theme, weeks: string[], offset = false) {
  return {
    offset,
    grid: { display: false },
    border: { color: theme.baseline },
    afterBuildTicks: (axis: Scale) => {
      // ~64px per "Mmm yyyy" label; the width is known here on a horizontal axis.
      const maxTicks = Math.max(2, Math.floor((axis.width || 600) / 64));
      axis.ticks = monthTicks(weeks, maxTicks).map((t) => ({ value: t.index, label: t.label }));
    },
    ticks: {
      color: theme.muted,
      maxRotation: 0,
      autoSkip: false,
      // Chart.js would label a category tick with its week; keep the month
      // label set above (it's still on the tick when this runs).
      callback: (_v: unknown, i: number, ticks: Tick[]) => ticks[i]?.label ?? '',
    },
  };
}

/** Tooltip title: the week and its dates. */
const weekTooltipTitle = (items: { label: string }[]) => (items.length ? weekTitle(items[0].label) : '');

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

export function renderRatioChart(
  canvas: HTMLCanvasElement,
  weeks: string[],
  orgs: string[],
  colors: Map<string, string>,
  points: RatioPoint[],
  theme: Theme,
  /** Running-average window in weeks (1 = none); named in the tooltip. */
  smoothing = 1,
): Chart<'line', RatioDatum[]> {
  const avg = smoothing > 1 ? `, ${smoothing}-week avg` : '';
  const datasets = orgs.map((org) => {
    const data: RatioDatum[] = weeks.map((week) => {
      const p = points.find((q) => q.week === week && q.org === org);
      const ratio = p?.ratio ?? null;
      return {
        x: week,
        y: ratio,
        ratio,
        contribution: p?.contribution ?? 0,
        derived: p?.derived ?? null,
      };
    });
    const ds = lineDataset(org, colors.get(org)!, theme, data);
    // Lines without dots, smoothed or not. A week between two gaps keeps a
    // small dot, since it would otherwise draw nothing.
    const pointRadius = data.map((p, i) =>
      p.y !== null && data[i - 1]?.y == null && data[i + 1]?.y == null ? 2 : 0,
    );
    const lineOnly = { ...ds, pointRadius, pointHoverRadius: 4 };
    if (smoothing <= 1) return lineOnly;
    // A running average is a trend, not weekly measurements: draw it as a
    // smooth curve. Monotone interpolation can't overshoot a point, so the
    // curve never dips below 0 or invents peaks.
    return { ...lineOnly, cubicInterpolationMode: 'monotone' as const };
  }).filter((d) => d.data.some((p) => p.ratio !== null));
  const isParity = (v: number) => Math.abs(v - 1) < 1e-9;
  const base = baseOptions(theme);

  return new Chart<'line', RatioDatum[]>(canvas, {
    type: 'line',
    data: { labels: weeks, datasets },
    options: {
      ...base,
      plugins: {
        ...base.plugins,
        tooltip: {
          ...base.plugins.tooltip,
          callbacks: {
            title: weekTooltipTitle,
            label: (ctx) => {
              const d = ctx.raw as RatioDatum;
              if (d.ratio === null) return `${ctx.dataset.label}: no ratio`;
              return `${formatRatio(d.ratio)}  ${ctx.dataset.label}  (${pct(d.contribution)} of review ÷ ${pct(d.derived ?? 0)} of usage${avg})`;
            },
          },
        },
      },
      scales: {
        x: weekAxis(theme, weeks, true),
        y: {
          type: 'linear',
          // Linear from 0; always reach a little past parity so the 1.0 line
          // shows even when every ratio is below it.
          min: 0,
          suggestedMax: 1.1,
          title: { display: true, text: 'value ratio', color: theme.muted },
          border: { display: false },
          afterBuildTicks: (axis) => {
            // Coarse steps (e.g. 0, 2, 4) can skip 1; add it so parity
            // always gets its highlighted gridline.
            if (!axis.ticks.some((t) => isParity(t.value))) {
              axis.ticks.push({ value: 1 });
              axis.ticks.sort((x, y) => x.value - y.value);
            }
          },
          ticks: {
            color: (ctx) => (isParity(ctx.tick?.value ?? NaN) ? theme.parity : theme.muted),
            font: (ctx) => ({ weight: isParity(ctx.tick?.value ?? NaN) ? 'bold' : 'normal' }),
            callback: (v) => `${formatRatio(Number(v))}×`,
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

/** Review chart y axis: log with every org, or linear without google.com. */
export type ReviewScale = 'log' | 'linear';

/** Weekly review counts per org: top orgs plus "Other", one line each. On the
 * default log axis (Google is ~97% of review, so a linear axis with Google
 * flattens everyone else) weeks with no review are gaps, since log(0) has no
 * position; on the linear axis (meant for the series without Google) they
 * sit at zero. */
export function renderReviewChart(
  canvas: HTMLCanvasElement,
  weeks: string[],
  series: { org: string; values: number[] }[],
  metricLabel: string,
  colors: Map<string, string>,
  theme: Theme,
  /** Running-average window in weeks (1 = none); named in the tooltip. */
  smoothing = 1,
  scale: ReviewScale = 'log',
): Chart<'line'> {
  const log = scale === 'log';
  const fmt = (v: number) => v.toLocaleString('en-US', { maximumFractionDigits: v < 10 ? 1 : 0 });
  const avg = smoothing > 1 ? `  (${smoothing}-week avg)` : '';
  const datasets = series.map((s) => {
    const color = s.org === OTHER ? theme.muted : colors.get(s.org) ?? theme.muted;
    const data = s.values.map((v) => (v > 0 || !log ? v : null));
    // Points on short ranges; on long ones only for weeks between two gaps,
    // which would otherwise draw nothing.
    const short = weeks.length <= 13;
    const pointRadius = data.map((v, i) =>
      short ? 3 : v !== null && data[i - 1] == null && data[i + 1] == null ? 2 : 0,
    );
    return { ...lineDataset(s.org, color, theme, data), pointRadius, pointHoverRadius: 4 };
  });
  const base = baseOptions(theme);
  return new Chart(canvas, {
    type: 'line',
    data: { labels: weeks, datasets },
    options: {
      ...base,
      plugins: {
        ...base.plugins,
        tooltip: {
          ...base.plugins.tooltip,
          itemSort: (a, b) => ((b.raw as number | null) ?? 0) - ((a.raw as number | null) ?? 0),
          callbacks: {
            title: weekTooltipTitle,
            label: (ctx) => `${ctx.raw === null ? 0 : fmt(ctx.raw as number)}  ${ctx.dataset.label}${avg}`,
          },
        },
      },
      scales: {
        x: weekAxis(theme, weeks),
        y: log
          ? {
              type: 'logarithmic',
              title: { display: true, text: `${metricLabel.toLowerCase()} per week (log scale)`, color: theme.muted },
              border: { display: false },
              grid: { color: theme.grid },
              afterBuildTicks: (axis) => {
                // Powers of ten only; Chart.js's default log ticks crowd the axis.
                axis.ticks = axis.ticks.filter((t) => Math.abs(Math.log10(t.value) % 1) < 1e-9);
              },
              ticks: { color: theme.muted, callback: (v) => fmt(Number(v)) },
            }
          : {
              type: 'linear',
              beginAtZero: true,
              title: { display: true, text: `${metricLabel.toLowerCase()} per week`, color: theme.muted },
              border: { display: false },
              grid: { color: theme.grid },
              ticks: { color: theme.muted, callback: (v) => fmt(Number(v)) },
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

/** Radar share of Chromium browser usage per browser over the given
 * complete weeks. */
export function renderUsageChart(
  canvas: HTMLCanvasElement,
  radar: RadarWeekly,
  weeks: string[],
  browsers: string[],
  marker: { week: string; text: string } | null,
  theme: Theme,
): Chart<'line'> {
  const series = [...browsers, OTHER];
  const datasets = series.map((b, i) => {
    const color = b === OTHER ? theme.muted : theme.series[i];
    const data = weeks.map((w) => browserShare(radar, w, b, browsers));
    // Points only on short ranges, where a single week would otherwise be invisible.
    const pointRadius = weeks.length <= 13 ? 3 : 0;
    return { ...lineDataset(b, color, theme, data), pointRadius, pointHoverRadius: 4 };
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
          callbacks: { title: weekTooltipTitle, label: (ctx) => `${pct(ctx.raw as number)}  ${ctx.dataset.label}` },
        },
      },
      scales: {
        x: weekAxis(theme, weeks),
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

/** One reviewer's weekly review comments, with their addressed comments in
 * front (null, so no bar, for weeks not classified). */
export function renderReviewerChart(
  canvas: HTMLCanvasElement,
  weeks: string[],
  comments: number[],
  addressed: (number | null)[],
  color: string,
  theme: Theme,
): Chart<'bar'> {
  const base = baseOptions(theme);
  return new Chart(canvas, {
    type: 'bar',
    data: {
      labels: weeks,
      datasets: [
        { label: 'Addressed comments', data: addressed, backgroundColor: color, borderWidth: 0, order: 0 },
        { label: 'Review comments', data: comments, backgroundColor: theme.grid, borderColor: theme.muted,
          borderWidth: 1, order: 1 },
      ],
    },
    options: {
      ...base,
      plugins: {
        ...base.plugins,
        legend: { ...base.plugins.legend, labels: { ...base.plugins.legend.labels, boxHeight: 10 } },
        tooltip: {
          ...base.plugins.tooltip,
          callbacks: {
            title: weekTooltipTitle,
            label: (ctx) => (ctx.raw === null ? `${ctx.dataset.label}: not classified` : `${ctx.raw}  ${ctx.dataset.label}`),
          },
        },
      },
      scales: {
        // Both series share each week's slot, the addressed bar in front.
        x: { ...weekAxis(theme, weeks, true), stacked: true },
        y: {
          stacked: false,
          min: 0,
          title: { display: true, text: 'comments per week', color: theme.muted },
          border: { display: false },
          grid: { color: theme.grid },
          ticks: { color: theme.muted, precision: 0 },
        },
      },
    },
  });
}

export { Chart };
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type AnyChart = Chart<any, any, any>;

