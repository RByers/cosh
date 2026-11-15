"""Publishes large files to the Cloudflare R2 bucket the site fetches from
(README.md; served at the `public_base` of ~/.secrets/cosh/r2.json).

  python3 -m cosh.r2 publish [<prefix> ...] [--dry-run]
  python3 -m cosh.r2 sync <local dir> <prefix> [--dry-run]

Uploading is the first half of a deploy: publish, then push main, whose
Pages workflow deploys the site that reads what was uploaded (docs/r2.md).
`cosh update` never runs it.

`publish` syncs the given prefixes of config/r2.json (default: all, plus
retired prefixes still in the bucket) from their folders under the data
directory (data/private); `sync` does any one folder. A sync uploads every
file under <local dir> to <prefix>/<relative path> (a trailing `.gz` is
dropped from the key and the object is served with `Content-Encoding:
gzip`, so browsers unpack it), skipping files whose content is unchanged
since the last upload.

An object whose local file is gone is kept while the live site may still
read it, and deleted otherwise: the site live now was deployed by the last
push, which reads the newest publish that began before that push (its time
comes from origin/main's reflog). An object last seen locally before that
publish is deleted; one still there at it is kept until a newer publish is
deployed. So a publish never breaks the live site, and the bucket holds at
most the live site's files and the new ones.

What was uploaded is recorded in a manifest (data/private/r2-manifest.json:
key -> sha256, size, and when it was last seen locally), so a sync never
lists the bucket; data/private/r2-publishes.json lists each publish's start
time and prefixes.

Limits guard against runaway uploads (a bug, a wrong directory): a sync
refuses to leave more than --max-total-gb in the manifest or to write or
delete more than --max-objects objects in one run.

The credentials file holds endpoint, bucket, access_key_id,
secret_access_key and public_base. It lives outside the repo
(~/.secrets/cosh/, mode 600) and is never printed. Standard library only:
requests are signed with AWS Signature Version 4, as R2's S3 API expects.
"""

import argparse
import datetime as dt
import fcntl
import gzip
import hashlib
import hmac
import http.client
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from zoneinfo import ZoneInfo

from . import store

CREDENTIALS = os.path.expanduser("~/.secrets/cosh/r2.json")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "config", "r2.json")
TORONTO = ZoneInfo("America/Toronto")
CACHE_CONTROL = "public, max-age=86400"
TYPES = {".json": "application/json", ".md": "text/markdown; charset=utf-8", ".txt": "text/plain; charset=utf-8"}


def config():
    with open(CONFIG) as f:
        return json.load(f)


def local_dir(name, data_dir=None):
    """The folder under the data directory that holds a published R2 prefix's files,
    by the folder's name in config/r2.json ('feedback-people')."""
    if name not in config()["prefixes"].values():
        raise ValueError(f"{name}: not a folder in {CONFIG}")
    return os.path.join(data_dir or store.DATA_DIR, name)


_held = []


def hold(data_dir=None):
    """Takes data/private/r2.lock for the rest of this process (waiting if
    another holds it): `publish` holds it while uploading, and the steps that
    write the published folders hold it while writing, so an upload never
    reads a folder that a step is rewriting. Writing to a scratch folder
    (--people-out, --out) needs no lock."""
    f = open(os.path.join(data_dir or store.DATA_DIR, "r2.lock"), "a")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("waiting for data/private/r2.lock (an R2 publish or a step writing its folders)",
              file=sys.stderr, flush=True)
        fcntl.flock(f, fcntl.LOCK_EX)
    _held.append(f)
    return f


def write_gz(path, text):
    """Writes text gzipped, byte for byte the same for the same text (so a sync
    uploads only what changed), and only if it changed. Returns
    (gzipped size, whether it changed)."""
    data = gzip.compress(text.encode(), mtime=0)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    old = None
    if os.path.exists(path):
        with open(path, "rb") as f:
            old = f.read()
    if old != data:
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    return len(data), old != data


def prune(root, keep):
    """Removes the files under root that aren't in keep (paths), and folders left empty."""
    removed = 0
    for d, _, names in os.walk(root, topdown=False):
        for name in names:
            p = os.path.join(d, name)
            if p not in keep:
                os.remove(p)
                removed += 1
        if d != root and not os.listdir(d):
            os.rmdir(d)
    return removed


def manifest_path(data_dir=None):
    return os.path.join(data_dir or store.DATA_DIR, "r2-manifest.json")


def load_credentials(path=CREDENTIALS):
    with open(path) as f:
        c = json.load(f)
    missing = {"endpoint", "bucket", "access_key_id", "secret_access_key"} - set(c)
    if missing:
        raise SystemExit(f"{path}: missing {', '.join(sorted(missing))}")
    return c


