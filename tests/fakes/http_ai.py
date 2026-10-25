"""A local HTTP server that imitates the Anthropic, Gemini and OpenAI-compatible APIs.

The real adapters (and their SDKs) talk to it over real HTTP, which exercises
status codes, `Retry-After` headers, timeouts and malformed bodies exactly as
production would see them.

    def test_something(fake_ai):
        fake_ai.queue(anthropic_text("hello"))
        fake_ai.queue(anthropic_error("overloaded_error"), status=529,
                      headers={"retry-after": "3"})
        provider = AnthropicProvider(Secret("test-key"), base_url=fake_ai.url, timeout=2)
        ...
        assert fake_ai.requests[0].json["model"] == "claude-opus-5-5"

Every POST pops the next queued reply, whatever its path, so a test scripts
replies in the order its calls will be made. The server runs once per test
session; `fake_ai` resets it for each test.
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import Response

from tests.fakes._server import BackgroundServer


@dataclass
class ScriptedReply:
    status: int = 200
    json: Any = None
    headers: dict[str, str] = field(default_factory=dict)
    delay: float = 0.0  # seconds before replying (to trigger client timeouts)
    raw_body: bytes | None = None  # sent instead of `json`, e.g. a malformed body


@dataclass
class RecordedHTTPRequest:
    method: str
    path: str
    query: str
    headers: dict[str, str]
    body: bytes

    @property
    def json(self) -> Any:
        return json.loads(self.body) if self.body else None


class FakeAIServer:
    def __init__(self) -> None:
        self.replies: deque[ScriptedReply] = deque()
        self.requests: list[RecordedHTTPRequest] = []
        self._lock = threading.Lock()
        self.app = FastAPI()
        self.app.add_api_route(
            "/{path:path}", self._handle, methods=["POST", "GET"], include_in_schema=False
        )
        self._background = BackgroundServer(self.app)

    @property
    def url(self) -> str:
        return self._background.url

    def queue(
        self,
        json: Any = None,
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
        delay: float = 0.0,
        raw_body: bytes | None = None,
    ) -> FakeAIServer:
        with self._lock:
            self.replies.append(ScriptedReply(status, json, headers or {}, delay, raw_body))
        return self

    def reset(self) -> None:
        with self._lock:
            self.replies.clear()
            self.requests.clear()

    async def _handle(self, request: Request, path: str) -> Response:
        body = await request.body()
        with self._lock:
            self.requests.append(
                RecordedHTTPRequest(
                    request.method, "/" + path, request.url.query, dict(request.headers), body
                )
            )
            reply = self.replies.popleft() if self.replies else None
        if reply is None:
            return Response(
                content=json.dumps({"error": {"message": f"fake: nothing queued for /{path}"}}),
                status_code=599,
                media_type="application/json",
            )
        if reply.delay:
            await asyncio.sleep(reply.delay)
        content = reply.raw_body if reply.raw_body is not None else json.dumps(reply.json)
        return Response(
            content=content,
            status_code=reply.status,
            headers=reply.headers,
            media_type="application/json",
        )

    def start(self) -> None:
        self._background.start()

    def stop(self) -> None:
        self._background.stop()


@pytest.fixture(scope="session")
def _fake_ai_server() -> Iterator[FakeAIServer]:
    server = FakeAIServer()
    server.start()
    yield server
    server.stop()


@pytest.fixture
def fake_ai(_fake_ai_server: FakeAIServer) -> FakeAIServer:
    _fake_ai_server.reset()
    return _fake_ai_server


# ----- Anthropic Messages API shapes -----------------------------------------


def anthropic_message(
    content: list[dict[str, Any]],
    stop_reason: str = "end_turn",
    *,
    model: str = "claude-opus-5-5",
    stop_details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": "msg_fake",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "stop_details": stop_details,
        "usage": {"input_tokens": 12, "output_tokens": 7},
    }


def anthropic_text(text: str, **kwargs: Any) -> dict[str, Any]:
    return anthropic_message([{"type": "text", "text": text}], **kwargs)


def anthropic_tool_use(
    name: str, arguments: dict[str, Any], *, call_id: str = "toolu_1", thinking: bool = True
) -> dict[str, Any]:
    content: list[dict[str, Any]] = []
    if thinking:
        content.append({"type": "thinking", "thinking": "", "signature": "sig-abc123"})
    content.append({"type": "tool_use", "id": call_id, "name": name, "input": arguments})
    return anthropic_message(content, "tool_use")


def anthropic_error(error_type: str, message: str = "fake error") -> dict[str, Any]:
    return {"type": "error", "error": {"type": error_type, "message": message}}


# ----- OpenAI chat completions shapes -----------------------------------------


def openai_completion(
    content: str | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
    finish_reason: str | None = None,
    *,
    model: str = "llama-test",
) -> dict[str, Any]:
    return {
        "id": "chatcmpl-fake",
        "object": "chat.completion",
        "created": 0,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content, "tool_calls": tool_calls},
                "finish_reason": finish_reason or ("tool_calls" if tool_calls else "stop"),
            }
        ],
        "usage": {"prompt_tokens": 12, "completion_tokens": 7, "total_tokens": 19},
    }


def openai_tool_call(name: str, arguments: Any, call_id: str = "call_1") -> dict[str, Any]:
    raw = arguments if isinstance(arguments, str) else json.dumps(arguments)
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": raw}}


def openai_error(message: str = "fake error") -> dict[str, Any]:
    return {"error": {"message": message, "type": "server_error", "code": None}}


# ----- Gemini generateContent shapes ------------------------------------------


def gemini_response(
    parts: list[dict[str, Any]],
    finish_reason: str = "STOP",
    *,
    prompt_feedback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response: dict[str, Any] = {
        "candidates": [
            {
                "content": {"role": "model", "parts": parts},
                "finishReason": finish_reason,
                "index": 0,
            }
        ],
        "usageMetadata": {"promptTokenCount": 12, "candidatesTokenCount": 7, "totalTokenCount": 19},
        "modelVersion": "gemini-3.5-flash-lite",
    }
    if prompt_feedback is not None:
        response = {"promptFeedback": prompt_feedback, "usageMetadata": response["usageMetadata"]}
    return response


def gemini_text(text: str, finish_reason: str = "STOP") -> dict[str, Any]:
    return gemini_response([{"text": text}], finish_reason)


def gemini_function_call(
    name: str,
    arguments: dict[str, Any],
    *,
    call_id: str | None = "fc_1",
    signature: str = "c2lnLTE=",
) -> dict[str, Any]:
    call: dict[str, Any] = {"name": name, "args": arguments}
    if call_id:
        call["id"] = call_id
    return gemini_response([{"functionCall": call, "thoughtSignature": signature}])


def gemini_error(
    code: int, status: str, message: str = "fake error", retry_delay: str | None = None
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message, "status": status}
    if retry_delay:
        error["details"] = [
            {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": retry_delay}
        ]
    return {"error": error}
