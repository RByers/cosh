"""Sample entries of every store in config/dataflow.json, for the data flow page.

  python3 scripts/dataflow_samples.py [--out config/dataflow-samples.json]

Writes five sample entries of each store: rows of each database table,
lines of a text file, rows of a CSV, entries of a JSON file, files of a
directory, refs or commits of a git repo. web/dataflow.html shows them in a
popup, with the column meanings kept in the inventory (`columns` on a
table or a single-file store). Samples are spread over the store (evenly
spaced rowids, lines or files), not just its first five.

The output is committed and published, so the inventory says what may not
be shown: a store's or table's `withheld` (a reason; its rows are left out)
and a table's `redact` (columns whose values are left out). Long text is
cut to a few hundred characters and binary values become their size.
Free text from Gerrit and the bug tracker is untrusted: the page renders it
as text only, and this script never prints it.

Reads only local files: databases are opened read-only, git commands run
with GIT_NO_LAZY_FETCH=1, so it fetches nothing and is safe while an
extractor runs. Rerun it when a store's layout changes (and commit
config/dataflow-samples.json); the values going stale between runs is fine.
"""
import argparse
import csv
import glob
import json
import os
import sqlite3
import subprocess
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dataflow  # noqa: E402

ROOT = dataflow.ROOT
OUT = os.path.join(ROOT, "config", "dataflow-samples.json")
N = 5
MAX_TEXT = 240
MAIN_CHECKOUT = "/home/rbagent/projects/cosh"


def data_dir():
    """data/private: $COSH_DATA_DIR, else this checkout's, else the main checkout's."""
    if os.environ.get("COSH_DATA_DIR"):
        return os.environ["COSH_DATA_DIR"]
    for root in (ROOT, MAIN_CHECKOUT):
        if os.path.isdir(os.path.join(root, "data", "private", "notedb")):
            return os.path.join(root, "data", "private")
    return os.path.join(ROOT, "data", "private")


def local(path):
    """A store path on disk; an R2 prefix (r2:...) is its local folder (config/r2.json)."""
    if path.startswith("r2:"):
        with open(os.path.join(ROOT, "config", "r2.json")) as f:
            prefixes = json.load(f)["prefixes"]
        return os.path.join(data_dir(), prefixes[path[3:].rstrip("/")])
    if path.startswith("data/private/"):
        return os.path.join(data_dir(), path[len("data/private/"):])
    if path.startswith("~"):
        return os.path.expanduser(path)
    return os.path.join(ROOT, path)


def spread(items, n=N):
    """n items evenly spaced over a list, first and last included."""
    if len(items) <= n:
        return list(items)
    return [items[round(k * (len(items) - 1) / (n - 1))] for k in range(n)]


def cell(v):
    if isinstance(v, (bytes, memoryview)):
        return f"<{len(v):,} bytes>"
    if isinstance(v, int) and abs(v) > 2**53:
        return str(v)  # a 64-bit hash: JavaScript numbers would round it
    if isinstance(v, float):
        return float(f"{v:.6g}")
    if isinstance(v, str) and len(v) > MAX_TEXT:
        return v[:MAX_TEXT] + "…"
    return v


def compact(v):
    return cell(json.dumps(v, ensure_ascii=False, separators=(",", ": ")))


def qi(name):
    return '"' + name.replace('"', '""') + '"'


