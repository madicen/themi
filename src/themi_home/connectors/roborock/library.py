"""The real Roborock connection, over `python-roborock` (optional: `themi[roborock]`).

`LibraryLogin` signs in (an emailed code, Roborock's v4 login) and opens a
`LibrarySession`: the library's device manager, which finds the robots and connects to
each over the LAN when it can, the cloud's MQTT otherwise, reconnecting by itself. Status,
parts, the room (its map, with the Roborock app's room names), "Resolved" and "go home" are
the library's V1 traits and commands.

This is the one piece the default test run can't reach: tests use `tests/fakes/roborock.py`.
The library's discovery data (home, network, the robots' features) is cached in memory for
the life of the process.
"""

from __future__ import annotations

import logging
from typing import Any

from themi_home.connectors.roborock.client import (
    BadCode,
    LoginExpired,
    RoborockError,
    RoborockSession,
    RobotOffline,
    VacuumDevice,
)

log = logging.getLogger(__name__)

STATUS_FIELDS = ("state", "error_code", "dock_error_status", "battery", "dss", "in_cleaning")
CONSUMABLE_FIELDS = (
    "main_brush_work_time",
    "side_brush_work_time",
    "filter_work_time",
    "sensor_dirty_time",
    "strainer_work_times",
    "cleaning_brush_work_times",
    "dust_collection_work_times",
    "moproller_work_time",
)


def _library() -> Any:
    try:
        import roborock  # type: ignore[import-not-found]
    except ImportError:
        return None
    return roborock


def available() -> LibraryLogin | None:
    """The real sign-in, or None without the library (no vacuum, then)."""
    return LibraryLogin() if _library() is not None else None


class LibraryLogin:
    def __init__(self) -> None:
        # A code is traded by the same client that asked for it (it carries a client id).
        self._pending: dict[str, Any] = {}

    async def request_code(self, email: str) -> None:
        from roborock.web_api import RoborockApiClient  # type: ignore[import-not-found]

        client = RoborockApiClient(username=email)
        with _translated():
            await client.request_code_v4()
        self._pending[email] = client

    async def code_login(self, email: str, code: str) -> dict[str, Any]:
        from roborock.web_api import RoborockApiClient  # type: ignore[import-not-found]

        client = self._pending.get(email) or RoborockApiClient(username=email)
        with _translated():
            user_data = await client.code_login_v4(code)
            base_url = await client.base_url
        self._pending.pop(email, None)
        return {"user_data": user_data.as_dict(), "base_url": base_url}

    async def open(self, email: str, login: dict[str, Any]) -> RoborockSession:
        from roborock.data import UserData  # type: ignore[import-not-found]
        from roborock.devices.cache import InMemoryCache  # type: ignore[import-not-found]
        from roborock.devices.device_manager import (  # type: ignore[import-not-found]
            UserParams,
            create_device_manager,
        )

        params = UserParams(
            username=email,
            user_data=UserData.from_dict(login["user_data"]),
            base_url=login.get("base_url"),
        )
        with _translated():
            manager = await create_device_manager(params, cache=InMemoryCache())
        return LibrarySession(manager)


class LibrarySession:
    def __init__(self, manager: Any) -> None:
        self.manager = manager

    async def devices(self) -> list[VacuumDevice]:
        with _translated():
            found = await self.manager.get_devices()
        return [VacuumDevice(d.duid, d.name, d.product.model) for d in found if d.v1_properties]

    async def status(self, duid: str) -> dict[str, Any]:
        props = await self._props(duid)
        with _translated():
            await props.status.refresh()
        return {name: _plain(getattr(props.status, name, None)) for name in STATUS_FIELDS}

    async def consumables(self, duid: str) -> dict[str, int]:
        props = await self._props(duid)
        with _translated():
            await props.consumables.refresh()
        found = {}
        for name in CONSUMABLE_FIELDS:
            value = getattr(props.consumables, name, None)
            if value is not None:
                found[name] = int(value)
        return found

    async def room(self, duid: str) -> str | None:
        props = await self._props(duid)
        with _translated():
            await props.rooms.refresh()
            await props.map_content.refresh()
        data = props.map_content.map_data
        segment = getattr(data, "vacuum_room", None) if data is not None else None
        if segment is None:
            return None
        room = props.rooms.room_map.get(segment)
        return room.name if room is not None and room.raw_name else None

    async def resolve(self, duid: str, code: int) -> None:
        props = await self._props(duid)
        with _translated():
            await props.status.resolve_error(code)

    async def send_home(self, duid: str) -> None:
        from roborock.roborock_typing import RoborockCommand  # type: ignore[import-not-found]

        props = await self._props(duid)
        with _translated():
            await props.command.send(RoborockCommand.APP_CHARGE)

    async def close(self) -> None:
        with _translated():
            await self.manager.close()

    async def _props(self, duid: str) -> Any:
        with _translated():
            device = await self.manager.get_device(duid)
        if device is None or device.v1_properties is None:
            raise RobotOffline("Roborock doesn't list that robot any more.")
        if not device.is_connected:
            raise RobotOffline("The vacuum isn't connected right now.")
        return device.v1_properties


def _plain(value: Any) -> Any:
    """An enum's number, or the value as it is."""
    return getattr(value, "value", value) if value is not None else None


class _translated:
    """The library's errors as Themi's."""

    def __enter__(self) -> None:
        return None

    def __exit__(self, kind: Any, exc: BaseException | None, tb: Any) -> None:
        if exc is None or not isinstance(exc, Exception):
            return
        from roborock import exceptions as rr  # type: ignore[import-not-found]

        if isinstance(exc, RoborockError) or not isinstance(exc, rr.RoborockException):
            return
        if isinstance(exc, rr.RoborockInvalidCode):
            raise BadCode("That code didn't work; ask for a new one.") from exc
        if isinstance(exc, rr.RoborockInvalidCredentials | rr.RoborockAccountDoesNotExist):
            raise LoginExpired("Roborock no longer accepts the sign-in; link it again.") from exc
        if isinstance(exc, rr.RoborockTooFrequentCodeRequests | rr.RoborockRateLimit):
            raise RoborockError("Roborock asked to wait before another code.") from exc
        if isinstance(exc, rr.RoborockTimeout | rr.RoborockConnectionException):
            raise RobotOffline(f"The vacuum didn't answer: {exc}") from exc
        raise RoborockError(f"Roborock said: {exc}") from exc
