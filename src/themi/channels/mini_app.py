"""Telegram Mini Apps (BD3a): checking the `initData` a Mini App is opened with.

Telegram signs it with the bot's token: the secret key is HMAC-SHA256 of the token keyed
with "WebAppData", and `hash` is HMAC-SHA256 of the other fields (sorted, `key=value`, one
per line) with that key. Anything unsigned, forged, or older than `max_age` is refused.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qsl

INIT_DATA_MAX_AGE = timedelta(minutes=1)


def sign_init_data(fields: dict[str, str], bot_token: str) -> str:
    """The `hash` Telegram would give these fields (for checking, and for tests)."""
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()) if k != "hash")
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    return hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()


def check_init_data(
    init_data: str, bot_token: str, now: datetime, max_age: timedelta = INIT_DATA_MAX_AGE
) -> int | None:
    """The Telegram user id `init_data` was signed for, or None."""
    try:
        fields = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
    except ValueError:
        return None
    given = fields.get("hash", "")
    if not given or not hmac.compare_digest(given, sign_init_data(fields, bot_token)):
        return None
    try:
        signed_at = datetime.fromtimestamp(int(fields.get("auth_date", "")), tz=UTC)
        user = json.loads(fields.get("user", ""))
        user_id = int(user["id"])
    except (ValueError, KeyError, TypeError):
        return None
    if not now - max_age <= signed_at <= now + timedelta(seconds=30):
        return None
    return user_id
