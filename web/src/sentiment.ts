// The Review Tone page (sentiment.html). Wording is in the HTML; this fills
// in values and draws the charts. Comment text is untrusted and goes into
// the DOM only as text (SECURITY.md). Ground rule 5: names and links only
// for praise. The "Comments by" switch picks whose comments every section
// counts; each choice has its own set of summary files.
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
import { weekMonday } from './data.ts';
import { fmtDay, fmtInt, fmtNum } from './format.ts';
import { fill, fragment, msg } from './text.ts';
import {
  AUTHORS,
  dayLabel,
  gerritLink,
  monthLabel,
  periodWeeks,
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

function bandedLine(canvas: HTMLCanvasElement, trend: ToneTrend, series: Series[], theme: Theme, fmt: (v: number) => string) {
  const months = trend.months;
  const datasets: ChartDataset<'line', number[]>[] = [];
  for (const s of series) {
    datasets.push(
      { label: s.label, data: months.map((m) => s.v(m.rolling)), borderColor: s.color, backgroundColor: s.color,
        borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, tension: 0, fill: false },
      { label: '', data: months.map((m) => s.ci(m.rolling)[1]), borderWidth: 0, pointRadius: 0, pointHoverRadius: 0,
        backgroundColor: faint(s.color), fill: '+1' },
      { label: '', data: months.map((m) => s.ci(m.rolling)[0]), borderWidth: 0, pointRadius: 0, pointHoverRadius: 0,
        fill: false },
    );
  }
  charts.push(new Chart(canvas, {
    type: 'line',
    data: { labels: months.map((m) => monthLabel(m.m)), datasets },
    options: {
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: 'index', intersect: false },
      font: { family: theme.font },
      scales: {
        x: { grid: { color: theme.grid }, ticks: { color: theme.text, maxTicksLimit: 12, font: { family: theme.font } } },
        y: { grid: { color: theme.grid }, ticks: { color: theme.text, callback: (v) => fmt(Number(v)), font: { family: theme.font } } },
      },
      plugins: {
        legend: {
          display: series.length > 1,
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
              const s = series.find((x) => x.label === item.dataset.label)!;
              const p = months[item.dataIndex].rolling;
              const [lo, hi] = s.ci(p);
              return `${s.label}: ${fmt(s.v(p))} (95% ${fmt(lo)} to ${fmt(hi)})`;
            },
            footer: (items) => `${fmtInt(months[items[0].dataIndex].rolling.n)} comments`,
          },
        },
      },
    },
  }));
}

function renderTrend(trend: ToneTrend, theme: Theme) {
  const months = trend.months.length;
  fill($('#trend-sub'), {
    rate: trend.rate ? pct(trend.rate).replace(/\.0%$/, '%') : 'random',
    n: fmtInt(trend.n),
    months,
    perMonth: fmtInt(Math.round(trend.n / Math.max(1, months))),
    window: trend.window,
  });
  fill($('#trend-note'), { glowing: trend.thresholds.glowing, angry: Math.abs(trend.thresholds.angry) });
  bandedLine($<HTMLCanvasElement>('#trend-mean'), trend,
    [{ label: 'Average score', color: theme.series[0], v: (p) => p.mean, ci: (p) => [p.lo, p.hi] }], theme, signed);
  bandedLine($<HTMLCanvasElement>('#trend-shares'), trend, [
    { label: 'Glowing', color: theme.series[2], v: (p) => p.glowing, ci: (p) => p.glowing_ci },
    { label: 'Angry', color: theme.series[7], v: (p) => p.angry, ci: (p) => p.angry_ci },
    { label: 'AI friction', color: theme.series[6], v: (p) => p.ai, ci: (p) => p.ai_ci },
  ], theme, pct);
}

// ---- the last two months

function tile(id: string, value: string) {
  $(`#${id} .tile-value`).textContent = value;
}

