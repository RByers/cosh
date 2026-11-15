"""`python3 -m cosh update`: rerun what is downstream of new data, in order.

It reads config/dataflow.json, plans as `scripts/dataflow.py plan` does
(docs/data-architecture.md), and runs each planned step that has a `run`
command: the free, local steps (and with --with-optional the optional ones
that have one). Steps without a `run` (fetches, which need approval, and
model calls that cost Max usage) are listed for a person to run, with their
measured cost. It stops at the first failure and ends with the files to
commit. It never uploads to R2 or pushes: that is deploying (docs/r2.md).

A step is skipped when nothing it depends on changed since it last ran:
its command, the content of its code (the step's `code` files and every
module and config file its processes read on the last run, which
cosh/steptrace records), the files of its input stores (sizes and
modification times; a git repo by its refs) and of its outputs here (a
missing or changed output runs it again). The record is
data/private/update-state.json. A step that reads an external data source
(not a model, whose answers the steps cache) always runs: that is a fetch.
--force runs every planned step; --record marks them as done without
running them (after running the steps by hand). Each run's time and peak
memory (the largest process's resident set) go in the record too.

  python3 -m cosh update                       # downstream of every source
  python3 -m cosh update --from gerrit         # after a new week was fetched
  python3 -m cosh update --from data/private/addressed.sqlite --dry-run
"""

import argparse
import fcntl
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import time

from . import store

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _dataflow():
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import dataflow
    return dataflow


STATE_FILE = "update-state.json"


def _paths(store_path):
    """The local files and directories a store's `path` names: ' + ' joins
    several, braces and globs expand, data/private/ is store.DATA_DIR. An
    r2: path has none."""
    out = []
    for p in store_path.split(" + "):
        p = p.strip()
        if p.startswith("r2:"):
            continue
        m = re.match(r"(.*)\{([^}]*)\}(.*)", p)
        alts = [m.group(1) + x + m.group(3) for x in m.group(2).split(",")] if m else [p]
        for a in alts:
            a = os.path.expanduser(a)
            if a.startswith("data/private/") or a == "data/private":
                a = os.path.join(store.DATA_DIR, a[len("data/private/"):])
            a = os.path.join(ROOT, a)
            hits = sorted(glob.glob(a)) if glob.has_magic(a) else [a]
            out.extend(hits or [a])
    return out


def _git_refs(d):
    """A git repo by its refs, not its objects: cheap however big it is."""
    out = []
    for f in ("HEAD", "packed-refs", "reftable/tables.list"):
        fp = os.path.join(d, f)
        if os.path.exists(fp):
            st = os.stat(fp)
            out.append((f, st.st_size, st.st_mtime_ns))
    for top, _, files in os.walk(os.path.join(d, "refs")):
        for f in files:
            st = os.stat(os.path.join(top, f))
            out.append((os.path.relpath(os.path.join(top, f), d), st.st_size, st.st_mtime_ns))
    return out


def _is_git(d):
    return os.path.isfile(os.path.join(d, "HEAD")) and os.path.isdir(os.path.join(d, "objects"))


def signature(path):
    """[(name, size, mtime_ns), ...] for a file or a directory tree; None if missing."""
    if not os.path.exists(path):
        return None
    if os.path.isfile(path):
        out = []
        for f in (path, path + "-wal"):    # an SQLite file's writes may sit in its WAL
            if os.path.exists(f):
                st = os.stat(f)
                out.append((os.path.basename(f), st.st_size, st.st_mtime_ns))
        return out
    if _is_git(path):
        return _git_refs(path)
    out = []
    for top, dirs, files in os.walk(path):
        for d in list(dirs):
            if _is_git(os.path.join(top, d)):
                dirs.remove(d)
                out.append((os.path.relpath(os.path.join(top, d), path), _git_refs(os.path.join(top, d))))
        dirs.sort()
        for f in sorted(files):
            st = os.stat(os.path.join(top, f))
            out.append((os.path.relpath(os.path.join(top, f), path), st.st_size, st.st_mtime_ns))
    return out


