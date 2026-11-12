"""Patch-set commits of reviewed CLs, fetched over git with their file contents.

Every patch set of a Gerrit change is a commit at refs/changes/NN/N/<ps>. We
fetch them into data/private/git/chromium-patchsets.git as
refs/patchsets/<N>/<ps>. That repo borrows chromium/src `main` from the shared
clone (~/projects/shared/chromium) through git alternates, so `main`'s tip goes
out as the "have" and the server sends commits, trees and the blobs that never
landed. Measured 2026-11-07 (docs/plan.md): 72 s per 1,000 CLs.

Load rules (CLAUDE.md): one fetch at a time (or the user-approved --jobs)
under the extract lock, backing off together on HTTP 429, at least
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
import threading
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
    # Parallel fetches (--jobs) take turns appending to the reftable stack;
    # wait for the lock rather than fail the fetch.
    "reftable.lockTimeout": "60000",
    # Local unpacking threads per fetch, so 8 parallel fetches stay polite on
    # a shared machine. `repack` sets its own.
    "pack.threads": "2",
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


# The approved range (CLAUDE.md, 2026-11-07): reviewed CLs closed (or, if
# open, last updated) since 2023-W26. derived.sqlite now reaches back to
# 2017, and patch sets of those older CLs are not approved, so a plain rerun
# must not select them. Fetching outside this range needs approval first.
APPROVED_SINCE = "2023-06-26"


def reviewed_cls(derived_path, project="chromium/src", branch="main", since=APPROVED_SINCE):
    """[(change_number, patchsets)] for CLs with a comment from a human other
    than the owner, closed (else last updated) on or after `since`, newest
    first."""
    db = sqlite3.connect(f"file:{derived_path}?mode=ro", uri=True)
    return db.execute(
        """SELECT ch.change_number, coalesce(ch.patchsets, 1) FROM changes ch
           WHERE ch.project = ? AND ch.branch = ? AND coalesce(ch.closed_at, ch.updated_at) >= ? AND EXISTS (
             SELECT 1 FROM comments cm
             LEFT JOIN accounts a ON a.host = cm.host AND a.account_id = cm.account_id
             WHERE cm.host = ch.host AND cm.change_number = ch.change_number
               AND cm.account_id != ch.owner_account AND coalesce(a.is_bot, 0) = 0)
           ORDER BY coalesce(ch.closed_at, ch.updated_at) DESC, ch.change_number DESC""",
        (project, branch, since)).fetchall()


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


_done_lock = threading.Lock()


def _pack_bytes(git_dir):
    d = os.path.join(git_dir, "objects", "pack")
    total = 0
    for f in os.listdir(d):
        if f.endswith(".pack"):
            try:
                total += os.path.getsize(os.path.join(d, f))
            except FileNotFoundError:  # renamed or removed meanwhile
                pass
    return total


def is_rate_limited(stderr):
    """googlesource's quota answer: HTTP 429, or RESOURCE_EXHAUSTED in-band."""
    return "HTTP 429" in stderr or "RESOURCE_EXHAUSTED" in stderr


class Throttle:
    """Shared by all workers, so the run as a whole backs off when
    googlesource rate-limits us, not just the worker that was refused.

    At most `limit` fetches run at once. A 429 drops `limit` by one and
    pauses every new fetch for `backoff` s (doubling while 429s keep coming,
    up to `max_backoff`). After `grow_after` s with no 429, `limit` grows by
    one again, up to `max_jobs`. So the run settles just under the server's
    limit."""

    def __init__(self, max_jobs, backoff=60.0, max_backoff=900.0, grow_after=600.0,
                 clock=time.monotonic):
        self.max_jobs = self.limit = max(1, max_jobs)
        self.backoff, self.max_backoff, self.grow_after = backoff, max_backoff, grow_after
        self.clock = clock
        self.active = 0
        self.pause_until = 0.0
        self.strikes = 0  # 429s since the last success
        self.last_change = clock()
        self.cond = threading.Condition()

    def acquire(self):
        with self.cond:
            while True:
                wait = self.pause_until - self.clock()
                if wait <= 0 and self.active < self.limit:
                    self.active += 1
                    return
                self.cond.wait(timeout=wait if wait > 0 else None)

    def release(self, rate_limited):
        with self.cond:
            self.active -= 1
            now = self.clock()
            if rate_limited:
                delay = min(self.max_backoff, self.backoff * 2 ** self.strikes)
                self.strikes += 1
                # One 429 often arrives for several fetches at once; drop the
                # limit once per pause, not once per refused fetch.
                if now >= self.pause_until:
                    self.limit = max(1, self.limit - 1)
                    self.last_change = now
                self.pause_until = max(self.pause_until, now + delay)
                print(f"  rate-limited; all workers pause {delay:.0f}s, "
                      f"now {self.limit} at once", file=sys.stderr, flush=True)
            else:
                self.strikes = 0
                if self.limit < self.max_jobs and now - self.last_change >= self.grow_after:
                    self.limit += 1
                    self.last_change = now
                    print(f"  no rate limits for {self.grow_after / 60:.0f} min; "
                          f"now {self.limit} at once", file=sys.stderr, flush=True)
            self.cond.notify_all()


