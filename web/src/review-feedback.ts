// The Review Feedback page (review-feedback.html). Wording is in the HTML;
// this looks a person up by the address typed (never offering completions:
// the data is one file per person, named by a hash of the address), fills in
// the values and draws the charts. Comment text is untrusted and goes into the
// DOM only as text (SECURITY.md). Tone appears only as praise (ground rule 5).
// The address is never put in the URL.
import { Chart, Filler, type ChartDataset } from 'chart.js';
import { readTheme, type Theme } from './charts.ts';
import {
  buildPerson,
  commentUrl,
  dirTable,
  groupKey,
  halves,
  isoDay,
  looksLikeEmail,
  metricOf,
  percentileOf,
  personKey,
  quantile,
  threadRows,
  valueFor,
  xpBreakdown,
  years,
  type Alias,
  type Shard,
  type Top,
  type Corr,
  type Dist,
  type Kind,
  type Metric,
  type PeerChoice,
  type Peers,
  type Person,
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

const state = {
  person: null as Person | null,
  peers: null as Peers | null,
  period: 'all',
  kind: 't' as Kind,
  corr: 'd' as Corr,
  peer: 'all' as PeerChoice,
  dir: null as number | null,
  praiseOnly: false,
  threadsShown: PAGE,
  praiseShown: 10,
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
const weekStart = (w: string) => {
  const [y, n] = w.split('-W').map(Number);
  const jan4 = Date.UTC(y, 0, 4);
  const mon = jan4 - ((new Date(jan4).getUTCDay() + 6) % 7) * 86_400_000;
  return mon + (n - 1) * 7 * 86_400_000;
};

/** A value of the current measure: per change, or against a norm. */
function fmtValue(v: number | null | undefined, corr: Corr = state.corr): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return '–';
  const s = fmtNum(v, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return corr === 'n' ? s : `${s}×`;
}
const pct = (v: number) => fmtNum(v, { style: 'percent', maximumFractionDigits: 0 });
const pct1 = (v: number) => fmtNum(v, { style: 'percent', minimumFractionDigits: 1, maximumFractionDigits: 1 });

function periodName(p: string): string {
  const last = state.peers ? halves(state.peers.periods).at(-1) : undefined;
  if (p === 'all') return msg('period-all');
  if (p.length === 4) {
    if (p === '2023') return msg('period-year-h2', { year: p });
    if (last && p === last.slice(0, 4)) return msg('period-year-now', { year: p });
    return msg('period-year', { year: p });
  }
  const year = p.slice(0, 4);
  if (p.endsWith('H1')) return msg('period-half1', { year });
  return p === last ? msg('period-half2-now', { year }) : msg('period-half2', { year });
}

function groupName(choice: PeerChoice, band: string | null): string {
  if (choice === 'ten') return band ? msg('group-ten', { band: bandName(band) }) : msg('group-ten-none');
  return msg(`group-${choice}`);
}

const BAND_NAMES: Record<string, string> = {
  '<1y': 'under 1 year', '1-2y': '1–2 years', '2-5y': '2–5 years', '5-10y': '5–10 years', '10y+': '10 years or more',
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
    put(note, 'find-none');
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
      put(note, 'find-none');
      return;
    }
    state.person = found;
    window.__rf!.person = found;
    state.dir = null;
    state.allDirs = false;
    put(note, 'find-done', { n: fmtInt(found.cls.length), from: dayLabel(found.cls[0][1]), to: dayLabel(found.cls.at(-1)![1]) });
    fillPeriods();
    $('main').hidden = false;
    render();
    document.body.dataset.person = '1';
  } catch (e) {
    put(note, 'find-error', { error: String(e instanceof Error ? e.message : e) });
  }
}

function fillPeriods() {
  const sel = $<HTMLSelectElement>('#rf-period');
  const peers = state.peers!;
  const p = state.person!;
  const has = (period: string) => p.periods[period] !== undefined;
  sel.replaceChildren();
  for (const period of ['all', ...years(peers.periods).reverse(), ...halves(peers.periods).reverse()]) {
    if (!has(period)) continue;
    const o = el('option', periodName(period));
    o.value = period;
    sel.append(o);
  }
  if (!has(state.period)) state.period = 'all';
  sel.value = state.period;
}

// ---- render

