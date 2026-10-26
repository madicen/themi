"""The OurGroceries side of the mirror: a small interface, and the real adapter.

The real adapter wraps the unofficial `ourgroceries` library (the one Home
Assistant uses), an optional dependency: `pip install 'themi[ourgroceries]'`.
It's imported only when the mirror first runs, so Themi works without it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from themi.storage.secrets import Secret


class MirrorError(Exception):
    """OurGroceries couldn't be reached or refused; the mirror retries later."""


@dataclass(frozen=True)
class RemoteItem:
    id: str
    value: str
    crossed_off: bool


class GroceryListClient(Protocol):
    """One shared list in OurGroceries."""

    async def items(self) -> list[RemoteItem]: ...

    async def add(self, value: str) -> None: ...

    async def remove(self, item_id: str) -> None: ...

    async def set_crossed_off(self, item_id: str, crossed_off: bool) -> None: ...


@dataclass(frozen=True)
class OurGroceriesConfig:
    username: str
    password: Secret
    list_name: str


class OurGroceriesClient:
    def __init__(self, config: OurGroceriesConfig) -> None:
        self.config = config
        self._api: Any = None
        self._list_id: str | None = None

    async def _ready(self) -> tuple[Any, str]:
        if self._api is None:
            try:
                from ourgroceries import OurGroceries  # type: ignore[import-not-found]
            except ImportError as exc:
                raise MirrorError(
                    "the ourgroceries library isn't installed (pip install 'themi[ourgroceries]')"
                ) from exc
            self._api = OurGroceries(self.config.username, self.config.password.reveal())
        if self._list_id is None:
            try:
                await self._api.login()
                overview = await self._api.get_my_lists()
            except Exception as exc:  # the library raises whatever aiohttp raises
                raise MirrorError(f"OurGroceries sign-in failed ({type(exc).__name__})") from exc
            wanted = self.config.list_name.strip().lower()
            for entry in overview.get("shoppingLists", []):
                if str(entry.get("name", "")).strip().lower() == wanted:
                    self._list_id = str(entry["id"])
                    break
            else:
                raise MirrorError(f"OurGroceries has no list called {self.config.list_name!r}")
        return self._api, self._list_id

    async def _call(self, what: str, action: Any) -> Any:
        try:
            return await action
        except MirrorError:
            raise
        except Exception as exc:
            self._list_id = None  # sign in again next time
            raise MirrorError(f"OurGroceries {what} failed ({type(exc).__name__})") from exc

    async def items(self) -> list[RemoteItem]:
        api, list_id = await self._ready()
        data = await self._call("reading the list", api.get_list_items(list_id))
        return [
            RemoteItem(
                str(i["id"]),
                str(i.get("value", "")),
                # The library's own `crossedOff` is always False; a crossed-off item is the one
                # with a `crossedOffAt` timestamp (checked against the live API, 2026-10-25).
                bool(i.get("crossedOff")) or i.get("crossedOffAt") is not None,
            )
            for i in data.get("list", {}).get("items", [])
        ]

    async def add(self, value: str) -> None:
        api, list_id = await self._ready()
        await self._call("adding an item", api.add_item_to_list(list_id, value, auto_category=True))

    async def remove(self, item_id: str) -> None:
        api, list_id = await self._ready()
        await self._call("removing an item", api.remove_item_from_list(list_id, item_id))

    async def set_crossed_off(self, item_id: str, crossed_off: bool) -> None:
        api, list_id = await self._ready()
        await self._call(
            "crossing an item off" if crossed_off else "bringing an item back",
            api.toggle_item_crossed_off(list_id, item_id, cross_off=crossed_off),
        )