def _hmac(k, msg):
    return hmac.new(k, msg.encode(), hashlib.sha256).digest()


def sign(method, url, headers, payload_hash, cred, now=None, region="auto"):
    """Headers for an AWS SigV4-signed request to R2 (region 'auto', service 's3')."""
    now = now or dt.datetime.now(dt.timezone.utc)
    amz_date, day = now.strftime("%Y%m%dT%H%M%SZ"), now.strftime("%Y%m%d")
    u = urllib.parse.urlsplit(url)
    h = {k.lower(): str(v).strip() for k, v in headers.items()}
    h.update({"host": u.netloc, "x-amz-date": amz_date, "x-amz-content-sha256": payload_hash})
    names = sorted(h)
    canonical = "\n".join([method, u.path or "/", u.query, "".join(f"{k}:{h[k]}\n" for k in names),
                           ";".join(names), payload_hash])
    scope = f"{day}/{region}/s3/aws4_request"
    to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical.encode()).hexdigest()])
    k = _hmac(_hmac(_hmac(_hmac(("AWS4" + cred["secret_access_key"]).encode(), day), region), "s3"), "aws4_request")
    sig = hmac.new(k, to_sign.encode(), hashlib.sha256).hexdigest()
    h["authorization"] = (f"AWS4-HMAC-SHA256 Credential={cred['access_key_id']}/{scope}, "
                          f"SignedHeaders={';'.join(names)}, Signature={sig}")
    del h["host"]
    return h


def object_url(cred, key):
    return f"{cred['endpoint'].rstrip('/')}/{cred['bucket']}/{urllib.parse.quote(key, safe='/')}"


_conns = threading.local()


def _connection(host, fresh=False):
    """This thread's open HTTPS connection to host: reused across requests, so
    each one costs a round trip rather than a new TCP and TLS handshake."""
    c = getattr(_conns, "c", None)
    if fresh or c is None or c.host != host:
        if c is not None:
            c.close()
        c = _conns.c = http.client.HTTPSConnection(host, timeout=60)
    return c


def request(cred, method, key, body=b"", headers=None, tries=5):
    """One signed request on this thread's kept-alive connection; retries 429s,
    5xx and network errors with backoff, on a new connection."""
    url = object_url(cred, key)
    u = urllib.parse.urlsplit(url)
    payload = hashlib.sha256(body).hexdigest()
    for attempt in range(tries):
        h = sign(method, url, headers or {}, payload, cred)
        try:
            c = _connection(u.netloc, fresh=attempt > 0)
            c.request(method, u.path, body=body if method == "PUT" else None, headers=h)
            r = c.getresponse()
            data = r.read()
            if r.status < 300 or (r.status == 404 and method == "DELETE"):
                return r.status
            if r.status != 429 and r.status < 500 or attempt == tries - 1:
                raise SystemExit(f"R2 {method} {key}: HTTP {r.status} {data[:300]!r}")
        except (http.client.HTTPException, OSError) as e:
            if attempt == tries - 1:
                raise SystemExit(f"R2 {method} {key}: {e}")
        time.sleep(2 ** attempt)


def object_key(prefix, rel):
    """'review-feedback/threads' + 'sub/abc.json.gz' -> (key without .gz, gzipped?)."""
    gz = rel.endswith(".gz")
    rel = rel[:-3] if gz else rel
    return f"{prefix.strip('/')}/{rel.replace(os.sep, '/')}", gz


def publishes_path(data_dir=None):
    return os.path.join(data_dir or store.DATA_DIR, "r2-publishes.json")


def load_publishes(data_dir=None):
    """Past publishes, oldest first: [{time, when, prefixes}]."""
    p = publishes_path(data_dir)
    if not os.path.exists(p):
        return []
    with open(p) as f:
        return json.load(f)


def record_publish(stamp, prefixes, data_dir=None, keep=100):
    pubs = load_publishes(data_dir) + [dict(
        time=stamp, prefixes=sorted(prefixes),
        when=dt.datetime.fromtimestamp(stamp, TORONTO).strftime("%Y-%m-%d %H:%M %Z"))]
    p = publishes_path(data_dir)
    with open(p + ".tmp", "w") as f:
        json.dump(pubs[-keep:], f, indent=1)
    os.replace(p + ".tmp", p)


