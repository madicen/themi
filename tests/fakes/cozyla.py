"""A fake of Cozyla's cloud (the unofficial API the tablet apps use), behind an httpx transport.

    fake_cozyla.add_list("Family")                       # -> list id
    fake_cozyla.add_todo(list_id, "Call the vet")        # as if added on the wall
    fake_cozyla.tick(todo_id)                            # ticked off on the wall
    fake_cozyla.fail("todosInfo/list", code=500)         # the next call to it fails
    fake_cozyla.expire_tokens()                          # every token now gets code 101
    fake_cozyla.add_chore("Bins", ["m-erin"], every="Weekly", days="Tuesday")  # -> chore uid
    fake_cozyla.tick_chore(uid, "m-erin", date(2026, 10, 27))  # ticked on the chore chart
    fake_cozyla.add_routine("m-erin", "Walk dog", "Morning")  # -> routine id

It answers like the real service as described in cozyla-sdk's notes: JSON POSTs to
`/cal-server/...`, a `{code, message, result}` envelope with the code as a string, the
token in `Authorization` with no "Bearer", and a sign-in whose password is RSA-encrypted
with the app's public key. The fake makes its own key pair, so tests hand the client
`fake_cozyla.public_key` and the fake can check the password it decrypts.
"""

from __future__ import annotations

import base64
import itertools
import json
import secrets
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from themi import clock

EMAIL = "family@x.example"
PASSWORD = "wall-calendar"


@dataclass
class Call:
    path: str
    body: dict[str, Any]
    headers: dict[str, str] = field(default_factory=dict)


