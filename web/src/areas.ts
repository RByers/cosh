// "Review by directory": one row per directory with its volume for the chosen
// metric (a bar on a shared scale) and how that splits across organizations
// (a 100% stacked bar), plus the non-Google share as text. Rows expand into
// subdirectories, and "other" rows into the next entries (dirRows in data.ts).
// HTML, like the leaderboard, so the numbers are real text, every row has a
// hover title, and the toggles are real buttons. An org's segment can link to
// its reviewers' CLs in the directory on Gerrit.
import { barScale, OTHER, type DirLink, type DirRow } from './data.ts';

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
 * `metricLabel` names the volume column, e.g. "Review comments". `onToggle`
 * is called with a row's key when its expand/collapse button is pressed.
 * `linkOf`, when it gives a link, makes that org's segment of the row open
 * its reviewers' CLs in the directory on Gerrit. */
export function buildAreaChart(
  box: HTMLElement,
  rows: DirRow[],
  orgs: readonly string[],
  colorOf: (org: string) => string | undefined,
  metricLabel: string,
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
      const li = node('li', `ar-row ar-${r.kind}`);
      li.dataset.key = r.key;
      li.dataset.depth = String(r.depth);
      const shareOf = (org: string) => (r.value ? (r.byOrg.get(org) ?? 0) / r.value : 0);
      const others = 1 - shareOf(MAJORITY_ORG);
      const status = r.included >= 1 ? 'included' : r.included <= 0 ? 'excluded' : `${pct(r.included)} included`;
      li.dataset.included = String(r.included);
      const lines = segOrder
        .filter((o) => r.byOrg.get(o))
        .map((o) => `  ${o}: ${int(r.byOrg.get(o)!)} (${pct(shareOf(o))})`);
      li.title = `${r.title}: ${int(r.value)} ${unit}, ${status}\n${lines.join('\n')}`;

      const label = node('span', 'ar-label');
      label.style.paddingLeft = `${r.depth * 14}px`;
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

      const vol = node('span', 'ar-vol');
      const torn = r.value > max;
      const bar = node('span', torn ? 'ar-bar ar-torn' : 'ar-bar');
      // Widths are a share of the column minus room for the value label, so
      // the label never runs into the next column.
      bar.style.width = `calc((100% - var(--ar-label-room)) * ${max ? Math.min(r.value, max) / max : 0})`;
      if (torn) bar.title = `Bar truncated: ${int(r.value)} is off the scale`;
      // Solid for the part in scope, hatched for the part left out.
      for (const [part, share] of [['ar-bar-in', r.included], ['ar-bar-out', 1 - r.included]] as const) {
        if (share <= 0) continue;
        const seg = node('span', part);
        seg.style.flexGrow = String(share);
        bar.append(seg);
      }
      vol.append(bar, node('span', 'ar-value', int(r.value)));

      const dist = node('span', 'ar-dist');
      for (const o of segOrder) {
        const s = shareOf(o);
        if (!s) continue;
        const link = linkOf(r, o);
        const seg = node(link ? 'a' : 'span', 'ar-seg');
        seg.style.flexGrow = String(s);
        const c = o === OTHER ? undefined : colorOf(o);
        if (c) seg.style.background = c;
        seg.title = `${o}: ${int(r.byOrg.get(o)!)} (${pct(s)})`;
        if (link) {
          seg.setAttribute('href', link.url);
          seg.setAttribute('target', '_blank');
          seg.setAttribute('rel', 'noopener');
          const who = link.shown < link.total
            ? `its ${link.shown} most active reviewers (of ${int(link.total)})`
            : link.total === 1 ? 'its reviewer' : `its ${link.total} reviewers`;
          seg.title += `\nOpens the CLs in ${link.path} that ${who} commented on, on Gerrit in a new tab. ` +
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
  grid.append(head, list);
  box.replaceChildren(grid);
}
