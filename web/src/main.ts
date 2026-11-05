// Data files are referenced from the repo, not copied: Vite emits them as
// hashed assets at build time, so the site always reads the committed data.
import { fmtDay, fmtInt, fmtNum } from './format.ts';
import summaryUrl from '../../summaries/org_weekly.json?url';
import totalsUrl from '../../summaries/weekly_totals.csv?url';
import radarUrl from '../../data/public/radar_browser_share.csv?url';
import orgBrowsersUrl from '../../config/org_browsers.csv?url';
import reviewerUrl from '../../summaries/reviewer_weekly.json?url';
import areaUrl from '../../summaries/area_weekly.json?url';
import areaReviewersUrl from '../../summaries/area_reviewers.json?url';
import threadExamplesUrl from '../../summaries/thread_examples.json?url';

import {
  type AnyChart,
  ORG_BRIGHT,
  readTheme,
  renderParityChart,
  renderRatioChart,
  renderReviewChart,
  renderSpreadChart,
  renderReviewerChart,
  type ReviewScale,
  renderUsageChart,
  type Theme,
} from './charts.ts';
import { buildAreaChart } from './areas.ts';
import { buildDirPerReviewChart, fmtRatio } from './dirreview.ts';
import { buildHeatmap, heatMax, type HeatCellInfo, type HeatValue } from './heatmap.ts';
import { buildLeaderboard } from './leaderboard.ts';
import {
  addWeeks,
  DEFAULT_HEAT_BIN,
  dirNodeByPath,
  dirWeeklyCounts,
  gerritDirUrl,
  HEAT_BIN_SIZES,
  type HeatBinSize,
  heatGrid,
  rowReviewers,
  topAccounts,
  dirRows,
  dirPerReviewRows,
  DIR_PER_REVIEW_MIN,
  DIR_PER_REVIEW_ORG_MIN,
  dirTotals,
  dirTree,
  topDirOrgs,
  type DirBoard,
  type DirRow,
  dirReviewerIndex,
  type DirReviewers,
  dirRowLink,
  OTHER,
  chartedOrgs,
  rangeChartedOrgs,
  clampRange,
  compareWeeks,
  computeRatios,
  DEFAULT_SMOOTHING,
  smoothingName,
  smoothRatios,
  ratioWeeks,
  SMOOTHING_WEEKS,
  type Smoothing,
  dataRanges,
  distinctReviewers,
  isoDate,
  isoWeekOf,
  isWeek,
  meanDerivedShare,
  METRICS,
  addressedRange,
  addressedWeeks,
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
  orgsByAllTimeReview,
  orgColorSlots,
  topReviewers,
  orgsByValue,
  reviewerTotals,
  reviewerHandle,
  orgSpreads,
  orgPerReviewSpreads,
  perReviewMetric,
  PER_REVIEW_MIN,
  trimRanked,
  LEADERBOARD_SIZE,
  LEADERBOARD_SIZES,
  leaderboardLimit,
  leaderboardOrgs,
  type LeaderboardSize,
  TABLE_TOP_ORGS,
  namedOrgs,
  NAMED_ORG_MIN_SHARE,
  weekMonday,
  weeksIn,
  weekSunday,
  type Metric,
  type RadarWeekly,
  type ReviewerBoard,
  type Summary,
  type WeekRange,
  type WeeklyTotals,
  gerritCommentUrl,
  gerritReviewsUrl,
  reviewerSeries,
  threadBreakdown,
  type ThreadExamples,
  type ThreadOutcome,
} from './data.ts';
import { formatRatio } from './scale.ts';
import { fill, msg, type Vars } from './text.ts';

interface Data {
  summary: Summary;
  totals: WeeklyTotals[];
  radar: RadarWeekly;
  orgBrowsers: Map<string, string[]>;
  reviewers: ReviewerBoard;
  areas: DirBoard;
  /** Who wrote each directory's comments: only the directory chart's links
   * need it, so it's fetched after the first render. */
  areaReviewers?: DirReviewers;
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
  /** How many reviewers the leaderboard shows. */
  lbSize: LeaderboardSize;
  /** Leaderboard organization: ALL_ORGS, ALL_BUT_GOOGLE, OTHER_ORGS, or one org. */
  lbOrg: string;
  /** Directory chart rows the reader expanded (DirRow keys); not in the URL. */
  expandedDirs: Set<string>;
  /** Per-review directory chart rows the reader expanded; its own set, as it
   * orders rows by reviews, so its "more" rows hold other entries. */
  expandedPrDirs: Set<string>;
  /** The directory the organization chart is limited to (a tree path), or null for the path scope. */
  reviewDir: string | null;
  /** Heatmap organization: ALL_ORGS, ALL_BUT_GOOGLE, OTHER_ORGS, or one org. */
  heatOrg: string;
  heatBin: HeatBinSize;
  heatValue: HeatValue;
  /** Heatmap rows the reader expanded; not in the URL. */
  heatExpanded: Set<string>;
  /** The reviewer whose weekly chart is open (Gerrit account id), or null. */
  lbReviewer: number | null;
}

/** The range the user picked. While the addressed metric narrows the views'
 * range (withView), the reviewer chart and thread box still use this one. */
let userRange: WeekRange | null = null;
let reviewerChart: AnyChart | undefined;
let distChart: AnyChart | undefined;
let perReviewChart: AnyChart | undefined;
/** What the usage chart was last built for (see renderViews). */
let usageChartKey = '';
let parityChart: AnyChart | undefined;
let examples: Promise<ThreadExamples> | null = null;

/** Organization choices (heatmap and leaderboard) besides a single org. */
const ALL_ORGS = '*';
const ALL_BUT_GOOGLE = '*-google.com';
/** Every org but the selector's named ones (namedOrgs), combined. */
const OTHER_ORGS = '*other';

/** The org the linear review chart leaves out, so the rest are legible, and
 * the one the leaderboard can leave out. */
const LINEAR_EXCLUDED_ORG = 'google.com';

