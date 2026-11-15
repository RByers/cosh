// The subtitle under each analysis page's title: the dates its data covers
// ("Based on Chromium Gerrit and git data from 3 Jul 2017 to 1 Nov 2026").
// The step that publishes a page's data stamps its first file with a
// `data_span` (cosh/data_span.py, docs/data-architecture.md "Data spans"),
// so the dates move with the data. The wording is the page's
// <template data-msg="data-span">; its <p id="data-span"> stays hidden
// until a span is known.

import { fmtDay } from './format.ts';
import { fill } from './text.ts';

/** cosh.data_span: UTC days, both included. */
export interface DataSpan {
  first: string;
  last: string;
  sources: string[];
}

/** One span for data from several: from the earliest start to the earliest
 * end, since the page is only as current as its oldest source. */
export function combineSpans(spans: readonly (DataSpan | null | undefined)[]): DataSpan | null {
  const known = spans.filter((s): s is DataSpan => !!s?.first && !!s.last);
  if (!known.length) return null;
  const min = (xs: string[]) => xs.reduce((a, b) => (b < a ? b : a));
  return {
    first: min(known.map((s) => s.first)),
    last: min(known.map((s) => s.last)),
    sources: [...new Set(known.flatMap((s) => s.sources))].sort(),
  };
}

/** "3 Jul 2017" for "2017-07-03". */
const day = (iso: string) => fmtDay(new Date(`${iso}T00:00:00Z`));

/** Shows the page's subtitle for these spans (combined), or keeps it hidden
 * if none is known. */
export function showDataSpan(...spans: (DataSpan | null | undefined)[]): void {
  const el = document.getElementById('data-span');
  const span = combineSpans(spans);
  if (!el || !span) return;
  fill(el, { first: day(span.first), last: day(span.last) });
  el.hidden = false;
}
