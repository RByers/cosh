// The Review Feedback page (review-feedback.html). Wording is in the HTML;
// this looks a person up by the address typed (never offering completions:
// the data is one file per person, named by a hash of the address), fills in
// the values and draws the charts. Comment text is untrusted and goes into the
// DOM only as text (SECURITY.md). Tone appears only as praise (ground rule 5).
// The address is never put in the URL.
import { Chart, Filler, type ChartDataset } from 'chart.js';
import { readTheme, type Theme } from './charts.ts';
import {
  bandOf,
  buildPerson,
  clsOf,
  commentUrl,
  dirTable,
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
    __rf?: { person: Person | null; peers: Peers | null; charts: Record<string, Chart> };
  }
}

const $ = <T extends Element = HTMLElement>(sel: string) => document.querySelector<T>(sel)!;
const DATA = 'review-feedback/';
const PAGE = 50;
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
  dir: null as number | null,
  praiseOnly: false,
  threadsShown: PAGE,
  allDirs: false,
};
const charts: Record<string, Chart> = {};
window.__rf = { person: null, peers: null, charts };

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
    state.allDirs = false;
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
  put($('#rf-change-note'), 'change-note', { ...vars, n: fmtInt(ch?.n ?? 0),
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
        x: { ...axis('change in feedback index per year'), grid: { display: false } },
        y: { beginAtZero: true, ...axis('contributors') },
      },
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: (i) => `${fmtInt(i.parsed.y ?? 0)} contributors` } },
      },
    },
  });
}

// ---- render

function render() {
  if (!state.person || !state.peers) return;
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
      pointBorderColor: t.series[0], pointRadius: 4, pointHoverRadius: 5, borderWidth: 2, tension: 0, spanGaps: true,
      fill: false, order: 0 },
  ];
  const names = hs.map((h) => halfName(h));
  charts.trend = new Chart($<HTMLCanvasElement>('#rf-trend'), {
    type: 'line',
    data: { labels: names, datasets },
    options: {
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: 'index', intersect: false },
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
  const rows = dirTable(p, ALL, state.kind);
  const body = $('#rf-dirs tbody');
  body.replaceChildren();
  const shown = state.allDirs ? rows : rows.slice(0, DIRS_SHOWN);
  for (const r of shown) {
    const tr = el('tr');
    tr.dataset.dir = String(r.index);
    if (state.dir === r.index) tr.setAttribute('aria-selected', 'true');
    const th = el('th');
    th.setAttribute('scope', 'row');
    const b = el('button', r.dir, 'rf-dir-pick');
    b.type = 'button';
    b.addEventListener('click', () => {
      state.dir = state.dir === r.index ? null : r.index;
      state.threadsShown = PAGE;
      renderDirs();
      renderThreads();
      if (state.dir !== null) $('#comments').scrollIntoView({ block: 'start' });
    });
    th.append(b);
    tr.append(th, el('td', fmtInt(r.cls), 'num'), el('td', fmtInt(r.threads), 'num'),
      el('td', fmtNum(r.expected, { maximumFractionDigits: 1 }), 'num'),
      el('td', r.expected > 0 ? fmtValue(r.threads / r.expected, 'd') : '–', 'num'), el('td', fmtInt(r.prior), 'num'));
    body.append(tr);
  }
  const more = $<HTMLButtonElement>('#rf-dirs-more');
  more.hidden = state.allDirs || rows.length <= DIRS_SHOWN;
  put(more, 'dirs-more', { n: fmtInt(rows.length) });
  // The comment section's directory picker lists the same directories.
  const sel = $<HTMLSelectElement>('#rf-dir');
  sel.replaceChildren(sel.options[0] ?? el('option'));
  sel.options[0].value = '';
  for (const r of rows) {
    const o = el('option', r.dir);
    o.value = String(r.index);
    sel.append(o);
  }
  sel.value = state.dir === null ? '' : String(state.dir);
  if (state.dir !== null && sel.value === '') state.dir = null;
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

function renderThreads() {
  const p = state.person!;
  const rows = threadRows(p, ALL, state.kind, state.dir, state.praiseOnly);
  put($('#comments-sub'), 'comments-sub', { n: fmtInt(rows.length), kind: state.kind,
    dir: state.dir === null ? '' : p.dirs[state.dir] });
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
    state.dir = v === '' ? null : Number(v);
    state.threadsShown = PAGE;
    renderDirs();
    renderThreads();
  });
  radio<string>('rf-show', (v) => {
    state.praiseOnly = v === 'praise';
    state.threadsShown = PAGE;
    renderThreads();
  });
  $('#rf-threads-more').addEventListener('click', () => {
    state.threadsShown += PAGE;
    renderThreads();
  });
  $('#rf-dirs-more').addEventListener('click', () => {
    state.allDirs = true;
    renderDirs();
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
