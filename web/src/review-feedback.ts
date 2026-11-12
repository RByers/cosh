// The Review Feedback page (feedback-index.html). Wording is in the HTML;
// this looks a person up by the address typed (never offering completions:
// the data is one file per person, named by a hash of the address), fills in
// the values and draws the charts. Comment text is untrusted and goes into the
// DOM only as text (SECURITY.md). Tone appears only as praise (ground rule 5).
// The address is never put in the URL.
import { Chart, Filler, type ChartDataset, type ChartEvent, type Plugin } from 'chart.js';
import { readTheme, type Theme } from './charts.ts';
import {
  bandOf,
  buildPerson,
  clsOf,
  commentUrl,
  dirTree,
  groupKey,
  halves,
  isoDay,
  looksLikeEmail,
  metricOf,
  okFor,
  percentileOf,
  periodSpan,
  personKey,
  quantile,
  rangeOf,
  ratioShade,
  threadRows,
  cohortYears,
  trendGroup,
  valueFor,
  xpBreakdown,
  type Alias,
  type Shard,
  type Top,
  type Corr,
  type CountField,
  type DirNode,
  type DirStats,
  type Dist,
  type Kind,
  type Metric,
  type PeerOrg,
  type Peers,
  type Person,
  type TenureBy,
  type ThreadRow,
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
const PAGE = 50;
/** Directory rows per level before an "N more" row, as on the Value Exchange page. */
const DIRS_SHOWN = 15;
/** The page's figures always cover all the data; only the over-time chart splits it, by half-year. */
const ALL = 'all';

const state = {
  person: null as Person | null,
  peers: null as Peers | null,
  kind: 't' as Kind,
  corr: 'd' as Corr,
  tenure: 'time' as TenureBy,
  org: 'all' as PeerOrg,
  /** The selected directory's path; comments are listed from it and below. */
  dir: null as string | null,
  /** The half-year picked in the over-time chart, filtering the directories and comments. */
  half: null as string | null,
  threadsShown: PAGE,
  /** Keys of the directory rows that are open (see dirRows). */
  expanded: new Set<string>(),
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

/** A value of the current measure: per change, or against a norm. */
function fmtValue(v: number | null | undefined, corr: Corr = state.corr): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return '–';
  const s = fmtNum(v, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return corr === 'n' ? s : `${s}×`;
}
const pct = (v: number) => fmtNum(v, { style: 'percent', maximumFractionDigits: 0 });
const ORDINAL = new Intl.PluralRules('en', { type: 'ordinal' });
const SUFFIX: Record<string, string> = { one: 'st', two: 'nd', few: 'rd', other: 'th' };
/** A share (0–1) as an ordinal percentile: "64th". */
const ordinal = (v: number) => {
  const n = Math.round(v * 100);
  return `${n}${SUFFIX[ORDINAL.select(n)]}`;
};

const monthOf = (day: number, year: boolean) => new Intl.DateTimeFormat('en-GB',
  { month: 'long', year: year ? 'numeric' : undefined, timeZone: 'UTC' }).format(new Date(day * 86_400_000));
/** The month a range starts in, and the one it ends in (`to` is exclusive). The script
 * trims the ranges to whole months, give or take the first week. */
const fromMonth = (from: number) => from;
const toMonth = (to: number) => to - 1;

/** A half-year's name in the over-time chart, cut to the dates the current measure covers. */
function halfName(h: string): string {
  const [from, to] = periodSpan(h, rangeOf(state.peers!, state.kind));
  const year = h.slice(0, 4);
  const [whole0, whole1] = periodSpan(h, [-Infinity, Infinity]);
  const a = monthOf(fromMonth(from), false);
  const b = monthOf(toMonth(to), false);
  if (a !== monthOf(fromMonth(whole0), false) || b !== monthOf(toMonth(whole1), false))
    return msg('period-part', { from: a, to: b, year });
  return msg(h.endsWith('H1') ? 'period-half1' : 'period-half2', { year });
}

/** The dates the data covers, by name: the first and last month, the last day, and the
 * month the addressed measures start (empty until peers.json has loaded). */
function rangeVars(peers: Peers | null): Record<string, string> {
  if (!peers) return { from: '', to: '', 'last-day': '', 'addr-from': '' };
  return {
    from: monthOf(fromMonth(peers.start), true),
    to: monthOf(toMonth(peers.end), true),
    'last-day': dayLabel(peers.end - 1),
    'addr-from': monthOf(fromMonth(peers.addr_start), true),
  };
}

/** The dates in the page's prose (`<span data-rf-range="from">` …). */
function fillRange(peers: Peers) {
  const vars = rangeVars(peers);
  for (const e of document.querySelectorAll<HTMLElement>('[data-rf-range]')) e.textContent = vars[e.dataset.rfRange!] ?? '';
}

/** The peer group's name: who, and their tenure band (null when the person's is unknown). */
function groupName(by: TenureBy, org: PeerOrg, band: string | null): string {
  const who = msg(`org-${org}`);
  if (by === 'dir') return msg('group-dir', { org: who });
  return band ? msg(`group-${by}`, { org: who, band: bandName(band) }) : msg('group-none');
}

const BAND_NAMES: Record<string, string> = {
  '<1y': 'under 1 year', '1-2y': '1–2 years', '2-5y': '2–5 years', '5-10y': '5–10 years', '10y+': '10 years or more',
  '<50': 'under 50', '50-199': '50–199', '200-499': '200–499', '500-999': '500–999', '1000+': '1,000 or more',
};
const bandName = (b: string) => BAND_NAMES[b] ?? b;

const metric = (): Metric => metricOf(state.kind, state.corr);
const theme = () => readTheme();

function destroy(name: string) {
  charts[name]?.destroy();
  delete charts[name];
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
    const found = top && peers && halvesOk && shards.every((s) => s)
      ? buildPerson(top.top, shards as Shard[], peers) : null;
    state.peers = peers;
    window.__rf!.peers = peers;
    if (!found || !peers) {
      put(note, 'find-none', rangeVars(peers));
      return;
    }
    state.person = found;
    window.__rf!.person = found;
    state.dir = null;
    state.half = null;
    window.__rf!.half = null;
    state.expanded = new Set();
    put(note, 'find-done', { n: fmtInt(found.cls.length), from: dayLabel(found.cls[0][1]), to: dayLabel(found.cls.at(-1)![1]) });
    // The person's praise is on the Review Tone page, which opens their popup from the hash.
    const praise = note.querySelector<HTMLAnchorElement>('.rf-praise-link');
    if (praise) praise.href = `sentiment.html#person=${encodeURIComponent(raw.trim())}`;
    $('#rf-person').hidden = false;
    render();
    document.body.dataset.person = '1';
  } catch (e) {
    put(note, 'find-error', { error: String(e instanceof Error ? e.message : e) });
  }
}

// ---- the opening card (no person needed)

function renderIntro() {
  const peers = state.peers;
  if (!peers?.cohorts) return;
  destroy('cohorts');
  destroy('change');
  const t = theme();
  const m = metric();
  const g = trendGroup(state.tenure, state.org);
  const org = state.org === 'all' ? '' : msg(`org-name-${state.org}`);
  const [from, to] = rangeOf(peers, state.kind);
  const vars = { kind: state.kind, corr: state.corr, dirxp: state.tenure === 'dir', org, min: fmtInt(peers.min_cohort),
    limited: state.kind === 'a' || state.tenure === 'dir',
    minCls: fmtInt(peers.min_cls), from: monthOf(fromMonth(from), true), to: monthOf(toMonth(to), true) };
  put($('#rf-cohorts-note'), 'cohorts-note', vars);
  const curves = peers.cohorts[g]?.[m] ?? {};
  const step = peers.cohort_step;
  const lines = cohortYears(curves, peers.cohort_from)
    .map((y, i) => ({ year: y, color: t.series[i], pts: curves[String(y)] }));
  const legend = $('#rf-cohort-legend');
  legend.replaceChildren(...lines.map((l) => {
    const li = el('li');
    const sw = el('span', undefined, 'swatch');
    sw.style.setProperty('--color', l.color);
    li.append(sw, document.createTextNode(`started in ${l.year}`));
    return li;
  }));
  const axis = (title: string) => ({ grid: { color: t.grid }, title: { display: true, text: title, color: t.text },
    ticks: { color: t.text, font: { family: t.font } } });
  charts.cohorts = new Chart($<HTMLCanvasElement>('#rf-cohorts'), {
    type: 'line',
    data: {
      datasets: lines.map((l) => ({ label: String(l.year), data: l.pts.map(([b, v]) => ({ x: b + step / 2, y: v })),
        borderColor: l.color, backgroundColor: l.color, borderWidth: 2, pointRadius: 2.5, pointHoverRadius: 4,
        tension: 0, fill: false })),
    },
    options: {
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: 'nearest', intersect: false },
      font: { family: t.font },
      scales: {
        x: { type: 'linear', min: 0, ...axis('years since first commit on main') },
        y: { beginAtZero: true, ...axis(msg('axis-feedback')),
          ticks: { color: t.text, font: { family: t.font }, callback: (v) => fmtValue(Number(v)) } },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: () => '',
            label: (i) => {
              const l = lines[i.datasetIndex];
              const [b, , n] = l.pts[i.dataIndex];
              const yrs = (x: number) => fmtNum(x, { maximumFractionDigits: 1 });
              return `Started in ${l.year}, ${yrs(b)}–${yrs(b + step)} years in: median ${fmtValue(i.parsed.y)} (${fmtInt(n)} people)`;
            },
          },
        },
      },
    },
  });

  const ch = peers.change[g]?.[m];
  const edges = peers.change_edges;
  // Bins of reduction: below 0 the feedback grew.
  const abs = (x: number) => fmtInt(Math.abs(x));
  const labels = edges.slice(0, -1).map((lo, i) => {
    const hi = edges[i + 1];
    if (i === 0) return `grew ${abs(hi)}%+`;
    if (i === edges.length - 2) return `fell ${abs(lo)}%+`;
    return hi <= 0 ? `grew ${abs(hi)}–${abs(lo)}%` : `fell ${abs(lo)}–${abs(hi)}%`;
  });
  // The first whole calendar year the measure covers.
  const start = new Date(from * 86_400_000);
  const fromYear = start.getUTCFullYear() + (start.getUTCMonth() === 0 && start.getUTCDate() === 1 ? 0 : 1);
  put($('#rf-change-note'), 'change-note', { ...vars, n: fmtInt(ch?.n ?? 0), people: fmtInt(ch?.people ?? 0),
    minYearCls: fmtInt(peers.min_year_cls), fromYear,
    median: ch?.median == null ? '–' : pct(Math.abs(ch.median) / 100), fell: (ch?.median ?? 0) >= 0 });
  charts.change = new Chart($<HTMLCanvasElement>('#rf-change'), {
    type: 'bar',
    data: {
      labels,
      datasets: [{ data: ch?.counts ?? [], backgroundColor: edges.slice(0, -1).map((e) => (e >= 0 ? t.series[0] : t.muted)),
        borderWidth: 0, categoryPercentage: 0.9, barPercentage: 1 }],
    },
    options: {
      maintainAspectRatio: false,
      animation: false,
      font: { family: t.font },
      scales: {
        x: { ...axis('change in feedback index from the year before'), grid: { display: false } },
        y: { beginAtZero: true, ...axis('contributor-years') },
      },
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: (i) => `${fmtInt(i.parsed.y ?? 0)} contributor-years` } },
      },
    },
  });
  renderSizes(axis);
}

