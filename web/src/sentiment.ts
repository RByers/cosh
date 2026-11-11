// The Review Tone page (sentiment.html). Wording is in the HTML; this fills
// in values and draws the charts. Comment text is untrusted and goes into
// the DOM only as text (SECURITY.md). Ground rule 5: names and links only
// for praise. The sticky bar's "Dates" (all, a calendar year or a calendar
// month) and "Comments by" switches apply to every section; each "Comments
// by" choice has its own set of summary files, each with every period in it.
// An open name popup is in the URL's hash (#given=<email>, …), so it can be
// shared.
import { Chart, Filler, type ChartDataset } from 'chart.js';
import monthlyUrl from '../../summaries/sentiment_monthly.json?url';
import praiseUrl from '../../summaries/sentiment_praise.json?url';
import samplesUrl from '../../summaries/sentiment_samples.json?url';
import recentUrl from '../../summaries/sentiment_recent.json?url';
import monthlyEveryoneUrl from '../../summaries/sentiment_monthly.everyone.json?url';
import praiseEveryoneUrl from '../../summaries/sentiment_praise.everyone.json?url';
import samplesEveryoneUrl from '../../summaries/sentiment_samples.everyone.json?url';
import recentEveryoneUrl from '../../summaries/sentiment_recent.everyone.json?url';
import monthlyOthersUrl from '../../summaries/sentiment_monthly.noncommitters.json?url';
import praiseOthersUrl from '../../summaries/sentiment_praise.noncommitters.json?url';
import samplesOthersUrl from '../../summaries/sentiment_samples.noncommitters.json?url';
import recentOthersUrl from '../../summaries/sentiment_recent.noncommitters.json?url';
import lookupUrl from '../../summaries/sentiment_people.json?url';
import commentsUrl from '../../summaries/sentiment_comments.json?url';
import commentsEveryoneUrl from '../../summaries/sentiment_comments.everyone.json?url';
import commentsOthersUrl from '../../summaries/sentiment_comments.noncommitters.json?url';
import promptText from '../../scripts/sentiment_prompts/v3.txt?raw';
import { readTheme, type Theme } from './charts.ts';
import { fmtInt, fmtNum } from './format.ts';
import { fill, fragment, msg } from './text.ts';
import {
  AUTHORS,
  dayLabel,
  gerritLink,
  monthLabel,
  periodWeeks,
  periodKind,
  periodsOf,
  netBoard,
  praisePeople,
  praiseTotal,
  weeksBetween,
  type Authors,
  allPraise,
  findPerson,
  suggestPeople,
  happyComments,
  boardRank,
  byMonth,
  relation,
  praiseComments,
  type HappyRow,
  type PersonComment,
  type PersonComments,
  type Period,
  type PraiseData,
  type RecentPeriod,
  type TonePoint,
  type ToneRecent,
  type ToneSamples,
  type ToneTrend,
} from './tone.ts';

Chart.register(Filler);

const URLS: Record<Authors, { monthly: string; praise: string; samples: string; recent: string; comments: string }> = {
  committers: { monthly: monthlyUrl, praise: praiseUrl, samples: samplesUrl, recent: recentUrl, comments: commentsUrl },
  everyone: { monthly: monthlyEveryoneUrl, praise: praiseEveryoneUrl, samples: samplesEveryoneUrl, recent: recentEveryoneUrl,
    comments: commentsEveryoneUrl },
  noncommitters: { monthly: monthlyOthersUrl, praise: praiseOthersUrl, samples: samplesOthersUrl, recent: recentOthersUrl,
    comments: commentsOthersUrl },
};

/** The writers chosen now, and their popup comments once loaded. */
let shown: Authors = 'committers';
/** The dates chosen now: "all", a year ("2026") or a month ("2026-10"). */
let period: Period = 'all';
const commentCache = new Map<Authors, Promise<PersonComments>>();
const personComments = (a: Authors) => {
  let p = commentCache.get(a);
  if (!p) {
    p = getJson<PersonComments>(URLS[a].comments);
    p.catch(() => commentCache.delete(a));
    commentCache.set(a, p);
  }
  return p;
};

declare global {
  interface Window {
    __tone?: Record<string, Chart>;
  }
}

/** The charts drawn for the current choice, destroyed before redrawing. */
let charts: Chart[] = [];

const $ = <T extends Element = HTMLElement>(sel: string) => document.querySelector<T>(sel)!;

async function getJson<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return (await r.json()) as T;
}

