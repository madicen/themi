"""A local fake of the S3 API subset backups use: put, get, delete and ListObjectsV2.

    fake_s3.objects                      # key -> bytes, for one bucket
    fake_s3.fail("put", 503, times=2)    # the next two uploads fail
    fake_s3.page_size = 2                # to exercise list paging

Every request must carry a valid AWS Signature V4 for the test credentials
(checked with the same canonical form AWS documents; the signer itself is pinned
to AWS's published test vector in tests/unit/test_s3_signing.py).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from xml.sax.saxutils import escape

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import Response

from tests.fakes._server import BackgroundServer
from themi import clock
from themi.backup.s3 import S3Config, sign
from themi.storage.secrets import Secret

BUCKET = "themi-backups"
ACCESS_KEY = "TESTACCESSKEY"
SECRET_KEY = "test/secret+key"
REGION = "auto"
CREDENTIAL = re.compile(r"Credential=([^/]+)/(\d{8})/([^/]+)/s3/aws4_request")


class FakeS3:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.modified: dict[str, datetime] = {}
        self.failures: dict[str, list[int]] = {}
        self.calls: list[str] = []
        self.page_size = 1000
        self.app = FastAPI()
        self.app.add_api_route(f"/{BUCKET}", self._list, methods=["GET"])
        self.app.add_api_route(
            f"/{BUCKET}/{{key:path}}", self._object, methods=["GET", "PUT", "DELETE"]
        )
        self._background = BackgroundServer(self.app)

    @property
    def url(self) -> str:
        return self._background.url

    def config(self, secret: str = SECRET_KEY) -> S3Config:
        return S3Config(self.url, BUCKET, ACCESS_KEY, Secret(secret), REGION)

    def start(self) -> None:
        self._background.start()

    def stop(self) -> None:
        self._background.stop()

    def reset(self) -> None:
        self.objects, self.modified, self.failures, self.calls = {}, {}, {}, []
        self.page_size = 1000

    def fail(self, op: str, status: int, *, times: int = 1) -> None:
        """Ops: put, get, delete, list."""
        self.failures.setdefault(op, []).extend([status] * times)

    def put_object(self, key: str, data: bytes) -> None:
        """Store something directly, as if uploaded earlier."""
        self.objects[key] = data
        self.modified[key] = clock.now().astimezone(UTC)

    # ----- plumbing -----------------------------------------------------------

    async def _check(self, request: Request, op: str) -> Response | None:
        self.calls.append(op)
        body = await request.body()
        header = request.headers.get("authorization", "")
        match = CREDENTIAL.search(header)
        sent_hash = request.headers.get("x-amz-content-sha256", "")
        if match is None or match.group(1) != ACCESS_KEY:
            return _error(403, "InvalidAccessKeyId")
        if sent_hash != hashlib.sha256(body).hexdigest():
            return _error(400, "XAmzContentSHA256Mismatch")
        signed = re.search(r"SignedHeaders=([^,]+)", header)
        names = signed.group(1).split(";") if signed else []
        headers = {n: request.headers.get(n, "") for n in names}
        url = str(request.url)
        expected = sign(
            request.method,
            url,
            headers,
            sent_hash,
            access_key=ACCESS_KEY,
            secret=SECRET_KEY,
            region=match.group(3),
            service="s3",
            amz_date=request.headers.get("x-amz-date", ""),
        )
        if expected != header:
            return _error(403, "SignatureDoesNotMatch")
        queued = self.failures.get(op)
        if queued:
            return _error(queued.pop(0), "SlowDown")
        return None

    async def _object(self, request: Request, key: str) -> Response:
        op = {"GET": "get", "PUT": "put", "DELETE": "delete"}[request.method]
        problem = await self._check(request, op)
        if problem is not None:
            return problem
        if op == "put":
            self.put_object(key, await request.body())
            return Response(status_code=200, headers={"ETag": '"x"'})
        if op == "delete":
            self.objects.pop(key, None)
            self.modified.pop(key, None)
            return Response(status_code=204)
        if key not in self.objects:
            return _error(404, "NoSuchKey")
        return Response(self.objects[key], media_type="application/octet-stream")

    async def _list(self, request: Request) -> Response:
        problem = await self._check(request, "list")
        if problem is not None:
            return problem
        prefix = request.query_params.get("prefix", "")
        start = int(request.query_params.get("continuation-token") or 0)
        keys = sorted(k for k in self.objects if k.startswith(prefix))
        page = keys[start : start + self.page_size]
        truncated = start + self.page_size < len(keys)
        contents = "".join(
            f"<Contents><Key>{escape(k)}</Key><Size>{len(self.objects[k])}</Size>"
            f"<LastModified>{self.modified[k].strftime('%Y-%m-%dT%H:%M:%S.000Z')}</LastModified>"
            "</Contents>"
            for k in page
        )
        token = (
            f"<NextContinuationToken>{start + self.page_size}</NextContinuationToken>"
            if truncated
            else ""
        )
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
            f"<Name>{BUCKET}</Name><Prefix>{escape(prefix)}</Prefix>"
            f"<IsTruncated>{'true' if truncated else 'false'}</IsTruncated>{token}{contents}"
            "</ListBucketResult>"
        )
        return Response(xml, media_type="application/xml")


def _error(status: int, code: str) -> Response:
    xml = f"<Error><Code>{code}</Code><Message>fake</Message></Error>"
    return Response(xml, status_code=status, media_type="application/xml")


@pytest.fixture(scope="session")
def _fake_s3_server() -> Iterator[FakeS3]:
    server = FakeS3()
    server.start()
    yield server
    server.stop()


@pytest.fixture
def fake_s3(_fake_s3_server: FakeS3) -> FakeS3:
    _fake_s3_server.reset()
    return _fake_s3_server