/** The opening card's size chart: the feedback index by change size, four ways;
 * the "Adjusted for" choice is drawn bold. */
function renderSizes(axis: (title: string) => object) {
  destroy('size');
  const peers = state.peers!;
  const s = peers.sizes?.[state.kind];
  const labels = peers.size_labels;
  if (!s || !labels) return;
  const t = theme();
  const [from, to] = rangeOf(peers, state.kind);
  put($('#rf-size-note'), 'size-note', { kind: state.kind, n: fmtInt(s.n),
    from: monthOf(fromMonth(from), true), to: monthOf(toMonth(to), true),
    perCl: fmtNum(s.avgPerCl, { maximumFractionDigits: 2 }), perKLine: fmtNum(s.avgPerKLine, { maximumFractionDigits: 1 }) });
  const bold = ({ n: 'perCl', s: 'size', d: 'dir' } as const)[state.corr];
  const ways = (['perCl', 'perKLine', 'size', 'dir'] as const).map((k, i) => ({ k, color: t.series[i], label: msg(`size-line-${k}`) }));
  const legend = $('#rf-size-legend');
  legend.replaceChildren(...ways.map((w) => {
    const li = el('li');
    const sw = el('span', undefined, 'swatch');
    sw.style.setProperty('--color', w.color);
    li.append(sw, document.createTextNode(w.label));
    return li;
  }));
  charts.size = new Chart($<HTMLCanvasElement>('#rf-size'), {
    type: 'line',
    data: {
      labels,
      datasets: ways.map((w) => ({ label: w.label, data: s[w.k], borderColor: w.color, backgroundColor: w.color,
        borderWidth: w.k === bold ? 3.5 : 1.5, pointRadius: w.k === bold ? 3.5 : 2, pointHoverRadius: 5, tension: 0,
        fill: false, spanGaps: false })),
    },
    options: {
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: 'index', intersect: false },
      font: { family: t.font },
      scales: {
        x: { ...axis('lines changed'), grid: { display: false } },
        y: { type: 'logarithmic', min: 0.05, max: 6, ...axis(msg('axis-feedback')),
          ticks: { color: t.text, font: { family: t.font }, autoSkip: false,
            callback: (v) => ([0.05, 0.1, 0.2, 0.5, 1, 2, 5].includes(Number(v)) ? fmtValue(Number(v), 'd') : '') } },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: (items) => `${labels[items[0].dataIndex]} lines changed: ${fmtInt(s.cls[items[0].dataIndex])} changes`,
            label: (i) => `${ways[i.datasetIndex].label}: ${fmtValue(i.parsed.y ?? 0, 'd')}`,
          },
        },
      },
    },
  });
}

