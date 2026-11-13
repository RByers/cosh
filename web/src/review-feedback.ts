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
  bestTenure,
  buildPerson,
  clsOf,
  commentUrl,
  dirTree,
  groupKey,
  halfGroups,
  halves,
  introAxis,
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
  threadsIn,
  threadBinLabel,
  threadBinRange,
  threadHistogram,
  THREAD_BINS,
  ratioBins,
  cohortYears,
  trendGroup,
  valueFor,
  forKind,
  xpBreakdown,
  chgBreakdown,
  type Alias,
  type Shard,
  type Top,
  type Corr,
  type CountField,
  type DirNode,
  type DirRowView,
  dirRows,
  type Dist,
  type Kind,
  type MedianBar,
  type Metric,
  type PeerOrg,
  type Peers,
  type Person,
  type TenureBy,
  type ThreadRow,
  type Sums,
} from './feedback.ts';
import { fmtDay, fmtInt, fmtNum } from './format.ts';
import { fragment, msg, type Vars } from './text.ts';

Chart.register(Filler);

/** Replaces `target`'s contents with the template `key`. */
const put = (target: Element, key: string, vars: Vars = {}) => target.replaceChildren(fragment(key, vars));

declare global {
  interface Window {
    __rf?: { person: Person | null; peers: Peers | null; charts: Record<string, Chart>; half: string | null;
      bin: number | null };
  }
}

const $ = <T extends Element = HTMLElement>(sel: string) => document.querySelector<T>(sel)!;
const DATA = 'review-feedback/';
const PAGE = 50;
/** Directory rows per level before an "N more" row, as on the Value Exchange page. */
/** The page's figures always cover all the data; only the over-time chart splits it, by half-year. */
const ALL = 'all';

const state = {
  person: null as Person | null,
  peers: null as Peers | null,
  kind: 'a' as Kind,
  corr: 'd' as Corr,
  tenure: 'changes' as TenureBy,
  /** The experience card: by changes landed before ('all') or per directory. */
  xpBy: 'all' as 'all' | 'dir',
  org: 'all' as PeerOrg,
  /** The selected directory's path; comments are listed from it and below. */
  dir: null as string | null,
  /** The half-year picked in the over-time chart, filtering the directories and comments. */
  half: null as string | null,
  /** The column picked in the threads-per-change chart (THREAD_BINS), filtering the same. */
  bin: null as number | null,
  threadsShown: PAGE,
  /** Keys of the directory rows that are open (see dirRows). */
  expanded: new Set<string>(),
};
const charts: Record<string, Chart> = {};
window.__rf = { person: null, peers: null, charts, half: null, bin: null };

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
/** A month and year in short form ("Jul 2024"), for chart axes. */
const shortMonth = (day: number) => new Intl.DateTimeFormat('en-US',
  { month: 'short', year: 'numeric', timeZone: 'UTC' }).format(new Date(day * 86_400_000));
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

/** The dates the data covers, by name: the first and last month, and the
 * month the addressed measures start (empty until peers.json has loaded). */
