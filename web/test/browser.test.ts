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
import puppeteer, { type Browser, type Page } from 'puppeteer-core';
import { preview, type PreviewServer } from 'vite';
import { randomPort } from '../vite.config.ts';
import { addWeeks, addressedWeeks, isoWeekOf, type Summary } from '../src/data.ts';

/** The committed summary the build bundles. */
const summary = JSON.parse(
  readFileSync(fileURLToPath(new URL('../../summaries/org_weekly.json', import.meta.url)), 'utf8'),
) as Summary;
const hasAddressedWeeks = () => addressedWeeks(summary).length > 0;

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
  if (process.env.CPU_THROTTLE) await page.emulateCPUThrottling(Number(process.env.CPU_THROTTLE));
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
  // Charts come in order: ratio, review, usage, the table, directories, directories over time, the per-reviewer
  // distribution, then the leaderboard.
  const order = await page.$$eval('main > section', (s) => s.map((e) => e.querySelector('canvas, table, .lb, .ar')?.id));
  assert.deepEqual(order.filter(Boolean),
    ['ratio-chart', 'review-chart', 'usage-chart', 'org-table', 'area-chart', 'heat-table', 'dist-chart', 'leaderboard-chart']);
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

test('directory rows drill down, and "more" rows open 20 at a time and close again', async () => {
  const { page, errors } = await open();
  // Pressing a toggle scrolls the chart into view, which starts loading its
  // Gerrit links; their arrival rebuilds the rows. Load them first, so a
  // rebuild can't replace a toggle between finding it and clicking it.
  await page.$eval('#area-chart', (e) => e.scrollIntoView());
  await page.waitForSelector('body[data-area-links]');
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
  const { page, errors } = await open();
  assert.equal(await page.$('body[data-area-links]'), null);
  // Pressing the toggle scrolls the chart into view, which starts the load.
  const key = await page.evaluate(() =>
    [...document.querySelectorAll<HTMLElement>('#area-chart .ar-row')]
      .find((r) => r.querySelector('.ar-name')?.textContent === 'third_party/blink/')!.dataset.key!);
  await page.click(`li[data-key="${key}"] .ar-toggle`);
  await page.waitForSelector('body[data-area-links]');
  assert.ok(await page.$('#area-chart a.ar-seg'), 'rows were rebuilt with links');
  assert.equal(await page.evaluate(() => (document.activeElement as HTMLElement).closest('li')?.dataset.key), key);
  assert.deepEqual(errors, []);
  await page.close();
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
  const before = await cell();
  assert.equal(await areaHead(), 'Review comments');
  for (const [id, axis, head] of [['cls', /^reviewed cls per week/, 'Reviewed CLs'],
    ['chars', /^review characters per week/, 'Review characters']] as const) {
    await page.click(`#metric input[value="${id}"]`);
    assert.notEqual(await cell(), before);
    assert.match(page.url(), new RegExp(`metric=${id}`));
    const label = await page.evaluate(() => window.__cosh!.reviewChart!.options.scales.y.title.text);
    assert.match(label, axis);
    assert.equal(await areaHead(), head);
  }
  // State survives a reload via the URL hash.
  await page.reload();
  await page.waitForSelector('body[data-ready]');
  assert.equal(await page.$eval('#metric input[value="chars"]', (i) => (i as HTMLInputElement).checked), true);
  assert.deepEqual(errors, []);
  await page.close();
});

