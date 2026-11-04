import './style.css';
// Data files are referenced from the repo, not copied: Vite emits them as
// hashed assets at build time, so the site always reads the committed data.
import summaryUrl from '../../summaries/org_weekly.json?url';
import totalsUrl from '../../summaries/weekly_totals.csv?url';
import radarUrl from '../../data/public/radar_browser_share.csv?url';
import orgBrowsersUrl from '../../config/org_browsers.csv?url';
import reviewerUrl from '../../summaries/reviewer_weekly.json?url';

import {
  type AnyChart,
  LEADERBOARD_ROW_PX,
  readTheme,
  renderLeaderboardChart,
  renderRatioChart,
  renderReviewChart,
  type ReviewScale,
  renderUsageChart,
  type Theme,
} from './charts.ts';
import {
  addWeeks,
  chartedOrgs,
  clampRange,
  compareWeeks,
  computeRatios,
  DEFAULT_SMOOTHING,
  smoothRatios,
  SMOOTHING_WEEKS,
  type Smoothing,
  dataRanges,
  distinctReviewers,
  isoDate,
  isoWeekOf,
  isWeek,
  meanDerivedShare,
  METRICS,
  MIN_DERIVED_SHARE,
  UNKNOWN_USAGE_ORGS,
  orgTotals,
  parseIsoDate,
  parseOrgBrowsers,
  parseRadarWeekly,
  parseWeeklyTotals,
  rangeLength,
  SHARE_COLUMN,
  sumWeeklyTotals,
  topBrowsers,
  orgWeeklyCounts,
  topReviewers,
  trimRanked,
  LEADERBOARD_SIZE,
  TABLE_TOP_ORGS,
  weekMonday,
  weeksIn,
  weekSunday,
  type Metric,
  type RadarWeekly,
  type ReviewerBoard,
  type Summary,
  type WeekRange,
  type WeeklyTotals,
} from './data.ts';
import { formatRatio } from './scale.ts';

interface Data {
  summary: Summary;
  totals: WeeklyTotals[];
  radar: RadarWeekly;
  orgBrowsers: Map<string, string[]>;
  reviewers: ReviewerBoard;
  /** full: the pickers' limits; common: where review and usage data overlap (the default). */
  ranges: { full: WeekRange; common: WeekRange };
}

interface State {
  metric: Metric;
  range: WeekRange;
  /** Value ratio running average, in weeks (1 = off). */
  smoothing: Smoothing;
  /** Review chart axis: log with every org, or linear without google.com. */
  reviewScale: ReviewScale;
}

/** The org the linear review chart leaves out, so the rest are legible. */
const LINEAR_EXCLUDED_ORG = 'google.com';

declare global {
  interface Window {
    __cosh?: {
      data: Data;
      state: State;
      ratioChart?: AnyChart;
      reviewChart?: AnyChart;
      leaderboardChart?: AnyChart;
      usageChart?: AnyChart;
      render: () => void;
    };
  }
}

const $ = <T extends HTMLElement>(sel: string) => document.querySelector<T>(sel)!;

