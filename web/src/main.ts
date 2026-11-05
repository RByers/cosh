import './style.css';
// Data files are referenced from the repo, not copied: Vite emits them as
// hashed assets at build time, so the site always reads the committed data.
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
  readTheme,
  renderRatioChart,
  renderReviewChart,
  renderSpreadChart,
  renderReviewerChart,
  type ReviewScale,
  renderUsageChart,
  type Theme,
} from './charts.ts';
import { buildAreaChart } from './areas.ts';
import { buildHeatmap, heatMax, heatShade, type HeatCellInfo, type HeatValue } from './heatmap.ts';
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
  metricLabel as metricName,
  METRICS,
  addressedMeta,
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
  topReviewers,
  reviewerTotals,
  reviewerHandle,
  orgSpreads,
  trimRanked,
  LEADERBOARD_SIZE,
  LEADERBOARD_SIZES,
  leaderboardOrgs,
  type LeaderboardSize,
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
  THREAD_OUTCOME_LABELS,
  gerritCommentUrl,
  gerritReviewsUrl,
  reviewerSeries,
  threadBreakdown,
  type ThreadExamples,
  type ThreadOutcome,
} from './data.ts';
import { formatRatio } from './scale.ts';

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
  /** Whether the leaderboard includes google.com's reviewers. */
  lbGoogle: boolean;
  /** Directory chart rows the reader expanded (DirRow keys); not in the URL. */
  expandedDirs: Set<string>;
  /** The directory the organization chart is limited to (a tree path), or null for the path scope. */
  reviewDir: string | null;
  /** Heatmap organization: ALL_ORGS, ALL_BUT_GOOGLE, or one org. */
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
let examples: Promise<ThreadExamples> | null = null;

/** Heatmap organization choices besides a single org. */
const ALL_ORGS = '*';
const ALL_BUT_GOOGLE = '*-google.com';

/** The org the linear review chart leaves out, so the rest are legible, and
 * the one the leaderboard can leave out. */
const LINEAR_EXCLUDED_ORG = 'google.com';