function rangeVars(peers: Peers | null): Record<string, string> {
  if (!peers) return { from: '', to: '', 'addr-from': '' };
  return {
    from: monthOf(fromMonth(peers.start), true),
    to: monthOf(toMonth(peers.end), true),
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
    state.bin = null;
    window.__rf!.bin = null;
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
  // Tenure in changes landed before, unless "Same tenure by" is years.
  const chg = introAxis(state.tenure) === 'changes' && !!peers.cohorts_chg && !!peers.chg_labels;
  const chgLabels = peers.chg_labels ?? [];
  const org = state.org === 'all' ? '' : msg(`org-name-${state.org}`);
  const [from, to] = rangeOf(peers, state.kind);
  const vars = { kind: state.kind, corr: state.corr, dirxp: state.tenure === 'dir', org, min: fmtInt(peers.min_cohort),
    // Only addressed threads start later: directory experience covers the same years as all threads.
    limited: state.kind === 'a', chg,
    minCls: fmtInt(peers.min_cls), minCohortCls: fmtInt(peers.min_cohort_cls),
    from: monthOf(fromMonth(from), true), to: monthOf(toMonth(to), true) };
  put($('#rf-cohorts-note'), 'cohorts-note', vars);
  const curves = (chg ? peers.cohorts_chg! : peers.cohorts)[g]?.[m] ?? {};
  const step = peers.cohort_step;
  const lines = cohortYears(curves, peers.cohort_from)
    .map((y, i) => ({ year: y, color: t.series[i], pts: curves[String(y)] }));
  lineLegend($('#rf-cohort-legend'), lines.map((l) => ({ label: `started in ${l.year}`, color: l.color })));
  const axis = (title: string) => ({ grid: { color: t.grid }, title: { display: true, text: title, color: t.text },
    ticks: { color: t.text, font: { family: t.font } } });
  // Years: a point in the middle of its half-year bin. Changes: one point per bin, labelled.
  const xScale = chg
    ? { type: 'linear' as const, min: 0, max: chgLabels.length - 1, ...axis(msg('axis-changes-before')),
      ticks: { color: t.text, font: { family: t.font }, stepSize: 1, autoSkip: false,
        callback: (v: string | number) => chgLabels[Number(v)] ?? '' } }
    : { type: 'linear' as const, min: 0, ...axis(msg('axis-years-since')) };
  const binName = (b: number) => (chg ? `${chgLabels[b]} earlier changes`
    : `${fmtNum(b, { maximumFractionDigits: 1 })}–${fmtNum(b + step, { maximumFractionDigits: 1 })} years in`);
  charts.cohorts = new Chart($<HTMLCanvasElement>('#rf-cohorts'), {
    type: 'line',
    data: {
      datasets: lines.map((l) => ({ label: String(l.year),
        data: l.pts.map(([b, v]) => ({ x: chg ? b : b + step / 2, y: v })),
        borderColor: l.color, backgroundColor: l.color, borderWidth: 2, pointRadius: 2.5, pointHoverRadius: 4,
        tension: 0, fill: false })),
    },
    options: {
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: 'nearest', intersect: false },
      font: { family: t.font },
      scales: {
        x: xScale,
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
              return `Started in ${l.year}, ${binName(b)}: median ${fmtValue(i.parsed.y)} (${fmtInt(n)} people)`;
            },
          },
        },
      },
    },
  });

  const ch = (chg && peers.change_chg ? peers.change_chg : peers.change)[g]?.[m];
  const bins = ratioBins(peers.change_ratios);
  // The first whole calendar year the measure covers.
  const start = new Date(from * 86_400_000);
  const fromYear = start.getUTCFullYear() + (start.getUTCMonth() === 0 && start.getUTCDate() === 1 ? 0 : 1);
  put($('#rf-change-title'), chg ? 'change-title-chg' : 'change-title-time');
  put($('#rf-change-note'), 'change-note', { ...vars, n: fmtInt(ch?.n ?? 0), people: fmtInt(ch?.people ?? 0),
    fromYear, from: monthOf(fromMonth(from), true), doublingFrom: fmtInt(peers.doubling_from ?? 32),
    median: ch?.median == null ? '–' : pct(Math.abs(ch.median) / 100), fell: (ch?.median ?? 0) >= 0 });
  charts.change = new Chart($<HTMLCanvasElement>('#rf-change'), {
    type: 'bar',
    data: {
      labels: bins.map((b) => b.label),
      datasets: [{ data: ch?.counts ?? [], backgroundColor: bins.map((b) => (b.fell ? t.series[0] : t.muted)),
        borderWidth: 0, categoryPercentage: 0.9, barPercentage: 1 }],
    },
    options: {
      maintainAspectRatio: false,
      animation: false,
      font: { family: t.font },
      scales: {
        x: { ...axis(msg(chg ? 'axis-change-chg' : 'axis-change-time')), grid: { display: false } },
        y: { beginAtZero: true, ...axis(msg(chg ? 'axis-steps-chg' : 'axis-steps-time')) },
      },
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: (i) => `${fmtInt(i.parsed.y ?? 0)} ${chg ? 'doublings' : 'contributor-years'}` } },
      },
    },
  });
  renderKinds(axis);
  renderTenures(axis);
  renderSizes(axis);
}

