// The Feedback Index page (feedback-index.html). Wording is in the HTML;
// this looks a person up by the address typed (never offering completions:
// the data is one file per person, named by a hash of the address), fills in
// the values and draws the charts. Comment text is untrusted and goes into the
// DOM only as text (SECURITY.md). Tone appears only as praise (ground rule 5).
// The address is never put in the URL.
import { Chart, Filler, type ChartDataset, type ChartEvent, type Plugin } from 'chart.js';
import { readTheme, withAlpha, type Theme } from './charts.ts';
import {
  binSums,
  buildPerson,
  clsIn,
  commentUrl,
  dirRows,
  dirTree,
  fiOf,
  fr,
  frOf,
  growth,
  halves,
  isoDay,
  looksLikeEmail,
  percentileOf,
  periodSpan,
  personKey,
  quantile,
  ratioShade,
  sums,
  threadBinLabel,
  threadBinRange,
  threadHistogram,
  threadRows,
  threadsIn,
  THREAD_BINS,
  usualOrg,
  type Alias,
  type DirNode,
  type DirRowView,
  type Norm,
  type Peers,
  type Person,
  type Shard,
  type ThreadRow,
  type Top,
} from './feedback.ts';
import { fmtDay, fmtInt, fmtNum } from './format.ts';
import { fragment, msg, type Vars } from './text.ts';

Chart.register(Filler);

/** Replaces `target`'s contents with the template `key`. */
const put = (target: Element, key: string, vars: Vars = {}) => target.replaceChildren(fragment(key, vars));

declare global {
  interface Window {
    __rf?: { person: Person | null; peers: Peers | null; charts: Record<string, Chart>; half: string | null;
      bin: number | null; norm: Norm };
  }
}

const $ = <T extends Element = HTMLElement>(sel: string) => document.querySelector<T>(sel)!;
const DATA = 'review-feedback/';
const PAGE = 50;
/** The page's figures cover all the data; only the over-time chart splits it, by half-year. */
const ALL = 'all';

const state = {
  person: null as Person | null,
  peers: null as Peers | null,
  /** What the feedback index compares with (experience, directories, org). */
  norm: 'ed' as Norm,
  /** The selected directory's path; comments are listed from it and below. */
  dir: null as string | null,
  /** The half-year picked in the over-time chart, filtering the directories and comments. */
  half: null as string | null,
  /** The column picked in the comments-per-change chart (THREAD_BINS), filtering the same. */
  bin: null as number | null,
  threadsShown: PAGE,
  noTextShown: PAGE,
  /** Keys of the directory rows that are open (see dirRows). */
  expanded: new Set<string>(),
};
const charts: Record<string, Chart> = {};
window.__rf = { person: null, peers: null, charts, half: null, bin: null, norm: state.norm };

async function getJson<T>(url: string): Promise<T | null> {
  const r = await fetch(url);
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return (await r.json()) as T;
}

function el<K extends keyof HTMLElementTagNameMap>(tag: K, text?: string, cls?: string): HTMLElementTagNameMap[K] {
  const e = document.createElement(tag);
  if (text !== undefined) e.textContent = text;
  if (cls) e.className = cls;
  return e;
}

function link(href: string, text: string): HTMLAnchorElement {
  const a = el('a', text);
  a.href = href;
  a.target = '_blank';
  a.rel = 'noopener';
  return a;
}

const dayLabel = (day: number) => fmtDay(new Date(`${isoDay(day)}T00:00:00Z`));
const monthLabel = (ym: string) =>
  new Intl.DateTimeFormat('en-GB', { month: 'long', year: 'numeric', timeZone: 'UTC' }).format(new Date(`${ym}-01T00:00:00Z`));