test.skipIf(!hasAddressedWeeks())('addressed comments show only classified weeks, with a note', async () => {
  const classified = addressedWeeks(summary);
  const last = classified[classified.length - 1];
  const from = addWeeks(classified[0], -8);
  const { page, errors } = await open(`#metric=addressed&from=${from}&to=${last}`);
  assert.equal(await page.$eval('#metric input[value="addressed"]', (i) => (i as HTMLInputElement).checked), true);
  const note = await page.$eval('#metric-note', (n) => ({ hidden: (n as HTMLElement).hidden, text: n.textContent ?? '' }));
  assert.equal(note.hidden, false);
  assert.match(note.text, /led the CL owner to change the CL/);
  assert.match(note.text, /Only \d+ of the \d+ review weeks in this range (is|are) classified/);
  // The user's range stays in the URL; the sections show the classified part.
  assert.match(page.url(), new RegExp(`from=${from}`));
  assert.match(await page.$eval('#table-caption', (c) => c.textContent ?? ''), new RegExp(classified[0]));
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
  // 4-week averages start from that week alone instead of averaging in zeros.
  const firstWeek = () =>
    page.evaluate(() => {
      const c = window.__cosh!;
      const ratio = c.ratioChart!.data.datasets.find((d: { label?: string }) => d.label === 'google.com')!;
      const review = c.reviewChart!.data.datasets.find((d: { label?: string }) => d.label === 'google.com')!;
      return {
        ratio: (ratio.data as unknown as { ratio: number | null }[])[0].ratio,
        review: (review as unknown as { counts: number[] }).counts[0],
      };
    });
  assert.equal(await page.evaluate(() => window.__cosh!.state.smoothing), 4);
  const smoothed = await firstWeek();
  await page.click('#smoothing input[value="1"]');
  const raw = await firstWeek();
  assert.ok(smoothed.ratio !== null && Math.abs(smoothed.ratio - raw.ratio!) < 1e-9, `${smoothed.ratio} vs ${raw.ratio}`);
  assert.ok(Math.abs(smoothed.review - raw.review) < 1e-9, `${smoothed.review} vs ${raw.review}`);
  await page.click('#smoothing input[value="4"]');
  // The intro links to the explainer: it opens it without losing the URL state.
  const intro = await page.$eval('header', (h) => h.textContent ?? '');
  assert.match(intro, /share of\s+addressed\s+review comments/);
  await page.click('#addressed-link');
  assert.equal(await page.$eval('#addressed-details', (d) => (d as HTMLDetailsElement).open), true);
  assert.match(page.url(), /metric=addressed/);
  await page.$eval('#addressed-details', (d) => { (d as HTMLDetailsElement).open = false; });
  // The classification explainer starts collapsed and gives the measured accuracy.
  const details = await page.$eval('#addressed-details', (d) => ({
    hidden: (d as HTMLElement).hidden, open: (d as HTMLDetailsElement).open, text: d.textContent ?? '' }));
  assert.equal(details.hidden, false);
  assert.equal(details.open, false);
  assert.match(details.text, /precision of 0\.98 .*recall of 0\.99/s);
  // Other metrics are unaffected and hide the note.
  await page.click('#metric input[value="comments"]');
  assert.equal(await page.$eval('#metric-note', (n) => (n as HTMLElement).hidden), true);
  assert.equal(await page.$eval('tr[data-org="google.com"] td:nth-child(8)', (td) => td.textContent), '—');
  assert.deepEqual(errors, []);
  await page.close();
});

test('review by directory shows volume and org split per directory, and the path rules', async () => {
  const { page, errors } = await open();
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
  assert.match(await page.$eval('#scope-note', (n) => n.textContent ?? ''), /Google's own products/);
  assert.match(await page.$eval('#unplaced-note', (n) => n.textContent ?? ''), /real investment/);
  assert.deepEqual(errors, []);
  await page.close();
});

test('each org segment of a directory links to its reviewers’ CLs there on Gerrit', async () => {
  const { page, errors } = await open();
  // The links' data loads only once the chart nears the viewport.
  assert.equal(await page.$$eval('#area-chart a.ar-seg', (a) => a.length), 0);
  await page.$eval('#area-chart', (e) => e.scrollIntoView());
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
        pointRadius: (ds as { pointRadius?: number | number[] }).pointRadius,
        curve: (ds as { cubicInterpolationMode?: string }).cubicInterpolationMode ?? 'default',
        sub: document.querySelector('#ratio-sub')!.textContent!,
        review: (c.reviewChart!.data.datasets.find((d: { label?: string }) => d.label === 'microsoft.com')! as
          unknown as { counts: number[] }).counts,
        reviewSub: document.querySelector('#review-sub')!.textContent!,
      };
    });
  const four = await read();
  assert.equal(four.smoothing, 4);
  assert.equal(four.checked, '4');
  assert.deepEqual(four.labels, ['Off', '4 weeks', '3 months']);
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

  await page.click('#smoothing input[value="13"]');
  assert.match(page.url(), /smooth=13/);
  await page.reload();
  await page.waitForSelector('body[data-ready]');
  assert.equal((await read()).smoothing, 13);
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
  assert.ok(d.ratioWeeks.every((w) => w >= d.range.from && w <= d.range.to));
  assert.deepEqual(d.reviewWeeks, d.ratioWeeks);
  assert.match(page.url(), new RegExp(`from=${d.range.from}&to=${d.range.to}`));

  // Pick an earlier start date: the usage chart widens to the week of that date.
  // Four weeks before the default start, so this holds however much review
  // data there is (Radar usage goes back to 2023-W26).
  const earlier = new Date(Date.parse(`${d.from}T00:00:00Z`) - 26 * 86_400_000); // a Wednesday
  const earlierWeek = isoWeekOf(earlier);
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
  assert.equal(wide.usageWeeks[0], earlierWeek);
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
  assert.equal(lin.sub, log.sub, 'the scale toggle leaves the description alone');
  assert.match(page.url(), /rscale=linear/);
  await page.reload();
  await page.waitForSelector('body[data-ready]');
  assert.equal((await read()).yType, 'linear');
  await page.click('#review-scale input[value="log"]');
  assert.doesNotMatch(page.url(), /rscale/);
  assert.deepEqual(errors, []);
  await page.close();
});

