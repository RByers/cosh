"""Records which repository files a step's Python processes read.

`python3 -m cosh update` puts this directory on PYTHONPATH and names a file
in COSH_STEP_TRACE; Python's site module then imports this file at startup
(the user site is on by default). At exit it appends the paths of the
modules loaded and the files opened under the repository, so that `cosh
update` reruns the step when any of them changes (cosh/update.py). Without
COSH_STEP_TRACE it does nothing. A process that never imports it (python3
-I or -s, or not Python) leaves no trace, and `cosh update` then counts
every code and config file instead.
"""

import os
import sys

_out = os.environ.get("COSH_STEP_TRACE")
if _out:
    import atexit

    _root = os.path.join(os.environ.get("COSH_STEP_TRACE_ROOT")
                         or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "")
    _seen = set()

    def _hook(event, args):
        if event == "open" and args and isinstance(args[0], (str, bytes)):
            try:
                p = os.path.abspath(os.fsdecode(args[0]))
            except (TypeError, ValueError):
                return
            if p.startswith(_root):
                _seen.add(p)

    def _flush():
        for m in list(sys.modules.values()):
            f = getattr(m, "__file__", None)
            if isinstance(f, str) and os.path.abspath(f).startswith(_root):
                _seen.add(os.path.abspath(f))
        if _seen:
            fd = os.open(_out, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            try:
                os.write(fd, "".join(p + "\n" for p in sorted(_seen)).encode("utf-8", "surrogateescape"))
            finally:
                os.close(fd)

    sys.addaudithook(_hook)
    atexit.register(_flush)
