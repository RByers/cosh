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
