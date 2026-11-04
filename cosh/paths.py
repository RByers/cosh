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
        """rules: [(prefix, included)]; areas: extra chart-only prefixes."""
        self.rules = sorted(rules, key=lambda r: -len(r[0]))
        self.areas = sorted({p for p, _ in rules} | set(areas), key=len, reverse=True)

    def includes(self, path):
        """Whether a placed file path is in scope. None (unplaced) never is."""
        if path is None:
            return False
        for prefix, included in self.rules:
            if path.startswith(prefix):
                return included
        return True

    def area(self, path):
        """The chart directory for a placed path (None -> UNPLACED)."""
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
