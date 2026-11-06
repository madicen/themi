"""One TLS context for every HTTP client Themi opens.

httpx builds a fresh SSL context, and re-reads the certificate bundle, for each
client unless it is given one. The Google connectors open a client per request,
so sharing this context saves that work every time (most noticeable on a Pi).
It's the same context httpx would make: certifi's bundle, or SSL_CERT_FILE and
SSL_CERT_DIR when they're set.
"""

from __future__ import annotations

import ssl
from functools import cache

import httpx


@cache
def tls() -> ssl.SSLContext:
    return httpx.create_ssl_context()
