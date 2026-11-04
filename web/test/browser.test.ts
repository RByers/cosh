// Browser tests: serve the production build with `vite preview` and drive it
// with headless Chrome through puppeteer-core (uses an installed Chrome; no
// browser download). Run `npm run build` first; `npm test` does both.
//
// CHROME_PATH overrides the Chrome binary. SCREENSHOT_DIR, if set, saves
// full-page screenshots in light and dark mode for eyeballing.
import assert from 'node:assert/strict';
import { existsSync } from 'node:fs';
import { join } from 'node:path';
import { afterAll as after, beforeAll as before, test } from 'vitest';
import { fileURLToPath } from 'node:url';
import puppeteer, { type Browser, type Page } from 'puppeteer-core';
import { preview, type PreviewServer } from 'vite';
import { randomPort } from '../vite.config.ts';

const webDir = fileURLToPath(new URL('..', import.meta.url));
const chromePath = process.env.CHROME_PATH ?? '/usr/bin/google-chrome';

let server: PreviewServer;
let browser: Browser;
let baseUrl: string;

before(async () => {
  assert.ok(existsSync(join(webDir, 'dist/index.html')), 'run `npm run build` first');
  // Always a random unforwarded port (argus-config/ports.md), even when the user runs the tests.
  server = await preview({
    root: webDir,
    logLevel: 'silent',
    preview: { host: 'localhost', port: randomPort(), strictPort: false },
  });
  baseUrl = server.resolvedUrls!.local[0];
  browser = await puppeteer.launch({
    executablePath: chromePath,
    headless: true,
    args: ['--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage'],
  });
});

after(async () => {
  await browser?.close();
  await server?.close();
});

async function open(hash = '', width = 1100): Promise<{ page: Page; errors: string[] }> {
  const page = await browser.newPage();
  await page.setViewport({ width, height: 900 });
  const errors: string[] = [];
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.goto(baseUrl + hash);
  await page.waitForSelector('body[data-ready]');
  const ready = await page.$eval('body', (b) => b.dataset.ready);
  const shown = await page.$eval('#error', (e) => e.textContent);
  assert.equal(ready, 'true', `page failed to load: ${shown} ${errors.join('; ')}`);
  return { page, errors };
}

test('page loads data and renders all three charts without errors', async () => {
  const { page, errors } = await open();
  assert.equal(await page.$eval('body', (b) => b.dataset.ready), 'true');
  assert.deepEqual(errors, []);
  const charts = await page.evaluate(() =>
    ['ratioChart', 'reviewChart', 'usageChart'].map((k) => {
      const c = (window.__cosh as unknown as Record<string, { width: number; height: number; data: { datasets: unknown[] } }>)[k];
      return { k, w: c.width, h: c.height, n: c.data.datasets.length };
    }),
  );
  for (const c of charts) {
    assert.ok(c.w > 200 && c.h > 200, `${c.k} has size ${c.w}x${c.h}`);
    assert.ok(c.n >= 1, `${c.k} has datasets`);
  }
  // Charts come in order: ratio, review, usage, then the table, then the leaderboard.
  const order = await page.$$eval('main > section', (s) => s.map((e) => e.querySelector('canvas, table, .lb')?.id));
  assert.deepEqual(order.filter(Boolean), ['ratio-chart', 'review-chart', 'usage-chart', 'org-table', 'leaderboard-chart']);
  await page.close();
});

test('ratio axis is linear from 0 with a highlighted 1.0 gridline', async () => {
  const { page } = await open();
  const axis = await page.evaluate(() => {
    const c = window.__cosh!.ratioChart!;
    const y = c.scales.y;
    const px = (v: number) => y.getPixelForValue(v);
    const width = (c.config.options!.scales!.y as unknown as { grid: { lineWidth: (ctx: unknown) => number } }).grid.lineWidth;
    const other = y.ticks.find((t) => t.value !== 1)!.value;
    return {
      min: y.min,
      max: y.max,
      labels: y.ticks.map((t) => String(t.label)),
      // Linear: equal ratio steps get equal pixel steps on both sides of 1.
      below: px(0.5) - px(1),
      above: px(1) - px(1.5),
      oneWidth: width({ tick: { value: 1 } }),
      otherWidth: width({ tick: { value: other } }),
    };
  });
  assert.equal(axis.min, 0);
  assert.ok(axis.max > 1, JSON.stringify(axis));
  assert.equal(axis.labels[0], '0×');
  assert.ok(axis.labels.includes('1.0×'), axis.labels.join());
  assert.ok(Math.abs(axis.below - axis.above) < 0.5, JSON.stringify(axis));
  assert.ok(axis.oneWidth > axis.otherWidth, JSON.stringify(axis));
  await page.close();
});

