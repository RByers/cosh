// Browser tests: serve the production build with `vite preview` and drive it
// with headless Chrome through puppeteer-core (uses an installed Chrome; no
// browser download). Run `npm run build` first; `npm test` does both.
//
// CHROME_PATH overrides the Chrome binary. SCREENSHOT_DIR, if set, saves
// full-page screenshots in light and dark mode for eyeballing. CPU_THROTTLE=6
// slows each page down 6x, like a CI runner, to shake out timing races.
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { afterAll as after, beforeAll as before, test } from 'vitest';
import { fileURLToPath } from 'node:url';
import puppeteer, { type Browser, type HTTPRequest, type Page } from 'puppeteer-core';
import { createServer, preview, type PreviewServer } from 'vite';
import { randomPort } from '../vite.config.ts';
import { addWeeks, addressedWeeks, isoWeekOf, namedOrgs, weeksIn, type Summary } from '../src/data.ts';

/** The committed summary the build bundles. */
const summary = JSON.parse(
  readFileSync(fileURLToPath(new URL('../../summaries/org_weekly.json', import.meta.url)), 'utf8'),
) as Summary;
const hasAddressedWeeks = () => addressedWeeks(summary).length > 0;

/** The orgs the review sections name for the page's current range. */
const namedOn = async (page: Page) => {
  const range = await page.evaluate(() => window.__cosh!.state.range);
  return namedOrgs(summary, weeksIn(summary.meta.weeks, range));
};

const webDir = fileURLToPath(new URL('..', import.meta.url));
const chromePath = process.env.CHROME_PATH ?? '/usr/bin/google-chrome';

let server: PreviewServer;
let browser: Browser;
let baseUrl: string;
/** The Value Exchange dashboard; baseUrl itself is the landing page. */
let valueUrl: string;

before(async () => {
  assert.ok(existsSync(join(webDir, 'dist/value.html')), 'run `npm run build` first');
  // Always a random unforwarded port (argus-config/ports.md), even when the user runs the tests.
  server = await preview({
    root: webDir,
    logLevel: 'silent',
    preview: { host: 'localhost', port: randomPort(), strictPort: false },
  });
  baseUrl = server.resolvedUrls!.local[0];
  valueUrl = baseUrl + 'value.html';
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

/** Opens the page and waits for its first render and then for the directory
 * sections' Gerrit link data, whose arrival rebuilds their rows (so a test
 * can't click a row that is about to be replaced). With `holdLinks`, that
 * file's request is held instead until `releaseLinks()`. */
async function open(
  hash = '',
  width = 1100,
  { holdLinks = false } = {},
): Promise<{ page: Page; errors: string[]; releaseLinks: () => void }> {
  const page = await browser.newPage();
  await page.setViewport({ width, height: 900 });
  if (process.env.CPU_THROTTLE) await page.emulateCPUThrottling(Number(process.env.CPU_THROTTLE));
  const errors: string[] = [];
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));
  page.on('pageerror', (e) => errors.push(String(e)));
  let releaseLinks = () => {};
  if (holdLinks) {
    let release: () => void;
    const released = new Promise<void>((r) => (release = r));
    releaseLinks = () => release();
    await page.setRequestInterception(true);
    page.on('request', (r) => {
      if (/\/area_reviewers-[^/]*\.json$/.test(r.url())) void released.then(() => r.continue());
      else void r.continue();
    });
  }
  await page.goto(valueUrl + hash);
  await page.waitForSelector('body[data-ready]');
  const ready = await page.$eval('body', (b) => b.dataset.ready);
  const shown = await page.$eval('#error', (e) => e.textContent);
  assert.equal(ready, 'true', `page failed to load: ${shown} ${errors.join('; ')}`);
  if (!holdLinks) await page.waitForSelector('body[data-area-links]');
  return { page, errors, releaseLinks };
}

/** One page at the default state and width, opened on first use and shared by
 * the tests that only read it: every open costs a full data load and render.
 * Tests that click, type, scroll, resize or reload open their own page. */
let shared: Promise<{ page: Page; errors: string[]; hash: string }> | undefined;
async function defaultPage(): Promise<{ page: Page; errors: string[] }> {
  shared ??= open().then(async ({ page, errors }) => ({ page, errors, hash: await page.evaluate(() => location.hash) }));
  const { page, errors, hash } = await shared;
  // A test that changed it would leak into the next one.
  const now = await page.evaluate(() => ({ hash: location.hash, y: window.scrollY, pending: !!document.body.dataset.pending }));
  assert.deepEqual(now, { hash, y: 0, pending: false }, 'a test changed the shared default page');
  return { page, errors };
}

/** Picks a metric and waits for the re-render it schedules (after a paint). */
async function pickMetric(page: Page, id: string) {
  await page.click(`#metric input[value="${id}"]`);
  await page.waitForSelector('body:not([data-pending])');
}

test('the stylesheet is linked from the HTML, so the first paint is styled even in the dev server', async () => {
  // The build always emits a <link>; the dev server injects a stylesheet that
  // main.ts imports only once the script runs, so the page flashes unstyled.
  // With the scripts blocked, the dev server's page must still be styled.
  const dev = await createServer({
    root: webDir,
    logLevel: 'silent',
    server: { host: 'localhost', port: randomPort(), strictPort: false },
  });
  await dev.listen();
  try {
    const page = await browser.newPage();
    await page.setRequestInterception(true);
    page.on('request', (r) => void (r.resourceType() === 'script' ? r.abort() : r.continue()));
    await page.goto(dev.resolvedUrls!.local[0] + 'value.html', { waitUntil: 'load' });
    const styled = await page.evaluate(() => ({
      sheets: document.styleSheets.length,
      font: getComputedStyle(document.body).fontFamily,
    }));
    assert.ok(styled.sheets > 0, 'no stylesheet without scripts');
    assert.match(styled.font, /system-ui/);
    await page.close();
  } finally {
    await dev.close();
  }
});

test('the intro shows while the data loads; the controls and charts appear once it has', async () => {
  const page = await browser.newPage();
  await page.setViewport({ width: 1100, height: 900 });
  const held: HTTPRequest[] = [];
  await page.setRequestInterception(true);
  page.on('request', (r) => (/\.(json|csv)$/.test(r.url()) ? held.push(r) : void r.continue()));
  await page.goto(valueUrl, { waitUntil: 'load' });
  const before = await page.evaluate(() => ({
    intro: (document.querySelector('header h1') as HTMLElement).offsetHeight > 0,
    loading: (document.querySelector('#loading') as HTMLElement).offsetHeight > 0,
    main: (document.querySelector('main') as HTMLElement).offsetHeight,
    ready: document.body.dataset.ready ?? null,
  }));
  assert.deepEqual(before, { intro: true, loading: true, main: 0, ready: null });
  // Only the page's own data is waited for; the directory links come later.
  assert.ok(held.length > 0 && held.every((r) => !/area_reviewers/.test(r.url())));
  page.removeAllListeners('request');
  page.on('request', (r) => void r.continue());
  for (const r of held) void r.continue();
  await page.waitForSelector('body[data-ready="true"]');
  assert.equal(await page.$eval('#loading', (e) => (e as HTMLElement).hidden), true);
  assert.ok(await page.evaluate(() => window.__cosh!.ratioChart!.width > 100));
  await page.waitForSelector('body[data-area-links]');
  await page.close();
});

test('page loads data and renders all three charts without errors', async () => {
  const { page, errors } = await defaultPage();
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
  // Charts come in order: parity, ratio over time, review, usage, the table, directories, directories over time,
  // the per-reviewer distribution, review complexity over time, per review, then the leaderboard.
  const order = await page.$$eval('main > section', (s) => s.map((e) => e.querySelector('canvas, table, .lb, .ar')?.id));
  assert.deepEqual(order.filter(Boolean),
    ['parity-chart', 'ratio-chart', 'review-chart', 'usage-chart', 'org-table', 'area-chart', 'heat-table', 'dist-chart', 'cx-table', 'pr-chart', 'leaderboard-chart']);
  const titles = await page.$$eval('#parity-title, #ratio-title', (h) => h.map((e) => e.textContent));
  assert.deepEqual(titles, ['Value ratio', 'Value ratio over time']);
});

test('the page names weeks by their dates, never as ISO week labels', async () => {
  // Labels like 2026-W44 stay in the URL and the data; text, hover titles and
  // accessible names show dates (web/README.md, "Text and styling").
  const { page, errors } = await open();
  // All the data, then a one-week range.
  for (const preset of ['all', '1']) {
    await page.click(`#range-presets button[data-preset="${preset}"]`);
    await page.waitForSelector('#heat-chart a.hm-box');
    const text = await page.evaluate(() => {
      const parts = [document.body.innerText];
      for (const e of document.body.querySelectorAll('[title], [aria-label]')) {
        parts.push(e.getAttribute('title') ?? '', e.getAttribute('aria-label') ?? '');
      }
      for (const e of document.body.querySelectorAll('.visually-hidden')) parts.push(e.textContent ?? '');
      return parts.join('\n');
    });
    assert.doesNotMatch(text, /\b\d{4}-W\d{2}\b/, `week label shown (preset ${preset})`);
    assert.doesNotMatch(text, /ISO week/i, `"ISO week" shown (preset ${preset})`);
  }
  assert.deepEqual(errors, []);
  await page.close();
});

test('parity chart: review share against usage share on equal log axes, matching the table', async () => {
  const { page, errors } = await defaultPage();
  const d = await page.evaluate(() => {
    const c = window.__cosh!.parityChart!;
    const { x, y } = c.scales;
    type P = { x: number; y: number; share: number };
    const pts: Record<string, P> = Object.fromEntries(
      c.data.datasets.map((ds: { label?: string; data: unknown[] }) => [ds.label, ds.data[0] as P]),
    );
    const table = Object.fromEntries(
      [...document.querySelectorAll<HTMLElement>('#org-table tbody tr')].map((r) => [r.dataset.org, r.querySelector('td.ratio')!.textContent]),
    );
    return {
      types: [x.type, y.type],
      bounds: [x.min, x.max, y.min, y.max],
      area: c.chartArea,
      pts,
      table,
      xTitle: (c.options.scales.x as { title: { text: string } }).title.text,
      yTitle: (c.options.scales.y as { title: { text: string } }).title.text,
      sub: document.querySelector('#parity-sub')!.textContent!,
      plugins: (c.config.plugins ?? []).map((p: { id: string }) => p.id),
    };
  });
  assert.deepEqual(errors, []);
  assert.deepEqual(d.types, ['logarithmic', 'logarithmic']);
  // Same bounds on both axes, so the diagonal is y = x.
  assert.equal(d.bounds[0], d.bounds[2]);
  assert.equal(d.bounds[1], d.bounds[3]);
  assert.ok(d.plugins.includes('parityLine'));
  assert.match(d.yTitle, /^share of addressed comments/);
  assert.match(d.xTitle, /^share of Chromium browser usage/);
  assert.match(d.sub, /1\.0×/);
  // Google above the diagonal, Microsoft below, as in the table.
  const g = d.pts['google.com']!;
  const m = d.pts['microsoft.com']!;
  assert.ok(g.y > g.x, JSON.stringify(g));
  assert.ok(m.y < m.x, JSON.stringify(m));
  assert.ok(!('brave.com' in d.pts));
  for (const [org, p] of Object.entries(d.pts)) {
    assert.ok(p.x >= d.bounds[0] && p.x <= d.bounds[1] && p.y >= d.bounds[0] && p.y <= d.bounds[1], org);
    // Plotted at its share, or at the bottom (0) tick when it has none.
    assert.equal(p.y, p.share > 0 ? p.share : d.bounds[2], org);
    // The table rounds (0.0005× shows as 0.0×).
    const r = p.share / p.x;
    assert.ok(Math.abs(parseFloat(d.table[org]!) - r) <= 0.05 * r + 0.05, `${org}: ${d.table[org]} vs ${r}`);
  }
  // Roughly square plot area.
  const w = d.area.right - d.area.left;
  const h = d.area.bottom - d.area.top;
  assert.ok(Math.abs(w - h) / w < 0.15, `${w}x${h}`);
});

test('parity chart keeps orgs with none of the metric, on a 0 row below the log scale', async () => {
  // The big browser owners get a dot in any range (samsung.com has no
  // addressed comments in some short ones).
  const { page, errors } = await open();
  for (const preset of ['all', '13', '4', '1']) {
    await page.click(`#range-presets button[data-preset="${preset}"]`);
    const d = await page.evaluate(() => {
      const c = window.__cosh!;
      const p = c.parityChart!;
      const y = p.scales.y;
      return {
        parity: p.data.datasets.map((ds: { label?: string }) => ds.label!),
        zeros: p.data.datasets
          .filter((ds: { data: unknown[] }) => (ds.data[0] as { share: number }).share === 0)
          .map((ds: { label?: string; data: unknown[] }) => ({ org: ds.label!, y: (ds.data[0] as { y: number }).y })),
        yMin: y.min,
        bottomLabel: String(y.ticks[0]?.label),
        xMin: p.scales.x.min,
      };
    });
    assert.deepEqual(errors, []);
    for (const org of ['google.com', 'microsoft.com', 'samsung.com', 'opera.com', 'meta.com']) {
      assert.ok(d.parity.includes(org), `${preset}: ${org} missing from ${d.parity}`);
    }
    if (d.zeros.length) {
      assert.equal(d.bottomLabel, '0', preset);
      assert.equal(d.xMin, d.yMin, preset);
      for (const z of d.zeros) {
        assert.equal(z.y, d.yMin, `${preset}: ${z.org}`);
      }
    }
  }
  await page.close();
});

test('organization chart names the orgs with enough review comments, whatever the metric', async () => {
  const { page, errors } = await open('#metric=comments&from=2025-W45&to=2026-W44');
  const labels = async () => {
    const d = await page.evaluate(() => window.__cosh!.reviewChart!.data.datasets.map((ds) => ds.label!));
    return { orgs: d.filter((o) => o !== 'Other'), named: await namedOn(page) };
  };
  const comments = await labels();
  await pickMetric(page, 'cls');
  const cls = await labels();
  assert.deepEqual(errors, []);
  await page.close();
  // The same set for both metrics: the rule's orgs (each has a colour over this range).
  assert.deepEqual([...comments.orgs].sort(), [...comments.named].sort());
  assert.deepEqual([...cls.orgs].sort(), [...comments.orgs].sort());
  for (const o of ['google.com', 'microsoft.com', 'intel.com', 'opera.com', 'igalia.com']) assert.ok(comments.orgs.includes(o), o);
});