test('leaderboard shows up to 25 reviewers compactly', async () => {
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
  await page.click('#metric input[value="cls"]');
  const cls = await read();
  assert.match(cls.title, /\n[\d,]+ reviewed cls\n/i);
  assert.notDeepEqual(cls.values, comments.values);
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
  assert.match(detail.sub, /review comments in/);
  const chart = await page.evaluate(() => {
    const c = (window as unknown as { Chart?: unknown }).Chart;
    const canvas = document.querySelector<HTMLCanvasElement>('#reviewer-chart')!;
    return { c: !!c, w: canvas.getBoundingClientRect().width };
  });
  assert.ok(chart.w > 100);
  assert.match(page.url(), /lbr=\d+/);
  // The selection survives a reload.
  await page.reload();
  await page.waitForSelector('body[data-ready]');
  assert.equal(await page.$eval('#reviewer-detail', (d) => (d as HTMLElement).hidden), false);
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
    segs: [...document.querySelectorAll<HTMLElement>('#threads-bar .tb-seg')].map((s) => parseFloat(s.style.width)),
    legend: [...document.querySelectorAll('#threads-legend li')].map((l) => l.textContent ?? ''),
    sub: document.querySelector('#threads-sub')!.textContent ?? '',
  }));
  assert.equal(box.hidden, false);
  assert.ok(Math.abs(box.segs.reduce((a, b) => a + b, 0) - 100) < 0.01, `segments ${box.segs}`);
  assert.ok(box.legend.some((l) => /owner replied “Done”/.test(l)), box.legend.join(' | '));
  assert.match(box.sub, new RegExp(last));
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
  const { page: addr } = await open('#metric=addressed');
  if ((await addr.evaluate(() => window.__cosh!.state.metric)) === 'addressed') {
    const first = await addr.evaluate(() => String(window.__cosh!.distChart!.scales.x.ticks[0].label));
    assert.equal(first, '0');
    assert.match(await addr.$eval('#dist-sub', (e) => e.textContent!), /none addressed sit at 0/);
  }
  await addr.close();
  assert.deepEqual(errors, []);
  await page.close();
});