test('W44 ratios: Google above parity, Microsoft below', async () => {
  const { page } = await open();
  const ratios = await page.$$eval('#org-table tbody tr', (rows) =>
    Object.fromEntries(rows.map((r) => [(r as HTMLElement).dataset.org, r.querySelector('td.ratio')!.textContent])),
  );
  assert.ok(parseFloat(ratios['google.com']!) > 1, ratios['google.com']!);
  assert.ok(parseFloat(ratios['microsoft.com']!) < 1, ratios['microsoft.com']!);
  assert.equal(ratios['igalia.com'], 'no browser');
  await page.close();
});

test('org table shows the top 20 plus orgs with a browser', async () => {
  const { page } = await open();
  const rows = await page.$$eval('#org-table tbody tr', (trs) => trs.map((r) => r.querySelector('td.ratio')!.textContent));
  assert.ok(rows.length >= 20, String(rows.length));
  assert.ok(rows.slice(20).every((t) => t !== 'no browser'), JSON.stringify(rows.slice(20)));
  assert.match(await page.$eval('#table-caption', (p) => p.textContent!), /top 20 organizations/);
  await page.close();
});

test('brave.com is listed with unknown usage and the Brave note explains why', async () => {
  const { page } = await open();
  const cells = await page.$eval('#org-table tbody tr[data-org="brave.com"]', (r) =>
    [...r.querySelectorAll('td')].slice(1, 3).map((c) => c.textContent),
  );
  assert.deepEqual(cells, ['unknown', 'usage unknown']);
  const ratioOrgs = await page.evaluate(() =>
    window.__cosh!.ratioChart!.data.datasets.map((d: { label?: string }) => d.label),
  );
  assert.ok(!ratioOrgs.includes('brave.com'), ratioOrgs.join());
  const note = await page.$eval('#brave-note', (n) => n.textContent ?? '');
  assert.match(note, /Brave is excluded/);
  assert.match(note, /Sec-CH-UA/);
  await page.close();
});

test('switching the metric updates the table, review chart and URL', async () => {
  const { page } = await open();
  const legend = await page.$eval('#metric legend', (l) => ({
    text: l.textContent,
    height: l.getBoundingClientRect().height,
  }));
  assert.equal(legend.text, 'Contribution metric');
  assert.ok(legend.height > 0, 'metric legend should be visible');
  const cell = () => page.$eval('tr[data-org="microsoft.com"] td', (td) => td.textContent);
  const before = await cell();
  await page.click('#metric input[value="cls"]');
  assert.notEqual(await cell(), before);
  assert.match(page.url(), /metric=cls/);
  const label = await page.evaluate(() => window.__cosh!.reviewChart!.options.scales.y.title.text);
  assert.match(label, /^reviewed cls per week/);
  // State survives a reload via the URL hash.
  await page.reload();
  await page.waitForSelector('body[data-ready]');
  assert.equal(await page.$eval('#metric input[value="cls"]', (i) => (i as HTMLInputElement).checked), true);
  await page.close();
});

