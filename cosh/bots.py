"""Bot / service-account detection. Primary signal is Gerrit's SERVICE_USER
account tag; the regex list in config/bots.txt is a backstop."""

import os
import re

_CONFIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "config", "bots.txt")


def _load_patterns():
    pats = []
    try:
        with open(_CONFIG) as f:
            for line in f:
                line = line.split("#", 1)[0].strip()
                if line:
                    pats.append(re.compile(line, re.I))
    except FileNotFoundError:
        pass
    return pats


_PATTERNS = _load_patterns()


def is_bot_account(acct):
    if "SERVICE_USER" in (acct.get("tags") or []):
        return True
    email = acct.get("email") or ""
    return any(p.search(email) for p in _PATTERNS)
