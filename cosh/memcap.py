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
cgroup. `review_feedback.load` joins by itself. `COSH_MEMCAP=off` skips
it. Without systemd (macOS) or without the slice's unit file it warns and
runs uncapped.
"""

import os
import shutil
import subprocess
import sys
import time

SLICE = "cosh-analysis.slice"


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
    """Move this process into the shared slice. True when it is in it."""
    if os.environ.get("COSH_MEMCAP", "").lower() in ("off", "0", "no"):
        return False
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
    os.execvp(argv[0], argv)


if __name__ == "__main__":
    main()