test('value ratio smoothing defaults to 4 weeks and is selectable', async () => {
  const { page, errors } = await open('#metric=comments&from=2026-W30&to=2026-W44');
  const read = () =>
    page.evaluate(() => {
      const c = window.__cosh!;
      const ds = c.ratioChart!.data.datasets.find((d: { label?: string }) => d.label === 'google.com')!;
      return {
        smoothing: c.state.smoothing,
        checked: (document.querySelector('#smoothing input:checked') as HTMLInputElement).value,
        labels: [...document.querySelectorAll('#smoothing label')].map((l) => l.textContent),
        ratios: (ds.data as unknown as { ratio: number | null }[]).map((p) => p.ratio),
        sub: document.querySelector('#ratio-sub')!.textContent!,
        review: c.reviewChart!.data.datasets.find((d: { label?: string }) => d.label === 'microsoft.com')!
          .data as (number | null)[],
        reviewSub: document.querySelector('#review-sub')!.textContent!,
      };
    });
  const four = await read();
  assert.equal(four.smoothing, 4);
  assert.equal(four.checked, '4');
  assert.deepEqual(four.labels, ['Off', '4 weeks', '12 weeks']);
  // A page-wide filter, not a value-ratio-only control.
  assert.ok(await page.$('form.filters #smoothing'), 'smoothing toggle sits with the page filters');
  assert.match(four.sub, /4-week running average/);
  assert.ok(four.ratios[0] !== null, 'first week averages over weeks before the range');

  await page.click('#smoothing input[value="1"]');
  const off = await read();
  assert.match(page.url(), /smooth=1/);
  assert.doesNotMatch(off.sub, /running average/);
  assert.notDeepEqual(off.ratios, four.ratios);
  // Smoothing steadies the line: smaller week-to-week moves.
  const jitter = (r: (number | null)[]) =>
    r.slice(1).reduce<number>((s, v, i) => s + Math.abs((v ?? 0) - (r[i] ?? 0)), 0);
  assert.ok(jitter(four.ratios) < jitter(off.ratios), `${jitter(four.ratios)} vs ${jitter(off.ratios)}`);
  // The review chart follows the same setting.
  assert.match(four.reviewSub, /4-week running average/);
  assert.doesNotMatch(off.reviewSub, /running average/);
  assert.ok(off.review.every((v) => v === null || Number.isInteger(v)), 'unsmoothed counts are whole');
  assert.ok(jitter(four.review) < jitter(off.review), `${jitter(four.review)} vs ${jitter(off.review)}`);

  await page.click('#smoothing input[value="12"]');
  assert.match(page.url(), /smooth=12/);
  await page.reload();
  await page.waitForSelector('body[data-ready]');
  assert.equal((await read()).smoothing, 12);
  assert.deepEqual(errors, []);
  await page.close();
});

test('date range defaults to where review and usage data overlap, and drives every chart', async () => {
  const { page, errors } = await open();
  const read = () =>
    page.evaluate(() => {
      const c = window.__cosh!;
      return {
        range: c.state.range,
        common: c.data.ranges.common,
        from: (document.querySelector('#from') as HTMLInputElement).value,
        to: (document.querySelector('#to') as HTMLInputElement).value,
        ratioWeeks: c.ratioChart!.data.labels as string[],
        usageWeeks: c.usageChart!.data.labels as string[],
        reviewWeeks: c.reviewChart!.data.labels as string[],
        reviewTotal: c.reviewChart!.data.datasets
          .flatMap((ds: { data: unknown[] }) => ds.data as (number | null)[])
          .reduce((s: number, v: number | null) => s + (v ?? 0), 0),
        summary: document.querySelector('#range-summary')!.textContent,
        pressed: document.querySelector('#range-presets [aria-pressed="true"]')?.textContent,
      };
    });
  const d = await read();
  assert.deepEqual(d.range, d.common);
  assert.equal(d.pressed, 'All data');
  // The inputs show the Monday and Sunday of the range's end weeks.
  assert.equal(new Date(`${d.from}T00:00:00Z`).getUTCDay(), 1);
  assert.equal(new Date(`${d.to}T00:00:00Z`).getUTCDay(), 0);
  assert.equal(d.usageWeeks[0], d.range.from);
  assert.equal(d.usageWeeks[d.usageWeeks.length - 1], d.range.to);
  assert.ok(d.ratioWeeks.every((w) => w >= d.range.from && w <= d.range.to));
  assert.deepEqual(d.reviewWeeks, d.ratioWeeks);
  assert.match(page.url(), new RegExp(`from=${d.range.from}&to=${d.range.to}`));

  // Pick an earlier start date: the usage chart widens to the week of that date.
  await page.$eval('#from', (i) => {
    const input = i as HTMLInputElement;
    input.value = '2026-01-07'; // a Wednesday in 2026-W02
    input.dispatchEvent(new Event('change', { bubbles: true }));
  });
  const wide = await read();
  assert.equal(wide.range.from, '2026-W02');
  assert.equal(wide.usageWeeks[0], '2026-W02');
  assert.equal(wide.pressed, undefined);
  assert.match(page.url(), /from=2026-W02/);
  assert.ok(wide.reviewTotal >= d.reviewTotal);

  // A "from" after "to" pulls "to" along.
  await page.$eval('#from', (i) => {
    const input = i as HTMLInputElement;
    input.value = '2030-01-01';
    input.dispatchEvent(new Event('change', { bubbles: true }));
  });
  const late = await read();
  assert.ok(late.range.from <= late.range.to, JSON.stringify(late.range));

  // Presets: the latest week only.
  await page.click('#range-presets [data-preset="1"]');
  const one = await read();
  assert.equal(one.range.from, one.range.to);
  assert.equal(one.range.to, d.common.to);
  assert.equal(await page.$eval('[data-preset="1"]', (b) => b.getAttribute('aria-pressed')), 'true');
  assert.deepEqual(errors, []);
  await page.close();
});

