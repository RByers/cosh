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
  ScatterController,
  Tooltip,
  type Plugin,
  type Scale,
  type Tick,
} from 'chart.js';
import type { OrgSpread, RadarWeekly, RatioPoint } from './data.ts';
import { browserShare, monthTicks, OTHER, weekTitle } from './data.ts';
import { formatRatio } from './scale.ts';

Chart.register(
  BarController,
  BarElement,
  LineController,
  LineElement,
  PointElement,
  ScatterController,
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

function lineDataset<T>(label: string, color: string, data: T[]) {
  return {
    label,
    data,
    borderColor: color,
    backgroundColor: color,
    borderWidth: 2,
    // Lines only, never dots: not on short ranges, isolated weeks or hover.
    pointRadius: 0,
    pointHoverRadius: 0,
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
    const lineOnly = lineDataset(org, colors.get(org)!, data);
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

/** Weekly review counts per org: top orgs plus "Other", one line each. Weeks
 * with no review are 0, drawn as such and averaged in when smoothing, so
 * lines never break. On the default log axis (Google is ~97% of review, so a
 * linear axis with Google flattens everyone else) log(0) has no position, so
 * the axis starts one power of ten below the smallest positive value and that
 * bottom tick, labelled 0, is where zeros are plotted (their tooltips still
 * say 0). The linear axis (meant for the series without Google)
 * starts at 0. */
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
  const logFloor = logAxisFloor(series.flatMap((s) => s.values));
  const datasets = series.map((s) => {
    const color = s.org === OTHER ? theme.muted : colors.get(s.org) ?? theme.muted;
    // Chart.js's log scale skips zeros, so they're plotted at the floor.
    const data = log ? s.values.map((v) => (v > 0 ? v : logFloor)) : s.values;
    // `counts`: the true values, for the tooltip.
    return { ...lineDataset(s.org, color, data), counts: s.values };
  });
  const count = (item: { datasetIndex: number; dataIndex: number }) => datasets[item.datasetIndex].counts[item.dataIndex];
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
          itemSort: (a, b) => count(b) - count(a),
          callbacks: {
            title: weekTooltipTitle,
            label: (ctx) => `${fmt(count(ctx))}  ${ctx.dataset.label}${avg}`,
          },
        },
      },
      scales: {
        x: weekAxis(theme, weeks),
        y: log
          ? {
              type: 'logarithmic',
              min: logFloor,
              title: { display: true, text: `${metricLabel.toLowerCase()} per week (log scale)`, color: theme.muted },
              border: { display: false },
              grid: { color: theme.grid },
              afterBuildTicks: (axis) => {
                // Powers of ten only; Chart.js's default log ticks crowd the axis.
                axis.ticks = axis.ticks.filter((t) => Math.abs(Math.log10(t.value) % 1) < 1e-9);
              },
              ticks: { color: theme.muted, callback: (v) => (Number(v) <= logFloor ? '0' : fmt(Number(v))) },
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

/** The bottom of a log axis showing `values`, where their zeros are drawn:
 * the largest power of ten below the smallest positive value (1 if none), so
 * no positive value shares the zero line. */
export function logAxisFloor(values: readonly number[]): number {
  const min = Math.min(...values.filter((v) => v > 0));
  return Number.isFinite(min) ? 10 ** (Math.ceil(Math.log10(min) - 1e-9) - 1) : 1;
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
    return lineDataset(b, color, data);
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

/** `#rrggbb` with an alpha; other colour formats are returned unchanged. */
function withAlpha(color: string, alpha: number): string {
  const m = /^#([0-9a-f]{6})$/i.exec(color.trim());
  if (!m) return color;
  const n = parseInt(m[1], 16);
  return `rgba(${n >> 16}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
}

/** A stable offset in [-1, 1) for an account id, so dots keep their place. */
function jitter(id: number): number {
  return ((Math.imul(id, 2654435761) >>> 0) / 2 ** 32) * 2 - 1;
}

/** Rows with fewer reviewers than this get no box: their dots say it all. */
export const SPREAD_BOX_MIN = 5;

/** Strip plot of reviewers by their total for the metric over the range: one
 * row per org, one dot per reviewer on a log axis (0 gets its own slot at
 * the left), with a box over the middle half of the row and a line at its
 * median. Hovering a dot gives the reviewer's email; clicking it calls `onPick`. */
export function renderSpreadChart(
  canvas: HTMLCanvasElement,
  spreads: OrgSpread[],
  colorOf: (org: string) => string,
  /** How the tooltip names a reviewer (their email). */
  handleOf: (id: number) => string,
  metricLabel: string,
  theme: Theme,
  selected: number | null,
  onPick: (id: number) => void,
): Chart<'scatter'> {
  const unit = metricLabel.toLowerCase();
  const fmt = (v: number) => v.toLocaleString('en-US', { maximumFractionDigits: 1 });
  const zeros = spreads.some((s) => s.reviewers.some((r) => r.value <= 0));
  const max = Math.max(1, ...spreads.flatMap((s) => s.reviewers.map((r) => r.value)));
  const ZERO = 0.5;
  const xOf = (v: number) => (v > 0 ? v : ZERO);
  type P = { x: number; y: number; id: number; value: number };
  const datasets = spreads.map((s, row) => {
    const color = colorOf(s.org);
    const alpha = s.reviewers.length > 300 ? 0.3 : s.reviewers.length > 50 ? 0.5 : 0.8;
    const data: P[] = s.reviewers.map((r) => ({ x: xOf(r.value), y: row + 0.3 * jitter(r.id), id: r.id, value: r.value }));
    return {
      label: s.org,
      data,
      backgroundColor: withAlpha(color, alpha),
      borderColor: (ctx: { raw?: unknown }) => ((ctx.raw as P | undefined)?.id === selected ? theme.parity : 'transparent'),
      borderWidth: 2,
      pointRadius: (ctx: { raw?: unknown }) => ((ctx.raw as P | undefined)?.id === selected ? 6 : 3),
      pointHoverRadius: 6,
      pointHoverBackgroundColor: color,
      pointHoverBorderColor: theme.parity,
    };
  });

  // Box over the middle half and a median line, drawn over the dots.
  const boxes: Plugin<'scatter'> = {
    id: 'spreadBoxes',
    afterDatasetsDraw(chart) {
      const { ctx, scales } = chart;
      const x = scales.x;
      const y = scales.y;
      const half = Math.abs(y.getPixelForValue(0.42) - y.getPixelForValue(0));
      ctx.save();
      spreads.forEach((s, row) => {
        if (s.stats.n < SPREAD_BOX_MIN) return;
        const cy = y.getPixelForValue(row);
        const x1 = x.getPixelForValue(xOf(s.stats.q1));
        const x3 = x.getPixelForValue(xOf(s.stats.q3));
        const xm = x.getPixelForValue(xOf(s.stats.median));
        ctx.strokeStyle = theme.parity;
        ctx.lineWidth = 1.5;
        ctx.strokeRect(x1, cy - half, Math.max(1, x3 - x1), 2 * half);
        // A surface halo keeps the median legible over dense dots.
        for (const [color, width] of [[theme.surface, 6], [theme.parity, 3]] as const) {
          ctx.strokeStyle = color;
          ctx.lineWidth = width;
          ctx.beginPath();
          ctx.moveTo(xm, cy - half - 2);
          ctx.lineTo(xm, cy + half + 2);
          ctx.stroke();
        }
      });
      ctx.restore();
    },
  };

  const base = baseOptions(theme);
  return new Chart(canvas, {
    type: 'scatter',
    data: { datasets },
    plugins: [boxes],
    options: {
      ...base,
      interaction: { mode: 'nearest', intersect: true },
      onClick: (_e, elements) => {
        const el = elements[0];
        if (!el) return;
        onPick((datasets[el.datasetIndex].data[el.index] as P).id);
      },
      onHover: (e, elements) => {
        const target = e.native?.target as HTMLElement | undefined;
        if (target) target.style.cursor = elements.length ? 'pointer' : 'default';
      },
      plugins: {
        ...base.plugins,
        legend: { display: false },
        tooltip: {
          ...base.plugins.tooltip,
          displayColors: false,
          callbacks: {
            title: () => '',
            label: (ctx) => {
              const p = ctx.raw as P;
              return `${handleOf(p.id)}: ${fmt(p.value)} ${unit}`;
            },
            footer: () => 'Click for their weekly chart',
          },
          footerColor: theme.muted,
          footerFont: { weight: 'normal' as const },
        },
      },
      scales: {
        x: {
          type: 'logarithmic',
          min: zeros ? 0.38 : 0.7,
          max: max * 1.4,
          title: { display: true, text: `${unit} per reviewer over the range (log scale)`, color: theme.muted },
          border: { color: theme.baseline },
          grid: { color: theme.grid },
          afterBuildTicks: (axis) => {
            const ticks = zeros ? [{ value: ZERO }] : [];
            // 1, 3, 10, 30, …; powers of ten only on narrow screens.
            const threes = (axis.width || 600) >= 480;
            for (let p = 1; p <= axis.max; p *= 10) {
              ticks.push({ value: p });
              if (threes && 3 * p <= axis.max) ticks.push({ value: 3 * p });
            }
            axis.ticks = ticks;
          },
          ticks: {
            color: theme.muted,
            maxRotation: 0,
            callback: (v) => {
              const n = Number(v);
              if (n === ZERO) return '0';
              return n < 1000 ? String(n) : n.toLocaleString('en-US', { notation: 'compact' });
            },
          },
        },
        y: {
          type: 'linear',
          reverse: true,
          min: -0.5,
          max: spreads.length - 0.5,
          border: { display: false },
          grid: { display: false },
          afterBuildTicks: (axis) => {
            axis.ticks = spreads.map((_, i) => ({ value: i }));
          },
          ticks: {
            color: theme.text,
            autoSkip: false,
            callback: (v) => {
              const s = spreads[Number(v)];
              return s ? `${s.org} (${s.stats.n.toLocaleString('en-US')})` : '';
            },
          },
        },
      },
    },
  });
}

export { Chart };
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type AnyChart = Chart<any, any, any>;

