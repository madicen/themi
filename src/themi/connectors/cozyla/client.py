"""A small client for Cozyla's cloud: the unofficial API its tablet apps use (C1a).

Cozyla publishes no API. This follows the description in cozyla-sdk
(https://github.com/Fgruntjes/cozyla-sdk, MIT), which mapped it from the
decompiled apps: JSON POSTs to `/cal-server/...` answered with a
`{code, message, result}` envelope, and a token from signing in with the
account's email and its password, RSA-encrypted with the app's public key.
There's no refresh: an expired token (101 or 102) means signing in again, once.
Repeated failed sign-ins lock the account for a while (1002), so a lockout
makes the client wait instead of trying again.

It may change without notice, and using it may conflict with Cozyla's terms:
it's only ever used with the family's own account, after an admin sets it up.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import load_der_public_key

from themi import clock
from themi.connectors.cozyla.chores import (
    Chore,
    ChoreRecord,
    Routine,
    RoutineRecord,
    WallSchedule,
    chore_body,
    chore_from,
    record_from,
    routine_body,
    routine_from,
    routine_record_from,
)
from themi.storage.secrets import Secret

BASE_URL = "https://api.cozylacal.com"
# The public key built into Cozyla's apps, for encrypting the password at sign-in.
PASSWORD_KEY = (
    "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAuy5lIpsXk9rk3rY/9yxWII+r6oLaMNc5pWw1XrbQaoEn2EUI"
    "0O2QXfF7C7S89FHZKoZlz0MDD0W9X6dCldWpIjZYf+5fjlsrQDOkfJULlwTn8b91pe/NYiv2YWCdfTv1Pq9tTy6rkw4C"
    "66S7PW4rxVmFxWHI1yXvaRVCLe70YFZYrOe+YUzruYRYSi4im77ITdZ7W2HAiQ2RwsJJXd8M2Y8w43aT3NXz1s/mKcpZ"
    "rABgD0MQSdYadmKs6Cdm6H6oBRYuca5YxQSfg2VAu2qliZKEU2nVV2PWAYzDcnH7a2HMv0FylabwP4on7n59yNWe0nH7"
    "L47457IL354qmJnVEQIDAQAB"
)
TOKEN_EXPIRED = {101, 102}
WRONG_LOGIN = 1001
LOCKED_OUT = 1002


class CozylaError(Exception):
    """Cozyla couldn't be reached or refused; the sync retries later."""

    def __init__(self, message: str, code: int = -1, result: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.result = result  # what came with the refusal (a lockout's countdown)


@dataclass(frozen=True)
class CozylaConfig:
    email: str
    password: Secret
    todo_list: str = ""  # the list to sync; empty means no sync
    device_sn: str = "themi"  # how Themi appears among the account's devices; keep it the same
    chores: bool = False  # Themi runs the wall's chore chart (C2b)


@dataclass(frozen=True)
class CozylaMember:
    id: str
    name: str


# How a list Themi makes looks on the wall: a preset colour and icon the wall's lists use.
LIST_COLOR, LIST_ICON = "#E9B14D", "icon_todolist_preset9"


@dataclass(frozen=True)
class TodoList:
    id: str
    title: str
    color: str = LIST_COLOR  # sent back as they are when the list is renamed
    icon: str = LIST_ICON


@dataclass(frozen=True)
class Todo:
    id: str
    list_id: str
    title: str
    assignee: str | None  # a member id
    due: datetime | None
    completed: bool
    # Everything as Cozyla sent it: an update must send every field back (C1a).
    raw: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)


def encrypt_password(password: str, key: str = PASSWORD_KEY) -> str:
    public = load_der_public_key(base64.b64decode(key))
    assert isinstance(public, rsa.RSAPublicKey)
    return base64.b64encode(public.encrypt(password.encode(), padding.PKCS1v15())).decode()


def _ms(moment: datetime | None) -> int:
    return -1 if moment is None else int(moment.timestamp() * 1000)


