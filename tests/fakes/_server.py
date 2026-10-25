"""Run a FastAPI app on a random local port in a background thread (for HTTP fakes)."""

from __future__ import annotations

import threading
import time

import uvicorn
from fastapi import FastAPI


class BackgroundServer:
    def __init__(self, app: FastAPI) -> None:
        self.app = app
        self.port = 0
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> None:
        config = uvicorn.Config(
            self.app, host="127.0.0.1", port=0, log_level="warning", lifespan="off"
        )
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()
        deadline = time.monotonic() + 10
        while not self._server.started:
            if time.monotonic() > deadline:
                raise RuntimeError("fake server didn't start")
            time.sleep(0.01)
        self.port = self._server.servers[0].sockets[0].getsockname()[1]

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=5)
