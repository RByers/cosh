"""Who we are, sent with every request so server operators can reach us.

The contact e-mail address is not in the code. It comes from, in order:

1. the COSH_CONTACT environment variable;
2. "contact_email" in settings.json in the data directory (store.DATA_DIR,
   i.e. data/private/ or $COSH_DATA_DIR);
3. "contact_email" in the main checkout's data/private/settings.json, so
   every git worktree shares one file.

settings.json is gitignored (it lives in data/private/). Commands that talk
to a server fail with ContactMissing if none of these is set; offline
commands never look."""

import json
import os
import subprocess
from functools import lru_cache

from . import store

VERSION = "0.1"
PROJECT = "Chromium Open Source Health research"
SETTINGS_NAME = "settings.json"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class ContactMissing(RuntimeError):
    pass


def _main_checkout_data_dir():
    """data/private of the main checkout when ROOT is a git worktree, else None."""
    try:
        common = subprocess.run(
            ["git", "-C", ROOT, "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    if os.path.basename(common) != ".git":
        return None
    return os.path.join(os.path.dirname(common), "data", "private")


def settings_paths():
    """Candidate settings.json paths, most specific first."""
    paths = [os.path.join(store.DATA_DIR, SETTINGS_NAME)]
    main = _main_checkout_data_dir()
    if main:
        p = os.path.join(main, SETTINGS_NAME)
        if os.path.realpath(p) != os.path.realpath(paths[0]):
            paths.append(p)
    return paths


@lru_cache(maxsize=None)
def contact():
    """The operator's contact e-mail address, or raise ContactMissing."""
    env = os.environ.get("COSH_CONTACT", "").strip()
    if env:
        return env
    paths = settings_paths()
    for path in paths:
        try:
            with open(path) as f:
                settings = json.load(f)
        except FileNotFoundError:
            continue
        except (OSError, ValueError) as e:
            raise ContactMissing(f"can't read {path}: {e}") from e
        email = str(settings.get("contact_email") or "").strip()
        if email:
            return email
    raise ContactMissing(
        "No contact e-mail address is configured. Every request to Gerrit, "
        "googlesource or Radar names a contact so server operators can reach "
        "us. Provide one in " + paths[0] + ', e.g. {"contact_email": '
        '"you@example.com"}, or set COSH_CONTACT.')


def http_headers():
    """User-Agent plus the RFC 9110 `From` header, which exists for exactly this
    purpose (contact address of the human running an automated client)."""
    c = contact()
    return {"User-Agent": f"cosh/{VERSION} ({PROJECT}; low-rate; contact: {c})", "From": c}


def git_env():
    """GIT_USER_AGENT sets both the HTTP User-Agent header and the protocol v2
    `agent=` capability (git replaces spaces there with '.')."""
    return {"GIT_USER_AGENT": f"git/cosh-{VERSION} ({PROJECT}; contact: {contact()})"}


def git_config():
    """http.extraHeader adds the From header to the smart-HTTP requests."""
    return ["-c", f"http.extraHeader=From: {contact()}"]