def last_push(root=ROOT):
    """When this checkout's origin/main last moved (a push of main, which deploys
    the site, or a fetch of one), from its reflog; None if that can't be told."""
    try:
        r = subprocess.run(["git", "reflog", "show", "--date=unix", "--format=%gd", "-n1",
                            "refs/remotes/origin/main"], cwd=root, capture_output=True, text=True)
    except OSError:
        return None
    m = re.search(r"@\{(\d+)\}", r.stdout)
    return int(m.group(1)) if r.returncode == 0 and m else None


def live_since(prefix, publishes, pushed):
    """The start time of the publish of <prefix> that the live site reads: the
    newest one that began before the last push (upload first, then push).
    None when there is none or the push time is unknown."""
    if pushed is None:
        return None
    ts = [p["time"] for p in publishes if prefix in p["prefixes"] and p["time"] <= pushed]
    return max(ts) if ts else None


def owns(prefix, key, nested=()):
    """Whether <key> is under <prefix> and not under one of the <nested>
    prefixes inside it (a retired 'a/threads' doesn't own 'a/threads/v2/x')."""
    return key.startswith(prefix.strip("/") + "/") and not any(key.startswith(n.strip("/") + "/") for n in nested)


def nested_in(prefix, prefixes):
    """The prefixes among <prefixes> inside <prefix>."""
    return [p for p in prefixes if p.strip("/").startswith(prefix.strip("/") + "/")]


def plan(local, prefix, manifest, live=None, nested=()):
    """What a publish does to <prefix>: (uploads [(key, path, sha256, gz)],
    deletes [key], kept [key], present [key]). <local> None means the prefix
    is retired (no longer in config/r2.json) and has no files. Objects under
    the <nested> prefixes belong to those, not to this one.

    An object whose file is gone is deleted only if the live site can't need
    it: it was last seen (present locally at a publish) before <live>, the
    publish the live site reads. Otherwise it is kept for the live site until
    a newer publish is deployed. With live None nothing is deleted."""
    want = {}
    for d, _, names in os.walk(local) if local else ():
        for name in sorted(names):
            if name.endswith(".tmp"):
                continue
            p = os.path.join(d, name)
            key, gz = object_key(prefix, os.path.relpath(p, local))
            with open(p, "rb") as f:
                want[key] = (p, hashlib.sha256(f.read()).hexdigest(), gz)
    ups = [(k, p, h, gz) for k, (p, h, gz) in sorted(want.items()) if manifest.get(k, {}).get("sha256") != h]
    gone = sorted(k for k in manifest if owns(prefix, k, nested) and k not in want)
    dels = [k for k in gone if live is not None and manifest[k].get("seen", 0) < live]
    kept = [k for k in gone if k not in set(dels)]
    return ups, dels, kept, sorted(want)