test('value charts show the orgs with enough mean usage over the range', async () => {
  // Amazon's Silk averages over 0.1% of Chromium usage since 2023 but not over
  // the last year; Alibaba's UC Browser is over it every week.
  const { page, errors } = await open('#metric=comments&from=2025-W45&to=2026-W44');
  const charted = () =>
    page.evaluate(() => {
      const c = window.__cosh!;
      const labels = (ch: { data: { datasets: { label?: string }[] } }) => ch.data.datasets.map((ds) => ds.label!);
      return { parity: labels(c.parityChart!), ratio: labels(c.ratioChart!) };
    });
  // The last year leaves Amazon out; all the data (back to 2023) brings it back.
  const year = await charted();
  await page.click('#range-presets button[data-preset="all"]');
  const all = await charted();
  assert.deepEqual(errors, []);
  await page.close();
  for (const d of [year, all]) {
    assert.ok(d.ratio.includes('alibaba-inc.com') && d.parity.includes('alibaba-inc.com'), String(d.ratio));
  }
  assert.ok(!year.ratio.includes('amazon.com') && !year.parity.includes('amazon.com'), String(year.ratio));
  assert.ok(all.ratio.includes('amazon.com') && all.parity.includes('amazon.com'), String(all.ratio));
});

test('ratio axis is linear from 0 with a highlighted 1.0 gridline', async () => {
  const { page } = await defaultPage();
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
});

test('org table shows the top 20 plus orgs with a browser', async () => {
  const { page } = await defaultPage();
  // (Its ratios are checked against the parity chart above.)
  assert.equal(await page.$eval('#org-table tr[data-org="igalia.com"] td.ratio', (td) => td.textContent), 'no browser');
  const rows = await page.$$eval('#org-table tbody tr', (trs) => trs.map((r) => r.querySelector('td.ratio')!.textContent));
  const caption = await page.$eval('#table-caption', (p) => p.textContent!);
  if (/omitted/.test(caption)) {
    // Trimmed: the top 20, then only orgs with a browser.
    assert.ok(rows.length >= 20, String(rows.length));
    assert.ok(rows.slice(20).every((t) => t !== 'no browser'), JSON.stringify(rows.slice(20)));
    assert.match(caption, /top 20 organizations/);
  } else {
    // Few enough orgs (e.g. a short range of data) that every one is listed.
    assert.ok(rows.length > 5, String(rows.length));
  }
});

test('brave.com is listed with unknown usage and kept out of the ratio chart', async () => {
  const { page } = await defaultPage();
  const cells = await page.$eval('#org-table tbody tr[data-org="brave.com"]', (r) =>
    [...r.querySelectorAll('td')].slice(1, 3).map((c) => c.textContent),
  );
  assert.deepEqual(cells, ['unknown', 'usage unknown']);
  const ratioOrgs = await page.evaluate(() =>
    window.__cosh!.ratioChart!.data.datasets.map((d: { label?: string }) => d.label),
  );
  assert.ok(!ratioOrgs.includes('brave.com'), ratioOrgs.join());
});

test('directory rows drill down, and "more" rows open 20 at a time and close again', async () => {
  const { page, errors } = await open();
  const read = () =>
    page.evaluate(() =>
      [...document.querySelectorAll<HTMLElement>('#area-chart .ar-row')].map((r) => ({
        key: r.dataset.key!,
        depth: Number(r.dataset.depth),
        name: r.querySelector('.ar-name')!.textContent!,
        value: Number(r.querySelector('.ar-value')!.textContent!.replace(/,/g, '')),
        kind: ['dir', 'rest', 'other'].find((k) => r.classList.contains(`ar-${k}`)),
      })),
    );
  const start = await read();
  assert.equal(await page.$('#area-count'), null);
  assert.ok(start.every((r) => r.depth === 0));
  // The top level: the 20 largest, then one "more" row.
  const others = start.filter((r) => r.kind === 'other');
  assert.equal(others.length, 1);
  assert.equal(start.length, 21);
  // Open third_party/blink/: its children appear one level down and add up to it.
  const blink = start.find((r) => r.name === 'third_party/blink/')!;
  await page.click(`li[data-key="${blink.key}"] .ar-toggle`);
  let rows = await read();
  const i = rows.findIndex((r) => r.key === blink.key);
  const kids = [];
  for (let j = i + 1; j < rows.length && rows[j].depth > 0; j++) if (rows[j].depth === 1) kids.push(rows[j]);
  assert.ok(kids.length > 1 && kids.length <= 21, String(kids.length));
  assert.equal(kids.reduce((s, r) => s + r.value, 0), blink.value);
  assert.equal(await page.$eval(`li[data-key="${blink.key}"] .ar-toggle`, (b) => b.getAttribute('aria-expanded')), 'true');
  // Focus stays on the toggle that was pressed.
  assert.equal(await page.evaluate(() => (document.activeElement as HTMLElement).closest('li')?.dataset.key), blink.key);
  // Open the top-level "more" row: up to 20 more entries, one level down.
  await page.click(`li[data-key="${others[0].key}"] .ar-toggle`);
  rows = await read();
  const k = rows.findIndex((r) => r.key === others[0].key);
  const revealed = rows.slice(k + 1).filter((r) => r.depth === 1);
  assert.ok(revealed.length >= 1 && revealed.length <= 21, String(revealed.length));
  assert.equal(revealed.reduce((s, r) => s + r.value, 0), others[0].value);
  // components/ is excluded except viz/ (and services/storage/): opening it shows viz/ fully in scope.
  const components = start.find((r) => r.name === 'components/')!;
  await page.click(`li[data-key="${components.key}"] .ar-toggle`);
  const inComponents = await page.evaluate(() =>
    Object.fromEntries([...document.querySelectorAll<HTMLElement>('#area-chart .ar-row[data-depth="1"]')]
      .map((r) => [r.querySelector('.ar-name')!.textContent!, Number(r.dataset.included)])));
  assert.equal(inComponents['viz/'], 1);
  assert.equal(inComponents['autofill/'], 0);
  assert.ok(inComponents['services/'] > 0, String(inComponents['services/']));
  await page.click(`li[data-key="${components.key}"] .ar-toggle`);
  // Close both again: back to the start.
  await page.click(`li[data-key="${others[0].key}"] .ar-toggle`);
  await page.click(`li[data-key="${blink.key}"] .ar-toggle`);
  assert.deepEqual(await read(), start);
  assert.deepEqual(errors, []);
  await page.close();
});

test('a directory toggle keeps focus when the Gerrit links arrive and rebuild the rows', async () => {
  const { page, errors, releaseLinks } = await open('', 1100, { holdLinks: true });
  assert.equal(await page.$('body[data-area-links]'), null);
  const key = await page.evaluate(() =>
    [...document.querySelectorAll<HTMLElement>('#area-chart .ar-row')]
      .find((r) => r.querySelector('.ar-name')?.textContent === 'third_party/blink/')!.dataset.key!);
  await page.click(`li[data-key="${key}"] .ar-toggle`);
  releaseLinks();
  await page.waitForSelector('body[data-area-links]');
  assert.ok(await page.$('#area-chart a.ar-seg'), 'rows were rebuilt with links');
  assert.equal(await page.evaluate(() => (document.activeElement as HTMLElement).closest('li')?.dataset.key), key);
  assert.deepEqual(errors, []);
  await page.close();
});

test('metric toggle stays at the top of the window while scrolling, on wide and phone widths', async () => {
  for (const width of [1100, 375]) {
    const { page, errors } = await open('', width);
    const startTop = await page.$eval('.metric-bar', (b) => b.getBoundingClientRect().top);
    assert.ok(startTop > 0, 'metric bar starts in the page flow, below the intro');
    // Scroll far down, to the org table, and the toggle is still pinned and clickable.
    await page.evaluate(() => document.querySelector('#org-table')!.scrollIntoView());
    const bar = await page.$eval('.metric-bar', (b) => {
      const r = b.getBoundingClientRect();
      const btn = b.querySelector('label:last-of-type')!.getBoundingClientRect();
      const hit = document.elementFromPoint(btn.left + btn.width / 2, btn.top + btn.height / 2);
      return { top: r.top, bottom: r.bottom, hit: !!hit && b.contains(hit), scrollY: window.scrollY };
    });
    assert.ok(bar.scrollY > 1000, 'page scrolled');
    assert.equal(bar.top, 0);
    assert.ok(bar.bottom < 150, `bar stays compact (${bar.bottom}px)`);
    // Anchor jumps land below the bar, not under it.
    await page.evaluate(() => document.querySelector('#areas')!.scrollIntoView());
    const areasTop = await page.$eval('#areas', (e) => e.getBoundingClientRect().top);
    assert.ok(areasTop >= bar.bottom, `#areas top ${areasTop} is below the bar ${bar.bottom}`);
    assert.ok(bar.hit, 'nothing covers the stuck toggle');
    await pickMetric(page, 'cls');
    assert.match(page.url(), /metric=cls/);
    assert.equal(await page.$eval('.metric-bar', (b) => b.getBoundingClientRect().top), 0);
    if (width < 1100) {
      // Dark mode at phone width: dark, and still no horizontal scroll.
      await page.emulateMediaFeatures([{ name: 'prefers-color-scheme', value: 'dark' }]);
      assert.equal(await page.$eval('body', (b) => getComputedStyle(b).backgroundColor), 'rgb(13, 13, 13)');
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      assert.ok(overflow <= 0, `horizontal overflow ${overflow}px`);
    }
    assert.deepEqual(errors, []);
    await page.close();
  }
});

test('switching the metric updates the table, review chart, directory chart and URL', async () => {
  const { page, errors } = await open();
  const legend = await page.$eval('#metric legend', (l) => ({
    text: l.textContent,
    height: l.getBoundingClientRect().height,
  }));
  assert.equal(legend.text, 'Contribution metric');
  assert.ok(legend.height > 0, 'metric legend should be visible');
  const options = await page.$$eval('#metric label', (ls) => ls.map((l) => l.textContent));
  // Addressed comments is offered only once some week is classified (cosh classify).
  assert.deepEqual(options, [...(hasAddressedWeeks() ? ['Addressed comments'] : []),
    'Review comments', 'Review characters', 'Reviewed CLs']);
  const headers = await page.$$eval('#org-table th[scope="col"]', (ths) => ths.map((t) => t.textContent));
  assert.deepEqual(headers, ['Org', 'Review share', 'Usage share', 'Ratio', 'Reviewers', 'Reviewed CLs',
    'Comments', 'Addressed comments', 'Review chars', 'AI comments', 'Post-merge comments']);
  const cell = () => page.$eval('tr[data-org="microsoft.com"] td', (td) => td.textContent);
  const areaHead = () => page.$eval('#area-chart .ar-head .ar-vol', (e) => e.textContent);
  // Addressed comments is the default whenever some week is classified.
  assert.equal(await page.$eval(`#metric input[value="${hasAddressedWeeks() ? 'addressed' : 'comments'}"]`,
    (i) => (i as HTMLInputElement).checked), true);
  await pickMetric(page, 'comments');
  const before = await cell();
  assert.equal(await areaHead(), 'Review comments');
  for (const [id, axis, head] of [['cls', /^reviewed CLs per week/, 'Reviewed CLs'],
    ['chars', /^review characters per week/, 'Review characters']] as const) {
    await pickMetric(page, id);
    assert.notEqual(await cell(), before);
    assert.match(page.url(), new RegExp(`metric=${id}`));
    const label = await page.evaluate(() => window.__cosh!.reviewChart!.options.scales.y.title.text);
    assert.match(label, axis);
    assert.equal(await areaHead(), head);
  }
  // (A reload keeping the state: "the page state survives a reload".)
  assert.deepEqual(errors, []);
  await page.close();
});