test('leaderboard size and Google toggles; every org is named, none as "other"', async () => {
  const { page, errors } = await open();
  const read = () =>
    page.evaluate(() => {
      const rows = [...document.querySelectorAll<HTMLElement>('#leaderboard-chart .lb-row')];
      return {
        n: rows.length,
        orgs: rows.map((r) => r.dataset.org!),
        inline: rows.map((r) => r.querySelector('.lb-org')?.textContent ?? null),
        colored: rows.map((r) => (r.querySelector<HTMLElement>('.lb-bar')!.style.background ? 1 : 0)),
        legend: document.querySelector('#leaderboard-legend')!.textContent!,
        sub: document.querySelector('#leaderboard-sub')!.textContent!,
      };
    });
  const check = (v: Awaited<ReturnType<typeof read>>) => {
    assert.doesNotMatch(v.legend, /other/i);
    // Every org on the board is in the legend; uncoloured rows name their org.
    for (const org of new Set(v.orgs)) assert.ok(v.legend.includes(org), `${org} in legend`);
    v.orgs.forEach((org, i) => assert.equal(v.inline[i], v.colored[i] ? null : ` · ${org}`));
  };
  const top25 = await read();
  check(top25);
  assert.ok(top25.orgs.includes('google.com'));
  await page.click('#leaderboard-size input[value="100"]');
  assert.match(page.url(), /lbn=100/);
  const top100 = await read();
  check(top100);
  assert.ok(top100.n > 50 && top100.n <= 100, `n=${top100.n}`);
  await page.click('#leaderboard-google input[value="false"]');
  assert.match(page.url(), /lbg=0/);
  const noGoogle = await read();
  check(noGoogle);
  assert.ok(!noGoogle.orgs.includes('google.com'));
  assert.ok(noGoogle.n > 50, `n=${noGoogle.n}`);
  assert.equal(noGoogle.sub, top25.sub, 'the toggles leave the description alone');
  assert.match(noGoogle.sub, /outside google\.com/);
  // The state survives a reload from the URL.
  const { page: again } = await open(new URL(page.url()).hash);
  assert.equal(await again.$eval('#leaderboard-google input[value="false"]', (e) => (e as HTMLInputElement).checked), true);
  assert.equal(await again.$eval('#leaderboard-size input[value="100"]', (e) => (e as HTMLInputElement).checked), true);
  await again.close();
  await page.click('#leaderboard-size input[value="25"]');
  await page.click('#leaderboard-google input[value="true"]');
  assert.doesNotMatch(page.url(), /lbn|lbg/);
  assert.deepEqual(errors, []);
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
  assert.match(await page.$eval('#review-metric-note', (n) => n.textContent ?? ''), /bare \+1\s+vote, don.t count/);
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
    // Without google.com: more orgs than palette colours, so some are named on their rows.
    await page.setViewport({ width: 1100, height: 3200 });
    await page.click('#leaderboard-size input[value="100"]');
    await page.click('#leaderboard-google input[value="false"]');
    await page.mouse.move(0, 0);
    const card = await page.$('#leaderboard');
    await card!.screenshot({ path: join(process.env.SCREENSHOT_DIR!, `leaderboard-nogoogle-${scheme}.png`) as `${string}.png` });
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
    assert.match(c.title, /^\d{4}-W\d{2} \([A-Z][a-z]{2} \d+ – [A-Z][a-z]{2} \d+\)$/);
  }
  assert.deepEqual(errors, []);
  await page.close();
  // Phone width: fewer, still month-aligned ticks.
  // The usage chart over a year, so this holds however few review weeks there are.
  const narrow = await open(`#from=${addWeeks(isoWeekOf(new Date()), -60)}&to=${addWeeks(isoWeekOf(new Date()), -8)}`, 390);
  const phone = await narrow.page.evaluate(() => window.__cosh!.usageChart!.scales.x.ticks.length);
  assert.ok(phone >= 2 && phone <= 6, `phone ticks: ${phone}`);
  await narrow.page.close();
});

test('heatmap: directories by time bins, per org or as a mix, with Gerrit links', async () => {
  const { page, errors } = await open('#from=2025-W45&to=2026-W44');
  const read = () =>
    page.evaluate(() => ({
      bins: document.querySelectorAll('#heat-table thead th.hm-bin').length,
      rows: [...document.querySelectorAll<HTMLElement>('#heat-table tbody tr')].map((r) => ({
        key: r.dataset.key!,
        name: r.querySelector('.hm-name')!.textContent!,
        cells: [...r.querySelectorAll<HTMLElement>('.hm-box')].map((b) => ({
          link: b instanceof HTMLAnchorElement ? b.href : null,
          title: b.title,
          shaded: !!b.style.background,
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
  await page.$eval('#heat-chart', (e) => e.scrollIntoView());
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
  assert.match(cell.title, /^third_party\/blink\/, \d{4}-W\d\d to \d{4}-W\d\d \(/);
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

  // From the URL: a partly excluded directory says how much the rest of the page leaves out.
  const reloaded = await open(`#from=2025-W45&to=2026-W44&dir=${encodeURIComponent('chrome/')}`);
  assert.equal(await reloaded.page.$eval('#review-dir', (e) => (e as HTMLInputElement).value), 'chrome/');
  assert.match(await reloaded.page.$eval('#review-dir-note', (e) => e.textContent!),
    /including the [\d.]+% on paths the rest of the page leaves out/);
  await reloaded.page.close();

  // An unknown directory leaves the chart alone and says why.
  await page.click('#review-dir', { count: 3 });
  await page.type('#review-dir', 'no/such/dir');
  await page.keyboard.press('Enter');
  assert.match(await page.$eval('#review-dir-status', (e) => e.textContent!), /No directory “no\/such\/dir”/);
  assert.match(page.url(), /dir=components%2Fservices%2Fstorage%2F/);

  // Clear goes back to the path scope.
  await page.click('#review-dir-clear');
  assert.doesNotMatch(page.url(), /dir=/);
  assert.deepEqual(await series(), before);
  assert.equal(await page.$eval('#review-dir-status', (e) => e.textContent!), '');
  assert.equal(await page.$eval('#review-dir-note', (e) => (e as HTMLElement).hidden), true);
  assert.deepEqual(errors, []);
  await page.close();
});
