"""`python3 -m cosh update`: rerun what is downstream of new data, in order.

It reads config/dataflow.json, plans as `scripts/dataflow.py plan` does
(docs/data-architecture.md), and runs each planned step that has a `run`
command: the free, local steps (and with --with-optional the optional ones
that have one). Steps without a `run` (fetches, which need approval, and
model calls that cost Max usage) are listed for a person to run, with their
measured cost. It stops at the first failure and ends with the files to
commit.

  python3 -m cosh update                       # downstream of every source
  python3 -m cosh update --from gerrit         # after a new week was fetched
  python3 -m cosh update --from data/private/labels.sqlite --dry-run
"""

import argparse
import fcntl
import os
import subprocess
import sys
import time

from . import store

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _dataflow():
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import dataflow
    return dataflow


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 -m cosh update", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="changed", nargs="+", metavar="ID",
                    help="sources or stores with new data (default: every source)")
    ap.add_argument("--with-optional", action="store_true",
                    help="also run optional steps that have a run command")
    ap.add_argument("--dry-run", action="store_true", help="print the plan, run nothing")
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
    if a.dry_run:
        for s in todo:
            print(f"  would run {s['id']}: {s['run']}")
        return 0
    os.makedirs(store.DATA_DIR, exist_ok=True)
    with open(os.path.join(store.DATA_DIR, "update.lock"), "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("another `cosh update` is running")
        for n, s in enumerate(todo, 1):
            print(f"[{n}/{len(todo)}] {s['id']}: {s['run']}", flush=True)
            t0 = time.time()
            r = subprocess.run(s["run"], shell=True, cwd=ROOT)
            if r.returncode:
                left = ", ".join(x["id"] for x in todo[n:]) or "nothing"
                print(f"{s['id']} failed (exit {r.returncode}); not run: {left}", file=sys.stderr)
                return r.returncode
            print(f"  done in {time.time() - t0:.0f}s", flush=True)
    print("Commit what changed (and push; the Pages workflow publishes the site):")
    for f in p["commit"]:
        print(f"  {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