function render() {
  if (!state.person || !state.peers) return;
  renderSummary();
  renderTrend();
  renderXp();
  renderDirs();
  renderThreads();
  renderPraise();
}

function renderSummary() {
  const p = state.person!;
  const peers = state.peers!;
  const vals = p.periods[state.period];
  const m = metric();
  put($('#summary-sub'), 'summary-sub', { corr: state.corr, kind: state.kind, peers: state.peer,
    eligible: vals?.ok ?? false, minCls: peers.min_cls });
  const tile = (id: string, text: string, sub?: string) => {
    $(`#${id} .tile-value`).textContent = text;
    const s = document.querySelector(`#${id} .tile-sub`);
    if (s) s.textContent = sub ?? '';
  };
  tile('rf-tile-cls', fmtInt(vals?.cls ?? 0));
  $('#rf-tile-threads .tile-label').textContent = msg(`tile-threads-${state.kind}`);
  tile('rf-tile-threads', fmtInt(state.kind === 't' ? vals?.threads ?? 0 : vals?.addressed ?? 0));
  const you = valueFor(state.peer, vals, m);
  tile('rf-tile-you', fmtValue(you));
  const g = groupKey(state.peer, vals);
  const dist: Dist | undefined = g ? peers.dist[state.period]?.[g]?.[m] : undefined;
  if (dist?.q) {
    tile('rf-tile-peers', fmtValue(quantile(dist.q, 0.5)), msg('tile-peers-sub', {
      group: groupName(state.peer, vals?.ten ?? null), n: fmtInt(dist.n),
      lo: fmtValue(quantile(dist.q, 0.25)), hi: fmtValue(quantile(dist.q, 0.75)) }));
    tile('rf-tile-rank', you === null ? '–' : pct(percentileOf(dist.q, you)));
  } else {
    tile('rf-tile-peers', '–', groupName(state.peer, vals?.ten ?? null));
    tile('rf-tile-rank', '–');
  }
  const facts = $('#rf-facts');
  if (vals && p.first) {
    put(facts, 'you-facts', { first: monthLabel(p.first), ten: vals.ten ? bandName(vals.ten) : '–', org: vals.org });
  } else facts.replaceChildren();
}

