// The Feedback Index page (feedback-index.html). Wording is in the HTML;
// this looks a person up by the address typed (never offering completions:
// the data is one file per person, named by a hash of the address), fills in
// the values and draws the charts. Data goes into the DOM only as text
// (SECURITY.md). The address is never put in the URL.
import { Chart, Filler, type ChartDataset, type ChartEvent, type Plugin } from 'chart.js';
import { readTheme, withAlpha, type Theme } from './charts.ts';
import {
  afrShade,
  attachReviewers,
  binReached,
  binSums,
  buildPerson,
  clsIn,
  dirTable,
  fiOf,
  fr,
  frOf,
  growth,
  halves,
  halvesBetween,
  isoDay,
  latestDoubling,
  looksLikeEmail,
  percentileOf,
  periodSpan,
  personKey,
  quantile,
  ratioShade,
  reviewerRows,
  sums,
  tableRows,
  threadBinLabel,
  threadHistogram,
  threadsMarkdown,
  threadsUrl,
  THREAD_BINS,
  type Alias,
  type Peers,
  type Person,
  type ReviewerTable,
  type Shard,
  type TableRowView,
  type ThreadFile,
  type Top,
} from './feedback.ts';
import { fmtDay, fmtInt, fmtNum } from './format.ts';
import { fragment, msg, type Vars } from './text.ts';

Chart.register(Filler);

/** Replaces `target`'s contents with the template `key`. */
const put = (target: Element, key: string, vars: Vars = {}) => target.replaceChildren(fragment(key, vars));

declare global {
  interface Window {
    __rf?: { person: Person | null; peers: Peers | null; charts: Record<string, Chart>; half: string | null };
  }
}

const $ = <T extends Element = HTMLElement>(sel: string) => document.querySelector<T>(sel)!;
const DATA = 'review-feedback/';
/** The page's figures cover all the data; only the over-time chart splits it, by half-year. */
const ALL = 'all';