const ok = (v: number | null | undefined): v is number => v !== null && v !== undefined && Number.isFinite(v);
/** A feedback rate: addressed comments per 100 lines. */
const fmtFr = (v: number | null | undefined) => (ok(v) ? fmtNum(v, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '–');
/** A feedback index. */
const fmtFi = (v: number | null | undefined) => (ok(v) ? `${fmtNum(v, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}×` : '–');
/** A change in %, signed ("−21%", "+12%"). */
const fmtChange = (v: number | null | undefined) => {
  if (!ok(v)) return '–';
  const r = Math.round(v);
  return r === 0 ? '0%' : `${r < 0 ? '−' : '+'}${fmtInt(Math.abs(r))}%`;
};
/** A fall or rise as a positive % ("21%"). */
const fmtAbs = (v: number | null | undefined) => (ok(v) ? `${fmtInt(Math.abs(Math.round(v)))}%` : '–');
const pct = (v: number) => fmtNum(v, { style: 'percent', maximumFractionDigits: 0 });

const monthOf = (day: number, year: boolean) => new Intl.DateTimeFormat('en-GB',
  { month: 'long', year: year ? 'numeric' : undefined, timeZone: 'UTC' }).format(new Date(day * 86_400_000));
/** A month and year in short form ("Jul 2024"), for chart axes. */
const shortMonth = (day: number) => new Intl.DateTimeFormat('en-US',
  { month: 'short', year: 'numeric', timeZone: 'UTC' }).format(new Date(day * 86_400_000));
/** The ranges' ends are exclusive: the last month is the one before. */
const toMonth = (to: number) => to - 1;
const rangeOf = (peers: Peers): [number, number] => [peers.addr_start, peers.end];

/** A half-year's name in the over-time chart, cut to the dates the data covers. */
function halfName(h: string): string {
  const [from, to] = periodSpan(h, rangeOf(state.peers!));
  const year = h.slice(0, 4);
  const [whole0, whole1] = periodSpan(h, [-Infinity, Infinity]);
  const a = monthOf(from, false);
  const b = monthOf(toMonth(to), false);
  if (a !== monthOf(whole0, false) || b !== monthOf(toMonth(whole1), false)) return msg('period-part', { from: a, to: b, year });
  return msg(h.endsWith('H1') ? 'period-half1' : 'period-half2', { year });
}

/** The dates the data covers, by name (empty until peers.json has loaded). */
function rangeVars(peers: Peers | null): Record<string, string> {
  if (!peers) return { from: '', to: '' };
  const [from, to] = rangeOf(peers);
  return { from: monthOf(from, true), to: monthOf(toMonth(to), true) };
}

/** The dates and minimums in the page's prose. */
function fillStatic(peers: Peers) {
  const vars = rangeVars(peers);
  for (const e of document.querySelectorAll<HTMLElement>('[data-rf-range]')) e.textContent = vars[e.dataset.rfRange!] ?? '';
  const fill = (sel: string, n: number) => { for (const e of document.querySelectorAll(sel)) e.textContent = fmtInt(n); };
  fill('.rf-min-cls', peers.min_cls);
  fill('.rf-min-bin', peers.min_bin_cls);
  fill('.rf-min-cell', peers.min_cell_cls);
}

/** Who the feedback index compares with, in words ("with as many changes landed before and in the same directories"). */
function peersName(norm: Norm): string {
  const parts = [...norm].map((k) => msg(`peers-${k}`));
  return parts.length <= 1 ? parts.join('') : `${parts.slice(0, -1).join(', ')} ${msg('peers-and')} ${parts.at(-1)}`;
}

const theme = () => readTheme();

function destroy(name: string) {
  charts[name]?.destroy();
  delete charts[name];
}

const axis = (t: Theme, title: string) => ({ grid: { color: t.grid }, title: { display: true, text: title, color: t.text },
  ticks: { color: t.text, font: { family: t.font } } });

/** A line legend: one swatch per line or band, coloured by --color. */
function lineLegend(target: Element, items: { label: string; color: string; dash?: boolean; band?: boolean }[]) {
  target.replaceChildren(...items.map((l) => {
    const li = el('li');
    const sw = el('span', undefined, l.dash ? 'swatch swatch-dash' : l.band ? 'swatch swatch-band' : 'swatch');
    sw.style.setProperty('--color', l.color);
    li.append(sw, document.createTextNode(l.label));
    return li;
  }));
}

// ---- lookup

async function lookup(raw: string) {
  const note = $('#rf-find-note');
  if (!looksLikeEmail(raw)) {
    put(note, 'find-none', rangeVars(state.peers));
    return;
  }
  put(note, 'find-loading');
  try {
    const [peers, top] = await Promise.all([
      state.peers ? Promise.resolve(state.peers) : getJson<Peers>(`${DATA}peers.json`),
      (async () => {
        let k = await personKey(raw);
        for (let hops = 0; hops < 2; hops++) {
          const d = await getJson<Top | Alias>(`${DATA}u/${k}.json`);
          if (!d) return null;
          if ('see' in d) {
            if (!/^[0-9a-f]{32}$/.test(d.see)) return null;
            k = d.see;
            continue;
          }
          return { key: k, top: d };
        }
        return null;
      })(),
    ]);
    // One file per half-year the person landed changes in.
    const halvesOk = top?.top.halves.every((h) => /^\d{4}H[12]$/.test(h));
    const shards = top && halvesOk
      ? await Promise.all(top.top.halves.map((h) => getJson<Shard>(`${DATA}${h}/${top.key}.json`)))
      : [];
    const found = top && peers && halvesOk && shards.every((s) => s) ? buildPerson(top.top, shards as Shard[], peers) : null;
    state.peers = peers;
    window.__rf!.peers = peers;
    if (!found || !peers || !clsIn(found, ALL).length) {
      put(note, 'find-none', rangeVars(peers));
      return;
    }
    state.person = found;
    window.__rf!.person = found;
    state.dir = null;
    state.half = null;
    window.__rf!.half = null;
    state.bin = null;
    window.__rf!.bin = null;
    state.expanded = new Set();
    const cs = clsIn(found, ALL);
    put(note, 'find-done', { n: fmtInt(cs.length), from: dayLabel(cs[0][1]), to: dayLabel(cs.at(-1)![1]) });
    // The person's praise is on the Review Tone page, which opens their popup from the hash.
    const praise = note.querySelector<HTMLAnchorElement>('.rf-praise-link');
    if (praise) praise.href = `sentiment.html#person=${encodeURIComponent(raw.trim())}`;
    $('#rf-person').hidden = false;
    render();
    if (charts.growth) renderGrowth();
    document.body.dataset.person = '1';
  } catch (e) {
    put(note, 'find-error', { error: String(e instanceof Error ? e.message : e) });
  }
}

// ---- the opening chart (no person needed), and the same with the person's line

/** The fan of every contributor's feedback rate by experience: the 10th–90th percentile and
 * the middle half shaded, the median a line. `grey` draws it all in grey, behind someone's line. */
function fanDatasets(peers: Peers, t: Theme, grey: boolean): ChartDataset<'line', (number | null)[]>[] {
  const q = (f: number) => peers.fr_bins.map((d) => (d.q ? quantile(d.q, f) : null));
  const band = (f: number) => ({ data: q(f), borderWidth: 0, pointRadius: 0, pointHoverRadius: 0, tension: 0.3, spanGaps: true });
  const wide = grey ? t.grid : withAlpha(t.series[0], 0.14);
  const mid = grey ? t.baseline : withAlpha(t.series[0], 0.3);
  return [
    { ...band(0.9), label: 'p90', backgroundColor: wide, fill: '+1', order: 4 },
    { ...band(0.1), label: 'p10', fill: false, order: 4 },
    { ...band(0.75), label: 'p75', backgroundColor: mid, fill: '+1', order: 3 },
    { ...band(0.25), label: 'p25', fill: false, order: 3 },
    { ...band(0.5), label: 'median', borderColor: grey ? t.muted : t.series[0], borderWidth: grey ? 1.5 : 2.5,
      borderDash: grey ? [5, 4] : [], fill: false, order: 1 },
  ];
}

function fanLegend(target: Element, t: Theme, grey: boolean, you: boolean) {
  lineLegend(target, [
    ...(you ? [{ label: msg('legend-you'), color: t.series[0] }] : []),
    { label: msg('legend-median'), color: grey ? t.muted : t.series[0], dash: grey },
    { label: msg('legend-mid'), color: grey ? t.baseline : withAlpha(t.series[0], 0.3), band: true },
    { label: msg('legend-wide'), color: grey ? t.grid : withAlpha(t.series[0], 0.14), band: true },
  ]);
}

/** Experience bin `b` as a range of CLs landed, counting the change itself: "8 or fewer CLs
 * landed", "9–16 CLs landed", "more than 2,048 CLs landed". */
function binRange(peers: Peers, b: number): string {
  const e = peers.bin_edges;
  if (b === 0) return `${fmtInt(e[0])} or fewer CLs landed`;
  if (b >= e.length) return `more than ${fmtInt(e.at(-1)!)} CLs landed`;
  return `${fmtInt(e[b - 1] + 1)}–${fmtInt(e[b])} CLs landed`;
}

/** The feedback rate charts' y-axis: logarithmic, so a steady fall per doubling is a straight
 * line and the wide bands don't flatten the median. A rate of 0 is drawn at the bottom. */
const FR_MIN = 0.2;
const frLogAxis = (t: Theme) => ({ type: 'logarithmic' as const, min: FR_MIN, max: 20, ...axis(t, msg('axis-fr')),
  afterBuildTicks: (a: { ticks: { value: number }[] }) => { a.ticks = [0.2, 0.5, 1, 2, 5, 10, 20].map((value) => ({ value })); },
  ticks: { color: t.text, font: { family: t.font }, callback: (v: string | number) => fmtNum(Number(v)) } });

/** The fan's tooltip line for bin `b`. */
function fanTooltip(peers: Peers, b: number): string {
  const d = peers.fr_bins[b];
  if (!d?.q) return '';
  return `Contributors: median ${fmtFr(quantile(d.q, 0.5))}, middle half ${fmtFr(quantile(d.q, 0.25))} – `
    + `${fmtFr(quantile(d.q, 0.75))} (${fmtInt(d.n)} contributors)`;
}

function renderIntro() {
  const peers = state.peers;
  if (!peers?.fr_bins) return;
  renderGrowth();
  renderFiDist();
  destroy('main');
  const t = theme();
  fanLegend($('#rf-main-legend'), t, false, false);
  const meds = peers.fr_bins.map((d) => (d.q ? quantile(d.q, 0.5) : null));
  const last = meds.reduce<number>((a, v, i) => (v !== null ? i : a), 0);
  put($('#rf-main-note'), 'main-note', { ...rangeVars(peers), minBin: fmtInt(peers.min_bin_cls), first: fmtFr(meds[0]),
    last: fmtFr(meds[last]), lastBin: peers.bins[last] });
  charts.main = new Chart($<HTMLCanvasElement>('#rf-main'), {
    type: 'line',
    data: { labels: peers.bins, datasets: fanDatasets(peers, t, false) },
    options: {
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: 'index', intersect: false },
      font: { family: t.font },
      scales: {
        x: { ...axis(t, msg('axis-experience')), grid: { display: false } },
        y: frLogAxis(t),
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          filter: (i) => i.datasetIndex === 4,
          callbacks: { title: (items) => binRange(peers, items[0]?.dataIndex ?? 0),
            label: (i) => fanTooltip(peers, i.dataIndex) },
        },
      },
    },
  });
}

