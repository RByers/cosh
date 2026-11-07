// "Review complexity by directory over time": the same directory rows and
// time columns as "Contribution by directory over time" (heatmap.ts), each cell
// shaded by the metric per review there (complexityGrid in data.ts). Cells
// with too few reviews to trust stay grey. Under Volume, cells are shaded by
// their reviews instead, to show what the figures rest on.
import { fmtInt as int, fmtNum } from './format.ts';
import { COMPLEXITY_MIN, perReview, type ComplexityGrid, type DirRow, type PerReview, type WeekRange } from './data.ts';
import { heatHead, heatRowLabel, heatTable, node } from './heatmap.ts';

/** A per-review figure: two decimals. */
export const fmtRatio = (v: number) => fmtNum(v, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export type ComplexityValue = 'complexity' | 'volume';

/** The reviews Volume's shading is scaled against: the busiest cell. */
export const complexityVolumeMax = (grid: ComplexityGrid) => Math.max(0, ...grid.cells.flat().map((c) => c.reviews));

export interface ComplexityOptions {
  grid: ComplexityGrid;
  value: ComplexityValue;
  /** The complexity shading scale (complexityScale). */
  lo: number;
  hi: number;
  /** The metric mid-sentence, e.g. "addressed comments". */
  unit: string;
  rowTitle: (row: DirRow) => string;
  binTitle: (bin: WeekRange) => string;
  onToggle: (key: string) => void;
}

const figure = (p: PerReview, unit: string) =>
  `${fmtRatio(perReview(p))} ${unit} per review (${int(p.num)} over ${int(p.reviews)} reviews)`;

export function buildComplexity(box: HTMLElement, o: ComplexityOptions): void {
  const { grid, lo, hi, unit } = o;
  if (!grid.rows.length || !grid.bins.length) {
    box.replaceChildren();
    return;
  }
  const volume = o.value === 'volume';
  const volMax = volume ? complexityVolumeMax(grid) : 0;
  const table = heatTable('cx-table', grid.bins.length);
  table.classList.add('cx');
  table.dataset.value = o.value;
  const binTitles = grid.bins.map((b) => o.binTitle(b));
  const body = node('tbody');
  grid.rows.forEach((r, ri) => {
    const tr = node('tr', `hm-row hm-${r.kind}`);
    tr.dataset.key = r.key;
    tr.dataset.depth = String(r.depth);
    const total = grid.totals[ri];
    const th = heatRowLabel(r, o.rowTitle(r), volume ? int(total.reviews) : fmtRatio(perReview(total)), o.onToggle);
    th.title = `${o.rowTitle(r)}: ${figure(total, unit)} in the range`;
    tr.append(th);
    grid.cells[ri].forEach((c, bi) => {
      const td = node('td', 'hm-cell');
      const box2 = node('span', 'hm-box');
      const lines = [`${o.rowTitle(r)}, ${binTitles[bi]}`];
      const shade = (t: number, label: string) => {
        box2.classList.add('hm-shade');
        box2.style.setProperty('--t', String(Math.min(1, Math.max(0, t))));
        box2.append(node('span', 'visually-hidden', label));
      };
      const grey = (label: string) => {
        box2.classList.add('hm-zero');
        box2.append(node('span', 'visually-hidden', label));
      };
      if (!c.reviews) {
        lines.push('No reviews');
        grey('no reviews');
      } else if (volume) {
        lines.push(figure(c, unit));
        shade(volMax ? Math.sqrt(c.reviews / volMax) : 0, `${int(c.reviews)} reviews`);
      } else if (c.reviews >= COMPLEXITY_MIN) {
        const v = perReview(c);
        lines.push(figure(c, unit));
        shade(hi > lo ? (v - lo) / (hi - lo) : 0.5, `${fmtRatio(v)} ${unit} per review`);
      } else {
        lines.push(`${figure(c, unit)}: too few reviews to shade`);
        grey('too few reviews');
      }
      box2.title = lines.join('\n');
      td.append(box2);
      tr.append(td);
    });
    body.append(tr);
  });
  table.append(heatHead(grid.bins, binTitles), body);
  box.replaceChildren(table);
}