// ---- render

function render() {
  if (!state.person || !state.peers) return;
  if (state.half && !(clsOf(state.person.periods[state.half], state.kind) > 0)) state.half = null;
  window.__rf!.half = state.half;
  renderSummary();
  renderTrend();
  renderXp();
  renderDirs();
  renderThreads();
}

function renderSummary() {
  const p = state.person!;
  const peers = state.peers!;
  const vals = p.periods[ALL];
  const m = metric();
  put($('#summary-sub'), 'summary-sub', { corr: state.corr, kind: state.kind, tenure: state.tenure,
    eligible: okFor(vals, state.kind), minCls: peers.min_cls });
  const tile = (id: string, text: string, sub?: string) => {
    $(`#${id} .tile-value`).textContent = text;
    const s = document.querySelector(`#${id} .tile-sub`);
    if (s) s.textContent = sub ?? '';
  };
  const g = groupKey(state.tenure, state.org, vals);
  // Where the person's counts sit among the same peers'.
  const rank = (field: CountField, v: number) => {
    const d = g ? peers.counts?.[ALL]?.[g]?.[field] : undefined;
    return d?.q ? msg('tile-count-rank', { p: ordinal(percentileOf(d.q, v)) }) : '';
  };
  const cls = clsOf(vals, state.kind);
  tile('rf-tile-cls', fmtInt(cls), rank(state.kind === 't' ? 'cls' : 'acls', cls));
  $('#rf-tile-threads .tile-label').textContent = msg(`tile-threads-${state.kind}`);
  const threads = state.kind === 't' ? vals?.threads ?? 0 : vals?.addressed ?? 0;
  tile('rf-tile-threads', fmtInt(threads), rank(state.kind === 't' ? 'threads' : 'addressed', threads));
  const you = valueFor(state.tenure, vals, m);
  tile('rf-tile-you', fmtValue(you));
  const dist: Dist | undefined = g ? peers.dist[ALL]?.[g]?.[m] : undefined;
  const name = groupName(state.tenure, state.org, bandOf(state.tenure, vals));
  if (dist?.q) {
    tile('rf-tile-peers', fmtValue(quantile(dist.q, 0.5)), msg('tile-peers-sub', {
      group: name, n: fmtInt(dist.n), lo: fmtValue(quantile(dist.q, 0.25)), hi: fmtValue(quantile(dist.q, 0.75)) }));
    tile('rf-tile-rank', you === null ? '–' : pct(percentileOf(dist.q, you)));
  } else {
    tile('rf-tile-peers', '–', name);
    tile('rf-tile-rank', '–');
  }
  const facts = $('#rf-facts');
  if (vals && p.first) {
    put(facts, 'you-facts', { first: monthLabel(p.first), ten: vals.ten ? bandName(vals.ten) : '–',
      prior: fmtInt(Math.round(vals.prior)), org: vals.org });
  } else facts.replaceChildren();
}

