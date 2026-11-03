import './style.css';
// Data files are referenced from the repo, not copied: Vite emits them as
// hashed assets at build time, so the site always reads the committed data.
import summaryUrl from '../../summaries/org_weekly.json?url';
import totalsUrl from '../../summaries/weekly_totals.csv?url';
import radarUrl from '../../data/public/radar_browser_share.csv?url';
import orgBrowsersUrl from '../../config/org_browsers.csv?url';

import { type AnyChart, readTheme, renderRatioChart, renderReviewChart, renderUsageChart } from './charts.ts';
import {
  chartedOrgs,
  compareWeeks,
  computeRatios,
  derivedShare,
  METRICS,
  metricColumn,
  MIN_DERIVED_SHARE,
  parseOrgBrowsers,
  parseRadarWeekly,
  parseWeeklyTotals,
  topBrowsers,
  topOrgCounts,
  type Metric,
  type RadarWeekly,
  type Summary,
  type WeeklyTotals,
} from './data.ts';
import { formatRatio, pivotScale } from './scale.ts';

interface Data {
  summary: Summary;
  totals: WeeklyTotals[];
  radar: RadarWeekly;
  orgBrowsers: Map<string, string[]>;
}

interface State {
  metric: Metric;
  week: string;
}

declare global {
  interface Window {
    __cosh?: { data: Data; state: State; ratioChart?: AnyChart; reviewChart?: AnyChart; usageChart?: AnyChart; render: () => void };
  }
}

const $ = <T extends HTMLElement>(sel: string) => document.querySelector<T>(sel)!;

async function fetchText(url: string): Promise<string> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url}: HTTP ${res.status}`);
  return res.text();
}

async function load(): Promise<Data> {
  const [summary, totals, radar, orgBrowsers] = await Promise.all([
    fetchText(summaryUrl).then((t) => JSON.parse(t) as Summary),
    fetchText(totalsUrl).then(parseWeeklyTotals),
    fetchText(radarUrl).then(parseRadarWeekly),
    fetchText(orgBrowsersUrl).then(parseOrgBrowsers),
  ]);
  summary.meta.weeks.sort(compareWeeks);
  return { summary, totals, radar, orgBrowsers };
}

const pct = (x: number) => `${(x * 100).toFixed(x !== 0 && x < 0.01 ? 2 : 1)}%`;
const int = (x: number) => x.toLocaleString('en-US');

function el<K extends keyof HTMLElementTagNameMap>(tag: K, text?: string, cls?: string) {
  const e = document.createElement(tag);
  if (text !== undefined) e.textContent = text;
  if (cls) e.className = cls;
  return e;
}

function readStateFromUrl(data: Data): State {
  const q = new URLSearchParams(location.hash.slice(1));
  const weeks = data.summary.meta.weeks;
  const metric = METRICS.some((m) => m.id === q.get('metric')) ? (q.get('metric') as Metric) : 'comments';
  const week = weeks.includes(q.get('week') ?? '') ? q.get('week')! : weeks[weeks.length - 1];
  return { metric, week };
}

function writeStateToUrl(s: State) {
  history.replaceState(null, '', `#metric=${s.metric}&week=${s.week}`);
}

function buildControls(data: Data, state: State, render: () => void) {
  const metricBox = $('#metric');
  metricBox.replaceChildren();
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

  const weekSel = $<HTMLSelectElement>('#week');
  weekSel.replaceChildren(...[...data.summary.meta.weeks].reverse().map((w) => new Option(w, w)));
  weekSel.value = state.week;
  weekSel.onchange = () => {
    state.week = weekSel.value;
    render();
  };
}

