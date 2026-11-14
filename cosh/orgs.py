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

OrgResolver() reads the local config/affiliations.json5 and never fetches.
`python3 -m cosh update-affiliations` (update_affiliations) is the one step
that refreshes it, together with config/org-list.txt from the same directory
of chromium/src main: two small requests to googlesource. `cosh update` runs
it before the steps that attribute orgs (config/dataflow.json). A file is
rewritten only when it changed; commit it with the outputs.
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
ORG_LIST_PATH = os.path.join(ROOT, "config", "org-list.txt")
SOURCE_DIR_URL = ("https://chromium.googlesource.com/chromium/src/+/main/"
                  "third_party/blink/tools/commit_stats/")
AFFILIATIONS_URL = SOURCE_DIR_URL + "affiliations.json5"
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


class OrgResolver:
    def __init__(self, affiliations=None):
        if affiliations is None:
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


def _fetch(name):
    import base64
    req = urllib.request.Request(SOURCE_DIR_URL + name + "?format=TEXT", headers=http_headers())
    with urllib.request.urlopen(req, timeout=60) as r:
        return base64.b64decode(r.read()).decode("utf-8")


def update_affiliations(config_dir=os.path.dirname(AFFILIATIONS_PATH)):
    """Fetch affiliations.json5 and org-list.txt from chromium/src main into
    `config_dir`, rewriting each (and the source note) only if its content
    changed. Both are fetched before either is written, so a failed fetch
    changes nothing. -> the names of the files that changed."""
    from datetime import datetime, timezone
    names = ("affiliations.json5", "org-list.txt")
    texts = {n: _fetch(n) for n in names}
    parse_json5(texts["affiliations.json5"])      # validate before replacing
    changed = []
    for n in names:
        path = os.path.join(config_dir, n)
        try:
            with open(path) as f:
                if f.read() == texts[n]:
                    continue
        except FileNotFoundError:
            pass
        with open(path + ".tmp", "w") as f:       # atomic: analyses may read it meanwhile
            f.write(texts[n])
        os.replace(path + ".tmp", path)
        changed.append(n)
    if changed:
        with open(os.path.join(config_dir, "affiliations.source.txt"), "w") as f:
            f.write(f"config/affiliations.json5 and config/org-list.txt are verbatim copies of the files\n"
                    f"of the same names in {SOURCE_DIR_URL}\n"
                    f"fetched {datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ} by "
                    "python3 -m cosh update-affiliations (cosh/orgs.py).\n")
    return changed