class FakeCozyla:
    def __init__(self, email: str = EMAIL, password: str = PASSWORD) -> None:
        self.email, self.password = email, password
        self._key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        der = self._key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        self.public_key = base64.b64encode(der).decode()
        self.members: list[dict[str, Any]] = []
        self.lists: dict[int, dict[str, Any]] = {}
        self.todos: dict[int, dict[str, Any]] = {}
        self.chores: dict[str, dict[str, Any]] = {}
        self.chore_ticks: dict[tuple[str, str, str], str] = {}  # (uid, member, day) -> status
        self.routines: dict[int, dict[str, Any]] = {}
        self.routine_ticks: set[tuple[int, str]] = set()  # (routine id, day) ticked
        self.tokens: set[str] = set()
        self.calls: list[Call] = []
        self.locked_for = 0  # seconds of sign-in lockout to report, if any
        self._failures: Counter[str] = Counter()
        self._failure_codes: dict[str, int] = {}
        self._ids = itertools.count(101)
        self.transport = httpx.MockTransport(self._handle)

    # ----- for tests: the family's account, and what someone does on the wall ------------

    def add_member(self, name: str) -> str:
        uid = f"m-{name.lower()}"
        self.members.append({"memberUid": uid, "memberName": name, "role": "member", "coins": 0})
        return uid

    def add_list(self, title: str) -> int:
        list_id = next(self._ids)
        self.lists[list_id] = {
            "listId": list_id,
            "todoListTitle": title,
            "todoListColor": "#E9B14D",
            "todoListIcon": "icon_todolist_preset9",
            "displayOrder": float(len(self.lists)),
        }
        return list_id

    def add_todo(
        self,
        list_id: int,
        title: str,
        *,
        assignee: str | None = None,
        due: datetime | None = None,
        done: bool = False,
    ) -> int:
        todo_id = next(self._ids)
        self.todos[todo_id] = {
            "todoId": todo_id,
            "todoListId": list_id,
            "todoTitle": title,
            "todoDesc": "",
            "assignMemberUid": assignee,
            "todoStars": 0,
            "isFlag": 0,
            "dueDateTime": int(due.timestamp() * 1000) if due else -1,
            "reminderTime": -1,
            "timeUnit": "none",
            "completeStatus": int(done),
            "completeTime": _ms(clock.now()) if done else 0,
            "createTime": _ms(clock.now()),
        }
        return todo_id

    def tick(self, todo_id: int, done: bool = True) -> None:
        todo = self.todos[todo_id]
        todo["completeStatus"] = int(done)
        todo["completeTime"] = _ms(clock.now()) if done else 0

    def edit(self, todo_id: int, **fields: Any) -> None:
        self.todos[todo_id].update(fields)

    def delete(self, todo_id: int) -> None:
        del self.todos[todo_id]

    def in_list(self, list_id: int) -> list[dict[str, Any]]:
        return [t for t in self.todos.values() if t["todoListId"] == list_id]

    def titles(self, list_id: int, *, done: bool = False) -> list[str]:
        return sorted(t["todoTitle"] for t in self.in_list(list_id) if t["completeStatus"] == done)

    def add_chore(
        self,
        name: str,
        members: list[str],
        *,
        kind: str = "Everyone",
        every: str = "Weekly",
        count: int = 1,
        days: str = "",
        start: date | None = None,
        end: date | None = None,
        forever: bool = True,
        repeats: bool = True,
        due_time: str = "23:59",
    ) -> str:
        start = start or clock.now().date()
        uid = secrets.token_hex(16)
        self.chores[uid] = {
            "choreUid": uid,
            "id": len(self.chores) + 1,
            "choreName": name,
            "icon": "czl_chores_emoji#_#broom#_#🧹",
            "coins": 0,
            "choreType": kind,
            "rotateEveryCounts": 1,
            "startDay": start.isoformat(),
            "endDay": (end or start + timedelta(days=30)).isoformat(),
            "dueTime": due_time,
            "repeats": repeats,
            "repeatsEvery": every,
            "repeatsEveryCounts": count,
            "repeatsIn": days,
            "repeatsUntil": forever,
            "reminder": -1,
            "memberRefs": self._refs(members),
            "choreBank": False,
            "choreDeviceId": "db3860b5-9178-427a-894e-d9dfed2bcf5b",
            "description": "",
        }
        return uid

    def tick_chore(self, uid: str, member: str, day: date, done: bool = True) -> None:
        self.chore_ticks[(uid, member, day.isoformat())] = "completed" if done else "pending"

    def chore_named(self, name: str) -> dict[str, Any]:
        (chore,) = [c for c in self.chores.values() if c["choreName"] == name]
        return chore

    def add_routine(
        self,
        member: str,
        title: str,
        part: str = "Morning",
        *,
        every: str = "Daily",
        days: str = "",
        start: date | None = None,
    ) -> int:
        routine_id = next(self._ids)
        self.routines[routine_id] = {
            "id": routine_id,
            "memberUid": member,
            "routineTitle": title,
            "routineType": part,
            "routineIcon": "routine_property_bed",
            "coins": 0,
            "habitEnabled": 0,
            "habitBonusStars": 0,
            "repeatsEvery": every,
            "repeatsEveryCounts": 1,
            "repeatsIn": days,
            "startDay": (start or clock.now().date()).isoformat(),
            "endDay": None,
            "description": "",
        }
        return routine_id

    def tick_routine(self, routine_id: int, day: date, done: bool = True) -> None:
        (self.routine_ticks.add if done else self.routine_ticks.discard)(
            (routine_id, day.isoformat())
        )

    def routine_named(self, title: str) -> dict[str, Any]:
        (routine,) = [r for r in self.routines.values() if r["routineTitle"] == title]
        return routine

    def fail(self, endpoint: str, code: int = 500, times: int = 1) -> None:
        """The next `times` calls to an endpoint ("todosInfo/list", "signIn") get `code`."""
        self._failures[endpoint] += times
        self._failure_codes[endpoint] = code

    def expire_tokens(self) -> None:
        self.tokens.clear()

    def paths(self) -> list[str]:
        return [c.path.removeprefix("/cal-server/") for c in self.calls]

    # ----- the service --------------------------------------------------------------------

    def _handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        self.calls.append(Call(request.url.path, body, dict(request.headers)))
        endpoint = request.url.path.removeprefix("/cal-server/")
        for name in (endpoint.split("/", 1)[-1], endpoint.rsplit("/", 1)[-1]):
            if self._failures[name]:
                self._failures[name] -= 1
                return _envelope(self._failure_codes[name], None, "fake failure")
        if endpoint == "users/cozUsers/signIn":
            return self._sign_in(body)
        if request.headers.get("Authorization") not in self.tokens:
            return _envelope(101, None, "token expired")
        handler = ROUTES.get(endpoint)
        if handler is None:
            return httpx.Response(404)
        try:
            return _envelope(0, handler(self, body))
        except KeyError:
            return _envelope(1500, None, "not found")

    def _sign_in(self, body: dict[str, Any]) -> httpx.Response:
        if self.locked_for:
            return _envelope(1002, {"loginLimitCountdown": self.locked_for}, "too many tries")
        password = self._key.decrypt(
            base64.b64decode(body["encryptionPassword"]), padding.PKCS1v15()
        ).decode()
        if body.get("email") != self.email or password != self.password:
            return _envelope(1001, None, "wrong email or password")
        token = secrets.token_hex(16)
        self.tokens.add(token)
        return _envelope(0, {"token": token, "deviceUid": "dev-1", "memberUid": "owner"})

    def _create(self, body: dict[str, Any]) -> dict[str, Any]:
        if body["todoListId"] not in self.lists:
            raise KeyError(body["todoListId"])
        todo_id = self.add_todo(body["todoListId"], body["todoTitle"])
        self.todos[todo_id].update(_fields(body))
        return {"todoId": todo_id}

    def _update(self, body: dict[str, Any]) -> dict[str, Any]:
        todo = self.todos[body["todoId"]]
        # The real API keeps only what's sent: anything left out is cleared.
        for name in TODO_FIELDS:
            todo[name] = body.get(name, BLANK[name])
        return {"todoId": todo["todoId"]}

    def _check(self, body: dict[str, Any]) -> dict[str, Any]:
        self.tick(body["todoId"], bool(body["completeStatus"]))
        todo = self.todos[body["todoId"]]
        return {
            "todoId": todo["todoId"],
            "completeStatus": todo["completeStatus"],
            "completeTime": todo["completeTime"],
        }

    def _delete(self, body: dict[str, Any]) -> None:
        del self.todos[body["id"]]

    # ----- chores and routines ------------------------------------------------------------

    def _refs(self, members: list[str]) -> list[dict[str, Any]]:
        names = {m["memberUid"]: m["memberName"] for m in self.members}
        return [{"memberUid": m, "memberName": names.get(m, m), "coins": 0} for m in members]

    def _create_chore(self, body: dict[str, Any]) -> dict[str, Any]:
        missing = [k for k in CHORE_FIELDS if k not in body]
        if missing:
            raise KeyError(missing)
        uid = self.add_chore(body["choreName"], body["memberUids"])
        self._set_chore(uid, body)
        return self.chores[uid]

    def _update_chore(self, body: dict[str, Any]) -> dict[str, Any]:
        missing = [k for k in CHORE_FIELDS if k not in body]  # the real API needs them all
        if missing or body["choreUid"] not in self.chores:
            raise KeyError(missing or body["choreUid"])
        self._set_chore(body["choreUid"], body)
        return self.chores[body["choreUid"]]

    def _set_chore(self, uid: str, body: dict[str, Any]) -> None:
        chore = self.chores[uid]
        for name in CHORE_FIELDS:
            if name != "memberUids":
                chore[name] = body[name]
        chore["memberRefs"] = self._refs(body["memberUids"])

    def _delete_chore(self, body: dict[str, Any]) -> list[dict[str, Any]]:
        del self.chores[body["choreUid"]]
        return list(self.chores.values())

    def _chore_records(self, body: dict[str, Any]) -> list[dict[str, Any]]:
        day = date.fromisoformat(body["selectDay"])
        records = []
        for chore in self.chores.values():
            if not _occurs(chore, day):
                continue
            for ref in chore["memberRefs"]:
                status = self.chore_ticks.get(
                    (chore["choreUid"], ref["memberUid"], day.isoformat())
                )
                if status is None:
                    status = "expired" if day < clock.now().date() else "pending"
                records.append(
                    {
                        "choreUid": chore["choreUid"],
                        "choreName": chore["choreName"],
                        "memberUid": ref["memberUid"],
                        "memberName": ref["memberName"],
                        "checkDay": day.isoformat(),
                        "status": status,
                        "choreMemberRecordUid": f"{chore['choreUid']}_{ref['memberUid']}_{day}",
                    }
                )
        return records

    def _check_chore(self, body: dict[str, Any]) -> None:
        if body["choreUid"] not in self.chores:
            raise KeyError(body["choreUid"])
        self.chore_ticks[(body["choreUid"], body["memberUid"], body["checkDay"])] = body[
            "choreStatus"
        ]

    def _create_routine(self, body: dict[str, Any]) -> list[dict[str, Any]]:
        made = []
        for member in body["memberUids"]:
            routine_id = self.add_routine(member, body["routineTitle"], body["routineType"])
            self.routines[routine_id].update({k: body[k] for k in ROUTINE_FIELDS})
            made.append({"routineId": routine_id, "memberUid": member, "memberId": 1})
        return made

    def _update_routine(self, body: dict[str, Any]) -> None:
        routine = self.routines[body["id"]]
        routine.update({k: body[k] for k in ROUTINE_FIELDS})

    def _delete_routine(self, body: dict[str, Any]) -> None:
        del self.routines[body["id"]]

    def _routine_records(self, body: dict[str, Any]) -> list[dict[str, Any]]:
        day = date.fromisoformat(body["selectDay"])
        return [
            {
                "routineId": r["id"],
                "memberUid": r["memberUid"],
                "routineTitle": r["routineTitle"],
                "routineType": r["routineType"],
                "checkDay": day.isoformat(),
                "status": "completed"
                if (r["id"], day.isoformat()) in self.routine_ticks
                else "pending",
            }
            for r in self.routines.values()
            if _occurs({**r, "repeats": True, "repeatsUntil": True}, day)
        ]

    def _check_routine(self, body: dict[str, Any]) -> None:
        if body["routineId"] not in self.routines:
            raise KeyError(body["routineId"])
        self.tick_routine(
            body["routineId"], date.fromisoformat(body["checkDay"]), body["status"] == "completed"
        )


