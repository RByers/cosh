// "Contribution by directory": one row per directory with its volume for the chosen
// metric (a bar on a shared scale) and how that splits across organizations
// (a 100% stacked bar), plus the non-Google share as text. Rows expand into
// subdirectories, and "other" rows into the next entries (dirRows in data.ts).
// HTML, like the leaderboard, so the numbers are real text, every row has a
// hover title, and the toggles are real buttons. An org's segment can link to
// its reviewers' CLs in the directory on Gerrit.
import { fmtInt as int } from './format.ts';
import { barScale, OTHER, type DirLink, type DirRow } from './data.ts';
import { fragment } from './text.ts';

export function node<K extends keyof HTMLElementTagNameMap>(tag: K, cls?: string, text?: string) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

export const pct = (v: number) => `${(v * 100).toFixed(v > 0 && v < 0.01 ? 2 : 1)}%`;

/** A row's first cell: its expand/collapse button (or the same width of
 * space), its name, and whether the path scope counts it. */
export function rowLabel(r: DirRow, onToggle: (key: string) => void): HTMLElement {
  const label = node('span', 'ar-label');
  if (r.expandable) {
    const button = node('button', 'ar-toggle', r.expanded ? '▾' : '▸');
    button.type = 'button';
    button.setAttribute('aria-expanded', String(r.expanded));
    button.setAttribute('aria-label', `${r.expanded ? 'Collapse' : 'Expand'} ${r.kind === 'other' ? r.label : r.title}`);
    button.addEventListener('click', () => onToggle(r.key));
    label.append(button);
  } else {
    label.append(node('span', 'ar-toggle-space'));
  }
  label.append(node('span', 'ar-name', r.label));
  // Whether the path scope counts this row: wholly, not at all, or in part.
  const tag = r.included >= 1 ? 'included' : r.included <= 0 ? 'excluded' : 'mixed';
  const tagEl = node('span', `ar-tag ar-tag-${tag}`, tag);
  if (tag === 'mixed') tagEl.title = `${pct(r.included)} included`;
  label.append(tagEl);
  return label;
}

/** The org whose share the last column reports the complement of. */
export const MAJORITY_ORG = 'google.com';

/** Fills `box` with the directory chart. `orgs` are the named segments in
 * order (then OTHER); `colorOf` gives each its colour (OTHER: muted).
 * `metricLabel` names the volume column, e.g. "Review comments", and `unit`
 * is the same mid-sentence, e.g. "review comments". `onToggle`
 * is called with a row's key when its expand/collapse button is pressed.
 * `linkOf`, when it gives a link, makes that org's segment of the row open
 * its reviewers' CLs in the directory on Gerrit. */
export function buildAreaChart(
  box: HTMLElement,
  rows: DirRow[],
  orgs: readonly string[],
  colorOf: (org: string) => string | undefined,
  metricLabel: string,
  unit: string,
  onToggle: (key: string) => void,
  linkOf: (row: DirRow, org: string) => DirLink | null = () => null,
): void {
  if (!rows.length) {
    box.replaceChildren();
    return;
  }
  // The scale comes from the top level, so expanding a row never rescales the
  // chart. A few huge directories (e.g. chrome/) would flatten every other bar,
  // so the scale may stop short of them; those bars are drawn torn (barScale).
  const { max } = barScale(rows.filter((r) => r.depth === 0).map((r) => r.value));
  const head = node('div', 'ar-head');
  head.setAttribute('aria-hidden', 'true');
  head.append(fragment('ar-head', { metric: metricLabel }));
  const segOrder = [...orgs, OTHER];
  const list = node('ol', 'ar-rows');
  list.append(
    ...rows.map((r) => {
      const li = node('li', `ar-row ar-${r.kind}`);
      li.dataset.key = r.key;
      li.dataset.depth = String(r.depth);
      li.style.setProperty('--depth', String(r.depth));
      const shareOf = (org: string) => (r.value ? (r.byOrg.get(org) ?? 0) / r.value : 0);
      const others = 1 - shareOf(MAJORITY_ORG);
      const status = r.included >= 1 ? 'included' : r.included <= 0 ? 'excluded' : `${pct(r.included)} included`;
      li.dataset.included = String(r.included);
      const lines = segOrder
        .filter((o) => r.byOrg.get(o))
        .map((o) => `  ${o}: ${int(r.byOrg.get(o)!)} (${pct(shareOf(o))})`);
      li.title = `${r.title}: ${int(r.value)} ${unit}, ${status}\n${lines.join('\n')}`;

      const label = rowLabel(r, onToggle);

      const vol = node('span', 'ar-vol');
      const torn = r.value > max;
      const bar = node('span', torn ? 'ar-bar ar-torn' : 'ar-bar');
      // Widths are a share of the column minus room for the value label, so
      // the label never runs into the next column.
      bar.style.setProperty('--fill', String(max ? Math.min(r.value, max) / max : 0));
      if (torn) bar.title = `Bar truncated: ${int(r.value)} is off the scale`;
      // Solid for the part in scope, hatched for the part left out.
      for (const [part, share] of [['ar-bar-in', r.included], ['ar-bar-out', 1 - r.included]] as const) {
        if (share <= 0) continue;
        const seg = node('span', part);
        seg.style.setProperty('--share', String(share));
        bar.append(seg);
      }
      vol.append(bar, node('span', 'ar-value', int(r.value)));

      const dist = node('span', 'ar-dist');
      for (const o of segOrder) {
        const s = shareOf(o);
        if (!s) continue;
        const link = linkOf(r, o);
        const seg = node(link ? 'a' : 'span', 'ar-seg');
        seg.style.setProperty('--share', String(s));
        const c = o === OTHER ? undefined : colorOf(o);
        if (c) seg.style.setProperty('--color', c);
        seg.title = `${o}: ${int(r.byOrg.get(o)!)} (${pct(s)})`;
        if (link) {
          seg.setAttribute('href', link.url);
          seg.setAttribute('target', '_blank');
          seg.setAttribute('rel', 'noopener');
          const people = link.authors ? 'authors' : 'reviewers';
          const who = link.shown < link.total
            ? `its ${link.shown} most active ${people} (of ${int(link.total)})`
            : link.total === 1 ? `its ${people.slice(0, -1)}` : `its ${link.total} ${people}`;
          seg.title += `\nOpens the CLs in ${link.path} that ${who} ${link.authors ? 'landed' : 'commented on'}, on Gerrit in a new tab. ` +
            'Gerrit can only match CLs that touch the directory and changed around the range, so it lists more than are counted here.';
          seg.setAttribute('aria-label', `${o} in ${r.title}: ${int(r.byOrg.get(o)!)} ${unit}; open on Gerrit`);
        }
        dist.append(seg);
      }
      li.append(label, vol, dist, node('span', 'ar-ng', r.value ? pct(others) : '—'));
      return li;
    }),
  );
  const grid = node('div', 'ar-grid');
  // Room for the longest value label (style.css: --ar-label-room).
  grid.style.setProperty('--ar-label-chars', String(Math.max(...rows.map((r) => int(r.value).length))));
  grid.append(head, list);
  box.replaceChildren(grid);
}
