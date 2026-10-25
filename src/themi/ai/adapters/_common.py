"""Helpers shared by the adapters."""

from __future__ import annotations

import json
from typing import Any

from themi.ai.errors import MalformedOutputError

TRANSCRIBE_PROMPT = (
    "Transcribe this voice note exactly as spoken. Reply with only the transcript, "
    "no commentary. If nothing intelligible is said, reply with an empty string."
)


def transport_exceptions() -> tuple[type[BaseException], ...]:
    """Timeout and connection exception types from whichever httpx flavours are installed.

    The Anthropic SDK runs on httpx2 and google-genai on either, so both are checked.
    """
    found: list[type[BaseException]] = []
    for module_name in ("httpx", "httpx2"):
        try:
            module = __import__(module_name)
        except ImportError:
            continue
        for attr in ("TimeoutException", "TransportError"):
            exc = getattr(module, attr, None)
            if isinstance(exc, type) and issubclass(exc, BaseException):
                found.append(exc)
    return tuple(found)


def parse_json_object(text: str, provider: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise MalformedOutputError(f"{provider} returned text that isn't JSON") from exc
    if not isinstance(data, dict):
        raise MalformedOutputError(f"{provider} returned JSON that isn't an object")
    return data
