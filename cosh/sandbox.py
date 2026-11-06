"""Running headless `claude -p` on untrusted text (SECURITY.md).

`cosh classify` feeds review comments, which anyone with a Gerrit account can
write, to Claude. The `claude -p` flags in classify.py already give the
model no tools. This module adds the layers around the process, so that a
model or CLI misbehaving on injected text still finds nothing worth taking:

  - a scrubbed environment: only PATH, the locale, a fresh HOME and the one
    credential claude needs. The caller's tokens (Radar, GitHub, the parent
    Claude session's socket) don't reach it;
  - a fresh, private (0700) HOME and working directory per call, deleted
    afterwards, so no user or project settings, hooks, plugins, CLAUDE.md
    or session transcripts are loaded, and nothing persists between calls;
  - with bubblewrap (`bwrap`), its own mount, PID, IPC and UTS namespaces:
    a read-only root with /home, /root, /run/user (ssh-agent, gpg-agent,
    D-Bus and Claude daemon sockets), /tmp, /var/tmp and the cosh data and
    code directories replaced by empty tmpfs, and no capabilities. The
    network is shared, because claude has to reach the API.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

# Paths hidden from claude under bwrap (each replaced by an empty tmpfs).
HIDDEN = ("/home", "/root", "/run/user", "/tmp", "/var/tmp", "/mnt", "/media", "/srv")
# The only variables carried over from the caller's environment.
KEEP_ENV = ("PATH", "LANG", "LC_ALL", "TZ")
CREDENTIALS = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY")


def find_credentials(environ=None, settings_path=None):
    """The credential env var(s) claude needs, from the environment, else from
    the `env` block of ~/.claude/settings.json (where `claude setup-token`
    tokens usually live). Never printed."""
    environ = os.environ if environ is None else environ
    found = {k: environ[k] for k in CREDENTIALS if environ.get(k)}
    if found:
        return found
    path = settings_path or os.path.expanduser("~/.claude/settings.json")
    try:
        with open(path) as f:
            env = json.load(f).get("env") or {}
    except (OSError, ValueError):
        env = {}
    return {k: env[k] for k in CREDENTIALS if isinstance(env.get(k), str) and env[k]}


def bwrap_works(bwrap):
    try:
        return subprocess.run([bwrap, "--ro-bind", "/", "/", "--unshare-all", "--share-net",
                               "--die-with-parent", "true"], capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


class Sandbox:
    """Runs claude, one call at a time per run(); safe to share across threads."""

    def __init__(self, mode="auto", hide=(), claude="claude", credentials=None):
        exe = shutil.which(claude)
        if not exe:
            raise SystemExit(f"{claude} not found on PATH")
        self.claude = os.path.realpath(exe)
        self.credentials = find_credentials() if credentials is None else credentials
        if not self.credentials:
            raise SystemExit("cosh classify needs CLAUDE_CODE_OAUTH_TOKEN (from `claude setup-token`, in the "
                             "environment or in ~/.claude/settings.json's env block) or ANTHROPIC_API_KEY. "
                             "It runs claude with a fresh HOME, not your ~/.claude (SECURITY.md).")
        self.bwrap = shutil.which("bwrap") if mode in ("auto", "bwrap") else None
        if self.bwrap and not bwrap_works(self.bwrap):
            self.bwrap = None
        if mode == "bwrap" and not self.bwrap:
            raise SystemExit("--sandbox bwrap: bubblewrap is missing or can't create namespaces here")
        if mode not in ("auto", "bwrap", "none"):
            raise SystemExit(f"unknown sandbox mode {mode!r}")
        self.mode = "bwrap" if self.bwrap else "none"
        # Extra paths to hide, unless already under a HIDDEN one.
        self.hide = [p for p in (os.path.realpath(h) for h in hide if h) if not self._under(p, HIDDEN)]
        self.root = tempfile.mkdtemp(prefix="cosh-claude-")      # 0700, ours only

    @staticmethod
    def _under(path, dirs):
        return any(path == d or path.startswith(d.rstrip("/") + "/") for d in dirs)

    def describe(self):
        return ("bwrap (fresh HOME, scrubbed env, /home /run/user /tmp and cosh data hidden)" if self.bwrap
                else "none (fresh HOME and scrubbed env only; install bubblewrap for more)")

    def env(self, home):
        env = {k: os.environ[k] for k in KEEP_ENV if k in os.environ}
        env.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
        env.setdefault("LANG", "C.UTF-8")
        env.update(HOME=home, TMPDIR=home, CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1")
        env.update(self.credentials)
        return env

    def command(self, args, home):
        cmd = [self.claude, *args]
        if not self.bwrap:
            return cmd
        jail = [self.bwrap, "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc"]
        for p in [*HIDDEN, *self.hide]:
            if os.path.isdir(p):
                jail += ["--tmpfs", p]
        if self._under(self.claude, [*HIDDEN, *self.hide]):
            jail += ["--ro-bind", self.claude, self.claude]   # e.g. a native install under ~/.local
        jail += ["--bind", home, home, "--chdir", home,
                 "--unshare-all", "--share-net", "--die-with-parent", "--new-session", "--cap-drop", "ALL"]
        return jail + cmd

    def run(self, args, input):
        home = tempfile.mkdtemp(dir=self.root)
        try:
            return subprocess.run(self.command(args, home), input=input, capture_output=True, text=True,
                                  cwd=home, env=self.env(home))
        finally:
            shutil.rmtree(home, ignore_errors=True)

    def close(self):
        shutil.rmtree(self.root, ignore_errors=True)


if __name__ == "__main__":       # python3 -m cosh.sandbox: show the jail, run nothing
    s = Sandbox()
    print(s.describe(), file=sys.stderr)
    print(" ".join(s.command(["-p", "..."], os.path.join(s.root, "HOME"))))
    s.close()