async function fetchText(url: string): Promise<string> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url}: HTTP ${res.status}`);
  return res.text();
}

async function load(): Promise<Data> {
  const [summary, totals, radar, orgBrowsers, reviewers] = await Promise.all([
    fetchText(summaryUrl).then((t) => JSON.parse(t) as Summary),
    fetchText(totalsUrl).then(parseWeeklyTotals),
    fetchText(radarUrl).then(parseRadarWeekly),
    fetchText(orgBrowsersUrl).then(parseOrgBrowsers),
    fetchText(reviewerUrl).then((t) => JSON.parse(t) as ReviewerBoard),
  ]);
  summary.meta.weeks.sort(compareWeeks);
  const ranges = dataRanges(summary.meta.weeks, [...radar.keys()]);
  return { summary, totals, radar, orgBrowsers, reviewers, ranges };
}

const pct = (x: number) => `${(x * 100).toFixed(x !== 0 && x < 0.01 ? 2 : 1)}%`;
const int = (x: number) => x.toLocaleString('en-US');
const day = (d: Date, year = true) =>
  d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', ...(year ? { year: 'numeric' } : {}), timeZone: 'UTC' });

function el<K extends keyof HTMLElementTagNameMap>(tag: K, text?: string, cls?: string) {
  const e = document.createElement(tag);
  if (text !== undefined) e.textContent = text;
  if (cls) e.className = cls;
  return e;
}

/** Calendar dates of a range: "30 Mar – 1 Nov 2026". */
function rangeDates(r: WeekRange): string {
  const a = weekMonday(r.from);
  const b = weekSunday(r.to);
  return `${day(a, a.getUTCFullYear() !== b.getUTCFullYear())} – ${day(b)}`;
}

/** Short label for captions: "2026-W44" or "2026-W14 to 2026-W44 (31 weeks)". */
function rangeLabel(r: WeekRange): string {
  return r.from === r.to ? r.from : `${r.from} to ${r.to} (${rangeLength(r)} weeks)`;
}

function readStateFromUrl(data: Data): State {
  const q = new URLSearchParams(location.hash.slice(1));
  const metric = METRICS.some((m) => m.id === q.get('metric')) ? (q.get('metric') as Metric) : 'comments';
  const { full, common } = data.ranges;
  const week = q.get('week'); // links from before the range picker
  const from = isWeek(q.get('from')) ? q.get('from')! : isWeek(week) ? week : common.from;
  const to = isWeek(q.get('to')) ? q.get('to')! : isWeek(week) ? week : common.to;
  const sm = Number(q.get('smooth'));
  const smoothing = SMOOTHING_WEEKS.find((w) => w === sm) ?? DEFAULT_SMOOTHING;
  const reviewScale: ReviewScale = q.get('rscale') === 'linear' ? 'linear' : 'log';
  return { metric, range: clampRange({ from, to }, full), smoothing, reviewScale };
}

function writeStateToUrl(s: State) {
  history.replaceState(null, '', `#metric=${s.metric}&from=${s.range.from}&to=${s.range.to}&smooth=${s.smoothing}` +
    (s.reviewScale === 'linear' ? '&rscale=linear' : ''));
}

const PRESETS: { id: string; label: string; weeks: number | null }[] = [
  { id: 'all', label: 'All data', weeks: null },
  { id: '13', label: 'Last 13 weeks', weeks: 13 },
  { id: '4', label: 'Last 4 weeks', weeks: 4 },
  { id: '1', label: 'Latest week', weeks: 1 },
];

function presetRange(data: Data, weeks: number | null): WeekRange {
  const { full, common } = data.ranges;
  if (weeks === null) return common;
  return clampRange({ from: addWeeks(common.to, 1 - weeks), to: common.to }, full);
}