test('old #week= links open a one-week range', async () => {
  const { page } = await open('#metric=cls&week=2026-W44');
  const range = await page.evaluate(() => window.__cosh!.state.range);
  assert.deepEqual(range, { from: '2026-W44', to: '2026-W44' });
  await page.close();
});

test('review chart is a weekly line per top org, Other last, on a log axis', async () => {
  const { page } = await open();
  const chart = await page.evaluate(() => {
    const c = window.__cosh!.reviewChart!;
    const ratio = window.__cosh!.ratioChart!;
    const color = (ch: typeof c, org: string) =>
      ch.data.datasets.find((d: { label?: string }) => d.label === org)?.borderColor;
    return {
      type: (c.config as { type?: string }).type,
      yType: c.options.scales.y.type,
      orgs: c.data.datasets.map((d: { label?: string }) => d.label),
      sameColor: color(c, 'microsoft.com') === color(ratio, 'microsoft.com'),
      colors: c.data.datasets.map((d: { borderColor?: string }) => d.borderColor),
    };
  });
  assert.equal(chart.type, 'line');
  assert.equal(chart.yType, 'logarithmic');
  assert.equal(chart.orgs[0], 'google.com');
  assert.equal(chart.orgs[chart.orgs.length - 1], 'Other');
  assert.ok(chart.orgs.length <= 8);
  assert.ok(chart.sameColor, 'orgs keep their ratio-chart colour');
  // Every named org gets its own colour.
  assert.equal(new Set(chart.colors.slice(0, -1)).size, chart.orgs.length - 1, JSON.stringify(chart.colors));
  await page.close();
});

test('review chart toggles to a linear axis without google.com', async () => {
  const { page, errors } = await open();
  const read = () =>
    page.evaluate(() => {
      const c = window.__cosh!.reviewChart!;
      return {
        yType: c.options.scales.y.type,
        orgs: c.data.datasets.map((d: { label?: string }) => d.label),
        colors: Object.fromEntries(
          c.data.datasets.map((d: { label?: string; borderColor?: string }) => [d.label, d.borderColor]),
        ),
        title: c.options.scales.y.title.text as string,
        sub: document.querySelector('#review-sub')!.textContent!,
        labels: [...document.querySelectorAll('#review-scale label')].map((l) => l.textContent),
      };
    });
  const log = await read();
  assert.deepEqual(log.labels, ['Log, all organizations', 'Linear, without google.com']);
  assert.equal(log.yType, 'logarithmic');
  await page.click('#review-scale input[value="linear"]');
  const lin = await read();
  assert.equal(lin.yType, 'linear');
  assert.ok(!lin.orgs.includes('google.com'), lin.orgs.join());
  assert.equal(lin.orgs[lin.orgs.length - 1], 'Other');
  assert.equal(lin.orgs.length, log.orgs.length, 'the next-ranked org takes google.com\'s place');
  // Orgs in both views keep their colour.
  for (const org of lin.orgs.filter((o): o is string => !!o && log.orgs.includes(o))) {
    assert.equal(lin.colors[org], log.colors[org], org);
  }
  assert.doesNotMatch(lin.title, /log scale/);
  assert.match(lin.sub, /google\.com is left out/);
  assert.match(page.url(), /rscale=linear/);
  await page.reload();
  await page.waitForSelector('body[data-ready]');
  assert.equal((await read()).yType, 'linear');
  await page.click('#review-scale input[value="log"]');
  assert.doesNotMatch(page.url(), /rscale/);
  assert.deepEqual(errors, []);
  await page.close();
});