function renderTrend() {
  destroy('trend');
  const p = state.person!;
  const peers = state.peers!;
  const t: Theme = theme();
  const m = metric();
  // The half-years the measure covers.
  const [from, to] = rangeOf(peers, state.kind);
  const hs = halves(peers.periods).filter((h) => { const [a, b] = periodSpan(h, [from, to]); return a < b; });
  const q = (h: string, f: number) => {
    const g = groupKey(state.tenure, state.org, p.periods[h]);
    const d = g ? peers.dist[h]?.[g]?.[m] : undefined;
    return d?.q ? quantile(d.q, f) : null;
  };
  const you = hs.map((h) => valueFor(state.tenure, p.periods[h], m));
  const ok = hs.map((h) => okFor(p.periods[h], state.kind));
  const band = (f: number, label = '') => ({ label, data: hs.map((h) => q(h, f)), borderWidth: 0, pointRadius: 0,
    pointHoverRadius: 0, tension: 0, spanGaps: true });
  const datasets: ChartDataset<'line', (number | null)[]>[] = [
    { ...band(0.9), backgroundColor: t.grid, fill: '+1', order: 4 },
    { ...band(0.1), fill: false, order: 4 },
    { ...band(0.75), backgroundColor: t.baseline, fill: '+1', order: 3 },
    { ...band(0.25), fill: false, order: 3 },
    { ...band(0.5, 'peers'), borderColor: t.muted, borderWidth: 1.5, borderDash: [5, 4], fill: false, order: 1 },
    { label: 'you', data: you, borderColor: t.series[0], backgroundColor: ok.map((o) => (o ? t.series[0] : t.surface)),
      pointBorderColor: t.series[0], pointRadius: 4, pointHoverRadius: 5, pointHitRadius: 10, borderWidth: 2, tension: 0,
      spanGaps: true, fill: false, order: 0 },
  ];
  const names = hs.map((h) => halfName(h));
  // The dot under the pointer, if it is one of the person's (dataset 5) with a value. Chart.js's
  // own event carries chart coordinates; the native one gave no hits under a real click.
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
        x: { grid: { color: t.grid }, title: { display: true, text: msg('axis-half'), color: t.text },
          ticks: { color: t.text, font: { family: t.font }, maxRotation: 0, autoSkip: true } },
        y: { beginAtZero: true, grid: { color: t.grid }, title: { display: true, text: msg('axis-feedback'), color: t.text },
          ticks: { color: t.text, font: { family: t.font }, callback: (v) => fmtValue(Number(v)) } },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          filter: (i) => i.datasetIndex >= 4,
          callbacks: {
            label: (i) => {
              const h = hs[i.dataIndex];
              if (i.datasetIndex === 5) {
                const n = clsOf(p.periods[h], state.kind);
                return n ? `You: ${fmtValue(i.parsed.y)} (${fmtInt(n)} changes)` : 'You: no changes';
              }
              return `Peers: median ${fmtValue(i.parsed.y)}, middle half ${fmtValue(q(h, 0.25))} – ${fmtValue(q(h, 0.75))}`;
            },
          },
        },
      },
    },
  });
}

