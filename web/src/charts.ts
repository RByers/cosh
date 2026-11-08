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
  RadarController,
  RadialLinearScale,
  ScatterController,
  Filler,
  Tooltip,
  type ChartType,
  type FontSpec,
  type Plugin,
  type Scale,
  type Tick,
  type TooltipModel,
  type TooltipPositionerFunction,
} from 'chart.js';
import { fmtInt, fmtNum } from './format.ts';
import { toFont, toPadding } from 'chart.js/helpers';
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
  RadarController,
  RadialLinearScale,
  Filler,
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
  /** Org colours: ORG_BRIGHT vivid hues, then the same hues muted. */
  orgs: string[];
  /** The page's font (style.css), for every chart's text. */
  font: string;
}

/** How many vivid org colours style.css defines (--org-1..6); --org-7..12
 * are the same hues muted. */
export const ORG_BRIGHT = 6;

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
    orgs: Array.from({ length: 2 * ORG_BRIGHT }, (_, i) => v(`--org-${i + 1}`)),
    font: getComputedStyle(document.body).fontFamily,
  };
}

declare module 'chart.js' {
  interface TooltipPositionerMap {
    belowOrAbove: TooltipPositionerFunction<ChartType>;
  }
}

/** The tooltip options the fraction card reads, as Chart.js has resolved
 * them by the time a positioner or plugin hook runs (typed as scriptable). */
interface CardOptions {
  padding: Parameters<typeof toPadding>[0];
  titleFont: Partial<FontSpec>;
  bodyFont: Partial<FontSpec>;
  titleMarginBottom: number;
  bodySpacing: number;
  caretSize: number;
  caretPadding: number;
  bodyColor: string;
}
const cardOptions = (t: TooltipModel<ChartType>) => t.options as unknown as CardOptions;

/** Height of a hover card with one title line and two body lines (the
 * fraction card below). Chart.js sizes the card only after positioning it. */
function fractionCardHeight(o: CardOptions): number {
  return (
    toPadding(o.padding).height +
    toFont(o.titleFont).lineHeight +
    o.titleMarginBottom +
    2 * toFont(o.bodyFont).lineHeight +
    o.bodySpacing
  );
}

/** Below the hovered point, or above it when the card would run off the
 * bottom of the canvas (Chart.js would otherwise push it up over the point). */
Tooltip.positioners.belowOrAbove = function (items, eventPosition) {
  const p = Tooltip.positioners.average.call(this, items, eventPosition);
  if (!p || p.y === null) return false;
  const o = cardOptions(this);
  const gap = o.caretSize + o.caretPadding;
  return { ...p, yAlign: p.y + gap + fractionCardHeight(o) <= this.chart.height ? 'top' : 'bottom' };
};

/** Draws the rule between a fraction card's two body lines, numerator over
 * denominator, as wide as the wider of them. */
const fractionRule: Plugin = {
  id: 'fractionRule',
  afterTooltipDraw(chart, { tooltip: t }) {
    const lines = t.body?.[0]?.lines ?? [];
    if (!t.opacity || t.body.length !== 1 || lines.length !== 2) return;
    const o = cardOptions(t);
    const bodyFont = toFont(o.bodyFont);
    const y =
      t.y +
      toPadding(o.padding).top +
      toFont(o.titleFont).lineHeight +
      o.titleMarginBottom +
      bodyFont.lineHeight +
      o.bodySpacing / 2;
    const { ctx } = chart;
    ctx.save();
    ctx.font = bodyFont.string;
    const w = Math.max(...lines.map((l) => ctx.measureText(l).width));
    const cx = t.x + t.width / 2;
    ctx.globalAlpha = t.opacity;
    ctx.strokeStyle = o.bodyColor;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(cx - w / 2, Math.round(y) + 0.5);
    ctx.lineTo(cx + w / 2, Math.round(y) + 0.5);
    ctx.stroke();
    ctx.restore();
  },
};

const pct = (x: number) => `${(x * 100).toFixed(x < 0.01 ? 2 : 1)}%`;

