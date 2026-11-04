// The reviewer leaderboard as HTML: one link per reviewer over a gridline
// layer. A CSS grid gives the axis labels, the gridlines and the bars the same
// plot column (the rows use subgrid), so bar ends and gridlines line up at any
// width without measuring anything. Real links and text mean middle-click,
// copy-link and find-in-page all work, and screen readers get an ordered list.
import { gerritReviewsUrl, niceTicks, type LeaderboardRow, type WeekRange } from './data.ts';

function node<K extends keyof HTMLElementTagNameMap>(tag: K, cls?: string, text?: string) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

const pct = (v: number, max: number) => `${(v / max) * 100}%`;

/** Fills `box` with the leaderboard. Bars take the org's colour (`colorOf`);
 * orgs without one get the muted neutral. Each row links to the CLs the
 * reviewer commented on, limited to `range` when given. */
export function buildLeaderboard(
  box: HTMLElement,
  rows: LeaderboardRow[],
  metricLabel: string,
  colorOf: (org: string) => string | undefined,
  range?: WeekRange,
): void {
  const fmt = (v: number) => v.toLocaleString('en-US');
  if (!rows.length) {
    box.replaceChildren();
    return;
  }
  const ticks = niceTicks(rows[0].value);
  const max = ticks[ticks.length - 1];
  // On narrow screens CSS hides every other tick label ("minor"); the
  // gridlines all stay.
  const minor = (i: number) => i % 2 === 1 && ticks.length > 4;

  const axis = node('div', 'lb-axis');
  axis.setAttribute('aria-hidden', 'true');
  const grid = node('div', 'lb-grid');
  grid.setAttribute('aria-hidden', 'true');
  ticks.forEach((t, i) => {
    const label = node('span', minor(i) ? 'lb-tick lb-minor' : 'lb-tick', fmt(t));
    label.style.left = pct(t, max);
    axis.append(label);
    const line = node('span', i === 0 ? 'lb-line lb-zero' : 'lb-line');
    line.style.left = pct(t, max);
    grid.append(line);
  });

  const unit = metricLabel.toLowerCase();
  const list = node('ol', 'lb-rows');
  list.append(
    ...rows.map((r, i) => {
      const li = node('li');
      const url = gerritReviewsUrl(r.email, range);
      const row = node(url ? 'a' : 'span', 'lb-row');
      if (url) {
        row.setAttribute('href', url);
        row.setAttribute('target', '_blank');
        row.setAttribute('rel', 'noopener');
      }
      row.title = `${i + 1}. ${r.name} (${r.org})\n${fmt(r.value)} ${unit}` +
        (r.email ? `\n${r.email}\nOpens the CLs they commented on in the range on Gerrit, in a new tab` : '');
      const label = node('span', 'lb-label');
      label.append(
        node('span', 'lb-rank', `${i + 1}. `),
        node('span', 'lb-name', r.name),
      );
      const plot = node('span', 'lb-plot');
      const bar = node('span', 'lb-bar');
      bar.style.width = pct(r.value, max);
      const color = colorOf(r.org);
      if (color) bar.style.background = color;
      plot.append(bar, node('span', 'lb-value', fmt(r.value)));
      row.append(label, plot);
      li.append(row);
      return li;
    }),
  );
  box.replaceChildren(axis, grid, list);
}
