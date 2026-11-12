"""Check and query config/dataflow.json, the inventory of cosh's data flow.

  python3 scripts/dataflow.py check
      Verify the inventory against the repository: ids and references, that
      code and tracked files exist, that every committed data file and every
      file a page imports is listed. Exits 1 with the problems if not.

  python3 scripts/dataflow.py plan ID [ID ...] [--json]
      What to rerun, in order, when the sources or stores named have new
      data, and which files in git change as a result. For a new week of
      Gerrit data: `plan gerrit-rest gerrit-notedb`.

  python3 scripts/dataflow.py list [sources|stores|steps|pages]
      The ids, with one line each.

web/dataflow.html draws the same file (web/src/dataflow-graph.ts has the
same graph rules). Field meanings: docs/data-architecture.md.
"""
import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "config", "dataflow.json")

TIERS = ("raw", "labels", "derived", "analysis", "published", "config")
REFRESHES = ("routine", "optional", "one-off", "analysis", "automatic")
# Directories where every committed file must belong to a store.
DATA_DIRS = ("summaries/", "data/public/", "config/")


def load(path=PATH):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class Graph:
    """Nodes by id and the flow edges: input -> step, step -> output,
    store -> page. A step that reads its own output (a resumable step) is
    only an edge to it, so resuming is not a loop."""

    def __init__(self, d):
        self.problems = []
        self.nodes = {}
        self.kind = {}
        groups = {g["id"] for g in d["groups"]}
        for kind in ("sources", "stores", "steps", "pages"):
            for item in d[kind]:
                if item["id"] in self.nodes:
                    self.problems.append(f"duplicate id {item['id']}")
                if item.get("group") not in groups:
                    self.problems.append(f"{item['id']}: unknown group {item.get('group')}")
                self.nodes[item["id"]] = item
                self.kind[item["id"]] = kind[:-1]
        self.out = {i: [] for i in self.nodes}
        self.inn = {i: [] for i in self.nodes}
        for s in d["steps"]:
            for i in s["inputs"]:
                if i not in s["outputs"]:
                    self._edge(i, s["id"], s["id"], i, ("source", "store"))
            for o in s["outputs"]:
                self._edge(s["id"], o, s["id"], o, ("store",))
        for p in d["pages"]:
            for r in p["reads"]:
                self._edge(r, p["id"], p["id"], r, ("store",))
        self.order = {i: n for n, i in enumerate(self.nodes)}

    def _edge(self, a, b, owner, other, want):
        if other not in self.nodes:
            self.problems.append(f"{owner}: unknown id {other}")
        elif self.kind[other] not in want:
            self.problems.append(f"{owner}: {other} is a {self.kind[other]}")
        else:
            self.out[a].append(b)
            self.inn[b].append(a)

    def reach(self, start, via=lambda i: True):
        seen = set(start)
        todo = list(seen)
        while todo:
            for nxt in self.out[todo.pop()]:
                if nxt not in seen and via(nxt):
                    seen.add(nxt)
                    todo.append(nxt)
        return seen

    def layers(self):
        """Longest path from a node with nothing upstream; edges that would
        close a cycle are ignored (and reported by `cycles`)."""
        depth, open_ = {}, set()
        self.cycles = []

        def visit(i):
            if i in depth:
                return depth[i]
            open_.add(i)
            d = 0
            for p in self.inn[i]:
                if p in open_:
                    self.cycles.append(f"{p} -> {i}")
                    continue
                d = max(d, visit(p) + 1)
            open_.discard(i)
            depth[i] = d
            return d

        sys.setrecursionlimit(10000)
        for i in self.nodes:
            visit(i)
        return depth


def plan(d, changed):
    """Steps to run in order, tracked stores to commit, and pages affected."""
    g = Graph(d)
    for c in changed:
        if c not in g.nodes:
            raise SystemExit(f"unknown id {c}; see `dataflow.py list`")

    def runs(optional):
        ok = ("routine", "automatic") + (("optional",) if optional else ())
        return lambda i: g.kind[i] != "step" or g.nodes[i]["refresh"] in ok

    everything = g.reach(changed, runs(True))
    sure = g.reach(changed, runs(False))
    depth = g.layers()
    ids = sorted((i for i in everything if i not in changed), key=lambda i: (depth[i], g.order[i]))
    of = lambda kind: [g.nodes[i] for i in ids if g.kind[i] == kind]  # noqa: E731
    return {
        "steps": [dict(id=s["id"], command=s["command"], refresh=s["refresh"],
                       after_optional=s["id"] not in sure, duration=s.get("duration"),
                       token_cost=s.get("token_cost"), approval=s.get("approval"))
                  for s in of("step")],
        "commit": [p for s in of("store") if s["tracked_in_git"] for p in s.get("git_paths", [s["path"]])],
        "pages": [p["path"] for p in of("page")],
    }