/** A line legend: one swatch per line, coloured by --color. */
function lineLegend(target: Element, items: { label: string; color: string; dash?: boolean }[]) {
  target.replaceChildren(...items.map((l) => {
    const li = el('li');
    const sw = el('span', undefined, l.dash ? 'swatch swatch-dash' : 'swatch');
    sw.style.setProperty('--color', l.color);
    li.append(sw, document.createTextNode(l.label));
    return li;
  }));
}

const times = (a: number | null | undefined, b: number | null | undefined) =>
  a && b ? fmtNum(a / b, { maximumFractionDigits: 1 }) : '–';

/** All reviewer threads against addressed ones only, by changes landed before
 * (or years since the first commit, when tenure is by years), over the same
 * contributor half-years ("Adjusted for" and "Peers" apply). */
function renderKinds(axis: (title: string) => object) {
  destroy('kinds');
  const peers = state.peers!;
  const chg = introAxis(state.tenure) === 'changes' && !!peers.kinds_chg && !!peers.chg_labels;
  const rows = (chg ? peers.kinds_chg : peers.kinds)?.[state.org]?.[state.corr];
  const labels = chg ? peers.chg_labels : peers.kind_labels;
  if (!rows?.length || !labels) {
    $('#rf-kinds-note').replaceChildren();
    $('#rf-kinds-legend').replaceChildren();
    return;
  }
  const t = theme();
  const share = (chg ? peers.kind_share_chg : peers.kind_share)?.[state.org] ?? [];
  const last = rows.length - 1;
  const [t0, a0] = rows[0];
  const [t10, a10] = rows[last];
  put($('#rf-kinds-title'), chg ? 'kinds-title-chg' : 'kinds-title-time');
  put($('#rf-kinds-note'), 'kinds-note', { chg, tFall: times(t0, t10), aFall: times(a0, a10),
    steeper: !!(t0 && t10 && a0 && a10 && a0 / a10 > t0 / t10) });
  const lines = [
    { label: msg('kinds-all'), color: t.series[1], data: rows.map((r) => r[0]) },
    { label: msg('kinds-addressed'), color: t.series[0], data: rows.map((r) => r[1]) },
  ];
  const norm = state.corr !== 'n';
  lineLegend($('#rf-kinds-legend'), [...lines, ...(norm ? [{ label: msg('kinds-norm'), color: t.muted, dash: true }] : [])]);
  const datasets: ChartDataset<'line'>[] = lines.map((l) => ({ label: l.label, data: l.data, borderColor: l.color,
    backgroundColor: l.color, borderWidth: 2, pointRadius: 3, pointHoverRadius: 4.5, tension: 0, fill: false }));
  if (norm) datasets.push({ label: msg('kinds-norm'), data: labels.map(() => 1), borderColor: t.muted, borderDash: [4, 4],
    borderWidth: 1, pointRadius: 0, pointHoverRadius: 0, fill: false });
  charts.kinds = new Chart($<HTMLCanvasElement>('#rf-kinds'), {
    type: 'line',
    data: { labels, datasets },
    options: {
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: 'index', intersect: false },
      font: { family: t.font },
      scales: {
        x: { ...axis(msg(chg ? 'axis-changes-before' : 'axis-years-since')), grid: { display: false } },
        y: { beginAtZero: true, ...axis(msg('axis-feedback')),
          ticks: { color: t.text, font: { family: t.font }, callback: (v) => fmtValue(Number(v)) } },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          filter: (i) => i.datasetIndex < 2,
          callbacks: {
            label: (i) => `${lines[i.datasetIndex].label}: median ${fmtValue(i.parsed.y)}`,
            footer: (items) => {
              const b = items[0]?.dataIndex ?? 0;
              const s = share[b];
              return `${fmtInt(rows[b][2])} contributor half-years${s == null ? '' : `; ${pct(s)} of threads addressed`}`;
            },
          },
        },
      },
    },
  });
}

