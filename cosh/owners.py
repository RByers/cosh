"""Chromium's OWNERS files at one commit, read from the local clone
(offline; docs/review-load.md, "OWNERS").

An OWNERS file lists the people who may approve changes to its directory
and everything below, one address per line. `file://path` (or `include
path`) pulls in another file's owners, `set noparent` stops inheriting from
the directories above, `*` lets anyone approve, and `per-file` lines give
owners for some files only. Per-file rules are not read: a directory's
owners here are those of every file in it.
"""

import os
import re
import subprocess

from . import commits as C

EMAIL = re.compile(r"[\w.+-]+@[\w.-]+")
NAME = re.compile(r"(^|/)[^/]*OWNERS[^/]*$")


def read(repo, rev):
    """{path: text} of the OWNERS files (and the files they may include,
    such as FOO_OWNERS) in `rev`'s tree."""
    names = []
    # Streamed: the tree has about 500k paths, and only the OWNERS files are kept.
    with subprocess.Popen(["git", "--git-dir", repo, "ls-tree", "-r", "--name-only", "-z", rev],
                          stdout=subprocess.PIPE, env=C.ENV) as p:
        rest = b""
        for chunk in iter(lambda: p.stdout.read(1 << 20), b""):
            *done, rest = (rest + chunk).split(b"\0")
            names += [n for n in (x.decode("utf-8", "replace") for x in done if b"OWNERS" in x) if NAME.search(n)]
    if p.returncode:
        raise subprocess.CalledProcessError(p.returncode, p.args)
    out = subprocess.run(["git", "--git-dir", repo, "cat-file", "--batch"], stdout=subprocess.PIPE, env=C.ENV, check=True,
                         input="".join(f"{rev}:{n}\n" for n in names).encode()).stdout
    files, pos = {}, 0
    for n in names:
        nl = out.index(b"\n", pos)
        head = out[pos:nl].split()
        if head[-1] == b"missing":
            pos = nl + 1
            continue
        size = int(head[2])
        files[n] = out[nl + 1:nl + 1 + size].decode("utf-8", "replace")
        pos = nl + 1 + size + 1
    return files


class Owners:
    """The owners of each directory, from {path: text}."""

    def __init__(self, files):
        self.files = files
        # directory ("" is the root, no trailing slash) -> (addresses, set noparent, anyone)
        self.direct = {os.path.dirname(n): self._parse(n, ()) for n in files if os.path.basename(n) == "OWNERS"}
        self._memo = {}

    def _parse(self, name, seen):
        own, noparent, anyone = set(), False, False
        for line in self.files.get(name, "").split("\n"):
            line = line.split("#")[0].strip()
            if not line or line.startswith("per-file"):
                continue
            if line == "set noparent":
                noparent = True
            elif line == "*":
                anyone = True
            elif line.startswith("file:") or line.startswith("include "):
                t = re.sub(r"^(file:|include\s+)", "", line).strip()
                t = t.lstrip("/") if t.startswith("/") else os.path.normpath(os.path.join(os.path.dirname(name), t))
                if t != name and t not in seen:
                    o, _, a = self._parse(t, seen + (name,))
                    own |= o
                    anyone = anyone or a
            elif EMAIL.fullmatch(line):
                own.add(line.lower())
        return own, noparent, anyone

    def of(self, d):
        """(addresses, anyone) that may approve a file in directory `d`
        ("a/b", "" for the root): its OWNERS file's and, unless one says
        `set noparent`, those of the directories above."""
        if d not in self._memo:
            own, noparent, anyone = self.direct.get(d, (frozenset(), False, False))
            if d and not noparent:
                up, a = self.of(os.path.dirname(d))
                own, anyone = own | up, anyone or a
            self._memo[d] = (frozenset(own), anyone)
        return self._memo[d]