/** Filters the directories and comments to the changes landed in half-year `h` (null: all). */
function setHalf(h: string | null) {
  state.half = h;
  window.__rf!.half = h;
  state.threadsShown = PAGE;
  charts.trend?.update('none');
  renderDirs();
  renderThreads();
}

function renderXp() {
  destroy('xp');
  const p = state.person!;
  const peers = state.peers!;
  const t = theme();
  const m = metric();
  put($('#experience-sub'), 'experience-sub');
  const mine = xpBreakdown(p, ALL, m);
  const bands = peers.bands[ALL]?.[m] ?? [];
  const labels = peers.xp.map((x) => x);
  const you = mine.map((b) => (b.cls >= 1 && b.den > 0 ? b.obs / b.den : null));
  const datasets: ChartDataset<'line', (number | null)[]>[] = [
    { label: '', data: bands.map((b) => (b.q ? quantile(b.q, 0.75) : null)), borderWidth: 0, pointRadius: 0,
      pointHoverRadius: 0, backgroundColor: t.baseline, fill: '+1', tension: 0, order: 3 },
    { label: '', data: bands.map((b) => (b.q ? quantile(b.q, 0.25) : null)), borderWidth: 0, pointRadius: 0,
      pointHoverRadius: 0, fill: false, tension: 0, order: 3 },
    { label: 'all', data: bands.map((b) => b.pooled), borderColor: t.muted, borderDash: [5, 4], borderWidth: 1.5,
      pointRadius: 0, fill: false, tension: 0, order: 1 },
    { label: 'you', data: you, borderColor: t.series[0], backgroundColor: t.series[0], pointRadius: 4, borderWidth: 2,
      spanGaps: true, fill: false, tension: 0, order: 0 },
  ];
  charts.xp = new Chart($<HTMLCanvasElement>('#rf-xp'), {
    type: 'line',
    data: { labels, datasets },
    options: {
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: 'index', intersect: false },
      font: { family: t.font },
      scales: {
        x: { grid: { color: t.grid }, title: { display: true, text: 'your earlier commits in the directory', color: t.text },
          ticks: { color: t.text, font: { family: t.font } } },
        y: { beginAtZero: true, grid: { color: t.grid }, title: { display: true, text: msg('axis-feedback'), color: t.text },
          ticks: { color: t.text, font: { family: t.font }, callback: (v) => fmtValue(Number(v)) } },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          filter: (i) => i.datasetIndex >= 2,
          callbacks: {
            label: (i) => (i.datasetIndex === 3 ? `You: ${fmtValue(i.parsed.y)}` : `All authors: ${fmtValue(i.parsed.y)}`),
          },
        },
      },
    },
  });
  const body = $('#rf-xp-table tbody');
  body.replaceChildren();
  peers.xp.forEach((label, b) => {
    const tr = el('tr');
    tr.append(el('th', label), el('td', fmtNum(mine[b].cls, { maximumFractionDigits: 1 }), 'num'),
      el('td', fmtInt(mine[b].obs), 'num'), el('td', fmtValue(you[b]), 'num'), el('td', fmtValue(bands[b]?.pooled), 'num'));
    tr.firstElementChild!.setAttribute('scope', 'row');
    body.append(tr);
  });
  $('#rf-xp-note-q').textContent = '; the shaded band is the middle half of authors with at least one and a half changes in the band';
}