/** Changes landed before first: the page's main tenure measure. */
const TENURE_MEASURES = ['changes', 'time', 'dir'] as const;
/** Each measure's five bands, least experienced first, as the chart's tick lines. */
const TENURE_BANDS: Record<(typeof TENURE_MEASURES)[number], string[]> = {
  time: ['<1 y', '1–2 y', '2–5 y', '5–10 y', '10+ y'],
  changes: ['<50', '50–199', '200–499', '500–999', '1,000+'],
  dir: ['0', '1–4', '5–19', '20–99', '100+'],
};

/** Feedback per tenure band for the three tenure measures, and how much of each
 * contributor's yearly fall is left once peers are matched on each. */
function renderTenures(axis: (title: string) => object) {
  destroy('tenures');
  const peers = state.peers!;
  const c = peers.tenure_cmp?.[state.org]?.[metric()];
  if (!c) {
    $('#rf-tenures-note').replaceChildren();
    $('#rf-tenures-legend').replaceChildren();
    return;
  }
  const t = theme();
  // How much of the plain yearly fall each measure takes out once peers are matched on it
  // (overshooting counts as missing); the best first.
  const explained = (m: (typeof TENURE_MEASURES)[number]) => {
    const v = c[m];
    return v === null || !c.none ? '–' : pct(Math.max(0, Math.min(1, 1 - Math.abs(v) / c.none)));
  };
  const best = bestTenure(c);
  if (best) {
    const [, m2, m3] = [best, ...TENURE_MEASURES.filter((m) => m !== best)];
    put($('#rf-tenures-note'), 'tenures-note', { best: msg(`tenure-name-${best}`), bestShare: explained(best),
      name2: msg(`tenure-name-${m2}`), share2: explained(m2), name3: msg(`tenure-name-${m3}`), share3: explained(m3) });
  } else {
    $('#rf-tenures-note').replaceChildren();
  }
  const lines = TENURE_MEASURES.map((m, i) => ({ m, label: msg(`tenure-${m}`), color: t.series[i] }));
  lineLegend($('#rf-tenures-legend'), lines);
  charts.tenures = new Chart($<HTMLCanvasElement>('#rf-tenures'), {
    type: 'line',
    data: {
      labels: [0, 1, 2, 3, 4].map((b) => TENURE_MEASURES.map((m) => TENURE_BANDS[m][b])),
      datasets: lines.map((l) => ({ label: l.label, data: c.bands[l.m].map(([v]) => v), borderColor: l.color,
        backgroundColor: l.color, borderWidth: 2, pointRadius: 3, pointHoverRadius: 4.5, tension: 0, fill: false })),
    },
    options: {
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: 'index', intersect: false },
      font: { family: t.font },
      scales: {
        x: { ...axis(msg('axis-tenure-band')), grid: { display: false } },
        y: { beginAtZero: true, ...axis(msg('axis-feedback')),
          ticks: { color: t.text, font: { family: t.font }, callback: (v) => fmtValue(Number(v), 'd') } },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: () => '',
            label: (i) => {
              const l = lines[i.datasetIndex];
              const [v, n] = c.bands[l.m][i.dataIndex];
              return `${l.label} ${TENURE_BANDS[l.m][i.dataIndex]}: ${fmtValue(v, 'd')} (${fmtInt(n)} changes)`;
            },
          },
        },
      },
    },
  });
}

/** The opening card's two bar charts: the median contributor's value by change
 * size and by directory (highest first), for the measure and "Peers" org chosen. */
