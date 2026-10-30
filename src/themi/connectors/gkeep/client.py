"""Google Keep, through the unofficial `gkeepapi` library (GK1).

Google's Keep API is for Workspace accounts only, so a personal account is read the way
Keep's own apps read it, with a master token. The library is an optional dependency
(`pip install 'themi[keep]'`), imported only when it's first used, so Themi works without
it. It's synchronous, so each call runs in a thread.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from themi.storage.secrets import Secret


class KeepError(Exception):
    """Keep couldn't be reached or refused the sign-in; the sync tries again later."""


@dataclass(frozen=True)
class KeepItem:
    id: str
    text: str


@dataclass(frozen=True)
class KeepLogin:
    email: str
    master_token: Secret = field(repr=False)
    device_id: str = ""


class KeepAccount(Protocol):
    """One person's Keep."""

    async def lists(self) -> list[str]: ...

    async def unchecked(self, list_name: str) -> list[KeepItem]: ...

    async def check_off(self, list_name: str, item_ids: list[str]) -> None: ...


KeepFactory = Callable[[KeepLogin], KeepAccount]


def _library() -> Any:
    try:
        import gkeepapi  # type: ignore[import-untyped]
    except ImportError as exc:
        raise KeepError("the gkeepapi library isn't installed (pip install 'themi[keep]')") from exc
    return gkeepapi


def exchange_token(email: str, oauth_token: Secret, device_id: str) -> Secret:
    """Turn the `oauth_token` cookie from Google's EmbeddedSetup page into a master token."""
    _library()
    import gpsoauth  # type: ignore[import-untyped]  # comes with gkeepapi

    try:
        answer = gpsoauth.exchange_token(email, oauth_token.reveal(), device_id)
    except Exception as exc:  # requests raises whatever it raises
        raise KeepError(f"Google couldn't be reached ({type(exc).__name__})") from exc
    token = answer.get("Token")
    if not token:
        raise KeepError(f"Google didn't give a master token ({answer.get('Error', 'no reason')})")
    return Secret(token)


class GKeepAccount:
    def __init__(self, login: KeepLogin) -> None:
        self.login = login
        self._keep: Any = None

    def _ready(self) -> Any:
        if self._keep is None:
            gkeepapi = _library()
            keep = gkeepapi.Keep()
            keep.authenticate(
                self.login.email, self.login.master_token.reveal(), device_id=self.login.device_id
            )
            self._keep = keep
        else:
            self._keep.sync()
        return self._keep

    async def _call(self, what: str, action: Callable[[Any], Any]) -> Any:
        def run() -> Any:
            return action(self._ready())

        try:
            return await asyncio.to_thread(run)
        except KeepError:
            raise
        except Exception as exc:  # the library raises its own errors and requests'
            self._keep = None  # sign in again next time
            raise KeepError(f"Keep {what} failed ({type(exc).__name__})") from exc

    async def lists(self) -> list[str]:
        def titles(keep: Any) -> list[str]:
            gkeepapi = _library()
            return [
                n.title
                for n in keep.all()
                if isinstance(n, gkeepapi.node.List) and not n.trashed and not n.archived
            ]

        return await self._call("reading the lists", titles)

    async def unchecked(self, list_name: str) -> list[KeepItem]:
        def items(keep: Any) -> list[KeepItem]:
            return [KeepItem(str(i.id), str(i.text)) for i in _find(keep, list_name).unchecked]

        return await self._call("reading the list", items)

    async def check_off(self, list_name: str, item_ids: list[str]) -> None:
        def check(keep: Any) -> None:
            wanted = set(item_ids)
            for item in _find(keep, list_name).items:
                if str(item.id) in wanted:
                    item.checked = True
            keep.sync()

        await self._call("checking items off", check)


def _find(keep: Any, list_name: str) -> Any:
    gkeepapi = _library()
    wanted = list_name.strip().lower()
    for note in keep.all():
        if (
            isinstance(note, gkeepapi.node.List)
            and not note.trashed
            and str(note.title).strip().lower() == wanted
        ):
            return note
    raise KeepError(f"Keep has no list called {list_name!r}")
