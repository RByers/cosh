// "Review by directory over time": directories (the same drill-down rows as
// the directory chart) against time bins. A table, so every cell has a row
// and column header for screen readers; the directory column stays put while
// the bins scroll sideways on narrow screens.
//
// Two modes. With several orgs ("mix"), each cell is a small stacked column:
// its segments are the orgs' shares, and its height the cell's volume against
// the row's busiest bin (or full height, to compare shares). With one org,
// each cell is shaded in that org's colour, by its volume against the busiest
// cell in the grid (square-root scale, so small directories still show) or by
// its share of the directory's review.
import { fmtInt as int } from './format.ts';
import { monthTicks, OTHER, TOP_ORGS, type DirLink, type HeatGrid, type DirRow, type WeekRange } from './data.ts';
import { msg } from './text.ts';

function node<K extends keyof HTMLElementTagNameMap>(tag: K, cls?: string, text?: string) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

const pct = (v: number) => `${(v * 100).toFixed(v > 0 && v < 0.01 ? 2 : 1)}%`;

export type HeatValue = 'volume' | 'share';

/** The extras a cell gets once the reviewer data has loaded. */
export interface HeatCellInfo {
  link: DirLink | null;
  /** Most active reviewers: email (or name, without one) and comments. */
  top: { who: string; comments: number }[];
}

export interface HeatOptions {
  grid: HeatGrid;
  /** null: every org the grid counts, as a mix; else the one org shown. */
  org: string | null;
  value: HeatValue;
  /** Named segment orgs, in order (then OTHER), and their colours. */
  orgs: readonly string[];
  colorOf: (org: string) => string | undefined;
  /** The single org's colour (org mode). */
  orgColor?: string;
  /** The metric mid-sentence, e.g. "review comments". */
  unit: string;
  /** Full path or description of a row, for titles. */
  rowTitle: (row: DirRow) => string;
  binTitle: (bin: WeekRange) => string;
  cellInfo?: (row: number, bin: number) => HeatCellInfo | null;
  onToggle: (key: string) => void;
  /** Shows a directory in the organization chart. */
  onChart: (row: DirRow) => void;
}

/** The volume a single-org cell is scaled against: the busiest cell. */
export const heatMax = (grid: HeatGrid, org: string) =>
  Math.max(0, ...grid.cells.flat().map((c) => c.byOrg.get(org) ?? 0));

