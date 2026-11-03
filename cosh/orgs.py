"""Email -> organization attribution.

Rules (in order), evaluated at the CL's submit date:
  1. If the email is listed in config/affiliations.json5 (Chromium's own
     third_party/blink/tools/commit_stats/affiliations.json5), use the domain of
     the most recent affiliation whose start <= date. Before its earliest start,
     fall through to the rules below.
  2. Any other @chromium.org account -> google.com.
  3. Otherwise the email's domain.
The "org" is therefore a domain name (or "Individual"/"Undisclosed" when the
affiliations file says so).
"""

import json
import os
import re
import urllib.request

from .contact import HTTP_HEADERS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AFFILIATIONS_PATH = os.path.join(ROOT, "config", "affiliations.json5")
AFFILIATIONS_URL = ("https://chromium.googlesource.com/chromium/src/+/main/"
                    "third_party/blink/tools/commit_stats/affiliations.json5")
NO_EMAIL = "(no email)"


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


class OrgResolver:
    def __init__(self, affiliations=None):
        self.aff = load_affiliations() if affiliations is None else affiliations

    def __call__(self, email, date=None):
        """date: 'YYYY-MM-DD...' string (CL submit time); None = today."""
        email = (email or "").strip().lower()
        if "@" not in email:
            return NO_EMAIL
        for start, domain in self.aff.get(email, ()):
            if date is None or date[:10] >= start:
                return domain
        domain = email.rpartition("@")[2]
        if domain == "chromium.org":
            return "google.com"
        return domain


def update_affiliations(path=AFFILIATIONS_PATH):
    import base64
    from datetime import datetime, timezone
    req = urllib.request.Request(AFFILIATIONS_URL + "?format=TEXT",
                                 headers=HTTP_HEADERS)
    with urllib.request.urlopen(req, timeout=60) as r:
        text = base64.b64decode(r.read()).decode("utf-8")
    parse_json5(text)                       # validate before replacing
    with open(path, "w") as f:
        f.write(text)
    with open(os.path.join(os.path.dirname(path), "affiliations.source.txt"), "w") as f:
        f.write(f"config/affiliations.json5 is a verbatim copy of\n{AFFILIATIONS_URL}\n"
                f"fetched {datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ}. "
                "Refresh with: python3 -m cosh update-affiliations\n")
