/** Formats a value ratio for axis labels and tooltips: 0, 0.25, 1.0, 12. */
export function formatRatio(r: number): string {
  if (r === 0) return '0';
  if (r >= 10) return r.toFixed(0);
  return r.toFixed(2).replace(/0$/, '');
}
