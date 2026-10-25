"""A local fake of Google's OAuth endpoints: authorize, token, revoke and userinfo.

    async def test_linking(fake_google, ...):
        url = oauth.authorization_url("link", REDIRECT, erin)
        callback = fake_google.consent(url, "erin@gmail.com")   # as if Erin clicked Allow
        ...

It checks what Google checks: the client id and secret, a registered redirect
address, a single-use code, the PKCE verifier against the S256 challenge, and
refresh tokens that stop working once revoked. Addresses are "verified" unless
added with `add_account(..., verified=False)`.

For trying Themi by hand, opening the authorize URL in a browser shows a tiny
form that asks which address to "sign in" as.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from html import escape
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from tests.fakes._server import BackgroundServer
from themi.connectors.google.oauth import GoogleConfig
from themi.storage.secrets import Secret

CLIENT_ID = "themi-test.apps.googleusercontent.com"
CLIENT_SECRET = "fake-google-client-secret"
REDIRECT_URI = "http://themi.test/auth/google/callback"


@dataclass
class _Code:
    email: str
    client_id: str
    redirect_uri: str
    challenge: str
    scopes: tuple[str, ...]
    offline: bool


@dataclass
class _Refresh:
    email: str
    scopes: tuple[str, ...]
    revoked: bool = False


@dataclass
class FakeGoogleState:
    verified: dict[str, bool] = field(default_factory=dict)  # address -> email_verified
    redirect_uris: set[str] = field(default_factory=lambda: {REDIRECT_URI})
    codes: dict[str, _Code] = field(default_factory=dict)
    refresh_tokens: dict[str, _Refresh] = field(default_factory=dict)
    access_tokens: dict[str, str] = field(default_factory=dict)  # token -> address
    revoked: list[str] = field(default_factory=list)  # every token sent to /revoke
    token_requests: list[dict[str, str]] = field(default_factory=list)


def _challenge(verifier: str) -> str:
    return (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )


def _error(status: int, error: str, description: str = "") -> JSONResponse:
    return JSONResponse({"error": error, "error_description": description}, status_code=status)


class FakeGoogle:
    def __init__(self) -> None:
        self.state = FakeGoogleState()
        self._lock = threading.Lock()
        self.app = FastAPI()
        self.app.add_api_route("/o/oauth2/v2/auth", self._authorize_page, methods=["GET"])
        self.app.add_api_route("/o/oauth2/v2/auth", self._authorize_form, methods=["POST"])
        self.app.add_api_route("/token", self._token, methods=["POST"])
        self.app.add_api_route("/revoke", self._revoke, methods=["POST"])
        self.app.add_api_route("/v1/userinfo", self._userinfo, methods=["GET"])
        self._background = BackgroundServer(self.app)

    # ----- wiring -------------------------------------------------------------

    @property
    def url(self) -> str:
        return self._background.url

    def config(self) -> GoogleConfig:
        return GoogleConfig(
            CLIENT_ID,
            Secret(CLIENT_SECRET),
            auth_url=f"{self.url}/o/oauth2/v2/auth",
            token_url=f"{self.url}/token",
            revoke_url=f"{self.url}/revoke",
            userinfo_url=f"{self.url}/v1/userinfo",
        )

    def start(self) -> None:
        self._background.start()

    def stop(self) -> None:
        self._background.stop()

    def reset(self) -> None:
        with self._lock:
            self.state = FakeGoogleState()

    # ----- test controls ------------------------------------------------------

    def add_account(self, address: str, *, verified: bool = True) -> None:
        self.state.verified[address.lower()] = verified

    def consent(
        self, authorize_url: str, address: str, *, scopes: tuple[str, ...] | None = None
    ) -> str:
        """The person picks `address` and clicks Allow; returns the callback URL.

        `scopes` narrows what they tick (Google lets people untick optional scopes).
        """
        params = {k: v[0] for k, v in parse_qs(urlparse(authorize_url).query).items()}
        return self._grant(params, address, scopes)

    def deny(self, authorize_url: str) -> str:
        params = {k: v[0] for k, v in parse_qs(urlparse(authorize_url).query).items()}
        query = urlencode({"error": "access_denied", "state": params.get("state", "")})
        return f"{params['redirect_uri']}?{query}"

    def revoke_everything_for(self, address: str) -> None:
        """As if the person removed Themi at myaccount.google.com/permissions."""
        with self._lock:
            for refresh in self.state.refresh_tokens.values():
                if refresh.email == address:
                    refresh.revoked = True

    def live_refresh_tokens(self, address: str) -> list[str]:
        return [
            token
            for token, refresh in self.state.refresh_tokens.items()
            if refresh.email == address and not refresh.revoked
        ]

    # ----- authorize ----------------------------------------------------------

    def _grant(self, params: dict[str, str], address: str, scopes: tuple[str, ...] | None) -> str:
        if params.get("client_id") != CLIENT_ID:
            raise AssertionError("authorize: unknown client_id")
        if params.get("redirect_uri") not in self.state.redirect_uris:
            raise AssertionError(
                f"authorize: unregistered redirect_uri {params.get('redirect_uri')}"
            )
        if params.get("response_type") != "code":
            raise AssertionError("authorize: response_type must be code")
        if params.get("code_challenge_method") != "S256" or not params.get("code_challenge"):
            raise AssertionError("authorize: Themi always sends an S256 PKCE challenge")
        address = address.lower()
        self.state.verified.setdefault(address, True)
        requested = tuple(params.get("scope", "").split())
        granted = requested if scopes is None else tuple(s for s in requested if s in scopes)
        code = secrets.token_urlsafe(16)
        with self._lock:
            self.state.codes[code] = _Code(
                address,
                params["client_id"],
                params["redirect_uri"],
                params["code_challenge"],
                granted,
                params.get("access_type") == "offline",
            )
        query = urlencode(
            {"code": code, "state": params.get("state", ""), "scope": " ".join(granted)}
        )
        return f"{params['redirect_uri']}?{query}"

    async def _authorize_page(self, request: Request) -> HTMLResponse:
        hidden = "".join(
            f'<input type="hidden" name="{escape(k)}" value="{escape(v)}">'
            for k, v in request.query_params.items()
        )
        return HTMLResponse(
            "<!doctype html><title>Fake Google</title><h1>Fake Google sign-in</h1>"
            f'<form method="post">{hidden}<label>Address <input name="address" '
            'value="erin@example.com"></label> <button>Allow</button></form>'
        )

    async def _authorize_form(self, request: Request) -> Response:
        form = {k: str(v) for k, v in (await request.form()).items()}
        address = form.pop("address")
        return RedirectResponse(self._grant(form, address, None), status_code=302)

    # ----- token, revoke, userinfo --------------------------------------------

    def _issue_access(self, address: str) -> str:
        token = f"ya29.fake-{secrets.token_urlsafe(12)}"
        self.state.access_tokens[token] = address
        return token

    async def _token(self, request: Request) -> JSONResponse:
        form = {k: str(v) for k, v in (await request.form()).items()}
        with self._lock:
            self.state.token_requests.append(form)
            if form.get("client_id") != CLIENT_ID or form.get("client_secret") != CLIENT_SECRET:
                return _error(401, "invalid_client", "The OAuth client was not found.")
            grant_type = form.get("grant_type")
            if grant_type == "authorization_code":
                return self._exchange_code(form)
            if grant_type == "refresh_token":
                refresh = self.state.refresh_tokens.get(form.get("refresh_token", ""))
                if refresh is None or refresh.revoked:
                    return _error(400, "invalid_grant", "Token has been expired or revoked.")
                return JSONResponse(
                    {
                        "access_token": self._issue_access(refresh.email),
                        "expires_in": 3599,
                        "scope": " ".join(refresh.scopes),
                        "token_type": "Bearer",
                    }
                )
            return _error(400, "unsupported_grant_type")

    def _exchange_code(self, form: dict[str, str]) -> JSONResponse:
        code = self.state.codes.pop(form.get("code", ""), None)  # single use
        if code is None:
            return _error(400, "invalid_grant", "Malformed auth code.")
        if form.get("redirect_uri") != code.redirect_uri:
            return _error(400, "redirect_uri_mismatch", "Bad Request")
        if _challenge(form.get("code_verifier", "")) != code.challenge:
            return _error(400, "invalid_grant", "Invalid code verifier.")
        body: dict[str, Any] = {
            "access_token": self._issue_access(code.email),
            "expires_in": 3599,
            "scope": " ".join(code.scopes),
            "token_type": "Bearer",
        }
        if code.offline:
            refresh = f"1//fake-{secrets.token_urlsafe(16)}"
            self.state.refresh_tokens[refresh] = _Refresh(code.email, code.scopes)
            body["refresh_token"] = refresh
        return JSONResponse(body)

    async def _revoke(self, request: Request) -> JSONResponse:
        token = str((await request.form()).get("token", ""))
        with self._lock:
            self.state.revoked.append(token)
            if token in self.state.refresh_tokens:
                self.state.refresh_tokens[token].revoked = True
                return JSONResponse({})
            if self.state.access_tokens.pop(token, None) is not None:
                return JSONResponse({})
        return _error(400, "invalid_token", "Token expired or revoked")

    async def _userinfo(self, request: Request) -> JSONResponse:
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        address = self.state.access_tokens.get(token)
        if address is None:
            return _error(401, "invalid_token")
        return JSONResponse(
            {
                "sub": hashlib.sha256(address.encode()).hexdigest()[:21],
                "email": address,
                "email_verified": self.state.verified.get(address, True),
            }
        )


@pytest.fixture(scope="session")
def _fake_google_server() -> Iterator[FakeGoogle]:
    server = FakeGoogle()
    server.start()
    yield server
    server.stop()


@pytest.fixture
def fake_google(_fake_google_server: FakeGoogle) -> FakeGoogle:
    _fake_google_server.reset()
    return _fake_google_server


if __name__ == "__main__":  # a fake Google for trying sign-in and linking by hand
    import uvicorn

    fake = FakeGoogle()
    port = 8765
    base = f"http://127.0.0.1:{port}"
    fake.state.redirect_uris |= {
        "http://localhost:8080/auth/google/callback",
        "http://127.0.0.1:8080/auth/google/callback",
    }
    print("Fake Google is running. Put these in .env and restart Themi:")
    print(f"GOOGLE_CLIENT_ID={CLIENT_ID}\nGOOGLE_CLIENT_SECRET={CLIENT_SECRET}")
    print(f"GOOGLE_AUTH_URL={base}/o/oauth2/v2/auth\nGOOGLE_TOKEN_URL={base}/token")
    print(f"GOOGLE_REVOKE_URL={base}/revoke\nGOOGLE_USERINFO_URL={base}/v1/userinfo", flush=True)
    uvicorn.run(fake.app, host="127.0.0.1", port=port, log_level="warning")
