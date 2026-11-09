// Number and date formatting with cached Intl formatters. `toLocaleString`
// builds a new formatter on every call, which is slow when a render formats
// thousands of values (the heatmap's hover text formats several per cell).

const numFormats = new Map<string, Intl.NumberFormat>();

/** `v.toLocaleString('en-US', opts)`, with the formatter cached per options. */
export function fmtNum(v: number, opts?: Intl.NumberFormatOptions): string {
  const key = opts ? JSON.stringify(opts) : '';
  let f = numFormats.get(key);
  if (!f) numFormats.set(key, (f = new Intl.NumberFormat('en-US', opts)));
  return f.format(v);
}

/** An integer with thousands separators: "12,345". */
export const fmtInt = (v: number) => fmtNum(v);

const dayYear = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
const dayNoYear = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' });

/** A UTC date as "30 Mar 2026", or "30 Mar" without the year. */
export const fmtDay = (d: Date, year = true) => (year ? dayYear : dayNoYear).format(d);

const monthYear = new Intl.DateTimeFormat('en-GB', { month: 'short', year: 'numeric', timeZone: 'UTC' });

/** "Oct 2025": the first month of quarter "2025Q4", or with `end` its last ("Dec 2025"). */
export const fmtQuarterMonth = (q: string, end = false) =>
  monthYear.format(new Date(Date.UTC(Number(q.slice(0, 4)), (Number(q.slice(-1)) - 1) * 3 + (end ? 2 : 0), 1)));

/** A histogram bin of hours, [lo, hi) or lo and up: "< 1 h", "16–24 h", "4–7 d", "2 wk+".
 * The low edge picks the unit. */
export function fmtHoursBin(lo: number, hi: number | null): string {
  if (lo === 0) return `< ${hi} h`;
  const [per, u] = lo < 24 ? [1, 'h'] : lo < 168 ? [24, 'd'] : [168, 'wk'];
  const v = (h: number) => fmtNum(h / per, { maximumFractionDigits: 1 });
  return hi === null ? `${v(lo)} ${u}+` : `${v(lo)}–${v(hi)} ${u}`;
}