def sync(local, prefix, dry_run=False, jobs=16, max_objects=50_000, max_total_gb=5.0, data_dir=None,
         cred=None, stamp=None, live=None, nested=()):
    """Makes <prefix> in the bucket hold <local>'s files, keeping objects the
    live site may still read (plan()). Each object present locally is marked
    seen at <stamp>, this publish's start time. Returns how many objects are
    left under <prefix>."""
    stamp = time.time() if stamp is None else stamp
    mpath = manifest_path(data_dir)
    manifest = {}
    if os.path.exists(mpath):
        with open(mpath) as f:
            manifest = json.load(f)
    ups, dels, kept, present = plan(local, prefix, manifest, live, nested)
    sizes = {k: os.path.getsize(p) if os.path.exists(p) else 0 for k, p, _, _ in ups}
    total = sum(v["bytes"] for k, v in manifest.items() if k not in sizes and k not in dels) + sum(sizes.values())
    print(f"{prefix}: {len(ups):,} to upload ({sum(sizes.values()) / 1e6:.1f} MB), {len(dels):,} to delete"
          + (f", {len(kept):,} gone locally but kept for the live site" if kept else "")
          + f"; bucket total after {total / 1e9:.2f} GB", file=sys.stderr, flush=True)
    if len(ups) + len(dels) > max_objects:
        raise SystemExit(f"refusing: {len(ups) + len(dels):,} objects is over --max-objects {max_objects:,}")
    if local is not None and not present and (dels or kept):
        # A folder emptied by a failed or half-done step, not a prefix that was retired.
        raise SystemExit(f"refusing: {local} has no files but the bucket has {len(dels) + len(kept):,} under "
                         f"{prefix}; rerun the step that writes it")
    if total > max_total_gb * 1e9:
        raise SystemExit(f"refusing: {total / 1e9:.2f} GB is over --max-total-gb {max_total_gb}")
    left = len(present) + len(kept)
    if dry_run:
        return left
    lock = threading.Lock()
    done = [0]

    def save():
        tmp = mpath + ".tmp"
        with open(tmp, "w") as f:
            json.dump(manifest, f, sort_keys=True, separators=(",", ":"))
        os.replace(tmp, mpath)

    for k in present:
        if k in manifest:
            manifest[k]["seen"] = stamp
    if not (ups or dels):
        save()
        return left
    cred = cred or load_credentials()
    skipped = []

    def put(item):
        key, path, sha, gz = item
        # A step may rewrite or remove files while a sync runs: record what was
        # sent, and leave a vanished file for the next sync.
        try:
            with open(path, "rb") as f:
                body = f.read()
        except FileNotFoundError:
            with lock:
                skipped.append(key)
            return
        sha = hashlib.sha256(body).hexdigest()
        headers = {"content-type": TYPES.get(os.path.splitext(key)[1], "application/octet-stream"),
                   "cache-control": CACHE_CONTROL}
        if gz:
            headers["content-encoding"] = "gzip"
        request(cred, "PUT", key, body, headers)
        with lock:
            manifest[key] = dict(sha256=sha, bytes=len(body), seen=stamp)
            done[0] += 1
            if done[0] % 500 == 0:
                save()
                print(f"  {done[0]:,}/{len(ups) + len(dels):,}", file=sys.stderr, flush=True)

    def delete(key):
        request(cred, "DELETE", key)
        with lock:
            manifest.pop(key, None)
            done[0] += 1
    try:
        with ThreadPoolExecutor(jobs) as ex:
            list(ex.map(put, ups))
            list(ex.map(delete, dels))
    finally:
        save()
    print(f"{prefix}: uploaded {len(ups) - len(skipped):,}, deleted {len(dels):,}"
          + (f"; {len(skipped):,} files vanished during the sync, run it again" if skipped else ""), file=sys.stderr)
    return sum(1 for k in manifest if owns(prefix, k, nested))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sync", help="make <prefix> in the bucket hold <local dir>'s files")
    s.add_argument("local")
    s.add_argument("prefix")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--jobs", type=int, default=16, help="requests in flight (default 16)")
    s.add_argument("--max-objects", type=int, default=50_000)
    s.add_argument("--max-total-gb", type=float, default=5.0)
    p = sub.add_parser("publish", help="sync prefixes of config/r2.json (default all, and retired ones) "
                                       "from their folders in the data directory")
    p.add_argument("prefixes", nargs="*")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--jobs", type=int, default=16, help="requests in flight (default 16)")
    p.add_argument("--max-objects", type=int, default=50_000, help="per prefix")
    p.add_argument("--max-total-gb", type=float, default=5.0)
    a = ap.parse_args(argv)
    known = config()["prefixes"]
    if a.cmd == "sync":
        todo = [(a.prefix, a.local)]
    else:
        for prefix in a.prefixes:
            if prefix not in known:
                raise SystemExit(f"{prefix}: not a prefix in {CONFIG} ({', '.join(known)})")
        todo = [(prefix, local_dir(name)) for prefix, name in known.items()
                if not a.prefixes or prefix in a.prefixes]
        for _, local in todo:
            if not os.path.isdir(local):
                raise SystemExit(f"{local}: missing; run the step that writes it first (config/dataflow.json)")
    if not a.dry_run:
        hold()
    pubs, pushed = load_publishes(), last_push()
    if a.cmd == "publish" and not a.prefixes:
        # A prefix dropped from config/r2.json (a format moved to v2) is emptied
        # once the live site no longer reads it.
        old = {x for pub in pubs for x in pub["prefixes"]} - set(known)
        todo += [(prefix, None) for prefix in sorted(old)]
    # A prefix may sit inside another (review-feedback/threads/v3 inside the
    # retired review-feedback/threads): each object belongs to the innermost.
    all_prefixes = set(known) | {x for pub in pubs for x in pub["prefixes"]} | {prefix for prefix, _ in todo}
    if pushed is None:
        print("can't tell when main was last pushed (origin/main's reflog); deleting nothing",
              file=sys.stderr, flush=True)
    stamp = time.time()
    synced = []
    for prefix, local in todo:
        left = sync(local, prefix, a.dry_run, a.jobs, a.max_objects, a.max_total_gb, stamp=stamp,
                    live=live_since(prefix, pubs, pushed), nested=nested_in(prefix, all_prefixes))
        if local is not None or left:
            synced.append(prefix)
    if not a.dry_run:
        record_publish(stamp, synced)
        print("Uploaded. Now push main to deploy the site that reads it (docs/r2.md).", file=sys.stderr)


if __name__ == "__main__":
    main()