function buildControls(data: Data, state: State, render: () => void) {
  const metricBox = $('#metric');
  // Replace only the buttons: the fieldset's <legend> is static markup.
  metricBox.querySelectorAll('label').forEach((l) => l.remove());
  for (const m of METRICS) {
    const label = el('label');
    const input = el('input');
    input.type = 'radio';
    input.name = 'metric';
    input.value = m.id;
    input.checked = m.id === state.metric;
    input.addEventListener('change', () => {
      state.metric = m.id;
      render();
    });
    label.append(input, document.createTextNode(m.label));
    metricBox.append(label);
  }

  const smoothBox = $('#smoothing');
  smoothBox.querySelectorAll('label').forEach((l) => l.remove());
  for (const w of SMOOTHING_WEEKS) {
    const label = el('label');
    const input = el('input');
    input.type = 'radio';
    input.name = 'smoothing';
    input.value = String(w);
    input.checked = w === state.smoothing;
    input.addEventListener('change', () => {
      state.smoothing = w;
      render();
    });
    label.append(input, document.createTextNode(w === 1 ? 'Off' : `${w} weeks`));
    smoothBox.append(label);
  }

  const scaleBox = $('#review-scale');
  scaleBox.querySelectorAll('label').forEach((l) => l.remove());
  const scales: { id: ReviewScale; label: string }[] = [
    { id: 'log', label: 'Log, all organizations' },
    { id: 'linear', label: `Linear, without ${LINEAR_EXCLUDED_ORG}` },
  ];
  for (const sc of scales) {
    const label = el('label');
    const input = el('input');
    input.type = 'radio';
    input.name = 'review-scale';
    input.value = sc.id;
    input.checked = sc.id === state.reviewScale;
    input.addEventListener('change', () => {
      state.reviewScale = sc.id;
      render();
    });
    label.append(input, document.createTextNode(sc.label));
    scaleBox.append(label);
  }

  const { full } = data.ranges;
  const fromInput = $<HTMLInputElement>('#from');
  const toInput = $<HTMLInputElement>('#to');
  for (const input of [fromInput, toInput]) {
    input.min = isoDate(weekMonday(full.from));
    input.max = isoDate(weekSunday(full.to));
  }
  // A date picks the ISO week it falls in. The "from" box snaps to that week's
  // Monday and "to" to its Sunday, but only once the box loses focus, so
  // typing a date isn't interrupted.
  const sync = () => {
    if (document.activeElement !== fromInput) fromInput.value = isoDate(weekMonday(state.range.from));
    if (document.activeElement !== toInput) toInput.value = isoDate(weekSunday(state.range.to));
  };
  const onChange = (end: 'from' | 'to') => () => {
    const d = parseIsoDate((end === 'from' ? fromInput : toInput).value);
    if (!d) return;
    const week = isoWeekOf(d);
    let { from, to } = state.range;
    if (end === 'from') {
      from = week;
      if (to < from) to = from;
    } else {
      to = week;
      if (from > to) from = to;
    }
    state.range = clampRange({ from, to }, full);
    render();
  };
  fromInput.addEventListener('change', onChange('from'));
  toInput.addEventListener('change', onChange('to'));
  fromInput.addEventListener('blur', sync);
  toInput.addEventListener('blur', sync);

  const presets = $('#range-presets');
  presets.replaceChildren(
    ...PRESETS.map((p) => {
      const b = el('button', p.label);
      b.type = 'button';
      b.dataset.preset = p.id;
      b.addEventListener('click', () => {
        state.range = presetRange(data, p.weeks);
        render();
      });
      return b;
    }),
  );
  return sync;
}

function renderRangeSummary(data: Data, state: State) {
  const r = state.range;
  const reviewWeeks = weeksIn(data.summary.meta.weeks, r).length;
  const n = rangeLength(r);
  const weeks = r.from === r.to ? r.from : `${r.from} to ${r.to}, ${n} weeks`;
  const gaps = reviewWeeks < n ? ` Review data covers ${reviewWeeks} of ${n === 1 ? 'it' : 'them'}.` : '';
  $('#range-summary').textContent = `${rangeDates(r)} (${weeks}).${gaps}`;
  for (const b of document.querySelectorAll<HTMLButtonElement>('#range-presets button')) {
    const p = PRESETS.find((x) => x.id === b.dataset.preset)!;
    const pr = presetRange(data, p.weeks);
    b.setAttribute('aria-pressed', String(pr.from === r.from && pr.to === r.to));
  }
}