function renderDirs() {
  const p = state.person!;
  put($('#directories-sub'), 'directories-sub', { corr: state.corr });
  $('#rf-dirs-typical').title = msg(`dirs-typical-${state.kind}`).replace(/\s+/g, ' ').trim();
  showHalfFilter('#rf-half-filter');
  const roots = dirTree(p, state.half ?? ALL, state.kind);
  const body = $('#rf-dirs tbody');
  body.replaceChildren(...dirRows(roots).map(dirRow));
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

/** One visible row of the directory tree: a directory, a directory's own files
 * ("rest of"), or the smaller entries of a level ("N more"). */
interface DirRowView {
  key: string;
  kind: 'dir' | 'rest' | 'other';
  depth: number;
  node?: DirNode;
  /** Changes: unknown for "N more", where one change can touch several entries. */
  stats: Omit<DirStats, 'cls'> & { cls: number | null };
  expandable: boolean;
  expanded: boolean;
  count?: number;
}

type DirItem = { kind: 'dir' | 'rest'; node: DirNode; stats: DirStats };

/** The rows to show, given `state.expanded`. Like the Value Exchange page's
 * directory chart: each level lists DIRS_SHOWN entries, then an "N more" row
 * that opens into the next ones; a directory with subdirectories opens into
 * them plus a "rest of" row for its own files. */
function dirRows(roots: DirNode[]): DirRowView[] {
  const out: DirRowView[] = [];
  const order = (a: DirItem, b: DirItem) => b.stats.cls - a.stats.cls || b.stats.threads - a.stats.threads ||
    (a.kind === b.kind ? (a.node.path < b.node.path ? -1 : 1) : a.kind === 'dir' ? -1 : 1);
  const emit = (it: DirItem, depth: number) => {
    if (it.kind === 'rest') {
      out.push({ key: `r:${it.node.path}`, kind: 'rest', depth, node: it.node, stats: it.stats, expandable: false, expanded: false });
      return;
    }
    const n = it.node;
    const key = `d:${n.path}`;
    const expandable = n.children.length > 0;
    const open = expandable && state.expanded.has(key);
    out.push({ key, kind: 'dir', depth, node: n, stats: n, expandable, expanded: open });
    if (!open) return;
    const items: DirItem[] = n.children.map((c) => ({ kind: 'dir', node: c, stats: c }));
    if (n.own) items.push({ kind: 'rest', node: n, stats: n.own });
    group(items.sort(order), depth + 1, key, 0);
  };
  const group = (items: DirItem[], depth: number, parentKey: string, offset: number) => {
    const head = items.slice(0, DIRS_SHOWN);
    const tail = items.slice(DIRS_SHOWN);
    for (const it of head) emit(it, depth);
    if (!tail.length) return;
    const key = `o:${parentKey}:${offset + DIRS_SHOWN}`;
    const open = state.expanded.has(key);
    out.push({
      key, kind: 'other', depth, expandable: true, expanded: open, count: tail.length,
      stats: {
        cls: null,
        threads: tail.reduce((s, it) => s + it.stats.threads, 0),
        expected: tail.reduce((s, it) => s + it.stats.expected, 0),
        prior: Math.max(...tail.map((it) => it.stats.prior)),
      },
    });
    if (open) group(tail, depth + 1, key, offset + DIRS_SHOWN);
  };
  group(roots.map((n): DirItem => ({ kind: 'dir', node: n, stats: n })).sort(order), 0, 'root', 0);
  return out;
}

function selectDir(path: string) {
  state.dir = state.dir === path ? null : path;
  state.threadsShown = PAGE;
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
    const t = el('button', r.expanded ? '▾' : '▸', 'ar-toggle');
    t.type = 'button';
    t.setAttribute('aria-expanded', String(r.expanded));
    t.setAttribute('aria-label', `${r.expanded ? 'Collapse' : 'Expand'} ${r.kind === 'dir' ? r.node!.path : name}`);
    t.addEventListener('click', () => {
      if (state.expanded.has(r.key)) state.expanded.delete(r.key);
      else state.expanded.add(r.key);
      renderDirs();
    });
    label.append(t);
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
    s.title = r.kind === 'rest' ? `Files directly in ${r.node!.path}` : `${fmtInt(r.count!)} more, smaller entries`;
    label.append(s);
  }
  th.append(label);
  const s = r.stats;
  const ratio = el('td', '–', 'num rf-ratio');
  if (s.expected > 0) {
    const v = s.threads / s.expected;
    ratio.textContent = fmtValue(v, 'd');
    const shade = ratioShade(v);
    ratio.classList.add(shade < 0 ? 'rf-ratio-lo' : 'rf-ratio-hi');
    ratio.style.setProperty('--rf-shade', String(Math.abs(shade)));
  }
  tr.append(th, el('td', s.cls === null ? '–' : fmtInt(s.cls), 'num'), el('td', fmtInt(s.threads), 'num'),
    el('td', fmtNum(s.expected, { maximumFractionDigits: 1 }), 'num'), ratio, el('td', fmtInt(s.prior), 'num'));
  return tr;
}