def _when(value: Any) -> datetime | None:
    if not isinstance(value, int | float) or value <= 0:
        return None
    return datetime.fromtimestamp(value / 1000, UTC)


def _todo(raw: dict[str, Any]) -> Todo:
    assignee = raw.get("assignMemberUid")
    return Todo(
        id=str(raw["todoId"]),
        list_id=str(raw["todoListId"]),
        title=str(raw.get("todoTitle") or ""),
        assignee=str(assignee) if assignee else None,
        due=_when(raw.get("dueDateTime")),
        completed=bool(int(raw.get("completeStatus") or 0)),
        raw=dict(raw),
    )


# What an update sends; the rest of a to-do's fields are Cozyla's own.
UPDATE_FIELDS = (
    "todoListId",
    "todoTitle",
    "todoDesc",
    "assignMemberUid",
    "todoStars",
    "isFlag",
    "dueDateTime",
    "reminderTime",
    "timeUnit",
)


class CozylaClient:
    def __init__(
        self,
        config: CozylaConfig,
        *,
        timezone: str = "UTC",
        password_key: str = PASSWORD_KEY,
        base_url: str = BASE_URL,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config
        self.timezone = timezone
        self._password_key = password_key
        self._http = httpx.AsyncClient(base_url=base_url, transport=transport, timeout=20)
        self._token: str | None = None
        self._device_uid = ""
        self._locked_until: datetime | None = None

    async def aclose(self) -> None:
        await self._http.aclose()

    # ----- reading ----------------------------------------------------------------------

    async def members(self) -> list[CozylaMember]:
        result = await self._call("users/cozUsersMember/queryMembers", {"app": 1})
        return [CozylaMember(str(m["memberUid"]), str(m["memberName"])) for m in result or []]

    async def lists(self) -> list[TodoList]:
        result = await self._call("rewards/todosList/list")
        return [
            TodoList(
                str(t["listId"]),
                str(t["todoListTitle"]),
                str(t.get("todoListColor") or LIST_COLOR),
                str(t.get("todoListIcon") or LIST_ICON),
            )
            for t in result or []
        ]

    async def todos(self) -> list[Todo]:
        """Every to-do on the account, across all its lists."""
        return [_todo(t) for t in await self._call("rewards/todosInfo/list") or []]

    # ----- changing ---------------------------------------------------------------------

    async def create(
        self, list_id: str, title: str, *, assignee: str | None, due: datetime | None
    ) -> str:
        body = {
            "todoListId": int(list_id),
            "todoTitle": title,
            "todoDesc": "",
            "assignMemberUid": assignee,
            "todoStars": 0,
            "isFlag": 0,
            "dueDateTime": _ms(due),
            "reminderTime": -1,
            "timeUnit": "none",
        }
        result = await self._call("rewards/todosInfo/create", body)
        return str(result["todoId"])

    async def update(
        self, todo: Todo, *, title: str, assignee: str | None, due: datetime | None
    ) -> None:
        """Change the title, assignee and due date; every other field is sent back as is."""
        body = {name: todo.raw[name] for name in UPDATE_FIELDS if name in todo.raw}
        body.update(todoTitle=title, assignMemberUid=assignee, dueDateTime=_ms(due))
        await self._call("rewards/todosInfo/update", {"todoId": int(todo.id), **body})

    async def place(self, todo: Todo, display: float, profile: float) -> None:
        """Where it shows on the list (F18d): the wall goes by `profileDisplayOrder`, highest
        at the top; `displayOrder` (the order Cozyla sends them) moves with it. Every other
        field is sent back as is."""
        body = {name: todo.raw[name] for name in UPDATE_FIELDS if name in todo.raw}
        body.update(displayOrder=display, profileDisplayOrder=profile)
        await self._call("rewards/todosInfo/update", {"todoId": int(todo.id), **body})

    async def set_done(self, todo_id: str, done: bool) -> None:
        await self._call(
            "rewards/todosInfo/checkTodo", {"todoId": int(todo_id), "completeStatus": int(done)}
        )

    async def delete(self, todo_id: str) -> None:
        await self._call("rewards/todosInfo/delete", {"id": int(todo_id)})

    async def create_list(self, title: str) -> str:
        """A new to-do list on the wall (L1b); returns its id."""
        body = {
            "todoListTitle": title,
            "todoListColor": LIST_COLOR,
            "todoListIcon": LIST_ICON,
            "version": 0,
        }
        result = await self._call("rewards/todosList/create", body)
        return str(result["listId"])

    async def rename_list(self, todo_list: TodoList, title: str) -> None:
        """A new name; the colour and icon are sent back as they are (L2a)."""
        body = {
            "listId": int(todo_list.id),
            "todoListTitle": title,
            "todoListColor": todo_list.color,
            "todoListIcon": todo_list.icon,
        }
        await self._call("rewards/todosList/update", body)

    async def delete_list(self, list_id: str) -> None:
        await self._call("rewards/todosList/delete", {"id": int(list_id)})

    # ----- the chore chart and routines (C2a) --------------------------------------------

    async def chores(self) -> list[Chore]:
        return [chore_from(c) for c in await self._call("rewards/chores/myChoresV1") or []]

    async def create_chore(
        self, name: str, members: list[str], kind: str, schedule: WallSchedule
    ) -> Chore:
        body = {**chore_body(name, members, kind, schedule, {}), "asATemplate": False}
        return chore_from(await self._call("rewards/chores/create/v1", body))

    async def update_chore(
        self, chore: Chore, name: str, members: list[str], kind: str, schedule: WallSchedule
    ) -> None:
        body = {**chore_body(name, members, kind, schedule, chore.raw), "choreUid": chore.uid}
        await self._call("rewards/chores/update/v1", body)

    async def delete_chore(self, uid: str) -> None:
        await self._call("rewards/chores/delete/v1", {"choreUid": uid})

    async def chore_records(self, day: date) -> list[ChoreRecord]:
        """One record per member per chore falling on `day`."""
        body = {"selectDay": day.isoformat()}
        return [
            record_from(r)
            for r in await self._call("rewards/chores/choreRecordByDay/v3", body) or []
        ]

    async def check_chore(self, uid: str, member: str, day: date, done: bool) -> None:
        body = {
            "choreUid": uid,
            "memberUid": member,
            "checkFrom": "widget",
            "choreStatus": "completed" if done else "pending",
            "checkDay": day.isoformat(),
            "selectDay": day.isoformat(),
        }
        await self._call("rewards/chores/choreCheck/v1", body)

    async def routines(self) -> list[Routine]:
        body = {"memberUids": [], "routineType": ""}
        result = await self._call("rewards/routineUser/getRoutineList/v1", body)
        return [routine_from(r) for r in result or []]

    async def create_routine(
        self, member: str, title: str, part: str, schedule: WallSchedule,
        order: float | None = None,
    ) -> int:  # fmt: skip
        """`order`: its displayOrder, where it shows in that part of the day (the wall
        numbers them 1000s, 2000s, 3000s; new ones go last)."""
        body = {
            **routine_body(title, part, schedule, {}),
            "memberUids": [member],
            "asATemplate": False,
            **({"displayOrder": order} if order is not None else {}),
        }
        result = await self._call("rewards/routineUser/createRoutine", body)
        return int(result[0]["routineId"])

    async def update_routine(
        self, routine: Routine, title: str, part: str, schedule: WallSchedule, today: date,
        order: float | None = None,
    ) -> None:  # fmt: skip
        body = {
            **routine_body(title, part, schedule, routine.raw),
            "id": routine.id,
            "toDay": today.isoformat(),  # the edit applies from this day
            **({"displayOrder": order} if order is not None else {}),
        }
        await self._call("rewards/routineUser/updateRoutine", body)

    async def delete_routine(self, routine_id: int, today: date) -> None:
        body = {"id": routine_id, "toDay": today.isoformat()}
        await self._call("rewards/routineUser/delRoutine", body)

    async def routine_records(self, day: date) -> list[RoutineRecord]:
        body = {"selectDay": day.isoformat(), "memberUids": []}
        result = await self._call("rewards/routineUserRecord/getRoutineRecordByDay/v1", body)
        return [routine_record_from(r) for r in result or []]

    async def check_routine(self, routine_id: int, day: date, done: bool) -> None:
        body = {
            "routineId": routine_id,
            "checkDay": day.isoformat(),
            "status": "completed" if done else "pending",
            "weekFirstDate": 0,
        }
        await self._call("rewards/routineUserRecord/checkUserRoutine", body)

    # ----- the wire ---------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        device = {
            "deviceSn": self.config.device_sn,
            "deviceUid": self._device_uid,
            "deviceType": "Device",
            "deviceName": "Themi",
            "modelName": "Themi",
            "packageName": "com.cozyla.id",
            "timeZoneId": self.timezone,
            "loginClient": "DEVICE",
        }
        headers = {
            "timeZoneId": self.timezone,
            "platform": "Android",
            "Accept-Language": "en-US,en;q=0.9",
            # Sign-in is refused without the device descriptor the apps send.
            "X-DEVICE-INFO": base64.b64encode(json.dumps(device).encode()).decode(),
        }
        if self._token:
            headers["Authorization"] = self._token  # no "Bearer"
        return headers

    async def _post(self, endpoint: str, body: dict[str, Any]) -> Any:
        try:
            response = await self._http.post(
                f"/cal-server/{endpoint}", json=body, headers=self._headers()
            )
            response.raise_for_status()
            envelope = response.json()
        except httpx.HTTPError as exc:
            raise CozylaError(f"Cozyla couldn't be reached ({type(exc).__name__})") from exc
        except ValueError as exc:
            raise CozylaError("Cozyla sent something that isn't JSON") from exc
        try:
            code = int(envelope.get("code", -1))  # the live API sends it as a string
        except (TypeError, ValueError):
            code = -1
        if code != 0:
            raise CozylaError(
                f"Cozyla said no to {endpoint} (code {code})", code, envelope.get("result")
            )
        return envelope.get("result")

    async def _sign_in(self) -> None:
        now = clock.now()
        if self._locked_until is not None and now < self._locked_until:
            raise CozylaError(self._locked_text(self._locked_until - now), LOCKED_OUT)
        body = {
            "email": self.config.email,
            "encryptionPassword": encrypt_password(
                self.config.password.reveal(), self._password_key
            ),
            "app_id": "Chores",
            "deviceSn": self.config.device_sn,
            "loginClient": "DEVICE",
            "deviceName": "Themi",
        }
        try:
            result = await self._post("users/cozUsers/signIn", body)
        except CozylaError as exc:
            if exc.code == WRONG_LOGIN:
                raise CozylaError("Cozyla refused the email or password", exc.code) from exc
            if exc.code == LOCKED_OUT:
                countdown = exc.result.get("loginLimitCountdown") if exc.result else None
                wait = timedelta(seconds=countdown if isinstance(countdown, int) else 15 * 60)
                self._locked_until = now + wait
                raise CozylaError(self._locked_text(wait), exc.code) from exc
            raise
        self._token = str(result["token"])
        self._device_uid = str(result.get("deviceUid") or "")
        self._locked_until = None

    @staticmethod
    def _locked_text(wait: timedelta) -> str:
        minutes = max(1, round(wait.total_seconds() / 60))
        return f"Cozyla has paused sign-ins after failed tries; waiting {minutes} minutes"

    async def _call(self, endpoint: str, body: dict[str, Any] | None = None) -> Any:
        for attempt in range(2):
            if self._token is None:
                await self._sign_in()
            try:
                return await self._post(endpoint, {**(body or {}), "deviceUid": self._device_uid})
            except CozylaError as exc:
                if exc.code in TOKEN_EXPIRED and attempt == 0:
                    self._token = None  # sign in again, once
                    continue
                raise
        raise AssertionError("unreachable")  # pragma: no cover