function baseOptions(theme: Theme) {
  Chart.defaults.font.family = theme.font;
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
        // Always beside the hovered week, never above or below it. Chart.js
        // otherwise picks top/bottom when the points' mean y is near an edge
        // (as on the usage chart, where most shares are small), centring the
        // card over the lines. It still keeps the card inside the canvas.
        yAlign: 'center' as const,
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

/** A datum's plotted value: the number itself, or an object's `y`. */
const yOf = (d: unknown) => (d !== null && typeof d === 'object' ? (d as { y?: number | null }).y ?? null : d ?? null);

export function lineDataset<T>(label: string, color: string, data: T[]) {
  // Lines without dots, except a week with gaps on both sides (it would
  // otherwise draw nothing) and the hovered week.
  const pointRadius = data.map((d, i) =>
    yOf(d) !== null && yOf(data[i - 1]) === null && yOf(data[i + 1]) === null ? 2 : 0,
  );
  return {
    label,
    data,
    borderColor: color,
    backgroundColor: color,
    borderWidth: 2,
    pointRadius,
    pointHoverRadius: 4,
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
  /** Running-average window in weeks (1 = none); smooths the curves. */
  smoothing = 1,
): Chart<'line', RatioDatum[]> {
  const byKey = new Map<string, RatioPoint>();
  for (const q of points) if (!byKey.has(`${q.org}|${q.week}`)) byKey.set(`${q.org}|${q.week}`, q);
  const datasets = orgs.map((org) => {
    const data: RatioDatum[] = weeks.map((week) => {
      const p = byKey.get(`${org}|${week}`);
      const ratio = p?.ratio ?? null;
      return {
        x: week,
        y: ratio,
        ratio,
        contribution: p?.contribution ?? 0,
        derived: p?.derived ?? null,
      };
    });
    const lineOnly = lineDataset(org, colors.get(org) ?? theme.muted, data);
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
              return `${formatRatio(d.ratio)}  ${ctx.dataset.label}  (${pct(d.contribution)} of review ÷ ${pct(d.derived ?? 0)} of usage)`;
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
            font: (ctx) => ({
              size: ctx.chart.width < 520 ? 10 : 12,
              weight: isParity(ctx.tick?.value ?? NaN) ? 'bold' : 'normal',
            }),
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

/** One org's range totals for the parity chart. */
export interface ParityPoint {
  org: string;
  /** Share of the chosen review metric over the range. */
  contribution: number;
  /** Mean weekly share of Chromium browser usage over the range. */
  derived: number;
}

/** Log-axis tick label as a percentage: 0.001 → "0.1%", 0.5 → "50%". */
export function formatShare(v: number): string {
  return `${fmtNum(v * 100, { maximumSignificantDigits: 2 })}%`;
}

/** Shared bounds for both log axes: whole decades around every value, so the
 * y = x parity line runs corner to corner. */
export function parityBounds(points: ParityPoint[]): { min: number; max: number } {
  const vals = points.flatMap((p) => [p.contribution, p.derived]).filter((v) => v > 0);
  if (!vals.length) return { min: 0.001, max: 1 };
  const min = 10 ** Math.floor(Math.log10(Math.min(...vals)) + 1e-9);
  const max = Math.min(1, 10 ** Math.ceil(Math.log10(Math.max(...vals)) - 1e-9));
  return { min, max: max > min ? max : min * 10 };
}

/** Contribution share against usage share over the range, one point per org, both
 * on log axes with the same bounds. The diagonal y = x is a 1.0× value ratio:
 * orgs above it review more than their usage share, those below less. Orgs
 * with no review in the range have no place on a log scale, so, as on the
 * review chart, the axes then start one power of ten lower and that bottom
 * tick, labelled 0 on the y axis, is where they sit (their tooltips say 0). */
export function renderParityChart(
  canvas: HTMLCanvasElement,
  points: ParityPoint[],
  metricLabel: string,
  colors: Map<string, string>,
  theme: Theme,
): Chart<'scatter'> {
  const { min, max } = parityBounds(points);
  // Both axes extend alike, so the diagonal stays at 45°.
  const zero = points.some((p) => p.contribution <= 0) ? min / 10 : null;
  const lo = zero ?? min;
  const datasets = points.map((p) => ({
    label: p.org,
    data: [{ x: p.derived, y: p.contribution > 0 ? p.contribution : lo, share: p.contribution }],
    backgroundColor: colors.get(p.org) ?? theme.muted,
    borderColor: theme.surface,
    borderWidth: 2,
    pointRadius: 7,
    pointHoverRadius: 9,
    // An org near 100% sits on the edge; draw its whole dot.
    clip: false as const,
  }));
  const plugin: Plugin<'scatter'> = {
    id: 'parityLine',
    // The parity diagonal, under the points.
    beforeDatasetsDraw(chart) {
      const { ctx, chartArea: a, scales } = chart;
      const x = scales.x;
      const y = scales.y;
      ctx.save();
      ctx.beginPath();
      ctx.rect(a.left, a.top, a.right - a.left, a.bottom - a.top);
      ctx.clip();
      ctx.strokeStyle = theme.parity;
      ctx.lineWidth = 2;
      // Corner to corner, through the 0 row's extra decade too when there is one.
      ctx.beginPath();
      ctx.moveTo(x.getPixelForValue(lo), y.getPixelForValue(lo));
      ctx.lineTo(x.getPixelForValue(max), y.getPixelForValue(max));
      ctx.stroke();
      // Its label runs along the line, above it near the low end: high review
      // on tiny usage, a corner no org is near.
      const x0 = x.getPixelForValue(lo);
      const y0 = y.getPixelForValue(lo);
      const angle = Math.atan2(y.getPixelForValue(max) - y0, x.getPixelForValue(max) - x0);
      ctx.translate(x0, y0);
      ctx.rotate(angle);
      ctx.fillStyle = theme.parity;
      ctx.font = `bold 12px ${Chart.defaults.font.family}`;
      ctx.textAlign = 'left';
      ctx.textBaseline = 'bottom';
      ctx.fillText('1.0× value ratio (parity)', 24, -4);
      ctx.restore();
    },
    // Org names beside their points, so the chart reads without the legend.
    // Each takes the first of right, left, above or below that stays in the
    // chart and clear of the dots and the labels placed so far (orgs on the
    // 0 row can sit close together).
    afterDatasetsDraw(chart) {
      const { ctx, chartArea: a } = chart;
      ctx.save();
      ctx.font = `12px ${Chart.defaults.font.family}`;
      ctx.fillStyle = theme.text;
      ctx.textBaseline = 'middle';
      ctx.textAlign = 'left';
      type Box = { l: number; r: number; t: number; b: number };
      const hit = (p: Box, q: Box) => p.l < q.r && q.l < p.r && p.t < q.b && q.t < p.b;
      const pts = chart.data.datasets.map((_, i) => chart.getDatasetMeta(i)).filter((m) => !m.hidden && m.data[0]);
      const dots: Box[] = pts.map((m) => {
        const { x, y } = m.data[0];
        return { l: x - 8, r: x + 8, t: y - 8, b: y + 8 };
      });
      const placed: Box[] = [];
      pts.forEach((m, i) => {
        const { x, y } = m.data[0];
        const label = chart.data.datasets[m.index].label ?? '';
        const w = ctx.measureText(label).width;
        const h = 14;
        const at = (l: number, cy: number): Box => ({ l, r: l + w, t: cy - h / 2, b: cy + h / 2 });
        const options = [at(x + 12, y), at(x - 12 - w, y), at(x - w / 2, y - 16), at(x - w / 2, y + 16)];
        const fits = (o: Box) => o.l >= a.left && o.r <= a.right + 8 && o.t >= a.top - 8 && o.b <= a.bottom + 8;
        const clear = (o: Box) =>
          fits(o) && !placed.some((p) => hit(o, p)) && !dots.some((d, j) => j !== i && hit(o, d));
        const box = options.find(clear) ?? options.find(fits) ?? options[0];
        placed.push(box);
        ctx.fillText(label, box.l, (box.t + box.b) / 2);
      });
      ctx.restore();
    },
  };
  // Ticks, labels and gridlines on whole decades only: 0.01%, 0.1%, 1%, …
  const decades: number[] = [];
  for (let e = Math.round(Math.log10(lo)); e <= Math.round(Math.log10(max)); e++) decades.push(10 ** e);
  const isZeroTick = (v: number) => zero !== null && Math.abs(v / zero - 1) < 1e-6;
  const axis = (title: string, zeroLabel: boolean) => ({
    type: 'logarithmic' as const,
    min: lo,
    max,
    title: { display: true, text: title, color: theme.muted },
    border: { color: theme.baseline },
    grid: { color: theme.grid },
    afterBuildTicks: (scale: Scale) => {
      scale.ticks = decades.map((value) => ({ value }));
    },
    ticks: {
      color: theme.muted,
      autoSkip: false,
      maxRotation: 0,
      callback: (v: number | string) => (zeroLabel && isZeroTick(Number(v)) ? '0' : formatShare(Number(v))),
    },
  });
  const base = baseOptions(theme);
  return new Chart<'scatter'>(canvas, {
    type: 'scatter',
    data: { datasets },
    plugins: [plugin, fractionRule],
    options: {
      ...base,
      interaction: { mode: 'nearest', intersect: true },
      plugins: {
        ...base.plugins,
        // Each point is labelled with its org instead.
        legend: { display: false },
        // Three lines below the point (above near the bottom), clear of its
        // neighbours: the org and its ratio, then the ratio as a fraction,
        // review share over usage share with a rule between them.
        tooltip: {
          ...base.plugins.tooltip,
          position: 'belowOrAbove',
          yAlign: undefined,
          // Clear of the hovered dot (radius 9).
          caretPadding: 8,
          titleAlign: 'center',
          bodyAlign: 'center',
          displayColors: false,
          titleMarginBottom: 6,
          bodySpacing: 7,
          callbacks: {
            title: (items) => {
              const it = items[0];
              if (!it) return '';
              const p = it.raw as { x: number; share: number };
              return `${it.dataset.label}  ${formatRatio(p.share / p.x)}×`;
            },
            label: (ctx) => {
              const p = ctx.raw as { x: number; share: number };
              return [`${pct(p.share)} of ${metricLabel}`, `${pct(p.x)} of usage`];
            },
          },
        },
      },
      scales: {
        x: axis('share of Chromium browser usage (log scale)', false),
        y: axis(`share of ${metricLabel} (log scale)`, true),
      },
    },
  });
}

/** One org's value ratio for each metric the value shape chart shows. */
export interface ShapeOrg {
  org: string;
  /** Per metric: contribution share and usage share, or null where the org
   * has no ratio (too little usage over that metric's weeks). */
  shares: ({ contribution: number; derived: number } | null)[];
}

/** A decade's ratio label: 0.001, 0.01, 0.1, 1.0, 10. */
const decadeLabel = (e: number) => (e >= 0 ? formatRatio(10 ** e) : String(10 ** e));

/** The value shape chart's radial range in decades (log10 of the ratio):
 * `center` is the whole decade at the center, `outer` the edge, a little past
 * the largest ratio and always past the 1.0× ring. A ratio of 0 (no
 * contribution) sits at the center, one decade below the smallest other
 * ratio, like the parity chart's 0 row. */
export function shapeBounds(ratios: number[]): { center: number; outer: number; zero: boolean } {
  const pos = ratios.filter((r) => r > 0);
  const zero = ratios.some((r) => r === 0);
  const lo = pos.length ? Math.min(-1, Math.floor(Math.log10(Math.min(...pos)) + 1e-9)) : -1;
  const outer = Math.max(0, pos.length ? Math.log10(Math.max(...pos)) : 0) + 0.2;
  return { center: zero ? lo - 1 : lo, outer, zero };
}

/** Every org's value ratio on every metric at once: one axis per metric, the
 * ratio on a log scale from the center out, and each org a shaded polygon
 * through its ratios. The bold ring is 1.0×, contribution in proportion to
 * usage: an org reaching outside it on an axis contributes more than its
 * usage share on that metric. `selected` is the metric picked below the chart,
 * whose axis label is bold. */
export function renderValueShapeChart(
  canvas: HTMLCanvasElement,
  orgs: ShapeOrg[],
  metricLabels: string[],
  selected: number,
  colors: Map<string, string>,
  theme: Theme,
): Chart<'radar'> {
  const ratio = (s: { contribution: number; derived: number } | null) => (s ? s.contribution / s.derived : null);
  const all = orgs.flatMap((o) => o.shares.map(ratio)).filter((r): r is number => r !== null);
  const { center, outer, zero } = shapeBounds(all);
  const r = (x: number | null) => (x === null ? null : x > 0 ? Math.log10(x) - center : 0);
  const datasets = orgs.map((o) => {
    const color = colors.get(o.org) ?? theme.muted;
    return {
      label: o.org,
      data: o.shares.map((s) => r(ratio(s))),
      shares: o.shares,
      borderColor: color,
      backgroundColor: withAlpha(color, 0.08),
      pointBackgroundColor: color,
      pointBorderColor: theme.surface,
      borderWidth: 2,
      pointRadius: 5,
      pointHoverRadius: 7,
      fill: true,
      spanGaps: true,
    };
  });
  const isParity = (v: number) => Math.abs(v + center) < 1e-6;
  const base = baseOptions(theme);
  return new Chart<'radar'>(canvas, {
    type: 'radar',
    data: { labels: metricLabels, datasets },
    options: {
      ...base,
      interaction: { mode: 'nearest', intersect: true },
      plugins: {
        ...base.plugins,
        legend: {
          ...base.plugins.legend,
          labels: { ...base.plugins.legend.labels, boxWidth: 14, boxHeight: 14 },
        },
        tooltip: {
          ...base.plugins.tooltip,
          yAlign: undefined,
          displayColors: false,
          callbacks: {
            title: (items) => {
              const it = items[0];
              if (!it) return '';
              const s = (it.dataset as unknown as { shares: ShapeOrg['shares'] }).shares[it.dataIndex];
              return `${it.dataset.label}  ${formatRatio(ratio(s) ?? 0)}×`;
            },
            label: (ctx) => {
              const s = (ctx.dataset as unknown as { shares: ShapeOrg['shares'] }).shares[ctx.dataIndex];
              const m = metricLabels[ctx.dataIndex].toLowerCase();
              return s ? [`${pct(s.contribution)} of ${m}`, `${pct(s.derived)} of usage`] : [];
            },
          },
        },
      },
      scales: {
        r: {
          min: 0,
          max: outer - center,
          angleLines: { color: theme.grid },
          // Ticks on whole decades only, not at the edge.
          afterBuildTicks: (scale: Scale) => {
            const ticks: Tick[] = [];
            for (let v = 0; v <= outer - center + 1e-9; v++) ticks.push({ value: v });
            scale.ticks = ticks;
          },
          grid: {
            // Circles, so the organizations' polygons stand out from them.
            circular: true,
            color: (ctx) => (isParity(ctx.tick?.value ?? NaN) ? theme.parity : theme.grid),
            lineWidth: (ctx) => (isParity(ctx.tick?.value ?? NaN) ? 2 : 1),
          },
          pointLabels: {
            color: theme.text,
            // One word a line on narrow screens, so the names fit beside the chart.
            callback: (label: string) => (canvas.clientWidth < 520 ? label.split(' ') : label),
            font: (ctx) => ({ size: ctx.chart.width < 520 ? 11 : 13, weight: ctx.index === selected ? 'bold' : 'normal' }),
            padding: 6,
          },
          ticks: {
            color: (ctx) => (isParity(ctx.tick?.value ?? NaN) ? theme.parity : theme.muted),
            font: (ctx) => ({ weight: isParity(ctx.tick?.value ?? NaN) ? 'bold' : 'normal' }),
            z: 1,
            backdropColor: theme.surface,
            callback: (v: number | string) => (zero && Number(v) === 0 ? '0' : `${decadeLabel(Number(v) + center)}×`),
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
  /** Null values are gaps (a ratio's weeks with nothing to divide by). */
  series: { org: string; values: (number | null)[] }[],
  /** The metric mid-sentence, e.g. "review comments". */
  unit: string,
  colors: Map<string, string>,
  theme: Theme,
  scale: ReviewScale = 'log',
  /** The values are weekly counts ("per week" on the axis), not ratios. */
  perWeek = true,
): Chart<'line'> {
  const log = scale === 'log';
  const fmt = (v: number) => fmtNum(v, { maximumFractionDigits: v < 10 ? (perWeek ? 1 : 2) : 0 });
  const logFloor = logAxisFloor(series.flatMap((s) => s.values.filter((v): v is number => v !== null)));
  const axisTitle = perWeek ? `${unit} per week` : unit;
  const datasets = series.map((s) => {
    const own = s.org === OTHER ? undefined : colors.get(s.org);
    // Chart.js's log scale skips zeros, so they're plotted at the floor.
    const data = log ? s.values.map((v) => (v === null ? null : v > 0 ? v : logFloor)) : s.values;
    // `counts`: the true values, for the tooltip. A named org without a
    // colour of its own is grey like Other, but dashed, so it reads apart.
    const dash = s.org !== OTHER && !own ? { borderDash: [6, 3] } : {};
    return { ...lineDataset(s.org, own ?? theme.muted, data), ...dash, counts: s.values };
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
          itemSort: (a, b) => (count(b) ?? -1) - (count(a) ?? -1),
          filter: (item) => count(item) !== null,
          callbacks: {
            title: weekTooltipTitle,
            label: (ctx) => `${fmt(count(ctx) ?? 0)}  ${ctx.dataset.label}`,
          },
        },
      },
      scales: {
        x: weekAxis(theme, weeks),
        y: log
          ? {
              type: 'logarithmic',
              min: logFloor,
              title: { display: true, text: `${axisTitle} (log scale)`, color: theme.muted },
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
              title: { display: true, text: axisTitle, color: theme.muted },
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
    ctx.font = `12px ${theme.font}`;
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
  /** Their commits per week, drawn as a line; null if not loaded. */
  commits: number[] | null = null,
): Chart<'bar'> {
  const base = baseOptions(theme);
  const commitLine = commits && commits.some((v) => v > 0)
    ? [{ type: 'line' as const, label: 'Commits', data: commits, borderColor: theme.text, backgroundColor: theme.text,
        borderWidth: 1.5, pointRadius: 0, pointStyle: 'line' as const, order: -1 }]
    : [];
  return new Chart(canvas, {
    type: 'bar',
    data: {
      labels: weeks,
      datasets: [
        { label: 'Addressed comments', data: addressed, backgroundColor: color, borderWidth: 0, order: 0,
          pointStyle: 'rect' },
        { label: 'Review comments', data: comments, backgroundColor: theme.grid, borderColor: theme.muted,
          borderWidth: 1, order: 1, pointStyle: 'rect' },
        // A line on the bar chart; Chart.js types a mixed chart's datasets loosely.
        ...(commitLine as unknown as { label: string; data: number[] }[]),
      ],
    },
    options: {
      ...base,
      plugins: {
        ...base.plugins,
        // Point styles in the legend: a square for each bar series, a short
        // line for commits (as a box, its 1.5px outline read as a blob).
        legend: { ...base.plugins.legend, labels: { ...base.plugins.legend.labels, boxHeight: 10,
          usePointStyle: true, pointStyleWidth: 16 } },
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
          title: { display: true, text: commitLine.length ? 'per week' : 'comments per week', color: theme.muted },
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
 * median. Hovering a dot gives the reviewer's email; clicking it calls `onPick`.
 * `opts` relabels it for other per-reviewer values, such as a ratio; the log
 * axis starts just below the smallest value. `opts.linear` uses a linear axis
 * from 0 instead (0 is then an ordinary value, with no slot of its own).
 * `opts.cap`, with `linear`, ends the axis at that value: reviewers above it
 * sit in a narrow slot in the right margin, labelled ">cap", so a few
 * outliers don't squash the rest. Their tooltips still give the value. */
export function renderSpreadChart(
  canvas: HTMLCanvasElement,
  spreads: OrgSpread[],
  colorOf: (org: string) => string,
  /** How the tooltip names a reviewer (their email). */
  handleOf: (id: number) => string,
  /** The metric mid-sentence, e.g. "review comments". */
  unit: string,
  theme: Theme,
  /** The selected reviewer, read on every draw: after a pick, `chart.draw()`
   * moves the ring without rebuilding the chart. */
  selected: () => number | null,
  onPick: (id: number) => void,
  opts: { axisTitle?: string; linear?: boolean; cap?: number } = {},
): Chart<'scatter'> {
  const values = spreads.flatMap((s) => s.reviewers.map((r) => r.value));
  const zeros = values.some((v) => v <= 0);
  const max = Math.max(1, ...values);
  // The axis starts just below the smallest value above 0.
  const positive = values.filter((v) => v > 0);
  const low = positive.length ? Math.min(...positive) : 1;
  const lowExp = Math.floor(Math.log10(low));
  const axisMin = (zeros ? 0.38 : 0.7) * low;
  const fmt = (v: number) =>
    fmtNum(v, { maximumFractionDigits: v > 0 && v < 1 ? 2 : 1 });
  const ZERO = 0.5 * low;
  // The outlier slot, in the margin just past the cap (only when some value is over it).
  const cap = opts.linear && opts.cap !== undefined && max > opts.cap ? opts.cap : null;
  const OVER = cap === null ? 0 : cap * 1.07;
  const xOf = (v: number) => (cap !== null && v > cap ? OVER : v > 0 || opts.linear ? v : ZERO);
  type P = { x: number; y: number; id: number; value: number };
  const datasets = spreads.map((s, row) => {
    const color = colorOf(s.org);
    const alpha = s.reviewers.length > 300 ? 0.3 : s.reviewers.length > 50 ? 0.5 : 0.8;
    const data: P[] = s.reviewers.map((r) => ({ x: xOf(r.value), y: row + 0.3 * jitter(r.id), id: r.id, value: r.value }));
    // Static (not scriptable) point options: Chart.js then resolves them once
    // per dataset instead of once per dot, which matters with thousands of
    // dots. The selected reviewer's ring is drawn by the plugin below.
    return {
      label: s.org,
      data,
      backgroundColor: withAlpha(color, alpha),
      borderColor: 'transparent',
      borderWidth: 2,
      pointRadius: 3,
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
      // The selected reviewer: a larger dot ringed in the text colour.
      const picked = selected();
      if (picked !== null) {
        chart.data.datasets.forEach((ds, di) => {
          const i = (ds.data as P[]).findIndex((p) => p.id === picked);
          if (i < 0) return;
          const pt = chart.getDatasetMeta(di).data[i];
          if (!pt) return;
          ctx.beginPath();
          ctx.arc(pt.x, pt.y, 6, 0, 2 * Math.PI);
          ctx.fillStyle = ds.backgroundColor as string;
          ctx.fill();
          ctx.strokeStyle = theme.parity;
          ctx.lineWidth = 2;
          ctx.stroke();
        });
      }
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
        // style.css gives a .pointing canvas the pointer cursor.
        const target = e.native?.target as HTMLElement | undefined;
        target?.classList.toggle('pointing', elements.length > 0);
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
        x: opts.linear ? {
          type: 'linear',
          min: 0,
          ...(cap === null ? {} : {
            max: cap * 1.1,
            afterBuildTicks: (axis: Scale) => {
              axis.ticks = [...axis.ticks.filter((t) => t.value <= cap), { value: OVER }];
            },
          }),
          title: {
            display: true,
            text: opts.axisTitle ?? `${unit} per reviewer over the range`,
            color: theme.muted,
          },
          border: { color: theme.baseline },
          grid: { color: theme.grid },
          ticks: {
            color: theme.muted,
            maxRotation: 0,
            callback: (v) => {
              const n = Number(v);
              if (cap !== null && n === OVER) return `>${cap}`;
              return n < 1000 ? String(n) : fmtNum(n, { notation: 'compact' });
            },
          },
        } : {
          type: 'logarithmic',
          min: axisMin,
          max: max * 1.4,
          title: {
            display: true,
            text: opts.axisTitle ?? `${unit} per reviewer over the range (log scale)`,
            color: theme.muted,
          },
          border: { color: theme.baseline },
          grid: { color: theme.grid },
          afterBuildTicks: (axis) => {
            const ticks = zeros ? [{ value: ZERO }] : [];
            // 1, 3, 10, 30, …; powers of ten only on narrow screens.
            const threes = (axis.width || 600) >= 480;
            for (let e = lowExp; 10 ** e <= axis.max; e++) {
              const p = 10 ** e;
              if (p >= axisMin) ticks.push({ value: p });
              const p3 = Number((3 * p).toPrecision(6));
              if (threes && p3 >= axisMin && p3 <= axis.max) ticks.push({ value: p3 });
            }
            axis.ticks = ticks;
          },
          ticks: {
            color: theme.muted,
            maxRotation: 0,
            callback: (v) => {
              const n = Number(v);
              if (n === ZERO) return '0';
              return n < 1000 ? String(n) : fmtNum(n, { notation: 'compact' });
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
              return s ? `${s.org} (${fmtInt(s.stats.n)})` : '';
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