test('every card has a "#" link that keeps the state in the URL, and a shared link scrolls to its card', async () => {
  const { page, errors } = await open('#metric=comments&smooth=1');
  const cards = await page.$$eval('section.card', (ss) =>
    ss.map((s) => ({ id: s.id, href: s.querySelector('.card-anchor')?.getAttribute('href') })));
  assert.ok(cards.length >= 12);
  for (const c of cards) assert.equal(c.href, `#${c.id}`, `card ${c.id} lacks its link`);
  // The heading the script rewrites keeps its link.
  assert.equal(await page.$$eval('#per-review > .card-anchor', (as) => as.length), 1);

  await page.click('#leaderboard .card-anchor');
  assert.match(page.url(), /#metric=comments&.*smooth=1.*&card=leaderboard$/);
  const shared = page.url();
  // A state change keeps the card.
  await pickMetric(page, 'cls');
  assert.match(page.url(), /metric=cls.*&card=leaderboard$/);
  assert.deepEqual(errors, []);
  await page.close();

  // Opening the shared link scrolls the card to the top, just below the sticky bar.
  for (const hash of [shared.slice(shared.indexOf('#')), '#leaderboard']) {
    const { page: p, errors: e } = await open(hash);
    await p.evaluate(() => new Promise((r) => requestAnimationFrame(r)));
    const t = await p.evaluate(() => {
      const bar = document.querySelector<HTMLElement>('.metric-bar')!.getBoundingClientRect().bottom;
      return document.getElementById('leaderboard')!.getBoundingClientRect().top - bar;
    });
    assert.ok(t >= 0 && t < 30, `${hash}: card ${t}px below the bar`);
    assert.deepEqual(e, []);
    await p.close();
  }
});

test('a metric toggle shows its choice before the slow re-render, and quick picks share one render', async () => {
  const { page, errors } = await open('#metric=comments');
  // All in one evaluate: a frame between two would let the render through.
  const r = await page.evaluate(() => {
    const axis = () => String(window.__cosh!.reviewChart!.options.scales!.y!.title!.text);
    const before = axis();
    let renders = 0;
    new MutationObserver(() => renders++).observe(document.querySelector('#review-sub')!, {
      childList: true, characterData: true, subtree: true,
    });
    document.querySelector<HTMLInputElement>('#metric input[value="cls"]')!.click();
    document.querySelector<HTMLInputElement>('#metric input[value="chars"]')!.click();
    // In the same task: the toggle and URL have changed, the views not yet.
    const now = {
      checked: document.querySelector<HTMLInputElement>('#metric input:checked')!.value,
      url: location.hash,
      pending: document.body.dataset.pending,
      busy: document.querySelector('main')!.getAttribute('aria-busy'),
      axisUnchanged: axis() === before,
    };
    return new Promise<{ now: typeof now; renders: number; axis: string; busy: boolean }>((resolve) => {
      const done = () => resolve({ now, renders, axis: axis(), busy: document.querySelector('main')!.hasAttribute('aria-busy') });
      // Once the render has run, wait one more of renderSoon's cycles (a frame,
      // then a task): any second render the picks had scheduled has run by then.
      // (The observer's records are delivered as microtasks, before that.)
      const check = () =>
        document.body.dataset.pending ? requestAnimationFrame(check) : requestAnimationFrame(() => setTimeout(done, 0));
      check();
    });
  });
  assert.deepEqual({ ...r.now, url: '' }, { checked: 'chars', url: '', pending: 'true', busy: 'true', axisUnchanged: true });
  assert.match(r.now.url, /metric=chars/);
  // A paint later the views catch up, once, with the last pick.
  assert.equal(r.renders, 1);
  assert.match(r.axis, /^review characters per week/);
  assert.equal(r.busy, false);
  assert.deepEqual(errors, []);
  await page.close();
});

test.skipIf(!hasAddressedWeeks())('addressed comments show only classified weeks, without a note', async () => {
  const classified = addressedWeeks(summary);
  const last = classified[classified.length - 1];
  // Start 8 weeks before the first classified week, unless that is the first
  // review week too (then nothing earlier exists, and the range would be clamped).
  const from = classified[0] === summary.meta.weeks[0] ? classified[0] : addWeeks(classified[0], -8);
  const { page, errors } = await open(`#metric=addressed&from=${from}&to=${last}`);
  assert.equal(await page.$eval('#metric input[value="addressed"]', (i) => (i as HTMLInputElement).checked), true);
  assert.equal(await page.$eval('#metric-note', (n) => (n as HTMLElement).hidden), true);
  // The user's range stays in the URL; the sections show the classified part.
  assert.match(page.url(), new RegExp(`from=${from}`));
  assert.equal(await page.evaluate(() => (window.__cosh!.reviewChart!.data.labels as string[])[0]), classified[0]);
  const cell = await page.$eval('tr[data-org="google.com"] td:nth-child(8)', (td) => td.textContent ?? '');
  assert.match(cell, /^[\d,]+$/);
  // Short ranges still draw lines only: no chart has point dots (google.com has no gaps), except on hover.
  const radii = await page.evaluate(() => {
    const c = window.__cosh!;
    return [c.ratioChart, c.reviewChart, c.usageChart].flatMap((ch) =>
      ch!.data.datasets
        .filter((d: { label?: string }) => d.label === 'google.com' || d.label === 'Chrome')
        .map((d: { pointRadius?: unknown; pointHoverRadius?: unknown }) => [d.pointRadius, d.pointHoverRadius]));
  });
  assert.ok(radii.length === 3 && radii.every(([r, h]) => Array.isArray(r) && r.every((x) => x === 0) && h === 4),
    JSON.stringify(radii));
  // The weeks before the first classified one have no addressed data, so the
  // 3-month review average starts from that week alone instead of averaging
  // in zeros. The ratio chart starts once its average has a full window.
  const firstWeek = () =>
    page.evaluate(() => {
      const c = window.__cosh!;
      const ratio = c.ratioChart!.data.datasets.find((d: { label?: string }) => d.label === 'google.com')!;
      const review = c.reviewChart!.data.datasets.find((d: { label?: string }) => d.label === 'google.com')!;
      return {
        ratioStart: (c.ratioChart!.data.labels as string[])[0],
        ratio: (ratio.data as unknown as { ratio: number | null }[])[0].ratio,
        review: (review as unknown as { counts: number[] }).counts[0],
      };
    });
  assert.equal(await page.evaluate(() => window.__cosh!.state.smoothing), 13);
  const smoothed = await firstWeek();
  await page.click('#smoothing input[value="1"]');
  const raw = await firstWeek();
  // The ratio chart starts on its first week with both review and usage data
  // (review data starts 2023-W26, Radar's the week after), and the 3-month
  // average 12 weeks later; both start on a ratio, not an empty week.
  assert.ok(raw.ratioStart >= classified[0], raw.ratioStart);
  assert.equal(smoothed.ratioStart, addWeeks(raw.ratioStart, 12));
  assert.ok(raw.ratio !== null && smoothed.ratio !== null, `${smoothed.ratio} vs ${raw.ratio}`);
  assert.ok(Math.abs(smoothed.review - raw.review) < 1e-9, `${smoothed.review} vs ${raw.review}`);
  await page.click('#smoothing input[value="13"]');
  // The intro links to the explainer in the thread box: it scrolls there without losing the URL state.
  await page.click('#addressed-link');
  // It lands just below the sticky metric bar.
  await page.waitForFunction(() => {
    const top = document.querySelector('#addressed-details')!.getBoundingClientRect().top;
    const bar = document.querySelector('.metric-bar')!.getBoundingClientRect().bottom;
    return top >= bar && top < bar + 12;
  });
  assert.match(page.url(), /metric=addressed/);
  // The classification explainer is always shown in the visible thread box and gives the measured accuracy.
  const details = await page.$eval('#addressed-details', (d) => ({
    boxHidden: document.querySelector<HTMLElement>('#threads')!.hidden,
    tag: d.tagName, text: d.textContent ?? '' }));
  assert.equal(details.boxHidden, false);
  assert.equal(details.tag, 'DIV');
  assert.match(details.text, /precision of 0\.98 .*recall of 0\.99/s);
  // Every mention of a file in this repo links to it on GitHub.
  const repoRefs = await page.$$eval('code', (codes) => codes
    .filter((c) => /^(docs|scripts|cosh|web|tests|summaries|config)\//.test(c.textContent ?? ''))
    .map((c) => ({ path: c.textContent, href: c.closest('a')?.getAttribute('href') ?? null })));
  assert.ok(repoRefs.length > 0);
  for (const r of repoRefs) assert.equal(r.href, `https://github.com/RByers/cosh/tree/main/${r.path}`);
  // Other metrics are unaffected and keep the note hidden.
  await pickMetric(page, 'comments');
  assert.equal(await page.$eval('#metric-note', (n) => (n as HTMLElement).hidden), true);
  // The addressed column totals the range only when every week in it is classified.
  const addressedCell = await page.$eval('tr[data-org="google.com"] td:nth-child(8)', (td) => td.textContent ?? '');
  if (from === classified[0]) assert.match(addressedCell, /^[\d,]+$/);
  else assert.equal(addressedCell, '—');
  assert.deepEqual(errors, []);
  await page.close();
});

test('review by directory shows volume and org split per directory, and the path rules', async () => {
  const { page, errors } = await defaultPage();
  const d = await page.evaluate(() => {
    const rows = [...document.querySelectorAll<HTMLElement>('#area-chart .ar-row')];
    return {
      rows: rows.map((r) => ({
        name: r.querySelector('.ar-name')!.textContent!,
        other: r.classList.contains('ar-other'),
        included: Number(r.dataset.included),
        solid: r.querySelector('.ar-bar-in')?.getBoundingClientRect().width ?? 0,
        hatched: r.querySelector('.ar-bar-out')?.getBoundingClientRect().width ?? 0,
        value: Number(r.querySelector('.ar-value')!.textContent!.replace(/,/g, '')),
        bar: r.querySelector('.ar-bar')!.getBoundingClientRect().width,
        torn: r.querySelector('.ar-bar')!.classList.contains('ar-torn'),
        labelRight: r.querySelector('.ar-value')!.getBoundingClientRect().right,
        volRight: r.querySelector('.ar-vol')!.getBoundingClientRect().right,
        segs: [...r.querySelectorAll<HTMLElement>('.ar-seg')].map((s) => s.getBoundingClientRect().width),
        dist: r.querySelector('.ar-dist')!.getBoundingClientRect().width,
        title: r.title,
      })),
      heads: [...document.querySelectorAll('#scope-rules .scope-head')].map((h) => h.textContent),
      rules: [...document.querySelectorAll('#scope-rules dt')].map((dt) => {
        const dd = dt.nextElementSibling!;
        const a = dt.getBoundingClientRect();
        const b = dd.getBoundingClientRect();
        return {
          path: dt.textContent!,
          group: (dt.parentElement as HTMLElement).dataset.included,
          beside: b.left > a.right && Math.abs(b.top - a.top) < 2,
          left: a.left,
        };
      }),
      groupGap: (() => {
        const [ex, inc] = document.querySelectorAll('#scope-rules dl');
        return inc.getBoundingClientRect().top - ex.getBoundingClientRect().bottom;
      })(),
      sub: document.querySelector('#areas-sub')!.textContent!,
      legend: [...document.querySelectorAll('#areas-legend li')].map((li) => li.textContent),
    };
  });
  const by = Object.fromEntries(d.rows.map((r) => [r.name, r]));
  for (const name of ['chrome/', 'third_party/blink/', 'content/', '(no file)']) assert.ok(by[name], name);
  // Re-included directories stay inside their parents, which are partly
  // included: their bars are solid for that part and hatched for the rest.
  for (const name of ['chrome/browser/web_applications/', 'components/viz/', 'components/services/storage/']) {
    assert.equal(by[name], undefined, name);
  }
  for (const name of ['chrome/', 'components/']) {
    assert.ok(by[name].included > 0 && by[name].included < 0.2, `${name} ${by[name].included}`);
    assert.ok(by[name].solid > 0 && by[name].hatched > 0, name);
  }
  assert.equal(by['(no file)'].included, 0);
  assert.equal(by['(no file)'].solid, 0);
  assert.equal(by['third_party/blink/'].included, 1);
  assert.equal(by['third_party/blink/'].hatched, 0);
  // Every row's name carries a basic indicator.
  const tag = (name: string) =>
    page.$$eval('#area-chart .ar-row', (rows, n) =>
      rows.find((r) => r.querySelector('.ar-name')?.textContent === n)?.querySelector('.ar-tag')?.textContent, name);
  assert.equal(await tag('chrome/'), 'mixed');
  assert.equal(await tag('components/'), 'mixed');
  assert.equal(await tag('ios/'), 'excluded');
  assert.equal(await tag('(no file)'), 'excluded');
  assert.equal(await tag('third_party/blink/'), 'included');
  assert.equal(await page.$$eval('#area-chart .ar-row', (rs) => rs.every((r) => r.querySelector('.ar-tag'))), true);
  // Bars share one scale: the largest directory has the longest bar. chrome/
  // dwarfs the rest, so its bar is torn and the others are scaled up.
  const top = [...d.rows].filter((r) => !r.other).sort((a, b) => b.value - a.value)[0];
  assert.ok(d.rows.every((r) => r.bar <= top.bar + 0.5));
  assert.equal(top.name, 'chrome/');
  assert.ok(top.torn, 'chrome/ bar is torn');
  assert.equal(d.rows.filter((r) => r.torn).length, 1);
  const second = [...d.rows].sort((a, b) => b.value - a.value)[1];
  assert.ok(second.bar > top.bar * 0.7, `second bar ${second.bar} vs ${top.bar}`);
  // Value labels stay inside their column.
  for (const r of d.rows) assert.ok(r.labelRight <= r.volRight + 0.5, `${r.name} label overflows`);
  // The org split fills the column, with no gaps between segments.
  const blink = by['third_party/blink/'];
  const filled = blink.segs.reduce((s, w) => s + w, 0);
  assert.ok(Math.abs(filled - blink.dist) < 1.5, `${filled} vs ${blink.dist}`);
  assert.match(blink.title, /google\.com: [\d,]+ \(\d/);
  assert.match(d.sub, /are on the paths the rest of the page counts/);
  assert.equal(d.legend[d.legend.length - 1], 'Other');
  // Which paths count: Excluded, then Included below a rule; each path's
  // reason sits to its right, and the paths line up in one column. (The
  // list itself is checked against config/paths.txt in unit.test.ts.)
  assert.deepEqual(d.heads, ['Excluded', 'Included']);
  const firstIncluded = d.rules.findIndex((r) => r.group === 'true');
  assert.ok(firstIncluded > 0 && d.rules.slice(firstIncluded).every((r) => r.group === 'true'));
  assert.ok(d.groupGap > 15, `groups ${d.groupGap}px apart`);
  for (const r of d.rules) assert.ok(r.beside, `${r.path}: reason not beside it`);
  assert.equal(new Set(d.rules.map((r) => Math.round(r.left))).size, 1);
  assert.deepEqual(errors, []);
});

test('review by directory: on a phone a toggle picks one bar, beside the name', async () => {
  const shown = (page: Page) =>
    page.evaluate(() => {
      const vis = (e: Element | null) => !!e && getComputedStyle(e).display !== 'none';
      const rows = [...document.querySelectorAll<HTMLElement>('#area-chart .ar-row')];
      return {
        toggle: vis(document.querySelector('.ar-toggles')),
        vol: rows.every((r) => vis(r.querySelector('.ar-vol'))),
        dist: rows.every((r) => vis(r.querySelector('.ar-dist'))),
        // The name and the shown bar share a line.
        oneLine: rows.every((r) => {
          const bar = [...r.querySelectorAll('.ar-vol, .ar-dist')].find(vis)!.getBoundingClientRect();
          const name = r.querySelector('.ar-label')!.getBoundingClientRect();
          return Math.abs(bar.top + bar.height / 2 - (name.top + name.height / 2)) < 6 && name.right <= bar.left;
        }),
        overflow: document.documentElement.scrollWidth - window.innerWidth,
      };
    });
  const wide = await defaultPage();
  assert.deepEqual(await shown(wide.page), { toggle: false, vol: true, dist: true, oneLine: true, overflow: 0 });

  const { page, errors } = await open('', 390);
  assert.deepEqual(await shown(page), { toggle: true, vol: true, dist: false, oneLine: true, overflow: 0 });
  await page.click('#area-show input[value="orgs"]');
  assert.deepEqual(await shown(page), { toggle: true, vol: false, dist: true, oneLine: true, overflow: 0 });
  // Expanding a directory rebuilds the rows; the choice holds.
  await page.click('#area-chart .ar-toggle');
  assert.deepEqual(await shown(page), { toggle: true, vol: false, dist: true, oneLine: true, overflow: 0 });
  await page.click('#area-show input[value="volume"]');
  assert.deepEqual(await shown(page), { toggle: true, vol: true, dist: false, oneLine: true, overflow: 0 });
  assert.deepEqual(errors, []);
  await page.close();
});

test('each org segment of a directory links to its reviewers’ CLs there on Gerrit', async () => {
  const { page, errors, releaseLinks } = await open('', 1100, { holdLinks: true });
  // The links' data is fetched after the first render; until it arrives the segments aren't links.
  assert.equal(await page.$$eval('#area-chart a.ar-seg', (a) => a.length), 0);
  releaseLinks();
  await page.waitForSelector('body[data-area-links]');
  const read = () =>
    page.evaluate(() =>
      [...document.querySelectorAll<HTMLElement>('#area-chart .ar-row')].map((r) => ({
        key: r.dataset.key!,
        depth: Number(r.dataset.depth),
        kind: r.classList.contains('ar-other') ? 'other' : 'dir-or-rest',
        name: r.querySelector('.ar-name')!.textContent!,
        segs: [...r.querySelectorAll<HTMLElement>('.ar-seg')].map((s) => ({
          link: s instanceof HTMLAnchorElement ? s.href : null,
          target: s.getAttribute('target'),
          title: s.title,
        })),
      })),
    );
  // A top-level directory links to its whole subtree.
  const top = await read();
  const blink = top.find((r) => r.name === 'third_party/blink/')!;
  assert.match(blink.segs.find((s) => s.title.startsWith('google.com:'))!.link!,
    /^https:\/\/chromium-review\.googlesource\.com\/q\/dir:third_party\/blink\+after:/);
  // Drill down to components/services/storage/, where Microsoft does most of the review.
  const open1 = async (depth: number, name: string) => {
    const row = (await read()).find((r) => r.depth === depth && r.name === name)!;
    assert.ok(row, name);
    await page.click(`li[data-key="${row.key}"] .ar-toggle`);
  };
  await open1(0, 'components/');
  await open1(1, 'services/');
  const d = await read();
  const storage = d.find((r) => r.depth === 2 && r.name === 'storage/')!;
  assert.ok(storage, 'components/services/storage/ row');
  const ms = storage.segs.find((s) => s.title.startsWith('microsoft.com:'))!;
  assert.ok(ms, 'microsoft.com segment in components/services/storage/');
  assert.match(ms.link!, /^https:\/\/chromium-review\.googlesource\.com\/q\/dir:components\/services\/storage\+after:\d{4}-\d\d-\d\d\+/);
  assert.match(ms.link!, /commentby:(\d+)\+-owner:\1/);
  assert.equal(ms.target, '_blank');
  assert.match(ms.title, /Opens the CLs in components\/services\/storage\/ that .* commented on/);
  // Every segment of a real directory is a link; "(no file)", "(top-level
  // files)" and the "N more" groups can't be.
  assert.ok(d.some((r) => r.kind === 'other'), 'an "N more" row');
  for (const r of d) {
    const linkable = r.kind !== 'other' && r.name.endsWith('/');
    assert.ok(r.segs.every((s) => !!s.link === linkable), `${r.name}: ${r.segs.map((s) => s.link).join(' ')}`);
  }
  assert.deepEqual(errors, []);
  await page.close();
});

test('value ratio smoothing defaults to 3 months and is selectable', async () => {
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
        pointRadius: (ds as { pointRadius?: number | number[] }).pointRadius,
        curve: (ds as { cubicInterpolationMode?: string }).cubicInterpolationMode ?? 'default',
        sub: document.querySelector('#ratio-sub')!.textContent!,
        review: (c.reviewChart!.data.datasets.find((d: { label?: string }) => d.label === 'microsoft.com')! as
          unknown as { counts: number[] }).counts,
        reviewSub: document.querySelector('#review-sub')!.textContent!,
      };
    });
  const def = await read();
  assert.equal(def.smoothing, 13);
  assert.equal(def.checked, '13');
  assert.deepEqual(def.labels, ['Off', '4 weeks', '3 months', '1 year']);
  assert.match(def.sub, /3-month running average/);
  assert.match(def.reviewSub, /3-month running average/);

  await page.click('#smoothing input[value="4"]');
  const four = await read();
  assert.equal(four.smoothing, 4);
  assert.match(page.url(), /smooth=4/);
  // A page-wide filter, not a value-ratio-only control.
  assert.ok(await page.$('form.filters #smoothing'), 'smoothing toggle sits with the page filters');
  assert.match(four.sub, /4-week running average/);
  assert.ok(four.ratios[0] !== null, 'first week averages over weeks before the range');
  // Smoothed: a curve without dots (google.com has no gaps here).
  assert.equal(four.curve, 'monotone');
  assert.ok(Array.isArray(four.pointRadius) && four.pointRadius.every((r) => r === 0), String(four.pointRadius));

  await page.click('#smoothing input[value="1"]');
  const off = await read();
  assert.match(page.url(), /smooth=1/);
  assert.doesNotMatch(off.sub, /running average/);
  // Unsmoothed: sharp segments, also without dots.
  assert.equal(off.curve, 'default');
  assert.ok(Array.isArray(off.pointRadius) && off.pointRadius.every((r) => r === 0), String(off.pointRadius));
  assert.notDeepEqual(off.ratios, four.ratios);
  // Smoothing steadies the line: smaller week-to-week moves.
  const jitter = (r: (number | null)[]) =>
    r.slice(1).reduce<number>((s, v, i) => s + Math.abs((v ?? 0) - (r[i] ?? 0)), 0);
  assert.ok(jitter(four.ratios) < jitter(off.ratios), `${jitter(four.ratios)} vs ${jitter(off.ratios)}`);
  // The review chart follows the same setting.
  assert.match(four.reviewSub, /4-week running average/);
  assert.doesNotMatch(off.reviewSub, /running average/);
  assert.ok(off.review.every((v) => Number.isInteger(v)), 'unsmoothed counts are whole');
  assert.ok(jitter(four.review) < jitter(off.review), `${jitter(four.review)} vs ${jitter(off.review)}`);

  await page.click('#smoothing input[value="52"]');
  assert.match(page.url(), /smooth=52/);
  const year = await read();
  assert.match(year.sub, /1-year running average/);
  assert.match(year.reviewSub, /1-year running average/);
  assert.ok(year.ratios[0] !== null, 'first week averages over the year before the range');
  assert.ok(jitter(year.ratios) < jitter(four.ratios), `${jitter(year.ratios)} vs ${jitter(four.ratios)}`);
  assert.deepEqual(errors, []);
  await page.close();
});

