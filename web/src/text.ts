// The page's wording lives in index.html, not in the scripts, so it can be
// reviewed and changed in one file. Text that depends on the data is written
// there as <template data-msg="key"> elements, next to where it's shown, and
// rendered here (index.html's opening comment has the syntax):
//
//   <slot name="x"></slot>   the value `x` the script passes
//   data-if="x" / "!x"       kept only when `x` is set (non-empty, non-zero) / isn't
//   data-if="x=v" / "x!=v"   kept only when `x` is / isn't v (compared as text)
//
// A kept <span data-if> is unwrapped; other elements stay. Whitespace that
// includes a line break collapses to one space (to nothing at the template's
// edges), so templates can be wrapped freely; spaces within a line are kept.

/** Values for a template's slots and conditions. */
export type Vars = Record<string, string | number | boolean | null | undefined>;

const templates = new Map<string, HTMLTemplateElement>();

function template(key: string): HTMLTemplateElement {
  let t = templates.get(key);
  if (!t) {
    t = document.querySelector<HTMLTemplateElement>(`template[data-msg="${CSS.escape(key)}"]`) ?? undefined;
    if (!t) throw new Error(`No <template data-msg="${key}"> in index.html`);
    templates.set(key, t);
  }
  return t;
}

function holds(key: string, cond: string, vars: Vars): boolean {
  const m = /^(!?)([\w-]+)(?:(!?=)(.*))?$/.exec(cond.trim());
  if (!m) throw new Error(`UI text "${key}": bad data-if="${cond}"`);
  const [, not, name, op, want] = m;
  if (!(name in vars)) throw new Error(`UI text "${key}": no value for data-if="${cond}"`);
  const v = vars[name];
  const set = !(v === null || v === undefined || v === false || v === '' || v === 0 || v === '0');
  const r = op ? (String(v) === want) === (op === '=') : set;
  return not ? !r : r;
}

/** The template `key`, rendered with `vars`. */
export function fragment(key: string, vars: Vars = {}): DocumentFragment {
  const frag = template(key).content.cloneNode(true) as DocumentFragment;

  // Conditions, outermost first (document order); a dropped element takes
  // its nested ones with it.
  for (const e of frag.querySelectorAll<HTMLElement>('[data-if]')) {
    if (!frag.contains(e)) continue;
    if (!holds(key, e.dataset.if!, vars)) e.remove();
    else if (e.localName === 'span' && e.attributes.length === 1) e.replaceWith(...e.childNodes);
    else e.removeAttribute('data-if');
  }

  // The template's own whitespace, before any value goes in.
  frag.normalize();
  const first = firstLeaf(frag);
  const last = lastLeaf(frag);
  const walker = document.createTreeWalker(frag, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const t = n as Text;
    let s = t.data;
    if (t === first) s = s.replace(/^[ \t]*[\n\r][ \t\n\r]*/, '');
    if (t === last) s = s.replace(/[ \t\n\r]*[\n\r][ \t]*$/, '');
    t.data = s.replace(/[ \t]*[\n\r][ \t\n\r]*/g, ' ');
  }

  for (const s of frag.querySelectorAll('slot')) {
    if (!(s.name in vars)) throw new Error(`UI text "${key}": no value for <slot name="${s.name}">`);
    s.replaceWith(String(vars[s.name] ?? ''));
  }
  return frag;
}

function firstLeaf(n: Node): Node {
  while (n.firstChild) n = n.firstChild;
  return n;
}

function lastLeaf(n: Node): Node {
  while (n.lastChild) n = n.lastChild;
  return n;
}

/** The template `key` as a plain string. */
export function msg(key: string, vars: Vars = {}): string {
  return fragment(key, vars).textContent ?? '';
}

/** Replaces `target`'s contents with the template `key` (by default the one
 * named after the target's id). */
export function fill(target: Element, vars: Vars = {}, key = target.id): void {
  target.replaceChildren(fragment(key, vars));
}