/** A colour with alpha, for the 95% bands. */
const faint = (hex: string) => (/^#[0-9a-f]{6}$/i.test(hex) ? hex + '2e' : hex);

const signed = (v: number) =>
  (v > 0 ? '+' : v < 0 ? '−' : '') + fmtNum(Math.abs(v), { minimumFractionDigits: 3, maximumFractionDigits: 3 });
const pct = (v: number) => fmtNum(v, { style: 'percent', minimumFractionDigits: 1, maximumFractionDigits: 1 });
const pct2 = (v: number) => fmtNum(v, { style: 'percent', minimumFractionDigits: 2, maximumFractionDigits: 2 });

function el<K extends keyof HTMLElementTagNameMap>(tag: K, text?: string, cls?: string): HTMLElementTagNameMap[K] {
  const e = document.createElement(tag);
  if (text !== undefined) e.textContent = text;
  if (cls) e.className = cls;
  return e;
}

/** The checked value of a radio group, and a call on every change. */
function radio<T extends string>(name: string, onChange: () => void): () => T {
  for (const i of document.querySelectorAll<HTMLInputElement>(`input[name="${name}"]`)) i.addEventListener('change', onChange);
  return () => document.querySelector<HTMLInputElement>(`input[name="${name}"]:checked`)!.value as T;
}

// ---- trend

interface Series {
  label: string;
  color: string;
  v: (p: TonePoint) => number;
  ci: (p: TonePoint) => [number, number];
}

/** A grey line on a right-hand axis, alongside the banded series. */
interface Extra {
  label: string;
  data: number[];
  /** The tooltip line for month `i`. */
  tip: (i: number) => string;
}

/** A line per series with its 95% band, over `months`; the month at index
 * `mark` (the month chosen on the page) gets a dot. `extra` adds a grey line
 * on a right-hand axis. */
function bandedLine(canvas: HTMLCanvasElement, months: ToneTrend['months'], series: Series[], theme: Theme,
  fmt: (v: number) => string, mark: number, boundary: number, footer: (i: number) => string, extra?: Extra) {
  const datasets: ChartDataset<'line', number[]>[] = [];
  const dots = months.map((_, i) => (i === mark ? 5 : 0));
  for (const s of series) {
    datasets.push(
      { label: s.label, data: months.map((m) => s.v(m.rolling)), borderColor: s.color, backgroundColor: s.color,
        borderWidth: 2, pointRadius: dots, pointHoverRadius: 4, tension: 0, fill: false },
      { label: '', data: months.map((m) => s.ci(m.rolling)[1]), borderWidth: 0, pointRadius: 0, pointHoverRadius: 0,
        backgroundColor: faint(s.color), fill: '+1' },
      { label: '', data: months.map((m) => s.ci(m.rolling)[0]), borderWidth: 0, pointRadius: 0, pointHoverRadius: 0,
        fill: false },
    );
  }
  // A dashed line between the last sampled month and the first complete one.
  const divider = {
    id: 'sample-divider',
    afterDatasetsDraw(chart: Chart) {
      if (boundary <= 0) return;
      const { ctx, chartArea: area, scales: { x } } = chart;
      const px = (x.getPixelForValue(boundary - 1) + x.getPixelForValue(boundary)) / 2;
      ctx.save();
      ctx.strokeStyle = theme.muted;
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(px, area.top);
      ctx.lineTo(px, area.bottom);
      ctx.stroke();
      ctx.restore();
    },
  };
  if (extra) {
    datasets.push({ label: extra.label, data: extra.data, yAxisID: 'y1', borderColor: theme.muted,
      backgroundColor: theme.muted, borderWidth: 1.5, pointRadius: dots, pointHoverRadius: 4, tension: 0, fill: false });
  }
  const y1 = extra ? {
    y1: { position: 'right' as const, beginAtZero: true, grid: { display: false },
      ticks: { color: theme.muted, callback: (v: string | number) => fmtInt(Number(v)), font: { family: theme.font } } },
  } : {};
  charts.push(new Chart(canvas, {
    type: 'line',
    plugins: [divider],
    data: { labels: months.map((m) => monthLabel(m.m)), datasets },
    options: {
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: 'index', intersect: false },
      font: { family: theme.font },
      scales: {
        x: { grid: { color: theme.grid }, ticks: { color: theme.text, maxTicksLimit: 12, font: { family: theme.font } } },
        y: { grid: { color: theme.grid }, ticks: { color: theme.text, callback: (v) => fmt(Number(v)), font: { family: theme.font } } },
        ...y1,
      },
      plugins: {
        legend: {
          display: series.length > 1 || !!extra,
          labels: { color: theme.text, filter: (item) => !!item.text, font: { family: theme.font } },
        },
        tooltip: {
          filter: (item) => !!item.dataset.label,
          callbacks: {
            title: (items) => {
              const m = months[items[0].dataIndex];
              return m.span[0] === m.span[1] ? monthLabel(m.m) : `${monthLabel(m.span[0])} – ${monthLabel(m.span[1])}`;
            },
            label: (item) => {
              if (extra && item.dataset.label === extra.label) return extra.tip(item.dataIndex);
              const s = series.find((x) => x.label === item.dataset.label)!;
              const p = months[item.dataIndex].rolling;
              const [lo, hi] = s.ci(p);
              return `${s.label}: ${fmt(s.v(p))} (95% ${fmt(lo)} to ${fmt(hi)})`;
            },
            footer: (items) => footer(items[0].dataIndex),
          },
        },
      },
    },
  }));
}

/** The trend over the chosen dates: every month, the chosen year's, or the
 * chosen month's year with that month marked. */