declare global {
  interface Window {
    __cosh?: {
      data: Data;
      state: State;
      ratioChart?: AnyChart;
      reviewChart?: AnyChart;
      usageChart?: AnyChart;
      distChart?: AnyChart;
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

/** The metrics this data can show: addressed comments only once some week is classified. */
function availableMetrics(data: Data) {
  const addressed = addressedWeeks(data.summary).length > 0;
  return METRICS.filter((m) => m.id !== 'addressed' || addressed);
}

/** Addressed comments when every review week of the range is classified, else comments. */
function defaultMetric(data: Data, range: WeekRange): Metric {
  const review = weeksIn(data.summary.meta.weeks, range).length;
  const classified = addressedRange(data.summary, range).weeks.length;
  return review > 0 && classified === review ? 'addressed' : 'comments';
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
  try {
    fn();
  } finally {
    state.range = chosen;
  }
}

function renderMetricNote(data: Data, state: State) {
  const note = $('#metric-note');
  if (state.metric !== 'addressed') {
    note.hidden = true;
    return;
  }
  const meta = addressedMeta(data.summary);
  const review = weeksIn(data.summary.meta.weeks, state.range);
  const { weeks, range } = addressedRange(data.summary, state.range);
  const all = addressedWeeks(data.summary);
  const what =
    'Addressed comments: review comments in a thread that led the CL owner to change the CL (the owner replied ' +
    '“Done” or similar, or a Claude model read the thread as a change), one point per comment to its author; ' +
    'threads the owner never answered score nothing.';
  let cover: string;
  if (!range) {
    cover = ` No week in this range is classified yet${all.length ? ` (classified: ${all.length === 1 ? all[0] : `${all.length} weeks, ${all[0]}–${all[all.length - 1]}`})` : ''}, so there is nothing to show; the other metrics cover it.`;
  } else if (weeks.length === review.length) {
    cover = ` Every week in this range is classified${meta?.classifier ? ` (labels: ${meta.classifier})` : ''}.`;
  } else {
    cover = ` Only ${weeks.length} of the ${review.length} review weeks in this range ${weeks.length === 1 ? 'is' : 'are'} classified, so every ` +
      `section below shows ${rangeLabel(range)} only; the other metrics cover the whole range.`;
  }
  note.textContent = what + cover;
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
  const lbn = Number(q.get('lbn'));
  const lbSize = LEADERBOARD_SIZES.find((n) => n === lbn) ?? LEADERBOARD_SIZE;
  const lbGoogle = q.get('lbg') !== '0';
  const dir = q.get('dir');
  const dirNode = dir ? dirNodeByPath(data.areas, dir) : null;
  const hmb = Number(q.get('hmb'));
  const range = clampRange({ from, to }, full);
  const asked = q.get('metric');
  const metric = availableMetrics(data).some((m) => m.id === asked) ? (asked as Metric) : defaultMetric(data, range);
  return {
    metric,
    range,
    smoothing,
    reviewScale,
    lbSize,
    lbGoogle,
    expandedDirs: new Set(),
    reviewDir: dirNode === null ? null : dirTree(data.areas).paths[dirNode],
    heatOrg: q.get('hm') || ALL_ORGS,
    heatBin: HEAT_BIN_SIZES.find((n) => n === hmb) ?? DEFAULT_HEAT_BIN,
    heatValue: q.get('hmv') === 'share' ? 'share' : 'volume',
    heatExpanded: new Set(),
    lbReviewer: /^\d+$/.test(q.get('lbr') ?? '') ? Number(q.get('lbr')) : null,
  };
}

function writeStateToUrl(s: State) {
  history.replaceState(null, '', `#metric=${s.metric}&from=${s.range.from}&to=${s.range.to}&smooth=${s.smoothing}` +
    (s.reviewScale === 'linear' ? '&rscale=linear' : '') +
    (s.lbSize !== LEADERBOARD_SIZE ? `&lbn=${s.lbSize}` : '') +
    (s.lbGoogle ? '' : '&lbg=0') +
    (s.reviewDir ? `&dir=${encodeURIComponent(s.reviewDir)}` : '') +
    (s.heatOrg !== ALL_ORGS ? `&hm=${encodeURIComponent(s.heatOrg)}` : '') +
    (s.heatBin !== DEFAULT_HEAT_BIN ? `&hmb=${s.heatBin}` : '') +
    (s.heatValue !== 'volume' ? '&hmv=share' : '') +
    (s.lbReviewer !== null ? `&lbr=${s.lbReviewer}` : ''));
}

/** How many directories the directory field suggests; any other one can be typed. */
const DIR_OPTIONS = 3000;

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

/** Fills a segmented fieldset with one radio per option, keeping its static
 * <legend>. */
function segmented<T>(
  box: HTMLElement,
  name: string,
  options: { id: T; label: string }[],
  current: T,
  pick: (id: T) => void,
) {
  box.querySelectorAll('label').forEach((l) => l.remove());
  for (const o of options) {
    const label = el('label');
    const input = el('input');
    input.type = 'radio';
    input.name = name;
    input.value = String(o.id);
    input.checked = o.id === current;
    input.addEventListener('change', () => pick(o.id));
    label.append(input, document.createTextNode(o.label));
    box.append(label);
  }
}

function buildControls(data: Data, state: State, render: () => void) {
  // Replace only the buttons: each fieldset's <legend> is static markup.
  const metricBox = $('#metric');
  metricBox.querySelectorAll('label').forEach((l) => l.remove());
  for (const m of availableMetrics(data)) {
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
    label.append(input, document.createTextNode(w === 1 ? 'Off' : w === 13 ? '3 months' : `${w} weeks`));
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

  segmented(
    $('#leaderboard-size'),
    'leaderboard-size',
    LEADERBOARD_SIZES.map((n) => ({ id: n, label: `Top ${n}` })),
    state.lbSize,
    (n) => {
      state.lbSize = n;
      render();
    },
  );
  segmented(
    $('#leaderboard-google'),
    'leaderboard-google',
    [
      { id: true, label: 'All organizations' },
      { id: false, label: `Without ${LINEAR_EXCLUDED_ORG}` },
    ],
    state.lbGoogle,
    (g) => {
      state.lbGoogle = g;
      render();
    },
  );

  segmented(
    $('#heat-bin'),
    'heat-bin',
    HEAT_BIN_SIZES.map((n) => ({ id: n, label: n === 1 ? 'Weeks' : `${n} weeks` })),
    state.heatBin,
    (n) => {
      state.heatBin = n;
      render();
    },
  );
  segmented(
    $('#heat-value'),
    'heat-value',
    [
      { id: 'volume' as HeatValue, label: 'Volume' },
      { id: 'share' as HeatValue, label: 'Share' },
    ],
    state.heatValue,
    (v) => {
      state.heatValue = v;
      render();
    },
  );
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
    $('#review-dir-status').textContent = text && n === null ? `No directory “${text}” has review comments.` : '';
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
  const comments = rows.reduce((s, r) => s + r.comments, 0);
  const ai = rows.reduce((s, r) => s + r.ai_comments, 0);
  const postMerge = rows.reduce((s, r) => s + r.post_merge_comments, 0);
  const tiles: [string, string, string][] = [
    ['CLs on main', t ? int(t.main_cls) : '—', t ? `${int(t.merged_cls)} merged, ${int(t.abandoned_cls)} abandoned` : ''],
    ['Human-owned CLs', t ? int(t.human_cls) : '—', t ? `${int(t.human_cls_with_comments)} with review comments; ${int(t.bot_cls)} bot CLs` : ''],
    ['Review comments', int(comments), `by ${int(reviewers)} reviewers, on the selected paths`],
    ['Self-declared AI comments', int(ai), comments ? `${pct(ai / comments)} of review comments; at least` : ''],
    ['Post-merge comments', int(postMerge), comments ? `${pct(postMerge / comments)} of review comments; written after the CL landed` : ''],
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
  const totals = orgTotals(data.summary, weeks, distinctReviewers(data.reviewers, weeks).byOrg);
  const classified = new Set(addressedWeeks(data.summary));
  const addressedShown = weeks.length > 0 && weeks.every((w) => classified.has(w));
  const orgs = new Set([...totals.map((r) => r.org), ...data.orgBrowsers.keys(), ...UNKNOWN_USAGE_ORGS.keys()]);
  const items = [...orgs].map((org) => {
    const row = totals.find((r) => r.org === org);
    const browsers = data.orgBrowsers.get(org);
    const contribution = row ? row[SHARE_COLUMN[state.metric]] : 0;
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
  const metricLabel = metricName(state.metric).toLowerCase();
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

function renderLeaderboard(
  data: Data,
  state: State,
  colors: Map<string, string>,
  theme: Theme,
  render: () => void,
): void {
  const name = metricName(state.metric);
  const weeks = weeksIn(Object.keys(data.reviewers.weeks), state.range);
  const excluded = state.lbGoogle ? undefined : LINEAR_EXCLUDED_ORG;
  const rows = topReviewers(data.reviewers, weeks, state.metric, state.lbSize, excluded);
  // Fixed for a given range and metric: the toggles below it mustn't move.
  $('#leaderboard-sub').textContent = !weeks.length
    ? `No reviewer data for ${rangeLabel(state.range)}.`
    : `${name}${weeks.length > 1 ? ' in total' : ''}, ${rangeLabel(state.range)}, for the top reviewers: ` +
      `from every organization, or only those outside ${LINEAR_EXCLUDED_ORG}. ` +
      'Same scope as the organization chart: reviewers\' own (non-bot) accounts on human-owned CLs, on the selected paths.';

  // Every org on the board gets its own legend entry, most reviewers first.
  // The palette has room for the first theme.series.length of them (keeping
  // ratio-chart colours where they can); any beyond that get the muted bar
  // and are named on their rows instead.
  const orgs = leaderboardOrgs(rows);
  const lbColors = reviewColors(orgs.slice(0, theme.series.length).map((o) => o.org), colors, theme);
  const legend = orgs
    .filter((o) => lbColors.has(o.org))
    .map(({ org, reviewers }) => {
      const li = el('li');
      const sw = el('span', undefined, 'swatch');
      sw.style.background = lbColors.get(org)!;
      li.append(sw, document.createTextNode(`${org} (${reviewers})`));
      return li;
    });
  const unnamed = orgs.filter((o) => !lbColors.has(o.org));
  if (unnamed.length) {
    const li = el('li');
    li.append(
      el('span', undefined, 'swatch swatch-muted'),
      document.createTextNode(
        `named on each row: ${unnamed.map(({ org, reviewers }) => `${org} (${reviewers})`).join(', ')}`,
      ),
    );
    legend.push(li);
  }
  $('#leaderboard-legend').replaceChildren(...legend);
  buildLeaderboard($('#leaderboard-chart'), rows, name, (org) => lbColors.get(org), state.lbReviewer, (id) => {
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
  $('#rd-title').textContent = `${r.name}${r.org ? ` (${r.org})` : ''}`;
  $('#rd-sub').textContent =
    `${int(total)} review comments in ${rangeLabel(range)}` +
    (nClassified
      ? `; ${int(addressed)} addressed in the ${nClassified === weeks.length ? '' : `${nClassified} classified `}` +
        `week${nClassified === 1 ? '' : 's'}${nClassified === weeks.length ? ' shown' : ''} (the filled bars). `
      : '. No week in this range is classified yet, so only review comments are shown. ') +
    'Comments that led to no change aren\'t a bad sign: questions are part of good review.';
  const color = (r.org && colors.get(r.org)) || theme.series[0];
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
  if (!counts || !total) {
    $('#threads-sub').textContent = `No week in ${rangeLabel(range)} is classified yet.`;
    bar.replaceChildren();
    legend.replaceChildren();
    $('#threads-examples').replaceChildren();
    return;
  }
  const span = weeks.length === 1 ? weeks[0] : `${weeks.length} classified weeks, ${weeks[0]} to ${weeks[weeks.length - 1]}`;
  $('#threads-sub').textContent =
    `The ${int(total)} review threads started by reviewers (not the CL owner) on the counted paths in ${span}, ` +
    'by how each was decided. Addressed threads give a point to every comment in them that isn\'t the owner\'s; ' +
    'the others give none.';
  const outcomes = [...counts.keys()].filter((o) => counts.get(o)! > 0);
  bar.replaceChildren(
    ...outcomes.map((o) => {
      const seg = el('span', undefined, `tb-seg tb-${o}`);
      seg.style.width = `${(counts.get(o)! / total) * 100}%`;
      seg.title = `${THREAD_OUTCOME_LABELS[o]}: ${int(counts.get(o)!)} (${pct(counts.get(o)! / total)})`;
      return seg;
    }),
  );
  bar.setAttribute('aria-label', outcomes.map((o) => `${THREAD_OUTCOME_LABELS[o]}: ${pct(counts.get(o)! / total)}`).join('; '));
  legend.replaceChildren(
    ...outcomes.map((o) => {
      const li = el('li');
      li.dataset.outcome = o;
      li.append(el('span', undefined, `tb-swatch tb-${o}`), el('span', THREAD_OUTCOME_LABELS[o]),
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
      det.append(el('summary', `Example threads: ${THREAD_OUTCOME_LABELS[o]}`));
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
            if (!list.length) det.append(el('p', 'No examples for these weeks.', 'tb-msg'));
            for (const t of list) det.append(exampleThread(t));
          })
          .catch((err: unknown) => det.append(el('p', `Couldn't load examples: ${String(err)}`, 'tb-msg')));
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
  head.append(a, document.createTextNode(` · ${t.path === '/PATCHSET_LEVEL' ? 'patchset-level comment' : t.path} · ${t.week}`));
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
  const orgs = topDirOrgs(data.areas, weeks, state.metric, 7);
  const totals = dirTotals(data.areas, weeks, orgs, state.metric);
  const unit = metricName(state.metric).toLowerCase();
  const segColors = reviewColors(orgs, colors, theme);
  const { roots } = dirTree(data.areas);
  const total = roots.reduce((s, r) => s + totals.total[r], 0);
  const inScope = roots.filter((r) => data.areas.nodes[r][2]).reduce((s, r) => s + totals.total[r], 0);
  const what = {
    addressed: 'Addressed review comments (in threads that led to a change)',
    comments: 'Every review comment',
    chars: 'Review characters, from every comment',
    cls: 'CLs closed with review comments',
  }[state.metric];
  $('#areas-sub').textContent = total
    ? `${what} in ${rangeLabel(state.range)}, by the directory of the file each comment is on: the ${unit} per ` +
      `directory, and how they split across organizations. ${pct(inScope / total)} of them ` +
      `(${int(inScope)} of ${int(total)}) are on the paths the rest of the page counts; the hatched part of a ` +
      'bar is left out. Use ▸ to open a directory, or a “more” row for the next entries; ▾ closes it again.' +
      (state.metric === 'cls' ? ' A CL with comments in two directories counts in each.' : '')
    : `No review data for ${rangeLabel(state.range)}.`;
  const legend = [...orgs.map((org) => ({ org, color: segColors.get(org) ?? '' })), { org: OTHER, color: '' }];
  $('#areas-legend').replaceChildren(
    ...legend.map(({ org, color }) => {
      const li = el('li');
      const sw = el('span', undefined, color ? 'swatch' : 'swatch swatch-muted');
      if (color) sw.style.background = color;
      li.append(sw, document.createTextNode(org));
      return li;
    }),
  );
  const box = $('#area-chart');
  const who = data.areaReviewers && dirReviewerIndex(data.areas, data.areaReviewers, weeks, orgs);
  const linkOf = (row: DirRow, org: string) => (who ? dirRowLink(data.areas, who, row, org, state.range) : null);
  const draw = (focusKey?: string) => {
    const rows = dirRows(data.areas, totals, state.expandedDirs);
    buildAreaChart(box, rows, orgs, (org) => segColors.get(org), metricName(state.metric), (key) => {
      if (state.expandedDirs.has(key)) state.expandedDirs.delete(key);
      else state.expandedDirs.add(key);
      draw(key);
    }, linkOf);
    // Rebuilding the rows drops focus; give it back to the toggle just used.
    if (focusKey) box.querySelector<HTMLButtonElement>(`li[data-key="${CSS.escape(focusKey)}"] .ar-toggle`)?.focus();
  };
  draw();
}

/** What the organization chart counts when it shows one directory. */
function dirScopeNote(board: DirBoard, node: number, weeks: string[], metric: Metric): string {
  const t = dirTotals(board, weeks, [], metric);
  const inc = t.total[node] ? t.inc[node] / t.total[node] : board.nodes[node][2];
  const scope =
    inc >= 1
      ? 'It counts every comment in this directory and below.'
      : inc <= 0
        ? 'This directory is outside the paths the rest of the page counts; the chart shows every comment in it anyway.'
        : `It counts every comment in this directory and below, including the ${pct(1 - inc)} on paths the rest of the page leaves out.`;
  return scope + (metric === 'cls' ? ' A CL with comments in two of its subdirectories counts in each.' : '');
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
  const name = metricName(state.metric);
  const unit = name.toLowerCase();
  const weeks = weeksIn(Object.keys(data.reviewers.weeks), state.range);
  // Who counts: for addressed comments, everyone who wrote a review comment
  // (0 addressed is telling); for the other metrics, those with some of it.
  const all = reviewerTotals(data.reviewers, weeks, state.metric).filter((r) =>
    state.metric === 'addressed' ? r.comments > 0 : r.value > 0,
  );
  const spreads = orgSpreads(all, data.reviewers.meta.fold_into_other ?? []);
  const orgColors = reviewColors(spreads.map((s) => s.org).filter((o) => o !== OTHER), colors, theme);
  const colorOf = (org: string) => orgColors.get(org) ?? theme.muted;

  $('#dist-sub').textContent = weeks.length
    ? `Each reviewer's ${unit} over ${rangeLabel(state.range)}: one dot per reviewer, one row per organization ` +
      '(the ten with the most, then everyone else, including personal addresses, as “Other”), on a log scale. ' +
      "Each box spans the middle half of its row's reviewers, with a thick line at the median; rows with under five " +
      'reviewers get none. ' +
      (state.metric === 'addressed'
        ? 'Everyone with a review comment in the range counts, so reviewers with none addressed sit at 0. '
        : `Reviewers with no ${unit} in the range are left out. `) +
      'A reviewer counts for the organization most of their comments were for. Hover a dot for the reviewer; ' +
      'click it for their weekly chart.'
    : `No reviewer data for ${rangeLabel(state.range)}.`;

  const fmt = (v: number) => v.toLocaleString('en-US', { maximumFractionDigits: 1 });
  $('#dist-table tbody').replaceChildren(
    ...spreads.map((s) => {
      const tr = el('tr');
      tr.dataset.org = s.org;
      const th = el('th');
      th.scope = 'row';
      const sw = el('span', undefined, s.org === OTHER || !orgColors.has(s.org) ? 'swatch swatch-muted' : 'swatch');
      if (orgColors.has(s.org)) sw.style.background = orgColors.get(s.org)!;
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
  $('#dist-box').style.height = `${Math.max(1, spreads.length) * 34 + 64}px`;
  distChart?.destroy();
  distChart = renderSpreadChart(
    $<HTMLCanvasElement>('#dist-chart'),
    spreads,
    colorOf,
    (id) => reviewerHandle(data.reviewers, id),
    name,
    theme,
    state.lbReviewer,
    (id) => {
      state.lbReviewer = id;
      render();
      $('#reviewer-detail').scrollIntoView({ block: 'nearest' });
    },
  );
}

/** Organizations the heatmap's selector lists, busiest first. */
const HEAT_ORG_CHOICES = 25;
/** Reviewers a heatmap cell's hover text names. */
const HEAT_TOP_REVIEWERS = 3;

/** Review by directory over time: the heatmap, its organization choices and legend. */
function renderHeat(data: Data, state: State, colors: Map<string, string>, theme: Theme, render: () => void) {
  const board = data.areas;
  const rangeWeeks = weeksIn(Object.keys(board.weeks), state.range);
  const unit = metricName(state.metric).toLowerCase();

  // The selector: the busiest orgs over the range, plus the current choice.
  const single = state.heatOrg.startsWith('*') ? null : state.heatOrg;
  const ranked = topDirOrgs(board, rangeWeeks, state.metric, HEAT_ORG_CHOICES);
  if (single && !ranked.includes(single)) ranked.push(single);
  const select = $<HTMLSelectElement>('#heat-org');
  select.replaceChildren(
    ...[
      { v: ALL_ORGS, t: 'All organizations' },
      { v: ALL_BUT_GOOGLE, t: `All except ${LINEAR_EXCLUDED_ORG}` },
      ...ranked.map((o) => ({ v: o, t: o })),
    ].map(({ v, t }) => {
      const o = el('option', t);
      o.value = v;
      return o;
    }),
  );
  const noGoogle = state.heatOrg === ALL_BUT_GOOGLE;
  select.value = noGoogle || single ? state.heatOrg : ALL_ORGS;

  const keep = noGoogle ? (o: string) => o !== LINEAR_EXCLUDED_ORG : undefined;
  const segOrgs = single
    ? [single]
    : topDirOrgs(board, rangeWeeks, state.metric, 8).filter((o) => !keep || keep(o)).slice(0, 7);
  const segColors = reviewColors(segOrgs, colors, theme);
  const grid = heatGrid(board, state.range, state.heatBin, state.metric, segOrgs, state.heatExpanded, {
    only: keep,
    rankOnly: single ? (o) => o === single : keep,
  });
  const { paths } = dirTree(board);
  const binTitle = (b: WeekRange) => (b.from === b.to ? b.from : `${b.from} to ${b.to}`) + ` (${rangeDates(b)})`;
  const rowTitle = (r: DirRow) => (r.node !== undefined && r.kind === 'dir' ? paths[r.node] : r.title);

  // Links and the "most active" line come from the reviewer file, once loaded.
  let cellInfo: ((row: number, bin: number) => HeatCellInfo | null) | undefined;
  if (data.areaReviewers) {
    // An excluded org gets its own segment, so it can be dropped rather than hide in Other.
    const idxOrgs = noGoogle ? [...segOrgs, LINEAR_EXCLUDED_ORG] : segOrgs;
    const perBin = grid.binWeeks.map((w) => dirReviewerIndex(board, data.areaReviewers!, w, idxOrgs));
    const keepSeg = single ? (o: string) => o === single : keep;
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

  const orgColor = single ? segColors.get(single) ?? theme.series[0] : undefined;
  buildHeatmap($('#heat-chart'), {
    grid,
    org: single,
    value: state.heatValue,
    orgs: segOrgs,
    colorOf: (o) => segColors.get(o),
    orgColor,
    metricLabel: metricName(state.metric),
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
  $('#heat-sub').textContent = rangeWeeks.length
    ? `${metricName(state.metric)} from the chosen organizations, ${rangeLabel(state.range)}: one row per directory, ` +
      'ranked over the range, and one column per week or group of weeks, the last ending with the range. ' +
      `With several organizations, each cell splits the directory's ${unit} in those weeks across them: ` +
      "under Volume it is a column whose height is against the row's busiest column; under Share it fills the cell. " +
      `With one organization, each cell is shaded by that organization's ${unit} there, against the busiest cell on a ` +
      `square-root scale so smaller directories still show (Volume), or by its share of the directory's ${unit} (Share). ` +
      'Every comment counts, on the selected paths or not, as in Review by directory. Use ▸ to open a directory and ' +
      '“chart” to show it in the organization chart. Hover a cell for its numbers and most active reviewers, or click ' +
      'it to open those CLs on Gerrit.' +
      (state.metric === 'cls' ? ' A CL with comments in two directories counts in each.' : '')
    : `No review data for ${rangeLabel(state.range)}.`;

  const legend = $('#heat-legend');
  if (single) {
    const share = state.heatValue === 'share';
    const li = el('li');
    const ramp = el('span', undefined, 'hm-ramp');
    ramp.style.background = `linear-gradient(to right, ${heatShade(orgColor!, 0)}, ${heatShade(orgColor!, 1)})`;
    li.append(
      document.createTextNode(share ? '0%' : '1'),
      ramp,
      document.createTextNode(share ? `100% of the directory's ${unit}` : `${int(heatMax(grid, single))} ${unit}`),
    );
    legend.replaceChildren(li);
  } else {
    legend.replaceChildren(
      ...[...segOrgs.map((org) => ({ org, color: segColors.get(org) ?? '' })), { org: OTHER, color: '' }].map(
        ({ org, color }) => {
          const li = el('li');
          const sw = el('span', undefined, color ? 'swatch' : 'swatch swatch-muted');
          if (color) sw.style.background = color;
          li.append(sw, document.createTextNode(org));
          return li;
        },
      ),
    );
  }
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
  let usageChart: AnyChart | undefined;
  const browsers = topBrowsers(data.radar);
  const jumpWeek = derivativeJumpWeek(data.radar);
  let syncInputs = () => {};

  const colorsFor = (theme: Theme) => new Map(orgs.map((o, i) => [o, theme.series[i]]));

  const render = () => {
    writeStateToUrl(state);
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
    const label = rangeLabel(state.range);
    // Smooth over every week before filtering, so the range's first weeks
    // average over earlier data too.
    // Addressed comments exist only for classified weeks; the running
    // averages skip the others instead of reading them as zero.
    const dataWeeks = state.metric === 'addressed' ? addressedWeeks(data.summary) : undefined;
    const points = smoothRatios(
      computeRatios(data.summary, data.radar, data.orgBrowsers, state.metric, undefined, dataWeeks),
      state.smoothing,
    ).filter(
      (p) => orgs.includes(p.org) && weeks.includes(p.week),
    );

    ratioChart?.destroy();
    ratioChart = renderRatioChart($<HTMLCanvasElement>('#ratio-chart'), weeks, orgs, colors, points, theme, state.smoothing);
    const name = metricName(state.metric);
    const metricLabel = name.toLowerCase();
    reviewChart?.destroy();
    const linear = state.reviewScale === 'linear';
    // One directory (every comment in it, from the directory data), or the path scope (org_weekly).
    const dirNode = state.reviewDir === null ? null : dirNodeByPath(data.areas, state.reviewDir);
    const seriesFor = (lin: boolean) => {
      const exclude = lin ? [LINEAR_EXCLUDED_ORG] : [];
      return dirNode === null
        ? orgWeeklyCounts(data.summary, weeks, state.metric, 7, state.smoothing, exclude, dataWeeks)
        : dirWeeklyCounts(data.areas, dirNode, weeks, state.metric, 7, state.smoothing, exclude, dataWeeks);
    };
    const reviewSeries = seriesFor(linear);
    reviewChart = renderReviewChart(
      $<HTMLCanvasElement>('#review-chart'),
      weeks,
      reviewSeries,
      name,
      // Colour the union of both scales' orgs (log ranking first), whichever
      // scale is shown, so an org keeps its colour when the scale toggles:
      // the org taking google.com's place in the linear view can rank above
      // others, or hold a fixed colour that would shrink the spare pool.
      reviewColors(
        [
          ...new Set(
            [false, true].flatMap((lin) => (lin === linear ? reviewSeries : seriesFor(lin)).map((s) => s.org)),
          ),
        ],
        colors,
        theme,
      ),
      theme,
      state.smoothing,
      state.reviewScale,
    );
    $('#review-sub').textContent = weeks.length
      ? `${name} per ISO week, ${label}` +
        (state.smoothing > 1
          ? `, as a ${state.smoothing}-week running average`
          : '') +
        ', for the organizations with the most over the range; the rest are combined as “Other”. ' +
        'The log scale shows every organization, since Google does most of the review; the linear scale leaves out ' +
        `${LINEAR_EXCLUDED_ORG}, so the other organizations can be compared directly. With no directory chosen it ` +
        'counts comments on the selected paths; with one, every comment in that directory and below.'
      : `No review data for ${label}.`;
    // The chosen directory's note sits below the controls, so it can't move them.
    const dirNote = $('#review-dir-note');
    dirNote.hidden = dirNode === null || !weeks.length;
    dirNote.textContent =
      dirNode === null ? '' : `Showing ${state.reviewDir}. ` + dirScopeNote(data.areas, dirNode, weeks, state.metric);
    const dirInput = $<HTMLInputElement>('#review-dir');
    if (document.activeElement !== dirInput) dirInput.value = state.reviewDir ?? '';
    $('#review-dir-clear').hidden = state.reviewDir === null;
    renderHeat(data, state, colors, theme, render);
    renderAreas(data, state, colors, theme);
    renderDistribution(data, state, colors, theme, render);
    renderLeaderboard(data, state, colors, theme, render);
    renderThreads(data, state);
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
    window.__cosh = { data, state, ratioChart, reviewChart, usageChart, distChart, render };
  };

  // The classifier explainer matters only once some week is classified.
  $('#addressed-details').hidden = !availableMetrics(data).some((m) => m.id === 'addressed');
  // The intro's link opens the explainer in place. The URL hash holds the
  // page state, so the link must not replace it.
  $('#addressed-link').addEventListener('click', (e) => {
    const details = $<HTMLDetailsElement>('#addressed-details');
    if (details.hidden) return;
    e.preventDefault();
    details.open = true;
    details.scrollIntoView({ block: 'start' });
  });
  syncInputs = buildControls(data, state, render);
  render();
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', render);
  const weeks = data.summary.meta.weeks;
  $('#coverage').textContent =
    `Review data: ${weeks.length} week${weeks.length === 1 ? '' : 's'} (${weeks[0]}${weeks.length > 1 ? `–${weeks[weeks.length - 1]}` : ''}). ` +
    `Usage data: Cloudflare Radar, ${[...data.radar.keys()].sort()[0]} onward.`;
  document.body.dataset.ready = 'true';
  // The directory chart's Gerrit links need a file larger than the chart's
  // own data, so it's fetched only when the chart comes near the viewport.
  // Until it arrives (or if it fails) the segments aren't links.
  const loadLinks = () =>
    fetchText(areaReviewersUrl)
      .then((t) => {
        data.areaReviewers = JSON.parse(t) as DirReviewers;
        // The file often arrives just after a toggle in one of these charts
        // was pressed (pressing it scrolls the chart into view). Rebuilding
        // the rows drops focus, so give it back to that toggle.
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
  if (!('IntersectionObserver' in window)) loadLinks();
  else {
    const seen = new IntersectionObserver(
      (entries) => {
        if (!entries.some((e) => e.isIntersecting)) return;
        seen.disconnect();
        loadLinks();
      },
      { rootMargin: '400px' },
    );
    seen.observe($('#area-chart'));
    seen.observe($('#heat-chart'));
  }
}

load()
  .then(main)
  .catch((err: unknown) => {
    console.error(err);
    $('#error').hidden = false;
    $('#error').textContent = `Couldn't load data: ${err instanceof Error ? err.message : String(err)}`;
    document.body.dataset.ready = 'error';
  });