TODO_FIELDS = (
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
BLANK: dict[str, Any] = {
    "todoListId": 0,
    "todoTitle": "",
    "todoDesc": "",
    "assignMemberUid": None,
    "todoStars": 0,
    "isFlag": 0,
    "dueDateTime": -1,
    "reminderTime": -1,
    "timeUnit": "none",
}

CHORE_FIELDS = (
    "choreName",
    "icon",
    "coins",
    "choreType",
    "rotateEveryCounts",
    "startDay",
    "endDay",
    "dueTime",
    "repeats",
    "repeatsEvery",
    "repeatsEveryCounts",
    "repeatsIn",
    "repeatsUntil",
    "reminder",
    "memberUids",
    "choreBank",
    "choreDeviceId",
    "description",
)
ROUTINE_FIELDS = (
    "routineTitle",
    "routineType",
    "routineIcon",
    "coins",
    "habitBonusStars",
    "habitEnabled",
    "repeatsEvery",
    "repeatsEveryCounts",
    "repeatsIn",
    "startDay",
    "description",
)


def _occurs(item: dict[str, Any], day: date) -> bool:
    """Whether a chore or routine falls on `day`, as the wall works it out."""
    start = date.fromisoformat(item["startDay"])
    end = date.fromisoformat(item["endDay"]) if item.get("endDay") else None
    if day < start:
        return False
    if not item.get("repeats", True):
        return day <= (end or start)
    if not item.get("repeatsUntil", True) and end is not None and day > end:
        return False
    n = int(item.get("repeatsEveryCounts") or 1)
    parts = [p.strip() for p in str(item.get("repeatsIn") or "").split(",") if p.strip()]
    if item["repeatsEvery"] == "Daily":
        return (day - start).days % n == 0
    if item["repeatsEvery"] == "Weekly":
        week_of = lambda d: (d - timedelta(days=d.weekday())).toordinal() // 7  # noqa: E731
        return day.strftime("%A") in parts and (week_of(day) - week_of(start)) % n == 0
    months = (day.year - start.year) * 12 + day.month - start.month
    return str(day.day) in parts and months % n == 0


ROUTES = {
    "users/cozUsersMember/queryMembers": lambda f, b: f.members,
    "rewards/todosList/list": lambda f, b: list(f.lists.values()),
    "rewards/todosInfo/list": lambda f, b: list(f.todos.values()),
    "rewards/todosInfo/create": FakeCozyla._create,
    "rewards/todosInfo/update": FakeCozyla._update,
    "rewards/todosInfo/checkTodo": FakeCozyla._check,
    "rewards/todosInfo/delete": FakeCozyla._delete,
    "rewards/chores/myChoresV1": lambda f, b: list(f.chores.values()),
    "rewards/chores/create/v1": FakeCozyla._create_chore,
    "rewards/chores/update/v1": FakeCozyla._update_chore,
    "rewards/chores/delete/v1": FakeCozyla._delete_chore,
    "rewards/chores/choreRecordByDay/v3": FakeCozyla._chore_records,
    "rewards/chores/choreCheck/v1": FakeCozyla._check_chore,
    "rewards/routineUser/getRoutineList/v1": lambda f, b: list(f.routines.values()),
    "rewards/routineUser/createRoutine": FakeCozyla._create_routine,
    "rewards/routineUser/updateRoutine": FakeCozyla._update_routine,
    "rewards/routineUser/delRoutine": FakeCozyla._delete_routine,
    "rewards/routineUserRecord/getRoutineRecordByDay/v1": FakeCozyla._routine_records,
    "rewards/routineUserRecord/checkUserRoutine": FakeCozyla._check_routine,
}


def _fields(body: dict[str, Any]) -> dict[str, Any]:
    return {k: body[k] for k in TODO_FIELDS if k in body}


def _ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def _envelope(code: int, result: Any, message: str = "success") -> httpx.Response:
    # The live API sends the code as a string ("0").
    return httpx.Response(200, json={"code": str(code), "message": message, "result": result})


@pytest.fixture
def fake_cozyla() -> FakeCozyla:
    return FakeCozyla()