function renderTrend(trend: ToneTrend, theme: Theme) {
  const kind = periodKind(period);
  const year = kind === 'all' ? null : period.slice(0, 4);
  let months = year ? trend.months.filter((m) => m.m.startsWith(`${year}-`)) : trend.months;
  if (!months.length) months = trend.months;
  const mark = kind === 'month' ? months.findIndex((m) => m.m === period) : -1;
  const full = months.filter((m) => m.full);
  const sampled = months.filter((m) => !m.full);
  const count = (ms: typeof months) => ms.reduce((s, m) => s + m.month.n, 0);
  const perMonth = (ms: typeof months) => fmtInt(Math.round(count(ms) / Math.max(1, ms.length)));
  const rate = trend.rate ? pct(trend.rate).replace(/\.0%$/, '%') : 'random';
  const boundary = full.length && sampled.length ? months.findIndex((m) => m.full) : -1;
  // The sample's monthly counts scaled up to every comment (20x for a 5% sample);
  // fully scored months are counted as they are.
  const scale = trend.rate ? Math.round(1 / trend.rate) : 20;
  fill($('#trend-sub'), {
    nFull: full.length ? fmtInt(count(full)) : '',
    fullFrom: full.length ? monthLabel(full[0].m) : '',
    fullPerMonth: perMonth(full),
    nSample: sampled.length ? fmtInt(count(sampled)) : '',
    rate,
    sampleMonths: sampled.length,
    perMonth: perMonth(sampled),
    window: trend.window,
    boundary: boundary > 0,
    mark: mark >= 0 ? monthLabel(period) : '',
    scale,
  });
  fill($('#trend-note'), { glowing: trend.thresholds.glowing, angry: Math.abs(trend.thresholds.angry) });
  // Tooltip footer: how many comments the point pools, and whether any were sampled.
  const footer = (i: number) => {
    const m = months[i];
    const inSpan = trend.months.filter((x) => x.m >= m.span[0] && x.m <= m.span[1]);
    const kind = m.rolling.full ? 'full' : inSpan.some((x) => x.full) ? 'mixed' : 'sample';
    return msg(`trend-footer-${kind}`, { n: fmtInt(m.rolling.n), rate });
  };
  bandedLine($<HTMLCanvasElement>('#trend-mean'), months,
    [{ label: 'Average score', color: theme.series[0], v: (p) => p.mean, ci: (p) => [p.lo, p.hi] }], theme, signed, mark,
    boundary, footer, { label: 'Comments', data: months.map((m) => m.month.n * (m.full ? 1 : scale)),
      tip: (i) => months[i].full ? `Comments that month: ${fmtInt(months[i].month.n)}`
        : `Comments that month: about ${fmtInt(months[i].month.n * scale)}` });
  bandedLine($<HTMLCanvasElement>('#trend-shares'), months, [
    { label: 'Glowing', color: theme.series[2], v: (p) => p.glowing, ci: (p) => p.glowing_ci },
    { label: 'Grumpy', color: theme.series[7], v: (p) => p.angry, ci: (p) => p.angry_ci },
    { label: 'AI friction', color: theme.series[6], v: (p) => p.ai, ci: (p) => p.ai_ci },
  ], theme, pct, mark, boundary, footer);
}

// ---- every comment of the chosen dates

function tile(id: string, value: string) {
  $(`#${id} .tile-value`).textContent = value;
}

const EMPTY_STAT = { n: 0, mean: null, glowing: null, angry: null, ai: 0 };

/** The detail for the chosen dates; empty when the file has none for them. */
function recentPeriod(r: ToneRecent): RecentPeriod {
  return r.periods[period] ?? { weeks: r.weeks, n_trivial: 0, total: EMPTY_STAT, dist: [],
    happy: { authors: [], reviewers: [] }, ai: [] };
}

/** The weeks the detail covers for the chosen dates. */
const recentWeeks = (r: ToneRecent) => recentPeriod(r).weeks;

function renderRecent(r: ToneRecent, theme: Theme) {
  const d = recentPeriod(r);
  fill($('#recent-sub'), { range: weeksBetween(d.weeks) });
  const t = d.total;
  tile('tile-n', fmtInt(t.n));
  tile('tile-trivial', fmtInt(d.n_trivial));
  tile('tile-mean', t.mean === null ? '–' : signed(t.mean));
  tile('tile-glowing', t.glowing === null ? '–' : pct2(t.glowing));
  tile('tile-angry', t.angry === null ? '–' : pct2(t.angry));
  tile('tile-ai', fmtInt(t.ai));
  const total = d.dist.reduce((s, [, n]) => s + n, 0) || 1;
  const bins: number[] = [];
  for (let i = -10; i <= 10; i++) bins.push(i / 10);
  const count = new Map(d.dist.map(([b, n]) => [Math.round(b * 10) / 10, n]));
  const colors = bins.map((b) => (b <= r.thresholds.angry ? theme.series[7] : b >= r.thresholds.glowing ? theme.series[2] : theme.baseline));
  charts.push(new Chart($<HTMLCanvasElement>('#recent-dist'), {
    type: 'bar',
    data: {
      labels: bins.map((b) => (b > 0 ? '+' : b < 0 ? '−' : '') + Math.abs(b).toFixed(1)),
      datasets: [{ label: 'Comments', data: bins.map((b) => count.get(b) ?? null), backgroundColor: colors }],
    },
    options: {
      maintainAspectRatio: false,
      animation: false,
      scales: {
        x: { grid: { display: false }, ticks: { color: theme.text, font: { family: theme.font } } },
        y: {
          type: 'logarithmic',
          min: 0.5,
          grid: { color: theme.grid },
          ticks: { color: theme.text, font: { family: theme.font }, callback: (v) => (Number(v) >= 1 && Math.log10(Number(v)) % 1 === 0 ? fmtInt(Number(v)) : '') },
        },
      },
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: (item) => `${fmtInt(Number(item.raw))} comments (${pct2(Number(item.raw) / total)})` } },
      },
    },
  }));
}