class DeadlineThrottle(Throttle):
    """A Throttle whose ceiling drops to `after_jobs` once `deadline` (unix
    seconds) passes: e.g. the user's "6 at once until Monday, then 1"."""

    def __init__(self, max_jobs, deadline, after_jobs=1, wall=time.time, **kw):
        super().__init__(max_jobs, **kw)
        self.deadline, self.after_jobs, self.wall = deadline, max(1, after_jobs), wall

    def acquire(self):
        with self.cond:
            if self.deadline and self.wall() >= self.deadline and self.max_jobs > self.after_jobs:
                self.max_jobs = self.after_jobs
                self.limit = min(self.limit, self.after_jobs)
                print(f"  past the parallel deadline; now {self.limit} at once",
                      file=sys.stderr, flush=True)
        super().acquire()


def fetch_batch(git_dir, cls, retries=4, throttle=None, max_rate_limited=20):
    """One git fetch for the batch. A rate-limited fetch goes back through
    the throttle (shared pause) and is retried as is. Other failures back
    off and retry; after two of those the batch is split in half. Returns
    seconds taken."""
    throttle = throttle or Throttle(1, backoff=60.0)
    t0 = time.time()
    attempt = limited = 0
    while True:
        throttle.acquire()
        p = None
        try:
            p = git(git_dir, "-c", "protocol.version=2", "fetch", "--quiet", "--no-tags",
                    "--no-write-fetch-head", "--stdin", GIT_URL,
                    input="".join(refspecs(n) for n, _ in cls), check=False, network=True)
        finally:
            throttle.release(p is not None and p.returncode != 0 and is_rate_limited(p.stderr))
        if p.returncode == 0:
            with _done_lock, open(os.path.join(git_dir, DONE_FILE), "a") as f:
                f.write("".join(f"{n}\n" for n, _ in cls))
            return time.time() - t0
        err = p.stderr.strip().replace("\n", " | ")[:300]
        if is_rate_limited(p.stderr):
            limited += 1
            if limited > max_rate_limited:
                raise RuntimeError(f"git fetch rate-limited {limited} times: {err}")
            continue
        if attempt == retries:
            raise RuntimeError(f"git fetch failed: {err}")
        if attempt >= 1 and len(cls) > 1:
            print(f"  fetch failed twice ({err}); splitting the batch", file=sys.stderr, flush=True)
            h = len(cls) // 2
            fetch_batch(git_dir, cls[:h], retries, throttle, max_rate_limited)
            time.sleep(2)
            fetch_batch(git_dir, cls[h:], retries, throttle, max_rate_limited)
            return time.time() - t0
        delay = 60 * 2 ** attempt
        print(f"  fetch failed ({err}); backing off {delay}s", file=sys.stderr, flush=True)
        time.sleep(delay)
        attempt += 1


def repack(git_dir):
    """Lossless: roll up packs geometrically and drop objects the shared
    clone already holds (-l). Never prunes."""
    t0 = time.time()
    # One thread: with 4, pack-objects reached 8 GB and aborted (exit 134)
    # on 65 GB of packs, 2026-11-07.
    p = git(git_dir, "-c", "pack.threads=1", "-c", "pack.windowMemory=1g",
            "-c", "pack.deltaCacheSize=128m", "repack", "--geometric=2", "-d", "-l", "-q",
            check=False)
    if p.returncode != 0:
        raise SystemExit(f"repack failed (exit {p.returncode}); old packs are untouched:\n"
                         f"{p.stderr.strip()[-2000:]}")
    return time.time() - t0


