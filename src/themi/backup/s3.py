"""A small S3-compatible client over `httpx`, for Cloudflare R2 and Backblaze B2.

Only what backups need: put, get, list (one prefix) and delete, with AWS
Signature Version 4 and path-style addresses (`<endpoint>/<bucket>/<key>`),
which both services accept. The signer is checked against AWS's published
test vector.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import quote, urlsplit
from xml.etree import ElementTree

import httpx

from themi import clock
from themi.storage.secrets import Secret

TIMEOUT = 60.0
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


class S3Error(Exception):
    pass


@dataclass(frozen=True)
class S3Config:
    endpoint: str  # e.g. https://<account>.r2.cloudflarestorage.com
    bucket: str
    access_key_id: str
    secret_access_key: Secret = field(repr=False)
    region: str = "auto"  # R2 uses "auto"; B2 uses its region, e.g. us-west-004


@dataclass(frozen=True)
class S3Object:
    key: str
    size: int
    last_modified: datetime


def _hmac(key: bytes, text: str) -> bytes:
    return hmac.new(key, text.encode(), hashlib.sha256).digest()


def signing_key(secret: str, date: str, region: str, service: str) -> bytes:
    k = _hmac(f"AWS4{secret}".encode(), date)
    k = _hmac(k, region)
    k = _hmac(k, service)
    return _hmac(k, "aws4_request")


def sign(
    method: str,
    url: str,
    headers: dict[str, str],
    payload_hash: str,
    *,
    access_key: str,
    secret: str,
    region: str,
    service: str,
    amz_date: str,
) -> str:
    """The Authorization header for a request. `headers` must include host and x-amz-date."""
    parts = urlsplit(url)
    path = quote(parts.path or "/", safe="/-_.~")
    query = "&".join(
        sorted(
            f"{quote(k, safe='-_.~')}={quote(v, safe='-_.~')}"
            for k, _, v in (p.partition("=") for p in parts.query.split("&") if p)
        )
    )
    names = sorted(h.lower() for h in headers)
    lowered = {k.lower(): " ".join(str(v).split()) for k, v in headers.items()}
    canonical_headers = "".join(f"{n}:{lowered[n]}\n" for n in names)
    signed = ";".join(names)
    canonical = "\n".join([method, path, query, canonical_headers, signed, payload_hash])
    date = amz_date[:8]
    scope = f"{date}/{region}/{service}/aws4_request"
    to_sign = "\n".join(
        ["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical.encode()).hexdigest()]
    )
    signature = hmac.new(
        signing_key(secret, date, region, service), to_sign.encode(), hashlib.sha256
    ).hexdigest()
    return (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, SignedHeaders={signed}, "
        f"Signature={signature}"
    )


class S3Client:
    def __init__(self, config: S3Config) -> None:
        self.config = config

    def _url(self, key: str = "") -> str:
        base = f"{self.config.endpoint.rstrip('/')}/{self.config.bucket}"
        return f"{base}/{quote(key, safe='/-_.~')}" if key else base

    async def _request(
        self, method: str, url: str, body: bytes = b"", params: dict[str, str] | None = None
    ) -> httpx.Response:
        if params:
            url = url + "?" + "&".join(f"{k}={quote(v, safe='-_.~')}" for k, v in params.items())
        payload_hash = hashlib.sha256(body).hexdigest() if body else EMPTY_SHA256
        amz_date = clock.now().strftime("%Y%m%dT%H%M%SZ")
        headers = {
            "host": urlsplit(url).netloc,
            "x-amz-date": amz_date,
            "x-amz-content-sha256": payload_hash,
        }
        headers["authorization"] = sign(
            method,
            url,
            {k: v for k, v in headers.items()},
            payload_hash,
            access_key=self.config.access_key_id,
            secret=self.config.secret_access_key.reveal(),
            region=self.config.region,
            service="s3",
            amz_date=amz_date,
        )
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                response = await client.request(method, url, content=body or None, headers=headers)
        except httpx.HTTPError as exc:
            raise S3Error(f"the backup storage couldn't be reached ({type(exc).__name__})") from exc
        if response.status_code >= 300:
            raise S3Error(
                f"the backup storage answered HTTP {response.status_code}: {_code(response)}"
            )
        return response

    async def put(self, key: str, data: bytes) -> None:
        await self._request("PUT", self._url(key), data)

    async def get(self, key: str) -> bytes:
        return (await self._request("GET", self._url(key))).content

    async def delete(self, key: str) -> None:
        await self._request("DELETE", self._url(key))

    async def list(self, prefix: str) -> list[S3Object]:
        objects: list[S3Object] = []
        token: str | None = None
        while True:
            params = {"list-type": "2", "prefix": prefix}
            if token:
                params["continuation-token"] = token
            response = await self._request("GET", self._url(), params=params)
            root = ElementTree.fromstring(response.content)
            for item in _children(root, "Contents"):
                key, size, modified = (_text(item, t) for t in ("Key", "Size", "LastModified"))
                if key and size is not None and modified:
                    objects.append(
                        S3Object(
                            key, int(size), datetime.fromisoformat(modified.replace("Z", "+00:00"))
                        )
                    )
            token = _text(root, "NextContinuationToken")
            if _text(root, "IsTruncated") != "true" or not token:
                return objects


def _local(tag: str) -> str:
    """An XML tag without its namespace ("{http://s3...}Key" -> "Key")."""
    return tag.rsplit("}", 1)[-1]


def _children(element: ElementTree.Element, name: str) -> list[ElementTree.Element]:
    return [child for child in element if _local(child.tag) == name]


def _text(element: ElementTree.Element, name: str) -> str | None:
    found = _children(element, name)
    return found[0].text if found else None


def _code(response: httpx.Response) -> str:
    try:
        root = ElementTree.fromstring(response.content)
    except ElementTree.ParseError:
        return "no details"
    code = next((e.text for e in root.iter() if e.tag.endswith("Code")), None)
    return code or "no details"
