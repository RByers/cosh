// Links into collapsed sections. A page's methodology is a closed <details>,
// and browsers don't all open one to follow a link into it. So when the URL's
// hash names an element (on load, or later: a "#" link, a term bubble's link),
// this opens every <details> around it and scrolls there. The page's data and
// a section's charts render after that, moving the element, so it scrolls
// there again whenever the page's size changes, until the reader scrolls,
// types or clicks, or a few seconds pass.

const SETTLE_MS = 10_000;

let target: Element | null = null;
let until = 0;

function follow() {
  if (target && performance.now() < until) target.scrollIntoView({ block: 'start' });
  else target = null;
}

/** Opens the sections around the element the URL's hash names, and scrolls to it. */
export function revealHash() {
  target = null;
  const raw = location.hash.slice(1);
  // Page state in the hash (#given=…, #n=…) names no element.
  if (!raw || raw.includes('=')) return;
  let id: string;
  try {
    id = decodeURIComponent(raw);
  } catch {
    return;
  }
  const el = document.getElementById(id);
  if (!el) return;
  // The element itself may be the <details> (#method).
  for (let d = el.closest('details'); d; d = d.parentElement?.closest('details') ?? null) d.open = true;
  target = el;
  until = performance.now() + SETTLE_MS;
  follow();
}

export function initAnchors() {
  revealHash();
  addEventListener('hashchange', revealHash);
  new ResizeObserver(() => follow()).observe(document.documentElement);
  // Once the reader moves the page themselves, leave it where they put it.
  const forget = () => { target = null; };
  for (const type of ['wheel', 'touchstart', 'keydown', 'pointerdown']) {
    addEventListener(type, forget, { capture: true, passive: true });
  }
}