const state = {
  person: null as Person | null,
  peers: null as Peers | null,
  /** reviewers.json, loaded with the first person. */
  reviewers: null as ReviewerTable | null,
  /** The person's file key and half-years, for the comment download. */
  key: null as string | null,
  halves: [] as string[],
  /** The half-year picked in the over-time chart, filtering the comments-per-change chart. */
  half: null as string | null,
  /** The experience bin shown in "How it's changing". */
  cohortBin: 0,
  /** Keys of everyone's directory table's rows that are open (see tableRows). */
  allExpanded: new Set<string>(),
};
const charts: Record<string, Chart> = {};
window.__rf = { person: null, peers: null, charts, half: null };

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
/** An AFR: addressed comments per 100 lines. */
const fmtFr = (v: number | null | undefined) => (ok(v) ? fmtNum(v, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '–');
/** A large count, short ("27M", "761K"). */
const fmtBig = (v: number) => fmtNum(v, { notation: 'compact', maximumFractionDigits: v >= 1e3 && v < 1e4 ? 1 : 0 });
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
    const [peers, reviewers, top] = await Promise.all([
      state.peers ? Promise.resolve(state.peers) : getJson<Peers>(`${DATA}peers.json`),
      state.reviewers ? Promise.resolve(state.reviewers) : getJson<ReviewerTable>(`${DATA}reviewers.json`),
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
    const found = top && peers && reviewers && halvesOk && shards.every((s) => s)
      ? buildPerson(top.top, shards as Shard[], peers) : null;
    // Every figure about the person needs their reviewers' factors.
    if (found) await attachReviewers(found, reviewers!);
    state.peers = peers;
    state.reviewers = reviewers;
    window.__rf!.peers = peers;
    if (!found || !peers || !clsIn(found, ALL).length) {
      put(note, 'find-none', rangeVars(peers));
      return;
    }
    state.person = found;
    window.__rf!.person = found;
    state.key = top!.key;
    state.halves = top!.top.halves;
    state.half = null;
    window.__rf!.half = null;
    state.allExpanded = new Set();
    const cs = clsIn(found, ALL);
    put(note, 'find-done', { n: fmtInt(cs.length), from: dayLabel(cs[0][1]), to: dayLabel(cs.at(-1)![1]) });
    // The person's praise is on the Review Tone page, which opens their popup from the hash.
    const praise = note.querySelector<HTMLAnchorElement>('.rf-praise-link');
    if (praise) praise.href = `sentiment.html#person=${encodeURIComponent(raw.trim())}`;
    $('#rf-person').hidden = false;
    setupDownload();
    render();
    renderIntro();
    document.body.dataset.person = '1';
  } catch (e) {
    put(note, 'find-error', { error: String(e instanceof Error ? e.message : e) });
  }
}

// ---- the opening charts (no person needed), with the person's red line once one is shown

/** The colour of the person's line on the opening charts. */
const youColor = (t: Theme) => t.series[7];

/** The fan of every contributor's AFR by experience: the 10th–90th percentile and
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
    ...(you ? [{ label: msg('legend-you'), color: youColor(t) }] : []),
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

/** The AFR charts' y-axis: logarithmic, so a steady fall per doubling is a straight
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
  renderAllDirs();
  destroy('main');
  const t = theme();
  const p = state.person;
  // The person's AFR per bin, a rate of 0 drawn at the axis's bottom; hollow under min_bin_cls.
  const bins = p ? binSums(p, peers, ALL) : [];
  const you = bins.map((s) => (s.cls ? Math.max(frOf(s) ?? 0, FR_MIN) : null));
  const full = bins.map((s) => s.cls >= peers.min_bin_cls);
  fanLegend($('#rf-main-legend'), t, false, !!p);
  $('#rf-main-you').hidden = !p;
  const meds = peers.fr_bins.map((d) => (d.q ? quantile(d.q, 0.5) : null));
  const last = meds.reduce<number>((a, v, i) => (v !== null ? i : a), 0);
  put($('#rf-main-note'), 'main-note', { ...rangeVars(peers), minBin: fmtInt(peers.min_bin_cls), first: fmtFr(meds[0]),
    last: fmtFr(meds[last]), lastBin: peers.bins[last] });
  charts.main = new Chart($<HTMLCanvasElement>('#rf-main'), {
    type: 'line',
    data: {
      labels: peers.bins,
      datasets: [...fanDatasets(peers, t, false),
        ...(p ? [{ label: 'you', data: you, borderColor: youColor(t),
          backgroundColor: full.map((o) => (o ? youColor(t) : t.surface)), pointBorderColor: youColor(t),
          pointRadius: 4.5, pointHoverRadius: 5.5, borderWidth: 3, tension: 0, spanGaps: true, fill: false, order: 0 }] : [])],
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
  // The person's index over all their changes.
  const p = state.person;
  const you = p ? fiOf(sums(p, peers, clsIn(p, ALL))) : null;
  lineLegend($('#rf-fi-legend'), [{ label: msg('legend-fi'), color: t.series[0] },
    { label: msg('legend-fi-marks'), color: t.muted, dash: true },
    ...(you !== null ? [{ label: msg('legend-you-value', { v: fmtFi(you) }), color: youColor(t) }] : [])]);
  const ticks = [0.125, 0.25, 0.5, 1, 2, 4];
  charts.fiDist = new Chart($<HTMLCanvasElement>('#rf-fi-dist'), {
    type: 'line',
    data: {
      datasets: [
        { label: 'curve', data: d.curve.map(([x, y]) => ({ x, y })), borderColor: t.series[0], borderWidth: 2,
          backgroundColor: withAlpha(t.series[0], 0.18), fill: 'origin', pointRadius: 0, pointHoverRadius: 0, tension: 0.3 },
        mark(q(0.5), [5, 4]), mark(q(0.1), [2, 3]), mark(q(0.9), [2, 3]),
        ...(you !== null ? [{ ...mark(Math.min(Math.max(you, 0.125), 5.7), []), label: 'you', borderColor: youColor(t),
          borderWidth: 2.5 }] : []),
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

/** An AFR cell, shaded from light (little feedback per line) to dark blue (a lot). */
function afrCell(v: number | null, title?: string): HTMLTableCellElement {
  const td = el('td', fmtFr(v), 'num');
  if (title) td.title = title;
  if (v === null || !Number.isFinite(v)) return td;
  const shade = afrShade(v);
  td.classList.add('rf-afr');
  if (shade > 0.6) td.classList.add('rf-afr-dark');
  td.style.setProperty('--rf-afr', String(shade));
  return td;
}

/** Everyone's directory table, below the index's chart; with the person's columns once someone is shown. */
function renderAllDirs() {
  const peers = state.peers;
  if (!peers?.dir_table) return;
  const p = state.person;
  const table = $('#rf-all-dirs');
  table.classList.toggle('rf-with-you', !!p);
  const rows = tableRows(dirTable(peers, p, ALL), state.allExpanded, !!p, peers.min_cls);
  $('#rf-all-dirs tbody').replaceChildren(...rows.map((r) => allDirRow(r, !!p)));
  put($('#rf-all-dirs-note'), 'all-dirs-note', { ...rangeVars(peers), minDir: fmtInt(peers.min_dir_cls), you: !!p,
    minCls: fmtInt(peers.min_cls) });
}

function allDirRow(r: TableRowView, you: boolean): HTMLTableRowElement {
  const n = r.node;
  const tr = el('tr', undefined, `rf-dir-row rf-dir-${n ? n.kind : 'more'}`);
  tr.dataset.key = r.key;
  const th = el('th');
  th.setAttribute('scope', 'row');
  const label = el('span', undefined, 'rf-dir-label');
  label.style.setProperty('--depth', String(r.depth));
  const name = !n ? msg('dirs-more', { n: fmtInt(r.more!) })
    : n.kind === 'other' ? fragment('dirs-other', { n: fmtInt(n.count ?? 0) }).textContent!
      : n.kind === 'rest' ? fragment('dirs-rest', { dir: n.path.split('/').filter(Boolean).at(-1) + '/' }).textContent! : n.name;
  if (r.expandable) {
    const b = el('button', r.expanded ? '▾' : '▸', 'ar-toggle');
    b.type = 'button';
    b.setAttribute('aria-expanded', String(r.expanded));
    b.setAttribute('aria-label', `${r.expanded ? 'Collapse' : 'Expand'} ${n?.kind === 'dir' ? n.path : name}`);
    b.addEventListener('click', () => {
      if (state.allExpanded.has(r.key)) state.allExpanded.delete(r.key);
      else state.allExpanded.add(r.key);
      renderAllDirs();
    });
    label.append(b);
  } else {
    label.append(el('span', undefined, 'ar-toggle-space'));
  }
  const s = el('span', name, n?.kind === 'dir' ? 'rf-dir-name' : 'rf-dir-group');
  if (n?.kind === 'dir') s.title = n.path;
  else if (n?.kind === 'rest') s.title = `Files directly in ${n.path}`;
  label.append(s);
  th.append(label);
  tr.append(th);
  if (!n) {
    const td = el('td');
    td.colSpan = you ? 9 : 4;
    tr.append(td);
    return tr;
  }
  const a = n.all;
  tr.append(el('td', fmtBig(a.lines), 'num'), el('td', fmtBig(a.threads), 'num'), el('td', fmtBig(a.addressed), 'num'),
    afrCell(r.fr));
  if (you) {
    const y = n.you;
    const few = y.cls && r.youFi === null ? msg('dirs-no-ratio', { n: fmtInt(state.peers!.min_cls) }) : undefined;
    const peersFr = y.lines > 0 ? fmtFr((100 * y.expected) / y.lines) : '–';
    const cell = (v: string, cls = 'num rf-you-col') => el('td', y.cls ? v : '', cls);
    tr.append(cell(fmtInt(Math.round(y.lines)), 'num rf-you-col rf-you-start'), cell(fmtInt(y.threads)), cell(fmtInt(y.addressed)));
    const fr_ = y.cls ? afrCell(r.youFr, few) : el('td');
    const fi = y.cls ? fiCell(r.youFi, few ?? msg('dirs-peers', { v: peersFr })) : el('td');
    fr_.classList.add('rf-you-col');
    fi.classList.add('rf-you-col');
    tr.append(fr_, fi);
  }
  return tr;
}

// ---- the methodology (rendered when opened)

function renderMethod() {
  const peers = state.peers;
  if (!peers?.fr_bins || !$<HTMLDetailsElement>('#method').open) return;
  renderPeerGroups();
  renderNewcomers();
  renderSizes();
}

/** The methodology's case for comparing by reviewer: how much of the change-to-change spread in
 * feedback each peer group predicts, how widely directories and reviewers differ, and what drift is
 * left once reviewers and authors are accounted for. */
function renderPeerGroups() {
  for (const c of ['method', 'spread', 'drift']) destroy(c);
  const peers = state.peers!;
  const t = theme();
  const m = new Map(peers.method.map(([k, , p]) => [k, p]));
  const keys = ['d', 'r', 'dr', 'rd'].filter((k) => m.has(k));
  const pctLabel = (v: number) => `${fmtNum(v, { maximumFractionDigits: 1 })}%`;
  put($('#rf-method-note'), 'method-note', { d: pctLabel(m.get('d') ?? 0), r: pctLabel(m.get('r') ?? 0),
    dr: pctLabel(m.get('dr') ?? 0), rd: pctLabel(m.get('rd') ?? 0) });
  charts.method = new Chart($<HTMLCanvasElement>('#rf-method-chart'), {
    type: 'bar',
    data: { labels: keys.map((k) => msg(`model-${k}`)),
      datasets: [{ data: keys.map((k) => m.get(k)!), borderWidth: 0, categoryPercentage: 0.8, barPercentage: 1,
        backgroundColor: keys.map((k) => (k === 'r' ? t.series[0] : withAlpha(t.series[0], 0.45))) }] },
    options: {
      indexAxis: 'y',
      maintainAspectRatio: false,
      animation: false,
      font: { family: t.font },
      scales: { x: { beginAtZero: true, ...axis(t, msg('axis-method')) }, y: { ...axis(t, ''), grid: { display: false },
        title: { display: false } } },
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: (i) => pctLabel(i.parsed.x ?? 0) } } },
    },
  });

  // Reviewers within each busy directory: their factors' 10th–90th percentile and middle half, and the
  // directory's own factor as a mark.
  const dr = peers.dir_revs;
  const first = dr[0];
  put($('#rf-spread-note'), 'spread-note', { n: fmtInt(dr.length), min: fmtInt(peers.min_spread_exp),
    dir: first?.[0] ?? '', dirF: fmtFi(first?.[1]), lo: fmtFi(first?.[3][0]), hi: fmtFi(first?.[3][4]) });
  const mark = (f: number) => [f / 1.04, f * 1.04] as [number, number];
  // Ticks at a few round factors only.
  const roundTick = (v: string | number) => ([0.01, 0.03, 0.1, 0.3, 1, 3].includes(Number(v)) ? fmtFi(Number(v)) : '');
  charts.spread = new Chart($<HTMLCanvasElement>('#rf-spread-chart'), {
    type: 'bar',
    data: { labels: dr.map((r) => r[0]), datasets: [
      // A lower `order` draws on top: the directory's mark over the middle half over the 10th–90th.
      { data: dr.map((r) => [r[3][0], r[3][4]] as [number, number]), backgroundColor: withAlpha(t.series[0], 0.3),
        borderWidth: 0, grouped: false, categoryPercentage: 0.8, barPercentage: 1, order: 2 },
      { data: dr.map((r) => [r[3][1], r[3][3]] as [number, number]), backgroundColor: withAlpha(t.series[0], 0.7),
        borderWidth: 0, grouped: false, categoryPercentage: 0.8, barPercentage: 1, order: 1 },
      { data: dr.map((r) => mark(r[1])), backgroundColor: t.series[1], borderWidth: 0, grouped: false,
        categoryPercentage: 0.8, barPercentage: 1, order: 0 },
    ] },
    options: {
      indexAxis: 'y',
      maintainAspectRatio: false,
      animation: false,
      font: { family: t.font },
      scales: { x: { type: 'logarithmic', min: 0.01, max: 4, ...axis(t, msg('axis-factor')),
        ticks: { color: t.text, autoSkip: false, maxRotation: 0, callback: roundTick } },
      y: { grid: { display: false }, ticks: { color: t.text, autoSkip: false } } },
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: (i) => {
        const r = dr[i.dataIndex];
        return [`10th–90th percentile of ${fmtInt(r[2])} reviewers ${fmtFi(r[3][0])} – ${fmtFi(r[3][4])}`,
          `middle half ${fmtFi(r[3][1])} – ${fmtFi(r[3][3])}, median ${fmtFi(r[3][2])}`,
          `the directory ${fmtFi(r[1])}`][i.datasetIndex];
      } } } },
    },
  });

  // Drift: per half-year, everyone's addressed comments over what experience and size expect, and over
  // what experience, size, reviewers and authors expect.
  const d = peers.drift;
  const last = d.at(-1);
  const steady = d.slice(0, -1).map((r) => r[3]);
  put($('#rf-drift-note'), 'drift-note', { lo: fmtFi(Math.min(...steady)), hi: fmtFi(Math.max(...steady)),
    upTo: halfName(d.at(-2)?.[0] ?? ''), last: halfName(last?.[0] ?? ''), lastRaw: fmtFi(last?.[2]),
    lastFull: fmtFi(last?.[3]) });
  lineLegend($('#rf-drift-legend'), [{ label: msg('drift-raw'), color: t.series[1] },
    { label: msg('drift-full'), color: t.series[0] }]);
  charts.drift = new Chart($<HTMLCanvasElement>('#rf-drift-chart'), {
    type: 'line',
    data: { labels: d.map((r) => shortMonth(Date.UTC(+r[0].slice(0, 4), r[0].endsWith('1') ? 0 : 6, 1) / 86_400_000)), datasets: [
      { data: d.map((r) => r[2]), borderColor: t.series[1], backgroundColor: t.series[1], borderWidth: 2, pointRadius: 2 },
      { data: d.map((r) => r[3]), borderColor: t.series[0], backgroundColor: t.series[0], borderWidth: 2.5, pointRadius: 3 },
      { data: d.map(() => 1), borderColor: t.grid, borderDash: [4, 4], borderWidth: 1, pointRadius: 0, pointHoverRadius: 0 },
    ] },
    options: {
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: 'index', intersect: false },
      font: { family: t.font },
      scales: { x: { ...axis(t, ''), grid: { display: false }, title: { display: false } },
        y: { min: 0.6, max: 1.4, ...axis(t, msg('axis-drift')), ticks: { color: t.text, callback: (v) => fmtFi(Number(v)) } } },
      plugins: { legend: { display: false }, tooltip: {
        filter: (i) => i.datasetIndex < 2,
        callbacks: { title: (items) => halfName(d[items[0].dataIndex][0]),
          label: (i) => `${msg(i.datasetIndex ? 'drift-full' : 'drift-raw')}: ${fmtFi(i.parsed.y)}` } } },
    },
  });
}