/** Everyone's feedback index: a smoothed distribution on a log scale, with the median and the
 * 10th and 90th percentiles marked. */
function renderFiDist() {
  destroy('fiDist');
  const peers = state.peers!;
  const d = peers.fi_dist;
  if (!d?.curve?.length || !d.q) return;
  const t = theme();
  const q = (f: number) => quantile(d.q!, f);
  put($('#rf-fi-note'), 'fi-note', { ...rangeVars(peers), minCls: fmtInt(peers.min_cls), n: fmtInt(d.n),
    p10: fmtFi(q(0.1)), p25: fmtFi(q(0.25)), p75: fmtFi(q(0.75)), p90: fmtFi(q(0.9)) });
  const top = Math.max(...d.curve.map(([, y]) => y));
  const mark = (x: number, dash: number[]): ChartDataset<'line', { x: number; y: number }[]> =>
    ({ label: '', data: [{ x, y: 0 }, { x, y: top * 1.05 }], borderColor: t.muted, borderWidth: dash.length ? 1.5 : 2,
      borderDash: dash, pointRadius: 0, pointHoverRadius: 0, fill: false });
  lineLegend($('#rf-fi-legend'), [{ label: msg('legend-fi'), color: t.series[0] },
    { label: msg('legend-fi-marks'), color: t.muted, dash: true }]);
  const ticks = [0.125, 0.25, 0.5, 1, 2, 4];
  charts.fiDist = new Chart($<HTMLCanvasElement>('#rf-fi-dist'), {
    type: 'line',
    data: {
      datasets: [
        { label: 'curve', data: d.curve.map(([x, y]) => ({ x, y })), borderColor: t.series[0], borderWidth: 2,
          backgroundColor: withAlpha(t.series[0], 0.18), fill: 'origin', pointRadius: 0, pointHoverRadius: 0, tension: 0.3 },
        mark(q(0.5), [5, 4]), mark(q(0.1), [2, 3]), mark(q(0.9), [2, 3]),
      ],
    },
    options: {
      maintainAspectRatio: false,
      animation: false,
      font: { family: t.font },
      scales: {
        x: { type: 'logarithmic', min: 0.125, max: 5.7, ...axis(t, msg('axis-fi')),
          afterBuildTicks: (a) => { a.ticks = ticks.map((v) => ({ value: v })); },
          ticks: { color: t.text, font: { family: t.font }, callback: (v) => fmtFi(Number(v)) } },
        y: { beginAtZero: true, ...axis(t, msg('axis-fi-share')), ticks: { display: false } },
      },
      plugins: { legend: { display: false }, tooltip: { enabled: false } },
    },
  });
}

// ---- the methodology (rendered when opened)

function renderMethod() {
  const peers = state.peers;
  if (!peers?.fr_bins || !$<HTMLDetailsElement>('#method').open) return;
  renderNewcomers();
  renderSizes();
}

