# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 MindTenet LLC
# This file is part of Undef Telemetry.
from __future__ import annotations

from typing import Any

import pytest

from undef.telemetry.asgi import middleware as middleware_mod
from undef.telemetry.asgi.middleware import TelemetryMiddleware, _extract_header
from undef.telemetry.asgi.websocket import _extract_header as ws_extract_header
from undef.telemetry.asgi.websocket import bind_websocket_context
from undef.telemetry.logger import get_context


async def _dummy_app(scope: dict[str, Any], receive: Any, send: Any) -> None:
    await send({"type": "done", "scope_type": scope["type"]})


@pytest.mark.asyncio
async def test_middleware_non_http_path() -> None:
    events: list[dict[str, Any]] = []

    async def send(msg: dict[str, Any]) -> None:
        events.append(msg)

    async def receive() -> dict[str, Any]:
        return {"type": "noop"}

    middleware = TelemetryMiddleware(_dummy_app)
    await middleware({"type": "lifespan"}, receive, send)
    assert events[0]["scope_type"] == "lifespan"


@pytest.mark.asyncio
async def test_middleware_http_context() -> None:
    events: list[dict[str, Any]] = []

    async def send(msg: dict[str, Any]) -> None:
        events.append(msg)

    async def receive() -> dict[str, Any]:
        return {"type": "noop"}

    middleware = TelemetryMiddleware(_dummy_app)
    scope = {
        "type": "http",
        "headers": [(b"x-request-id", b"r1"), (b"x-session-id", b"s1")],
    }
    await middleware(scope, receive, send)
    assert events[0]["scope_type"] == "http"
    assert get_context() == {}


@pytest.mark.asyncio
async def test_middleware_generates_request_id() -> None:
    events: list[dict[str, Any]] = []

    async def send(msg: dict[str, Any]) -> None:
        events.append(msg)

    async def receive() -> dict[str, Any]:
        return {"type": "noop"}

    middleware = TelemetryMiddleware(_dummy_app)
    await middleware({"type": "http", "headers": []}, receive, send)
    assert events[0]["scope_type"] == "http"


@pytest.mark.asyncio
async def test_middleware_binds_expected_context_and_clears(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, str | None]]] = []

    def _bind_context(**kwargs: str | None) -> None:
        calls.append(("bind", kwargs))

    def _clear_context() -> None:
        calls.append(("clear", {}))

    monkeypatch.setattr(middleware_mod, "bind_context", _bind_context)
    monkeypatch.setattr(middleware_mod, "clear_context", _clear_context)
    monkeypatch.setattr("undef.telemetry.asgi.middleware.uuid.uuid4", lambda: type("U", (), {"hex": "generated"})())

    sent: list[dict[str, Any]] = []
    received_token = object()

    async def send(msg: dict[str, Any]) -> None:
        sent.append(msg)

    async def receive() -> dict[str, Any]:
        return {"type": "receive", "token": "ok"}

    async def app(scope: dict[str, Any], recv: Any, send_fn: Any) -> None:
        assert recv is receive
        assert send_fn is send
        msg = await recv()
        assert msg["type"] == "receive"
        await send_fn({"type": "done", "scope_type": scope["type"], "token": received_token})

    middleware = TelemetryMiddleware(app)
    await middleware({"type": "http", "headers": []}, receive, send)

    assert sent == [{"type": "done", "scope_type": "http", "token": received_token}]
    assert calls[0] == ("bind", {"request_id": "generated"})
    assert calls[-1] == ("clear", {})


