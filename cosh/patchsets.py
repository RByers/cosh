"""Patch-set commits of reviewed CLs, fetched over git with their file contents.

Every patch set of a Gerrit change is a commit at refs/changes/NN/N/<ps>. We
fetch them into data/private/git/chromium-patchsets.git as
refs/patchsets/<N>/<ps>. That repo borrows chromium/src `main` from the shared
clone (~/projects/shared/chromium) through git alternates, so `main`'s tip goes
out as the "have" and the server sends commits, trees and the blobs that never
landed. Measured 2026-11-07 (docs/plan.md): 72 s per 1,000 CLs.

Load rules (CLAUDE.md): one fetch at a time under the extract lock, at least
1 s between fetches, glob refspecs per CL (never ls-remote), no blob fetches
by id, GIT_NO_LAZY_FETCH=1.

The server excludes only what is in each patch set's parent tree, so it also
re-sends blobs and trees that landed on `main` later. `repack --geometric -l`
drops those copies (they stay in the shared clone, so nothing is lost) and
runs every few GB so the disk doesn't fill.
"""

import os
import shutil
import sqlite3
import subprocess
import sys
import time

from . import store
from .contact import git_config, git_env

GIT_URL = "https://chromium.googlesource.com/chromium/src.git"
SHARED_OBJECTS = os.path.expanduser("~/projects/shared/chromium/objects")
DONE_FILE = "cosh-fetched.txt"  # CLs fetched, including any that had no refs

REPO_CONFIG = {
    "gc.auto": "0",
    "maintenance.auto": "false",
    "log.mailmap": "false",
    "core.logAllRefUpdates": "false",
    # Our own refs make no useful haves (main's tip covers each parent) and
    # with millions of them the post-fetch connectivity walk would dominate.
    # Hidden, the check still walks every new object down to main.
    "fetch.hideRefs": "refs/patchsets/",
}


def default_repo():
    return os.path.join(store.DATA_DIR, "git", "chromium-patchsets.git")


def git(git_dir, *args, input=None, check=True, network=False):
    extra = git_config() if network else []
    env = {**os.environ, "GIT_NO_LAZY_FETCH": "1", **(git_env() if network else {})}
    return subprocess.run(["git", "-C", git_dir, *extra, *args], input=input, text=True,
                          capture_output=True, check=check, env=env)


def init_repo(git_dir):
    if not os.path.isdir(git_dir):
        os.makedirs(os.path.dirname(git_dir), exist_ok=True)
        subprocess.run(["git", "init", "-q", "--bare", "--ref-format=reftable", git_dir], check=True)
    alt = os.path.join(git_dir, "objects", "info", "alternates")
    if not os.path.exists(alt):
        with open(alt, "w") as f:
            f.write(SHARED_OBJECTS + "\n")
    for k, v in REPO_CONFIG.items():
        git(git_dir, "config", k, v)
    return git_dir


def refspecs(n):
    nn = f"{n % 100:02d}"
    return f"+refs/changes/{nn}/{n}/*:refs/patchsets/{n}/*\n^refs/changes/{nn}/{n}/meta\n"


def reviewed_cls(derived_path, project="chromium/src", branch="main"):
    """[(change_number, patchsets)] for CLs with a comment from a human other
    than the owner, newest first (closed, else last updated)."""
    db = sqlite3.connect(f"file:{derived_path}?mode=ro", uri=True)
    return db.execute(
        """SELECT ch.change_number, coalesce(ch.patchsets, 1) FROM changes ch
           WHERE ch.project = ? AND ch.branch = ? AND EXISTS (
             SELECT 1 FROM comments cm
             LEFT JOIN accounts a ON a.host = cm.host AND a.account_id = cm.account_id
             WHERE cm.host = ch.host AND cm.change_number = ch.change_number
               AND cm.account_id != ch.owner_account AND coalesce(a.is_bot, 0) = 0)
           ORDER BY coalesce(ch.closed_at, ch.updated_at) DESC, ch.change_number DESC""",
        (project, branch)).fetchall()


def batches(cls, max_cls=1000, max_ps=5000):
    """Split [(n, patchsets)] into fetches of at most max_cls CLs and max_ps
    patch sets (a CL bigger than max_ps goes alone)."""
    out, cur, ps = [], [], 0
    for n, p in cls:
        if cur and (len(cur) >= max_cls or ps + p > max_ps):
            out.append(cur)
            cur, ps = [], 0
        cur.append((n, p))
        ps += p
    if cur:
        out.append(cur)
    return out


def fetched(git_dir):
    done = set()
    path = os.path.join(git_dir, DONE_FILE)
    if os.path.exists(path):
        done.update(int(x) for x in open(path).read().split())
    refs = git(git_dir, "for-each-ref", "--format=%(refname)", "refs/patchsets/").stdout
    done.update(int(r.split("/")[2]) for r in refs.split())
    return done