test('date range defaults to where review and usage data overlap, and drives every chart', async () => {
  const { page, errors } = await open('#metric=comments'); // addressed narrows to classified weeks
  const read = () =>
    page.evaluate(() => {
      const c = window.__cosh!;
      return {
        range: c.state.range,
        common: c.data.ranges.common,
        full: c.data.ranges.full,
        radarFirst: [...c.data.radar.keys()].sort()[0],
        from: (document.querySelector('#from') as HTMLInputElement).value,
        to: (document.querySelector('#to') as HTMLInputElement).value,
        ratioWeeks: c.ratioChart!.data.labels as string[],
        usageWeeks: c.usageChart!.data.labels as string[],
        reviewWeeks: c.reviewChart!.data.labels as string[],
        reviewTotal: c.reviewChart!.data.datasets
          .flatMap((ds) => (ds as unknown as { counts: number[] }).counts)
          .reduce((s: number, v: number) => s + v, 0),
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
  // The ratio chart's 3-month average starts once its window is full of
  // data, 12 weeks in; then it follows the review chart to the range's end.
  assert.equal(d.ratioWeeks[0], addWeeks(d.range.from, 12));
  assert.deepEqual(d.reviewWeeks.slice(d.reviewWeeks.length - d.ratioWeeks.length), d.ratioWeeks);
  // "All data" stays out of the URL, so a reload follows new data and keeps it picked.
  assert.doesNotMatch(page.url(), /from=|to=/);
  const pinned = await open(`#metric=comments&from=${d.range.from}&to=${d.range.to}`);
  assert.equal(await pinned.page.$eval('#range-presets [aria-pressed="true"]', (b) => b.textContent), 'All data');
  assert.doesNotMatch(pinned.page.url(), /from=|to=/);
  await pinned.page.close();

  // Pick an earlier start date, four weeks before the default start: the
  // usage chart widens to the week of that date, or to the earliest week with
  // any data when that is later (review data now starts with Radar's, so the
  // default start may already be the earliest).
  const earlier = new Date(Date.parse(`${d.from}T00:00:00Z`) - 26 * 86_400_000); // a Wednesday
  const earlierWeek = isoWeekOf(earlier) < d.full.from ? d.full.from : isoWeekOf(earlier);
  await page.$eval(
    '#from',
    (i, v) => {
      const input = i as HTMLInputElement;
      input.value = v;
      input.dispatchEvent(new Event('change', { bubbles: true }));
    },
    earlier.toISOString().slice(0, 10),
  );
  const wide = await read();
  assert.equal(wide.range.from, earlierWeek);
  // Radar's first week (2023-W27; its data starts Saturday 2023-07-01) can be
  // later than the earliest review week the pickers allow.
  assert.equal(wide.usageWeeks[0], earlierWeek < d.radarFirst ? d.radarFirst : earlierWeek);
  assert.equal(wide.pressed, undefined);
  assert.match(page.url(), new RegExp(`from=${earlierWeek}`));
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
  const { page } = await defaultPage();
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
      values: c.data.datasets.flatMap((d) => d.data as (number | null)[]),
      zeros: c.data.datasets.flatMap((d) => (d as unknown as { counts: number[] }).counts).filter((v) => v === 0).length,
      yMin: c.scales.y.min,
      bottomTick: c.scales.y.ticks[0]?.label,
    };
  });
  assert.equal(chart.type, 'line');
  // Weeks without review are zeros, not gaps, drawn on a bottom "0" line
  // below every positive value.
  assert.ok(chart.values.every((v) => typeof v === 'number' && v > 0), 'no gaps');
  assert.ok(chart.zeros > 0, 'the default range has weeks without review for some org');
  assert.equal(chart.values.filter((v) => v === chart.yMin).length, chart.zeros, 'zeros sit on the axis floor');
  assert.equal(chart.bottomTick, '0');
  assert.equal(chart.yType, 'logarithmic');
  assert.equal(chart.orgs[0], 'google.com');
  assert.equal(chart.orgs[chart.orgs.length - 1], 'Other');
  assert.ok(chart.orgs.length <= 8);
  assert.ok(chart.sameColor, 'orgs keep their ratio-chart colour');
  // Every named org gets its own colour.
  assert.equal(new Set(chart.colors.slice(0, -1)).size, chart.orgs.length - 1, JSON.stringify(chart.colors));
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
  // The same named orgs less google.com: no small org is promoted into its place.
  assert.deepEqual(lin.orgs, log.orgs.filter((o) => o !== 'google.com'));
  // Orgs in both views keep their colour.
  for (const org of lin.orgs.filter((o): o is string => !!o && log.orgs.includes(o))) {
    assert.equal(lin.colors[org], log.colors[org], org);
  }
  assert.doesNotMatch(lin.title, /log scale/);
  assert.equal(lin.sub, log.sub, 'the scale toggle leaves the description alone');
  assert.match(page.url(), /rscale=linear/);
  await page.click('#review-scale input[value="log"]');
  assert.doesNotMatch(page.url(), /rscale/);
  assert.deepEqual(errors, []);
  await page.close();
});

test('leaderboard shows up to 25 reviewers compactly', async () => {
  const { page } = await open('#metric=comments');
  const read = () =>
    page.evaluate(() => {
      const box = document.querySelector('#leaderboard-chart')!;
      const rows = [...box.querySelectorAll<HTMLElement>('.lb-row')];
      return {
        n: rows.length,
        values: rows.map((r) => Number(r.querySelector('.lb-value')!.textContent!.replace(/,/g, ''))),
        top: rows[0].querySelector('.lb-label')!.textContent!,
        title: rows[0].title,
        tags: rows.map((r) => r.tagName),
        h: box.getBoundingClientRect().height,
      };
    });
  const comments = await read();
  assert.ok(comments.n > 10 && comments.n <= 25, `n=${comments.n}`);
  assert.deepEqual(comments.values, [...comments.values].sort((a, b) => b - a));
  assert.match(comments.top, /^1\. [^·]+$/); // rank and name only; the org is the bar colour
  // The hover text gives the email (not the name or org), then the count with the metric.
  assert.match(comments.title, /^1\. [^@\s]+@[^@\s]+\.[a-z]+\n[\d,]+ review comments\n/i);
  // Each row is a button that opens the reviewer's weekly chart.
  assert.ok(comments.tags.every((t) => t === 'BUTTON'), `tags=${comments.tags}`);
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
  await pickMetric(page, 'cls');
  const cls = await read();
  assert.match(cls.title, /\n[\d,]+ reviewed cls\n/i);
  assert.notDeepEqual(cls.values, comments.values);
  await page.close();
});

test('a control in one section rebuilds only that section; the metric and range rebuild them all', async () => {
  const { page, errors } = await open('#metric=comments');
  // What each section builds: its Chart.js chart, or the root of its rows.
  const parts = {
    parity: 'parityChart', ratio: 'ratioChart', review: 'reviewChart', dist: 'distChart', perReview: 'perReviewChart',
    table: '#org-table tbody', areas: '#area-chart', heat: '#heat-chart', cx: '#cx-chart', leaderboard: '#leaderboard-chart',
  } as const;
  type Part = keyof typeof parts;
  // Tags every part, runs `act`, and lists the parts it replaced.
  const rebuilt = async (act: () => Promise<unknown>) => {
    await page.evaluate((parts) => {
      for (const [k, v] of Object.entries(parts)) {
        const o = (v.startsWith('#')
          ? document.querySelector(v)!.firstElementChild
          : (window.__cosh as unknown as Record<string, object>)[v]) as unknown as Record<string, string>;
        o.__tag = k;
      }
    }, parts);
    await act();
    await page.waitForSelector('body:not([data-pending])');
    return page.evaluate((parts) => Object.entries(parts).filter(([k, v]) => {
      const o = (v.startsWith('#')
        ? document.querySelector(v)!.firstElementChild
        : (window.__cosh as unknown as Record<string, object>)[v]) as unknown as Record<string, string> | null;
      return o?.__tag !== k;
    }).map(([k]) => k), parts) as Promise<Part[]>;
  };
  const click = (sel: string) => () => page.click(sel);
  const select = (sel: string, v: string) => () => page.select(sel, v);
  assert.deepEqual(await rebuilt(click('#smoothing input[value="4"]')), ['ratio', 'review']);
  assert.deepEqual(await rebuilt(click('#review-scale input[value="linear"]')), ['review']);
  assert.deepEqual(await rebuilt(click('#heat-bin input[value="13"]')), ['heat']);
  assert.deepEqual(await rebuilt(click('#heat-value input[value="share"]')), ['heat']);
  assert.deepEqual(await rebuilt(select('#heat-org', '*-google.com')), ['heat']);
  assert.deepEqual(await rebuilt(click('#cx-bin input[value="4"]')), ['cx']);
  assert.deepEqual(await rebuilt(click('#cx-value input[value="volume"]')), ['cx']);
  assert.deepEqual(await rebuilt(select('#leaderboard-size', '50')), ['leaderboard']);
  assert.deepEqual(await rebuilt(select('#leaderboard-org', '*-google.com')), ['leaderboard']);
  assert.deepEqual(await rebuilt(click('#heat-chart .ar-toggle')), ['heat']);
  assert.deepEqual(await rebuilt(click('#cx-chart .ar-toggle')), ['cx']);
  // Picking a reviewer only marks them in the leaderboard and the spreads.
  assert.deepEqual(await rebuilt(click('#leaderboard-chart li:nth-child(3) .lb-row')), []);
  const id = await page.$eval('#leaderboard-chart li:nth-child(3) .lb-row', (b) => Number((b as HTMLElement).dataset.account));
  assert.equal(await page.evaluate(() => window.__cosh!.state.lbReviewer), id);
  assert.deepEqual(
    await page.$$eval('#leaderboard-chart .lb-row[aria-pressed="true"]', (bs) => bs.map((b) => Number((b as HTMLElement).dataset.account))),
    [id],
  );
  assert.equal(await page.$eval('#reviewer-detail', (d) => (d as HTMLElement).hidden), false);
  assert.deepEqual(await rebuilt(click('#rd-close')), []);
  assert.equal(await page.$$eval('#leaderboard-chart .lb-row[aria-pressed="true"]', (bs) => bs.length), 0);
  // The top controls change every section.
  assert.deepEqual(await rebuilt(() => pickMetric(page, 'chars')), Object.keys(parts));
  assert.deepEqual(await rebuilt(click('#range-presets button[data-preset="13"]')), Object.keys(parts));
  // Each control's state still reaches the URL.
  const hash = await page.evaluate(() => location.hash);
  for (const p of ['smooth=4', 'rscale=linear', 'hmb=13', 'hmv=share', 'hm=*-google.com', 'cxb=4', 'cxv=volume', 'lbn=50', 'lbo=*-google.com', 'metric=chars'])
    assert.ok(decodeURIComponent(hash).includes(p), `${p} in ${hash}`);
  assert.deepEqual(errors, []);
  await page.close();
});

