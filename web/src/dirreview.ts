// "… per review by directory": one row per directory, like "Review by
// directory" (areas.ts), but each row shows the metric divided by its reviews
// (a bar on a shared scale), each organization's own figure there (dots on
// the same scale), and how many reviews it rests on. Rows are laid out by
// reviews (dirPerReviewRows in data.ts) and expand the same way.
import { fmtInt as int, fmtNum } from './format.ts';
import { DIR_PER_REVIEW_MIN, DIR_PER_REVIEW_ORG_MIN, OTHER, type DirPerReviewRow } from './data.ts';
import { node, rowLabel } from './areas.ts';
import { fragment } from './text.ts';

/** A per-review figure: two decimals below 10, else one. */
export const fmtRatio = (v: number) => fmtNum(v, { minimumFractionDigits: v < 10 ? 2 : 1, maximumFractionDigits: v < 10 ? 2 : 1 });

/** The bar scale: the largest top-level figure resting on enough reviews,
 * so expanding a row never rescales the chart and one tiny directory can't
 * flatten the rest. Bars and dots past it are drawn at its end. */
export function dirPerReviewMax(rows: DirPerReviewRow[]): number {
  const top = rows.filter((r) => r.row.depth === 0);
  const sure = top.filter((r) => r.row.value >= DIR_PER_REVIEW_MIN);
  return Math.max(0, ...(sure.length ? sure : top).map((r) => r.ratio));
}

/** Fills `box` with the chart. `orgs` are the named orgs in order (then
 * OTHER); `colorOf` gives each its colour (OTHER: muted). `metricLabel`
 * names the figure, e.g. "Addressed comments", and `unit` is the same
 * mid-sentence. `overall` is every directory's figure together, marked as a
 * line down the bar column. */
export function buildDirPerReviewChart(
  box: HTMLElement,
  rows: DirPerReviewRow[],
  orgs: readonly string[],
  colorOf: (org: string) => string | undefined,
  metricLabel: string,
  unit: string,
  overall: number,
  onToggle: (key: string) => void,
): void {
  if (!rows.length) {
    box.replaceChildren();
    return;
  }
  const max = dirPerReviewMax(rows) || 1;
  const at = (v: number) => String(Math.min(v, max) / max);
  const head = node('div', 'ar-head');
  head.setAttribute('aria-hidden', 'true');
  head.append(fragment('dr-head', { metric: metricLabel }));
  const order = [...orgs, OTHER];
  const list = node('ol', 'ar-rows');
  list.append(
    ...rows.map(({ row: r, num, ratio, orgs: byOrg }) => {
      const few = r.value < DIR_PER_REVIEW_MIN;
      const li = node('li', `ar-row ar-${r.kind}${few ? ' dr-few' : ''}`);
      li.dataset.key = r.key;
      li.dataset.depth = String(r.depth);
      li.style.setProperty('--depth', String(r.depth));
      const shown = order.filter((o) => byOrg.get(o)?.reviews);
      const lines = shown.map((o) => {
        const f = byOrg.get(o)!;
        return `  ${o}: ${fmtRatio(f.ratio)} (${int(f.num)} over ${int(f.reviews)} reviews)`;
      });
      li.title =
        `${r.title}: ${fmtRatio(ratio)} ${unit} per review (${int(num)} over ${int(r.value)} reviews)` +
        (few ? `; under ${DIR_PER_REVIEW_MIN} reviews, so one CL can sway it` : '') +
        `\n${lines.join('\n')}`;

      const vol = node('span', 'ar-vol dr-vol');
      const torn = ratio > max;
      const bar = node('span', torn ? 'ar-bar ar-torn' : 'ar-bar');
      bar.style.setProperty('--fill', at(ratio));
      if (torn) bar.title = `Bar truncated: ${fmtRatio(ratio)} is off the scale`;
      bar.append(node('span', 'ar-bar-in'));
      vol.append(bar, node('span', 'ar-value', fmtRatio(ratio)));

      // Each org's own figure, for those with enough reviews here; OTHER first,
      // so named orgs draw on top of it.
      const dots = node('span', 'dr-dots');
      for (const o of [OTHER, ...orgs]) {
        const f = byOrg.get(o);
        if (!f || f.reviews < DIR_PER_REVIEW_ORG_MIN) continue;
        const dot = node('span', f.ratio > max ? 'dr-dot dr-dot-over' : 'dr-dot');
        dot.style.setProperty('--at', at(f.ratio));
        const c = o === OTHER ? undefined : colorOf(o);
        if (c) dot.style.setProperty('--color', c);
        dot.title = `${o}: ${fmtRatio(f.ratio)} ${unit} per review (${int(f.num)} over ${int(f.reviews)} reviews)`;
        dots.append(dot);
      }
      li.append(rowLabel(r, onToggle), vol, dots, node('span', 'ar-ng', int(r.value)));
      return li;
    }),
  );
  const grid = node('div', 'ar-grid dr-grid');
  grid.style.setProperty('--ar-label-chars', String(Math.max(...rows.map((r) => fmtRatio(r.ratio).length))));
  grid.style.setProperty('--avg', at(overall));
  grid.append(head, list);
  box.replaceChildren(grid);
}