test('leaderboard shows up to 50 reviewers compactly and follows the metric', async () => {
  const { page } = await open();
  const read = () =>
    page.evaluate(() => {
      const box = document.querySelector('#leaderboard-chart')!;
      const rows = [...box.querySelectorAll<HTMLElement>('.lb-row')];
      return {
        n: rows.length,
        values: rows.map((r) => Number(r.querySelector('.lb-value')!.textContent!.replace(/,/g, ''))),
        top: rows[0].querySelector('.lb-label')!.textContent!,
        title: rows[0].title,
        links: rows.map((r) => (r as HTMLAnchorElement).href),
        h: box.getBoundingClientRect().height,
      };
    });
  const comments = await read();
  assert.ok(comments.n > 10 && comments.n <= 50, `n=${comments.n}`);
  assert.deepEqual(comments.values, [...comments.values].sort((a, b) => b - a));
  assert.match(comments.top, /^1\. .+ · \S+$/);
  // The hover text gives the count with the metric, then the email.
  assert.match(comments.title, /^1\. .+\n[\d,]+ review comments\n[^@\s]+@[^@\s]+\.[a-z]+\n/i);
  // Each row is a real link to the reviewer's reviews on Gerrit.
  assert.match(comments.links[0], /^https:\/\/chromium-review\.googlesource\.com\/q\/reviewedby:[^@\s/]+@[^@\s/]+$/);
  // Bars and gridlines share the plot column: a bar's length is its share of
  // the axis, measured against the gridline layer, which spans the axis.
  const geo = await page.evaluate(() => {
    const box = (s: string) => {
      const { left, right, width } = document.querySelector(s)!.getBoundingClientRect();
      return { left, right, width };
    };
    const grid = box('#leaderboard-chart .lb-grid');
    const lines = [...document.querySelectorAll('#leaderboard-chart .lb-line')].map((l) => l.getBoundingClientRect());
    const ticks = [...document.querySelectorAll('#leaderboard-chart .lb-tick')].map((t) => {
      const r = t.getBoundingClientRect();
      return { x: (r.left + r.right) / 2, v: Number(t.textContent!.replace(/,/g, '')) };
    });
    const plot = box('#leaderboard-chart .lb-plot');
    const bar = box('#leaderboard-chart .lb-bar');
    return { grid, lines: lines.map((l) => l.left + l.width / 2), ticks, plot, bar };
  });
  const max = geo.ticks[geo.ticks.length - 1].v;
  assert.ok(max >= comments.values[0] && max < comments.values[0] * 2, `axis max ${max}`);
  assert.ok(Math.abs(geo.plot.left - geo.grid.left) < 0.5 && Math.abs(geo.plot.right - geo.grid.right) < 0.5, JSON.stringify(geo));
  assert.ok(Math.abs(geo.lines[0] - geo.grid.left) < 1 && Math.abs(geo.lines[geo.lines.length - 1] - geo.grid.right) < 1);
  for (const [i, t] of geo.ticks.entries()) assert.ok(Math.abs(t.x - geo.lines[i]) < 1, `tick ${t.v} over its line`);
  const expected = (comments.values[0] / max) * geo.grid.width;
  assert.ok(Math.abs(geo.bar.width - expected) < 1, `bar ${geo.bar.width} vs ${expected}`);
  // Compact: one 16px line per reviewer plus the axis.
  assert.ok(comments.h <= comments.n * 16 + 24, `height ${comments.h}`);
  await page.click('#metric input[value="cls"]');
  const cls = await read();
  assert.match(cls.title, /\n[\d,]+ reviewed cls\n/i);
  assert.notDeepEqual(cls.values, comments.values);
  await page.close();
  // Phones: the org is dropped from the label (it stays in the colour and hover text).
  const narrow = await open('', 390);
  const org = await narrow.page.$eval('#leaderboard-chart .lb-org', (o) => getComputedStyle(o).display);
  assert.equal(org, 'none');
  await narrow.page.close();
});

test('usage chart shows ChromeDerivative with the jump note', async () => {
  const { page } = await open();
  const names = await page.evaluate(() =>
    window.__cosh!.usageChart!.data.datasets.map((d: { label?: string }) => d.label),
  );
  assert.ok(names.includes('ChromeDerivative'), names.join());
  assert.ok(names.includes('Chrome'));
  const note = await page.$eval('#derivative-note', (n) => n.textContent ?? '');
  assert.match(note, /ChromeDerivative/);
  assert.match(note, /2026-W37/);
  await page.close();
});

