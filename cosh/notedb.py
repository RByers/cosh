"""Bulk review data via Gerrit NoteDb meta refs, fetched over git.

Each change has a ref refs/changes/<NN>/<N>/meta in the project's git repo.
The tip commit's tree holds one notes blob per patchset revision, each holding
JSON {"comments": [...]} for every *published* comment (drafts live elsewhere).
We fetch many meta refs in one `git fetch` (explicit refspecs, never globs:
chromium/src has millions of refs) into a local bare repo, then read comments
offline and convert them to the same shape as REST /comments, so derivation
is shared. See docs/gerrit-api-research.md §5.

NoteDb identities are numeric account ids only; emails come from the REST
listing (DETAILED_ACCOUNTS).
"""

import json
import os
import subprocess
import sys
import time

from . import store
from .contact import GIT_CONFIG, GIT_ENV

GIT_URL = "https://chromium.googlesource.com/{project}"
LOCAL_REF = "refs/meta/{n}"


def meta_ref(n):
    return f"refs/changes/{n % 100:02d}/{n}/meta"


def git(git_dir, *args, input=None, check=True):
    return subprocess.run(["git", "-C", git_dir, *GIT_CONFIG, *args], input=input,
                          capture_output=True, check=check, env={**os.environ, **GIT_ENV},
                          text=isinstance(input, str) or input is None)


def init_repo(git_dir):
    if not os.path.isdir(git_dir):
        os.makedirs(git_dir)
        git(git_dir, "init", "--bare", "-q")
        # never let a background gc / auto-maintenance kick in mid-run
        git(git_dir, "config", "gc.auto", "0")
        git(git_dir, "config", "maintenance.auto", "false")
    return git_dir


def fetched_numbers(git_dir):
    out = git(git_dir, "for-each-ref", "--format=%(refname:strip=2)", "refs/meta/").stdout
    return {int(x) for x in out.split()}


def fetch_batch(git_dir, project, numbers, retries=5):
    """One `git fetch` for many meta refs. Returns seconds taken."""
    specs = "".join(f"+{meta_ref(n)}:{LOCAL_REF.format(n=n)}\n" for n in numbers)
    url = GIT_URL.format(project=project)
    delay = 30
    for attempt in range(retries + 1):
        t0 = time.monotonic()
        p = git(git_dir, "-c", "protocol.version=2", "fetch", "--quiet", "--no-tags",
                "--no-write-fetch-head", "--stdin", url, input=specs, check=False)
        dt = time.monotonic() - t0
        if p.returncode == 0:
            return dt
        err = p.stderr.strip()
        # A missing ref (e.g. change deleted) fails the whole fetch: drop it and retry.
        missing = [n for n in numbers if meta_ref(n) in err and "couldn't find" in err]
        if missing:
            print(f"  missing meta refs, skipping: {missing}", file=sys.stderr)
            numbers = [n for n in numbers if n not in missing]
            if not numbers:
                return dt
            specs = "".join(f"+{meta_ref(n)}:{LOCAL_REF.format(n=n)}\n" for n in numbers)
            continue
        if attempt == retries:
            raise RuntimeError(f"git fetch failed: {err[:500]}")
        print(f"  git fetch failed ({err[:120]}); backing off {delay}s", file=sys.stderr)
        time.sleep(delay)
        delay = min(delay * 2, 900)


def _gerrit_ts(iso):
    # '2026-10-22T00:15:10Z' -> '2026-10-22 00:15:10.000000000' (REST format)
    return iso.replace("T", " ").rstrip("Z")[:19] + ".000000000"


def read_comments(git_dir, n):
    """Published comments of change n in REST /comments shape ({path: [comment]}),
    or None if the meta ref isn't present locally."""
    ref = LOCAL_REF.format(n=n)
    p = git(git_dir, "ls-tree", "-r", ref, check=False)
    if p.returncode != 0:
        return None
    blobs = [line.split()[2] for line in p.stdout.splitlines() if " blob " in line]
    out = {}
    if not blobs:
        return out
    batch = git(git_dir, "cat-file", "--batch",
                input=("\n".join(blobs) + "\n").encode()).stdout   # bytes
    # parse `<sha> blob <size>\n<content>\n` records (size in bytes)
    pos = 0
    while pos < len(batch):
        hdr_end = batch.index(b"\n", pos)
        size = int(batch[pos:hdr_end].split()[2])
        content = batch[hdr_end + 1:hdr_end + 1 + size]
        pos = hdr_end + 1 + size + 1
        try:
            doc = json.loads(content)
        except ValueError:
            continue
        for c in doc.get("comments", []):
            rc = {"author": {"_account_id": c.get("author", {}).get("id")},
                  "id": c.get("key", {}).get("uuid"),
                  "patch_set": c.get("key", {}).get("patchSetId"),
                  "updated": _gerrit_ts(c.get("writtenOn", "")),
                  "message": c.get("message", "")}
            if c.get("isAi"):
                rc["is_ai"] = True
            if c.get("tag"):
                rc["tag"] = c["tag"]
            if c.get("realAuthor"):
                rc["real_author"] = c["realAuthor"].get("id")
            out.setdefault(c.get("key", {}).get("filename", ""), []).append(rc)
    return out


def default_repo(project):
    return os.path.join(store.DATA_DIR, "notedb", project.replace("/", "_") + ".git")