function renderNewcomers() {
  destroy('newcomers');
  const peers = state.peers!;
  const t = theme();
  const rows = peers.newcomers;
  if (!rows.length) return;
  put($('#rf-newcomers-note'), 'newcomers-note', { cls: fmtInt(peers.newcomer_cls), minBin: fmtInt(peers.min_bin_cls),
    people: fmtInt(rows.reduce((a, r) => a + r[1], 0)), lastYear: String(rows.at(-1)![0]) });
  const col = (i: number) => rows.map((r) => r[i] as number | null);
  charts.newcomers = new Chart($<HTMLCanvasElement>('#rf-newcomers'), {
    type: 'line',
    data: {
      labels: rows.map((r) => String(r[0])),
      datasets: [
        { label: 'p75', data: col(5), borderWidth: 0, pointRadius: 0, pointHoverRadius: 0,
          backgroundColor: withAlpha(t.series[0], 0.25), fill: '+1', tension: 0.3 },
        { label: 'p25', data: col(3), borderWidth: 0, pointRadius: 0, pointHoverRadius: 0, fill: false, tension: 0.3 },
        { label: 'median', data: col(4), borderColor: t.series[0], backgroundColor: t.series[0], borderWidth: 2.5,
          pointRadius: 3, fill: false, tension: 0.3 },
      ],
    },
    options: {
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: 'index', intersect: false },
      font: { family: t.font },
      scales: {
        x: { ...axis(t, 'year of first commit'), grid: { display: false } },
        y: { beginAtZero: true, ...axis(t, msg('axis-fr')) },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          filter: (i) => i.datasetIndex === 2,
          callbacks: { label: (i) => { const r = rows[i.dataIndex];
            return `Median ${fmtFr(r[4])}, middle half ${fmtFr(r[3])} – ${fmtFr(r[5])} (${fmtInt(r[1])} contributors)`; } },
        },
      },
    },
  });
}

/** Growth on the chart's axis: log2 of the ratio per doubling. */
const growthX = (pctChange: number) => Math.log2(1 + pctChange / 100);

function renderGrowth() {
  destroy('growth');
  const peers = state.peers!;
  const g = peers.growth;
  if (!g?.curve?.length || !g.q || g.median === null) return;
  const t = theme();
  const q = (f: number) => quantile(g.q!, f);
  put($('#rf-growth-note'), 'growth-note', { minBin: fmtInt(peers.min_bin_cls), bins: fmtInt(peers.min_growth_bins),
    n: fmtInt(g.n), median: fmtAbs(g.median), p10: fmtAbs(q(0.1)), p90: fmtAbs(q(0.9)) });
  const top = Math.max(...g.curve.map(([, y]) => y));
  const you = state.person ? growth(binSums(state.person, peers, ALL, ''), peers) : null;
  const marker = (x: number, color: string, label: string, dash: number[]): ChartDataset<'line', { x: number; y: number }[]> =>
    ({ label, data: [{ x: growthX(x), y: 0 }, { x: growthX(x), y: top * 1.05 }], borderColor: color, borderWidth: 2,
      borderDash: dash, pointRadius: 0, pointHoverRadius: 0, fill: false });
  lineLegend($('#rf-growth-legend'), [{ label: msg('legend-growth'), color: t.series[0] },
    { label: msg('legend-growth-median'), color: t.muted, dash: true },
    ...(you !== null ? [{ label: `${msg('legend-you')} (${fmtChange(you)})`, color: t.series[1] }] : [])]);
  const ticks = [-75, -50, -25, 0, 50, 100, 200];
  charts.growth = new Chart($<HTMLCanvasElement>('#rf-growth'), {
    type: 'line',
    data: {
      datasets: [
        { label: 'curve', data: g.curve.map(([x, y]) => ({ x: growthX(x), y })), borderColor: t.series[0], borderWidth: 2,
          backgroundColor: withAlpha(t.series[0], 0.18), fill: 'origin', pointRadius: 0,
          pointHoverRadius: 0, tension: 0.3 },
        marker(g.median, t.muted, 'median', [5, 4]),
        ...(you !== null ? [marker(you, t.series[1], 'you', [])] : []),
      ],
    },
    options: {
      maintainAspectRatio: false,
      animation: false,
      font: { family: t.font },
      scales: {
        x: { type: 'linear', min: growthX(-75), max: growthX(200), ...axis(t, msg('axis-growth')),
          afterBuildTicks: (a) => { a.ticks = ticks.map((v) => ({ value: growthX(v) })); },
          ticks: { color: t.text, font: { family: t.font }, callback: (v) => fmtChange(100 * (2 ** Number(v) - 1)) } },
        y: { beginAtZero: true, ...axis(t, msg('axis-growth-share')), ticks: { display: false } },
      },
      plugins: { legend: { display: false }, tooltip: { enabled: false } },
    },
  });
}

/** The methodology's bar charts: by change size (per change and per 100 lines), by directory and by org. */
function renderSizes() {
  for (const c of ['sizeCl', 'size', 'dirs', 'orgs']) destroy(c);
  const peers = state.peers!;
  const t = theme();
  const s = peers.by_size;
  put($('#rf-size-note'), 'size-note', { clFirst: fmtFr(s[0]?.[1]), clBig: fmtFr(s[8]?.[1]), frFirst: fmtFr(s[0]?.[0]),
    frBig: fmtFr(s[8]?.[0]), minCell: fmtInt(peers.min_cell_cls) });
  const bars = (canvas: string, labels: string[], data: (number | null)[], people: number[], xTitle: string,
    yTitle: string, color = t.series[0]) => new Chart($<HTMLCanvasElement>(canvas), {
    type: 'bar',
    data: { labels, datasets: [{ data, backgroundColor: color, borderWidth: 0, categoryPercentage: 0.85, barPercentage: 1 }] },
    options: {
      maintainAspectRatio: false,
      animation: false,
      font: { family: t.font },
      scales: {
        x: { ...axis(t, xTitle), grid: { display: false },
          ticks: { color: t.text, font: { family: t.font }, autoSkip: false, minRotation: 45, maxRotation: 45 } },
        y: { beginAtZero: true, ...axis(t, yTitle) },
      },
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: (i) => `median ${fmtFr(data[i.dataIndex])} (${fmtInt(people[i.dataIndex])} contributors)` } },
      },
    },
  });
  charts.sizeCl = bars('#rf-size-cl', peers.size_labels, s.map((r) => r[1]), s.map((r) => r[2]), msg('axis-lines'),
    msg('axis-per-cl-median'), t.series[1]);
  charts.size = bars('#rf-size', peers.size_labels, s.map((r) => r[0]), s.map((r) => r[2]), msg('axis-lines'), msg('axis-fr'));
  charts.dirs = bars('#rf-dir-chart', peers.by_dir.map((r) => r[0]), peers.by_dir.map((r) => r[1]),
    peers.by_dir.map((r) => r[2]), msg('axis-dir'), msg('axis-fr'));
  charts.orgs = bars('#rf-org-chart', peers.by_org.map((r) => r[0]), peers.by_org.map((r) => r[1]),
    peers.by_org.map((r) => r[2]), msg('axis-org'), msg('axis-fr'));
}