// ---- leaderboards

/** A board's rows. Each name is a button that opens its comments (`open`),
 * with the email address under it. */
function boardRows(table: HTMLTableElement, rows: { name: string; email: string; count: string | Node; title?: string }[],
  open: (r: { name: string; email: string }) => void) {
  table.tBodies[0].replaceChildren(...rows.map((r, i) => {
    const tr = el('tr');
    const who = el('td');
    const b = el('button', r.name, 'link-button person-link');
    b.type = 'button';
    b.addEventListener('click', () => open(r));
    who.append(b, el('span', r.email, 'person-email'));
    const count = el('td', undefined, 'num');
    count.append(r.count);
    if (r.title) count.title = r.title;
    tr.append(el('td', String(i + 1)), who, count);
    return tr;
  }));
}

// ---- the name popup

const dialog = $<HTMLDialogElement>('#person-dialog');
// Escape closes a modal dialog by itself; a click on the backdrop (outside
// the dialog's box) closes it too.
dialog.addEventListener('click', (e) => {
  const r = dialog.getBoundingClientRect();
  const inside = e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom;
  if (e.target === dialog && !inside) dialog.close();
});
$('#person-close').addEventListener('click', () => dialog.close());
// Print prints just the popup (style.css, @media print). The page title is
// the person's while printing, so a saved PDF is named after them.
$('#person-print').addEventListener('click', () => {
  const title = document.title;
  document.title = msg('person-print-title', { title: $('#person-title').textContent ?? '' });
  window.addEventListener('afterprint', () => (document.title = title), { once: true });
  window.print();
});
dialog.addEventListener('close', () => {
  personChart?.destroy();
  personChart = undefined;
  if (parseHash()) history.replaceState(null, '', location.pathname + location.search);
});

/** What a popup charts: one bar series per kind of comment it lists, over
 * the weeks it lists them from (the dates chosen on the page). */
interface ChartSpec {
  range: [string, string];
  series: { key: SeriesKey; pick: (d: PersonComments) => PersonComment[] }[];
  /** One bar per month with every series in it (the lookup popup), rather
   * than a bar each for given and received. */
  oneStack?: boolean;
}

/** A chart series: praise given or received, as change author or as reviewer.
 * Given and received each stack their two roles. */
type SeriesKey = 'given-author' | 'given-reviewer' | 'received-author' | 'received-reviewer';

/** The popup's series for `email`: its comments in `kinds` (given, received
 * or both), split by role. */
function roleSeries(email: string, kinds: ('given' | 'received')[], pick: (d: PersonComments) => PersonComment[]) {
  return kinds.flatMap((k) => (['author', 'reviewer'] as const).map((role) => ({
    key: `${k}-${role}` as SeriesKey,
    pick: (d: PersonComments) => pick(d).filter((c) => relation(c, email) === `${k}-${role}`),
  })));
}

/** The popup's monthly chart, destroyed when the popup closes. */
let personChart: Chart | undefined;
let lastChart: { spec: ChartSpec; data: PersonComments } | undefined;
// Printing uses the light colours (style.css), so the chart is redrawn in
// them, and in the screen's again afterwards.
for (const ev of ['beforeprint', 'afterprint']) {
  window.addEventListener(ev, () => {
    if (dialog.open && personChart && lastChart) drawPersonChart(lastChart.spec, lastChart.data);
  });
}

/** The popup's comments per month, a series for each kind `spec` names, so
 * the chart shows just what the popup is about. Hidden when there are none,
 * and when the chosen dates are one month (the count line says it all). */
function drawPersonChart(spec: ChartSpec | null, data?: PersonComments) {
  personChart?.destroy();
  personChart = undefined;
  const fig = $('#person-chart');
  lastChart = spec && data ? { spec, data } : undefined;
  const m = spec && data ? byMonth(spec.range, spec.series.map((x) => x.pick(data))) : null;
  const totals = m ? m.counts.map((c) => c.reduce((a, b) => a + b, 0)) : [];
  fig.hidden = !m || m.months.length < 2 || totals.every((t) => t === 0);
  if (fig.hidden) return;
  fill($('#person-chart-sub'), { range: weeksBetween(spec!.range) });
  const theme = readTheme();
  const axis = { color: theme.text, font: { family: theme.font } };
  const labels = spec!.series.map((x, i) => `${msg(`chart-${x.key}`)} (${fmtInt(totals[i])})`);
  $('#person-months').setAttribute('aria-label', `${labels.join(', ')} per month`);
  const css = getComputedStyle(document.documentElement);
  const color = (k: SeriesKey) => css.getPropertyValue(k.startsWith('given') ? `--${k}` : `--praise-${k.slice('received-'.length)}`).trim();
  personChart = new Chart($<HTMLCanvasElement>('#person-months'), {
    type: 'bar',
    data: {
      labels: m!.months.map(monthLabel),
      datasets: spec!.series.map((x, i) => ({
        label: labels[i],
        data: m!.counts[i],
        stack: spec!.oneStack ? 'all' : x.key.split('-')[0],
        backgroundColor: color(x.key),
      })),
    },
    options: {
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: 'index', intersect: false },
      scales: {
        x: { stacked: true, grid: { display: false }, ticks: { ...axis, maxRotation: 0, autoSkip: true, maxTicksLimit: 7 } },
        y: { stacked: true, beginAtZero: true, grace: '10%', grid: { color: theme.grid }, ticks: { ...axis, precision: 0 } },
      },
      plugins: {
        legend: { labels: axis },
        tooltip: {
          callbacks: { label: (item) => `${msg(`chart-${spec!.series[item.datasetIndex].key}`)}: ${fmtInt(Number(item.raw))}` },
        },
      },
    },
  });
}

