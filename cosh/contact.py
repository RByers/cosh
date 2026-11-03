"""Who we are, sent with every request so server operators can reach us.

Override with the COSH_CONTACT environment variable."""

import os

CONTACT = os.environ.get("COSH_CONTACT", "rick@rbyers.net")
VERSION = "0.1"
PROJECT = "Chromium Open Source Health research"

# HTTP (REST): User-Agent plus the RFC 9110 `From` header, which exists for
# exactly this purpose (contact address of the human running an automated client).
USER_AGENT = f"cosh/{VERSION} ({PROJECT}; low-rate; contact: {CONTACT})"
HTTP_HEADERS = {"User-Agent": USER_AGENT, "From": CONTACT}

# git: GIT_USER_AGENT sets both the HTTP User-Agent header and the protocol v2
# `agent=` capability (git replaces spaces there with '.'); http.extraHeader
# adds the From header to the smart-HTTP requests.
GIT_ENV = {"GIT_USER_AGENT": f"git/cosh-{VERSION} ({PROJECT}; contact: {CONTACT})"}
GIT_CONFIG = ["-c", f"http.extraHeader=From: {CONTACT}"]
