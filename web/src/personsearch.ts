// The leaderboard's "Find a person" box: a combobox that suggests people as
// the reader types (nothing until then, at most SEARCH_MAX), from data the
// page already holds (findPeople in data.ts). Text only, no innerHTML: names
// and emails come from Gerrit.

import type { PersonMatch } from './data.ts';

export interface PersonSearch {
  /** Re-runs the current query, e.g. once more people (commit authors) are loaded. */
  refresh: () => void;
}

/** Wires `input` (role=combobox, in value.html) to `list` (role=listbox).
 * `matches` gives the suggestions for a query; `onPick` opens a person.
 * `onType` runs on the first keystroke (to load more people); `none` is the
 * line shown when nothing matches. */
export function personSearch(
  input: HTMLInputElement,
  list: HTMLElement,
  { matches, onPick, onType, none }: {
    matches: (query: string) => PersonMatch[];
    onPick: (m: PersonMatch) => void;
    onType?: () => void;
    none: (query: string) => string;
  },
): PersonSearch {
  let shown: PersonMatch[] = [];
  let active = -1;

  const close = () => {
    list.hidden = true;
    list.replaceChildren();
    input.setAttribute('aria-expanded', 'false');
    input.removeAttribute('aria-activedescendant');
    shown = [];
    active = -1;
  };

  const setActive = (i: number) => {
    active = i;
    list.querySelectorAll<HTMLElement>('[role="option"]').forEach((o, k) => o.setAttribute('aria-selected', String(k === i)));
    if (i >= 0) {
      input.setAttribute('aria-activedescendant', `${list.id}-${i}`);
      list.querySelector(`#${list.id}-${i}`)?.scrollIntoView({ block: 'nearest' });
    } else input.removeAttribute('aria-activedescendant');
  };

  const choose = (i: number) => {
    const m = shown[i];
    if (!m) return;
    input.value = m.name;
    close();
    onPick(m);
  };

  const show = () => {
    const q = input.value;
    if (!q.trim()) return close();
    shown = matches(q);
    active = -1;
    input.removeAttribute('aria-activedescendant');
    if (!shown.length) {
      const li = document.createElement('li');
      li.className = 'person-none';
      li.textContent = none(q.trim());
      list.replaceChildren(li);
    } else {
      list.replaceChildren(...shown.map((m, i) => {
        const li = document.createElement('li');
        li.id = `${list.id}-${i}`;
        li.setAttribute('role', 'option');
        li.setAttribute('aria-selected', 'false');
        li.dataset.account = String(m.id);
        const name = document.createElement('span');
        name.className = 'person-name';
        name.textContent = m.name;
        li.append(name);
        if (m.email) {
          const email = document.createElement('span');
          email.className = 'person-email';
          email.textContent = m.email;
          li.append(email);
        }
        // mousedown, not click: picking mustn't blur the input first, which closes the list.
        li.addEventListener('mousedown', (e) => {
          e.preventDefault();
          choose(i);
        });
        li.addEventListener('mousemove', () => active !== i && setActive(i));
        return li;
      }));
    }
    list.hidden = false;
    input.setAttribute('aria-expanded', 'true');
  };

  let typed = false;
  input.addEventListener('input', () => {
    if (!typed) {
      typed = true;
      onType?.();
    }
    show();
  });
  input.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      if (list.hidden) show();
      if (!shown.length) return;
      e.preventDefault();
      const step = e.key === 'ArrowDown' ? 1 : -1;
      setActive((active + step + shown.length) % shown.length);
    } else if (e.key === 'Enter') {
      if (list.hidden || !shown.length) return;
      e.preventDefault();
      choose(active >= 0 ? active : 0);
    } else if (e.key === 'Escape' && !list.hidden) {
      e.preventDefault();
      close();
    }
  });
  input.addEventListener('blur', close);
  return { refresh: () => document.activeElement === input && input.value.trim() && show() };
}
