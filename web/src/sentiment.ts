// The Review Tone page (sentiment.html). Wording is in the HTML; this fills
// in values and draws the charts. Comment text is untrusted and goes into
// the DOM only as text (SECURITY.md). Ground rule 5: names and links only
// for praise.
import { Chart, Filler, type ChartDataset } from 'chart.js';
import monthlyUrl from '../../summaries/sentiment_monthly.json?url';
import praiseUrl from '../../summaries/sentiment_praise.json?url';
import samplesUrl from '../../summaries/sentiment_samples.json?url';
import { readTheme, type Theme } from './charts.ts';
import { fmtInt, fmtNum } from './format.ts';
import { fill, fragment } from './text.ts';
import {
  dayLabel,
  gerritLink,
  monthLabel,
  praiseBoard,
  praisePeople,
  praiseTotal,
  weeksBetween,
  type PraiseData,
  type TonePoint,
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

const signed = (v: number) => (v > 0 ? '+' : v < 0 ? '−' : '') + fmtNum(Math.abs(v), { minimumFractionDigits: 3, maximumFractionDigits: 3 });
const pct = (v: number) => fmtNum(v, { style: 'percent', minimumFractionDigits: 1, maximumFractionDigits: 1 });

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

function el<K extends keyof HTMLElementTagNameMap>(tag: K, text?: string, cls?: string): HTMLElementTagNameMap[K] {
  const e = document.createElement(tag);
  if (text !== undefined) e.textContent = text;
  if (cls) e.className = cls;
  return e;
}

function renderBoard(table: HTMLTableElement, d: PraiseData, key: 'given' | 'received') {
  const body = table.tBodies[0];
  body.replaceChildren(...praiseBoard(d, key).map((r, i) => {
    const tr = el('tr');
    const who = el('td', r.name);
    who.title = r.email;
    tr.append(el('td', String(i + 1)), who, el('td', fmtInt(r.count), 'num'));
    return tr;
  }));
}

function renderPraise(d: PraiseData) {
  fill($('#praise-sub'), { range: weeksBetween(d.weeks), n: fmtInt(praiseTotal(d)), people: fmtInt(praisePeople(d)) });
  renderBoard($<HTMLTableElement>('#praise-given'), d, 'given');
  renderBoard($<HTMLTableElement>('#praise-received'), d, 'received');
}

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

async function main() {
  try {
    const [trend, praise, samples] = await Promise.all([
      getJson<ToneTrend>(monthlyUrl),
      getJson<PraiseData>(praiseUrl),
      getJson<ToneSamples>(samplesUrl),
    ]);
    const theme = readTheme();
    renderTrend(trend, theme);
    renderPraise(praise);
    renderSamples(samples);
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