declare global {
  interface Window {
    __cosh?: {
      data: Data;
      state: State;
      parityChart?: AnyChart;
      ratioChart?: AnyChart;
      reviewChart?: AnyChart;
      usageChart?: AnyChart;
      distChart?: AnyChart;
      perReviewChart?: AnyChart;
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
  const [summary, totals, radar, orgBrowsers, reviewers, areas] = await Promise.all([
    fetchText(summaryUrl).then((t) => JSON.parse(t) as Summary),
    fetchText(totalsUrl).then(parseWeeklyTotals),
    fetchText(radarUrl).then(parseRadarWeekly),
    fetchText(orgBrowsersUrl).then(parseOrgBrowsers),
    fetchText(reviewerUrl).then((t) => JSON.parse(t) as ReviewerBoard),
    fetchText(areaUrl).then((t) => JSON.parse(t) as DirBoard),
  ]);
  summary.meta.weeks.sort(compareWeeks);
  const ranges = dataRanges(summary.meta.weeks, [...radar.keys()]);
  return { summary, totals, radar, orgBrowsers, reviewers, areas, ranges };
}

const pct = (x: number) => `${(x * 100).toFixed(x !== 0 && x < 0.01 ? 2 : 1)}%`;

/** The orgs the review sections name over the selected range (namedOrgs):
 * decided by review comments, so the same whatever the metric. */
const rangeNamedOrgs = (data: Data, state: State) => namedOrgs(data.summary, weeksIn(data.summary.meta.weeks, state.range));
const int = fmtInt;
const day = fmtDay;

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

/** Each metric's name, from its button in index.html (read before any is
 * removed); metricUnit is the name mid-sentence. */
const METRIC_NAMES = new Map<Metric, string>();
const metricName = (m: Metric) => METRIC_NAMES.get(m) ?? m;
const metricUnit = (m: Metric) => msg('metric-unit', { m });

/** The metrics this data can show: addressed comments only once some week is classified. */
function availableMetrics(data: Data): Metric[] {
  const addressed = addressedWeeks(data.summary).length > 0;
  return METRICS.filter((m) => m !== 'addressed' || addressed);
}

/** Addressed comments whenever any week is classified (the views then show
 * the range's classified part), else review comments. */
function defaultMetric(data: Data): Metric {
  return addressedWeeks(data.summary).length > 0 ? 'addressed' : 'comments';
}

/** The range the views show: the user's, or for the addressed metric only
 * its classified part (first to last classified week in it). */
function viewRange(data: Data, state: State): WeekRange {
  if (state.metric !== 'addressed') return state.range;
  return addressedRange(data.summary, state.range).range ?? state.range;
}

/** Runs `fn` with state.range narrowed to viewRange, then restores the
 * user's range (which the URL, pickers and range summary keep showing). */
function withView(data: Data, state: State, fn: () => void) {
  const chosen = state.range;
  state.range = viewRange(data, state);
  const outer = chartQueue === null;
  if (outer) chartQueue = [];
  try {
    fn();
    if (outer) for (const draw of chartQueue!) draw();
  } finally {
    if (outer) chartQueue = null;
    state.range = chosen;
  }
}

/** Chart builds waiting for the end of the current render (withView). A
 * Chart.js chart reads its container's size when built, which forces a
 * layout; built amid the render's DOM changes, every chart forced a full one.
 * Built together after them, only the first does. */
let chartQueue: (() => void)[] | null = null;

/** Runs `draw` at the end of the current render, or now outside one. */
function drawChart(draw: () => void) {
  if (chartQueue) chartQueue.push(draw);
  else draw();
}

function renderMetricNote(data: Data, state: State) {
  const note = $('#metric-note');
  // Only when there is nothing to show: the metric itself is described elsewhere.
  if (state.metric !== 'addressed' || addressedRange(data.summary, state.range).range) {
    note.hidden = true;
    return;
  }
  const all = addressedWeeks(data.summary);
  fill(note, { classified: all.length, dates: all.length ? rangeDates({ from: all[0], to: all[all.length - 1] }) : '' });
  note.hidden = false;
}

function readStateFromUrl(data: Data): State {
  const q = new URLSearchParams(location.hash.slice(1));
  const { full, common } = data.ranges;
  const week = q.get('week'); // links from before the range picker
  const from = isWeek(q.get('from')) ? q.get('from')! : isWeek(week) ? week : common.from;
  const to = isWeek(q.get('to')) ? q.get('to')! : isWeek(week) ? week : common.to;
  const sm = Number(q.get('smooth'));
  const smoothing = SMOOTHING_WEEKS.find((w) => w === sm) ?? DEFAULT_SMOOTHING;
  const reviewScale: ReviewScale = q.get('rscale') === 'linear' ? 'linear' : 'log';
  const lbn = q.get('lbn');
  const lbSize = LEADERBOARD_SIZES.find((n) => String(n) === lbn) ?? LEADERBOARD_SIZE;
  // lbg=0: links from before the organization select.
  const lbOrg = q.get('lbo') || (q.get('lbg') === '0' ? ALL_BUT_GOOGLE : ALL_ORGS);
  const dir = q.get('dir');
  const dirNode = dir ? dirNodeByPath(data.areas, dir) : null;
  const hmb = Number(q.get('hmb'));
  const range = clampRange({ from, to }, full);
  const asked = q.get('metric');
  const metric = availableMetrics(data).includes(asked as Metric) ? (asked as Metric) : defaultMetric(data);
  return {
    metric,
    range,
    smoothing,
    reviewScale,
    lbSize,
    lbOrg,
    expandedDirs: new Set(),
    expandedPrDirs: new Set(),
    reviewDir: dirNode === null ? null : dirTree(data.areas).paths[dirNode],
    heatOrg: q.get('hm') || ALL_ORGS,
    heatBin: HEAT_BIN_SIZES.find((n) => n === hmb) ?? DEFAULT_HEAT_BIN,
    heatValue: q.get('hmv') === 'share' ? 'share' : 'volume',
    heatExpanded: new Set(),
    lbReviewer: /^\d+$/.test(q.get('lbr') ?? '') ? Number(q.get('lbr')) : null,
  };
}

/** `allData` is the "All data" range: a range equal to it is left out of the
 * URL, so a reload or shared link keeps "All data" as new weeks arrive. */
function writeStateToUrl(s: State, allData: WeekRange) {
  const all = s.range.from === allData.from && s.range.to === allData.to;
  history.replaceState(null, '', `#metric=${s.metric}${all ? '' : `&from=${s.range.from}&to=${s.range.to}`}&smooth=${s.smoothing}` +
    (s.reviewScale === 'linear' ? '&rscale=linear' : '') +
    (s.lbSize !== LEADERBOARD_SIZE ? `&lbn=${s.lbSize}` : '') +
    (s.lbOrg !== ALL_ORGS ? `&lbo=${encodeURIComponent(s.lbOrg)}` : '') +
    (s.reviewDir ? `&dir=${encodeURIComponent(s.reviewDir)}` : '') +
    (s.heatOrg !== ALL_ORGS ? `&hm=${encodeURIComponent(s.heatOrg)}` : '') +
    (s.heatBin !== DEFAULT_HEAT_BIN ? `&hmb=${s.heatBin}` : '') +
    (s.heatValue !== 'volume' ? '&hmv=share' : '') +
    (s.lbReviewer !== null ? `&lbr=${s.lbReviewer}` : ''));
}

/** How many directories the directory field suggests; any other one can be typed. */
const DIR_OPTIONS = 3000;

/** A range preset button's length in weeks (index.html's data-preset), or null for all data. */
const presetWeeks = (b: HTMLElement) => (b.dataset.preset === 'all' ? null : Number(b.dataset.preset));

function presetRange(data: Data, weeks: number | null): WeekRange {
  const { full, common } = data.ranges;
  if (weeks === null) return common;
  return clampRange({ from: addWeeks(common.to, 1 - weeks), to: common.to }, full);
}

/** Wires a fieldset of radios (written in index.html): checks `current`
 * and calls `pick` with the value chosen. */
function radios(box: HTMLElement, current: string | number, pick: (value: string) => void) {
  for (const input of box.querySelectorAll<HTMLInputElement>('input[type="radio"]')) {
    input.checked = input.value === String(current);
    input.addEventListener('change', () => pick(input.value));
  }
}

/** `renderSoon` re-renders after the browser has painted, so the control
 * just used shows its new state at once (used where a render is slow). */
function buildControls(data: Data, state: State, render: () => void, renderSoon: () => void) {
  // The metric buttons name the metrics; drop those this data can't show.
  const available = availableMetrics(data);
  for (const input of $('#metric').querySelectorAll<HTMLInputElement>('input')) {
    const label = input.closest('label')!;
    METRIC_NAMES.set(input.value as Metric, label.textContent!.trim());
    if (!available.includes(input.value as Metric)) label.remove();
  }
  radios($('#metric'), state.metric, (v) => {
    state.metric = v as Metric;
    // Re-rendering every section takes a while; paint the toggle first.
    renderSoon();
  });
  radios($('#smoothing'), state.smoothing, (v) => {
    state.smoothing = Number(v) as Smoothing;
    render();
  });
  radios($('#review-scale'), state.reviewScale, (v) => {
    state.reviewScale = v as ReviewScale;
    render();
  });

  const sizeSelect = $<HTMLSelectElement>('#leaderboard-size');
  sizeSelect.value = String(state.lbSize);
  sizeSelect.addEventListener('change', () => {
    state.lbSize = LEADERBOARD_SIZES.find((n) => String(n) === sizeSelect.value) ?? LEADERBOARD_SIZE;
    render();
  });
  $<HTMLSelectElement>('#leaderboard-org').addEventListener('change', (e) => {
    state.lbOrg = (e.target as HTMLSelectElement).value;
    render();
  });

  radios($('#heat-bin'), state.heatBin, (v) => {
    state.heatBin = Number(v) as HeatBinSize;
    render();
  });
  radios($('#heat-value'), state.heatValue, (v) => {
    state.heatValue = v as HeatValue;
    render();
  });
  // Only shown when the directory chart is too narrow for both bars (CSS);
  // it flips which one the rows show, so the chart needn't be rebuilt.
  radios($('#area-show'), $('#area-chart').dataset.show!, (v) => {
    $('#area-chart').dataset.show = v;
  });
  $<HTMLSelectElement>('#heat-org').addEventListener('change', (e) => {
    state.heatOrg = (e.target as HTMLSelectElement).value;
    state.heatExpanded.clear();
    render();
  });

  // The organization chart's directory: any directory in the tree, typed or
  // picked from the busiest few thousand.
  const dirInput = $<HTMLInputElement>('#review-dir');
  const { paths } = dirTree(data.areas);
  const busy = dirTotals(data.areas, Object.keys(data.areas.weeks), [], 'comments');
  $('#dir-options').replaceChildren(
    ...paths
      .map((p, i) => ({ p, v: busy.total[i] }))
      .filter((x) => x.v > 0)
      .sort((a, b) => b.v - a.v || (a.p < b.p ? -1 : 1))
      .slice(0, DIR_OPTIONS)
      .map(({ p }) => {
        const o = el('option');
        o.value = p;
        return o;
      }),
  );
  dirInput.value = state.reviewDir ?? '';
  const pickDir = () => {
    const text = dirInput.value.trim();
    const n = text ? dirNodeByPath(data.areas, text) : null;
    $('#review-dir-status').textContent = text && n === null ? msg('review-dir-status', { dir: text }) : '';
    if (text && n === null) return;
    state.reviewDir = n === null ? null : paths[n];
    render();
  };
  dirInput.addEventListener('change', pickDir);
  $('#review-dir-clear').addEventListener('click', () => {
    dirInput.value = '';
    pickDir();
    dirInput.focus();
  });

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

  for (const b of document.querySelectorAll<HTMLButtonElement>('#range-presets button')) {
    b.addEventListener('click', () => {
      state.range = presetRange(data, presetWeeks(b));
      render();
    });
  }
  return sync;
}

function renderRangeSummary(data: Data, state: State) {
  const r = state.range;
  const reviewWeeks = weeksIn(data.summary.meta.weeks, r).length;
  const n = rangeLength(r);
  fill($('#range-summary'), { dates: rangeDates(r), n, from: r.from, to: r.to, review: reviewWeeks, gaps: reviewWeeks < n });
  for (const b of document.querySelectorAll<HTMLButtonElement>('#range-presets button')) {
    const pr = presetRange(data, presetWeeks(b));
    b.setAttribute('aria-pressed', String(pr.from === r.from && pr.to === r.to));
  }
}

function renderTiles(data: Data, weeks: string[]) {
  const t = sumWeeklyTotals(data.totals, weeks);
  const rows = orgTotals(data.summary, weeks);
  const reviewers = distinctReviewers(data.reviewers, weeks).total;
  const comments = rows.reduce((s, r) => s + r.comments, 0);
  const ai = rows.reduce((s, r) => s + r.ai_comments, 0);
  const postMerge = rows.reduce((s, r) => s + r.post_merge_comments, 0);
  // The tiles and their wording are in index.html; each sub-line is the template named after its tile.
  const tile = (id: string, value: string, sub: Vars | null) => {
    const box = $(`#${id}`);
    box.querySelector('.tile-value')!.textContent = value;
    const line = box.querySelector('.tile-sub')!;
    if (sub) fill(line, sub, id);
    else line.replaceChildren();
  };
  tile('tile-cls', t ? int(t.main_cls) : '—', t && { merged: int(t.merged_cls), abandoned: int(t.abandoned_cls) });
  tile('tile-human', t ? int(t.human_cls) : '—', t && { commented: int(t.human_cls_with_comments), bots: int(t.bot_cls) });
  tile('tile-comments', int(comments), { reviewers: int(reviewers) });
  tile('tile-ai', int(ai), comments ? { share: pct(ai / comments) } : null);
  tile('tile-post', int(postMerge), comments ? { share: pct(postMerge / comments) } : null);
}

/** Template values for the range's weeks the value views leave out for
 * lacking review or usage data: their number, and a list if it's short. */
function skippedVars(weeks: string[], vWeeks: string[]) {
  const kept = new Set(vWeeks);
  const out = weeks.filter((w) => !kept.has(w));
  return { skippedN: out.length, skipped: out.length <= 3 ? out.map((w) => rangeDates({ from: w, to: w })).join('; ') : '' };
}

/** Each org's share of the metric and of usage over the range, and their
 * ratio: what the table lists and the parity chart plots. */
function orgRangeShares(data: Data, state: State, weeks: string[], vWeeks: string[] = weeks) {
  const totals = orgTotals(data.summary, weeks, distinctReviewers(data.reviewers, weeks).byOrg);
  // Review share and usage share over the same weeks: those with both.
  const vTotals = vWeeks === weeks ? totals : orgTotals(data.summary, vWeeks);
  const orgs = new Set([...totals.map((r) => r.org), ...data.orgBrowsers.keys(), ...UNKNOWN_USAGE_ORGS.keys()]);
  return [...orgs].map((org) => {
    const row = totals.find((r) => r.org === org);
    const vRow = vTotals.find((r) => r.org === org);
    const browsers = data.orgBrowsers.get(org);
    const contribution = vRow ? vRow[SHARE_COLUMN[state.metric]] : 0;
    const derived = browsers && vWeeks.length ? meanDerivedShare(data.radar, vWeeks, browsers) : null;
    const ratio = derived !== null && derived >= MIN_DERIVED_SHARE ? contribution / derived : null;
    const unknownUsage = UNKNOWN_USAGE_ORGS.has(org);
    return { org, row, browsers, unknownUsage, contribution, derived, ratio };
  });
}

/** The parity chart: review share against usage share over the range, for
 * the orgs the ratio-over-time chart shows. */
function renderParity(data: Data, state: State, weeks: string[], orgs: string[], colors: Map<string, string>, theme: Theme) {
  const metricLabel = metricUnit(state.metric);
  const items = orgRangeShares(data, state, weeks).filter((it) => orgs.includes(it.org) && it.ratio !== null);
  const none = items.filter((it) => it.contribution <= 0).map((it) => it.org);
  drawChart(() => {
    parityChart?.destroy();
    parityChart = renderParityChart(
      $<HTMLCanvasElement>('#parity-chart'),
      items.map((it) => ({ org: it.org, contribution: it.contribution, derived: it.derived! })),
      metricLabel,
      colors,
      theme,
    );
  });
  fill($('#parity-sub'), {
    weeks: weeks.length,
    multi: weeks.length > 1,
    metric: metricLabel,
    none: none.join(', '),
    noneN: none.length,
  });
}

function renderTable(data: Data, state: State, weeks: string[], vWeeks: string[], colors: Map<string, string>) {
  const classified = new Set(addressedWeeks(data.summary));
  const addressedShown = weeks.length > 0 && weeks.every((w) => classified.has(w));
  const items = orgRangeShares(data, state, weeks, vWeeks);
  items.sort((a, b) => b.contribution - a.contribution || (b.derived ?? 0) - (a.derived ?? 0));
  const shown = trimRanked(items, TABLE_TOP_ORGS, (it) => !!it.browsers || it.unknownUsage);
  const hidden = items.length - shown.length;
  fill($('#table-caption'), {
    weeks: weeks.length,
    multi: weeks.length > 1,
    metric: metricUnit(state.metric),
    top: TABLE_TOP_ORGS,
    omitted: int(hidden),
    ...skippedVars(weeks, vWeeks),
  });
  const tbody = $('#org-table tbody');
  tbody.replaceChildren(
    ...shown.map((it) => {
      const tr = el('tr');
      tr.dataset.org = it.org;
      const orgCell = el('th');
      orgCell.scope = 'row';
      const swatch = el('span', undefined, 'swatch');
      const color = colors.get(it.org);
      if (color) swatch.style.setProperty('--color', color);
      orgCell.append(swatch, document.createTextNode(it.org));
      const ratioText = msg('ratio-cell', {
        is: it.ratio !== null ? 'value' : it.unknownUsage ? 'unknown' : !it.browsers ? 'no-browser' : it.derived === null ? 'no-usage' : 'small',
        ratio: it.ratio !== null ? formatRatio(it.ratio) : '',
      });
      const r = it.row;
      const cells = [
        pct(it.contribution),
        it.unknownUsage ? 'unknown' : it.browsers ? (it.derived === null ? '—' : pct(it.derived)) : '—',
        ratioText,
        r ? int(r.reviewers) : '0',
        r ? int(r.reviewed_cls) : '—',
        r ? int(r.comments) : '—',
        r && addressedShown ? int(r.addressed_comments) : '—',
        r ? int(r.review_chars) : '—',
        r ? int(r.ai_comments) : '—',
        r ? int(r.post_merge_comments) : '—',
      ];
      tr.append(orgCell, ...cells.map((c, i) => el('td', c, i === 2 ? 'ratio' : undefined)));
      return tr;
    }),
  );
}

/** Fills an organization select: index.html gives everyone, everyone but
 * google.com and "Other" (everyone else); the top orgs go before "Other",
 * and the current choice after it if it isn't among them. */
function fillOrgSelect(select: HTMLSelectElement, top: string[], current: string) {
  const single = current.startsWith('*') ? null : current;
  const extra = single && !top.includes(single) ? [single] : [];
  const option = (org: string) => {
    const o = el('option', org);
    o.value = org;
    o.dataset.org = '';
    return o;
  };
  select.querySelectorAll('option[data-org]').forEach((o) => o.remove());
  select.querySelector(`option[value="${OTHER_ORGS}"]`)!.before(...top.map(option));
  select.append(...extra.map(option));
  select.value = single || current === ALL_BUT_GOOGLE || current === OTHER_ORGS ? current : ALL_ORGS;
}

function renderLeaderboard(
  data: Data,
  state: State,
  colors: Map<string, string>,
  theme: Theme,
  render: () => void,
): void {
  const name = metricName(state.metric);
  const weeks = weeksIn(Object.keys(data.reviewers.weeks), state.range);
  const all = topReviewers(data.reviewers, weeks, state.metric, Infinity);

  // The selector: the named orgs over the range, by the metric, "Other", plus the current choice.
  const single = state.lbOrg.startsWith('*') ? null : state.lbOrg;
  const noGoogle = state.lbOrg === ALL_BUT_GOOGLE;
  const named = rangeNamedOrgs(data, state);
  const ranked = orgsByValue(all).filter((o) => named.includes(o));
  const top = [...ranked, ...named.filter((o) => !ranked.includes(o))];
  fillOrgSelect($<HTMLSelectElement>('#leaderboard-org'), top, state.lbOrg);
  const keep = single
    ? (o: string) => o === single
    : noGoogle
      ? (o: string) => o !== LINEAR_EXCLUDED_ORG
      : state.lbOrg === OTHER_ORGS
        ? (o: string) => !top.includes(o)
        : null;
  const rows = (keep ? all.filter((r) => keep(r.org)) : all).slice(0, leaderboardLimit(state.lbSize));
  // Fixed for a given range and metric: the toggles below it mustn't move.
  fill($('#leaderboard-sub'), {
    weeks: weeks.length,
    name,
    multi: weeks.length > 1,
    min: pct(NAMED_ORG_MIN_SHARE),
  });

  // Orgs with a fixed review colour get a legend entry, most reviewers first;
  // the rest get the muted bar and are named on their rows instead, with no
  // legend entry (with Show: All there can be dozens of them).
  const orgs = leaderboardOrgs(rows);
  const lbColors = colors;
  const legend = orgs
    .filter((o) => lbColors.has(o.org))
    .map(({ org, reviewers }) => {
      const li = el('li');
      const sw = el('span', undefined, 'swatch');
      sw.style.setProperty('--color', lbColors.get(org)!);
      li.append(sw, document.createTextNode(`${org} (${reviewers})`));
      return li;
    });
  $('#leaderboard-legend').replaceChildren(...legend);
  buildLeaderboard($('#leaderboard-chart'), rows, metricUnit(state.metric), (org) => lbColors.get(org), state.lbReviewer, (id) => {
    state.lbReviewer = id;
    render();
    $('#reviewer-detail').scrollIntoView({ block: 'nearest' });
  });
  renderReviewerDetail(data, state, colors, theme, render);
}

/** One reviewer's review comments and addressed comments per week over the
 * picked range, with their reviews on Gerrit. All from reviewer_weekly.json,
 * which the leaderboard already loads: no extra data. */
function renderReviewerDetail(data: Data, state: State, colors: Map<string, string>, theme: Theme, render: () => void) {
  const box = $('#reviewer-detail');
  reviewerChart?.destroy();
  reviewerChart = undefined;
  if (state.lbReviewer === null) {
    box.hidden = true;
    return;
  }
  const range = userRange ?? state.range;
  const weeks = weeksIn(Object.keys(data.reviewers.weeks), range);
  const classified = new Set(addressedWeeks(data.summary));
  const r = reviewerSeries(data.reviewers, state.lbReviewer, weeks, classified);
  const total = r.comments.reduce((a, b) => a + b, 0);
  const addressed = r.addressed.reduce<number>((a, b) => a + (b ?? 0), 0);
  const nClassified = weeks.filter((w) => classified.has(w)).length;
  box.hidden = false;
  // The email identifies the account (the bar colour and legend already give
  // the org); the org only when there's no email.
  const who = r.email ?? r.org;
  $('#rd-title').textContent = `${r.name}${who ? ` (${who})` : ''}`;
  fill($('#rd-sub'), {
    total: int(total),
    classified: nClassified,
    all: nClassified === weeks.length,
    addressed: int(addressed),
  });
  const color = (r.org && colors.get(r.org)) || theme.muted;
  reviewerChart = renderReviewerChart($<HTMLCanvasElement>('#reviewer-chart'), weeks, r.comments, r.addressed, color, theme);
  const link = $<HTMLAnchorElement>('#rd-gerrit');
  const url = gerritReviewsUrl(r.email, range);
  link.hidden = !url;
  if (url) link.href = url;
  $('#rd-close').onclick = () => {
    state.lbReviewer = null;
    render();
  };
}

/** An outcome's name, from index.html. */
const outcomeLabel = (o: ThreadOutcome) => msg('thread-outcome', { o });

/** How the reviewer-started threads of the picked range's classified weeks
 * were decided, with example threads per outcome (loaded on first open). */
function renderThreads(data: Data, state: State) {
  const box = $('#threads');
  const available = addressedWeeks(data.summary).length > 0;
  box.hidden = !available;
  if (!available) return;
  const range = userRange ?? state.range;
  const { weeks } = addressedRange(data.summary, range);
  const counts = threadBreakdown(data.summary, weeks);
  const total = counts ? [...counts.values()].reduce((a, b) => a + b, 0) : 0;
  const bar = $('#threads-bar');
  const legend = $('#threads-legend');
  fill($('#threads-sub'), {
    total: counts ? int(total) : '',
  });
  if (!counts || !total) {
    bar.replaceChildren();
    legend.replaceChildren();
    $('#threads-examples').replaceChildren();
    return;
  }
  const outcomes = [...counts.keys()].filter((o) => counts.get(o)! > 0);
  bar.replaceChildren(
    ...outcomes.map((o) => {
      const seg = el('span', undefined, `tb-seg tb-${o}`);
      seg.style.setProperty('--share', String(counts.get(o)! / total));
      seg.title = `${outcomeLabel(o)}: ${int(counts.get(o)!)} (${pct(counts.get(o)! / total)})`;
      return seg;
    }),
  );
  bar.setAttribute('aria-label', outcomes.map((o) => `${outcomeLabel(o)}: ${pct(counts.get(o)! / total)}`).join('; '));
  legend.replaceChildren(
    ...outcomes.map((o) => {
      const li = el('li');
      li.dataset.outcome = o;
      li.append(el('span', undefined, `tb-swatch tb-${o}`), el('span', outcomeLabel(o)),
        el('span', `${int(counts.get(o)!)} · ${pct(counts.get(o)! / total)}`, 'tb-n'));
      return li;
    }),
  );
  // Example threads: one collapsed list per outcome; the file loads on the first open.
  const shown = new Set(weeks);
  const box2 = $('#threads-examples');
  box2.replaceChildren(
    ...(['done_reply', 'model_addressed', 'model_not', 'no_reply'] as ThreadOutcome[]).map((o) => {
      const det = el('details');
      det.dataset.outcome = o;
      det.append(el('summary', msg('thread-examples', { outcome: outcomeLabel(o) })));
      det.addEventListener('toggle', () => {
        if (!det.open || det.dataset.loaded) return;
        det.dataset.loaded = 'true';
        examples ??= fetchText(threadExamplesUrl).then((t) => JSON.parse(t) as ThreadExamples);
        examples
          .then((ex) => {
            const list = ex.threads
              .filter((t) => t.outcome === o && shown.has(t.week))
              .sort((a, b) => compareWeeks(b.week, a.week))
              .slice(0, 6);
            if (!list.length) det.append(el('p', msg('thread-examples-none'), 'tb-msg'));
            for (const t of list) det.append(exampleThread(t));
          })
          .catch((err: unknown) => det.append(el('p', msg('thread-examples-error', { error: String(err) }), 'tb-msg')));
      });
      return det;
    }),
  );
}

function exampleThread(t: ThreadExamples['threads'][number]): HTMLElement {
  const box = el('div', undefined, 'tb-thread');
  const head = el('div', undefined, 'tb-thread-head');
  const a = el('a', `CL ${t.cl}`);
  a.href = gerritCommentUrl(t.cl, t.root);
  a.target = '_blank';
  a.rel = 'noopener';
  head.append(a, document.createTextNode(` · ${t.path === '/PATCHSET_LEVEL' ? 'patchset-level comment' : t.path} · week of ${day(weekMonday(t.week))}`));
  box.append(head);
  for (const [role, text] of t.messages) {
    const p = el('p', undefined, 'tb-msg');
    p.append(el('span', role, 'tb-role'), document.createTextNode(text));
    box.append(p);
  }
  if (t.more) box.append(el('p', `… ${t.more} more ${t.more === 1 ? 'reply' : 'replies'} on Gerrit`, 'tb-msg'));
  return box;
}

/** Review by directory: every comment in the range, by directory and org, with
 * the path rules that decide what the other sections count. */
function renderAreas(data: Data, state: State, colors: Map<string, string>, theme: Theme) {
  const weeks = weeksIn(Object.keys(data.areas.weeks), state.range);
  const orgs = topDirOrgs(data.areas, weeks, state.metric, rangeNamedOrgs(data, state));
  const totals = dirTotals(data.areas, weeks, orgs, state.metric);
  const unit = metricUnit(state.metric);
  const segColors = colors;
  const { roots } = dirTree(data.areas);
  const total = roots.reduce((s, r) => s + totals.total[r], 0);
  const inScope = roots.filter((r) => data.areas.nodes[r][2]).reduce((s, r) => s + totals.total[r], 0);
  fill($('#areas-sub'), {
    total: int(total),
    m: state.metric,
    metric: unit,
    share: total ? pct(inScope / total) : '',
    counted: int(inScope),
  });
  const legend = [...orgs.map((org) => ({ org, color: segColors.get(org) ?? '' })), { org: OTHER, color: '' }];
  $('#areas-legend').replaceChildren(
    ...legend.map(({ org, color }) => {
      const li = el('li');
      const sw = el('span', undefined, color ? 'swatch' : 'swatch swatch-muted');
      if (color) sw.style.setProperty('--color', color);
      li.append(sw, document.createTextNode(org));
      return li;
    }),
  );
  const box = $('#area-chart');
  const who = data.areaReviewers && dirReviewerIndex(data.areas, data.areaReviewers, weeks, orgs);
  const linkOf = (row: DirRow, org: string) => (who ? dirRowLink(data.areas, who, row, org, state.range) : null);
  const draw = (focusKey?: string) => {
    const rows = dirRows(data.areas, totals, state.expandedDirs);
    buildAreaChart(box, rows, orgs, (org) => segColors.get(org), metricName(state.metric), unit, (key) => {
      if (state.expandedDirs.has(key)) state.expandedDirs.delete(key);
      else state.expandedDirs.add(key);
      draw(key);
    }, linkOf);
    // Rebuilding the rows drops focus; give it back to the toggle just used.
    if (focusKey) box.querySelector<HTMLButtonElement>(`li[data-key="${CSS.escape(focusKey)}"] .ar-toggle`)?.focus();
  };
  draw();
}

/** The metric per review by directory: how much review a CL gets in each
 * part of the codebase, every comment in the range, in scope or not. */
function renderDirPerReview(data: Data, state: State, colors: Map<string, string>) {
  const weeks = weeksIn(Object.keys(data.areas.weeks), state.range);
  const num = perReviewMetric(state.metric);
  const orgs = topDirOrgs(data.areas, weeks, 'cls', rangeNamedOrgs(data, state));
  const all = dirTotals(data.areas, weeks, orgs, 'cls');
  const nums = dirTotals(data.areas, weeks, orgs, num);
  // Comments that can't be placed on a file are left out: mostly sign-offs on
  // CLs the reviewer didn't comment on line by line, they say nothing about
  // the code, and they are a third of all reviews. A node with no total is
  // not listed (dirRows).
  const roots = dirTree(data.areas).roots.filter((r) => data.areas.nodes[r][1] !== data.areas.meta.unplaced);
  const reviews = { ...all, total: all.total.map((v, i) => (roots.includes(i) || data.areas.nodes[i][0] >= 0 ? v : 0)) };
  const total = roots.reduce((s, r) => s + reviews.total[r], 0);
  const overall = total ? roots.reduce((s, r) => s + nums.total[r], 0) / total : 0;
  const unit = metricUnit(num);
  fill($('#dr-title'), { name: metricName(num) });
  fill($('#dr-sub'), {
    total,
    metric: unit,
    overall: fmtRatio(overall),
    reviews: int(total),
    min: DIR_PER_REVIEW_MIN,
    orgmin: DIR_PER_REVIEW_ORG_MIN,
  });
  $('#dr-legend').replaceChildren(
    ...[...orgs, OTHER].map((org) => {
      const li = el('li');
      const color = org === OTHER ? undefined : colors.get(org);
      const sw = el('span', undefined, color ? 'swatch swatch-dot' : 'swatch swatch-dot swatch-muted');
      if (color) sw.style.setProperty('--color', color);
      li.append(sw, document.createTextNode(org));
      return li;
    }),
  );
  const box = $('#dr-chart');
  const draw = (focusKey?: string) => {
    const rows = dirPerReviewRows(data.areas, reviews, nums, state.expandedPrDirs);
    buildDirPerReviewChart(box, rows, orgs, (org) => colors.get(org), metricName(num), unit, overall, (key) => {
      if (state.expandedPrDirs.has(key)) state.expandedPrDirs.delete(key);
      else state.expandedPrDirs.add(key);
      draw(key);
    });
    if (focusKey) box.querySelector<HTMLButtonElement>(`li[data-key="${CSS.escape(focusKey)}"] .ar-toggle`)?.focus();
  };
  draw();
}

/** The organization chart's note when it shows one directory: which of its comments it counts. */
function renderDirNote(board: DirBoard, dir: string, node: number, weeks: string[], metric: Metric) {
  const t = dirTotals(board, weeks, [], metric);
  const inc = t.total[node] ? t.inc[node] / t.total[node] : board.nodes[node][2];
  fill($('#review-dir-note'), {
    dir,
    scope: inc >= 1 ? 'all' : inc <= 0 ? 'none' : 'part',
    part: pct(1 - inc),
    m: metric,
  });
}

/** How the metric is spread across reviewers, org by org: a strip plot of
 * each reviewer's total over the range, and a table of each org's figures. */
function renderDistribution(
  data: Data,
  state: State,
  colors: Map<string, string>,
  theme: Theme,
  render: () => void,
) {
  const unit = metricUnit(state.metric);
  const weeks = weeksIn(Object.keys(data.reviewers.weeks), state.range);
  // Who counts: for addressed comments, everyone who wrote a review comment
  // (0 addressed is telling); for the other metrics, those with some of it.
  const all = reviewerTotals(data.reviewers, weeks, state.metric).filter((r) =>
    state.metric === 'addressed' ? r.comments > 0 : r.value > 0,
  );
  const spreads = orgSpreads(all, data.reviewers.meta.fold_into_other ?? [], rangeNamedOrgs(data, state));
  const colorOf = (org: string) => colors.get(org) ?? theme.muted;

  fill($('#dist-sub'), {
    weeks: weeks.length,
    metric: unit,
    min: pct(NAMED_ORG_MIN_SHARE),
    m: state.metric,
  });

  const fmt = (v: number) => fmtNum(v, { maximumFractionDigits: 1 });
  $('#dist-table tbody').replaceChildren(
    ...spreads.map((s) => {
      const tr = el('tr');
      tr.dataset.org = s.org;
      const th = el('th');
      th.scope = 'row';
      const sw = el('span', undefined, s.org === OTHER || !colors.has(s.org) ? 'swatch swatch-muted' : 'swatch');
      if (colors.has(s.org)) sw.style.setProperty('--color', colors.get(s.org)!);
      th.append(sw, document.createTextNode(s.org));
      const st = s.stats;
      tr.append(
        th,
        ...[int(st.n), fmt(st.q1), fmt(st.median), fmt(st.q3), pct(st.top10Share), int(st.total)].map((c) => el('td', c)),
      );
      return tr;
    }),
  );

  // One row of dots per org: the chart grows with the rows.
  $('#dist-box').style.setProperty('--rows', String(Math.max(1, spreads.length)));
  drawChart(() => {
    distChart?.destroy();
    distChart = renderSpreadChart(
      $<HTMLCanvasElement>('#dist-chart'),
      spreads,
      colorOf,
      (id) => reviewerHandle(data.reviewers, id),
      unit,
      theme,
      state.lbReviewer,
      (id) => {
        state.lbReviewer = id;
        render();
        $('#reviewer-detail').scrollIntoView({ block: 'nearest' });
      },
    );
  });
  renderPerReview(data, state, weeks, spreads.map((s) => s.org), colorOf, theme, render);
}

/** Where the addressed-comments-per-review axis ends: a few reviewers far
 * above it would otherwise squash everyone else to the left. */
const PER_REVIEW_CAP = 9;

/** How deep each review goes, org by org: a strip plot of each reviewer's
 * metric per reviewed CL over the range (review comments per review when the
 * metric is reviewed CLs), on the same org rows as the per-reviewer spread. */
function renderPerReview(
  data: Data,
  state: State,
  weeks: string[],
  orgOrder: string[],
  colorOf: (org: string) => string,
  theme: Theme,
  render: () => void,
) {
  const num = perReviewMetric(state.metric);
  const unit = `${metricUnit(num)} per review`;
  const spreads = orgPerReviewSpreads(data.reviewers, weeks, state.metric, orgOrder);

  fill($('#pr-title'), { name: metricName(num) });
  fill($('#pr-sub'), {
    weeks: weeks.length,
    metric: metricUnit(num),
    min: PER_REVIEW_MIN,
    cap: PER_REVIEW_CAP,
    m: num,
  });

  const fmt = (v: number) => fmtNum(v, { maximumFractionDigits: v < 10 ? 2 : 0 });
  $('#pr-table tbody').replaceChildren(
    ...spreads.map((s) => {
      const tr = el('tr');
      tr.dataset.org = s.org;
      const th = el('th');
      th.scope = 'row';
      const color = s.org === OTHER ? undefined : colorOf(s.org);
      const named = color !== undefined && color !== theme.muted;
      const sw = el('span', undefined, named ? 'swatch' : 'swatch swatch-muted');
      if (named) sw.style.setProperty('--color', color);
      th.append(sw, document.createTextNode(s.org));
      const st = s.stats;
      tr.append(th, ...[int(st.n), fmt(st.q1), fmt(st.median), fmt(st.q3), fmt(s.pooled)].map((c) => el('td', c)));
      return tr;
    }),
  );

  $('#pr-box').style.setProperty('--rows', String(Math.max(1, spreads.length)));
  drawChart(() => {
    perReviewChart?.destroy();
    perReviewChart = renderSpreadChart(
      $<HTMLCanvasElement>('#pr-chart'),
      spreads,
      colorOf,
      (id) => reviewerHandle(data.reviewers, id),
      unit,
      theme,
      state.lbReviewer,
      (id) => {
        state.lbReviewer = id;
        render();
        $('#reviewer-detail').scrollIntoView({ block: 'nearest' });
      },
      { axisTitle: `${unit}, per reviewer over the range`, linear: true,
        cap: num === 'addressed' ? PER_REVIEW_CAP : undefined },
    );
  });
}

/** Reviewers a heatmap cell's hover text names. */
const HEAT_TOP_REVIEWERS = 3;

/** Review by directory over time: the heatmap, its organization choices and legend. */
function renderHeat(data: Data, state: State, colors: Map<string, string>, theme: Theme, render: () => void) {
  const board = data.areas;
  const rangeWeeks = weeksIn(Object.keys(board.weeks), state.range);
  const unit = metricUnit(state.metric);

  // The selector: the named orgs over the range, by the metric, "Other", plus the current choice.
  const single = state.heatOrg.startsWith('*') ? null : state.heatOrg;
  const named = rangeNamedOrgs(data, state);
  const ranked = topDirOrgs(board, rangeWeeks, state.metric, named);
  const top = [...ranked, ...named.filter((o) => !ranked.includes(o))];
  fillOrgSelect($<HTMLSelectElement>('#heat-org'), top, state.heatOrg);
  const noGoogle = state.heatOrg === ALL_BUT_GOOGLE;
  const others = state.heatOrg === OTHER_ORGS;

  // "Other" is the rest combined: one segment, with the top orgs left out.
  const keep = noGoogle
    ? (o: string) => o !== LINEAR_EXCLUDED_ORG
    : others
      ? (o: string) => !top.includes(o)
      : undefined;
  const segOrgs = single
    ? [single]
    : others
      ? []
      : topDirOrgs(board, rangeWeeks, state.metric, named, keep);
  const segColors = colors;
  const grid = heatGrid(board, state.range, state.heatBin, state.metric, segOrgs, state.heatExpanded, {
    only: keep,
    rankOnly: single ? (o) => o === single : keep,
  });
  const { paths } = dirTree(board);
  const binTitle = (b: WeekRange) => rangeDates(b);
  const rowTitle = (r: DirRow) => (r.node !== undefined && r.kind === 'dir' ? paths[r.node] : r.title);

  // Links and the "most active" line come from the reviewer file, once loaded.
  let cellInfo: ((row: number, bin: number) => HeatCellInfo | null) | undefined;
  if (data.areaReviewers) {
    // An excluded org gets its own segment, so it can be dropped rather than hide in Other.
    const idxOrgs = noGoogle ? [...segOrgs, LINEAR_EXCLUDED_ORG] : others ? top : segOrgs;
    const perBin = grid.binWeeks.map((w) => dirReviewerIndex(board, data.areaReviewers!, w, idxOrgs));
    const keepSeg = single ? (o: string) => o === single : others ? (o: string) => o === OTHER : keep;
    cellInfo = (ri, bi) => {
      const idx = perBin[bi];
      const row = grid.rows[ri];
      const who = idx ? rowReviewers(idx, row, keepSeg) : undefined;
      if (!who?.comments.size || row.node === undefined) return null;
      // Emails, which stand for name and org.
      const top = topAccounts(who.comments, HEAT_TOP_REVIEWERS).map(([id, n]) => ({
        who: reviewerHandle(data.reviewers, id),
        comments: n,
      }));
      return { link: gerritDirUrl(paths[row.node], who.comments, grid.bins[bi]), top };
    };
  }

  const orgColor = single ? segColors.get(single) ?? theme.muted : undefined;
  buildHeatmap($('#heat-chart'), {
    grid,
    org: single,
    value: state.heatValue,
    orgs: segOrgs,
    colorOf: (o) => segColors.get(o),
    orgColor,
    unit,
    rowTitle,
    binTitle,
    cellInfo,
    onToggle: (key) => {
      if (state.heatExpanded.has(key)) state.heatExpanded.delete(key);
      else state.heatExpanded.add(key);
      render();
      // Rebuilding the rows drops focus; give it back to the toggle just used.
      $('#heat-chart').querySelector<HTMLButtonElement>(`tr[data-key="${CSS.escape(key)}"] .ar-toggle`)?.focus();
    },
    onChart: (row) => {
      state.reviewDir = rowTitle(row);
      render();
      $('#review-title').scrollIntoView({ block: 'start' });
      $<HTMLInputElement>('#review-dir').focus({ preventScroll: true });
    },
  });

  // Fixed for a given range and metric: it describes every choice of the
  // toggles below it, so switching them doesn't move them.
  fill($('#heat-sub'), {
    weeks: rangeWeeks.length,
    name: metricName(state.metric),
    metric: unit,
    m: state.metric,
  });

  const legend = $('#heat-legend');
  if (single) {
    const li = el('li');
    // The ramp's colours are in style.css (.hm-ramp), from the org's colour.
    li.style.setProperty('--color', orgColor!);
    fill(li, { share: state.heatValue === 'share', metric: unit, max: int(heatMax(grid, single)) }, 'heat-legend');
    legend.replaceChildren(li);
  } else {
    legend.replaceChildren(
      ...[...segOrgs.map((org) => ({ org, color: segColors.get(org) ?? '' })), { org: OTHER, color: '' }].map(
        ({ org, color }) => {
          const li = el('li');
          const sw = el('span', undefined, color ? 'swatch' : 'swatch swatch-muted');
          if (color) sw.style.setProperty('--color', color);
          li.append(sw, document.createTextNode(org));
          return li;
        },
      ),
    );
  }
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
  let usageChart: AnyChart | undefined;
  const browsers = topBrowsers(data.radar);
  const jumpWeek = derivativeJumpWeek(data.radar);
  let syncInputs = () => {};

  // Every chart colours orgs from this one map, fixed for the page: the
  // range, metric and filters never repaint an org, and no two orgs share a
  // colour. A named org (namedOrgs) outside the map still gets its own
  // series, row and legend entry, in grey: it is never folded into Other.
  const slots = orgColorSlots(orgsByAllTimeReview(data.summary), orgs, ORG_BRIGHT);
  const colorsFor = (theme: Theme) => new Map([...slots].map(([o, i]) => [o, theme.orgs[i]]));

  // A render waiting for the next paint (renderSoon). Any render meanwhile
  // covers it, so it's dropped; several renderSoon calls share one render.
  let pending = false;
  const setPending = (on: boolean) => {
    pending = on;
    // For tests (body[data-pending]) and assistive tech (aria-busy).
    if (on) document.body.dataset.pending = 'true';
    else delete document.body.dataset.pending;
    if (on) $('main').setAttribute('aria-busy', 'true');
    else $('main').removeAttribute('aria-busy');
  };
  const renderSoon = () => {
    writeStateToUrl(state, data.ranges.common);
    if (pending) return;
    setPending(true);
    // rAF runs just before the next paint; the timeout after it.
    requestAnimationFrame(() => setTimeout(() => pending && render(), 0));
  };

  const render = () => {
    if (pending) setPending(false);
    writeStateToUrl(state, data.ranges.common);
    syncInputs();
    renderRangeSummary(data, state);
    renderMetricNote(data, state);
    userRange = state.range;
    withView(data, state, renderViews);
  };

  const renderViews = () => {
    const theme = readTheme();
    const colors = colorsFor(theme);
    // Every section covers the selected range only.
    const weeks = weeksIn(data.summary.meta.weeks, state.range);
    // Smooth over every week before filtering, so the range's first weeks
    // average over earlier data too.
    // Addressed comments exist only for classified weeks; the running
    // averages skip the others instead of reading them as zero.
    const dataWeeks = state.metric === 'addressed' ? addressedWeeks(data.summary) : undefined;
    // The value views cover only weeks with both review data for the metric
    // and Radar usage, e.g. not 2023-W26, which Radar has only 2 days of.
    const vWeeks = ratioWeeks(weeks, data.radar, dataWeeks);
    const shownWeeks = new Set(vWeeks);
    // The value charts show the orgs with enough mean usage over the range.
    const shown = rangeChartedOrgs(data.radar, data.orgBrowsers, orgs, vWeeks);
    const points = smoothRatios(
      computeRatios(data.summary, data.radar, data.orgBrowsers, state.metric, undefined, dataWeeks),
      state.smoothing,
    ).filter(
      (p) => shown.includes(p.org) && shownWeeks.has(p.week),
    );

    // A running average shows no ratio until its window is full of data:
    // start the chart at its first ratio instead of on empty weeks.
    const firstRatio = vWeeks.findIndex((w) => points.some((p) => p.week === w && p.ratio !== null));
    const chartWeeks = firstRatio < 0 ? [] : vWeeks.slice(firstRatio);

    renderParity(data, state, vWeeks, shown, colors, theme);
    drawChart(() => {
      ratioChart?.destroy();
      ratioChart = renderRatioChart($<HTMLCanvasElement>('#ratio-chart'), chartWeeks, shown, colors, points, theme, state.smoothing);
    });
    const name = metricName(state.metric);
    const metricLabel = metricUnit(state.metric);
    const linear = state.reviewScale === 'linear';
    // One directory (every comment in it, from the directory data), or the path scope (org_weekly).
    const dirNode = state.reviewDir === null ? null : dirNodeByPath(data.areas, state.reviewDir);
    const named = rangeNamedOrgs(data, state);
    const seriesFor = (lin: boolean) => {
      const exclude = lin ? [LINEAR_EXCLUDED_ORG] : [];
      return dirNode === null
        ? orgWeeklyCounts(data.summary, weeks, state.metric, named, state.smoothing, exclude, dataWeeks)
        : dirWeeklyCounts(data.areas, dirNode, weeks, state.metric, named, state.smoothing, exclude, dataWeeks);
    };
    const reviewSeries = seriesFor(linear);
    drawChart(() => {
      reviewChart?.destroy();
      reviewChart = renderReviewChart(
        $<HTMLCanvasElement>('#review-chart'),
        weeks,
        reviewSeries,
        metricLabel,
        colors,
        theme,
        state.reviewScale,
      );
    });
    fill($('#review-sub'), {
      weeks: weeks.length,
      metric: name,
        smoothed: state.smoothing > 1,
      smoothing: smoothingName(state.smoothing),
      min: pct(NAMED_ORG_MIN_SHARE),
    });
    // The chosen directory's note sits below the controls, so it can't move them.
    const dirNote = $('#review-dir-note');
    dirNote.hidden = dirNode === null || !weeks.length;
    if (dirNode === null) dirNote.replaceChildren();
    else renderDirNote(data.areas, state.reviewDir!, dirNode, weeks, state.metric);
    const dirInput = $<HTMLInputElement>('#review-dir');
    if (document.activeElement !== dirInput) dirInput.value = state.reviewDir ?? '';
    $('#review-dir-clear').hidden = state.reviewDir === null;
    renderHeat(data, state, colors, theme, render);
    renderAreas(data, state, colors, theme);
    renderDirPerReview(data, state, colors);
    renderDistribution(data, state, colors, theme, render);
    renderLeaderboard(data, state, colors, theme, render);
    renderThreads(data, state);
    // Usage doesn't depend on the metric (or the review filters): rebuild
    // only when its range or the theme changes.
    const usageWeeks = weeksIn(data.radar.keys(), state.range);
    const usageKey = JSON.stringify([usageWeeks[0], usageWeeks[usageWeeks.length - 1], usageWeeks.length, theme]);
    if (!usageChart || usageKey !== usageChartKey) {
      usageChartKey = usageKey;
      drawChart(() => {
        usageChart?.destroy();
        usageChart = renderUsageChart(
          $<HTMLCanvasElement>('#usage-chart'),
          data.radar,
          usageWeeks,
          browsers,
          jumpWeek ? { week: jumpWeek, text: 'ChromeDerivative jump' } : null,
          theme,
        );
      });
    }

    fill($('#ratio-sub'), {
      weeks: weeks.length,
      shown: chartWeeks.length,
      metric: metricLabel,
        smoothed: state.smoothing > 1,
      smoothing: smoothingName(state.smoothing),
      // Set when the running average's warm-up moves the chart's start.
      start: chartWeeks.length && chartWeeks[0] !== vWeeks[0] ? day(weekMonday(chartWeeks[0])) : '',
      ...skippedVars(weeks, vWeeks),
    });
    renderTiles(data, weeks);
    renderTable(data, state, weeks, vWeeks, colors);
    // Queued after the charts, so it holds the new ones.
    drawChart(() => {
      window.__cosh = { data, state, parityChart, ratioChart, reviewChart, usageChart, distChart, perReviewChart, render };
    });
  };

  // The intro's link scrolls to the classifier explainer, which is in the
  // thread box (shown once some week is classified). The URL hash holds the
  // page state, so the link must not replace it.
  $('#addressed-link').addEventListener('click', (e) => {
    if ($('#threads').hidden) return;
    e.preventDefault();
    $('#addressed-details').scrollIntoView({ block: 'start' });
  });
  // The data is in: swap the loading note for the page before anything is
  // built, so the controls and charts lay out at their real size.
  $('#loading').hidden = true;
  $('main').hidden = false;
  syncInputs = buildControls(data, state, render, renderSoon);
  // The metric bar is sticky; scroll-padding-top (in style.css) keeps anchor
  // jumps clear of it, at whatever height it wraps to.
  const metricBar = $('.metric-bar');
  new ResizeObserver(() =>
    document.documentElement.style.setProperty('--metric-bar-h', `${metricBar.offsetHeight}px`),
  ).observe(metricBar);
  render();
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', render);
  const weeks = data.summary.meta.weeks;
  fill($('#coverage'), {
    weeks: weeks.length,
    dates: rangeDates({ from: weeks[0], to: weeks[weeks.length - 1] }),
    usage: day(weekMonday([...data.radar.keys()].sort()[0])),
  });
  document.body.dataset.ready = 'true';
  // The directory sections' Gerrit links and "most active" lines need a file
  // larger than the rest of the page's data. It's fetched only now, after the
  // first render, so it holds nothing up. Until it arrives (or if it fails)
  // the segments and cells aren't links.
  fetchText(areaReviewersUrl)
    .then((t) => {
      data.areaReviewers = JSON.parse(t) as DirReviewers;
      // Its arrival rebuilds both sections' rows. If the reader has just
      // pressed a toggle in one, that drops focus: give it back.
      const active = document.activeElement;
      const box = active?.closest<HTMLElement>('#area-chart, #heat-chart');
      const key = active?.classList.contains('ar-toggle') ? active.closest<HTMLElement>('[data-key]')?.dataset.key : undefined;
      const theme = readTheme();
      withView(data, state, () => {
        renderAreas(data, state, colorsFor(theme), theme);
        renderHeat(data, state, colorsFor(theme), theme, render);
      });
      if (box && key) box.querySelector<HTMLButtonElement>(`[data-key="${CSS.escape(key)}"] .ar-toggle`)?.focus({ preventScroll: true });
      document.body.dataset.areaLinks = 'true';
    })
    .catch((err: unknown) => console.error(err));
}

load()
  .then(main)
  .catch((err: unknown) => {
    console.error(err);
    $('#loading').hidden = true;
    $('#error').hidden = false;
    fill($('#error'), { error: err instanceof Error ? err.message : String(err) });
    document.body.dataset.ready = 'error';
  });