def tracked(root=ROOT):
    out = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True)
    return out.stdout.splitlines()


def matches(pattern, path):
    """A git_paths entry against a file: a glob, or a directory prefix."""
    return fnmatch.fnmatchcase(path, pattern) or (pattern.endswith("/") and path.startswith(pattern))


def page_imports(root=ROOT):
    """Repo-relative data files the pages' scripts import with ?url or ?raw."""
    found = set()
    src = os.path.join(root, "web", "src")
    for name in sorted(os.listdir(src)):
        if not name.endswith(".ts"):
            continue
        with open(os.path.join(src, name), encoding="utf-8") as f:
            for m in re.finditer(r"from '(\.\./\.\./[^'?]+)\?(?:url|raw)'", f.read()):
                found.add(os.path.normpath(os.path.join("web/src", m.group(1))))
    return found


def check(d, root=ROOT, files=None):
    """Problems with the inventory, as a list of sentences."""
    g = Graph(d)
    problems = list(g.problems)
    g.layers()
    problems += [f"cycle through {c}" for c in g.cycles]
    files = tracked(root) if files is None else files
    covered = set()
    for s in d["stores"]:
        if s["tier"] not in TIERS:
            problems.append(f"{s['id']}: unknown tier {s['tier']}")
        pats = s.get("git_paths", [s["path"]])
        hits = [f for f in files if any(matches(p, f) for p in pats)]
        if s["tracked_in_git"]:
            for p in pats:
                if not any(matches(p, f) for f in files):
                    problems.append(f"{s['id']}: no committed file matches {p}")
            covered.update(hits)
        elif hits and not s["path"].endswith("/"):
            problems.append(f"{s['id']}: marked untracked but {hits[0]} is committed")
    for f in files:
        if f.startswith(DATA_DIRS) and f not in covered:
            problems.append(f"{f}: committed data file that no store lists")
    for s in d["steps"]:
        if s["refresh"] not in REFRESHES:
            problems.append(f"{s['id']}: unknown refresh {s['refresh']}")
        if not s["purpose"] or not s["command"]:
            problems.append(f"{s['id']}: needs a purpose and a command")
        for c in s["code"]:
            if not os.path.exists(os.path.join(root, c)):
                problems.append(f"{s['id']}: code {c} doesn't exist")
    stores = {s["id"]: s for s in d["stores"]}
    read = set()
    for p in d["pages"]:
        if not os.path.exists(os.path.join(root, p["path"])):
            problems.append(f"{p['id']}: {p['path']} doesn't exist")
        for r in p["reads"]:
            if r in stores:
                read.update(stores[r].get("git_paths", [stores[r]["path"]]))
    listed = {p["path"] for p in d["pages"]}
    for name in sorted(os.listdir(os.path.join(root, "web"))):
        if name.endswith(".html") and f"web/{name}" not in listed:
            problems.append(f"web/{name}: page that the inventory doesn't list")
    for imp in sorted(page_imports(root)):
        if not any(matches(p, imp) for p in read):
            problems.append(f"{imp}: imported by a page script but in no page's reads")
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    p = sub.add_parser("plan")
    p.add_argument("ids", nargs="+")
    p.add_argument("--json", action="store_true")
    ls = sub.add_parser("list")
    ls.add_argument("kind", nargs="?", choices=("sources", "stores", "steps", "pages"))
    args = ap.parse_args(argv)
    d = load()
    if args.cmd == "check":
        problems = check(d)
        for line in problems:
            print(line)
        print(f"{len(d['sources'])} sources, {len(d['stores'])} stores, {len(d['steps'])} steps, "
              f"{len(d['pages'])} pages: {'ok' if not problems else f'{len(problems)} problems'}")
        return 1 if problems else 0
    if args.cmd == "list":
        for kind in ([args.kind] if args.kind else ["sources", "stores", "steps", "pages"]):
            for item in d[kind]:
                print(f"{kind[:-1]:6} {item['id']:45} {item['purpose']}")
        return 0
    result = plan(d, args.ids)
    if args.json:
        json.dump(result, sys.stdout, indent=2)
        print()
        return 0
    print("Steps, in order:")
    for s in result["steps"]:
        when = s["refresh"] + (", after an optional step" if s["after_optional"] and s["refresh"] != "optional" else "")
        cost = "; ".join(x for x in (s["duration"], s["token_cost"]) if x)
        print(f"  [{when}] {s['id']}: {s['command']}" + (f"\n      {cost}" if cost else "")
              + (f"\n      approval: {s['approval']}" if s["approval"] else ""))
    print("Files to commit:")
    for f in result["commit"]:
        print(f"  {f}")
    print("Pages that change: " + (", ".join(result["pages"]) or "none"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