test('clicking a reviewer opens their weekly chart with a Gerrit link; Close and the URL', async () => {
  const { page, errors } = await open();
  assert.equal(await page.$eval('#reviewer-detail', (d) => (d as HTMLElement).hidden), true);
  await page.click('#leaderboard-chart li:nth-child(2) .lb-row');
  const detail = await page.evaluate(() => ({
    hidden: document.querySelector<HTMLElement>('#reviewer-detail')!.hidden,
    title: document.querySelector('#rd-title')!.textContent ?? '',
    name: document.querySelector('#leaderboard-chart li:nth-child(2) .lb-name')!.textContent ?? '',
    pressed: document.querySelector('#leaderboard-chart li:nth-child(2) .lb-row')!.getAttribute('aria-pressed'),
    link: document.querySelector<HTMLAnchorElement>('#rd-gerrit')!.href,
    target: document.querySelector('#rd-gerrit')!.getAttribute('target'),
    sub: document.querySelector('#rd-sub')!.textContent ?? '',
  }));
  assert.equal(detail.hidden, false);
  assert.ok(detail.title.startsWith(detail.name), `${detail.title} / ${detail.name}`);
  assert.equal(detail.pressed, 'true');
  // The CLs the reviewer commented on (and doesn't own) in the range, on Gerrit, in a new tab.
  assert.match(detail.link,
    /^https:\/\/chromium-review\.googlesource\.com\/q\/commentby:([^@\s/+]+@[^@\s/+]+)\+-owner:\1\+after:\d{4}-\d\d-\d\d(\+before:\d{4}-\d\d-\d\d)?$/);
  assert.equal(detail.target, '_blank');
  // The title gives the account's email, not its org.
  const email = decodeURIComponent(detail.link.match(/commentby:([^+]+)/)![1]);
  assert.equal(detail.title, `${detail.name} (${email})`);
  assert.match(detail.sub, /review comments in/);
  const chart = await page.evaluate(() => {
    const c = (window as unknown as { Chart?: unknown }).Chart;
    const canvas = document.querySelector<HTMLCanvasElement>('#reviewer-chart')!;
    return { c: !!c, w: canvas.getBoundingClientRect().width };
  });
  assert.ok(chart.w > 100);
  assert.match(page.url(), /lbr=\d+/);
  await page.click('#rd-close');
  assert.equal(await page.$eval('#reviewer-detail', (d) => (d as HTMLElement).hidden), true);
  assert.doesNotMatch(page.url(), /lbr=/);
  assert.deepEqual(errors, []);
  await page.close();
});

test.skipIf(!hasAddressedWeeks())('thread box: outcome breakdown and example threads loaded on open', async () => {
  const classified = addressedWeeks(summary);
  const last = classified[classified.length - 1];
  const { page, errors } = await open(`#metric=comments&from=${last}&to=${last}`);
  const box = await page.evaluate(() => ({
    hidden: document.querySelector<HTMLElement>('#threads')!.hidden,
    segs: [...document.querySelectorAll<HTMLElement>('#threads-bar .tb-seg')].map((s) => Number(s.style.getPropertyValue('--share')) * 100),
    legend: [...document.querySelectorAll('#threads-legend li')].map((l) => l.textContent ?? ''),
    sub: document.querySelector('#threads-sub')!.textContent ?? '',
  }));
  assert.equal(box.hidden, false);
  assert.ok(Math.abs(box.segs.reduce((a, b) => a + b, 0) - 100) < 0.01, `segments ${box.segs}`);
  assert.ok(box.legend.some((l) => /owner replied “Done”/.test(l)), box.legend.join(' | '));
  assert.match(box.sub, /on the counted paths, by how each was decided/);
  // Examples load only when a list is opened.
  await page.click('#threads-examples details[data-outcome="model_addressed"] summary');
  await page.waitForSelector('#threads-examples details[data-outcome="model_addressed"] .tb-thread');
  const ex = await page.$eval('#threads-examples details[data-outcome="model_addressed"] .tb-thread', (t) => ({
    link: t.querySelector('a')!.getAttribute('href') ?? '',
    roles: [...t.querySelectorAll('.tb-role')].map((r) => r.textContent),
  }));
  assert.match(ex.link, /^https:\/\/chromium-review\.googlesource\.com\/c\/chromium\/src\/\+\/\d+\/comment\/[^/]+\/$/);
  assert.equal(ex.roles[0], 'reviewer');
  assert.deepEqual(errors, []);
  await page.close();
});