function threadItem(r: ThreadRow): HTMLLIElement {
  const li = el('li', undefined, `quote rf-thread${r.praise ? ' quote-praise' : ''}`);
  const head = el('div', undefined, 'rf-thread-head');
  head.append(fragment('thread-meta', { date: dayLabel(r.day), file: r.file }));
  const tags = el('span', undefined, 'rf-tags');
  // Only the positive label: "not addressed" reads as ignored feedback, when such
  // threads usually needed no change.
  if (r.addressed) tags.append(el('span', msg('thread-addressed'), 'rf-tag rf-tag-on'));
  if (r.praise) tags.append(el('span', msg('thread-praise'), 'rf-tag rf-tag-praise'));
  head.append(tags);
  li.append(head);
  li.append(r.text ? el('p', r.text, 'rf-text') : el('p', msg('thread-no-text'), 'rf-text muted'));
  li.append(link(commentUrl(r.cl, r.uuid), msg(r.uuid ? 'thread-link' : 'thread-link-cl')));
  return li;
}

/** Shows or hides one of the half-year filter lines (above the directories, and above the comments). */
function showHalfFilter(sel: string) {
  const filter = $(sel);
  filter.hidden = !state.half;
  if (state.half) put(filter.querySelector('.rf-filter-name')!, 'half-filter', { half: halfName(state.half) });
}