function renderSizes(axis: (title: string) => object) {
  destroy('size');
  destroy('dirs');
  const peers = state.peers!;
  const m = metric();
  const bySize = peers.by_size?.[state.org]?.[m];
  const byDir = peers.by_dir?.[state.org]?.[m];
  if (!bySize && !byDir) return;
  const t = theme();
  const [from, to] = rangeOf(peers, state.kind);
  put($('#rf-breakdown-note'), 'breakdown-note', { kind: state.kind, corr: state.corr,
    org: state.org === 'all' ? '' : msg(`org-name-${state.org}`), minCls: fmtInt(peers.min_cell_cls ?? 10),
    from: monthOf(fromMonth(from), true), to: monthOf(toMonth(to), true) });
  const yTitle = msg('axis-feedback');
  // Both as columns, like the year-over-year histogram, with the size or directory names at 45°.
  const bars = (canvas: string, labels: string[], data: MedianBar[], xTitle: string) =>
    new Chart($<HTMLCanvasElement>(canvas), {
      type: 'bar',
      data: { labels, datasets: [{ data: data.map(([v]) => v), backgroundColor: t.series[0], borderWidth: 0,
        categoryPercentage: 0.85, barPercentage: 1 }] },
      options: {
        maintainAspectRatio: false,
        animation: false,
        font: { family: t.font },
        scales: {
          x: { ...axis(xTitle), grid: { display: false },
            ticks: { color: t.text, font: { family: t.font }, autoSkip: false, minRotation: 45, maxRotation: 45 } },
          y: { beginAtZero: true, ...axis(yTitle),
            ticks: { color: t.text, font: { family: t.font }, callback: (v: string | number) => fmtValue(Number(v)) } },
        },
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: (i) => `median ${fmtValue(data[i.dataIndex][0])} (${fmtInt(data[i.dataIndex][1])} contributors)` } },
        },
      },
    });
  if (bySize && peers.size_labels) charts.size = bars('#rf-size', peers.size_labels, bySize, msg('axis-lines'));
  const names = peers.dir_names;
  if (!byDir || !names) return;
  // Directories by their value, highest first; those without one go last.
  const order = names.map((_, i) => i)
    .sort((a, b) => (byDir[b][0] ?? -1) - (byDir[a][0] ?? -1));
  charts.dirs = bars('#rf-dir-chart', order.map((i) => names[i]), order.map((i) => byDir[i]), msg('axis-dir'));
}

// ---- render

function render() {
  if (!state.person || !state.peers) return;
  if (state.half && !(clsOf(state.person.periods[state.half], state.kind) > 0)) state.half = null;
  window.__rf!.half = state.half;
  renderSummary();
  renderTrend();
  renderXp();
  renderPerCl();
  renderDirs();
  renderThreads();
}