test('Meta gets a ratio line; WebView counts as usage; fine print covers WebView and iOS', async () => {
  const { page } = await open();
  const ratioOrgs = await page.evaluate(() =>
    window.__cosh!.ratioChart!.data.datasets.map((d: { label?: string }) => d.label),
  );
  assert.ok(ratioOrgs.includes('meta.com'), ratioOrgs.join());
  const usage = await page.evaluate(() =>
    window.__cosh!.usageChart!.data.datasets.map((d: { label?: string }) => d.label),
  );
  assert.ok(usage.includes('ChromeMobileWebview'), usage.join());
  const webview = await page.$eval('#webview-note', (n) => n.textContent ?? '');
  assert.match(webview, /credited to Google/);
  assert.match(webview, /credited to Meta/);
  assert.match(webview, /Microsoft 365's to\s+Microsoft/);
  assert.match(await page.$eval('#ios-note', (n) => n.textContent ?? ''), /iOS is excluded/);
  await page.close();
});

test('review chart explains its scope, metrics and org attribution', async () => {
  const { page } = await open();
  assert.match(await page.$eval('#review-scope-note', (n) => n.textContent ?? ''), /owned by humans/);
  assert.match(await page.$eval('#review-metric-note', (n) => n.textContent ?? ''), /bare \+1/);
  const href = await page.$eval('#affiliation-note a', (a) => (a as HTMLAnchorElement).href);
  assert.equal(
    href,
    'https://chromium.googlesource.com/chromium/src/+/main/third_party/blink/tools/commit_stats/affiliations.json5',
  );
  await page.close();
});

test('dark mode and phone width render without horizontal scroll', async () => {
  const { page } = await open('', 375);
  await page.emulateMediaFeatures([{ name: 'prefers-color-scheme', value: 'dark' }]);
  const bg = await page.$eval('body', (b) => getComputedStyle(b).backgroundColor);
  assert.equal(bg, 'rgb(13, 13, 13)');
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  assert.ok(overflow <= 0, `horizontal overflow ${overflow}px`);
  await page.close();
});

test.skipIf(!process.env.SCREENSHOT_DIR)('screenshots (only when SCREENSHOT_DIR is set)', async () => {
  for (const scheme of ['light', 'dark'] as const) {
    const page = await browser.newPage();
    await page.emulateMediaFeatures([{ name: 'prefers-color-scheme', value: scheme }]);
    await page.setViewport({ width: 1100, height: 900 });
    await page.goto(baseUrl);
    await page.waitForSelector('body[data-ready]');
    await page.screenshot({ path: join(process.env.SCREENSHOT_DIR!, `cosh-${scheme}.png`) as `${string}.png`, fullPage: true });
    // The leaderboard alone, at desktop and phone width.
    for (const width of [1100, 390]) {
      // Tall enough for the whole card, so the screenshot needn't scroll (which
      // would move the hover off the row).
      await page.setViewport({ width, height: 1400 });
      await page.evaluate(() => window.__cosh!.render());
      await page.$eval('#leaderboard', (e) => e.scrollIntoView());
      await page.hover('#leaderboard-chart li:nth-child(3) .lb-row'); // show the hover state
      const card = await page.$('#leaderboard');
      await card!.screenshot({ path: join(process.env.SCREENSHOT_DIR!, `leaderboard-${width}-${scheme}.png`) as `${string}.png` });
    }
    await page.close();
  }
});

test('time axes are labelled by month; tooltips still name the week', async () => {
  const { page, errors } = await open();
  const read = () =>
    page.evaluate(() =>
      (['ratioChart', 'reviewChart', 'usageChart'] as const).map((k) => {
        const c = window.__cosh![k]!;
        const title = c.options.plugins.tooltip.callbacks.title as (items: { label: string }[]) => string;
        const weeks = c.data.labels as string[];
        return {
          k,
          ticks: c.scales.x.ticks.map((t) => String(t.label)),
          title: title([{ label: weeks[weeks.length - 1] }]),
        };
      }),
    );
  for (const c of await read()) {
    assert.ok(c.ticks.length >= 2, `${c.k}: ${c.ticks}`);
    for (const t of c.ticks) assert.match(t, /^[A-Z][a-z]{2}( \d{4})?$/, `${c.k} tick ${t}`);
    assert.match(c.ticks[0], / \d{4}$/, `${c.k}: first tick names the year`);
    assert.match(c.title, /^\d{4}-W\d{2} \([A-Z][a-z]{2} \d+ – [A-Z][a-z]{2} \d+\)$/);
  }
  assert.deepEqual(errors, []);
  await page.close();
  // Phone width: fewer, still month-aligned ticks.
  const narrow = await open('', 390);
  const phone = await narrow.page.evaluate(() => window.__cosh!.reviewChart!.scales.x.ticks.length);
  assert.ok(phone >= 2 && phone <= 6, `phone ticks: ${phone}`);
  await narrow.page.close();
});