def _digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()[:20]


def _stores_sig(stores, ids):
    return _digest({i: [(p, signature(p)) for p in _paths(stores[i]["path"])]
                    for i in ids if i in stores})   # sources (not stores) have no local files


TRACER = os.path.join(ROOT, "cosh", "steptrace")


def _sha(rel):
    try:
        with open(os.path.join(ROOT, rel), "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return None


def _is_code(rel):
    """Files whose content is part of a step's code: Python under cosh/ and
    scripts/ (not the tracer), and config/."""
    return (rel.endswith(".py") and rel.split("/")[0] in ("cosh", "scripts")
            and not rel.startswith("cosh/steptrace/")) or rel.startswith("config/")


def code_snapshot():
    """{path: sha256} of every code and config file, taken before a step
    runs, so a file changed while it runs (main moving under it) counts as
    changed afterwards."""
    out = {}
    for top in ("cosh", "scripts", "config"):
        for d, dirs, files in os.walk(os.path.join(ROOT, top)):
            dirs[:] = sorted(x for x in dirs if x != "__pycache__")
            for f in sorted(files):
                rel = os.path.relpath(os.path.join(d, f), ROOT)
                if _is_code(rel):
                    out[rel] = _sha(rel)
    return out


def traced_files(path):
    """The code and config files a step's processes read (cosh/steptrace)."""
    try:
        with open(path, encoding="utf-8", errors="surrogateescape") as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        return set()
    out = set()
    for p in lines:
        rel = os.path.relpath(p, ROOT)
        if not rel.startswith("..") and _is_code(rel):
            out.add(rel)
    return out


def step_inputs_sig(d, step, code_files=None, hashes=None, stores_sig=None):
    """The step's command, the content of its code (its `code` list plus
    `code_files`, as `hashes` has them or as they are now) and its input
    stores' files (`stores_sig`, or as they are now)."""
    stores = {s["id"]: s for s in d["stores"]}
    if stores_sig is None:
        stores_sig = _stores_sig(stores, step.get("inputs", []))
    files = sorted(set(step.get("code", [])) | set(code_files or ()))
    code = []
    for c in files:
        h = hashes[c] if hashes and c in hashes else _sha(c)
        if h or c not in step.get("code", []):
            code.append((c, h))
    return _digest({"run": step["run"], "code": code,
                    "inputs": stores_sig})


def run_traced(cmd, trace):
    """Runs a step's shell command with cosh/steptrace on PYTHONPATH.
    (exit code, peak resident set of its largest process in KB, code files
    its processes read)."""
    try:
        os.remove(trace)
    except FileNotFoundError:
        pass
    env = dict(os.environ, COSH_STEP_TRACE=trace, COSH_STEP_TRACE_ROOT=ROOT,
               PYTHONPATH=os.pathsep.join([TRACER] + ([os.environ["PYTHONPATH"]] if os.environ.get("PYTHONPATH") else [])))
    p = subprocess.Popen(cmd, shell=True, cwd=ROOT, env=env)
    _, status, ru = os.wait4(p.pid, 0)
    p.returncode = os.waitstatus_to_exitcode(status)
    files = traced_files(trace)
    try:
        os.remove(trace)
    except FileNotFoundError:
        pass
    return p.returncode, ru.ru_maxrss, files


def step_outputs_sig(d, step):
    stores = {s["id"]: s for s in d["stores"]}
    return _stores_sig(stores, step.get("outputs", []))


def _load_state():
    try:
        with open(os.path.join(store.DATA_DIR, STATE_FILE)) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_state(state):
    path = os.path.join(store.DATA_DIR, STATE_FILE)
    with open(path + ".tmp", "w") as f:
        json.dump(state, f, indent=1, sort_keys=True)
    os.replace(path + ".tmp", path)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 -m cosh update", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="changed", nargs="+", metavar="ID",
                    help="sources or stores with new data (default: every source)")
    ap.add_argument("--with-optional", action="store_true",
                    help="also run optional steps that have a run command")
    ap.add_argument("--dry-run", action="store_true", help="print the plan, run nothing")
    ap.add_argument("--force", action="store_true",
                    help="run every planned step, even those whose inputs are unchanged")
    ap.add_argument("--record", action="store_true",
                    help="run nothing; record the planned steps as done with their inputs as they are now")
    a = ap.parse_args(argv)
    df = _dataflow()
    d = df.load()
    changed = a.changed or [s["id"] for s in d["sources"]]
    p = df.plan(d, changed)
    todo, manual = [], []
    for s in p["steps"]:
        auto = s["run"] and (s["refresh"] == "routine" or a.with_optional)
        (todo if auto else manual).append(s)
    print(f"update from {', '.join(changed)}: {len(todo)} steps to run, {len(manual)} by hand", flush=True)
    for s in manual:
        cost = "; ".join(x for x in (s["duration"], s["token_cost"]) if x)
        print(f"  by hand [{s['refresh']}] {s['id']}: {s['command']}" + (f" ({cost})" if cost else ""))
    steps = {s["id"]: s for s in d["steps"]}
    fetched = {s["id"] for s in d["sources"] if s.get("kind") != "model"}
    state = _load_state()

    def unchanged(s):
        """Whether the step can be skipped: its inputs signature, over the
        code files its last run read, is as recorded then."""
        full = steps[s["id"]]
        rec = state.get(s["id"], {})
        sig = step_inputs_sig(d, full, rec.get("code_files"))
        return (not a.force and not fetched & set(full.get("inputs", [])) and rec.get("inputs") == sig
                and rec.get("outputs") == step_outputs_sig(d, full))

    if a.dry_run:
        for s in todo:
            print(f"  would {'skip (unchanged)' if unchanged(s) else 'run'} {s['id']}: {s['run']}")
        return 0
    os.makedirs(store.DATA_DIR, exist_ok=True)
    with open(os.path.join(store.DATA_DIR, "update.lock"), "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("another `cosh update` is running")
        if a.record:
            for s in todo:
                full = steps[s["id"]]
                state[s["id"]] = {"inputs": step_inputs_sig(d, full),
                                  "outputs": step_outputs_sig(d, full), "at": store.now_iso()}
            _save_state(state)
            print(f"recorded {len(todo)} steps as done")
            return 0
        for n, s in enumerate(todo, 1):
            if unchanged(s):
                print(f"[{n}/{len(todo)}] {s['id']}: unchanged since {state[s['id']]['at']}, skipped",
                      flush=True)
                continue
            print(f"[{n}/{len(todo)}] {s['id']}: {s['run']}", flush=True)
            full = steps[s["id"]]
            snap = code_snapshot()
            stores = {x["id"]: x for x in d["stores"]}
            inputs = _stores_sig(stores, full.get("inputs", []))   # as the step found them
            t0 = time.time()
            code, rss, files = run_traced(s["run"], os.path.join(store.DATA_DIR, f"update-trace-{s['id']}.txt"))
            if code:
                left = ", ".join(x["id"] for x in todo[n:]) or "nothing"
                print(f"{s['id']} failed (exit {code}); not run: {left}", file=sys.stderr)
                return code
            secs = time.time() - t0
            if not files:      # nothing traced: count every code and config file
                files = set(snap)
            print(f"  done in {secs:.0f}s, peak memory {rss / 1024:,.0f} MB", flush=True)
            state[s["id"]] = {"inputs": step_inputs_sig(d, full, files, snap, inputs),
                              "outputs": step_outputs_sig(d, full), "code_files": sorted(files),
                              "at": store.now_iso(), "seconds": round(secs), "peak_rss_mb": round(rss / 1024)}
            _save_state(state)
    print("Commit what changed. To deploy, upload to R2 and then push main "
          "(python3 -m cosh.r2 publish; docs/r2.md, \"Deploying\"):")
    for f in p["commit"]:
        print(f"  {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
