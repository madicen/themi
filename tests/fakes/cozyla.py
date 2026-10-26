"""A fake of Cozyla's cloud (the unofficial API the tablet apps use), behind an httpx transport.

    fake_cozyla.add_list("Family")                       # -> list id
    fake_cozyla.add_todo(list_id, "Call the vet")        # as if added on the wall
    fake_cozyla.tick(todo_id)                            # ticked off on the wall
    fake_cozyla.fail("todosInfo/list", code=500)         # the next call to it fails
    fake_cozyla.expire_tokens()                          # every token now gets code 101

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
from datetime import datetime
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

ROUTES = {
    "users/cozUsersMember/queryMembers": lambda f, b: f.members,
    "rewards/todosList/list": lambda f, b: list(f.lists.values()),
    "rewards/todosInfo/list": lambda f, b: list(f.todos.values()),
    "rewards/todosInfo/create": FakeCozyla._create,
    "rewards/todosInfo/update": FakeCozyla._update,
    "rewards/todosInfo/checkTodo": FakeCozyla._check,
    "rewards/todosInfo/delete": FakeCozyla._delete,
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
