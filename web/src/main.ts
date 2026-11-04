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

import {
  type AnyChart,
  readTheme,
  renderRatioChart,
  renderReviewChart,
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
}

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
  const lbn = Number(q.get('lbn'));
  const lbSize = LEADERBOARD_SIZES.find((n) => n === lbn) ?? LEADERBOARD_SIZE;
  const lbGoogle = q.get('lbg') !== '0';
  const dir = q.get('dir');
  const dirNode = dir ? dirNodeByPath(data.areas, dir) : null;
  const hmb = Number(q.get('hmb'));
  return {
    metric,
    range: clampRange({ from, to }, full),
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
    (s.heatValue !== 'volume' ? '&hmv=share' : ''));
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
): void {
  const name = metricName(state.metric);
  const weeks = weeksIn(Object.keys(data.reviewers.weeks), state.range);
  const excluded = state.lbGoogle ? undefined : LINEAR_EXCLUDED_ORG;
  const rows = topReviewers(data.reviewers, weeks, state.metric, state.lbSize, excluded);
  const outside = excluded ? ` outside ${excluded}` : '';
  $('#leaderboard-sub').textContent = !rows.length
    ? `No reviewer data${outside} for ${rangeLabel(state.range)}.`
    : `${name}${weeks.length > 1 ? ' in total' : ''}, ${rangeLabel(state.range)}, ` +
      `top ${rows.length} reviewers${outside}. ` +
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
  buildLeaderboard($('#leaderboard-chart'), rows, name, (org) => lbColors.get(org), state.range);
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
    const nameOf = (id: number) => data.reviewers.accounts[String(id)] ?? `account ${id}`;
    cellInfo = (ri, bi) => {
      const idx = perBin[bi];
      const row = grid.rows[ri];
      const who = idx ? rowReviewers(idx, row, keepSeg) : undefined;
      if (!who?.comments.size || row.node === undefined) return null;
      const top = topAccounts(who.comments, HEAT_TOP_REVIEWERS).map(([id, n]) => {
        const org = who.org.get(id);
        return { name: single || !org || org === OTHER ? nameOf(id) : `${nameOf(id)}, ${org}`, comments: n };
      });
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

  const bins = grid.bins.length;
  const width = state.heatBin === 1 ? 'a week' : `${state.heatBin} weeks`;
  const who = single ?? (noGoogle ? `every organization but ${LINEAR_EXCLUDED_ORG}` : 'every organization');
  const how = single
    ? state.heatValue === 'share'
      ? `Each cell is shaded by ${single}'s share of the ${unit} in that directory in those weeks.`
      : `Each cell is shaded by ${single}'s ${unit} there, against the busiest cell, on a square-root scale so smaller directories still show.`
    : state.heatValue === 'share'
      ? `Each cell splits the directory's ${unit} in those weeks across organizations.`
      : `Each cell is a column of the directory's ${unit} in those weeks, split across organizations; its height is against the row's busiest column.`;
  $('#heat-sub').textContent = grid.rows.length
    ? `${metricName(state.metric)} from ${who}, ${rangeLabel(state.range)}: one row per directory, ranked over the range, ` +
      `and ${bins} column${bins === 1 ? '' : 's'} of ${width}, the last ending with the range. ${how} ` +
      'Every comment counts, on the selected paths or not, as in Review by directory. Use ▸ to open a directory and ' +
      '“chart” to show it in the organization chart. Hover a cell for its numbers and most active reviewers, or click ' +
      'it to open those CLs on Gerrit.' +
      (state.metric === 'cls' ? ' A CL with comments in two directories counts in each.' : '')
    : `No review data${single ? ` from ${single}` : ''} for ${rangeLabel(state.range)}.`;

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
    const theme = readTheme();
    const colors = colorsFor(theme);
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
    const name = metricName(state.metric);
    const metricLabel = name.toLowerCase();
    reviewChart?.destroy();
    const linear = state.reviewScale === 'linear';
    // One directory (every comment in it, from the directory data), or the path scope (org_weekly).
    const dirNode = state.reviewDir === null ? null : dirNodeByPath(data.areas, state.reviewDir);
    const seriesFor = (lin: boolean) => {
      const exclude = lin ? [LINEAR_EXCLUDED_ORG] : [];
      return dirNode === null
        ? orgWeeklyCounts(data.summary, weeks, state.metric, 7, state.smoothing, exclude)
        : dirWeeklyCounts(data.areas, dirNode, weeks, state.metric, 7, state.smoothing, exclude);
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
        (dirNode === null ? '' : ` in ${state.reviewDir}`) +
        ', for the organizations with the most over the range; the rest are combined as “Other”. ' +
        (linear
          ? `${LINEAR_EXCLUDED_ORG} is left out and the axis is linear, so the other organizations can be compared directly.`
          : 'The axis is logarithmic, since Google does most of the review.') +
        (dirNode === null ? '' : ' ' + dirScopeNote(data.areas, dirNode, weeks, state.metric))
      : `No review data for ${label}.`;
    const dirInput = $<HTMLInputElement>('#review-dir');
    if (document.activeElement !== dirInput) dirInput.value = state.reviewDir ?? '';
    $('#review-dir-clear').hidden = state.reviewDir === null;
    renderHeat(data, state, colors, theme, render);
    renderAreas(data, state, colors, theme);
    renderLeaderboard(data, state, colors, theme);
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
    window.__cosh = { data, state, ratioChart, reviewChart, usageChart, render };
  };

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
        renderAreas(data, state, colorsFor(theme), theme);
        renderHeat(data, state, colorsFor(theme), theme, render);
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
