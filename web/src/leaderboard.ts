// The reviewer leaderboard as HTML: one link per reviewer over a gridline
// layer. A CSS grid gives the axis labels, the gridlines and the bars the same
// plot column (the rows use subgrid), so bar ends and gridlines line up at any
// width without measuring anything. Real links and text mean middle-click,
// copy-link and find-in-page all work, and screen readers get an ordered list.
import { fmtInt } from './format.ts';
import { niceTicks, type LeaderboardRow } from './data.ts';

function node<K extends keyof HTMLElementTagNameMap>(tag: K, cls?: string, text?: string) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

/** `v` as a fraction of `max`, for the --at and --fill properties style.css places bars and ticks by. */
const frac = (v: number, max: number) => String(v / max);

/** Fills `box` with the leaderboard. Bars take the org's colour (`colorOf`);
 * orgs without one get the muted neutral and their name after the
 * reviewer's, so every row's org can be read off. Each row is a button that
 * selects the reviewer (`onSelect`): the page then shows their weekly chart,
 * with the link to their reviews on Gerrit. `selected` is pressed. */
export function buildLeaderboard(
  box: HTMLElement,
  rows: LeaderboardRow[],
  /** The metric mid-sentence, e.g. "review comments". */
  unit: string,
  colorOf: (org: string) => string | undefined,
  selected: number | null,
  onSelect: (id: number) => void,
): void {
  const fmt = (v: number) => fmtInt(v);
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
    label.style.setProperty('--at', frac(t, max));
    axis.append(label);
    const line = node('span', i === 0 ? 'lb-line lb-zero' : 'lb-line');
    line.style.setProperty('--at', frac(t, max));
    grid.append(line);
  });

  const list = node('ol', 'lb-rows');
  list.append(
    ...rows.map((r, i) => {
      const li = node('li');
      const row = node('button', 'lb-row');
      row.type = 'button';
      row.dataset.account = String(r.id);
      row.dataset.org = r.org;
      row.setAttribute('aria-pressed', String(r.id === selected));
      row.addEventListener('click', () => onSelect(r.id));
      // Hover card: the email stands for name and org (a name only without one).
      row.title = `${i + 1}. ${r.email ?? `${r.name} (${r.org})`}\n${fmt(r.value)} ${unit}` +
        '\nShows their comments week by week, with a link to them on Gerrit';
      const color = colorOf(r.org);
      const label = node('span', 'lb-label');
      label.append(
        node('span', 'lb-rank', `${i + 1}. `),
        node('span', 'lb-name', r.name),
      );
      if (!color) label.append(node('span', 'lb-org', ` · ${r.org}`));
      const plot = node('span', 'lb-plot');
      const bar = node('span', 'lb-bar');
      bar.style.setProperty('--fill', frac(r.value, max));
      if (color) bar.style.setProperty('--color', color);
      plot.append(bar, node('span', 'lb-value', fmt(r.value)));
      row.append(label, plot);
      li.append(row);
      return li;
    }),
  );
  box.replaceChildren(axis, grid, list);
}