function renderTiles(data: Data, weeks: string[]) {
  const t = sumWeeklyTotals(data.totals, weeks);
  const rows = orgTotals(data.summary, weeks);
  const reviewers = distinctReviewers(data.reviewers, weeks).total;
  const human = rows.reduce((s, r) => s + r.comments, 0);
  const ai = rows.reduce((s, r) => s + r.ai_comments, 0);
  const postMerge = rows.reduce((s, r) => s + r.post_merge_comments, 0);
  const tiles: [string, string, string][] = [
    ['CLs on main', t ? int(t.main_cls) : '—', t ? `${int(t.merged_cls)} merged, ${int(t.abandoned_cls)} abandoned` : ''],
    ['Human-owned CLs', t ? int(t.human_cls) : '—', t ? `${int(t.human_cls_with_review)} reviewed; ${int(t.bot_cls)} bot CLs` : ''],
    ['Review comments', int(human), `by ${int(reviewers)} reviewers`],
    ['Self-declared AI comments', int(ai), human + ai ? `${pct(ai / (human + ai))} of all; at least` : ''],
    ['Post-merge comments', int(postMerge), 'written after the CL landed; not in the headline'],
  ];
  $('#tiles').replaceChildren(
    ...tiles.map(([k, v, sub]) => {
      const d = el('div', undefined, 'tile');
      d.append(el('div', k, 'tile-label'), el('div', v, 'tile-value'), el('div', sub, 'tile-sub'));
      return d;
    }),
  );
}

function renderTable(data: Data, state: State, weeks: string[], colors: Map<string, string>) {
  const col = SHARE_COLUMN[state.metric];
  const totals = orgTotals(data.summary, weeks, distinctReviewers(data.reviewers, weeks).byOrg);
  const orgs = new Set([...totals.map((r) => r.org), ...data.orgBrowsers.keys(), ...UNKNOWN_USAGE_ORGS.keys()]);
  const items = [...orgs].map((org) => {
    const row = totals.find((r) => r.org === org);
    const browsers = data.orgBrowsers.get(org);
    const contribution = row ? row[col] : 0;
    const derived = browsers && weeks.length ? meanDerivedShare(data.radar, weeks, browsers) : null;
    const ratio = derived !== null && derived >= MIN_DERIVED_SHARE ? contribution / derived : null;
    const unknownUsage = UNKNOWN_USAGE_ORGS.has(org);
    return { org, row, browsers, unknownUsage, contribution, derived, ratio };
  });
  items.sort((a, b) => b.contribution - a.contribution || (b.derived ?? 0) - (a.derived ?? 0));
  const shown = trimRanked(items, TABLE_TOP_ORGS, (it) => !!it.browsers || it.unknownUsage);
  const hidden = items.length - shown.length;
  const trimNote = hidden
    ? ` Showing the top ${TABLE_TOP_ORGS} organizations by review share, plus those with a browser; ` +
      `${int(hidden)} smaller ${hidden === 1 ? 'organization is' : 'organizations are'} omitted.`
    : '';

  const multi = weeks.length > 1;
  const metricLabel = METRICS.find((m) => m.id === state.metric)!.label.toLowerCase();
  $('#table-caption').textContent = !weeks.length
    ? `${rangeLabel(state.range)}: no review data in this range.`
    : multi
      ? `${rangeLabel(state.range)}: counts are totals over the range (reviewers: distinct people); review share is the share of all ${metricLabel} ` +
        'in the range, usage share the mean weekly share of Chromium browser usage.'
      : `${rangeLabel(state.range)}: share of ${metricLabel} and of Chromium browser usage.`;
  if (weeks.length) $('#table-caption').textContent += trimNote;
  const tbody = $('#org-table tbody');
  tbody.replaceChildren(
    ...shown.map((it) => {
      const tr = el('tr');
      tr.dataset.org = it.org;
      const orgCell = el('th');
      orgCell.scope = 'row';
      const swatch = el('span', undefined, 'swatch');
      const color = colors.get(it.org);
      if (color) swatch.style.background = color;
      orgCell.append(swatch, document.createTextNode(it.org));
      const ratioText =
        it.ratio !== null
          ? `${formatRatio(it.ratio)}×`
          : it.unknownUsage
            ? 'usage unknown'
            : !it.browsers
              ? 'no browser'
              : it.derived === null
                ? 'no usage data'
                : 'usage too small';
      const r = it.row;
      const cells = [
        pct(it.contribution),
        it.unknownUsage ? 'unknown' : it.browsers ? (it.derived === null ? '—' : pct(it.derived)) : '—',
        ratioText,
        r ? int(r.reviewers) : '0',
        r ? int(r.reviewed_cls) : '—',
        r ? int(r.comments) : '—',
        r ? int(r.review_chars) : '—',
        r ? int(r.ai_comments) : '—',
        r ? int(r.post_merge_comments) : '—',
      ];
      tr.append(orgCell, ...cells.map((c, i) => el('td', c, i === 2 ? 'ratio' : undefined)));
      return tr;
    }),
  );
}