def _pack_bytes(git_dir):
    d = os.path.join(git_dir, "objects", "pack")
    return sum(os.path.getsize(os.path.join(d, f)) for f in os.listdir(d) if f.endswith(".pack"))


def fetch_batch(git_dir, cls, retries=4):
    """One git fetch for the batch. On failure, back off and retry; after two
    failures split the batch in half. Returns seconds taken."""
    t0 = time.time()
    for attempt in range(retries + 1):
        p = git(git_dir, "-c", "protocol.version=2", "fetch", "--quiet", "--no-tags",
                "--no-write-fetch-head", "--stdin", GIT_URL,
                input="".join(refspecs(n) for n, _ in cls), check=False, network=True)
        if p.returncode == 0:
            with open(os.path.join(git_dir, DONE_FILE), "a") as f:
                f.write("".join(f"{n}\n" for n, _ in cls))
            return time.time() - t0
        err = p.stderr.strip().replace("\n", " | ")[:300]
        if attempt == retries:
            raise RuntimeError(f"git fetch failed: {err}")
        if attempt >= 1 and len(cls) > 1:
            print(f"  fetch failed twice ({err}); splitting the batch", file=sys.stderr, flush=True)
            h = len(cls) // 2
            fetch_batch(git_dir, cls[:h], retries)
            time.sleep(2)
            fetch_batch(git_dir, cls[h:], retries)
            return time.time() - t0
        delay = 60 * 2 ** attempt
        print(f"  fetch failed ({err}); backing off {delay}s", file=sys.stderr, flush=True)
        time.sleep(delay)
    raise AssertionError("unreachable")


def repack(git_dir):
    """Lossless: roll up packs geometrically and drop objects the shared
    clone already holds (-l). Never prunes."""
    t0 = time.time()
    git(git_dir, "-c", "pack.threads=4", "repack", "--geometric=2", "-d", "-l", "-q")
    return time.time() - t0


def run(go=False, derived_path=None, git_dir=None, interval=2.0, max_cls=1000, max_ps=5000,
        repack_bytes=8e9, min_free=25e9, max_batches=None):
    derived_path = derived_path or os.path.join(store.DATA_DIR, "derived.sqlite")
    git_dir = git_dir or default_repo()
    cls = reviewed_cls(derived_path)
    done = fetched(git_dir) if os.path.isdir(git_dir) else set()
    todo = [c for c in cls if c[0] not in done]
    plan = batches(todo, max_cls, max_ps)
    print(f"reviewed CLs {len(cls):,} ({sum(p for _, p in cls):,} patch sets); "
          f"already fetched {len(cls) - len(todo):,}; to fetch {len(todo):,} CLs "
          f"({sum(p for _, p in todo):,} patch sets) in {len(plan):,} fetches", flush=True)
    if not go:
        return
    init_repo(git_dir)
    since_repack, t_start, ps_done = 0, time.time(), 0
    for i, b in enumerate(plan[:max_batches] if max_batches else plan):
        if i:
            time.sleep(interval)
        before = _pack_bytes(git_dir)
        secs = fetch_batch(git_dir, b)
        got = _pack_bytes(git_dir) - before
        since_repack += got
        ps_done += sum(p for _, p in b)
        rate = ps_done / (time.time() - t_start)
        left = sum(p for bb in plan[i + 1:] for _, p in bb) / rate / 3600 if rate else 0
        print(f"{time.strftime('%H:%M:%S')} fetch {i + 1}/{len(plan)}: {len(b)} CLs, "
              f"{sum(p for _, p in b)} patch sets, {secs:.0f}s, {got / 1e6:.0f} MB "
              f"(CLs {b[0][0]}..{b[-1][0]}); ~{left:.1f} h left", flush=True)
        free = shutil.disk_usage(git_dir).free
        if since_repack >= repack_bytes or free < min_free:
            print(f"  repacking ({since_repack / 1e9:.1f} GB since last, "
                  f"{free / 1e9:.0f} GB free) ...", flush=True)
            s = repack(git_dir)
            since_repack = 0
            free = shutil.disk_usage(git_dir).free
            print(f"  repacked in {s:.0f}s; packs {_pack_bytes(git_dir) / 1e9:.2f} GB, "
                  f"{free / 1e9:.0f} GB free", flush=True)
            if free < min_free:
                raise SystemExit(f"stopping: only {free / 1e9:.0f} GB free")
    s = repack(git_dir)
    print(f"done; final repack {s:.0f}s, packs {_pack_bytes(git_dir) / 1e9:.2f} GB", flush=True)