@pytest.mark.asyncio
async def test_middleware_passes_through_lifespan_without_context_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    bind = pytest.MonkeyPatch()
    clear = pytest.MonkeyPatch()
    try:
        bind_spy = {"count": 0}
        clear_spy = {"count": 0}

        def _bind_context(**kwargs: str | None) -> None:
            _ = kwargs
            bind_spy["count"] += 1

        def _clear_context() -> None:
            clear_spy["count"] += 1

        bind.setattr(middleware_mod, "bind_context", _bind_context)
        clear.setattr(middleware_mod, "clear_context", _clear_context)

        async def send(_: dict[str, Any]) -> None:
            return None

        async def receive() -> dict[str, Any]:
            return {"type": "noop"}

        async def app(scope: dict[str, Any], recv: Any, send_fn: Any) -> None:
            assert scope["type"] == "lifespan"
            assert recv is receive
            assert send_fn is send

        middleware = TelemetryMiddleware(app)
        await middleware({"type": "lifespan", "headers": []}, receive, send)
        assert bind_spy["count"] == 0
        assert clear_spy["count"] == 0
    finally:
        bind.undo()
        clear.undo()


def test_extract_header_none() -> None:
    assert _extract_header({"headers": []}, b"x-request-id") is None
    assert _extract_header({}, b"x-request-id") is None


def test_extract_header_positive_and_case_insensitive_name() -> None:
    scope = {"headers": [(b"X-Request-Id", b"rid"), (b"x-session-id", b"sid")]}
    assert _extract_header(scope, b"x-request-id") == "rid"
    assert _extract_header(scope, b"x-session-id") == "sid"
    assert _extract_header(scope, b"x-missing") is None


def test_websocket_context_binding() -> None:
    result = bind_websocket_context(
        {"headers": [(b"x-request-id", b"r2"), (b"x-session-id", b"s2"), (b"x-actor-id", b"u1")]}
    )
    assert result == {"request_id": "r2", "session_id": "s2", "actor_id": "u1"}
    assert ws_extract_header({"headers": []}, b"x-request-id") is None
    partial = bind_websocket_context({"headers": [(b"x-request-id", b"r3")]})
    assert partial == {"request_id": "r3", "session_id": None, "actor_id": None}
    no_request = bind_websocket_context({"headers": [(b"x-session-id", b"s3")]})
    assert no_request == {"request_id": None, "session_id": "s3", "actor_id": None}


def test_websocket_bind_context_invokes_only_present_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, str | None]] = []

    def _bind_context(**kwargs: str | None) -> None:
        calls.append(kwargs)

    monkeypatch.setattr("undef.telemetry.asgi.websocket.bind_context", _bind_context)

    result = bind_websocket_context(
        {"headers": [(b"x-request-id", b"r9"), (b"x-session-id", b"s9"), (b"x-actor-id", b"a9")]}
    )
    assert result == {"request_id": "r9", "session_id": "s9", "actor_id": "a9"}
    assert {"request_id": "r9"} in calls
    assert {"session_id": "s9"} in calls
    assert {"actor_id": "a9"} in calls
    assert {"request_id": None} not in calls
    assert {"session_id": None} not in calls
    assert {"actor_id": None} not in calls

    calls.clear()
    result = bind_websocket_context({"headers": [(b"x-session-id", b"s-only")]})
    assert result == {"request_id": None, "session_id": "s-only", "actor_id": None}
    assert calls == [{"session_id": "s-only"}]


def test_websocket_extract_header_missing_headers_key() -> None:
    assert ws_extract_header({}, b"x-request-id") is None


@pytest.mark.asyncio
async def test_middleware_websocket_path(monkeypatch: pytest.MonkeyPatch) -> None:
    bound: list[dict[str, str | None]] = []

    def _bind_context(**kwargs: str | None) -> None:
        bound.append(kwargs)

    monkeypatch.setattr(middleware_mod, "bind_context", _bind_context)

    async def send(_: dict[str, Any]) -> None:
        return None

    async def receive() -> dict[str, Any]:
        return {"type": "noop"}

    async def app(scope: dict[str, Any], _recv: Any, _send: Any) -> None:
        assert scope["type"] == "websocket"

    middleware = TelemetryMiddleware(app)
    await middleware(
        {"type": "websocket", "headers": [(b"x-request-id", b"rw"), (b"x-session-id", b"sw")]}, receive, send
    )
    assert {"request_id": "rw"} in bound
    assert {"session_id": "sw"} in bound