function renderLeaderboard(
  data: Data,
  state: State,
  colors: Map<string, string>,
  prev: AnyChart | undefined,
): AnyChart {
  prev?.destroy();
  const metricName = METRICS.find((m) => m.id === state.metric)!.label;
  const weeks = weeksIn(Object.keys(data.reviewers.weeks), state.range);
  const rows = topReviewers(data.reviewers, weeks, state.metric, LEADERBOARD_SIZE);
  $('#leaderboard-sub').textContent = !rows.length
    ? `No reviewer data for ${rangeLabel(state.range)}.`
    : `${metricName}${weeks.length > 1 ? ' in total' : ''}, ${rangeLabel(state.range)}, top ${rows.length} reviewers. ` +
      'Same scope as the organization chart: human reviewers on human-owned CLs.';
  $('#leaderboard-chart-box').style.height = `${rows.length * LEADERBOARD_ROW_PX + 36}px`;

  // Legend: the coloured orgs that appear, in colour order, then the rest.
  const present = new Set(rows.map((r) => r.org));
  const legend = [...colors].filter(([org]) => present.has(org)).map(([org, color]) => ({ org, color }));
  if (rows.some((r) => !colors.has(r.org))) legend.push({ org: 'other organizations', color: '' });
  $('#leaderboard-legend').replaceChildren(
    ...legend.map(({ org, color }) => {
      const li = el('li');
      const sw = el('span', undefined, color ? 'swatch' : 'swatch swatch-muted');
      if (color) sw.style.background = color;
      li.append(sw, document.createTextNode(org));
      return li;
    }),
  );
  return renderLeaderboardChart($<HTMLCanvasElement>('#leaderboard-chart'), rows, metricName, colors, readTheme());
}

/** Colours for the review chart: an org keeps its ratio-chart colour; orgs
 * without one take, in rank order, the series colours that no org in this
 * chart uses (all eight may be assigned to browser owners), then the muted
 * neutral. */
function reviewColors(orgs: string[], colors: Map<string, string>, theme: Theme): Map<string, string> {
  const out = new Map(orgs.filter((o) => colors.has(o)).map((o) => [o, colors.get(o)!]));
  const used = new Set(out.values());
  const spare = theme.series.filter((c) => !used.has(c));
  for (const org of orgs) if (!out.has(org) && spare.length) out.set(org, spare.shift()!);
  return out;
}

/** First week where Radar's unnamed-Chromium bucket more than triples week
 * over week (2026-W37 in the current data); see docs/plan.md, Open questions. */
function derivativeJumpWeek(radar: RadarWeekly): string | null {
  const weeks = [...radar.keys()].sort();
  for (let i = 1; i < weeks.length; i++) {
    const prev = radar.get(weeks[i - 1])!.get('ChromeDerivative') ?? 0;
    const cur = radar.get(weeks[i])!.get('ChromeDerivative') ?? 0;
    if (prev > 0 && cur > 3 * prev && cur > 0.02) return weeks[i];
  }
  return null;
}