/** A popup card; `email`'s cards are tinted by how the comment relates to
 * them (given or received, as change author or as reviewer). */
function commentItem(c: PersonComment, email?: string): HTMLElement {
  const rel = email ? relation(c, email) : null;
  const li = el('li', undefined, `quote ${rel ? `quote-${rel}` : 'quote-praise'}`);
  li.append(el('blockquote', c.text));
  const by = el('p', undefined, 'quote-by');
  // The popup's person gets their role on the CL after their name.
  const role = (r?: string) => (r ? ` ${msg(`role-${r}`)}` : '');
  const writer = c.writer + (email && c.writer_email === email ? role(c.writer_role) : '');
  const recipient = c.recipient + (email && c.writer_email !== email && c.recipient_email === email ? role(c.recipient_role) : '');
  by.append(scoreBadge(c.score), ' ', fragment('praise-by', { writer, recipient, date: dayLabel(c.date) }));
  const url = gerritLink(c.url);
  if (url) {
    const a = el('a', 'View review');
    a.href = url;
    a.rel = 'noopener';
    a.target = '_blank';
    by.append(' · ', a);
  }
  li.append(by);
  return li;
}

/** A board a popup's person may be on: its rows for each period. */
type RankBoard = 'given' | 'received' | 'authors' | 'reviewers';

/** The weeks a board covers for the chosen dates. */
function boardWeeks(b: RankBoard): [string, string] | null {
  if (b === 'given' || b === 'received') return praiseData ? periodWeeks(praiseData.weeks, period) : null;
  return recentData ? recentWeeks(recentData) : null;
}

/** A board's rows for the chosen dates, everyone on it. */
function boardRowsFor(b: RankBoard): { email: string; name: string }[] {
  if (b === 'given' || b === 'received') return praiseData ? netBoard(praiseData, b, period, 'all') : [];
  return recentData ? recentPeriod(recentData).happy[b] : [];
}

/** The person's places on `boards` for the dates chosen on the page, a line
 * each with its dates (so a printed popup records them). Boards they aren't
 * on are left out. */
function drawRanks(email: string, boards: RankBoard[]) {
  const items: HTMLElement[] = [];
  for (const b of boards) {
    const r = boardRank(boardRowsFor(b), email);
    const weeks = boardWeeks(b);
    if (!r || !weeks) continue;
    const li = el('li');
    li.append(fragment('person-rank', { rank: fmtInt(r.rank), of: fmtInt(r.of), board: msg(`rank-${b}`), range: weeksBetween(weeks) }));
    items.push(li);
  }
  $('#person-ranks').replaceChildren(...items);
}

/** Opens the popup: `title` and the person's board places at once, then the
 * comments `pick` chooses (from the weeks `who.range`), and the chart `chart`
 * describes. */
function openPerson(title: string, who: { email: string; boards: RankBoard[]; range: [string, string] },
  chart: ChartSpec | null, pick: (d: PersonComments) => PersonComment[]) {
  $('#person-title').textContent = title;
  drawRanks(who.email, who.boards);
  const list = $('#person-list');
  const note = $('#person-note');
  list.replaceChildren();
  note.textContent = msg('person-loading');
  if (!dialog.open) dialog.showModal();
  drawPersonChart(null);
  list.scrollTop = 0;
  dialog.scrollTop = 0;
  const want = shown;
  personComments(want).then(
    (d) => {
      if (want !== shown || !dialog.open) return;
      const items = pick(d);
      drawPersonChart(chart, d);
      const range = weeksBetween(who.range);
      if (!items.length) {
        note.textContent = msg('person-none', { range });
        return;
      }
      note.textContent = msg('person-count', { n: fmtInt(items.length), range });
      list.replaceChildren(...orNone(items.map((c) => commentItem(c, who.email))));
    },
    (e) => {
      if (want === shown) note.textContent = msg('error', { error: String(e) });
    },
  );
}

// The boards' own toggles are wired once; each draw reads the current data.
let praiseData: PraiseData | undefined;
let recentData: ToneRecent | undefined;
const praiseSize = radio<string>('praise-size', () => drawPraise());
const happySize = radio<string>('happy-size', () => drawHappy());

/** What a popup is about, as named in the URL's hash: praise given or
 * received (the praise boards), glowing comments received as change author
 * or as reviewer (the happy tables), or all of someone's praise (the lookup
 * box). */
type Mode = 'given' | 'received' | 'authors' | 'reviewers' | 'person';
const MODES: readonly Mode[] = ['given', 'received', 'authors', 'reviewers', 'person'];