test('review complexity over time: directories by reviews, cells shaded by the metric per review, and it expands', async () => {
  const { page, errors } = await open();
  const read = () =>
    page.evaluate(() => ({
      title: document.querySelector('#cx-title')!.textContent!,
      sub: document.querySelector('#cx-sub')!.textContent!,
      legend: document.querySelector('#cx-legend')!.textContent!,
      bins: document.querySelectorAll('#cx-table thead .hm-bin').length,
      rows: [...document.querySelectorAll<HTMLElement>('#cx-table .hm-row')].map((r) => {
        const th = r.querySelector<HTMLElement>('.hm-label')!;
        return {
          key: r.dataset.key!,
          depth: Number(r.dataset.depth),
          name: th.querySelector('.hm-name')!.textContent!,
          total: th.querySelector('.hm-total')!.textContent!,
          reviews: Number(/over ([\d,]+) reviews/.exec(th.title)![1].replace(/,/g, '')),
          cells: [...r.querySelectorAll<HTMLElement>('.hm-box')].map((b) => ({
            shaded: b.classList.contains('hm-shade'),
            t: Number(b.style.getPropertyValue('--t') || NaN),
            title: b.title,
          })),
        };
      }),
    }));
  const v = await read();
  assert.equal(v.title, 'Review complexity by directory over time');
  assert.match(v.sub, /^How review complexity varies across the codebase: each cell is a directory's addressed comments per review/);
  assert.match(v.sub, /All directories together: \d+\.\d\d per review over [\d,]+ reviews/);
  // The legend is the ramp only: no swatch that looks like a checkbox.
  assert.match(v.legend, /^\d+\.\d\d or less\s*\d+\.\d\d or more addressed comments per review$/);
  assert.equal(await page.$$eval('#cx-legend .swatch', (s) => s.length), 0);
  // Rows: most reviews first, each with its own figure; (no file) is left out.
  const top = v.rows.filter((r) => r.key.startsWith('d'));
  assert.ok(top.length >= 10, `${top.length} top-level directories`);
  for (let i = 1; i < top.length; i++) assert.ok(top[i - 1].reviews >= top[i].reviews, `${top[i - 1].name} >= ${top[i].name}`);
  for (const r of top) assert.match(r.total, /^\d+\.\d\d$/, r.name);
  assert.ok(!v.rows.some((r) => r.name === '(no file)'));
  // Every row has a cell per column; busy directories are shaded throughout, on 0..1.
  for (const r of v.rows) assert.equal(r.cells.length, v.bins, r.name);
  const blink = v.rows.find((r) => r.name === 'third_party/blink/')!;
  assert.ok(blink.cells.every((c) => c.shaded && c.t >= 0 && c.t <= 1), 'blink is shaded in every column');
  assert.match(blink.cells.at(-1)!.title, /\n\d+\.\d\d addressed comments per review \([\d,]+ over [\d,]+ reviews\)$/);
  // Cells with too few reviews stay grey and say so.
  const few = v.rows.flatMap((r) => r.cells).filter((c) => !c.shaded);
  assert.ok(few.every((c) => /too few reviews to shade$|No reviews$/.test(c.title)));
  // Expanding a directory lists its subdirectories, whose reviews add up to it.
  await page.click(`#cx-table tr[data-key="${blink.key}"] .ar-toggle`);
  const after = (await read()).rows;
  const i = after.findIndex((r) => r.key === blink.key);
  const end = after.findIndex((r, j) => j > i && r.depth === 0);
  const kids = after.slice(i + 1, end).filter((r) => r.depth === 1);
  assert.ok(kids.length > 1);
  assert.equal(kids.reduce((s, r) => s + r.reviews, 0), blink.reviews);
  assert.equal(await page.evaluate(() => document.activeElement?.closest('tr')?.dataset.key), blink.key);
  // Columns: 3 months by default; a year gives fewer, and goes in the URL.
  await page.click('#cx-bin input[value="52"]');
  assert.ok((await read()).bins < v.bins);
  assert.match(await page.evaluate(() => location.hash), /&cxb=52/);
  // Volume: cells shaded by reviews (every cell with one), rows totalled in
  // reviews, the legend up to the busiest cell; it goes in the URL.
  await page.click('#cx-value input[value="volume"]');
  const vol = await read();
  assert.match(vol.legend, /^1\s*[\d,]+ reviews$/);
  assert.match(await page.evaluate(() => location.hash), /&cxv=volume/);
  for (const r of vol.rows) {
    assert.equal(Number(r.total.replace(/,/g, '')), r.reviews, r.name);
    for (const c of r.cells) assert.equal(c.shaded, !/No reviews$/.test(c.title), `${r.name}: ${c.title}`);
  }
  // Busier directories are shaded more strongly, as a rule.
  const mean = (r: (typeof vol.rows)[number]) => r.cells.reduce((s, c) => s + (c.t || 0), 0) / r.cells.length;
  const vtop = vol.rows.filter((r) => r.depth === 0);
  assert.ok(mean(vtop[0]) > mean(vtop[vtop.length - 2]));
  await page.click('#cx-value input[value="complexity"]');
  assert.match((await read()).legend, /or more addressed comments per review$/);
  assert.doesNotMatch(await page.evaluate(() => location.hash), /cxv=/);
  // Reviewed CLs as the metric: review comments per review.
  await page.click('#metric input[value="cls"]');
  await page.waitForFunction(() => /review comments per review/.test(document.querySelector('#cx-legend')!.textContent!));
  assert.deepEqual(errors, []);
  await page.close();
});

test('per-reviewer spread: a row of dots per org, a figures table, and clicking a dot opens the reviewer', async () => {
  const { page, errors } = await open('#metric=comments');
  const read = () =>
    page.evaluate(() => {
      const c = window.__cosh!.distChart!;
      return {
        sets: c.data.datasets.map((d) => ({ org: d.label!, n: d.data.length })),
        table: [...document.querySelectorAll<HTMLTableRowElement>('#dist-table tbody tr')].map((tr) => ({
          org: tr.dataset.org!,
          cells: [...tr.querySelectorAll('td')].map((td) => td.textContent!),
        })),
        // Reviewers with a review comment in the range, straight from the data.
        reviewers: (() => {
          const { data, state } = window.__cosh!;
          const sum = new Map<number, number>();
          for (const [w, rows] of Object.entries(data.reviewers.weeks)) {
            if (w < state.range.from || w > state.range.to) continue;
            for (const r of rows) sum.set(r[0], (sum.get(r[0]) ?? 0) + r[2]);
          }
          return [...sum.values()].filter((c) => c > 0).length;
        })(),
        h: c.height,
        yLabels: c.scales.y.ticks.map((t) => String(t.label)),
      };
    });
  const v = await read();
  const orgs = v.sets.map((x) => x.org);
  assert.equal(orgs[0], 'google.com');
  assert.ok(orgs.includes('microsoft.com'));
  assert.equal(orgs[orgs.length - 1], 'Other');
  assert.ok(!orgs.includes('gmail.com'), 'personal addresses are in Other');
  assert.ok(orgs.length > 5 && orgs.length <= 11, orgs.join());
  // Every reviewer with a review comment is one dot.
  assert.equal(v.sets.reduce((a, x) => a + x.n, 0), v.reviewers);
  // The chart grows with its rows; rows are labelled with their reviewer counts.
  assert.ok(v.h >= orgs.length * 30, `height ${v.h} for ${orgs.length} rows`);
  assert.match(v.yLabels[0], /^google\.com \([\d,]+\)$/);
  // The table lists the same orgs with ascending quartiles.
  assert.deepEqual(v.table.map((r) => r.org), orgs);
  for (const r of v.table) {
    const [n, q1, med, q3] = r.cells.slice(0, 4).map((c) => Number(c.replace(/,/g, '')));
    assert.ok(n > 0 && q1 <= med && med <= q3, `${r.org}: ${r.cells}`);
    assert.match(r.cells[4], /^[\d.]+%$/);
  }
  // Clicking a dot opens that reviewer's weekly chart.
  const pt = await page.evaluate(() => {
    const c = window.__cosh!.distChart!;
    const meta = c.getDatasetMeta(1);
    const el = meta.data[meta.data.length - 1];
    const r = c.canvas.getBoundingClientRect();
    return { x: r.left + el.x, y: r.top + el.y, id: (c.data.datasets[1].data[meta.data.length - 1] as unknown as { id: number }).id };
  });
  await page.$eval('#distribution', (e) => e.scrollIntoView());
  const pt2 = await page.evaluate(() => {
    const c = window.__cosh!.distChart!;
    const meta = c.getDatasetMeta(1);
    const el = meta.data[meta.data.length - 1];
    const r = c.canvas.getBoundingClientRect();
    return { x: r.left + el.x, y: r.top + el.y };
  });
  // The tooltip names the reviewer by email, not name and org.
  const label = await page.evaluate(() => {
    const c = window.__cosh!.distChart!;
    const meta = c.getDatasetMeta(1);
    const i = meta.data.length - 1;
    const cb = c.options.plugins!.tooltip!.callbacks!.label as unknown as (ctx: unknown) => string;
    return cb({ raw: c.data.datasets[1].data[i], dataset: c.data.datasets[1] });
  });
  assert.match(label, /^[^@\s]+@[^@\s]+\.[a-z]+: [\d,]+ review comments$/);
  await page.mouse.click(pt2.x, pt2.y);
  await page.waitForFunction(() => !document.querySelector<HTMLElement>('#reviewer-detail')!.hidden);
  assert.match(page.url(), new RegExp(`lbr=${pt.id}`));
  // Under addressed comments, reviewers whose comments led to no change sit at 0.
  if (hasAddressedWeeks()) {
    await pickMetric(page, 'addressed');
    const first = await page.evaluate(() => String(window.__cosh!.distChart!.scales.x.ticks[0].label));
    assert.equal(first, '0');
    assert.match(await page.$eval('#dist-sub', (e) => e.textContent!), /none addressed sit at 0/);
  }
  assert.deepEqual(errors, []);
  await page.close();
});

test('an org keeps one colour in every section, value charts included, whatever the filters', async () => {
  const colorsOn = async (hash: string) => {
    const { page, errors } = hash ? await open(hash) : await defaultPage();
    const out = await page.evaluate(() => {
      const norm = (c: string) => {
        const d = document.createElement('div');
        d.style.color = c;
        document.body.append(d);
        const v = getComputedStyle(d).color;
        d.remove();
        return v;
      };
      const seen: [string, string, string][] = [];
      for (const d of window.__cosh!.reviewChart!.data.datasets as { label: string; borderColor: string; borderDash?: number[] }[]) {
        // Dashed grey: a named org without a colour of its own.
        if (d.label !== 'Other' && !d.borderDash) seen.push(['review', d.label, norm(d.borderColor)]);
      }
      for (const d of window.__cosh!.ratioChart!.data.datasets as { label: string; borderColor: string }[]) {
        seen.push(['ratio', d.label, norm(d.borderColor)]);
      }
      for (const sel of ['#leaderboard-legend', '#heat-legend']) {
        for (const li of document.querySelectorAll(`${sel} li`)) {
          const sw = li.querySelector<HTMLElement>('.swatch:not(.swatch-muted)');
          const org = li.textContent!.replace(/ \(\d+\)$/, '').trim();
          const c = sw?.style.getPropertyValue('--color');
          if (c && org !== 'Other') seen.push([sel, org, norm(c)]);
        }
      }
      return seen;
    });
    assert.deepEqual(errors, []);
    if (hash) await page.close();
    return out;
  };
  const all = [
    ...(await colorsOn('')),
    ...(await colorsOn('#lbo=igalia.com&hm=*-google.com&rscale=linear')),
    ...(await colorsOn('#lbo=*-google.com&lbn=100&hm=intel.com&from=2026-W40&to=2026-W44')),
  ];
  const byOrg = new Map<string, Set<string>>();
  for (const [, org, c] of all) byOrg.set(org, (byOrg.get(org) ?? new Set()).add(c));
  assert.ok(byOrg.has('igalia.com') && byOrg.has('samsung.com') && byOrg.size >= 8, [...byOrg.keys()].join());
  for (const [org, cs] of byOrg) assert.equal(cs.size, 1, `${org}: ${[...cs].join(' / ')}`);
  // And no two orgs share one.
  const owner = new Map<string, string>();
  for (const [org, cs] of byOrg) {
    const c = [...cs][0];
    assert.ok(!owner.has(c) || owner.get(c) === org, `${org} and ${owner.get(c)} share ${c}`);
    owner.set(c, org);
  }
});

test('a named org without a colour still gets its own series and legend entries, in grey', async () => {
  // januschka.com wrote over 0.25% of review comments in 2024-W37..W40, but
  // ranks too low over all the data for one of the 12 org colours.
  const { page, errors } = await open('#metric=comments&from=2024-W37&to=2024-W40');
  const v = await page.evaluate(() => {
    const ds = window.__cosh!.reviewChart!.data.datasets as { label: string; borderColor: string; borderDash?: number[] }[];
    const legend = (sel: string) =>
      [...document.querySelectorAll(`${sel} li`)].map((li) => ({
        org: li.textContent!.replace(/ \(\d+\)$/, '').trim(),
        muted: !!li.querySelector('.swatch-muted'),
      }));
    const muted = getComputedStyle(document.documentElement).getPropertyValue('--text-muted').trim();
    return {
      review: ds.map((d) => ({ org: d.label, dashed: !!d.borderDash, grey: d.borderColor === muted })),
      areas: legend('#areas-legend'),
    };
  });
  assert.deepEqual(errors, []);
  await page.close();
  const j = v.review.find((d) => d.org === 'januschka.com');
  assert.ok(j, JSON.stringify(v.review));
  assert.ok(j.dashed && j.grey, JSON.stringify(j));
  // Coloured orgs and Other stay solid.
  assert.ok(v.review.filter((d) => d.org !== 'januschka.com').every((d) => !d.dashed), JSON.stringify(v.review));
  assert.deepEqual(v.areas.find((l) => l.org === 'januschka.com'), { org: 'januschka.com', muted: true }, JSON.stringify(v.areas));
});

test('per-review spread: the metric per reviewed CL, on the per-reviewer rows; review comments under reviewed CLs', async () => {
  const { page, errors } = await open('#metric=cls');
  const read = () =>
    page.evaluate(() => {
      const { data, state, perReviewChart: c, distChart: d } = window.__cosh!;
      // Each reviewer's comments and reviewed CLs in the range, straight from the data.
      const sums = new Map<number, [number, number]>();
      for (const [w, rows] of Object.entries(data.reviewers.weeks)) {
        if (w < state.range.from || w > state.range.to) continue;
        for (const r of rows) {
          const s = sums.get(r[0]) ?? [0, 0];
          s[0] += r[2];
          s[1] += r[3];
          sums.set(r[0], s);
        }
      }
      const pts = c!.data.datasets.flatMap((ds) => ds.data as unknown as { id: number; value: number }[]);
      return {
        title: document.querySelector('#pr-title')!.textContent,
        orgs: c!.data.datasets.map((ds) => ds.label!),
        distOrgs: d!.data.datasets.map((ds) => ds.label!),
        bad: pts.filter((p) => {
          const [cm, cl] = sums.get(p.id)!;
          return cl < 3 || Math.abs(p.value - cm / cl) > 1e-9;
        }).length,
        n: pts.length,
        eligible: [...sums.values()].filter(([cm, cl]) => cm > 0 && cl >= 3).length,
        table: [...document.querySelectorAll<HTMLTableRowElement>('#pr-table tbody tr')].map((tr) => ({
          org: tr.dataset.org!,
          cells: [...tr.querySelectorAll('td')].map((td) => Number(td.textContent!.replace(/,/g, ''))),
        })),
        label: (() => {
          const cb = c!.options.plugins!.tooltip!.callbacks!.label as unknown as (ctx: unknown) => string;
          return cb({ raw: c!.data.datasets[0].data[0], dataset: c!.data.datasets[0] });
        })(),
      };
    });
  const v = await read();
  assert.equal(v.title, 'Review comments per review');
  // A linear axis from 0 here; the per-reviewer spread keeps its log axis.
  assert.deepEqual(await page.evaluate(() => [window.__cosh!.perReviewChart!.scales.x.type,
    window.__cosh!.perReviewChart!.scales.x.min, window.__cosh!.distChart!.scales.x.type]), ['linear', 0, 'logarithmic']);
  // Same rows, in the same order, as the per-reviewer spread above it.
  assert.deepEqual(v.orgs, v.distOrgs.filter((o) => v.orgs.includes(o)));
  assert.equal(v.orgs[0], 'google.com');
  assert.equal(v.orgs[v.orgs.length - 1], 'Other');
  // Every reviewer with a comment and 3+ reviewed CLs is one dot, at comments ÷ CLs.
  assert.ok(v.n > 0);
  assert.equal(v.n, v.eligible);
  assert.equal(v.bad, 0);
  assert.deepEqual(v.table.map((r) => r.org), v.orgs);
  for (const r of v.table) {
    const [n, q1, med, q3, pooled] = r.cells;
    assert.ok(n > 0 && q1 <= med && med <= q3 && pooled > 0, `${r.org}: ${r.cells}`);
  }
  assert.match(v.label, /^[^@\s]+@[^@\s]+\.[a-z]+: [\d.,]+ review comments per review$/);
  // Another metric: that metric per review.
  await page.evaluate(() => {
    window.__cosh!.state.metric = 'chars';
    window.__cosh!.render();
  });
  assert.equal(await page.$eval('#pr-title', (e) => e.textContent), 'Review characters per review');
  // Other metrics have no cap: the axis reaches the largest value.
  assert.ok(await page.evaluate(() => {
    const c = window.__cosh!.perReviewChart!;
    const vals = c.data.datasets.flatMap((ds) => (ds.data as unknown as { value: number }[]).map((p) => p.value));
    return c.scales.x.max >= Math.max(...vals);
  }));
  // Addressed comments per review: the axis ends just past 9, and reviewers
  // above it sit in a margin slot labelled ">9", their tooltips giving the value.
  await page.evaluate(() => {
    window.__cosh!.state.metric = 'addressed';
    window.__cosh!.render();
  });
  const capped = await page.evaluate(() => {
    const c = window.__cosh!.perReviewChart!;
    const pts = c.data.datasets.flatMap((ds) => ds.data as unknown as { x: number; value: number }[]);
    const over = pts.filter((p) => p.value > 9);
    const cb = c.options.plugins!.tooltip!.callbacks!.label as unknown as (ctx: unknown) => string;
    return {
      max: c.scales.x.max,
      labels: c.scales.x.ticks.map((t) => t.label),
      over: over.length,
      overX: [...new Set(over.map((p) => p.x))],
      inside: pts.every((p) => p.value > 9 || p.x === p.value),
      overLabel: over.length ? cb({ raw: over[0] }) : '',
      overValue: over.length ? over[0].value : 0,
      sub: document.querySelector('#pr-sub')!.textContent!,
    };
  });
  assert.ok(capped.over > 0, 'the real data has addressed-per-review outliers above 9');
  assert.ok(capped.max > 9 && capped.max < 10, `max ${capped.max}`);
  assert.equal(capped.labels[capped.labels.length - 1], '>9');
  assert.ok(Number(capped.labels[capped.labels.length - 2]) <= 9);
  assert.equal(capped.overX.length, 1);
  assert.ok(capped.overX[0] > 9 && capped.overX[0] < capped.max);
  assert.ok(capped.inside);
  assert.ok(capped.overLabel.includes(capped.overValue.toLocaleString('en-US', { maximumFractionDigits: 1 })), capped.overLabel);
  assert.match(capped.sub, /above 9 sit in the right margin/);
  // The section sits below the per-reviewer spread, just after review complexity.
  assert.equal(await page.$eval('#distribution', (e) => e.nextElementSibling!.id), 'complexity');
  assert.equal(await page.$eval('#complexity', (e) => e.nextElementSibling!.id), 'per-review');
  assert.deepEqual(errors, []);
  await page.close();
});

test('leaderboard size and organization selects; every org is named, none as "other"', async () => {
  const { page, errors } = await open();
  const read = () =>
    page.evaluate(() => {
      const rows = [...document.querySelectorAll<HTMLElement>('#leaderboard-chart .lb-row')];
      return {
        n: rows.length,
        orgs: rows.map((r) => r.dataset.org!),
        inline: rows.map((r) => r.querySelector('.lb-org')?.textContent ?? null),
        colored: rows.map((r) => (r.querySelector<HTMLElement>('.lb-bar')!.style.getPropertyValue('--color') ? 1 : 0)),
        legend: document.querySelector('#leaderboard-legend')!.textContent!,
        legendOrgs: [...document.querySelectorAll('#leaderboard-legend li')].map((li) => li.textContent!.replace(/ \(\d+\)$/, '')),
        sub: document.querySelector('#leaderboard-sub')!.textContent!,
      };
    });
  const check = (v: Awaited<ReturnType<typeof read>>) => {
    assert.doesNotMatch(v.legend, /other/i);
    // Coloured orgs are in the legend; uncoloured rows name their org instead
    // and stay out of it (Show: All would make that entry very long).
    v.orgs.forEach((org, i) => assert.equal(v.legendOrgs.includes(org), v.colored[i] === 1, `${org} in legend`));
    v.orgs.forEach((org, i) => assert.equal(v.inline[i], v.colored[i] ? null : ` · ${org}`));
  };
  const top25 = await read();
  check(top25);
  assert.ok(top25.orgs.includes('google.com'));
  await page.select('#leaderboard-size', '100');
  assert.match(page.url(), /lbn=100/);
  const top100 = await read();
  check(top100);
  assert.ok(top100.n > 50 && top100.n <= 100, `n=${top100.n}`);
  await page.select('#leaderboard-org', '*-google.com');
  assert.match(page.url(), /lbo=\*-google\.com/);
  const noGoogle = await read();
  check(noGoogle);
  assert.ok(!noGoogle.orgs.includes('google.com'));
  assert.ok(noGoogle.n > 50, `n=${noGoogle.n}`);
  assert.equal(noGoogle.sub, top25.sub, 'the toggles leave the description alone');
  assert.match(noGoogle.sub, /counted as in Review by organization/);
  // Old lbg=0 links still leave google.com out; a link can ask for every reviewer.
  const { page: old } = await open('#lbg=0&lbn=all');
  assert.deepEqual(await old.$$eval('#leaderboard-org, #leaderboard-size', (es) => es.map((e) => (e as HTMLSelectElement).value)),
    ['*-google.com', 'all']);
  await old.close();
  // One org: every row is that org's, and the choices are the busiest orgs.
  const options = await page.$$eval('#leaderboard-org option', (os) => os.map((o) => (o as HTMLOptionElement).value));
  assert.deepEqual(options.slice(0, 3), ['*', '*-google.com', 'google.com']);
  const one = options[3];
  await page.select('#leaderboard-org', one);
  assert.ok(page.url().includes(`lbo=${encodeURIComponent(one)}`), page.url());
  const single = await read();
  check(single);
  assert.ok(single.n > 0);
  assert.deepEqual([...new Set(single.orgs)], [one]);
  assert.equal(single.sub, top25.sub, 'the selects leave the description alone');
  // The named orgs (enough of the range's review comments), then "Other": everyone else, combined.
  const at = options.indexOf('*other');
  const named = options.slice(2, at);
  assert.deepEqual([...named].sort(), (await namedOn(page)).sort(), options.join());
  assert.ok(named.length >= 4, named.join());
  await page.select('#leaderboard-org', '*other');
  assert.match(page.url(), /lbo=\*other/);
  const rest = await read();
  check(rest);
  assert.ok(rest.n > 0);
  assert.ok(rest.orgs.every((o) => !named.includes(o)), rest.orgs.join());
  // Show: All lists every reviewer, from the data already loaded.
  await page.select('#leaderboard-org', '*');
  const requests: string[] = [];
  page.on('request', (r) => requests.push(r.url()));
  await page.select('#leaderboard-size', 'all');
  assert.match(page.url(), /lbn=all/);
  const all = await read();
  check(all);
  assert.ok(all.n > 200, `n=${all.n}`);
  assert.deepEqual(requests.filter((u) => u.endsWith('.json')), []);
  // The axis stays in view while scrolling down the long board.
  const stuck = await page.evaluate(() => {
    const rows = document.querySelectorAll('#leaderboard-chart .lb-row');
    rows[rows.length - 1].scrollIntoView({ block: 'center' });
    return document.querySelector('#leaderboard-chart .lb-axis')!.getBoundingClientRect().top;
  });
  assert.ok(Math.abs(stuck) < 1, `axis top ${stuck}`);
  await page.select('#leaderboard-size', '25');
  await page.select('#leaderboard-org', '*');
  assert.doesNotMatch(page.url(), /lbn|lbo/);
  assert.deepEqual(errors, []);
  await page.close();
});

test('a link (or a reload) restores the page state from the URL, and the page writes it back unchanged', async () => {
  // Each control's own test checks what it writes to the URL; this reads every
  // setting back, as a reload or a shared link does.
  const reviewer = await (await defaultPage()).page.$eval('#leaderboard-chart .lb-row', (r) => (r as HTMLElement).dataset.account!);
  const hash = '#metric=chars&from=2025-W45&to=2026-W44&smooth=52&rscale=linear&lbn=100&lbo=*-google.com' +
    `&dir=${encodeURIComponent('chrome/')}&hm=microsoft.com&hmb=1&hmv=share&cxb=52&cxv=volume&lbr=${reviewer}`;
  const { page, errors } = await open(hash);
  const got = await page.evaluate(() => {
    const value = (sel: string) => document.querySelector<HTMLInputElement | HTMLSelectElement>(sel)!.value;
    return {
      controls: ['#metric input:checked', '#smoothing input:checked', '#review-scale input:checked', '#review-dir',
        '#leaderboard-size', '#leaderboard-org', '#heat-org', '#heat-bin input:checked', '#heat-value input:checked',
        '#cx-bin input:checked', '#cx-value input:checked'].map(value),
      yType: window.__cosh!.reviewChart!.options.scales.y.type,
      detail: !document.querySelector<HTMLElement>('#reviewer-detail')!.hidden,
      hash: location.hash,
    };
  });
  assert.deepEqual(got.controls,
    ['chars', '52', 'linear', 'chrome/', '100', '*-google.com', 'microsoft.com', '1', 'share', '52', 'volume']);
  assert.equal(got.yType, 'linear');
  assert.ok(got.detail, 'the reviewer chart is open');
  // Written back in the page's own order: the same settings.
  const params = (h: string) => [...new URLSearchParams(h.slice(1))].sort();
  assert.deepEqual(params(got.hash), params(hash));
  assert.deepEqual(errors, []);
  await page.close();
});

test('usage chart shows ChromeDerivative', async () => {
  const { page } = await defaultPage();
  const names = await page.evaluate(() =>
    window.__cosh!.usageChart!.data.datasets.map((d: { label?: string }) => d.label),
  );
  assert.ok(names.includes('ChromeDerivative'), names.join());
  assert.ok(names.includes('Chrome'));
});

test('Meta gets a ratio line; the usage chart shows WebView', async () => {
  const { page } = await defaultPage();
  const ratioOrgs = await page.evaluate(() =>
    window.__cosh!.ratioChart!.data.datasets.map((d: { label?: string }) => d.label),
  );
  assert.ok(ratioOrgs.includes('meta.com'), ratioOrgs.join());
  const usage = await page.evaluate(() =>
    window.__cosh!.usageChart!.data.datasets.map((d: { label?: string }) => d.label),
  );
  assert.ok(usage.includes('ChromeMobileWebview'), usage.join());
});

test.skipIf(!process.env.SCREENSHOT_DIR)('screenshots (only when SCREENSHOT_DIR is set)', async () => {
  for (const scheme of ['light', 'dark'] as const) {
    const page = await browser.newPage();
    await page.emulateMediaFeatures([{ name: 'prefers-color-scheme', value: scheme }]);
    await page.setViewport({ width: 1100, height: 900 });
    await page.goto(valueUrl);
    await page.waitForSelector('body[data-area-links]');
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
    // Without google.com: more orgs than palette colours, so some are named on their rows.
    await page.setViewport({ width: 1100, height: 3200 });
    await page.select('#leaderboard-size', '100');
    await page.select('#leaderboard-org', '*-google.com');
    await page.mouse.move(0, 0);
    const card = await page.$('#leaderboard');
    await card!.screenshot({ path: join(process.env.SCREENSHOT_DIR!, `leaderboard-nogoogle-${scheme}.png`) as `${string}.png` });
    await page.close();
  }
});

test('time axes are labelled by month; tooltips still name the week', async () => {
  const { page, errors } = await defaultPage();
  const read = () =>
    page.evaluate(() =>
      (['ratioChart', 'reviewChart', 'usageChart'] as const).map((k) => {
        const c = window.__cosh![k]!;
        const title = c.options.plugins.tooltip.callbacks.title as (items: { label: string }[]) => string;
        const weeks = c.data.labels as string[];
        return {
          k,
          n: weeks.length,
          ticks: c.scales.x.ticks.map((t) => String(t.label)),
          title: title([{ label: weeks[weeks.length - 1] }]),
        };
      }),
    );
  for (const c of await read()) {
    // A range of a few weeks can sit inside one month.
    assert.ok(c.ticks.length >= (c.n > 6 ? 2 : 1), `${c.k}: ${c.ticks}`);
    for (const t of c.ticks) assert.match(t, /^[A-Z][a-z]{2}( \d{4})?$/, `${c.k} tick ${t}`);
    assert.match(c.ticks[0], / \d{4}$/, `${c.k}: first tick names the year`);
    assert.match(c.title, /^[A-Z][a-z]{2} \d+ – [A-Z][a-z]{2} \d+, \d{4}$/);
  }
  assert.deepEqual(errors, []);
  // Phone width: fewer, still month-aligned ticks.
  // The usage chart over a year, so this holds however few review weeks there are.
  const narrow = await open(`#from=${addWeeks(isoWeekOf(new Date()), -60)}&to=${addWeeks(isoWeekOf(new Date()), -8)}`, 390);
  const phone = await narrow.page.evaluate(() => window.__cosh!.usageChart!.scales.x.ticks.length);
  assert.ok(phone >= 2 && phone <= 6, `phone ticks: ${phone}`);
  await narrow.page.close();
});

test('chart tooltips sit beside the hovered week, not over its points', async () => {
  // Shows each tooltip and hides it again, leaving the shared page as it was.
  const { page, errors } = await defaultPage();
  const cards = await page.evaluate(() =>
    (['ratioChart', 'reviewChart', 'usageChart'] as const).flatMap((k) => {
      const c = window.__cosh![k]!;
      const n = (c.data.labels as string[]).length;
      return [Math.floor(n / 4), n - 2].filter((i) => i >= 0).map((index) => {
        const active = c.data.datasets
          .map((d, datasetIndex) => ({ datasetIndex, index, v: d.data[index] }))
          .filter((a) => a.v != null && (a.v as { y?: unknown }).y !== null)
          .map(({ datasetIndex, index }) => ({ datasetIndex, index }));
        const x = c.scales.x.getPixelForValue(index);
        c.tooltip!.setActiveElements(active, { x, y: c.chartArea.top });
        c.update();
        const t = c.tooltip!;
        const out = { k, index, yAlign: t.yAlign, xAlign: t.xAlign, left: t.x, right: t.x + t.width, x };
        c.tooltip!.setActiveElements([], { x: 0, y: 0 });
        c.update();
        return out;
      });
    }),
  );
  for (const t of cards) {
    assert.equal(t.yAlign, 'center', `${t.k}@${t.index}`);
    // Beside the week unless the card is too wide to fit on either side.
    if (t.xAlign !== 'center') assert.ok(t.left > t.x || t.right < t.x, `${t.k}@${t.index}: ${JSON.stringify(t)}`);
  }
  assert.ok(cards.some((t) => t.k === 'usageChart' && t.xAlign !== 'center'), JSON.stringify(cards));
  assert.deepEqual(errors, []);
});

test('heatmap: column ticks carry the year wherever it changes, wide or narrow', async () => {
  const ticks = (page: Page) =>
    page.$$eval('#heat-table thead .hm-tick', (ts) =>
      ts.filter((t) => getComputedStyle(t).display !== 'none').map((t) => (t as HTMLElement).innerText.trim()));
  // 4-week columns over a year: the year is on January, not the first tick (the subtitle has it).
  const { page, errors } = await open('#metric=comments&from=2025-W45&to=2026-W44');
  const wide = await ticks(page);
  assert.ok(wide.includes('Jan 2026'), wide.join());
  assert.ok(!/\d/.test(wide[0]), wide.join());
  // 3-month columns that start mid-quarter: no tick is in January, yet each new year is named.
  await page.click('#heat-bin input[value="13"]');
  const quarters = await ticks(page);
  assert.ok(quarters.every((t) => !t.startsWith('Jan')), quarters.join());
  assert.ok(quarters.some((t) => / 2026$/.test(t)), quarters.join());
  // On a phone only coarse ticks show, and they carry the year where it changes between them.
  assert.deepEqual(errors, []);
  await page.close();
  const phone = await open('#metric=comments&from=2025-W45&to=2026-W44', 400);
  const narrow = await ticks(phone.page);
  assert.ok(narrow.length <= 4, narrow.join());
  assert.equal(narrow[0], 'Jan 2026', narrow.join());
  assert.deepEqual(phone.errors, []);
  await phone.page.close();
});

test('parity chart hover cards sit below or above the point: org and ratio over a fraction', async () => {
  const { page, errors } = await open();
  const cards = await page.evaluate(() => {
    const c = window.__cosh!.parityChart!;
    return c.data.datasets.map((ds, datasetIndex) => {
      const pt = c.getDatasetMeta(datasetIndex).data[0];
      c.tooltip!.setActiveElements([{ datasetIndex, index: 0 }], { x: pt.x, y: pt.y });
      c.update();
      const t = c.tooltip!;
      const out = {
        org: ds.label!,
        yAlign: t.yAlign,
        top: t.y,
        bottom: t.y + t.height,
        canvas: c.height,
        pointY: pt.y,
        title: t.title,
        lines: t.body.map((b) => b.lines),
      };
      c.tooltip!.setActiveElements([], { x: 0, y: 0 });
      c.update();
      return out;
    });
  });
  assert.ok(cards.length > 3, JSON.stringify(cards));
  for (const t of cards) {
    const at = `${t.org}: ${JSON.stringify(t)}`;
    assert.ok(t.yAlign === 'top' || t.yAlign === 'bottom', at);
    // Clear of the point (radius 9 when hovered), and inside the canvas.
    if (t.yAlign === 'top') assert.ok(t.top >= t.pointY + 9, at);
    else assert.ok(t.bottom <= t.pointY - 9, at);
    assert.ok(t.top >= 0 && t.bottom <= t.canvas, at);
    // Three lines: "org  ratio×", then review share over usage share.
    assert.equal(t.title.length, 1, at);
    assert.match(t.title[0], new RegExp(`^${t.org.replace(/\./g, '\\.')}  [\\d.]+×$`), at);
    assert.equal(t.lines.length, 1, at);
    assert.equal(t.lines[0].length, 2, at);
    assert.match(t.lines[0][0], /^[\d.]+% of addressed comments$/, at);
    assert.match(t.lines[0][1], /^[\d.]+% of usage$/, at);
  }
  // Points high on the chart get the card below them.
  assert.ok(cards.some((t) => t.yAlign === 'top'), JSON.stringify(cards));
  assert.deepEqual(errors, []);
});

test('heatmap: directories by time bins, per org or as a mix, with Gerrit links', async () => {
  const { page, errors } = await open('#metric=comments&from=2025-W45&to=2026-W44');
  const read = () =>
    page.evaluate(() => ({
      bins: document.querySelectorAll('#heat-table thead th.hm-bin').length,
      rows: [...document.querySelectorAll<HTMLElement>('#heat-table tbody tr')].map((r) => ({
        key: r.dataset.key!,
        name: r.querySelector('.hm-name')!.textContent!,
        cells: [...r.querySelectorAll<HTMLElement>('.hm-box')].map((b) => ({
          link: b instanceof HTMLAnchorElement ? b.href : null,
          title: b.title,
          shaded: b.classList.contains('hm-shade'),
          segs: b.querySelectorAll('.hm-seg').length,
        })),
      })),
      org: (document.querySelector('#heat-org') as HTMLSelectElement).value,
      options: [...document.querySelectorAll<HTMLOptionElement>('#heat-org option')].map((o) => o.value),
      legend: document.querySelector('#heat-legend')!.textContent!,
      sub: document.querySelector('#heat-sub')!.textContent!,
    }));
  // Default: every org as a mix, 4-week columns over the 52 weeks.
  const mix = await read();
  assert.equal(mix.bins, 13);
  assert.equal(mix.org, '*');
  for (const o of ['google.com', 'microsoft.com', '*-google.com']) assert.ok(mix.options.includes(o), o);
  assert.ok(mix.rows.length >= 10 && mix.rows.every((r) => r.cells.length === 13));
  assert.ok(mix.rows[0].cells.some((c) => c.segs > 0), 'mix cells are stacked columns');
  assert.match(mix.legend, /google\.com/);

  // The links and "most active" lines arrive with the reviewer data.
  // Scroll the whole card in, so its toggles sit below the sticky metric bar.
  await page.$eval('#heatmap', (e) => e.scrollIntoView());
  await page.waitForSelector('#heat-chart a.hm-box');

  // One org: shaded cells, ranked by that org's review.
  await page.select('#heat-org', 'microsoft.com');
  assert.match(page.url(), /hm=microsoft\.com/);
  const ms = await read();
  assert.equal(ms.org, 'microsoft.com');
  assert.equal(ms.sub, mix.sub, 'the organization choice leaves the description alone');
  assert.match(ms.legend, /review comments$/);
  const blink = ms.rows.find((r) => r.name === 'third_party/blink/')!;
  assert.ok(blink, 'third_party/blink/ row');
  const cell = blink.cells.find((c) => c.link)!;
  assert.ok(cell.shaded);
  assert.match(cell.title, /^third_party\/blink\/, \d+ [A-Z][a-z]{2}( \d{4})? – \d+ [A-Z][a-z]{2} \d{4}\n/);
  assert.match(cell.title, /\nmicrosoft\.com: [\d,]+ review comments \([\d.]+% of [\d,]+ there\)/);
  assert.match(cell.title, /\nMost active: [^@\s]+@[^@\s]+ \(\d+\)/);
  assert.match(cell.link!, /^https:\/\/chromium-review\.googlesource\.com\/q\/dir:third_party\/blink\+after:\d{4}-\d\d-\d\d\+/);

  // Share, and weekly columns.
  await page.click('#heat-value input[value="share"]');
  await page.click('#heat-bin input[value="1"]');
  const weekly = await read();
  assert.match(page.url(), /hmb=1/);
  assert.match(page.url(), /hmv=share/);
  assert.equal(weekly.bins, 52);
  assert.match(weekly.legend, /^0%.*100% of the directory/);
  assert.equal(weekly.sub, mix.sub, 'the column and value toggles leave the description alone');

  // Longer columns are named in months or years: 13 weeks is "3 months", 52 weeks "1 year".
  assert.deepEqual(
    await page.$$eval('#heat-bin label', (ls) => ls.map((l) => l.textContent!.trim())),
    ['Weeks', '4 weeks', '3 months', '1 year'],
  );
  await page.click('#heat-bin input[value="13"]');
  assert.equal((await read()).bins, 4);
  await page.click('#heat-bin input[value="52"]');
  assert.equal((await read()).bins, 1);
  assert.match(page.url(), /hmb=52/);
  await page.click('#heat-bin input[value="1"]');

  // Expanding a row opens its subdirectories; "chart" shows one in the organization chart.
  await page.click(`#heat-table tr[data-key="${blink.key}"] .ar-toggle`);
  const renderer = (await read()).rows.find((r) => r.name === 'renderer/')!;
  assert.ok(renderer, 'third_party/blink/renderer/ row');
  await page.click(`#heat-table tr[data-key="${renderer.key}"] .hm-chart`);
  assert.match(page.url(), /dir=third_party%2Fblink%2Frenderer%2F/);
  assert.equal(await page.$eval('#review-dir', (e) => (e as HTMLInputElement).value), 'third_party/blink/renderer/');
  assert.match(await page.$eval('#review-dir-note', (e) => e.textContent!), /^Showing third_party\/blink\/renderer\/\./);

  // All but google.com: google.com's comments are in no cell.
  await page.select('#heat-org', '*-google.com');
  const nog = await read();
  // (Org lines only: a reviewer's email may still be at google.com.)
  assert.ok(nog.rows.flatMap((r) => r.cells).every((c) => !/(^|\n)google\.com:/.test(c.title)), 'no google.com in any cell');
  assert.doesNotMatch(nog.legend, /google\.com/);

  // Other: after the named orgs, the rest as one segment.
  const at = nog.options.indexOf('*other');
  const named = nog.options.slice(2, at);
  assert.deepEqual([...named].sort(), (await namedOn(page)).sort(), nog.options.join());
  await page.select('#heat-org', '*other');
  const rest = await read();
  assert.equal(rest.legend, 'Other');
  const titles = rest.rows.flatMap((r) => r.cells).map((c) => c.title);
  assert.ok(titles.some((t) => /\n\s*Other: [\d,]+ \(100(\.0)?%\)/.test(t)), 'cells count the rest');
  for (const o of named) assert.ok(titles.every((t) => !t.includes(` ${o}:`)), o);
  assert.deepEqual(errors, []);
  await page.close();
});

test('organization chart can show one directory, kept in the URL', async () => {
  const { page, errors } = await open('#from=2025-W45&to=2026-W44&rscale=linear');
  const series = () =>
    page.evaluate(() => window.__cosh!.reviewChart!.data.datasets.map((d) => ({
      org: d.label!,
      total: (d.data as (number | null)[]).reduce<number>((s, v) => s + (v ?? 0), 0),
    })));
  const before = await series();
  assert.equal(await page.$eval('#review-dir-clear', (e) => (e as HTMLButtonElement).hidden), true);
  // Suggestions are directories the chart can show.
  const options = await page.$$eval('#dir-options option', (o) => o.map((x) => (x as HTMLOptionElement).value));
  assert.ok(options.length > 100 && options.includes('components/services/storage/'));

  // Typing a path without its slash works; the subtitle says what's counted.
  await page.type('#review-dir', 'components/services/storage');
  await page.keyboard.press('Enter');
  await page.waitForFunction(() => /dir=/.test(location.hash));
  assert.match(page.url(), /dir=components%2Fservices%2Fstorage%2F/);
  const storage = await series();
  assert.notDeepEqual(storage, before);
  assert.equal(storage[0].org, 'microsoft.com', 'Microsoft leads components/services/storage/ once google.com is left out');
  assert.match(await page.$eval('#review-dir-note', (e) => e.textContent!),
    /^Showing components\/services\/storage\/.*It counts every comment in this directory and below\./);
  assert.equal(await page.$eval('#review-dir-clear', (e) => (e as HTMLButtonElement).hidden), false);

  // A partly excluded directory says how much the rest of the page leaves out.
  await page.click('#review-dir', { count: 3 });
  await page.type('#review-dir', 'chrome/');
  await page.keyboard.press('Enter');
  await page.waitForFunction(() => /dir=chrome%2F(&|$)/.test(location.hash));
  assert.match(await page.$eval('#review-dir-note', (e) => e.textContent!),
    /including the [\d.]+% on paths the rest of the page leaves out/);

  // An unknown directory leaves the chart alone and says why.
  await page.click('#review-dir', { count: 3 });
  await page.type('#review-dir', 'no/such/dir');
  await page.keyboard.press('Enter');
  assert.match(await page.$eval('#review-dir-status', (e) => e.textContent!), /No directory “no\/such\/dir”/);
  assert.match(page.url(), /dir=chrome%2F/);

  // Clear goes back to the path scope.
  await page.click('#review-dir-clear');
  assert.doesNotMatch(page.url(), /dir=/);
  assert.deepEqual(await series(), before);
  assert.equal(await page.$eval('#review-dir-status', (e) => e.textContent!), '');
  assert.equal(await page.$eval('#review-dir-note', (e) => (e as HTMLElement).hidden), true);
  assert.deepEqual(errors, []);
  await page.close();
});

test('the landing page links to the Value Exchange dashboard', async () => {
  const page = await browser.newPage();
  const errors: string[] = [];
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.setViewport({ width: 1100, height: 900 });
  await page.goto(baseUrl, { waitUntil: 'load' });
  assert.equal(await page.title(), 'Chromium Open Source');
  const cards = await page.$$eval('.cards a', (as) =>
    as.map((a) => ({ href: a.getAttribute('href'), title: a.querySelector('h3')!.textContent })));
  assert.deepEqual(cards, [
    { href: 'value.html', title: 'Value Exchange' },
    { href: 'sentiment.html', title: 'Review Tone' },
  ]);
  // Styled by its own sheet.
  assert.match(await page.$eval('body', (b) => getComputedStyle(b).fontFamily), /system-ui/);
  await Promise.all([page.waitForNavigation(), page.click('.cards a')]);
  assert.equal(await page.title(), 'Chromium Open Source - Value Exchange');
  await page.waitForSelector('body[data-ready]');
  // …and the dashboard links back.
  assert.equal(await page.$eval('.crumb a', (a) => a.getAttribute('href')), './');
  assert.deepEqual(errors, []);
  await page.close();
});

test('the landing page fits a phone in dark mode', async () => {
  const page = await browser.newPage();
  await page.emulateMediaFeatures([{ name: 'prefers-color-scheme', value: 'dark' }]);
  await page.setViewport({ width: 360, height: 800 });
  await page.goto(baseUrl, { waitUntil: 'load' });
  assert.equal(await page.$eval('body', (b) => getComputedStyle(b).backgroundColor), 'rgb(13, 13, 13)');
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  assert.ok(overflow <= 0, `horizontal overflow ${overflow}px`);
  if (process.env.SCREENSHOT_DIR) {
    await page.screenshot({ path: join(process.env.SCREENSHOT_DIR, 'home-phone-dark.png') as `${string}.png`, fullPage: true });
    await page.emulateMediaFeatures([{ name: 'prefers-color-scheme', value: 'light' }]);
    await page.setViewport({ width: 1100, height: 800 });
    await page.screenshot({ path: join(process.env.SCREENSHOT_DIR, 'home-light.png') as `${string}.png`, fullPage: true });
  }
  await page.close();
});

test('the Review Tone page: trend, praise leaderboard and samples; names only for praise', async () => {
  const page = await browser.newPage();
  const errors: string[] = [];
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.setViewport({ width: 1100, height: 900 });
  await page.goto(baseUrl + 'sentiment.html', { waitUntil: 'load' });
  await page.waitForSelector('body[data-ready]');
  assert.equal(await page.title(), 'Chromium Open Source - Review Tone');
  assert.equal(await page.$eval('#error', (e) => (e as HTMLElement).hidden), true);
  assert.equal(await page.$eval('.crumb a', (a) => a.getAttribute('href')), './');
  // Both charts drew.
  for (const id of ['#trend-mean', '#trend-shares']) {
    const w = await page.$eval(id, (c) => (c as HTMLCanvasElement).width);
    assert.ok(w > 0, id);
  }
  assert.match(await page.$eval('#trend-sub', (e) => e.textContent!), /random sample/);
  // Leaderboards, highest first.
  for (const id of ['#praise-given', '#praise-received']) {
    const counts = await page.$$eval(`${id} tbody tr td:last-child`, (tds) =>
      tds.map((t) => Number(t.textContent!.replace(/,/g, ''))));
    assert.ok(counts.length > 0, id);
    assert.deepEqual(counts, [...counts].sort((a, b) => b - a), id);
  }
  // Praise samples link to Gerrit and name writer and recipient…
  const praise = await page.$$eval('#praise-samples li', (lis) =>
    lis.map((li) => ({ by: li.querySelector('.quote-by')!.textContent!, href: li.querySelector('a')?.getAttribute('href') })));
  assert.ok(praise.length > 0);
  for (const p of praise) {
    assert.match(p.href ?? '', /^https:\/\/chromium-review\.googlesource\.com\/c\//);
    assert.match(p.by, / to .+, \d{1,2} \w{3,4} \d{4}/);
  }
  // …grumpy ones have no link, no name and only a month.
  const grumpy = await page.$$eval('#grumpy-samples li', (lis) =>
    lis.map((li) => ({ links: li.querySelectorAll('a').length, by: li.querySelector('.quote-by')!.textContent!.trim() })));
  assert.ok(grumpy.length > 0);
  for (const g of grumpy) {
    assert.equal(g.links, 0);
    assert.match(g.by, /^[A-Z][a-z]{2,3} \d{4}$/);
  }
  const text = await page.$eval('body', (b) => (b as HTMLElement).innerText);
  assert.doesNotMatch(text, /\b\d{4}-W\d{2}\b/);
  assert.doesNotMatch(text, /ISO week/i);
  assert.deepEqual(errors, []);
  await page.close();
});

test('the Review Tone page: last two months, board controls, happy tables, AI list and prompt', async () => {
  const page = await browser.newPage();
  const errors: string[] = [];
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.setViewport({ width: 1100, height: 900 });
  await page.goto(baseUrl + 'sentiment.html', { waitUntil: 'load' });
  await page.waitForSelector('body[data-ready]');
  // Tiles and the weekly table are filled; weeks are named by their dates.
  for (const id of ['tile-n', 'tile-trivial', 'tile-mean', 'tile-glowing', 'tile-angry', 'tile-ai']) {
    assert.notEqual(await page.$eval(`#${id} .tile-value`, (e) => e.textContent!.trim()), '', id);
  }
  const weeks = await page.$$eval('#recent-weekly tbody th', (ths) => ths.map((t) => t.textContent!));
  assert.ok(weeks.length >= 4);
  for (const w of weeks) assert.match(w, /^\d{1,2} \w{3,4} \d{4}$/);
  assert.ok((await page.$eval('#recent-dist', (c) => (c as HTMLCanvasElement).width)) > 0);

  // The praise boards: Top 100 shows more rows (up to 100); the past month changes the caption.
  const rows = (id: string) => page.$$eval(`${id} tbody tr`, (trs) => trs.length);
  const given15 = await rows('#praise-given');
  assert.ok(given15 > 0 && given15 <= 15);
  await page.click('#praise-size input[value="100"]');
  const given100 = await rows('#praise-given');
  assert.ok(given100 >= given15 && given100 <= 100);
  const allSub = await page.$eval('#praise-sub', (e) => e.textContent!);
  await page.click('#praise-period input[value="month"]');
  assert.notEqual(await page.$eval('#praise-sub', (e) => e.textContent!), allSub);
  assert.ok((await rows('#praise-given')) > 0);

  // Happy tables: names with "N of M" counts, expandable too.
  const happy = await page.$$eval('#happy-authors tbody tr td:last-child', (tds) => tds.map((t) => t.textContent!));
  assert.ok(happy.length > 0 && happy.length <= 15);
  for (const h of happy) assert.match(h, /^\d+ of \d+$/);
  await page.click('#happy-size input[value="100"]');
  assert.ok((await rows('#happy-authors')) >= happy.length);
  await page.click('#happy-period input[value="month"]');
  assert.ok((await rows('#happy-reviewers')) > 0);

  // The AI-friction list: anonymous (no links), month and role only; "Show all" expands it.
  const first = await page.$$eval('#ai-list li', (lis) =>
    lis.map((li) => ({ links: li.querySelectorAll('a').length, by: li.querySelector('.quote-by')!.textContent!.trim() })));
  assert.ok(first.length > 0 && first.length <= 20);
  for (const c of first) {
    assert.equal(c.links, 0);
    assert.match(c.by, /^[A-Z][a-z]{2,3} \d{4}, (change author|reviewer)$/);
  }
  if (!(await page.$eval('#ai-more', (b) => (b as HTMLElement).hidden))) {
    await page.click('#ai-more');
    assert.ok((await page.$$eval('#ai-list li', (lis) => lis.length)) > first.length);
  }

  // The prompt, as text.
  assert.match(await page.$eval('#prompt-text', (e) => e.textContent!), /Rate the emotional tone/);
  const text = await page.$eval('body', (b) => (b as HTMLElement).innerText);
  assert.doesNotMatch(text, /\b\d{4}-W\d{2}\b/);
  assert.deepEqual(errors, []);
  await page.close();
});

test('the Review Tone page fits a phone in dark mode', async () => {
  const page = await browser.newPage();
  await page.emulateMediaFeatures([{ name: 'prefers-color-scheme', value: 'dark' }]);
  await page.setViewport({ width: 360, height: 800 });
  await page.goto(baseUrl + 'sentiment.html', { waitUntil: 'load' });
  await page.waitForSelector('body[data-ready]');
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  assert.ok(overflow <= 0, `horizontal overflow ${overflow}px`);
  if (process.env.SCREENSHOT_DIR) {
    await page.screenshot({ path: join(process.env.SCREENSHOT_DIR, 'tone-phone-dark.png') as `${string}.png`, fullPage: true });
    await page.emulateMediaFeatures([{ name: 'prefers-color-scheme', value: 'light' }]);
    await page.setViewport({ width: 1100, height: 800 });
    await page.screenshot({ path: join(process.env.SCREENSHOT_DIR, 'tone-light.png') as `${string}.png`, fullPage: true });
  }
  await page.close();
});