// ---- the person

function render() {
  if (!state.person || !state.peers) return;
  if (state.half && !clsIn(state.person, state.half).length) state.half = null;
  window.__rf!.half = state.half;
  renderSummary();
  renderTrend();
  renderCompare();
  renderPerCl();
  renderDirs();
  renderThreads();
}

/** Re-renders what depends on the norm. */
function renderNorm() {
  if (!state.person) return;
  renderSummary();
  renderTrend();
  renderCompare();
  renderDirs();
}

function renderSummary() {
  const p = state.person!;
  const peers = state.peers!;
  const cs = clsIn(p, ALL);
  const s = sums(p, peers, cs, state.norm);
  const fi = fiOf(s);
  const eligible = s.cls >= peers.min_cls;
  put($('#summary-sub'), 'summary-sub', { ...rangeVars(peers), none: state.norm === '', peers: peersName(state.norm),
    eligible, minCls: fmtInt(peers.min_cls) });
  const tile = (id: string, text: string, sub = '') => {
    $(`#${id} .tile-value`).textContent = text;
    const e = document.querySelector(`#${id} .tile-sub`);
    if (e) e.textContent = sub;
  };
  tile('rf-tile-cls', fmtInt(s.cls), msg('tile-lines', { n: fmtInt(s.lines) }));
  tile('rf-tile-threads', fmtInt(s.addressed));
  tile('rf-tile-fr', fmtFr(frOf(s)), msg('tile-fr-sub'));
  const d = peers.fi[state.norm]?.[ALL];
  tile('rf-tile-fi', fmtFi(fi), eligible && d?.q && fi !== null
    ? msg('tile-fi-rank', { p: pct(percentileOf(d.q, fi)), n: fmtInt(d.n) }) : msg('tile-fi-none'));
  const g = growth(binSums(p, peers, ALL, state.norm), peers);
  tile('rf-tile-growth', fmtChange(g), g === null
    ? msg('tile-growth-none', { min: fmtInt(peers.min_bin_cls), bins: fmtInt(peers.min_growth_bins) })
    : msg('tile-growth-sub', { median: fmtChange(peers.growth.median) }));
  const facts = $('#rf-facts');
  const org = usualOrg(p, cs);
  if (p.first && org) put(facts, 'you-facts', { first: monthLabel(p.first), org });
  else facts.replaceChildren();
}

/** The person's feedback index per half-year, against everyone's spread then. */
function renderTrend() {
  destroy('trend');
  const p = state.person!;
  const peers = state.peers!;
  const t: Theme = theme();
  const range = rangeOf(peers);
  const all = halves(peers.periods).filter((h) => { const [a, b] = periodSpan(h, range); return a < b; });
  // From the half-year of their first change in the data.
  const firstDay = clsIn(p, ALL)[0][1];
  const hs = all.filter((h) => periodSpan(h, range)[1] > firstDay);
  const per = hs.map((h) => sums(p, peers, clsIn(p, h), state.norm));
  const you = per.map((s) => (s.cls ? fiOf(s) : null));
  const full = per.map((s) => s.cls >= peers.min_cls);
  const q = (h: string, f: number) => { const d = peers.fi[state.norm]?.[h]; return d?.q ? quantile(d.q, f) : null; };
  const band = (f: number) => ({ data: hs.map((h) => q(h, f)), borderWidth: 0, pointRadius: 0, pointHoverRadius: 0,
    tension: 0, spanGaps: true });
  const datasets: ChartDataset<'line', (number | null)[]>[] = [
    { ...band(0.9), label: '', backgroundColor: t.grid, fill: '+1', order: 4 },
    { ...band(0.1), label: '', fill: false, order: 4 },
    { ...band(0.75), label: '', backgroundColor: t.baseline, fill: '+1', order: 3 },
    { ...band(0.25), label: '', fill: false, order: 3 },
    { ...band(0.5), label: 'peers', borderColor: t.muted, borderWidth: 1.5, borderDash: [5, 4], fill: false, order: 1 },
    { label: 'you', data: you, borderColor: t.series[0], backgroundColor: full.map((o) => (o ? t.series[0] : t.surface)),
      pointBorderColor: t.series[0], pointRadius: 4, pointHoverRadius: 5, pointHitRadius: 10, borderWidth: 2, tension: 0,
      spanGaps: true, fill: false, order: 0 },
  ];
  const names = hs.map((h) => shortMonth(periodSpan(h, range)[0]));
  // The dot under the pointer, if it is one of the person's (dataset 5) with a value.
  const dotAt = (chart: Chart, e: ChartEvent) => {
    const hit = chart.getElementsAtEventForMode(e as unknown as Event, 'nearest', { intersect: true }, false)
      .find((x) => x.datasetIndex === 5);
    return hit && you[hit.index] !== null ? hit.index : null;
  };
  // A ring around the selected dot, as long as its filter is on.
  const ring: Plugin<'line'> = {
    id: 'rf-ring',
    afterDatasetsDraw(chart) {
      const i = state.half ? hs.indexOf(state.half) : -1;
      const pt = i >= 0 && you[i] !== null ? chart.getDatasetMeta(5).data[i] : undefined;
      if (!pt) return;
      const { ctx } = chart;
      ctx.save();
      ctx.beginPath();
      ctx.arc(pt.x, pt.y, 9, 0, 2 * Math.PI);
      ctx.lineWidth = 2;
      ctx.strokeStyle = t.series[0];
      ctx.stroke();
      ctx.restore();
    },
  };
  charts.trend = new Chart($<HTMLCanvasElement>('#rf-trend'), {
    type: 'line',
    data: { labels: names, datasets },
    plugins: [ring],
    options: {
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: 'index', intersect: false },
      onHover: (e, _els, chart) => {
        chart.canvas.classList.toggle('rf-pointable', dotAt(chart, e) !== null);
      },
      onClick: (e, _els, chart) => {
        const i = dotAt(chart, e);
        if (i !== null) setHalf(state.half === hs[i] ? null : hs[i]);
      },
      font: { family: t.font },
      scales: {
        x: { ...axis(t, msg('axis-half')), ticks: { color: t.text, font: { family: t.font }, maxRotation: 0, autoSkip: true } },
        y: { beginAtZero: true, ...axis(t, msg('axis-fi')),
          ticks: { color: t.text, font: { family: t.font }, callback: (v) => fmtFi(Number(v)) } },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          position: 'primary',
          filter: (i) => i.datasetIndex >= 4,
          callbacks: {
            title: (items) => (items.length ? halfName(hs[items[0].dataIndex]) : ''),
            label: (i) => {
              const h = hs[i.dataIndex];
              if (i.datasetIndex === 5) {
                const s = per[i.dataIndex];
                return s.cls ? `You: ${fmtFi(i.parsed.y)} (${fmtInt(s.cls)} changes, rate ${fmtFr(frOf(s))})` : 'You: no changes';
              }
              return `Everyone: median ${fmtFi(i.parsed.y)}, middle half ${fmtFi(q(h, 0.25))} – ${fmtFi(q(h, 0.75))}`;
            },
          },
        },
      },
    },
  });
}

