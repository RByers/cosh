"""Publishes large files to the Cloudflare R2 bucket the site fetches from
(README.md; served at the `public_base` of ~/.secrets/cosh/r2.json).

  python3 -m cosh.r2 publish [<prefix> ...] [--dry-run]
  python3 -m cosh.r2 sync <local dir> <prefix> [--dry-run]

`publish` syncs the given prefixes of config/r2.json (default: all) from
their folders under the data directory (data/private); `sync` does any one
folder.

uploads every file under <local dir> to <prefix>/<relative path> (a
trailing `.gz` is dropped from the key and the object is served with
`Content-Encoding: gzip`, so browsers unpack it), skipping files whose
content is unchanged since the last upload, and deletes objects under
<prefix> whose local file is gone. What was uploaded is recorded in a
manifest (data/private/r2-manifest.json: key -> sha256), so a sync never
lists the bucket.

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
import gzip
import hashlib
import hmac
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from . import store

CREDENTIALS = os.path.expanduser("~/.secrets/cosh/r2.json")
CONFIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "r2.json")
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


def request(cred, method, key, body=b"", headers=None, tries=5):
    """One signed request; retries 429s, 5xx and network errors with backoff."""
    url = object_url(cred, key)
    payload = hashlib.sha256(body).hexdigest()
    for attempt in range(tries):
        req = urllib.request.Request(url, data=body if method == "PUT" else None, method=method,
                                     headers=sign(method, url, headers or {}, payload, cred))
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status
        except urllib.error.HTTPError as e:
            if e.code == 404 and method == "DELETE":
                return 404
            if e.code != 429 and e.code < 500 or attempt == tries - 1:
                raise SystemExit(f"R2 {method} {key}: HTTP {e.code} {e.read()[:300]!r}")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt == tries - 1:
                raise SystemExit(f"R2 {method} {key}: {e}")
        time.sleep(2 ** attempt)


def object_key(prefix, rel):
    """'review-feedback/threads' + '2026H1/abc.json.gz' -> (key without .gz, gzipped?)."""
    gz = rel.endswith(".gz")
    rel = rel[:-3] if gz else rel
    return f"{prefix.strip('/')}/{rel.replace(os.sep, '/')}", gz


def plan(local, prefix, manifest):
    """(uploads [(key, path, sha256, gz)], deletes [key]) to make <prefix> match <local>."""
    want = {}
    for d, _, names in os.walk(local):
        for name in sorted(names):
            if name.endswith(".tmp"):
                continue
            p = os.path.join(d, name)
            key, gz = object_key(prefix, os.path.relpath(p, local))
            with open(p, "rb") as f:
                want[key] = (p, hashlib.sha256(f.read()).hexdigest(), gz)
    pre = prefix.strip("/") + "/"
    ups = [(k, p, h, gz) for k, (p, h, gz) in sorted(want.items()) if manifest.get(k, {}).get("sha256") != h]
    dels = sorted(k for k in manifest if k.startswith(pre) and k not in want)
    return ups, dels


def sync(local, prefix, dry_run=False, jobs=4, max_objects=50_000, max_total_gb=5.0, data_dir=None,
         cred=None):
    mpath = manifest_path(data_dir)
    manifest = {}
    if os.path.exists(mpath):
        with open(mpath) as f:
            manifest = json.load(f)
    ups, dels = plan(local, prefix, manifest)
    sizes = {k: os.path.getsize(p) if os.path.exists(p) else 0 for k, p, _, _ in ups}
    total = sum(v["bytes"] for k, v in manifest.items() if k not in sizes and k not in dels) + sum(sizes.values())
    print(f"{prefix}: {len(ups):,} to upload ({sum(sizes.values()) / 1e6:.1f} MB), {len(dels):,} to delete; "
          f"bucket total after {total / 1e9:.2f} GB", file=sys.stderr, flush=True)
    if len(ups) + len(dels) > max_objects:
        raise SystemExit(f"refusing: {len(ups) + len(dels):,} objects is over --max-objects {max_objects:,}")
    if total > max_total_gb * 1e9:
        raise SystemExit(f"refusing: {total / 1e9:.2f} GB is over --max-total-gb {max_total_gb}")
    if dry_run or not (ups or dels):
        return
    cred = cred or load_credentials()
    lock = threading.Lock()
    done = [0]

    def save():
        tmp = mpath + ".tmp"
        with open(tmp, "w") as f:
            json.dump(manifest, f, sort_keys=True, separators=(",", ":"))
        os.replace(tmp, mpath)

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
            manifest[key] = dict(sha256=sha, bytes=len(body))
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


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sync", help="make <prefix> in the bucket match <local dir>")
    s.add_argument("local")
    s.add_argument("prefix")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--jobs", type=int, default=4, help="requests in flight (default 4)")
    s.add_argument("--max-objects", type=int, default=50_000)
    s.add_argument("--max-total-gb", type=float, default=5.0)
    p = sub.add_parser("publish", help="sync prefixes of config/r2.json (default all) from their folders in the data directory")
    p.add_argument("prefixes", nargs="*")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--jobs", type=int, default=4, help="requests in flight (default 4)")
    p.add_argument("--max-objects", type=int, default=50_000, help="per prefix")
    p.add_argument("--max-total-gb", type=float, default=5.0)
    a = ap.parse_args(argv)
    if a.cmd == "sync":
        sync(a.local, a.prefix, a.dry_run, a.jobs, a.max_objects, a.max_total_gb)
        return
    known = config()["prefixes"]
    for prefix in a.prefixes:
        if prefix not in known:
            raise SystemExit(f"{prefix}: not a prefix in {CONFIG} ({', '.join(known)})")
    for prefix, name in known.items():
        if a.prefixes and prefix not in a.prefixes:
            continue
        local = local_dir(name)
        if not os.path.isdir(local):
            raise SystemExit(f"{local}: missing; run the step that writes it first (config/dataflow.json)")
        sync(local, prefix, a.dry_run, a.jobs, a.max_objects, a.max_total_gb)


if __name__ == "__main__":
    main()