function renderThreads() {
  const p = state.person!;
  showHalfFilter('#rf-half-filter-comments');
  const rows = threadRows(p, state.half ?? ALL, state.kind, state.dir);
  put($('#comments-sub'), 'comments-sub', { n: fmtInt(rows.length), kind: state.kind, dir: state.dir ?? '',
    half: state.half ? halfName(state.half) : '' });
  const list = $('#rf-threads');
  list.replaceChildren(...rows.slice(0, state.threadsShown).map(threadItem));
  if (!rows.length) list.append(el('li', msg('threads-none'), 'quote-none'));
  const more = $<HTMLButtonElement>('#rf-threads-more');
  more.hidden = rows.length <= state.threadsShown;
  put(more, 'threads-more', { n: fmtInt(Math.min(PAGE, rows.length - state.threadsShown)) });
}


// ---- wiring

function radio<T extends string>(name: string, onChange: (v: T) => void) {
  for (const i of document.querySelectorAll<HTMLInputElement>(`input[name="${name}"]`))
    i.addEventListener('change', () => onChange(i.value as T));
}

function init() {
  const form = $<HTMLFormElement>('#rf-find');
  const input = $<HTMLInputElement>('#rf-email');
  form.addEventListener('submit', (e) => {
    e.preventDefault();
    void lookup(input.value);
  });
  for (const b of document.querySelectorAll('#rf-half-clear, .rf-half-clear')) b.addEventListener('click', () => setHalf(null));
  radio<Kind>('rf-kind', (v) => {
    state.kind = v;
    state.threadsShown = PAGE;
    renderIntro();
    render();
  });
  radio<Corr>('rf-corr', (v) => {
    state.corr = v;
    renderIntro();
    if (!state.person) return;
    renderSummary();
    renderTrend();
    renderXp();
  });
  const peersChanged = () => {
    renderIntro();
    if (!state.person) return;
    renderSummary();
    renderTrend();
  };
  $<HTMLSelectElement>('#rf-tenure').addEventListener('change', (e) => {
    state.tenure = (e.target as HTMLSelectElement).value as TenureBy;
    peersChanged();
  });
  $<HTMLSelectElement>('#rf-org').addEventListener('change', (e) => {
    state.org = (e.target as HTMLSelectElement).value as PeerOrg;
    peersChanged();
  });
  $<HTMLSelectElement>('#rf-dir').addEventListener('change', (e) => {
    const v = (e.target as HTMLSelectElement).value;
    state.dir = v === '' ? null : v;
    state.threadsShown = PAGE;
    renderDirs();
    renderThreads();
  });
  $('#rf-threads-more').addEventListener('click', () => {
    state.threadsShown += PAGE;
    renderThreads();
  });
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    renderIntro();
    if (!state.person) return;
    renderTrend();
    renderXp();
  });
  void getJson<Peers>(`${DATA}peers.json`).then((p) => {
    state.peers = p;
    window.__rf!.peers = p;
    if (!p) return;
    $('#rf-min-cls').textContent = fmtInt(p.min_cls);
    fillRange(p);
    renderIntro();
  }).catch(() => {}).finally(() => {
    document.body.dataset.ready = '1';
  });
}

init();
