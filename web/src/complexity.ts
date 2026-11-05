// "Review complexity by directory over time": the same directory rows and
// time columns as "Review by directory over time" (heatmap.ts), each cell
// shaded by the metric per review there (complexityGrid in data.ts). Cells
// with too few reviews to trust stay grey.
import { fmtInt as int, fmtNum } from './format.ts';
import { COMPLEXITY_MIN, perReview, type ComplexityGrid, type DirRow, type PerReview, type WeekRange } from './data.ts';
import { heatHead, heatRowLabel, heatTable, node } from './heatmap.ts';

/** A per-review figure: two decimals. */
export const fmtRatio = (v: number) => fmtNum(v, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export interface ComplexityOptions {
  grid: ComplexityGrid;
  /** The shading scale (complexityScale). */
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
  const table = heatTable('cx-table', grid.bins.length);
  table.classList.add('cx');
  const binTitles = grid.bins.map((b) => o.binTitle(b));
  const body = node('tbody');
  grid.rows.forEach((r, ri) => {
    const tr = node('tr', `hm-row hm-${r.kind}`);
    tr.dataset.key = r.key;
    tr.dataset.depth = String(r.depth);
    const total = grid.totals[ri];
    const th = heatRowLabel(r, o.rowTitle(r), fmtRatio(perReview(total)), o.onToggle);
    th.title = `${o.rowTitle(r)}: ${figure(total, unit)} in the range`;
    tr.append(th);
    grid.cells[ri].forEach((c, bi) => {
      const td = node('td', 'hm-cell');
      const box2 = node('span', 'hm-box');
      const lines = [`${o.rowTitle(r)}, ${binTitles[bi]}`];
      if (c.reviews >= COMPLEXITY_MIN) {
        const v = perReview(c);
        box2.classList.add('hm-shade');
        box2.style.setProperty('--t', String(hi > lo ? Math.min(1, Math.max(0, (v - lo) / (hi - lo))) : 0.5));
        lines.push(figure(c, unit));
        box2.append(node('span', 'visually-hidden', `${fmtRatio(v)} ${unit} per review`));
      } else {
        box2.classList.add('hm-zero');
        lines.push(c.reviews ? `${figure(c, unit)}: too few reviews to shade` : 'No reviews');
        box2.append(node('span', 'visually-hidden', c.reviews ? 'too few reviews' : 'no reviews'));
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
