// "Review by directory": one row per directory with its volume for the chosen
// metric (a bar on a shared scale) and how that splits across organizations
// (a 100% stacked bar), plus the non-Google share as text. HTML, like the
// leaderboard, so the numbers are real text and every row has a hover title.
import { OTHER, type AreaRow } from './data.ts';

function node<K extends keyof HTMLElementTagNameMap>(tag: K, cls?: string, text?: string) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

const int = (v: number) => v.toLocaleString('en-US');
const pct = (v: number) => `${(v * 100).toFixed(v > 0 && v < 0.01 ? 2 : 1)}%`;

/** The org whose share the last column reports the complement of. */
export const MAJORITY_ORG = 'google.com';

/** Fills `box` with the directory chart. `orgs` are the named segments in
 * order (then OTHER); `colorOf` gives each its colour (OTHER: muted).
 * `metricLabel` names the volume column, e.g. "Review comments". */
export function buildAreaChart(
  box: HTMLElement,
  rows: AreaRow[],
  orgs: readonly string[],
  colorOf: (org: string) => string | undefined,
  metricLabel = 'Review comments',
): void {
  if (!rows.length) {
    box.replaceChildren();
    return;
  }
  const max = Math.max(...rows.map((r) => r.value));
  const unit = metricLabel.toLowerCase();
  const head = node('div', 'ar-head');
  head.setAttribute('aria-hidden', 'true');
  head.append(
    node('span', 'ar-label', 'Directory'),
    node('span', 'ar-vol', metricLabel),
    node('span', 'ar-dist', 'By organization'),
    node('span', 'ar-ng', `Not ${MAJORITY_ORG}`),
  );
  const segOrder = [...orgs, OTHER];
  const list = node('ol', 'ar-rows');
  list.append(
    ...rows.map((r) => {
      const li = node('li', r.included ? 'ar-row' : 'ar-row ar-excluded');
      const shareOf = (org: string) => (r.value ? (r.byOrg.get(org) ?? 0) / r.value : 0);
      const others = 1 - shareOf(MAJORITY_ORG);
      const status = r.included ? 'included' : 'excluded';
      const lines = segOrder
        .filter((o) => r.byOrg.get(o))
        .map((o) => `  ${o}: ${int(r.byOrg.get(o)!)} (${pct(shareOf(o))})`);
      li.title = `${r.area}${r.combined ? ` (${r.combined} directories)` : ''}: ${int(r.value)} ${unit}, ` +
        `${status}\n${lines.join('\n')}`;

      const label = node('span', 'ar-label');
      label.append(node('span', 'ar-name', r.area));
      label.append(node('span', 'ar-tag', status));

      const vol = node('span', 'ar-vol');
      const bar = node('span', 'ar-bar');
      bar.style.width = `${(r.value / max) * 100}%`;
      vol.append(bar, node('span', 'ar-value', int(r.value)));

      const dist = node('span', 'ar-dist');
      for (const o of segOrder) {
        const s = shareOf(o);
        if (!s) continue;
        const seg = node('span', 'ar-seg');
        seg.style.flexGrow = String(s);
        const c = o === OTHER ? undefined : colorOf(o);
        if (c) seg.style.background = c;
        seg.title = `${o}: ${int(r.byOrg.get(o)!)} (${pct(s)})`;
        dist.append(seg);
      }
      li.append(label, vol, dist, node('span', 'ar-ng', pct(others)));
      return li;
    }),
  );
  const grid = node('div', 'ar-grid');
  grid.append(head, list);
  box.replaceChildren(grid);
}