/** The weeks the praise data covers for the chosen dates. */
const praiseWeeks = (d: PraiseData) => periodWeeks(d.weeks, period) ?? d.weeks;

/** Opens the popup for `email` in `mode`, and names it in the URL's hash. */
function openMode(mode: Mode, email: string, name: string) {
  const p = praiseData;
  const r = recentData;
  if (!p) return;
  const range = praiseWeeks(p);
  if (mode === 'given' || mode === 'received') {
    openPerson(msg(`person-praise-${mode}`, { name }), { email, boards: [mode], range },
      { range, series: roleSeries(email, [mode], (c) => praiseComments(c, email, mode, range)) },
      (c) => praiseComments(c, email, mode, range));
  } else if (mode === 'authors' || mode === 'reviewers') {
    const weeks = r ? recentWeeks(r) : range;
    openPerson(msg(`person-happy-${mode}`, { name }), { email, boards: [mode], range: weeks },
      { range: weeks, series: roleSeries(email, ['received'], (c) => happyComments(c, email, mode, weeks))
        .filter((sr) => sr.key === (mode === 'authors' ? 'received-author' : 'received-reviewer')) },
      (c) => happyComments(c, email, mode, weeks));
  } else {
    openPerson(msg('person-praise-all', { name }),
      { email, boards: ['given', 'received', 'authors', 'reviewers'], range }, {
        range,
        series: roleSeries(email, ['given', 'received'], (c) => allPraise(c, email, range)),
        oneStack: true,
      }, (c) => allPraise(c, email, range));
  }
  const hash = `#${mode}=${email.replace(/[%#&\s]/g, encodeURIComponent)}`;
  if (location.hash !== hash) history.replaceState(null, '', hash);
}

/** The popup the URL's hash names, if any. */
function parseHash(): { mode: Mode; email: string } | null {
  const m = /^#([a-z]+)=(.+)$/.exec(location.hash);
  if (!m || !(MODES as readonly string[]).includes(m[1])) return null;
  try {
    return { mode: m[1] as Mode, email: decodeURIComponent(m[2]) };
  } catch {
    return null;
  }
}

/** Opens the popup the URL's hash names, under the person's name from the
 * data (any board, the praise data, or the lookup list). */
async function openFromHash() {
  const h = parseHash();
  if (!h || !praiseData) return;
  const fromBoards = (['given', 'received', 'authors', 'reviewers'] as const)
    .map((b) => boardRowsFor(b).find((x) => x.email === h.email)?.name).find(Boolean);
  let name = fromBoards ?? praiseData.people[h.email];
  if (!name) name = (await lookupData()).people[h.email] ?? h.email;
  openMode(h.mode, h.email, name);
}

function drawPraise() {
  const d = praiseData;
  if (!d) return;
  const range = praiseWeeks(d);
  const size = praiseSize();
  const n = size === 'all' ? 'all' : Number(size);
  $('#net-angry').textContent = String(Math.abs(recentData?.thresholds.angry ?? 0.3));
  fill($('#praise-sub'), { range: weeksBetween(range), n: fmtInt(praiseTotal(d, range)), people: fmtInt(praisePeople(d, range)) });
  for (const key of ['given', 'received'] as const) {
    boardRows($<HTMLTableElement>(`#praise-${key}`),
      netBoard(d, key, period, n).map((r) => ({ name: r.name, email: r.email,
        count: scoreBadge(r.score, d.net_scale, `Net praise ${signed1(r.score)} (${fmtInt(r.praise)} praise comments)`) })),
      (r) => openMode(key, r.email, r.name));
  }
}

// ---- the lookup box: any email (or name) with praise, with autocomplete

const findForm = $<HTMLFormElement>('#praise-find');
const findInput = $<HTMLInputElement>('#praise-find-input');

/** Everyone who commented in the praise weeks (summaries/sentiment_people.json),
 * loaded when the box is first used, so anyone can be looked up. */
let lookupPeople: Promise<Record<string, string>> | undefined;
const everyone = () => {
  if (!lookupPeople) {
    lookupPeople = getJson<{ people: Record<string, string> }>(lookupUrl).then((d) => d.people);
    lookupPeople.catch(() => (lookupPeople = undefined));
  }
  return lookupPeople;
};

/** The people the box can find: everyone, plus anyone in the praise data. */
async function lookupData(): Promise<{ people: Record<string, string> }> {
  let all: Record<string, string> = {};
  try {
    all = await everyone();
  } catch {
    // Without the list, the box still finds everyone with praise.
  }
  return { people: { ...all, ...praiseData?.people } };
}

/** The lookup's suggestions: none until something is typed, then at most
 * SUGGESTIONS people whose name or email contains it. */
async function suggest() {
  const typed = findInput.value;
  const d = typed.trim() ? await lookupData() : { people: {} };
  if (findInput.value !== typed) return;
  const people = suggestPeople(d, typed, SUGGESTIONS);
  $('#praise-people').replaceChildren(...people.map(({ email, name }) => {
    const o = el('option');
    o.value = email;
    o.label = name;
    return o;
  }));
}
const SUGGESTIONS = 10;

function fillPeople() {
  void suggest();
  $('#praise-find-note').textContent = '';
}