function renderTrend() {
  destroy('trend');
  const p = state.person!;
  const peers = state.peers!;
  const t: Theme = theme();
  const m = metric();
  const hs = halves(peers.periods);
  const q = (h: string, f: number) => {
    const g = groupKey(state.peer, p.periods[h]) ?? (state.peer === 'ten' ? null : state.peer);
    const d = g ? peers.dist[h]?.[g]?.[m] : undefined;
    return d?.q ? quantile(d.q, f) : null;
  };
  const you = hs.map((h) => valueFor(state.peer, p.periods[h], m));
  const ok = hs.map((h) => p.periods[h]?.ok ?? false);
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
  const names = hs.map((h) => periodName(h));
  charts.trend = new Chart($<HTMLCanvasElement>('#rf-trend'), {
    type: 'line',
    data: { labels: names, datasets },
    options: {
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: 'index', intersect: false },
      font: { family: t.font },
      scales: {
        x: { grid: { color: t.grid }, ticks: { color: t.text, font: { family: t.font }, maxRotation: 0, autoSkip: true } },
        y: { beginAtZero: true, grid: { color: t.grid },
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
                const v = p.periods[h];
                return v ? `You: ${fmtValue(i.parsed.y)} (${fmtInt(v.cls)} changes)` : 'You: no changes';
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
  const mine = xpBreakdown(p, state.period, m);
  const bands = peers.bands[state.period]?.[m] ?? [];
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
        y: { beginAtZero: true, grid: { color: t.grid },
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
  const rows = dirTable(p, state.period, state.kind);
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
  if (r.addressed !== null) tags.append(el('span', msg(r.addressed ? 'thread-addressed' : 'thread-not-addressed'),
    `rf-tag ${r.addressed ? 'rf-tag-on' : ''}`));
  if (r.praise) tags.append(el('span', msg('thread-praise'), 'rf-tag rf-tag-praise'));
  head.append(tags);
  li.append(head);
  li.append(r.text ? el('p', r.text, 'rf-text') : el('p', msg('thread-no-text'), 'rf-text muted'));
  li.append(link(commentUrl(r.cl, r.uuid), msg(r.uuid ? 'thread-link' : 'thread-link-cl')));
  return li;
}

function renderThreads() {
  const p = state.person!;
  const rows = threadRows(p, state.period, state.kind, state.dir, state.praiseOnly);
  put($('#comments-sub'), 'comments-sub', { n: fmtInt(rows.length), kind: state.kind,
    dir: state.dir === null ? '' : p.dirs[state.dir] });
  const list = $('#rf-threads');
  list.replaceChildren(...rows.slice(0, state.threadsShown).map(threadItem));
  if (!rows.length) list.append(el('li', msg('threads-none'), 'quote-none'));
  const more = $<HTMLButtonElement>('#rf-threads-more');
  more.hidden = rows.length <= state.threadsShown;
  put(more, 'threads-more', { n: fmtInt(Math.min(PAGE, rows.length - state.threadsShown)) });
}

function renderPraise() {
  const p = state.person!;
  const peers = state.peers!;
  const [w0, w1] = peers.tone_weeks;
  const from = weekStart(w0);
  const to = weekStart(w1) + 6 * 86_400_000;
  put($('#praise-sub'), 'praise-sub', { from: fmtDay(new Date(from)), to: fmtDay(new Date(to)) });
  $('#rf-tile-received .tile-value').textContent = fmtInt(p.tone.received);
  $('#rf-tile-praise .tile-value').textContent = p.tone.received
    ? msg('praise-share', { n: fmtInt(p.tone.praise), share: pct1(p.tone.praise / p.tone.received) }) : fmtInt(p.tone.praise);
  // Tone peers: everyone or the same tenure. Orgs get no tone figures.
  const isOrg = state.peer.startsWith('org:');
  const g = state.peer === 'ten' && p.tone.ten ? `ten:${p.tone.ten}` : 'all';
  const d = peers.tone[g];
  $('#rf-tile-praise-peers .tile-value').textContent = d?.q ? pct1(quantile(d.q, 0.5)) : '–';
  $('#rf-tile-praise-peers .tile-sub').textContent = msg('praise-peers-sub', {
    group: groupName(g === 'all' ? 'all' : 'ten', p.tone.ten), n: fmtInt(d?.n ?? 0), min: peers.min_received });
  const note = $('#rf-praise-note');
  if (isOrg) put(note, 'praise-org-note');
  else note.replaceChildren();
  const list = $('#rf-praise');
  list.replaceChildren();
  for (const [cl, uuid, day, text] of p.praise.slice(0, state.praiseShown)) {
    const li = el('li', undefined, 'quote quote-praise');
    li.append(el('p', text, 'rf-text'), el('span', `${dayLabel(day)} · `, 'muted'), link(commentUrl(cl, uuid), msg('thread-link')));
    list.append(li);
  }
  if (!p.praise.length) list.append(el('li', msg('praise-none'), 'quote-none'));
  const more = $<HTMLButtonElement>('#rf-praise-more');
  more.hidden = p.praise.length <= state.praiseShown;
  put(more, 'threads-more', { n: fmtInt(Math.min(PAGE, p.praise.length - state.praiseShown)) });
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
  $<HTMLSelectElement>('#rf-period').addEventListener('change', (e) => {
    state.period = (e.target as HTMLSelectElement).value;
    state.threadsShown = PAGE;
    render();
  });
  radio<Kind>('rf-kind', (v) => {
    state.kind = v;
    state.threadsShown = PAGE;
    render();
  });
  radio<Corr>('rf-corr', (v) => {
    state.corr = v;
    renderSummary();
    renderTrend();
    renderXp();
  });
  $<HTMLSelectElement>('#rf-peers').addEventListener('change', (e) => {
    state.peer = (e.target as HTMLSelectElement).value as PeerChoice;
    renderSummary();
    renderTrend();
    renderPraise();
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
  $('#rf-praise-more').addEventListener('click', () => {
    state.praiseShown += PAGE;
    renderPraise();
  });
  $('#rf-dirs-more').addEventListener('click', () => {
    state.allDirs = true;
    renderDirs();
  });
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    if (!state.person) return;
    renderTrend();
    renderXp();
  });
  void getJson<Peers>(`${DATA}peers.json`).then((p) => {
    state.peers = p;
    window.__rf!.peers = p;
    if (p) $('#rf-min-cls').textContent = fmtInt(p.min_cls);
  }).catch(() => {}).finally(() => {
    document.body.dataset.ready = '1';
  });
}

init();
