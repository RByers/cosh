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
  // Charts come in order: ratio, review, (leaderboard,) usage, before the table.
  const order = await page.$$eval('main > section', (s) => s.map((e) => e.querySelector('canvas, table')?.id));
  assert.deepEqual(order.filter(Boolean), ['ratio-chart', 'review-chart', 'leaderboard-chart', 'usage-chart', 'org-table']);
  await page.close();
});

test('ratio axis puts 1.0 halfway between 0 and the maximum', async () => {
  const { page } = await open();
  const axis = await page.evaluate(() => {
    const c = window.__cosh!.ratioChart!;
    const y = c.scales.y;
    const labels = y.ticks.map((t) => String(t.label));
    return { top: y.top, bottom: y.bottom, one: y.getPixelForValue(1), labels };
  });
  assert.ok(Math.abs(axis.one - (axis.top + axis.bottom) / 2) < 1, JSON.stringify(axis));
  assert.equal(axis.labels[0], '0×');
  assert.ok(axis.labels.includes('1.0×'));
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

test('switching the metric updates the table, review chart and URL', async () => {
  const { page } = await open();
  const cell = () => page.$eval('tr[data-org="microsoft.com"] td', (td) => td.textContent);
  const before = await cell();
  await page.click('#metric input[value="cls"]');
  assert.notEqual(await cell(), before);
  assert.match(page.url(), /metric=cls/);
  const label = await page.evaluate(() => window.__cosh!.reviewChart!.data.datasets[0].label);
  assert.equal(label, 'Reviewed CLs');
  // State survives a reload via the URL hash.
  await page.reload();
  await page.waitForSelector('body[data-ready]');
  assert.equal(await page.$eval('#metric input[value="cls"]', (i) => (i as HTMLInputElement).checked), true);
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
        reviewTotal: (c.reviewChart!.data.datasets[0].data as number[]).reduce((s, v) => s + v, 0),
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

test('review chart lists top orgs with Other last', async () => {
  const { page } = await open();
  const labels = await page.evaluate(() => window.__cosh!.reviewChart!.data.labels as string[]);
  assert.equal(labels[0], 'google.com');
  assert.equal(labels[labels.length - 1], 'Other');
  assert.ok(labels.length <= 8);
  await page.close();
});

test('leaderboard shows up to 50 reviewers compactly and follows the metric', async () => {
  const { page } = await open();
  const read = () =>
    page.evaluate(() => {
      const c = window.__cosh!.leaderboardChart!;
      const values = c.data.datasets[0].data as number[];
      return { n: values.length, values, label: c.data.datasets[0].label, h: c.height, top: (c.data.labels as string[])[0] };
    });
  const comments = await read();
  assert.ok(comments.n > 10 && comments.n <= 50, `n=${comments.n}`);
  assert.deepEqual(comments.values, [...comments.values].sort((a, b) => b - a));
  assert.match(comments.top, /^1\. /);
  // Compact: 50 rows fit in well under a 900px-tall viewport's worth plus axes.
  assert.ok(comments.h <= comments.n * 15 + 40, `height ${comments.h}`);
  await page.click('#metric input[value="cls"]');
  const cls = await read();
  assert.equal(cls.label, 'Reviewed CLs');
  assert.notDeepEqual(cls.values, comments.values);
  await page.close();
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
    await page.close();
  }
});
