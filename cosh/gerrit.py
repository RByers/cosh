"""Polite, read-only Gerrit REST client.

Rules (see docs/gerrit-api-research.md §5):
  * strictly serial: one request at a time
  * a minimum gap between the end of one request and the start of the next
  * gzip on
  * exponential backoff on HTTP 429 / 5xx, honoring Retry-After
  * anonymous only
"""

import gzip
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from .contact import HTTP_HEADERS
XSSI_PREFIX = ")]}'"


def strip_xssi(body: str) -> str:
    if body.startswith(XSSI_PREFIX):
        return body[body.index("\n") + 1:]
    return body


class GerritClient:
    def __init__(self, host, min_interval=1.0, max_retries=6, log=sys.stderr):
        self.host = host
        self.base = f"https://{host}"
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.log = log
        self._last_done = 0.0
        self.request_count = 0

    def _wait_turn(self):
        gap = time.monotonic() - self._last_done
        if gap < self.min_interval:
            time.sleep(self.min_interval - gap)

    def get(self, path, params=None):
        """GET a path. Returns (http_status, body_text_without_xssi, url)."""
        url = self.base + path
        if params:
            url += "?" + urllib.parse.urlencode(params, doseq=True, safe=":/\"")
        delay = max(self.min_interval, 2.0)
        for attempt in range(self.max_retries + 1):
            self._wait_turn()
            req = urllib.request.Request(url, headers={
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                **HTTP_HEADERS,
            })
            status, raw, retry_after = None, b"", None
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    status = resp.status
                    raw = resp.read()
                    if resp.headers.get("Content-Encoding") == "gzip":
                        raw = gzip.decompress(raw)
            except urllib.error.HTTPError as e:
                status = e.code
                raw = e.read() or b""
                retry_after = e.headers.get("Retry-After")
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                status = -1
                raw = str(e).encode()
            finally:
                self._last_done = time.monotonic()
                self.request_count += 1

            if status == 429 or status == -1 or status >= 500:
                if attempt == self.max_retries:
                    break
                wait = delay
                if retry_after and retry_after.isdigit():
                    wait = max(wait, int(retry_after))
                print(f"  [{status}] backing off {wait:.0f}s: {url}", file=self.log)
                time.sleep(wait)
                delay = min(delay * 2, 600)
                continue
            return status, strip_xssi(raw.decode("utf-8", "replace")), url
        raise RuntimeError(f"giving up after {self.max_retries} retries "
                           f"(last status {status}): {url}")

    def get_json(self, path, params=None):
        status, body, url = self.get(path, params)
        if status != 200:
            raise RuntimeError(f"HTTP {status} for {url}: {body[:200]}")
        return json.loads(body), body, url