/** Opens the popup for what the box names, or says no one matched. */
async function lookUp() {
  const d = praiseData;
  if (!d) return;
  const note = $('#praise-find-note');
  const who = findPerson(await lookupData(), findInput.value);
  if (!who) {
    fill(note, { q: findInput.value.trim(), range: weeksBetween(praiseWeeks(d)) }, 'praise-find-none');
    return;
  }
  note.textContent = '';
  openMode('person', who.email, who.name);
}

findForm.addEventListener('submit', (e) => {
  e.preventDefault();
  void lookUp();
});
findInput.addEventListener('focus', () => void everyone().catch(() => undefined), { once: true });
// Picking a suggestion opens it at once; typing waits for Enter or Show.
findInput.addEventListener('input', (e) => {
  void suggest();
  if (!(e instanceof InputEvent) || e.inputType === 'insertReplacementText') {
    void lookupData().then((d) => {
      if (findPerson(d, findInput.value)) void lookUp();
    });
  }
});

function drawHappy() {
  const r = recentData;
  if (!r) return;
  const fmtRow = (x: HappyRow) => ({ name: x.name, email: x.email, count: fmtInt(x.glowing),
    title: `${fmtInt(x.glowing)} glowing comments from ${fmtInt(x.happy)} of the ${fmtInt(x.counterparts)} people who commented` });
  const d = recentPeriod(r);
  const n = Number(happySize());
  fill($('#happy-sub'), { range: weeksBetween(d.weeks), min: r.min_counterparts });
  for (const table of ['authors', 'reviewers'] as const) {
    boardRows($<HTMLTableElement>(`#happy-${table}`), d.happy[table].slice(0, n).map(fmtRow),
      (x) => openMode(table, x.email, x.name));
  }
}

// ---- comments

/** A comment's score as a small pill: "+0.6" or "−0.8", tinted from neutral
 * toward the glowing or the grumpy colour as the score grows. */
function scoreBadge(score: number, scale = 1, title = `Score ${signed1(score)} on a scale from −1 to +1`): HTMLElement {
  const b = el('span', signed1(score), 'score-badge');
  const m = Math.min(1, Math.abs(score) / scale);
  b.dataset.pole = score < 0 ? 'neg' : 'pos';
  b.style.setProperty('--mix', `${Math.round(m * 100)}%`);
  if (m > 0.6) b.classList.add('score-strong');
  b.title = title;
  return b;
}

const signed1 = (v: number) =>
  (v > 0 ? '+' : v < 0 ? '−' : '') + fmtNum(Math.abs(v), { minimumFractionDigits: 1, maximumFractionDigits: 1 });

/** A list's items, or one "none" line when there are none. */
function orNone(items: HTMLElement[]): HTMLElement[] {
  return items.length ? items : [el('li', msg('quotes-none'), 'quote-none')];
}

function renderSamples(s: ToneSamples) {
  const d = s.periods[period] ?? { praise: [], grumpy: [] };
  fill($('#samples-sub'), { range: weeksBetween(periodWeeks(s.weeks, period) ?? s.weeks) });
  $('#praise-min').textContent = String(s.praise_min);
  $('#grumpy-max').textContent = String(Math.abs(s.grumpy_max));
  $('#praise-samples').replaceChildren(...orNone(d.praise.map((p) => {
    const li = el('li', undefined, 'quote quote-praise');
    li.append(el('blockquote', p.text));
    const by = el('p', undefined, 'quote-by');
    by.append(scoreBadge(p.score), ' ', fragment('praise-by', { writer: p.writer, recipient: p.recipient, date: dayLabel(p.date) }));
    const url = gerritLink(p.url);
    if (url) {
      const a = el('a', 'View review');
      a.href = url;
      a.target = '_blank';
      a.rel = 'noopener';
      by.append(' · ', a);
    }
    li.append(by);
    return li;
  })));
  $('#grumpy-samples').replaceChildren(...orNone(d.grumpy.map((g) => {
    const li = el('li', undefined, 'quote quote-grumpy');
    li.append(el('blockquote', g.text));
    const when = el('p', undefined, 'quote-by');
    when.append(scoreBadge(g.score), ' ', fragment('grumpy-when', { month: monthLabel(g.month) }));
    li.append(when);
    return li;
  })));
}

function renderAi(r: ToneRecent) {
  const d = recentPeriod(r);
  fill($('#ai-sub'), { range: weeksBetween(d.weeks), shown: fmtInt(d.ai.length), total: fmtInt(d.total.ai) });
  // Most negative first, as the data lists them.
  $('#ai-list').replaceChildren(...orNone(d.ai.map((c) => {
    const li = el('li', undefined, 'quote quote-ai');
    li.append(el('blockquote', c.text));
    const when = el('p', undefined, 'quote-by');
    when.append(scoreBadge(c.score), ' ', fragment('ai-when', { month: monthLabel(c.month), role: c.role }));
    li.append(when);
    return li;
  })));
}

/** Bumped on every switch, so a slower earlier load doesn't draw over a later one. */
let current = 0;

/** The loaded files for the writers shown. */
let loaded: { trend: ToneTrend; samples: ToneSamples } | undefined;