def sample_table(db, table, info):
    kind = db.execute("SELECT type, sql FROM sqlite_master WHERE name = ?", (table,)).fetchone()
    if not kind:
        return {"name": table, "kind": "rows", "missing": True, "columns": [], "rows": []}
    t = qi(table)
    cols = [r[1] for r in db.execute(f"PRAGMA table_info({t})")]
    part = {"name": table, "kind": "rows", "columns": cols, "rows": []}
    if info.get("withheld"):
        part["withheld"] = info["withheld"]
        return part
    rows = []
    rowid = kind[0] == "table" and "WITHOUT ROWID" not in (kind[1] or "").upper()
    if rowid:
        lo, hi = db.execute(f"SELECT min(rowid), max(rowid) FROM {t}").fetchone()
        seen = set()
        if lo is not None:
            for k in range(N):
                r = db.execute(f"SELECT rowid, * FROM {t} WHERE rowid >= ? ORDER BY rowid LIMIT 1",
                               (lo + (hi - lo) * k // (N - 1),)).fetchone()
                if r and r[0] not in seen:
                    seen.add(r[0])
                    rows.append(r[1:])
            # Sparse rowids (a bug id as the key) can land on one row twice.
            for r in db.execute(f"SELECT rowid, * FROM {t} ORDER BY rowid LIMIT {2 * N}"):
                if len(rows) < N and r[0] not in seen:
                    seen.add(r[0])
                    rows.append(r[1:])
    else:
        total = info.get("rows") if kind[0] == "table" else None
        if total and total > N:
            for k in range(N):
                r = db.execute(f"SELECT * FROM {t} LIMIT 1 OFFSET ?", ((total - 1) * k // (N - 1),)).fetchone()
                if r:
                    rows.append(r)
        else:
            rows = db.execute(f"SELECT * FROM {t} LIMIT {N}").fetchall()
    redact = set(info.get("redact", []))
    part["rows"] = [[None if v is None else "(withheld)" if c in redact else cell(v)
                     for c, v in zip(cols, r)] for r in rows]
    return part


def sample_db(path, tables):
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return [sample_table(db, t["name"], t) for t in tables]
    finally:
        db.close()


def sample_csv(path, name):
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))
    return {"name": name, "kind": "rows", "columns": rows[0] if rows else [],
            "rows": [[cell(v) for v in r] for r in spread(rows[1:])]}


def sample_lines(path, name):
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = [(i + 1, line.rstrip("\n")) for i, line in enumerate(f) if line.strip()]
    return {"name": name, "kind": "lines", "columns": ["line", "text"],
            "rows": [[i, cell(t)] for i, t in spread(lines)]}


def sample_json(path, name):
    with open(path, encoding="utf-8") as f:
        v = json.load(f)
    # Step into the biggest member while the top holds only a few, so the
    # sample shows the repeated entries rather than a handful of headers.
    where = ""
    while isinstance(v, (dict, list)) and len(v) < N:
        items = list(v.items()) if isinstance(v, dict) else list(enumerate(v))
        big = [(k, x) for k, x in items if isinstance(x, (dict, list)) and len(x) >= N]
        if not big:
            break
        k, v = max(big, key=lambda kx: len(kx[1]))
        where += f"[{json.dumps(k)}]" if isinstance(k, str) else f"[{k}]"
    if isinstance(v, dict):
        entries = [[where + f"[{json.dumps(k)}]", compact(x)] for k, x in spread(list(v.items()))]
    elif isinstance(v, list):
        entries = [[where + f"[{i}]", compact(x)] for i, x in spread(list(enumerate(v)))]
    else:
        entries = [[where or "(top)", compact(v)]]
    return {"name": name, "kind": "entries", "columns": ["at", "value"], "rows": entries}


def sample_file(path, name):
    if path.endswith(".csv"):
        return sample_csv(path, name)
    if path.endswith(".json"):
        return sample_json(path, name)
    if path.endswith(".sqlite"):
        return None
    return sample_lines(path, name)


def sample_dir(path, name):
    files = []
    for top, dirs, names in os.walk(path):
        dirs[:] = sorted(d for d in dirs if not d.endswith(".git"))
        for n in sorted(names):
            p = os.path.join(top, n)
            files.append((os.path.relpath(p, path), os.path.getsize(p)))
    files.sort()
    return {"name": name, "kind": "files", "columns": ["file", "bytes"], "total": len(files),
            "rows": [[f, s] for f, s in spread(files)]}


def git(repo, *args):
    env = dict(os.environ, GIT_NO_LAZY_FETCH="1")
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, check=True, env=env).stdout


def sample_git(path, name):
    refs = git(path, "for-each-ref", "--format=%(refname) %(objectname:short)").splitlines()
    if len(refs) > N:
        return {"name": name, "kind": "refs", "columns": ["ref", "object"], "total": len(refs),
                "rows": [r.split(" ", 1) for r in spread(refs)]}
    log = git(path, "log", "--first-parent", f"-{N}", "--format=%h%x00%cI%x00%s", "main")
    return {"name": name, "kind": "commits", "columns": ["commit", "landed", "subject"],
            "rows": [[cell(x) for x in line.split("\0")] for line in log.splitlines()]}


def sample_path(path, name):
    p = local(path)
    if not os.path.exists(p):
        return {"name": name, "kind": "files", "missing": True, "columns": [], "rows": []}
    if os.path.isdir(p):
        if os.path.exists(os.path.join(p, "HEAD")) and os.path.isdir(os.path.join(p, "objects")):
            return sample_git(p, name)
        return sample_dir(p, name)
    return sample_file(p, name)


def sample_store(s):
    if s.get("withheld"):
        return {"withheld": s["withheld"], "parts": []}
    parts = []
    paths = [p.strip() for p in s["path"].split(" + ")]
    tables = s.get("tables", [])
    db = s.get("database") or next((p for p in paths if p.endswith(".sqlite")), None)
    if tables and db:
        parts += sample_db(local(db), tables)
    elif tables:
        # A family of files: each table is one member (a glob takes its first match).
        base = os.path.dirname(s.get("git_paths", [s["path"]])[0].rstrip("/")) if not s["path"].endswith("/") else s["path"]
        for t in tables:
            hits = sorted(glob.glob(os.path.join(local(base), t["name"].replace("{recent,comments}", "recent"))))
            part = sample_file(hits[0], t["name"]) if hits else None
            if part:
                if t.get("withheld"):
                    part.update(rows=[], withheld=t["withheld"])
                parts.append(part)
    for p in paths if db or not tables else []:
        if p.endswith(".sqlite") or p == db:
            continue
        part = sample_path(p, None if len(paths) == 1 and not tables else p)
        if part:
            parts.append(part)
    return {"parts": parts}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args(argv)
    d = dataflow.load()
    out = {"generated": date.today().isoformat(), "stores": {}}
    for s in d["stores"]:
        try:
            out["stores"][s["id"]] = sample_store(s)
        except (OSError, sqlite3.Error, subprocess.CalledProcessError, ValueError) as e:
            print(f"{s['id']}: {type(e).__name__}", file=sys.stderr)
            out["stores"][s["id"]] = {"parts": [], "error": type(e).__name__}
    text = json.dumps(out, ensure_ascii=False, indent=1) + "\n"
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(text)
    # Counts only: the samples hold untrusted text.
    for sid, v in out["stores"].items():
        parts = ", ".join(f"{p['name'] or p['kind']}:{len(p['rows'])}" + ("!" if p.get("missing") else "")
                          for p in v["parts"])
        print(f"{sid}: {'withheld' if v.get('withheld') else parts}")
    print(f"{len(text):,} bytes to {os.path.relpath(args.out, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