/** The opening chart in grey with the person's rate per experience bin, and the table below it. */
function renderCompare() {
  destroy('compare');
  const p = state.person!;
  const peers = state.peers!;
  const t = theme();
  const bins = binSums(p, peers, ALL, state.norm);
  const you = bins.map((s) => (s.cls ? Math.max(frOf(s) ?? 0, FR_MIN) : null));
  const full = bins.map((s) => s.cls >= peers.min_bin_cls);
  fanLegend($('#rf-compare-legend'), t, true, true);
  charts.compare = new Chart($<HTMLCanvasElement>('#rf-compare'), {
    type: 'line',
    data: {
      labels: peers.bins,
      datasets: [...fanDatasets(peers, t, true),
        { label: 'you', data: you, borderColor: t.series[0], backgroundColor: full.map((o) => (o ? t.series[0] : t.surface)),
          pointBorderColor: t.series[0], pointRadius: 4.5, pointHoverRadius: 5.5, borderWidth: 3, tension: 0, spanGaps: true,
          fill: false, order: 0 }],
    },
    options: {
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: 'index', intersect: false },
      font: { family: t.font },
      scales: {
        x: { ...axis(t, msg('axis-experience')), grid: { display: false } },
        y: frLogAxis(t),
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          filter: (i) => i.datasetIndex >= 4,
          callbacks: {
            title: (items) => binRange(peers, items[0]?.dataIndex ?? 0),
            label: (i) => {
              if (i.datasetIndex === 4) return fanTooltip(peers, i.dataIndex);
              const s = bins[i.dataIndex];
              return `You: ${fmtFr(frOf(s))} (${fmtInt(s.cls)} ${s.cls === 1 ? 'change' : 'changes'})`;
            },
          },
        },
      },
    },
  });
  // The table: the bins with changes; the change from the bin before where both have enough.
  const body = $('#rf-xp-table tbody');
  body.replaceChildren();
  const enough = (s: { cls: number; lines: number }) => s.cls >= peers.min_bin_cls && s.lines > 0;
  bins.forEach((s, b) => {
    if (!s.cls) return;
    const prev = bins[b - 1];
    const change = prev && enough(prev) && enough(s) && fr(prev.addressed, prev.lines)! > 0
      ? 100 * (frOf(s)! / frOf(prev)! - 1) : null;
    const tr = el('tr');
    const th = el('th', peers.bins[b]);
    th.setAttribute('scope', 'row');
    tr.append(th, el('td', fmtInt(s.cls), 'num'), el('td', fmtInt(s.lines), 'num'), el('td', fmtInt(s.addressed), 'num'),
      el('td', fmtFr(frOf(s)), 'num'), el('td', fmtFr(peers.ref_bin[b]), 'num'), fiCell(enough(s) ? fiOf(s) : null),
      el('td', fmtChange(change), 'num'));
    body.append(tr);
  });
  const tot = sums(p, peers, clsIn(p, ALL), state.norm);
  const foot = $('#rf-xp-table tfoot tr');
  const cells = [fmtInt(tot.cls), fmtInt(tot.lines), fmtInt(tot.addressed), fmtFr(frOf(tot)), '–'];
  const tds = foot.querySelectorAll('td');
  cells.forEach((v, i) => (tds[i].textContent = v));
  tds[5].replaceWith(fiCell(fiOf(tot)));
  foot.querySelectorAll('td')[6].textContent = fmtChange(growth(bins, peers));
  put($('#rf-xp-note'), 'experience-note', { peers: state.norm ? peersName(state.norm) : msg('peers-all'),
    minBin: fmtInt(peers.min_bin_cls) });
}

/** A table cell for a feedback index, shaded green below 1 and red above. */
function fiCell(v: number | null, title?: string): HTMLTableCellElement {
  const td = el('td', '–', 'num rf-ratio');
  if (title) td.title = title;
  if (v === null || !Number.isFinite(v)) return td;
  td.textContent = fmtFi(v);
  const shade = ratioShade(v);
  td.classList.add(shade < 0 ? 'rf-ratio-lo' : 'rf-ratio-hi');
  td.style.setProperty('--rf-shade', String(Math.abs(shade)));
  return td;
}

/** Filters the directories and comments to the changes landed in half-year `h` (null: all). */
function setHalf(h: string | null) {
  state.half = h;
  window.__rf!.half = h;
  state.threadsShown = PAGE;
  state.noTextShown = PAGE;
  charts.trend?.update('none');
  renderPerCl();
  renderDirs();
  renderThreads();
}