/** Loads every section's files for one choice of writers, then draws. */
async function show(authors: Authors, token: number) {
  const u = URLS[authors];
  const [trend, praise, samples, recent] = await Promise.all([
    getJson<ToneTrend>(u.monthly),
    getJson<PraiseData>(u.praise),
    getJson<ToneSamples>(u.samples),
    getJson<ToneRecent>(u.recent),
  ]);
  if (token !== current) return;
  shown = authors;
  if (dialog.open) dialog.close();
  praiseData = praise;
  recentData = recent;
  loaded = { trend, samples };
  fillPeriods();
  fillPeople();
  draw();
  fill($('#authors-note'), { a: authors });
}

/** Draws every section for the chosen dates. */
function draw() {
  if (!loaded || !praiseData || !recentData) return;
  for (const c of charts) c.destroy();
  charts = [];
  const theme = readTheme();
  renderTrend(loaded.trend, theme);
  renderRecent(recentData, theme);
  drawPraise();
  drawHappy();
  renderSamples(loaded.samples);
  renderAi(recentData);
  // For the browser tests: the charts just drawn, by canvas id.
  window.__tone = Object.fromEntries(charts.map((c) => [c.canvas.id, c]));
}

// ---- the dates: all, a calendar year or a calendar month

const yearPick = $<HTMLSelectElement>('#period-year');
const monthPick = $<HTMLSelectElement>('#period-month');

/** The kind of dates checked (all, year, month). */
const periodChoice = () => document.querySelector<HTMLInputElement>('input[name="period"]:checked')!.value as
  'all' | 'year' | 'month';

/** Lists the years and months the data has, newest first, keeping the
 * choice when it's still there (else the newest). */
function fillPeriods() {
  if (!praiseData) return;
  const { years, months } = periodsOf(praiseData.weeks);
  const options = (sel: HTMLSelectElement, keys: string[], label: (k: string) => string) => {
    const keep = sel.value;
    sel.replaceChildren(...keys.slice().reverse().map((k) => {
      const o = el('option', label(k));
      o.value = k;
      return o;
    }));
    if (keys.includes(keep)) sel.value = keep;
  };
  options(yearPick, years, (y) => y);
  options(monthPick, months, monthLabel);
  syncPeriod();
}

/** Shows the select for the kind checked and takes the dates from it. */
function syncPeriod() {
  const kind = periodChoice();
  $('#period-year-box').hidden = kind !== 'year';
  $('#period-month-box').hidden = kind !== 'month';
  period = kind === 'year' ? yearPick.value || 'all' : kind === 'month' ? monthPick.value || 'all' : 'all';
}

/** A new choice of dates: redraw, and keep it in the URL (?period=…). */
function changePeriod() {
  syncPeriod();
  const url = new URL(location.href);
  if (period === 'all') url.searchParams.delete('period');
  else url.searchParams.set('period', period);
  history.replaceState(null, '', url);
  if (dialog.open) dialog.close();
  draw();
}

/** The dates in the URL (?period=2026 or 2026-10): checks their kind and
 * picks them once the selects are filled. */
function initialPeriod() {
  const v = new URLSearchParams(location.search).get('period') ?? '';
  const kind = /^\d{4}$/.test(v) ? 'year' : /^\d{4}-\d{2}$/.test(v) ? 'month' : 'all';
  $<HTMLInputElement>(`input[name="period"][value="${kind}"]`).checked = true;
  if (kind === 'all') return;
  const sel = kind === 'year' ? yearPick : monthPick;
  const o = el('option', v);
  o.value = v;
  sel.replaceChildren(o);
  sel.value = v;
}

/** The writers in the URL (?authors=…), else committers. */
function initialAuthors(): Authors {
  const v = new URLSearchParams(location.search).get('authors');
  return (AUTHORS as readonly string[]).includes(v ?? '') ? (v as Authors) : 'committers';
}

async function run(authors: Authors) {
  const token = ++current;
  const main = $('main');
  main.setAttribute('aria-busy', 'true');
  delete document.body.dataset.ready;
  try {
    await show(authors, token);
    if (token === current) $('#error').hidden = true;
  } catch (e) {
    if (token !== current) return;
    const err = $('#error');
    fill(err, { error: String(e) });
    err.hidden = false;
  } finally {
    if (token === current) {
      main.removeAttribute('aria-busy');
      document.body.dataset.ready = authors;
    }
  }
}

function main() {
  $('#prompt-text').textContent = promptText.trim();
  const start = initialAuthors();
  $<HTMLInputElement>(`input[name="authors"][value="${start}"]`).checked = true;
  initialPeriod();
  const authors = radio<Authors>('authors', () => {
    const a = authors();
    const url = new URL(location.href);
    if (a === 'committers') url.searchParams.delete('authors');
    else url.searchParams.set('authors', a);
    history.replaceState(null, '', url);
    void run(a);
  });
  radio('period', changePeriod);
  yearPick.addEventListener('change', changePeriod);
  monthPick.addEventListener('change', changePeriod);
  // The bar is sticky; scroll-padding-top (style.css) keeps anchor jumps
  // clear of it, at whatever height it wraps to.
  const bar = $('.metric-bar');
  new ResizeObserver(() => document.documentElement.style.setProperty('--metric-bar-h', `${bar.offsetHeight}px`))
    .observe(bar);
  // A shared link to a popup opens it once the data is in, and so does a
  // hash typed or followed later.
  void run(start).then(() => openFromHash());
  window.addEventListener('hashchange', () => void openFromHash());
}

main();