function renderRecent(r: ToneRecent, theme: Theme) {
  fill($('#recent-sub'), { range: weeksBetween(r.weeks) });
  const t = r.total;
  tile('tile-n', fmtInt(t.n));
  tile('tile-trivial', fmtInt(r.n_trivial));
  tile('tile-mean', t.mean === null ? '–' : signed(t.mean));
  tile('tile-glowing', t.glowing === null ? '–' : pct2(t.glowing));
  tile('tile-angry', t.angry === null ? '–' : pct2(t.angry));
  tile('tile-ai', fmtInt(t.ai));
  $<HTMLTableElement>('#recent-weekly').tBodies[0].replaceChildren(...r.weekly.map((w) => {
    const tr = el('tr');
    tr.append(
      el('th', fmtDay(weekMonday(w.week))),
      el('td', fmtInt(w.n)),
      el('td', w.mean === null ? '–' : signed(w.mean)),
      el('td', w.glowing === null ? '–' : pct2(w.glowing)),
      el('td', w.angry === null ? '–' : pct2(w.angry)),
      el('td', fmtInt(w.ai)),
    );
    tr.firstElementChild!.setAttribute('scope', 'row');
    return tr;
  }));
  const total = r.dist.reduce((s, [, n]) => s + n, 0) || 1;
  const bins: number[] = [];
  for (let i = -10; i <= 10; i++) bins.push(i / 10);
  const share = new Map(r.dist.map(([b, n]) => [Math.round(b * 10) / 10, n / total]));
  const colors = bins.map((b) => (b <= r.thresholds.angry ? theme.series[7] : b >= r.thresholds.glowing ? theme.series[2] : theme.baseline));
  charts.push(new Chart($<HTMLCanvasElement>('#recent-dist'), {
    type: 'bar',
    data: {
      labels: bins.map((b) => (b > 0 ? '+' : b < 0 ? '−' : '') + Math.abs(b).toFixed(1)),
      datasets: [{ label: 'Share of comments', data: bins.map((b) => share.get(b) ?? null), backgroundColor: colors }],
    },
    options: {
      maintainAspectRatio: false,
      animation: false,
      scales: {
        x: { grid: { display: false }, ticks: { color: theme.text, font: { family: theme.font } } },
        y: {
          type: 'logarithmic',
          min: 1e-5,
          grid: { color: theme.grid },
          ticks: { color: theme.text, font: { family: theme.font }, callback: (v) => (Math.log10(Number(v)) % 1 === 0 ? pct(Number(v)).replace(/\.0%$/, '%') : '') },
        },
      },
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: (item) => `${pct2(Number(item.raw))} of comments` } },
      },
    },
  }));
}

// ---- leaderboards