/** Filters the directories and comments to the changes in comments-per-change column `b` (null: all). */
function setBin(b: number | null) {
  state.bin = b;
  window.__rf!.bin = b;
  state.threadsShown = PAGE;
  state.noTextShown = PAGE;
  renderPerCl();
  renderDirs();
  renderThreads();
}

/** The person's changes by how many addressed comments each drew, for the half-year
 * picked in the over-time chart if any. A column can be selected. */
function renderPerCl() {
  destroy('perCl');
  const p = state.person!;
  const t = theme();
  const counts = threadHistogram(p, state.half ?? ALL);
  // A column left empty by a new half-year drops its filter.
  if (state.bin !== null && !counts[state.bin]) {
    state.bin = null;
    window.__rf!.bin = null;
  }
  put($('#per-cl-sub'), 'per-cl-sub', { half: state.half ? halfName(state.half) : '' });
  const labels = Array.from({ length: THREAD_BINS }, (_, b) => threadBinLabel(b));
  // The column under the pointer, anywhere in its height, if it has changes.
  const colAt = (chart: Chart, e: ChartEvent) => {
    const hit = chart.getElementsAtEventForMode(e as unknown as Event, 'index', { intersect: false }, false)[0];
    return hit && counts[hit.index] > 0 ? hit.index : null;
  };
  charts.perCl = new Chart($<HTMLCanvasElement>('#rf-per-cl'), {
    type: 'bar',
    data: {
      labels,
      datasets: [{ data: counts, borderWidth: 0, categoryPercentage: 0.9, barPercentage: 1,
        backgroundColor: counts.map((_, b) => (state.bin === null || state.bin === b ? t.series[0] : t.muted)) }],
    },
    options: {
      maintainAspectRatio: false,
      animation: false,
      font: { family: t.font },
      onHover: (e, _els, chart) => {
        chart.canvas.classList.toggle('rf-pointable', colAt(chart, e) !== null);
      },
      onClick: (e, _els, chart) => {
        const b = colAt(chart, e);
        if (b !== null) setBin(state.bin === b ? null : b);
      },
      scales: {
        x: { ...axis(t, msg('axis-per-cl')), grid: { display: false } },
        y: { beginAtZero: true, ...axis(t, msg('axis-your-cls')), ticks: { color: t.text, font: { family: t.font }, precision: 0 } },
      },
      plugins: {
        legend: { display: false },
        tooltip: { intersect: false, mode: 'index',
          callbacks: { label: (i) => `${fmtInt(i.parsed.y ?? 0)} ${i.parsed.y === 1 ? 'change' : 'changes'}` } },
      },
    },
  });
}

/** Column `b` of the comments-per-change chart, in words: "3–5 addressed comments". */
function binName(b: number): string {
  const [lo, hi] = threadBinRange(b);
  return msg('bin-name', { none: hi === 0, one: lo === 1 && hi === 1, more: hi === null,
    n: hi === null || hi === lo ? fmtInt(lo) : `${fmtInt(lo)}–${fmtInt(hi)}` });
}

function renderDirs() {
  const p = state.person!;
  const peers = state.peers!;
  showHalfFilter('#rf-half-filter');
  showBinFilter('#rf-bin-filter');
  const roots = dirTree(p, peers, state.half ?? ALL, state.norm, state.bin);
  const body = $('#rf-dirs tbody');
  body.replaceChildren(...dirRows(roots, state.expanded, peers.min_cls).map(dirRow));
  // The comment section's directory picker lists every directory in the tree, in path order.
  const paths: string[] = [];
  const walk = (ns: DirNode[]) => ns.forEach((n) => (paths.push(n.path), walk(n.children)));
  walk(roots);
  paths.sort();
  const sel = $<HTMLSelectElement>('#rf-dir');
  sel.replaceChildren(sel.options[0] ?? el('option'));
  sel.options[0].value = '';
  for (const path of paths) {
    const o = el('option', path);
    o.value = path;
    sel.append(o);
  }
  sel.value = state.dir ?? '';
  if (state.dir !== null && sel.value === '') state.dir = null;
}

function selectDir(path: string) {
  state.dir = state.dir === path ? null : path;
  state.threadsShown = PAGE;
  state.noTextShown = PAGE;
  renderDirs();
  renderThreads();
  if (state.dir !== null) $('#comments').scrollIntoView({ block: 'start' });
}

function dirRow(r: DirRowView): HTMLTableRowElement {
  const tr = el('tr', undefined, `rf-dir-row rf-dir-${r.kind}`);
  tr.dataset.key = r.key;
  tr.dataset.depth = String(r.depth);
  if (r.kind === 'dir' && state.dir === r.node!.path) tr.setAttribute('aria-selected', 'true');
  const th = el('th');
  th.setAttribute('scope', 'row');
  const label = el('span', undefined, 'rf-dir-label');
  label.style.setProperty('--depth', String(r.depth));
  const name = r.kind === 'other' ? fragment('dirs-other', { n: fmtInt(r.count!) }).textContent!
    : r.kind === 'rest' ? fragment('dirs-rest', { dir: r.node!.name }).textContent! : r.node!.name;
  if (r.expandable) {
    const b = el('button', r.expanded ? '▾' : '▸', 'ar-toggle');
    b.type = 'button';
    b.setAttribute('aria-expanded', String(r.expanded));
    b.setAttribute('aria-label', `${r.expanded ? 'Collapse' : 'Expand'} ${r.kind === 'dir' ? r.node!.path : name}`);
    b.addEventListener('click', () => {
      if (state.expanded.has(r.key)) state.expanded.delete(r.key);
      else state.expanded.add(r.key);
      renderDirs();
    });
    label.append(b);
  } else {
    label.append(el('span', undefined, 'ar-toggle-space'));
  }
  if (r.kind === 'dir') {
    const b = el('button', name, 'rf-dir-pick');
    b.type = 'button';
    b.title = `${r.node!.path}: list its comments below`;
    b.addEventListener('click', () => selectDir(r.node!.path));
    label.append(b);
  } else {
    const s = el('span', name, 'rf-dir-group');
    s.title = r.kind === 'rest' ? `Files directly in ${r.node!.path}` : `${fmtInt(r.count!)} smaller entries`;
    label.append(s);
  }
  th.append(label);
  const s = r.stats;
  const few = r.fi === null ? msg('dirs-no-ratio', { n: fmtInt(state.peers!.min_cls) }) : undefined;
  const rate = el('td', fmtFr(r.fr), 'num');
  if (few) rate.title = few;
  tr.append(th, el('td', fmtInt(s.cls), 'num'), el('td', fmtInt(Math.round(s.lines)), 'num'), el('td', fmtInt(s.addressed), 'num'),
    rate, fiCell(r.fi, few), el('td', fmtInt(s.prior), 'num'));
  return tr;
}