def run(go=False, derived_path=None, git_dir=None, interval=2.0, max_cls=1000, max_ps=5000,
        repack_bytes=8e9, min_free=25e9, max_batches=None, jobs=1, since=APPROVED_SINCE):
    """Fetch the plan with up to `jobs` workers sharing the repo (each waits
    `interval` between its own fetches; a shared Throttle lowers how many
    run at once when the server rate-limits us). When new packs pass `repack_bytes`
    or free space drops under `min_free`, workers finish their fetch and
    stop, the repo is repacked, and fetching continues."""
    derived_path = derived_path or os.path.join(store.DATA_DIR, "derived.sqlite")
    git_dir = git_dir or default_repo()
    cls = reviewed_cls(derived_path, since=since)
    done = fetched(git_dir) if os.path.isdir(git_dir) else set()
    todo = [c for c in cls if c[0] not in done]
    plan = batches(todo, max_cls, max_ps)
    print(f"reviewed CLs {len(cls):,} ({sum(p for _, p in cls):,} patch sets); "
          f"already fetched {len(cls) - len(todo):,}; to fetch {len(todo):,} CLs "
          f"({sum(p for _, p in todo):,} patch sets) in {len(plan):,} fetches"
          f"{f', {jobs} at a time' if jobs > 1 else ''}", flush=True)
    if not go:
        return
    init_repo(git_dir)
    work = plan[:max_batches] if max_batches else plan
    ps_total = sum(p for b in work for _, p in b)
    lock = threading.Lock()
    st = dict(next=0, ps=0, stop=None, error=None, base=_pack_bytes(git_dir))
    throttle = Throttle(jobs)
    t_start = time.time()

    def worker():
        first = True
        while True:
            with lock:
                if st["stop"] or st["next"] >= len(work):
                    return
                i = st["next"]
                st["next"] += 1
            if not first:
                time.sleep(interval)
            first = False
            b = work[i]
            try:
                secs = fetch_batch(git_dir, b, throttle=throttle)
            except Exception as e:  # leave the batch unfetched; a rerun retries it
                with lock:
                    st["error"] = st["error"] or f"fetch {i + 1} failed: {e}"
                    st["stop"] = "error"
                return
            with lock:
                st["ps"] += sum(p for _, p in b)
                rate = st["ps"] / (time.time() - t_start)
                grown = _pack_bytes(git_dir) - st["base"]
                free = shutil.disk_usage(git_dir).free
                print(f"{time.strftime('%H:%M:%S')} fetch {i + 1}/{len(work)}: {len(b)} CLs, "
                      f"{sum(p for _, p in b)} patch sets, {secs:.0f}s (CLs {b[0][0]}..{b[-1][0]}); "
                      f"{grown / 1e9:.1f} GB new, {free / 1e9:.0f} GB free; "
                      f"~{(ps_total - st['ps']) / rate / 3600:.1f} h left", flush=True)
                if (grown >= repack_bytes or free < min_free) and not st["stop"]:
                    st["stop"] = "repack"

    while st["next"] < len(work):
        threads = [threading.Thread(target=worker) for _ in range(max(1, jobs))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        if st["error"]:
            raise SystemExit(st["error"])
        if st["stop"] == "repack":
            print("  repacking ...", flush=True)
            s = repack(git_dir)
            free = shutil.disk_usage(git_dir).free
            print(f"  repacked in {s:.0f}s; packs {_pack_bytes(git_dir) / 1e9:.2f} GB, "
                  f"{free / 1e9:.0f} GB free", flush=True)
            if free < min_free:
                raise SystemExit(f"stopping: only {free / 1e9:.0f} GB free")
            st["stop"], st["base"] = None, _pack_bytes(git_dir)
    s = repack(git_dir)
    print(f"done; final repack {s:.0f}s, packs {_pack_bytes(git_dir) / 1e9:.2f} GB", flush=True)
