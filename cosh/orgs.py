"""Email -> organization attribution.

Rules (in order), evaluated at the CL's submit date:
  1. If the email is listed in config/affiliations.json5 (Chromium's own
     third_party/blink/tools/commit_stats/affiliations.json5), use the domain of
     the most recent affiliation whose start <= date. Before its earliest start,
     fall through to the rules below.
  2. Any other @chromium.org account -> google.com.
  3. Otherwise the email's domain.
  4. Finally, a domain an org used to use is renamed to its current one
     (DOMAIN_ALIASES: fb.com, Facebook's old corporate domain -> meta.com).
The "org" is therefore a domain name (or "Individual"/"Undisclosed" when the
affiliations file says so).

OrgResolver() (no arguments, as every analysis uses it) first refreshes
config/affiliations.json5 from chromium/src main, once per process: one small
request to googlesource, so no analysis runs on a stale copy. The file is
rewritten only when it changed, with a note on stderr to commit it alongside
the outputs. A failed fetch is an error; COSH_AFFILIATIONS_OFFLINE=1 uses the
local copy as it is.
"""

import hashlib
import json
import os
import re
import sys
import urllib.request

from .contact import http_headers

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AFFILIATIONS_PATH = os.path.join(ROOT, "config", "affiliations.json5")
AFFILIATIONS_URL = ("https://chromium.googlesource.com/chromium/src/+/main/"
                    "third_party/blink/tools/commit_stats/affiliations.json5")
NO_EMAIL = "(no email)"
# Former domain -> the org's current one. Meta employees used @fb.com addresses.
DOMAIN_ALIASES = {"fb.com": "meta.com"}


def parse_json5(text):
    """Minimal JSON5 subset reader: comments, unquoted keys, trailing commas,
    double-quoted strings. Enough for affiliations.json5."""
    out, i, n = [], 0, len(text)
    while i < n:
        ch = text[i]
        if ch == '"':                                   # copy string verbatim
            j = i + 1
            while text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            out.append(text[i:j + 1])
            i = j + 1
        elif text.startswith("//", i):
            i = text.find("\n", i) if "\n" in text[i:] else n
        elif text.startswith("/*", i):
            i = text.index("*/", i) + 2
        else:
            out.append(ch)
            i += 1
    s = "".join(out)
    s = re.sub(r'([{,]\s*)([A-Za-z_$][\w$]*)\s*:', r'\1"\2":', s)   # quote bare keys
    s = re.sub(r',(\s*[}\]])', r'\1', s)                            # trailing commas
    return json.loads(s)


def load_affiliations(path=AFFILIATIONS_PATH):
    """-> {email: [(start 'YYYY-MM-DD', domain), ...] sorted newest first}."""
    with open(path) as f:
        data = parse_json5(f.read())
    return {email.lower(): sorted(((a["start"], a["domain"]) for a in v["affiliations"]),
                                  reverse=True)
            for email, v in data.items()}


def affiliations_digest(path=AFFILIATIONS_PATH):
    """Short content hash of the affiliations file, for caches that store
    resolved orgs."""
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:16]


_refreshed = set()


def refresh_affiliations(path=AFFILIATIONS_PATH):
    """Fetch the current file from chromium/src main, once per process per path.
    COSH_AFFILIATIONS_OFFLINE=1 skips it; a failed fetch raises SystemExit."""
    if path in _refreshed or os.environ.get("COSH_AFFILIATIONS_OFFLINE") == "1":
        return
    try:
        changed = update_affiliations(path)
    except Exception as e:
        raise SystemExit(f"cosh.orgs: could not refresh {path} from {AFFILIATIONS_URL}: {e}\n"
                         "Set COSH_AFFILIATIONS_OFFLINE=1 to use the local copy as it is.")
    _refreshed.add(path)
    if changed:
        print(f"cosh.orgs: {os.path.relpath(path)} was out of date and has been updated; "
              "commit it with the outputs", file=sys.stderr)


class OrgResolver:
    def __init__(self, affiliations=None):
        if affiliations is None:
            refresh_affiliations()
            affiliations = load_affiliations()
        self.aff = affiliations

    def __call__(self, email, date=None):
        """date: 'YYYY-MM-DD...' string (CL submit time); None = today."""
        email = (email or "").strip().lower()
        if "@" not in email:
            return NO_EMAIL
        for start, domain in self.aff.get(email, ()):
            if date is None or date[:10] >= start:
                return DOMAIN_ALIASES.get(domain, domain)
        domain = email.rpartition("@")[2]
        if domain == "chromium.org":
            return "google.com"
        return DOMAIN_ALIASES.get(domain, domain)


def update_affiliations(path=AFFILIATIONS_PATH):
    """Fetch the file from chromium/src main; rewrite it (and the source note)
    only if its content changed. -> True if it changed."""
    import base64
    from datetime import datetime, timezone
    req = urllib.request.Request(AFFILIATIONS_URL + "?format=TEXT",
                                 headers=http_headers())
    with urllib.request.urlopen(req, timeout=60) as r:
        text = base64.b64decode(r.read()).decode("utf-8")
    parse_json5(text)                       # validate before replacing
    try:
        with open(path) as f:
            if f.read() == text:
                return False
    except FileNotFoundError:
        pass
    with open(path + ".tmp", "w") as f:     # atomic: analyses may run side by side
        f.write(text)
    os.replace(path + ".tmp", path)
    with open(os.path.join(os.path.dirname(path), "affiliations.source.txt"), "w") as f:
        f.write(f"config/affiliations.json5 is a verbatim copy of\n{AFFILIATIONS_URL}\n"
                f"fetched {datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ}. "
                "Every OrgResolver() refreshes it (cosh/orgs.py); by hand: "
                "python3 -m cosh update-affiliations\n")
    return True
