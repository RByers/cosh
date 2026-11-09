// Defined terms (balance.html): each use of a term is a <button class="term"
// popovertarget="def-…">, and the short definition is that popover, written
// in the HTML. The browser opens and light-dismisses it; this only places the
// bubble next to the term that opened it (CSS anchor positioning isn't
// available everywhere yet), through the --pop-top and --pop-left properties.

const GUTTER = 16;
const GAP = 6;

function place(pop: HTMLElement, term: HTMLElement) {
  // A term that wraps has several boxes; the bubble goes by the first.
  const r = term.getClientRects()[0] ?? term.getBoundingClientRect();
  const vw = document.documentElement.clientWidth;
  const vh = window.innerHeight;
  const w = pop.offsetWidth;
  const h = pop.offsetHeight;
  const left = Math.min(Math.max(GUTTER, r.left), Math.max(GUTTER, vw - GUTTER - w));
  // Below the term, or above it when there's no room below.
  const below = r.bottom + GAP + h <= vh || r.top - GAP - h < 0;
  const top = below ? r.bottom + GAP : r.top - GAP - h;
  // The popover sits in the top layer, positioned against the whole page.
  pop.style.setProperty('--pop-left', `${left + window.scrollX}px`);
  pop.style.setProperty('--pop-top', `${top + window.scrollY}px`);
  pop.dataset.placed = '';
}

export function initTerms() {
  const termOf = (e: Event) => (e.target instanceof Element ? e.target.closest<HTMLElement>('button.term') : null);
  if (!('popover' in HTMLElement.prototype)) {
    // No popovers: a term jumps to its full definition instead.
    document.addEventListener('click', (e) => {
      const id = termOf(e)?.getAttribute('popovertarget');
      const link = id ? document.getElementById(id)?.querySelector('a') : null;
      if (link) location.hash = link.hash;
    });
    return;
  }
  let last: HTMLElement | null = null;
  // Capture runs before the button opens its popover.
  document.addEventListener('click', (e) => {
    const t = termOf(e);
    if (t) last = t;
  }, true);
  for (const pop of document.querySelectorAll<HTMLElement>('.term-pop')) {
    pop.addEventListener('toggle', (e) => {
      if ((e as ToggleEvent).newState === 'open' && last) place(pop, last);
      else delete pop.dataset.placed;
    });
    pop.querySelector('a')?.addEventListener('click', () => pop.hidePopover());
  }
}