/** An experience bin's range of CLs landed on main, e.g. "9–16 CLs". */
function cohortBinName(peers: Peers, b: number): string {
  const e = peers.bin_edges;
  return b === 0 ? msg('cohort-bin', { first: true, hi: fmtInt(e[0]) })
    : msg('cohort-bin', { first: false, lo: fmtInt(e[b - 1] + 1), hi: fmtInt(e[b]) });
}

/** The experience bins "How it's changing" offers: those with medians in COHORT_MIN_YEARS years or more. */
const COHORT_MIN_YEARS = 3;

function fillCohortBins(peers: Peers) {
  const sel = $<HTMLSelectElement>('#rf-cohort-bin');
  if (sel.options.length) return;
  peers.cohorts.forEach((rows, b) => {
    if (b >= peers.bin_edges.length || rows.filter((r) => r[4] !== null).length < COHORT_MIN_YEARS) return;
    const o = el('option', cohortBinName(peers, b));
    o.value = String(b);
    sel.append(o);
  });
  sel.value = String(state.cohortBin);
}

function renderNewcomers() {
  destroy('newcomers');
  const peers = state.peers!;
  const t = theme();
  fillCohortBins(peers);
  const rows = peers.cohorts[state.cohortBin] ?? [];
  if (!rows.length) return;
  put($('#rf-newcomers-note'), 'newcomers-note', { bin: cohortBinName(peers, state.cohortBin),
    minBin: fmtInt(peers.min_bin_cls), people: fmtInt(rows.reduce((a, r) => a + r[1], 0)),
    lastYear: String(new Date((peers.end - 1) * 86_400_000).getUTCFullYear()) });
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
  const you = state.person ? growth(binSums(state.person, peers, ALL), peers) : null;
  const marker = (x: number, color: string, label: string, dash: number[]): ChartDataset<'line', { x: number; y: number }[]> =>
    ({ label, data: [{ x: growthX(x), y: 0 }, { x: growthX(x), y: top * 1.05 }], borderColor: color, borderWidth: 2,
      borderDash: dash, pointRadius: 0, pointHoverRadius: 0, fill: false });
  lineLegend($('#rf-growth-legend'), [{ label: msg('legend-growth'), color: t.series[0] },
    { label: msg('legend-growth-median'), color: t.muted, dash: true },
    ...(you !== null ? [{ label: msg('legend-you-value', { v: fmtChange(you) }), color: youColor(t) }] : [])]);
  const ticks = [-75, -50, -25, 0, 50, 100, 200];
  charts.growth = new Chart($<HTMLCanvasElement>('#rf-growth'), {
    type: 'line',
    data: {
      datasets: [
        { label: 'curve', data: g.curve.map(([x, y]) => ({ x: growthX(x), y })), borderColor: t.series[0], borderWidth: 2,
          backgroundColor: withAlpha(t.series[0], 0.18), fill: 'origin', pointRadius: 0,
          pointHoverRadius: 0, tension: 0.3 },
        marker(g.median, t.muted, 'median', [5, 4]),
        ...(you !== null ? [marker(you, youColor(t), 'you', [])] : []),
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
  renderXpTable();
  renderReviewers();
  renderPerCl();
}

function renderSummary() {
  const p = state.person!;
  const peers = state.peers!;
  const cs = clsIn(p, ALL);
  const s = sums(p, peers, cs);
  const fi = fiOf(s);
  const eligible = s.cls >= peers.min_cls;
  put($('#summary-sub'), 'summary-sub', { ...rangeVars(peers), eligible, minCls: fmtInt(peers.min_cls) });
  const tile = (id: string, text: string, sub = '') => {
    $(`#${id} .tile-value`).textContent = text;
    const e = document.querySelector(`#${id} .tile-sub`);
    if (e) e.textContent = sub;
  };
  tile('rf-tile-cls', fmtInt(s.cls), msg('tile-lines', { n: fmtInt(s.lines) }));
  tile('rf-tile-threads', fmtInt(s.addressed));
  tile('rf-tile-fr', fmtFr(frOf(s)), msg('tile-fr-sub'));
  const d = peers.fi[ALL];
  tile('rf-tile-fi', fmtFi(fi), eligible && d?.q && fi !== null
    ? msg('tile-fi-rank', { p: pct(percentileOf(d.q, fi)), n: fmtInt(d.n) }) : msg('tile-fi-none'));
  const g = latestDoubling(p, binSums(p, peers, ALL), peers);
  const r = g?.reached;
  tile('rf-tile-growth', fmtChange(g?.change), g === null
    ? msg('tile-growth-none', { min: fmtInt(peers.min_bin_cls) })
    : msg('tile-growth-sub', { from: peers.bins[g.from], to: peers.bins[g.to], per: g.steps > 1,
      day: !r ? '–' : msg(r[1] ? 'tile-growth-on' : 'as-of-by', { day: dayLabel(r[0]) }), typical: fmtChange(g.typical) }));
  const facts = $('#rf-facts');
  if (p.first && p.org) put(facts, 'you-facts', { first: monthLabel(p.first), org: p.org });
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
  const per = hs.map((h) => sums(p, peers, clsIn(p, h)));
  const you = per.map((s) => (s.cls ? fiOf(s) : null));
  const full = per.map((s) => s.cls >= peers.min_cls);
  const q = (h: string, f: number) => { const d = peers.fi[h]; return d?.q ? quantile(d.q, f) : null; };
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

/** The person's AFR per experience bin, when they reached each, and everyone's median there. */
function renderXpTable() {
  const p = state.person!;
  const peers = state.peers!;
  const bins = binSums(p, peers, ALL);
  // The table: the bins with changes, when the person reached each, and everyone's median there.
  const body = $('#rf-xp-table tbody');
  body.replaceChildren();
  const reached = binReached(p, peers.bin_edges);
  bins.forEach((s, b) => {
    if (!s.cls) return;
    const r = reached[b];
    const asOf = !r ? '–' : r[1] ? dayLabel(r[0]) : msg('as-of-by', { day: dayLabel(r[0]) });
    const tr = el('tr');
    const th = el('th', peers.bins[b]);
    th.setAttribute('scope', 'row');
    tr.append(th, el('td', asOf), el('td', fmtInt(s.cls), 'num'), el('td', fmtInt(s.lines), 'num'),
      el('td', fmtInt(s.addressed), 'num'), el('td', fmtFr(frOf(s)), 'num'), el('td', fmtFr(peers.ref_bin[b]), 'num'));
    body.append(tr);
  });
  const tot = sums(p, peers, clsIn(p, ALL));
  const cells = ['', fmtInt(tot.cls), fmtInt(tot.lines), fmtInt(tot.addressed), fmtFr(frOf(tot)), '–'];
  $('#rf-xp-table tfoot tr').querySelectorAll('td').forEach((td, i) => (td.textContent = cells[i]));
  put($('#rf-xp-note'), 'experience-note');
}

/** The person's approvers: their changes each approved, the feedback on them, the reviewer's factor
 * (how much feedback their approvals draw, everyone's changes counted) and the person's index on them. */
function renderReviewers() {
  const p = state.person!;
  const peers = state.peers!;
  const rows = reviewerRows(p, peers, ALL);
  const body = $('#rf-revs tbody');
  body.replaceChildren();
  for (const r of rows) {
    const tr = el('tr');
    const th = el('th', r.email);
    th.setAttribute('scope', 'row');
    const few = r.cls < peers.min_bin_cls;
    tr.append(th, el('td', fmtInt(r.cls), 'num'), el('td', fmtInt(r.addressed), 'num'),
      el('td', few ? '–' : fmtFr(fr(r.addressed, r.lines)), 'num'),
      el('td', fmtFi(r.factor), 'num'), el('td', fmtInt(r.approved), 'num'),
      few ? el('td', '–', 'num') : fiCell(r.expected > 0 ? r.addressed / r.expected : null));
    body.append(tr);
  }
  const none = clsIn(p, ALL).filter((c) => !c[6].length).length;
  put($('#rf-revs-note'), 'revs-note', { n: fmtInt(rows.length), none: fmtInt(none), hasNone: none > 0,
    noneF: fmtFi(peers.rev_none), min: fmtInt(peers.min_bin_cls) });
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

/** Filters the comments-per-change chart to the changes landed in half-year `h` (null: all). */
function setHalf(h: string | null) {
  state.half = h;
  window.__rf!.half = h;
  charts.trend?.update('none');
  renderPerCl();
}

/** The person's changes by how many addressed comments each drew, for the half-year
 * picked in the over-time chart if any. */
function renderPerCl() {
  destroy('perCl');
  const p = state.person!;
  const t = theme();
  const counts = threadHistogram(p, state.half ?? ALL);
  const filter = $('#rf-half-filter');
  filter.hidden = !state.half;
  if (state.half) put(filter.querySelector('.rf-filter-name')!, 'half-filter', { half: halfName(state.half) });
  const labels = Array.from({ length: THREAD_BINS }, (_, b) => threadBinLabel(b));
  charts.perCl = new Chart($<HTMLCanvasElement>('#rf-per-cl'), {
    type: 'bar',
    data: {
      labels,
      datasets: [{ data: counts, borderWidth: 0, categoryPercentage: 0.9, barPercentage: 1, backgroundColor: t.series[0] }],
    },
    options: {
      maintainAspectRatio: false,
      animation: false,
      font: { family: t.font },
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

// ---- downloading the comments

/** A template as one line of text (the HTML wraps long ones). */
const line = (key: string, vars: Vars = {}) => msg(key, vars).replace(/\s+/g, ' ').trim();

/** The download's half-year choices: every half-year the person has changes in; by default the
 * latest two (about the past year). */
function setupDownload() {
  const from = $<HTMLSelectElement>('#rf-dl-from');
  const to = $<HTMLSelectElement>('#rf-dl-to');
  for (const sel of [from, to]) {
    sel.replaceChildren(...state.halves.map((h) => {
      const o = el('option', halfName(h));
      o.value = h;
      return o;
    }));
  }
  from.value = state.halves.at(-2) ?? state.halves[0] ?? '';
  to.value = state.halves.at(-1) ?? '';
  $('#rf-dl-note').replaceChildren();
}

/** The coach's instructions (the dl-prompt template) as Markdown. */
function promptMarkdown(): string {
  const out: string[] = [];
  const text = (e: Element) => (e.textContent ?? '').replace(/\s+/g, ' ').trim();
  for (const e of fragment('dl-prompt').children) {
    if (e.localName === 'h2') out.push(`## ${text(e)}`, '');
    else if (e.localName === 'ul') out.push(...[...e.children].map((li) => `- ${text(li)}`), '');
    else out.push(text(e), '');
  }
  return out.join('\n').trim();
}

/** Fetches the person's threads for the chosen half-years and saves them as one file. Comment text
 * goes only into that file, never into the page. */
async function download() {
  const note = $('#rf-dl-note');
  const key = state.key;
  const peers = state.peers;
  if (!key || !peers) return;
  const from = $<HTMLSelectElement>('#rf-dl-from').value;
  const to = $<HTMLSelectElement>('#rf-dl-to').value;
  const json = $<HTMLSelectElement>('#rf-dl-format').value === 'json';
  const prompt = $<HTMLInputElement>('#rf-dl-prompt').checked;
  const hs = halvesBetween(state.halves, from, to);
  put(note, 'dl-loading', { n: fmtInt(hs.length) });
  try {
    const files = (await Promise.all(hs.map(async (h) => {
      const r = await fetch(threadsUrl(key, h, peers.end));
      if (r.status === 404) return null;
      if (!r.ok) throw new Error(`${h}: ${r.status}`);
      const f = (await r.json()) as ThreadFile;
      if (f?.v !== 1 || f.half !== h || !Array.isArray(f.cls)) throw new Error(`${h}: unexpected file`);
      return f;
    }))).filter((f): f is ThreadFile => f !== null);
    const md = threadsMarkdown(files, {
      owner: line('dl-owner'),
      addressed: line('dl-addressed'),
      notAddressed: line('dl-not-addressed'),
      unresolved: line('dl-unresolved'),
      change: line('dl-change'),
      commitMsg: line('dl-commit-msg'),
      line: (n) => line('dl-line', { n: String(n) }),
      patchSet: (n) => line('dl-patch-set', { n: String(n) }),
      landed: (day, lines) => line('dl-landed', { day, lines }),
    });
    if (!md.threads) {
      put(note, 'dl-none');
      return;
    }
    const [a, b] = from <= to ? [from, to] : [to, from];
    const today = new Date().toISOString().slice(0, 10);
    const body = json
      ? JSON.stringify({ v: 1, downloaded: today, files }, null, 1)
      : [line('dl-title', { from: halfName(a), to: halfName(b) }), '', line('dl-about', { day: today }), '',
        ...(prompt ? [promptMarkdown(), ''] : []), md.md].join('\n');
    const blob = new Blob([body], { type: json ? 'application/json' : 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const link = el('a');
    link.href = url;
    link.download = `chromium-review-comments-${a}-${b}.${json ? 'json' : 'md'}`;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
    put(note, 'dl-done', { threads: fmtInt(md.threads), cls: fmtInt(md.cls) });
  } catch (e) {
    put(note, 'dl-error', { error: String(e instanceof Error ? e.message : e) });
  }
}

// ---- wiring

function init() {
  const form = $<HTMLFormElement>('#rf-find');
  const input = $<HTMLInputElement>('#rf-email');
  form.addEventListener('submit', (e) => {
    e.preventDefault();
    void lookup(input.value);
  });
  $<HTMLFormElement>('#rf-dl').addEventListener('submit', (e) => {
    e.preventDefault();
    void download();
  });
  $('#rf-half-clear').addEventListener('click', () => setHalf(null));
  const method = $<HTMLDetailsElement>('#method');
  method.addEventListener('toggle', () => renderMethod());
  $<HTMLSelectElement>('#rf-cohort-bin').addEventListener('change', (e) => {
    state.cohortBin = Number((e.target as HTMLSelectElement).value);
    renderNewcomers();
  });
  if (location.hash === '#method') method.open = true;
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    renderIntro();
    renderMethod();
    if (!state.person) return;
    renderTrend();
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
