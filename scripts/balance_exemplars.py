"""Private: named examples of each activity pattern and trajectory
(docs/balance-person.md, "Cluster exemplars").

Reads data/private/balance_clusters/people.json (scripts/balance_clusters.py)
and writes one HTML page naming a few clear examples per pattern and per
trajectory, to make the aggregate clusters concrete. PRIVATE: never
published on the site; share only as a private claude.ai artifact.

  COSH_DATA_DIR=<main>/data/private python3 scripts/balance_exemplars.py [--per 3] [--out FILE]
"""

import argparse
import html
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cosh import store  # noqa: E402
from balance_person import CSS  # noqa: E402

RECENT = ["2025H1", "2025H2", "2026H1", "2026H2"]


def activity(h):
    raw = h.get("raw") or {}
    return (raw.get("commits") or 0) + (raw.get("approvals") or 0)


def pick_patterns(people, per):
    """Per pattern: people in it for at least 3 of the last 4 half-years,
    ranked by how many, then by median activity (clear, typical examples,
    not the extremes: the middle of the activity range is preferred)."""
    cands = {}
    for pid, r in people.items():
        hs = [r["halves"].get(k) for k in RECENT]
        names = Counter(h["git_cluster"] for h in hs if h and h.get("git_cluster"))
        if not names:
            continue
        name, n = names.most_common(1)[0]
        if n >= 3:
            act = sorted(activity(h) for h in hs if h)
            cands.setdefault(name, []).append((n, act[len(act) // 2], pid))
    out = {}
    for name, xs in cands.items():
        xs.sort(key=lambda t: (-t[0], t[1]))
        top = [x for x in xs if x[0] == xs[0][0]] or xs
        mid = len(top) // 2
        out[name] = (len(xs), [pid for _, _, pid in top[max(0, mid - per // 2): max(0, mid - per // 2) + per]])
    return out


def pick_trajectories(people, per):
    """Per trajectory: those with the longest active record, typical activity."""
    by = {}
    for pid, r in people.items():
        t = r.get("trajectory")
        if t:
            n = sum(1 for h in r["halves"].values() if h.get("git_cluster"))
            by.setdefault(t, []).append((n, pid))
    out = {}
    for t, xs in by.items():
        xs.sort(key=lambda x: -x[0])
        out[t] = (len(xs), [pid for _, pid in xs[:per]])
    return out


def strip(r, idx):
    cells = []
    for k, h in sorted(r["halves"].items()):
        if k < "2017H1":
            continue
        c = h.get("git_cluster")
        cls = f"c{idx[c]}" if c in idx else "gap"
        title = f"{k}: {c or 'not active'}"
        cells.append(f'<div class="strip-cell {cls}" title="{html.escape(title)}"><span>{html.escape(k[2:])}</span></div>')
    return f'<div class="strip">{"".join(cells)}</div>'


def person_block(pid, r, idx):
    recent = [r["halves"].get(k) or {} for k in RECENT]
    commits = sum((h.get("raw") or {}).get("commits") or 0 for h in recent)
    approvals = sum((h.get("raw") or {}).get("approvals") or 0 for h in recent)
    return (f'<div class="ex"><h3>{html.escape(pid)}</h3>'
            f'<p class="note">{html.escape(r.get("trajectory") or "no trajectory")} · 2025–26: {commits:,} commits, '
            f'{approvals:,} approvals</p>{strip(r, idx)}</div>')


def render(people, patterns, trajectories, names):
    idx = {n: i for i, n in enumerate(sorted(names))}
    key = "".join(f'<span><i class="c{idx[n]}"></i>{html.escape(n)}</span>' for n in sorted(names))
    pat = "".join(
        f'<section><h2>{html.escape(name)}</h2><p class="note">{n:,} people fit this pattern in most of 2025–26; '
        f'typical examples:</p><div class="exs">{"".join(person_block(p, people[p], idx) for p in ps)}</div></section>'
        for name, (n, ps) in sorted(patterns.items()))
    tra = "".join(
        f'<section><h2>{html.escape(t)}</h2><p class="note">{n:,} people with this trajectory; examples with the '
        f'longest records:</p><div class="exs">{"".join(person_block(p, people[p], idx) for p in ps)}</div></section>'
        for t, (n, ps) in sorted(trajectories.items(), key=lambda kv: -kv[1][0]))
    return f"""<title>Chromium activity patterns</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;600&family=Source+Serif+4:opsz,wght@8..60,600&display=swap">
<style>{CSS}
.exs {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 20rem), 1fr)); gap: 12px; }}
.ex {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px; display: grid; gap: 6px; min-width: 0; }}
.ex h3 {{ font-family: var(--font-data); font-weight: 500; overflow-wrap: anywhere; }}
</style>
<main>
  <header style="display:grid;gap:10px">
    <p class="note">Chromium review balance · activity patterns</p>
    <h1>Who fits each pattern</h1>
    <div class="private"><strong>Private.</strong> This page names people as examples of activity patterns found by
      clustering everyone's git activity (docs/balance-clusters.md). Patterns describe what someone did in each
      half-year, scored against everyone active then; they are not judgements, and this page is not for sharing.</div>
    <div class="legend">{key}</div>
  </header>
  <h2>Patterns in 2025–26</h2>
  {pat}
  <h2>Trajectories since 2017</h2>
  {tra}
</main>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per", type=int, default=3)
    ap.add_argument("--out", default=os.path.join(store.DATA_DIR, "balance_people", "exemplars.html"))
    a = ap.parse_args()
    people = json.load(open(os.path.join(store.DATA_DIR, "balance_clusters", "people.json")))
    names = json.load(open(os.path.join(store.DATA_DIR, "balance_clusters", "clusters.json")))["git_model"]["names"]
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    open(a.out, "w").write(render(people, pick_patterns(people, a.per), pick_trajectories(people, a.per), names))
    print(f"wrote {a.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
