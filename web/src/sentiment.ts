// The Review Tone page (sentiment.html). Wording is in the HTML; this fills
// in values and draws the charts. Comment text is untrusted and goes into
// the DOM only as text (SECURITY.md). Ground rule 5: names and links only
// for praise.
import { Chart, Filler, type ChartDataset } from 'chart.js';
import monthlyUrl from '../../summaries/sentiment_monthly.json?url';
import praiseUrl from '../../summaries/sentiment_praise.json?url';
import samplesUrl from '../../summaries/sentiment_samples.json?url';
import recentUrl from '../../summaries/sentiment_recent.json?url';
import promptText from '../../scripts/sentiment_prompts/v3.txt?raw';
import { readTheme, type Theme } from './charts.ts';
import { weekMonday } from './data.ts';
import { fmtDay, fmtInt, fmtNum } from './format.ts';
import { fill, fragment, msg } from './text.ts';
import {
  dayLabel,
  gerritLink,
  monthLabel,
  periodWeeks,
  praiseBoard,
  praisePeople,
  praiseTotal,
  weeksBetween,
  type HappyRow,
  type Period,
  type PraiseData,
  type TonePoint,
  type ToneRecent,
  type ToneSamples,
  type ToneTrend,
} from './tone.ts';

Chart.register(Filler);

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
  return new Chart(canvas, {
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
  });
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
  new Chart($<HTMLCanvasElement>('#recent-dist'), {
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
  });
}

// ---- leaderboards

function boardRows(table: HTMLTableElement, rows: { name: string; email: string; count: string }[]) {
  table.tBodies[0].replaceChildren(...rows.map((r, i) => {
    const tr = el('tr');
    const who = el('td', r.name);
    who.title = r.email;
    tr.append(el('td', String(i + 1)), who, el('td', r.count, 'num'));
    return tr;
  }));
}

function renderPraise(d: PraiseData) {
  const draw = () => {
    const range = periodWeeks(d.weeks, period());
    const n = Number(size());
    fill($('#praise-sub'), { range: weeksBetween(range), n: fmtInt(praiseTotal(d, range)), people: fmtInt(praisePeople(d, range)) });
    for (const key of ['given', 'received'] as const) {
      boardRows($<HTMLTableElement>(`#praise-${key}`),
        praiseBoard(d, key, n, range).map((r) => ({ name: r.name, email: r.email, count: fmtInt(r.count) })));
    }
  };
  const period = radio<Period>('praise-period', () => draw());
  const size = radio<string>('praise-size', () => draw());
  draw();
}

function renderHappy(r: ToneRecent) {
  const fmtRow = (x: HappyRow) => ({ name: x.name, email: x.email, count: `${fmtInt(x.happy)} of ${fmtInt(x.counterparts)}` });
  const draw = () => {
    const p = period();
    const n = Number(size());
    fill($('#happy-sub'), { range: weeksBetween(p === 'all' ? r.weeks : r.month_weeks), min: r.min_counterparts });
    boardRows($<HTMLTableElement>('#happy-authors'), r.happy[p].authors.slice(0, n).map(fmtRow));
    boardRows($<HTMLTableElement>('#happy-reviewers'), r.happy[p].reviewers.slice(0, n).map(fmtRow));
  };
  const period = radio<Period>('happy-period', () => draw());
  const size = radio<string>('happy-size', () => draw());
  draw();
}

// ---- comments

function renderSamples(s: ToneSamples) {
  fill($('#samples-sub'), { range: weeksBetween(s.weeks) });
  $('#praise-min').textContent = String(s.praise_min);
  $('#grumpy-max').textContent = String(Math.abs(s.grumpy_max));
  $('#praise-samples').replaceChildren(...s.praise.map((p) => {
    const li = el('li', undefined, 'quote quote-praise');
    li.append(el('blockquote', p.text));
    const by = el('p', undefined, 'quote-by');
    by.append(fragment('praise-by', { writer: p.writer, recipient: p.recipient, date: dayLabel(p.date) }));
    const url = gerritLink(p.url);
    if (url) {
      const a = el('a', 'View review');
      a.href = url;
      a.rel = 'noopener';
      by.append(' · ', a);
    }
    li.append(by);
    return li;
  }));
  $('#grumpy-samples').replaceChildren(...s.grumpy.map((g) => {
    const li = el('li', undefined, 'quote quote-grumpy');
    li.append(el('blockquote', g.text));
    const when = el('p', undefined, 'quote-by');
    when.append(fragment('grumpy-when', { month: monthLabel(g.month) }));
    li.append(when);
    return li;
  }));
}

const AI_FIRST = 20;

function renderAi(r: ToneRecent) {
  const total = r.total.ai;
  fill($('#ai-sub'), { range: weeksBetween(r.weeks), shown: fmtInt(r.ai.length), total: fmtInt(total) });
  // Newest first.
  const items = [...r.ai].reverse();
  const list = $('#ai-list');
  const draw = (n: number) =>
    list.replaceChildren(...items.slice(0, n).map((c) => {
      const li = el('li', undefined, 'quote quote-ai');
      li.append(el('blockquote', c.text));
      const when = el('p', undefined, 'quote-by');
      when.append(fragment('ai-when', { month: monthLabel(c.month), role: c.role }));
      li.append(when);
      return li;
    }));
  draw(AI_FIRST);
  const more = $<HTMLButtonElement>('#ai-more');
  if (items.length > AI_FIRST) {
    more.textContent = msg('ai-more', { n: fmtInt(items.length) });
    more.hidden = false;
    more.addEventListener('click', () => {
      draw(items.length);
      more.hidden = true;
    });
  }
}

async function main() {
  try {
    $('#prompt-text').textContent = promptText.trim();
    const [trend, praise, samples, recent] = await Promise.all([
      getJson<ToneTrend>(monthlyUrl),
      getJson<PraiseData>(praiseUrl),
      getJson<ToneSamples>(samplesUrl),
      getJson<ToneRecent>(recentUrl),
    ]);
    const theme = readTheme();
    renderTrend(trend, theme);
    renderRecent(recent, theme);
    renderPraise(praise);
    renderHappy(recent);
    renderSamples(samples);
    renderAi(recent);
  } catch (e) {
    const err = $('#error');
    fill(err, { error: String(e) });
    err.hidden = false;
  } finally {
    $('main').removeAttribute('aria-busy');
    document.body.dataset.ready = '';
  }
}

void main();