function renderSummary() {
  const p = state.person!;
  const peers = state.peers!;
  // Placed among peers by the changes the measure counts (the addressed ones start later).
  const vals = forKind(p.periods[ALL], state.kind);
  const m = metric();
  const [from, to] = rangeOf(peers, state.kind);
  put($('#summary-sub'), 'summary-sub', { corr: state.corr, kind: state.kind, tenure: state.tenure,
    eligible: okFor(vals, state.kind), minCls: peers.min_cls,
    from: monthOf(fromMonth(from), true), to: monthOf(toMonth(to), true) });
  const tile = (id: string, text: string, sub?: string) => {
    $(`#${id} .tile-value`).textContent = text;
    const s = document.querySelector(`#${id} .tile-sub`);
    if (s) s.textContent = sub ?? '';
  };
  const g = groupKey(state.tenure, state.org, vals);
  // The person's counts in the latest whole half-year, among everyone of the same org
  // who landed a change then (no tenure band: one by changes landed would be circular).
  const h = peers.count_half;
  const hv = h ? p.periods[h] : undefined;
  const rank = (field: CountField) => {
    const d = h ? peers.counts_half?.[state.org]?.[field] : undefined;
    if (!h || !d?.q) return '';
    const v = hv?.[field] ?? 0;
    return msg('tile-count-rank', { n: fmtInt(v), half: halfName(h), org: state.org,
      p: v > 0 ? ordinal(percentileOf(d.q, v)) : '' });
  };
  const cls = clsOf(vals, state.kind);
  tile('rf-tile-cls', fmtInt(cls), rank(state.kind === 't' ? 'cls' : 'acls'));
  $('#rf-tile-threads .tile-label').textContent = msg(`tile-threads-${state.kind}`);
  const threads = state.kind === 't' ? vals?.threads ?? 0 : vals?.addressed ?? 0;
  tile('rf-tile-threads', fmtInt(threads), rank(state.kind === 't' ? 'threads' : 'addressed'));
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
  const all = halves(peers.periods).filter((h) => { const [a, b] = periodSpan(h, [from, to]); return a < b; });
  // Every half-year gets its peer group, also those without the person's changes: a band
  // drawn only where they have some was a lone point (no fill) for someone in one half-year.
  // The axis starts where they started contributing.
  const allGroups = halfGroups(state.tenure, state.org, p, all, state.kind);
  const first = Math.max(0, all.findIndex((h, i) => allGroups[i] !== null || p.periods[h]));
  const hs = all.slice(first);
  const groups = allGroups.slice(first);
  const q = (h: string, f: number) => {
    const g = groups[hs.indexOf(h)];
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
  // Each point is named by the month its six months start in ("Jan 2024").
  const names = hs.map((h) => shortMonth(fromMonth(periodSpan(h, [from, to])[0])));
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
          position: 'primary',
          filter: (i) => i.datasetIndex >= 4,
          callbacks: {
            title: (items) => (items.length ? halfName(hs[items[0].dataIndex]) : ''),
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
  renderPerCl();
  renderDirs();
  renderThreads();
}

/** Filters the directories and comments to the changes in threads-per-change column `b` (null: all). */
function setBin(b: number | null) {
  state.bin = b;
  window.__rf!.bin = b;
  state.threadsShown = PAGE;
  renderPerCl();
  renderDirs();
  renderThreads();
}

/** The person's changes by how many reviewer threads (or addressed ones) each drew,
 * for the half-year picked in the over-time chart if any. A column can be selected. */
function renderPerCl() {
  destroy('perCl');
  const p = state.person!;
  const t = theme();
  const period = state.half ?? ALL;
  const counts = threadHistogram(p, period, state.kind);
  // A column left empty by a new half-year or measure drops its filter.
  if (state.bin !== null && !counts[state.bin]) {
    state.bin = null;
    window.__rf!.bin = null;
  }
  put($('#per-cl-sub'), 'per-cl-sub', { kind: state.kind, half: state.half ? halfName(state.half) : '' });
  const labels = Array.from({ length: THREAD_BINS }, (_, b) => threadBinLabel(b));
  const axis = (title: string) => ({ grid: { color: t.grid }, title: { display: true, text: title, color: t.text },
    ticks: { color: t.text, font: { family: t.font } } });
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
        x: { ...axis(msg(`axis-per-cl-${state.kind}`)), grid: { display: false } },
        y: { beginAtZero: true, ...axis(msg('axis-your-cls')),
          ticks: { color: t.text, font: { family: t.font }, precision: 0 } },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          intersect: false,
          mode: 'index',
          callbacks: { label: (i) => `${fmtInt(i.parsed.y ?? 0)} ${i.parsed.y === 1 ? 'change' : 'changes'}` },
        },
      },
    },
  });
}

/** Column `b` of the threads-per-change chart, in words: "3–5 reviewer threads". */
function binName(b: number): string {
  const [lo, hi] = threadBinRange(b);
  return msg('bin-name', { kind: state.kind, none: hi === 0, one: lo === 1 && hi === 1, more: hi === null,
    n: hi === null || hi === lo ? fmtInt(lo) : `${fmtInt(lo)}–${fmtInt(hi)}` });
}

