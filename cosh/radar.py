"""Cloudflare Radar browser share (the usage side of the value ratio).

  python3 -m cosh radar [--start 2020-09-01] [--agg 1d|1w] [--offline]

Fetches three Radar series per calendar-quarter chunk (human traffic only):
  browser      /http/timeseries_groups/BROWSER            all operating systems
  browser_ios  /http/timeseries_groups/BROWSER?os=IOS     iOS only
  os           /http/timeseries_groups/OS                 share of requests per OS
caches every raw response under data/public/radar/raw/, then writes
data/public/radar_browser_share.csv with iOS removed and shares renormalised
among Chromium-based browsers, WebViews and in-app browsers (config/browsers.csv).

iOS is excluded because every iOS browser is WebKit (Chrome iOS included), so
Chromium usage there is negligible. Radar can't exclude an OS in one query
(`os` takes a single value, no `-` prefix), so per day and browser b:
  non_ios(b) = (all(b) - w_ios * ios(b)) / (1 - w_ios)
with w_ios the iOS share of requests. Checked against `os=ANDROID` on
2026-10-26: Android-only browsers matched to 4 decimal places.

Rules (same spirit as gerrit.py): serial requests, >= 1 s apart, gzip,
backoff on 429/5xx. Needs CLOUDFLARE_API_TOKEN (custom token with
Account > Radar > Read); see docs/radar-research.md.
"""

import csv
import datetime as dt
import gzip
import itertools
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "public" / "radar" / "raw"
OUT_CSV = ROOT / "data" / "public" / "radar_browser_share.csv"
BROWSERS_CSV = ROOT / "config" / "browsers.csv"

API = "https://api.cloudflare.com/client/v4"
ENDPOINT = "/radar/http/timeseries_groups/BROWSER"
OS_ENDPOINT = "/radar/http/timeseries_groups/OS"
from .contact import HTTP_HEADERS
# name -> (endpoint, extra params). "browser" keeps the original cache file names.
SERIES = {
    "browser": (ENDPOINT, {}),
    "browser_ios": (ENDPOINT, {"os": "IOS"}),
    "os": (OS_ENDPOINT, {}),
}
DEVICES = ("ALL",)                       # ALL = no deviceType filter; the UI uses only ALL
# Kinds counted in the Chromium denominator (bots, TVs and "other" never are).
COUNTED_KINDS = frozenset({"browser", "webview", "in_app"})
DEFAULT_START = dt.date(2020, 9, 1)      # Radar launched Sept 2020; earlier chunks are probed
DEFAULT_LIMIT_PER_GROUP = 50
# Cloudflare API auth failures (missing/invalid headers, invalid token, no permission);
# some come back as HTTP 400, so they are checked explicitly and never cached.
AUTH_ERROR_CODES = {6003, 6111, 9106, 9109, 10000}

CSV_FIELDS = ["period", "period_start", "period_end", "granularity", "device", "browser",
              "is_chromium", "kind", "days", "raw_share", "chromium_share"]


# ---------------------------------------------------------------- config

def load_browsers(path=BROWSERS_CSV):
    """browser name -> {"is_chromium": bool, "kind": str}."""
    with open(path, newline="") as f:
        return {r["browser"]: {"is_chromium": r["is_chromium"].strip() == "1",
                               "kind": r["kind"].strip() or "browser"}
                for r in csv.DictReader(f)}


# ---------------------------------------------------------------- HTTP

