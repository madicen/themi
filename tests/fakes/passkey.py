"""SP7b: a fake authenticator (a phone's passkey), for the tests.

It makes a real P-256 key and answers WebAuthn ceremonies the way a browser and a platform
authenticator would: a "none" attestation to register, an ECDSA signature to sign in. Only
what py_webauthn checks is built; nothing reaches a network.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import struct
from typing import Any

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class FakeAuthenticator:
    def __init__(self, origin: str, rp_id: str) -> None:
        self.origin = origin
        self.rp_id = rp_id
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = os.urandom(16)
        self.user_handle = b""
        self.count = 0

    def _client_data(self, kind: str, challenge: str, origin: str | None = None) -> bytes:
        data = {"type": kind, "challenge": challenge, "origin": origin or self.origin}
        return json.dumps(data).encode()

    def _rp_hash(self) -> bytes:
        return hashlib.sha256(self.rp_id.encode()).digest()

    def register(self, options: dict[str, Any], *, origin: str | None = None) -> dict[str, Any]:
        """The credential a browser sends back for these registration options."""
        self.user_handle = unb64(options["user"]["id"])
        numbers = self.key.public_key().public_numbers()
        cose = cbor2.dumps(
            {
                1: 2,  # EC2
                3: -7,  # ES256
                -1: 1,  # P-256
                -2: numbers.x.to_bytes(32, "big"),
                -3: numbers.y.to_bytes(32, "big"),
            }
        )
        attested = bytes(16) + struct.pack(">H", len(self.credential_id)) + self.credential_id
        auth_data = (
            self._rp_hash() + bytes([0x45]) + struct.pack(">I", self.count) + attested + cose
        )
        attestation = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
        client_data = self._client_data("webauthn.create", options["challenge"], origin)
        return {
            "id": b64(self.credential_id),
            "rawId": b64(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": b64(client_data),
                "attestationObject": b64(attestation),
                "transports": ["internal"],
            },
            "clientExtensionResults": {},
        }

    def sign_in(self, options: dict[str, Any], *, origin: str | None = None) -> dict[str, Any]:
        """The credential a browser sends back for these sign-in options."""
        self.count += 1
        auth_data = self._rp_hash() + bytes([0x05]) + struct.pack(">I", self.count)
        client_data = self._client_data("webauthn.get", options["challenge"], origin)
        signed = auth_data + hashlib.sha256(client_data).digest()
        signature = self.key.sign(signed, ec.ECDSA(hashes.SHA256()))
        return {
            "id": b64(self.credential_id),
            "rawId": b64(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": b64(client_data),
                "authenticatorData": b64(auth_data),
                "signature": b64(signature),
                "userHandle": b64(self.user_handle),
            },
            "clientExtensionResults": {},
        }