/** The experience card: by changes landed before (all your changes) or by directory experience. */
function renderXp() {
  destroy('xp');
  const p = state.person!;
  const peers = state.peers!;
  const t = theme();
  const m = metric();
  const by = state.xpBy;
  const org = state.org === 'all' ? '' : msg(`org-name-${state.org}`);
  put($('#experience-sub'), `experience-sub-${by}`, { org });
  put($('#rf-xp-note'), `experience-note-${by}`, { org, min: fmtInt(peers.min_peers) });
  put($('#rf-xp-head'), `experience-head-${by}`);
  put($('#rf-xp-head-peers'), `experience-peers-${by}`);
  // Your changes in each band, and the peers' middle half and middle there.
  let labels: string[];
  let mine: Sums[];
  let lo: (number | null)[];
  let hi: (number | null)[];
  let mid: (number | null)[];
  if (by === 'all') {
    labels = peers.changes.map(bandName);
    mine = chgBreakdown(p, ALL, m, peers.changes);
    const qs = peers.changes.map((b) => peers.dist[ALL]?.[`changes:${b}:${state.org}`]?.[m]?.q ?? null);
    [lo, mid, hi] = [0.25, 0.5, 0.75].map((f) => qs.map((q) => (q ? quantile(q, f) : null)));
  } else {
    labels = [...peers.xp];
    mine = xpBreakdown(p, ALL, m);
    const bands = peers.bands[ALL]?.[m] ?? [];
    lo = bands.map((b) => (b.q ? quantile(b.q, 0.25) : null));
    hi = bands.map((b) => (b.q ? quantile(b.q, 0.75) : null));
    mid = bands.map((b) => b.pooled);
  }
  const you = mine.map((b) => (b.cls >= 1 && b.den > 0 ? b.obs / b.den : null));
  const peerName = msg(`experience-peers-${by}`);
  const datasets: ChartDataset<'line', (number | null)[]>[] = [
    { label: '', data: hi, borderWidth: 0, pointRadius: 0,
      pointHoverRadius: 0, backgroundColor: t.baseline, fill: '+1', tension: 0, order: 3 },
    { label: '', data: lo, borderWidth: 0, pointRadius: 0,
      pointHoverRadius: 0, fill: false, tension: 0, order: 3 },
    { label: 'peers', data: mid, borderColor: t.muted, borderDash: [5, 4], borderWidth: 1.5,
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
        x: { grid: { color: t.grid }, title: { display: true, text: msg(`axis-xp-${by}`), color: t.text },
          ticks: { color: t.text, font: { family: t.font } } },
        y: { beginAtZero: true, grid: { color: t.grid }, title: { display: true, text: msg('axis-feedback'), color: t.text },
          ticks: { color: t.text, font: { family: t.font }, callback: (v) => fmtValue(Number(v)) } },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          position: 'primary',
          filter: (i) => i.datasetIndex >= 2,
          callbacks: {
            label: (i) => (i.datasetIndex === 3 ? `You: ${fmtValue(i.parsed.y)}` : `${peerName}: ${fmtValue(i.parsed.y)}`),
          },
        },
      },
    },
  });
  const body = $('#rf-xp-table tbody');
  body.replaceChildren();
  labels.forEach((label, b) => {
    const tr = el('tr');
    tr.append(el('th', label), el('td', fmtNum(mine[b].cls, { maximumFractionDigits: 1 }), 'num'),
      el('td', fmtInt(mine[b].obs), 'num'), el('td', fmtValue(you[b]), 'num'), el('td', fmtValue(mid[b]), 'num'));
    tr.firstElementChild!.setAttribute('scope', 'row');
    body.append(tr);
  });
}

function renderDirs() {
  const p = state.person!;
  put($('#directories-sub'), 'directories-sub', { corr: state.corr });
  $('#rf-dirs-typical').title = msg(`dirs-typical-${state.kind}`).replace(/\s+/g, ' ').trim();
  showHalfFilter('#rf-half-filter');
  showBinFilter('#rf-bin-filter');
  const roots = dirTree(p, state.half ?? ALL, state.kind, state.bin);
  const body = $('#rf-dirs tbody');
  body.replaceChildren(...dirRows(roots, state.expanded, state.peers!.min_cls).map(dirRow));
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
    s.title = r.kind === 'rest' ? `Files directly in ${r.node!.path}` : `${fmtInt(r.count!)} smaller entries`;
    label.append(s);
  }
  th.append(label);
  const s = r.stats;
  const ratio = el('td', '–', 'num rf-ratio');
  if (r.ratio === null) ratio.title = msg('dirs-no-ratio', { n: fmtInt(state.peers!.min_cls) });
  else {
    const v = r.ratio;
    ratio.textContent = fmtValue(v, 'd');
    const shade = ratioShade(v);
    ratio.classList.add(shade < 0 ? 'rf-ratio-lo' : 'rf-ratio-hi');
    ratio.style.setProperty('--rf-shade', String(Math.abs(shade)));
  }
  tr.append(th, el('td', fmtInt(s.cls), 'num'), el('td', fmtInt(s.lines), 'num'), el('td', fmtInt(s.threads), 'num'),
    el('td', fmtNum(s.expected, { maximumFractionDigits: 1 }), 'num'), ratio, el('td', fmtInt(s.prior), 'num'));
  return tr;
}