export function buildHeatmap(box: HTMLElement, o: HeatOptions): void {
  const { grid } = o;
  if (!grid.rows.length || !grid.bins.length) {
    box.replaceChildren();
    return;
  }
  const unit = o.unit;
  const segOrder = [...o.orgs, OTHER];
  const single = o.org;
  const gridMax = single ? heatMax(grid, single) : 0;

  const table = node('table', 'hm');
  table.id = 'heat-table';
  // Fixed layout: the bins share the width evenly, but never get narrower
  // than a few pixels; past that the region scrolls.
  table.style.setProperty('--hm-bins', String(grid.bins.length));
  // A single org's cells are shaded from its colour (style.css: .hm-shade).
  if (single && o.orgColor) table.style.setProperty('--color', o.orgColor);
  const head = node('thead');
  const hr = node('tr');
  const corner = node('th', 'hm-corner', msg('hm-corner'));
  corner.scope = 'col';
  hr.append(corner);
  // Month ticks; on narrow screens CSS keeps only the coarse ones (at most 4).
  // The subtitle names the range, so only January carries its year.
  const starts = grid.bins.map((b) => b.from);
  // Once per bin: every cell's hover text repeats its bin's title.
  const binTitles = grid.bins.map((b) => o.binTitle(b));
  // Coarse ticks near the right edge would run off it.
  const coarse = new Set(monthTicks(starts, 4).map((t) => t.index).filter((i) => i < starts.length - 2));
  const ticks = new Map(monthTicks(starts, 12).map((t) => [t.index, t.label.split(' ')]));
  grid.bins.forEach((b, i) => {
    const th = node('th', 'hm-bin');
    th.scope = 'col';
    const tick = ticks.get(i);
    if (tick) {
      const t = node('span', coarse.has(i) ? 'hm-tick' : 'hm-tick hm-minor', tick[0]);
      if (tick[0] === 'Jan' && tick[1]) t.append(node('span', 'hm-year', ` ${tick[1]}`));
      t.setAttribute('aria-hidden', 'true');
      th.append(t);
    }
    th.append(node('span', 'visually-hidden', binTitles[i]));
    th.title = binTitles[i];
    hr.append(th);
  });
  head.append(hr);

  const body = node('tbody');
  grid.rows.forEach((r, ri) => {
    const tr = node('tr', `hm-row hm-${r.kind}`);
    tr.dataset.key = r.key;
    tr.dataset.depth = String(r.depth);
    const cells = grid.cells[ri];
    const rowTotal = cells.reduce((s, c) => s + (single ? c.byOrg.get(single) ?? 0 : c.value), 0);
    const rowMax = Math.max(0, ...cells.map((c) => c.value));

    const th = node('th', 'hm-label');
    th.scope = 'row';
    const lab = node('span', 'hm-lab');
    lab.style.setProperty('--depth', String(r.depth));
    th.append(lab);
    th.title = `${o.rowTitle(r)}: ${int(rowTotal)} ${unit}${single ? ` from ${single}` : ''} in the range`;
    if (r.expandable) {
      const b = node('button', 'ar-toggle', r.expanded ? '▾' : '▸');
      b.type = 'button';
      b.setAttribute('aria-expanded', String(r.expanded));
      b.setAttribute('aria-label', `${r.expanded ? 'Collapse' : 'Expand'} ${r.kind === 'other' ? r.label : o.rowTitle(r)}`);
      b.addEventListener('click', () => o.onToggle(r.key));
      lab.append(b);
    } else {
      lab.append(node('span', 'ar-toggle-space'));
    }
    lab.append(node('span', 'hm-name', r.label));
    if (r.kind === 'dir') {
      const c = node('button', 'hm-chart', msg('hm-chart'));
      c.type = 'button';
      c.title = `Show ${o.rowTitle(r)} in the organization chart`;
      c.setAttribute('aria-label', c.title);
      c.addEventListener('click', () => o.onChart(r));
      lab.append(c);
    }
    lab.append(node('span', 'hm-total', int(rowTotal)));
    tr.append(th);

    cells.forEach((c, bi) => {
      const td = node('td', 'hm-cell');
      const info = o.cellInfo?.(ri, bi) ?? null;
      const link = info?.link ?? null;
      const mine = single ? c.byOrg.get(single) ?? 0 : c.value;
      const box2 = node(link ? 'a' : 'span', 'hm-box');
      const lines = [`${o.rowTitle(r)}, ${binTitles[bi]}`];
      if (single) {
        const share = c.value ? mine / c.value : 0;
        lines.push(`${single}: ${int(mine)} ${unit}` + (c.value ? ` (${pct(share)} of ${int(c.value)} there)` : ''));
        const t = o.value === 'share' ? share : gridMax ? Math.sqrt(mine / gridMax) : 0;
        if (mine > 0 && o.orgColor) {
          box2.classList.add('hm-shade');
          box2.style.setProperty('--t', String(Math.min(1, Math.max(0, t))));
        } else box2.classList.add('hm-zero');
      } else {
        lines.push(`${int(c.value)} ${unit}`);
        const shown = segOrder.filter((g) => c.byOrg.get(g));
        const bySize = shown.filter((g) => g !== OTHER).sort((x, y) => c.byOrg.get(y)! - c.byOrg.get(x)!);
        for (const g of [...bySize.slice(0, TOP_ORGS), ...(c.byOrg.get(OTHER) ? [OTHER] : [])]) lines.push(`  ${g}: ${int(c.byOrg.get(g)!)} (${pct(c.byOrg.get(g)! / c.value)})`);
        if (c.value > 0) {
          const col = node('span', 'hm-col');
          col.style.setProperty('--fill', String(o.value === 'share' ? 1 : rowMax ? Math.max(0.08, c.value / rowMax) : 0));
          // Bottom-up in legend order, so google.com's share sits on the baseline.
          for (const g of shown) {
            const seg = node('span', 'hm-seg');
            seg.style.setProperty('--share', String(c.byOrg.get(g)! / c.value));
            const color = g === OTHER ? undefined : o.colorOf(g);
            if (color) seg.style.setProperty('--color', color);
            col.append(seg);
          }
          box2.append(col);
        } else {
          box2.classList.add('hm-zero');
        }
      }
      if (info?.top.length) {
        lines.push(`Most active: ${info.top.map((p) => `${p.who} (${int(p.comments)})`).join(', ')}`);
      }
      if (link) {
        box2.setAttribute('href', link.url);
        box2.setAttribute('target', '_blank');
        box2.setAttribute('rel', 'noopener');
        const who = link.shown < link.total
          ? `its ${link.shown} most active reviewers (of ${int(link.total)})`
          : link.total === 1 ? 'its reviewer' : `its ${link.total} reviewers`;
        lines.push(`Opens the CLs in ${link.path} that ${who} commented on in these weeks, on Gerrit in a new tab.`);
      }
      box2.title = lines.join('\n');
      // The number, for screen readers; the colour and height carry it visually.
      box2.append(node('span', 'visually-hidden', single ? `${int(mine)} ${unit}` : `${int(c.value)} ${unit}`));
      td.append(box2);
      tr.append(td);
    });
    body.append(tr);
  });
  table.append(head, body);
  box.replaceChildren(table);
}