function threadItem(r: ThreadRow): HTMLLIElement {
  const li = el('li', undefined, `quote rf-thread${r.praise ? ' quote-praise' : ''}`);
  const head = el('div', undefined, 'rf-thread-head');
  head.append(fragment('thread-meta', { date: dayLabel(r.day), file: r.file }));
  const tags = el('span', undefined, 'rf-tags');
  if (r.praise) tags.append(el('span', msg('thread-praise'), 'rf-tag rf-tag-praise'));
  head.append(tags);
  li.append(head);
  li.append(el('p', r.text!, 'rf-text'));
  li.append(link(commentUrl(r.cl, r.uuid), msg('thread-link')));
  return li;
}

/** A comment without stored text, as a row of the table below the list: the change, linked to the
 * comment where its id is known, the date and the file (or directory and count). */
function noTextRow(r: ThreadRow): HTMLTableRowElement {
  const tr = el('tr');
  const cl = el('td', undefined, 'num');
  cl.append(link(commentUrl(r.cl, r.uuid), String(Math.trunc(r.cl))));
  const path = el('td', undefined, 'rf-notext-path');
  path.append(r.count === undefined ? r.file : fragment('notext-path-count', { dir: r.file, n: fmtInt(r.count) }));
  tr.append(cl, el('td', dayLabel(r.day), 'num'), path);
  return tr;
}

/** Shows or hides one of the half-year filter lines (above the directories, and above the comments). */
function showHalfFilter(sel: string) {
  const filter = $(sel);
  filter.hidden = !state.half;
  if (state.half) put(filter.querySelector('.rf-filter-name')!, 'half-filter', { half: halfName(state.half) });
}

/** Shows or hides one of the comments-per-change filter lines. */
function showBinFilter(sel: string) {
  const filter = $(sel);
  filter.hidden = state.bin === null;
  if (state.bin !== null) put(filter.querySelector('.rf-filter-name')!, 'bin-filter', { bin: binName(state.bin) });
}

function renderThreads() {
  const p = state.person!;
  showHalfFilter('#rf-half-filter-comments');
  showBinFilter('#rf-bin-filter-comments');
  const rows = threadRows(p, state.half ?? ALL, state.dir, state.bin);
  put($('#comments-sub'), 'comments-sub', { n: fmtInt(threadsIn(rows)), dir: state.dir ?? '',
    half: state.half ? halfName(state.half) : '', bin: state.bin === null ? '' : binName(state.bin) });
  // Comments with text are listed; the rest go in a table at the end, each paged on its own.
  const withText = rows.filter((r) => r.text);
  const noText = rows.filter((r) => !r.text);
  const list = $('#rf-threads');
  list.replaceChildren(...withText.slice(0, state.threadsShown).map(threadItem));
  if (!rows.length) list.append(el('li', msg('threads-none'), 'quote-none'));
  list.hidden = !withText.length && noText.length > 0;
  showMore($<HTMLButtonElement>('#rf-threads-more'), withText.length, state.threadsShown);
  $('#rf-notext').hidden = !noText.length;
  $('#rf-notext-table tbody').replaceChildren(...noText.slice(0, state.noTextShown).map(noTextRow));
  showMore($<HTMLButtonElement>('#rf-notext-more'), noText.length, state.noTextShown);
}

function showMore(more: HTMLButtonElement, total: number, shown: number) {
  more.hidden = total <= shown;
  put(more, 'threads-more', { n: fmtInt(Math.min(PAGE, total - shown)) });
}

// ---- wiring

/** The norm the checkboxes pick, in the order e, d, o. */
function readNorm(): Norm {
  const on = new Set([...document.querySelectorAll<HTMLInputElement>('#rf-norm input:checked')].map((i) => i.value));
  return (['e', 'd', 'o'] as const).filter((k) => on.has(k)).join('') as Norm;
}

function init() {
  const form = $<HTMLFormElement>('#rf-find');
  const input = $<HTMLInputElement>('#rf-email');
  form.addEventListener('submit', (e) => {
    e.preventDefault();
    void lookup(input.value);
  });
  for (const b of document.querySelectorAll('#rf-half-clear, .rf-half-clear')) b.addEventListener('click', () => setHalf(null));
  for (const b of document.querySelectorAll('.rf-bin-clear')) b.addEventListener('click', () => setBin(null));
  for (const i of document.querySelectorAll<HTMLInputElement>('#rf-norm input')) {
    i.addEventListener('change', () => {
      state.norm = readNorm();
      window.__rf!.norm = state.norm;
      renderNorm();
    });
  }
  $<HTMLSelectElement>('#rf-dir').addEventListener('change', (e) => {
    const v = (e.target as HTMLSelectElement).value;
    state.dir = v === '' ? null : v;
    state.threadsShown = PAGE;
    state.noTextShown = PAGE;
    renderDirs();
    renderThreads();
  });
  $('#rf-threads-more').addEventListener('click', () => {
    state.threadsShown += PAGE;
    renderThreads();
  });
  $('#rf-notext-more').addEventListener('click', () => {
    state.noTextShown += PAGE;
    renderThreads();
  });
  const method = $<HTMLDetailsElement>('#method');
  method.addEventListener('toggle', () => renderMethod());
  if (location.hash === '#method') method.open = true;
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    renderIntro();
    renderMethod();
    if (!state.person) return;
    renderTrend();
    renderCompare();
    renderPerCl();
  });
  void getJson<Peers>(`${DATA}peers.json`).then((p) => {
    state.peers = p;
    window.__rf!.peers = p;
    if (!p) return;
    fillStatic(p);
    renderIntro();
    renderMethod();
  }).catch(() => {}).finally(() => {
    document.body.dataset.ready = '1';
  });
}

init();