function threadItem(r: ThreadRow): HTMLLIElement {
  const li = el('li', undefined, `quote rf-thread${r.praise ? ' quote-praise' : ''}`);
  const head = el('div', undefined, 'rf-thread-head');
  head.append(r.count === undefined
    ? fragment('thread-meta', { date: dayLabel(r.day), file: r.file })
    : fragment('thread-meta-count', { date: dayLabel(r.day), n: fmtInt(r.count), dir: r.file }));
  const tags = el('span', undefined, 'rf-tags');
  // Only the positive label: "not addressed" reads as ignored feedback, when such
  // threads usually needed no change.
  if (r.addressed) tags.append(el('span', msg('thread-addressed'), 'rf-tag rf-tag-on'));
  if (r.praise) tags.append(el('span', msg('thread-praise'), 'rf-tag rf-tag-praise'));
  head.append(tags);
  li.append(head);
  li.append(r.text ? el('p', r.text, 'rf-text')
    : el('p', msg(r.count === undefined ? 'thread-no-text' : 'thread-no-text-count'), 'rf-text muted'));
  li.append(link(commentUrl(r.cl, r.uuid), msg(r.uuid ? 'thread-link' : 'thread-link-cl')));
  return li;
}

/** Shows or hides one of the half-year filter lines (above the directories, and above the comments). */
function showHalfFilter(sel: string) {
  const filter = $(sel);
  filter.hidden = !state.half;
  if (state.half) put(filter.querySelector('.rf-filter-name')!, 'half-filter', { half: halfName(state.half) });
}

/** Shows or hides one of the threads-per-change filter lines. */
function showBinFilter(sel: string) {
  const filter = $(sel);
  filter.hidden = state.bin === null;
  if (state.bin !== null) put(filter.querySelector('.rf-filter-name')!, 'bin-filter', { bin: binName(state.bin) });
}

function renderThreads() {
  const p = state.person!;
  showHalfFilter('#rf-half-filter-comments');
  showBinFilter('#rf-bin-filter-comments');
  const rows = threadRows(p, state.half ?? ALL, state.kind, state.dir, state.bin);
  put($('#comments-sub'), 'comments-sub', { n: fmtInt(threadsIn(rows)), kind: state.kind, dir: state.dir ?? '',
    half: state.half ? halfName(state.half) : '', bin: state.bin === null ? '' : binName(state.bin) });
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
  for (const b of document.querySelectorAll('.rf-bin-clear')) b.addEventListener('click', () => setBin(null));
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
  radio<'all' | 'dir'>('rf-xp-by', (v) => {
    state.xpBy = v;
    if (state.person) renderXp();
  });
  const peersChanged = () => {
    renderIntro();
    if (!state.person) return;
    renderSummary();
    renderTrend();
    renderXp();
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
    renderPerCl();
  });
  void getJson<Peers>(`${DATA}peers.json`).then((p) => {
    state.peers = p;
    window.__rf!.peers = p;
    if (!p) return;
    $('#rf-min-cls').textContent = fmtInt(p.min_cls);
    $('#rf-dirs-min').textContent = fmtInt(p.min_cls);
    fillRange(p);
    renderIntro();
  }).catch(() => {}).finally(() => {
    document.body.dataset.ready = '1';
  });
}

init();