function main(data: Data) {
  const state = readStateFromUrl(data);
  const orgs = chartedOrgs(data.radar, data.orgBrowsers).slice(0, 8);
  let ratioChart: AnyChart | undefined;
  let reviewChart: AnyChart | undefined;
  let leaderboardChart: AnyChart | undefined;
  let usageChart: AnyChart | undefined;
  const browsers = topBrowsers(data.radar);
  const jumpWeek = derivativeJumpWeek(data.radar);
  let syncInputs = () => {};

  const render = () => {
    writeStateToUrl(state);
    syncInputs();
    renderRangeSummary(data, state);
    const theme = readTheme();
    const colors = new Map(orgs.map((o, i) => [o, theme.series[i]]));
    // Every section covers the selected range only.
    const weeks = weeksIn(data.summary.meta.weeks, state.range);
    const label = rangeLabel(state.range);
    // Smooth over every week before filtering, so the range's first weeks
    // average over earlier data too.
    const points = smoothRatios(
      computeRatios(data.summary, data.radar, data.orgBrowsers, state.metric),
      state.smoothing,
    ).filter(
      (p) => orgs.includes(p.org) && weeks.includes(p.week),
    );

    ratioChart?.destroy();
    ratioChart = renderRatioChart($<HTMLCanvasElement>('#ratio-chart'), weeks, orgs, colors, points, theme, state.smoothing);
    const metricName = METRICS.find((m) => m.id === state.metric)!.label;
    const metricLabel = metricName.toLowerCase();
    reviewChart?.destroy();
    const linear = state.reviewScale === 'linear';
    const reviewSeries = orgWeeklyCounts(
      data.summary,
      weeks,
      state.metric,
      7,
      state.smoothing,
      linear ? [LINEAR_EXCLUDED_ORG] : [],
    );
    reviewChart = renderReviewChart(
      $<HTMLCanvasElement>('#review-chart'),
      weeks,
      reviewSeries,
      metricName,
      // Keep the excluded org's colour reserved, so the rest keep theirs
      // when the scale toggles.
      reviewColors([...reviewSeries.map((s) => s.org), ...(linear ? [LINEAR_EXCLUDED_ORG] : [])], colors, theme),
      theme,
      state.smoothing,
      state.reviewScale,
    );
    $('#review-sub').textContent = weeks.length
      ? `${metricName} per ISO week, ${label}` +
        (state.smoothing > 1
          ? `, as a ${state.smoothing}-week running average`
          : '') +
        ', for the organizations with the most over the range; the rest are combined as “Other”. ' +
        (linear
          ? `${LINEAR_EXCLUDED_ORG} is left out and the axis is linear, so the other organizations can be compared directly.`
          : 'The axis is logarithmic, since Google does most of the review.')
      : `No review data for ${label}.`;
    leaderboardChart = renderLeaderboard(data, state, colors, leaderboardChart);
    usageChart?.destroy();
    usageChart = renderUsageChart(
      $<HTMLCanvasElement>('#usage-chart'),
      data.radar,
      weeksIn(data.radar.keys(), state.range),
      browsers,
      jumpWeek ? { week: jumpWeek, text: 'ChromeDerivative jump' } : null,
      theme,
    );

    $('#ratio-sub').textContent = weeks.length
      ? `Share of ${metricLabel} ÷ share of Chromium browser usage, per ISO week, ${label}` +
        (state.smoothing > 1
          ? `, as a ${state.smoothing}-week running average (mean share of ${metricLabel} ÷ mean usage share over the ${state.smoothing} weeks ending each week). `
          : '. ') +
        'The 1.0× line is parity: review in proportion to usage.'
      : `No review data for ${label}.`;
    renderTiles(data, weeks);
    renderTable(data, state, weeks, colors);
    window.__cosh = { data, state, ratioChart, reviewChart, leaderboardChart, usageChart, render };
  };

  syncInputs = buildControls(data, state, render);
  render();
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', render);
  const weeks = data.summary.meta.weeks;
  $('#coverage').textContent =
    `Review data: ${weeks.length} week${weeks.length === 1 ? '' : 's'} (${weeks[0]}${weeks.length > 1 ? `–${weeks[weeks.length - 1]}` : ''}). ` +
    `Usage data: Cloudflare Radar, ${[...data.radar.keys()].sort()[0]} onward.`;
  document.body.dataset.ready = 'true';
}

load()
  .then(main)
  .catch((err: unknown) => {
    console.error(err);
    $('#error').hidden = false;
    $('#error').textContent = `Couldn't load data: ${err instanceof Error ? err.message : String(err)}`;
    document.body.dataset.ready = 'error';
  });
