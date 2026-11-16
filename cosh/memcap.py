"""One memory budget for every heavy analysis run on argus.

Loading every CL and commit takes several GB per process. On 2026-11-14 two
sessions ran such loads at once, the box ran out of memory and the kernel
killed unrelated services (the site server, argus-health, the session
D-Bus). So heavy runs share one cgroup, the systemd user slice
`cosh-analysis.slice` (5 GB, no swap; the unit file is in argus-config,
`tools/cosh-analysis/`). When the runs in it together pass the limit, the
kernel kills the largest of them, which then just says "Killed", and
nothing else on the box suffers.

    from cosh import memcap; memcap.join()     # first thing in a script
    python3 -m cosh.memcap CMD [ARG ...]       # or wrap any command

Join before loading: memory already allocated stays charged to the old
cgroup. `cosh.review_feedback` joins by itself. `COSH_MEMCAP=off` skips
it. Without systemd (macOS) or without the slice's unit file it warns and
runs uncapped.

Heavy runs also take turns. Two runs that each fit under the cap can still
pass it together, and then the kernel kills one of them, so joining first
waits for the heavy-run lock (`hold`), an flock on a file in the user's
runtime directory that every session shares, and keeps it until the
process exits. A run that has to wait says whose run it is waiting for.
Its children (and a command run by `python3 -m cosh.memcap`) inherit the
lock through COSH_MEMCAP_HELD and don't wait for their own parent.
`cosh update` holds it around each step it runs.
"""

import contextlib
import fcntl
import os
import shutil
import subprocess
import sys
import tempfile
import time

SLICE = "cosh-analysis.slice"
HELD = "COSH_MEMCAP_HELD"   # set (to the holder's PID) while this process or a parent holds the lock

_held = None                # the open lock file while this process holds it


def lock_path():
    """One file for every session of this user, whatever its data dir."""
    if os.environ.get("COSH_MEMCAP_LOCK"):
        return os.environ["COSH_MEMCAP_LOCK"]
    run = f"/run/user/{os.getuid()}"
    if os.path.isdir(run):
        return os.path.join(run, "cosh-analysis.lock")
    return os.path.join(tempfile.gettempdir(), f"cosh-analysis-{os.getuid()}.lock")


def _disabled():
    return os.environ.get("COSH_MEMCAP", "").lower() in ("off", "0", "no")


def acquire():
    """Wait until no other heavy run holds the lock, then hold it until
    release() or exit. True if this process (or a parent) now holds it."""
    global _held
    if _disabled():
        return False
    if _held or os.environ.get(HELD):
        return True
    fh = open(lock_path(), "a+")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fh.seek(0)
        who = fh.read().strip() or "another run"
        print(f"memcap: waiting for the heavy run before this one to finish ({who})",
              file=sys.stderr, flush=True)
        t0 = time.time()
        fcntl.flock(fh, fcntl.LOCK_EX)
        print(f"memcap: waited {(time.time() - t0) / 60:.1f} min; starting", file=sys.stderr, flush=True)
    fh.seek(0)
    fh.truncate()
    fh.write(f"pid {os.getpid()} since {time.strftime('%H:%M')}: {' '.join(sys.argv)[:200]}\n")
    fh.flush()
    _held = fh
    os.environ[HELD] = str(os.getpid())
    return True


def release():
    """Let the next heavy run start (only the process that took the lock)."""
    global _held
    if _held:
        if os.environ.get(HELD) == str(os.getpid()):
            del os.environ[HELD]
        _held.truncate(0)
        _held.close()      # closing the file drops the flock
        _held = None


@contextlib.contextmanager
def hold():
    """`with memcap.hold():` around a heavy child process, which inherits it."""
    took = not _held and not os.environ.get(HELD)
    acquire()
    try:
        yield
    finally:
        if took:
            release()


def _cgroup():
    try:
        with open("/proc/self/cgroup") as f:
            return f.read().strip().rpartition("::")[2]
    except OSError:
        return ""


def _warn(why):
    print(f"memcap: running without the shared memory cap ({why})", file=sys.stderr, flush=True)
    return False


def join():
    """Wait for the heavy-run lock, then move this process into the shared
    slice. True when it is in it."""
    if _disabled():
        return False
    acquire()
    if f"/{SLICE}/" in _cgroup():
        return True
    if not shutil.which("busctl"):
        return _warn("no systemd here")
    # A transient scope around our own PID: the one way to change cgroup
    # without starting over (systemd-run would need a re-exec).
    unit = f"cosh-analysis-{os.getpid()}-{int(time.time())}.scope"
    r = subprocess.run(
        ["busctl", "--user", "call", "org.freedesktop.systemd1", "/org/freedesktop/systemd1",
         "org.freedesktop.systemd1.Manager", "StartTransientUnit", "ssa(sv)a(sa(sv))",
         unit, "fail", "2", "PIDs", "au", "1", str(os.getpid()), "Slice", "s", SLICE, "0"],
        capture_output=True, text=True)
    if r.returncode:
        return _warn(r.stderr.strip() or "busctl failed")
    for _ in range(50):  # the move is a queued job
        cg = _cgroup()
        if f"/{SLICE}/" in cg:
            break
        time.sleep(0.02)
    else:
        return _warn("systemd did not move the process")
    try:
        with open(os.path.join("/sys/fs/cgroup" + os.path.dirname(cg), "memory.max")) as f:
            if f.read().strip() == "max":
                return _warn(f"{SLICE} has no limit; is its unit file installed?")
    except OSError:
        pass
    return True


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        sys.exit("usage: python3 -m cosh.memcap CMD [ARG ...]")
    join()
    if _held:
        os.set_inheritable(_held.fileno(), True)   # the command keeps the lock
    os.execvp(argv[0], argv)


if __name__ == "__main__":
    main()