class RadarClient:
    def __init__(self, token, min_interval=1.0, max_retries=6, log=sys.stderr):
        self.token = token
        self.min_interval = max(min_interval, 1.0)
        self.max_retries = max_retries
        self.log = log
        self._last_done = 0.0
        self.request_count = 0

    def get(self, path, params):
        """GET; returns (status, parsed_json_or_None, body_text, url)."""
        url = API + path + "?" + urllib.parse.urlencode(params)
        delay = 2.0
        for attempt in range(self.max_retries + 1):
            gap = time.monotonic() - self._last_done
            if gap < self.min_interval:
                time.sleep(self.min_interval - gap)
            req = urllib.request.Request(url, headers={
                "Accept": "application/json", "Accept-Encoding": "gzip",
                **HTTP_HEADERS, "Authorization": f"Bearer {self.token}"})
            status, raw, retry_after = None, b"", None
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    status, raw = resp.status, resp.read()
                    if resp.headers.get("Content-Encoding") == "gzip":
                        raw = gzip.decompress(raw)
            except urllib.error.HTTPError as e:
                status, raw = e.code, e.read() or b""
                retry_after = e.headers.get("Retry-After")
                if e.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                status, raw = -1, str(e).encode()
            finally:
                self._last_done = time.monotonic()
                self.request_count += 1
            if status in (429, -1) or status >= 500:
                if attempt == self.max_retries:
                    break
                wait = max(delay, int(retry_after)) if (retry_after or "").isdigit() else delay
                print(f"  [{status}] backing off {wait:.0f}s", file=self.log)
                time.sleep(wait)
                delay = min(delay * 2, 600)
                continue
            body = raw.decode("utf-8", "replace")
            try:
                parsed = json.loads(body)
            except ValueError:
                parsed = None
            return status, parsed, body, url
        raise RuntimeError(f"giving up after {self.max_retries} retries (last {status}): {url}")


# ---------------------------------------------------------------- chunks / cache

