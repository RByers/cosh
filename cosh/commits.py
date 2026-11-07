"""Commits on chromium/src main, for the author-side metric (docs/commits.md).

Reads the local bare clone (~/projects/shared/chromium, or $COSH_CHROMIUM_GIT)
and never fetches: GIT_NO_LAZY_FETCH=1 and no remote command. Writes two
tables of derived.sqlite, rebuilt from scratch on every run (about 2 min):

  commits      one row per first-parent commit on main landed since the
               oldest fetched week: git author, landing time (committer date,
               UTC), its CL (the Reviewed-on footer) and a bot flag
  commit_dirs  the directories each commit touches (paths.directory of each
               file), with a file count

A commit is a bot's if its CL's owner is a bot (changes.is_bot_owned) or
config/bots.txt matches its git author: some bots (e.g. a WebLayer builder)
author commits on CLs a person owns. summarize credits commits to the git
author's org.

`python3 -m cosh commits` runs it; a full `derive` runs it at its end.
"""

import json
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import date

from . import store
from .bots import _PATTERNS
from .extract import iso_week_of
from .paths import directory

DEFAULT_REPO = os.path.expanduser("~/projects/shared/chromium")
REVIEWED_ON = re.compile(r"https://chromium-review\.googlesource\.com/c/chromium/src/\+/(\d+)")
# Every commit since this week's Monday, if derived.sqlite names no fetched weeks.
FALLBACK_SINCE = "2023-06-26"


def repo_path():
    return os.environ.get("COSH_CHROMIUM_GIT") or DEFAULT_REPO


def is_bot_email(email):
    return any(p.search(email) for p in _PATTERNS)


def read_commits(repo, since):
    """Yields (sha, author email, author name, landed_at, CL or None, files)
    for each first-parent commit on main landed at or after `since` (UTC
    date), newest first. Merges list their files against the first parent."""
    env = dict(os.environ, GIT_NO_LAZY_FETCH="1", TZ="UTC")
    cmd = ["git", "-C", repo, "log", "main", "--first-parent", "--diff-merges=first-parent",
           "--no-renames", "--name-only", f"--since={since}T00:00:00Z",
           "--date=format-local:%Y-%m-%d %H:%M:%S",
           "--format=%x01%H%x00%ae%x00%an%x00%cd%x00%(trailers:key=Reviewed-on,valueonly,separator=%x20)"]
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, env=env, text=True, errors="replace") as p:
        cur = None
        for line in p.stdout:
            line = line.rstrip("\n")
            if line.startswith("\x01"):
                if cur:
                    yield cur
                sha, email, name, landed, footer = line[1:].split("\x00")
                m = REVIEWED_ON.search(footer)
                cur = (sha, email.strip().lower(), name, landed, int(m.group(1)) if m else None, [])
            elif line and cur:
                cur[5].append(line)
        if cur:
            yield cur
    if p.returncode:
        raise SystemExit(f"git log in {repo} failed with exit code {p.returncode}")


def build_commits(db, repo=None):
    """Rebuilds `commits` and `commit_dirs` in an open derived DB."""
    repo = repo or repo_path()
    if not os.path.isdir(repo):
        raise SystemExit(f"no Chromium git repo at {repo} (set COSH_CHROMIUM_GIT)")
    weeks = [w for (v,) in db.execute("SELECT v FROM meta WHERE k = 'fetched_weeks'")
             for w in json.loads(v or "[]")]
    since = FALLBACK_SINCE
    if weeks:
        y, w = min(weeks).split("-W")
        since = date.fromisocalendar(int(y), int(w), 1).isoformat()
    bot_owned = dict(db.execute("SELECT change_number, is_bot_owned FROM changes WHERE branch = 'main'"))
    n = Counter()
    with db:
        db.execute("DELETE FROM commit_dirs")
        db.execute("DELETE FROM commits")
        for cid, (sha, email, name, landed, cl, files) in enumerate(read_commits(repo, since), 1):
            owned = bot_owned.get(cl)
            bot = bool(owned) or is_bot_email(email)
            n["bot" if bot else "human"] += 1
            n["no CL in derived.sqlite"] += owned is None
            db.execute("INSERT INTO commits VALUES (?,?,?,?,?,?,?,?,?)",
                       (cid, sha, cl, email, name, landed, iso_week_of(landed), int(bot), len(files)))
            dirs = Counter(directory(f) for f in files)
            db.executemany("INSERT INTO commit_dirs VALUES (?,?,?)",
                           [(cid, d, k) for d, k in dirs.items()])
        db.execute("INSERT OR REPLACE INTO meta VALUES ('commits_built_at', ?)", (store.now_iso(),))
        db.execute("INSERT OR REPLACE INTO meta VALUES ('commits_since', ?)", (since,))
    print(f"commits since {since}: {dict(n)}", file=sys.stderr)
    return n
