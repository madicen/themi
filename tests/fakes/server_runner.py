"""A stand-in for the host's runner (D3b, `deploy/control.sh`) over a temp control folder.

Tests play the runner's part by hand: pick up the request Themi wrote, say it's running,
then write how it went, in the files' agreed shapes (themi.updates)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


class FakeRunner:
    def __init__(self, folder: Path) -> None:
        self.folder = folder
        folder.mkdir(exist_ok=True)

    def install(self, newest: str | None = "1.5.0") -> None:
        self.write(
            "runner.json",
            {
                "installed_at": "2026-10-20T12:00:00+00:00",
                "newest": newest,
                "checked_at": "2026-10-21T15:00:00+00:00",
            },
        )

    def write(self, name: str, value: Any) -> None:
        (self.folder / name).write_text(json.dumps(value))

    def request(self) -> dict[str, Any] | None:
        path = self.folder / "request.json"
        return json.loads(path.read_text()) if path.exists() else None

    def pick_up(self) -> dict[str, Any]:
        """Take the waiting request, as the runner does first, and say it's running."""
        request = self.request()
        assert request is not None, "no request waiting"
        (self.folder / "request.json").unlink()
        self.write("result.json", {"id": request["id"], "state": "running"})
        return request

    def finish(
        self, request_id: int, state: str, frm: str, to: str, detail: str = "update: done"
    ) -> None:
        self.write(
            "result.json",
            {
                "id": request_id,
                "state": state,
                "from": frm,
                "to": to,
                "detail": detail,
                "finished_at": "2026-10-21T16:02:00+00:00",
            },
        )


@pytest.fixture
def fake_runner(tmp_path: Path) -> FakeRunner:
    return FakeRunner(tmp_path / "control")