def quarter_chunks(start, end):
    """Calendar quarters [qs, qe) covering [start, end); first is clipped to start."""
    q = dt.date(start.year, 3 * ((start.month - 1) // 3) + 1, 1)
    while q < end:
        nm = q.month + 3
        qe = dt.date(q.year + (nm > 12), (nm - 1) % 12 + 1, 1)
        yield max(q, start), min(qe, end)
        q = qe


def cache_path(device, agg, cs, ce, series="browser"):
    return RAW_DIR / f"{series}_{device.lower()}_{agg}_{cs.isoformat()}_{ce.isoformat()}.json"


def request_params(device, agg, cs, ce, limit_per_group, series="browser"):
    p = {"aggInterval": agg, "botClass": "LIKELY_HUMAN", "limitPerGroup": limit_per_group,
         "normalization": "PERCENTAGE", "format": "JSON",
         "dateStart": f"{cs.isoformat()}T00:00:00Z", "dateEnd": f"{ce.isoformat()}T00:00:00Z"}
    if series == "os":
        del p["limitPerGroup"]                  # Radar rejects it for the OS dimension
    p.update(SERIES[series][1])
    if device != "ALL":
        p["deviceType"] = device
    return p


def series_of(request):
    """Which SERIES a cached request belongs to."""
    if request.get("endpoint") == OS_ENDPOINT:
        return "os"
    return "browser_ios" if request.get("os") == "IOS" else "browser"


def fetch(start=DEFAULT_START, agg="1d", devices=DEVICES, limit_per_group=DEFAULT_LIMIT_PER_GROUP,
          token=None, min_interval=1.0, today=None, retry_errors=False, series=tuple(SERIES),
          log=sys.stderr):
    """Fetch every missing/incomplete chunk of each series. Complete chunks are
    never re-fetched."""
    token = token or os.environ.get("CLOUDFLARE_API_TOKEN")
    if not token:
        raise SystemExit("CLOUDFLARE_API_TOKEN is not set. Create a Cloudflare API token "
                         "with 'Account > Radar > Read' and export it (see docs/radar-research.md).")
    today = today or dt.datetime.now(dt.timezone.utc).date()
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    client = RadarClient(token, min_interval=min_interval, log=log)
    for name, device in itertools.product(series, devices):
        endpoint = SERIES[name][0]
        # newest first: a bad token / bad parameter fails on data that surely exists,
        # before any old chunk could be cached as a "no history" 4xx.
        for cs, qe in reversed(list(quarter_chunks(start, today))):
            ce = min(qe, today)                     # only whole UTC days that have ended
            path = cache_path(device, agg, cs, qe, name)
            params = request_params(device, agg, cs, ce, limit_per_group, name)
            if path.exists():
                old = json.loads(path.read_text())
                if old.get("status") == 200 and (old.get("complete")
                                                 or old["request"]["dateEnd"] == params["dateEnd"]):
                    continue                        # nothing new since last fetch
                if old.get("status") != 200 and not retry_errors:
                    continue                        # cached 4xx, e.g. before history start
            if ce <= cs:
                continue
            status, parsed, body, url = client.get(endpoint, params)
            codes = {e.get("code") for e in (parsed or {}).get("errors") or [] if isinstance(e, dict)}
            if status in (401, 403, 429) or status >= 500 or codes & AUTH_ERROR_CODES:
                hint = " (bad token or missing 'Radar Read'?)" if status != 429 else ""
                raise SystemExit(f"HTTP {status} from Radar{hint}: {body[:300]}")
            if status != 200 and (today - ce).days < 365:
                # Recent data surely exists, so this is a bad request, not "before history
                # starts": don't cache it, stop and show the error.
                raise SystemExit(f"HTTP {status} for {url}: {body[:500]}")
            rec = {"request": dict(params, endpoint=endpoint), "status": status,
                   "complete": status == 200 and ce == qe,
                   "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                   "response": parsed if parsed is not None else body}
            path.write_text(json.dumps(rec, indent=1, sort_keys=True) + "\n")
            n = len(((parsed or {}).get("result") or {}).get("serie_0", {}).get("timestamps", []))
            print(f"  {name:<11} {device:<7} {cs}..{ce} -> HTTP {status}, {n} points", file=log)
    return client.request_count


# ---------------------------------------------------------------- parsing

def parse_serie(resp, lo=None, hi=None):
    """Radar timeseries_groups response -> {date: {browser: fraction}}.

    Values come as percentage strings; returned as fractions. Only timestamps in
    [lo, hi) are kept (dateEnd is inclusive, so a chunk may return a partial
    bucket at its end)."""
    serie = (resp.get("result") or {}).get("serie_0") or {}
    stamps = serie.get("timestamps") or []
    out = {}
    for i, ts in enumerate(stamps):
        d = dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).date()
        if (lo and d < lo) or (hi and d >= hi):
            continue
        row = {}
        for name, vals in serie.items():
            if name == "timestamps" or not isinstance(vals, list) or i >= len(vals):
                continue
            v = vals[i]
            if v in (None, ""):
                continue
            row["Other" if name.lower() == "other" else name] = float(v) / 100.0
        out[d] = row
    return out


def load_raw(agg="1d"):
    """All cached 200 responses -> {series: {device: {date: {name: fraction}}}}."""
    data = defaultdict(lambda: defaultdict(dict))
    for path in sorted(RAW_DIR.glob(f"*_{agg}_*.json")):
        rec = json.loads(path.read_text())
        if rec.get("status") != 200 or not isinstance(rec.get("response"), dict):
            continue
        r = rec["request"]
        device = r.get("deviceType", "ALL")
        lo = dt.date.fromisoformat(r["dateStart"][:10])
        hi = dt.date.fromisoformat(r["dateEnd"][:10])
        data[series_of(r)][device].update(parse_serie(rec["response"], lo, hi))
    return data


def exclude_ios(all_os, ios, os_shares):
    """{browser: share of all requests} -> {browser: share of non-iOS requests}.

    Clamped at 0: limitPerGroup can leave a browser in the iOS top N but not in
    the all-OS one, and Radar rounds its percentages."""
    w = os_shares.get("IOS", 0.0)
    if w >= 1:
        return {}
    out = {}
    for b in set(all_os) | set(ios):
        v = (all_os.get(b, 0.0) - w * ios.get(b, 0.0)) / (1 - w)
        if v > 0 or b in all_os:
            out[b] = max(v, 0.0)
    return out


def load_cached(agg="1d"):
    """{device: {date: {browser: share of non-iOS human requests}}}.

    A day is kept only if the OS series and (unless iOS was 0%) the iOS series
    have it too; otherwise iOS couldn't be removed."""
    raw = load_raw(agg)
    data = defaultdict(dict)
    for device, days in raw["browser"].items():
        ios, osw = raw["browser_ios"].get(device, {}), raw["os"].get(device, {})
        for d, row in days.items():
            if d in osw and (d in ios or osw[d].get("IOS", 0.0) == 0):
                data[device][d] = exclude_ios(row, ios.get(d, {}), osw[d])
    return data


# ---------------------------------------------------------------- normalisation

def period_of(d, granularity):
    """(label, start, end_inclusive) of the ISO week / calendar month / day containing d."""
    if granularity == "week":
        y, w, wd = d.isocalendar()
        s = d - dt.timedelta(days=wd - 1)
        return f"{y}-W{w:02d}", s, s + dt.timedelta(days=6)
    if granularity == "month":
        s = d.replace(day=1)
        nxt = (s + dt.timedelta(days=32)).replace(day=1)
        return f"{d.year}-{d.month:02d}", s, nxt - dt.timedelta(days=1)
    return d.isoformat(), d, d


def renormalize(shares, browsers):
    """{browser: raw_share} -> {browser: chromium_share or None}.

    chromium_share: among is_chromium browsers, WebViews and in-app browsers
    (COUNTED_KINDS). Non-Chromium, bots, TVs and unknown names get None."""
    def counted(b):
        c = browsers.get(b)
        return bool(c) and c["is_chromium"] and c["kind"] in COUNTED_KINDS
    tot = sum(v for b, v in shares.items() if counted(b))
    return {b: (v / tot if counted(b) and tot > 0 else None) for b, v in shares.items()}


def aggregate(daily, granularity):
    """{date: {browser: share}} -> {(label, start, end): (days, {browser: mean share})}.

    Mean of daily shares over the days present (a browser absent on a day counts 0)."""
    groups = defaultdict(list)
    for d, row in daily.items():
        groups[period_of(d, granularity)].append(row)
    out = {}
    for key, rows in groups.items():
        names = set().union(*rows)
        out[key] = (len(rows), {b: sum(r.get(b, 0.0) for r in rows) / len(rows) for b in names})
    return out


def build_rows(data, browsers, granularities=("week", "month")):
    rows = []
    for device in sorted(data):
        for gran in granularities:
            for (label, s, e), (days, shares) in sorted(aggregate(data[device], gran).items()):
                norm = renormalize(shares, browsers)
                for b in sorted(shares, key=lambda b: -shares[b]):
                    c = browsers.get(b)
                    cs = norm[b]
                    rows.append({
                        "period": label, "period_start": s.isoformat(), "period_end": e.isoformat(),
                        "granularity": gran, "device": device.lower(), "browser": b,
                        "is_chromium": "" if c is None else int(c["is_chromium"]),
                        "kind": "" if c is None else c["kind"], "days": days,
                        "raw_share": f"{shares[b]:.6f}",
                        "chromium_share": "" if cs is None else f"{cs:.6f}"})
    return rows


def write_table(agg="1d", out=OUT_CSV, log=sys.stderr):
    browsers = load_browsers()
    data = load_cached(agg)
    unknown = sorted({b for dev in data.values() for row in dev.values() for b in row} - set(browsers))
    if unknown:
        print(f"  WARNING: browsers not in config/browsers.csv (treated as non-Chromium): "
              f"{', '.join(unknown)}", file=log)
    rows = build_rows(data, browsers, ("week", "month") if agg == "1d" else ("week",))
    if not rows:
        print("  no cached Radar data; nothing written", file=log)
        return rows
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".csv.tmp")
    with open(tmp, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        w.writerows(rows)
    tmp.replace(out)
    return rows


def run(start=DEFAULT_START, agg="1d", offline=False, limit_per_group=DEFAULT_LIMIT_PER_GROUP,
        retry_errors=False, min_interval=1.0, log=sys.stderr):
    if not offline:
        n = fetch(start=start, agg=agg, limit_per_group=limit_per_group, retry_errors=retry_errors,
                  min_interval=min_interval, log=log)
        print(f"  {n} requests", file=log)
    rows = write_table(agg=agg, log=log)
    if rows:
        print(f"  wrote {len(rows)} rows to {OUT_CSV.relative_to(ROOT)}", file=log)
    return rows