function renderTiles(data: Data, state: State) {
  const t = data.totals.find((r) => r.iso_week === state.week);
  const rows = data.summary.rows.filter((r) => r.iso_week === state.week);
  const human = rows.reduce((s, r) => s + r.comments, 0);
  const ai = rows.reduce((s, r) => s + r.ai_comments, 0);
  const postMerge = rows.reduce((s, r) => s + (r.post_merge_comments ?? 0), 0);
  const tiles: [string, string, string][] = [
    ['CLs on main', t ? int(t.main_cls) : '—', t ? `${int(t.merged_cls)} merged, ${int(t.abandoned_cls)} abandoned` : ''],
    ['Human-owned CLs', t ? int(t.human_cls) : '—', t ? `${int(t.human_cls_with_review)} reviewed; ${int(t.bot_cls)} bot CLs` : ''],
    ['Review comments', int(human), `by ${int(rows.reduce((s, r) => s + r.reviewers, 0))} reviewers`],
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

function renderTable(data: Data, state: State, colors: Map<string, string>) {
  const col = metricColumn(state.metric);
  const rows = data.summary.rows.filter((r) => r.iso_week === state.week);
  const orgs = new Set([...rows.map((r) => r.org), ...data.orgBrowsers.keys()]);
  const items = [...orgs].map((org) => {
    const row = rows.find((r) => r.org === org);
    const browsers = data.orgBrowsers.get(org);
    const contribution = row ? Number(row[col]) : 0;
    const derived = browsers ? derivedShare(data.radar, state.week, browsers) : null;
    const ratio = derived !== null && derived >= MIN_DERIVED_SHARE ? contribution / derived : null;
    return { org, row, browsers, contribution, derived, ratio };
  });
  items.sort((a, b) => b.contribution - a.contribution || (b.derived ?? 0) - (a.derived ?? 0));

  const metricLabel = METRICS.find((m) => m.id === state.metric)!.label.toLowerCase();
  $('#table-caption').textContent = `${state.week}: share of ${metricLabel} and of Chromium browser usage`;
  const tbody = $('#org-table tbody');
  tbody.replaceChildren(
    ...items.map((it) => {
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
          : !it.browsers
            ? 'no browser'
            : it.derived === null
              ? 'no usage data'
              : 'usage too small';
      const cells = [
        pct(it.contribution),
        it.browsers ? (it.derived === null ? '—' : pct(it.derived)) : '—',
        ratioText,
        it.row ? int(it.row.reviewers) : '<5',
        it.row ? int(it.row.comments) : '—',
        it.row ? int(it.row.ai_comments) : '—',
        it.row && it.row.post_merge_comments !== undefined ? int(it.row.post_merge_comments) : '—',
      ];
      tr.append(orgCell, ...cells.map((c, i) => el('td', c, i === 2 ? 'ratio' : undefined)));
      return tr;
    }),
  );
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

  const render = () => {
    writeStateToUrl(state);
    const theme = readTheme();
    const colors = new Map(orgs.map((o, i) => [o, theme.series[i]]));
    const weeks = data.summary.meta.weeks;
    const points = computeRatios(data.summary, data.radar, data.orgBrowsers, state.metric).filter((p) =>
      orgs.includes(p.org),
    );
    const scale = pivotScale(Math.max(...points.map((p) => p.ratio ?? 0)));

    ratioChart?.destroy();
    ratioChart = renderRatioChart($<HTMLCanvasElement>('#ratio-chart'), weeks, orgs, colors, points, scale, theme);
    const metricName = METRICS.find((m) => m.id === state.metric)!.label;
    const metricLabel = metricName.toLowerCase();
    reviewChart?.destroy();
    reviewChart = renderReviewChart(
      $<HTMLCanvasElement>('#review-chart'),
      topOrgCounts(data.summary, state.week, state.metric),
      metricName,
      theme,
    );
    $('#review-sub').textContent = `${metricName} in ${state.week}, top organizations; the rest are combined as “Other”.`;
    usageChart?.destroy();
    usageChart = renderUsageChart(
      $<HTMLCanvasElement>('#usage-chart'),
      data.radar,
      browsers,
      jumpWeek ? { week: jumpWeek, text: 'ChromeDerivative jump' } : null,
      theme,
    );

    $('#ratio-sub').textContent =
      `Share of ${metricLabel} ÷ share of Chromium browser usage, per ISO week. ` +
      `Parity (1×) is the middle line: the lower half runs linearly 0–1×, the upper half 1–${formatRatio(scale.upper)}×.`;
    renderTiles(data, state);
    renderTable(data, state, colors);
    window.__cosh = { data, state, ratioChart, reviewChart, usageChart, render };
  };

  buildControls(data, state, render);
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