/** A board's rows. Each name is a button that opens its comments (`open`). */
function boardRows(table: HTMLTableElement, rows: { name: string; email: string; count: string | Node; title?: string }[],
  open: (r: { name: string; email: string }) => void) {
  table.tBodies[0].replaceChildren(...rows.map((r, i) => {
    const tr = el('tr');
    const who = el('td');
    const b = el('button', r.name, 'link-button person-link');
    b.type = 'button';
    b.title = r.email;
    b.addEventListener('click', () => open(r));
    who.append(b);
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
});

/** What a popup charts: one bar series per kind of comment it lists, over
 * the weeks its board covers. */
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
 * the chart shows just what the popup is about. Hidden when there are none. */
function drawPersonChart(spec: ChartSpec | null, data?: PersonComments) {
  personChart?.destroy();
  personChart = undefined;
  const fig = $('#person-chart');
  lastChart = spec && data ? { spec, data } : undefined;
  const m = spec && data ? byMonth(spec.range, spec.series.map((x) => x.pick(data))) : null;
  const totals = m ? m.counts.map((c) => c.reduce((a, b) => a + b, 0)) : [];
  fig.hidden = !m || totals.every((t) => t === 0);
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

/** The weeks a board covers in `period`. */
function boardWeeks(b: RankBoard, period: Period): [string, string] | null {
  if (b === 'given' || b === 'received') return praiseData ? periodWeeks(praiseData.weeks, period) : null;
  return recentData ? (period === 'all' ? recentData.weeks : recentData.month_weeks) : null;
}

/** The person's places on `boards` in the period selected on the page, a
 * line each with its dates (so a printed popup records them). Boards they
 * aren't on are left out. */
function drawRanks(email: string, boards: RankBoard[], period: Period) {
  const rows = (b: RankBoard): { email: string }[] =>
    b === 'given' || b === 'received'
      ? (praiseData ? netBoard(praiseData, b, period, 'all') : [])
      : (recentData?.happy[period][b] ?? []);
  const items: HTMLElement[] = [];
  for (const b of boards) {
    const r = boardRank(rows(b), email);
    const weeks = boardWeeks(b, period);
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
function openPerson(title: string, who: { email: string; boards: RankBoard[]; period: Period; range: [string, string] },
  chart: ChartSpec | null, pick: (d: PersonComments) => PersonComment[]) {
  $('#person-title').textContent = title;
  drawRanks(who.email, who.boards, who.period);
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
const praisePeriod = radio<Period>('praise-period', () => drawPraise());
const praiseSize = radio<string>('praise-size', () => drawPraise());
const happyPeriod = radio<Period>('happy-period', () => drawHappy());
const happySize = radio<string>('happy-size', () => drawHappy());

function drawPraise() {
  const d = praiseData;
  if (!d) return;
  const period = praisePeriod();
  const range = periodWeeks(d.weeks, period);
  const size = praiseSize();
  const n = size === 'all' ? 'all' : Number(size);
  $('#net-angry').textContent = String(Math.abs(recentData?.thresholds.angry ?? 0.3));
  fill($('#praise-sub'), { range: weeksBetween(range), n: fmtInt(praiseTotal(d, range)), people: fmtInt(praisePeople(d, range)) });
  for (const key of ['given', 'received'] as const) {
    boardRows($<HTMLTableElement>(`#praise-${key}`),
      netBoard(d, key, period, n).map((r) => ({ name: r.name, email: r.email,
        count: scoreBadge(r.score, d.net_scale, `Net praise ${signed1(r.score)} (${fmtInt(r.praise)} praise comments)`) })),
      (r) => openPerson(msg(`person-praise-${key}`, { name: r.name }), { email: r.email, boards: [key], period, range },
        { range: d.weeks, series: roleSeries(r.email, [key], (c) => praiseComments(c, r.email, key, d.weeks)) },
        (c) => praiseComments(c, r.email, key, range)));
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
    fill(note, { q: findInput.value.trim(), range: weeksBetween(d.weeks) }, 'praise-find-none');
    return;
  }
  note.textContent = '';
  const period = praisePeriod();
  const range = periodWeeks(d.weeks, period);
  openPerson(msg('person-praise-all', { name: who.name }),
    { email: who.email, boards: ['given', 'received', 'authors', 'reviewers'], period, range }, {
    range: d.weeks,
    series: roleSeries(who.email, ['given', 'received'], (c) => allPraise(c, who.email, d.weeks)),
    oneStack: true,
  }, (c) => allPraise(c, who.email, range));
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

/** Every glowing comment behind `email`'s row in a happy table, over all its
 * weeks (the past-month list is part of it), for the popup's chart. */
const happyAll = (c: PersonComments, email: string, table: 'authors' | 'reviewers') => {
  const all = happyComments(c, email, table, 'all');
  return all.length ? all : happyComments(c, email, table, 'month');
};

function drawHappy() {
  const r = recentData;
  if (!r) return;
  const fmtRow = (x: HappyRow) => ({ name: x.name, email: x.email, count: fmtInt(x.glowing),
    title: `${fmtInt(x.glowing)} glowing comments from ${fmtInt(x.happy)} of the ${fmtInt(x.counterparts)} people who commented` });
  const p = happyPeriod();
  const n = Number(happySize());
  fill($('#happy-sub'), { range: weeksBetween(p === 'all' ? r.weeks : r.month_weeks), min: r.min_counterparts });
  for (const table of ['authors', 'reviewers'] as const) {
    boardRows($<HTMLTableElement>(`#happy-${table}`), r.happy[p][table].slice(0, n).map(fmtRow),
      (x) => openPerson(msg(`person-happy-${table}`, { name: x.name }), { email: x.email, boards: [table], period: p, range: p === 'all' ? r.weeks : r.month_weeks },
        { range: r.weeks, series: roleSeries(x.email, ['received'], (c) => happyAll(c, x.email, table))
          .filter((sr) => sr.key === (table === 'authors' ? 'received-author' : 'received-reviewer')) },
        (c) => happyComments(c, x.email, table, p)));
  }
}

// ---- comments

/** A comment's score as a small pill: "+0.6" or "−0.8", tinted from neutral
 * toward the glowing or the angry colour as the score grows. */
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
  fill($('#samples-sub'), { range: weeksBetween(s.weeks) });
  $('#praise-min').textContent = String(s.praise_min);
  $('#grumpy-max').textContent = String(Math.abs(s.grumpy_max));
  $('#praise-samples').replaceChildren(...orNone(s.praise.map((p) => {
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
  $('#grumpy-samples').replaceChildren(...orNone(s.grumpy.map((g) => {
    const li = el('li', undefined, 'quote quote-grumpy');
    li.append(el('blockquote', g.text));
    const when = el('p', undefined, 'quote-by');
    when.append(scoreBadge(g.score), ' ', fragment('grumpy-when', { month: monthLabel(g.month) }));
    li.append(when);
    return li;
  })));
}

function renderAi(r: ToneRecent) {
  const total = r.total.ai;
  fill($('#ai-sub'), { range: weeksBetween(r.weeks), shown: fmtInt(r.ai.length), total: fmtInt(total) });
  // Most negative first, as the data lists them.
  $('#ai-list').replaceChildren(...orNone(r.ai.map((c) => {
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

/** Loads and draws every section for one choice of writers. */
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
  for (const c of charts) c.destroy();
  charts = [];
  const theme = readTheme();
  renderTrend(trend, theme);
  renderRecent(recent, theme);
  praiseData = praise;
  recentData = recent;
  fillPeople();
  drawPraise();
  drawHappy();
  renderSamples(samples);
  renderAi(recent);
  fill($('#authors-note'), { a: authors });
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
  const authors = radio<Authors>('authors', () => {
    const a = authors();
    const url = new URL(location.href);
    if (a === 'committers') url.searchParams.delete('authors');
    else url.searchParams.set('authors', a);
    history.replaceState(null, '', url);
    void run(a);
  });
  void run(start);
}

main();
