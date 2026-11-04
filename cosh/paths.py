"""Path scope: which chromium/src files the review metrics cover.

Rules come from config/paths.txt (see the comments there). Every review
comment is placed on one file:

- An inline comment is on its own file.
- A patchset-level or commit-message comment (Gerrit paths starting with "/")
  goes to the CL's *anchor*: the file with the most inline comments on the CL,
  from anyone, owner replies included (ties: the alphabetically first path).
- A comment on a CL with no inline comments at all can't be placed. It is
  outside the scope and shows as its own area, UNPLACED. In a 20k-CL sample
  that was about 10% of human review comments (68% inline, 22% placed via the
  anchor).

We don't fetch CL file lists, so the anchor stands in for "what the CL touches".
"""

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATHS_FILE = os.path.join(ROOT, "config", "paths.txt")

UNPLACED = "(no file)"     # area of comments that can't be placed on a file
ROOT_FILES = "(top-level files)"


def is_file(path):
    """False for Gerrit's pseudo-paths: /PATCHSET_LEVEL, /COMMIT_MSG, /MERGE_LIST."""
    return bool(path) and not path.startswith("/")


class PathScope:
    def __init__(self, rules, areas=()):
        """rules: [(prefix, included)]; areas: chart-only prefixes that are
        top-level rows of the web UI's directory tree (e.g. third_party/blink/)."""
        self.rules = sorted(rules, key=lambda r: -len(r[0]))
        self.areas = sorted(set(areas), key=len, reverse=True)

    def includes(self, path):
        """Whether a placed file path is in scope. None (unplaced) never is."""
        if path is None:
            return False
        for prefix, included in self.rules:
            if path.startswith(prefix):
                return included
        return True

    def area(self, path):
        """The top-level row of the directory tree a placed path is under:
        the longest matching `area` prefix, else its top-level directory
        (None -> UNPLACED, a file at the top -> ROOT_FILES). Include and exclude
        rules don't make areas: a re-included directory stays inside its
        parent, which is then partly included."""
        if path is None:
            return UNPLACED
        for prefix in self.areas:
            if path.startswith(prefix):
                return prefix
        top, sep, _ = path.partition("/")
        return top + "/" if sep else ROOT_FILES

    def describe(self):
        """Rules for the summaries' metadata, longest prefix first."""
        return [{"prefix": p, "included": inc} for p, inc in self.rules]


def parse_rules(text):
    rules, areas = [], []
    for n, line in enumerate(text.splitlines(), 1):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        kind, _, prefix = line.partition(" ")
        prefix = prefix.strip()
        if kind not in ("include", "exclude", "area") or not prefix.endswith("/"):
            raise ValueError(f"paths.txt line {n}: expected 'include|exclude|area <dir>/', got {line!r}")
        if kind == "area":
            areas.append(prefix)
        else:
            rules.append((prefix, kind == "include"))
    return PathScope(rules, areas)


def load_scope(path=PATHS_FILE):
    with open(path) as f:
        return parse_rules(f.read())


def anchor(inline_counts):
    """The CL's anchor file from {file: inline comment count}, or None."""
    files = [(-n, p) for p, n in inline_counts.items() if is_file(p) and n > 0]
    return min(files)[1] if files else None


def place(path, cl_anchor):
    """The file a comment is credited to (None if it can't be placed)."""
    return path if is_file(path) else cl_anchor


def directory(placed):
    """The directory ("a/b/") of a placed file; UNPLACED for None and
    ROOT_FILES for a file at the top of the tree."""
    if placed is None:
        return UNPLACED
    head, sep, _ = placed.rpartition("/")
    return head + "/" if sep else ROOT_FILES


def parent_dir(d):
    """'a/b/c/' -> 'a/b/'; a top-level directory has no parent (None)."""
    head, sep, _ = d.rstrip("/").rpartition("/")
    return head + "/" if sep else None


DIR_LIMIT = 10_000   # directories kept in area_weekly.json (see dir_tree)


def dir_tree(totals, scope, limit=DIR_LIMIT):
    """The directory tree the web UI drills into.

    totals: {directory: comments} (directories as from directory()).
    Roots are the areas (scope.area: `area` prefixes, else top-level
    directories, plus UNPLACED and ROOT_FILES). Below a root, the `limit`
    directories with the most comments are kept, with their ancestors up to
    the root, so the tree is connected. Every include/exclude rule directory
    is kept too, so each node's own bucket is wholly in or out of scope. A
    directory that isn't kept is counted in its
    nearest kept ancestor (its "rest" bucket), so children always sum to their
    parent. Over 2025-W45..2026-W44, 10,312 directories had comments, so a
    limit of 10,000 keeps 99.9% of comments in their own directory.

    Returns (nodes, bucket): nodes is [(path, parent path or None)], parents
    before children; bucket(directory) gives the kept node a directory's
    comments count in."""
    pseudo = {UNPLACED, ROOT_FILES}

    def root(d):
        return d if d in pseudo else scope.area(d)

    real = [d for d in totals if d not in pseudo]
    kept = set(sorted(real, key=lambda d: (-totals[d], d))[:limit])
    kept |= {d for d in totals if d in pseudo}
    kept |= {root(d) for d in real}
    kept |= {p for p, _ in scope.rules}
    for d in list(kept):
        r = root(d)
        while d != r and d not in pseudo:
            d = parent_dir(d)
            kept.add(d)

    def bucket(d):
        r = root(d)
        while d not in kept and d != r:
            d = parent_dir(d)
        return d

    def parent(d):
        return None if d in pseudo or d == root(d) else parent_dir(d)

    nodes = sorted(((d, parent(d)) for d in kept), key=lambda n: (n[0].count("/"), n[0]))
    return nodes, bucket
