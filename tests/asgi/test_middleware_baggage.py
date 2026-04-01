# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests for W3C baggage session extraction in ASGI middleware."""

from __future__ import annotations

from typing import Any

import pytest

from provide.telemetry.asgi import middleware as middleware_mod
from provide.telemetry.asgi.middleware import TelemetryMiddleware


@pytest.mark.asyncio
async def test_middleware_extracts_session_from_baggage(monkeypatch: pytest.MonkeyPatch) -> None:
    """Session ID should be extracted from W3C baggage header."""
    captured_session: list[str] = []

    monkeypatch.setattr(middleware_mod, "bind_session_context", lambda sid: captured_session.append(sid))
    monkeypatch.setattr(middleware_mod, "bind_context", lambda **kw: None)

    async def send(_: dict[str, Any]) -> None:
        return None

    async def receive() -> dict[str, Any]:
        return {"type": "noop"}

    async def app(scope: dict[str, Any], _recv: Any, _send: Any) -> None:
        assert scope["type"] == "http"

    middleware = TelemetryMiddleware(app)
    await middleware(
        {
            "type": "http",
            "headers": [(b"baggage", b"session_id=bag-sess-1,other=val")],
        },
        receive,
        send,
    )
    assert captured_session == ["bag-sess-1"]


@pytest.mark.asyncio
async def test_middleware_prefers_x_session_id_over_baggage(monkeypatch: pytest.MonkeyPatch) -> None:
    """x-session-id header takes priority over W3C baggage session_id."""
    captured_session: list[str] = []

    monkeypatch.setattr(middleware_mod, "bind_session_context", lambda sid: captured_session.append(sid))
    monkeypatch.setattr(middleware_mod, "bind_context", lambda **kw: None)

    async def send(_: dict[str, Any]) -> None:
        return None

    async def receive() -> dict[str, Any]:
        return {"type": "noop"}

    async def app(scope: dict[str, Any], _recv: Any, _send: Any) -> None:
        assert scope["type"] == "http"

    middleware = TelemetryMiddleware(app)
    await middleware(
        {
            "type": "http",
            "headers": [
                (b"x-session-id", b"header-sess"),
                (b"baggage", b"session_id=baggage-sess"),
            ],
        },
        receive,
        send,
    )
    assert captured_session == ["header-sess"]


@pytest.mark.asyncio
async def test_middleware_no_session_without_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    """No session binding when neither x-session-id nor baggage provides one."""
    captured_session: list[str] = []

    monkeypatch.setattr(middleware_mod, "bind_session_context", lambda sid: captured_session.append(sid))
    monkeypatch.setattr(middleware_mod, "bind_context", lambda **kw: None)

    async def send(_: dict[str, Any]) -> None:
        return None

    async def receive() -> dict[str, Any]:
        return {"type": "noop"}

    async def app(scope: dict[str, Any], _recv: Any, _send: Any) -> None:
        assert scope["type"] == "http"

    middleware = TelemetryMiddleware(app)
    await middleware({"type": "http", "headers": []}, receive, send)
    assert captured_session == []


@pytest.mark.asyncio
async def test_middleware_baggage_without_session_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Baggage header present but without session_id key yields no session binding."""
    captured_session: list[str] = []

    monkeypatch.setattr(middleware_mod, "bind_session_context", lambda sid: captured_session.append(sid))
    monkeypatch.setattr(middleware_mod, "bind_context", lambda **kw: None)

    async def send(_: dict[str, Any]) -> None:
        return None

    async def receive() -> dict[str, Any]:
        return {"type": "noop"}

    async def app(scope: dict[str, Any], _recv: Any, _send: Any) -> None:
        assert scope["type"] == "http"

    middleware = TelemetryMiddleware(app)
    await middleware(
        {
            "type": "http",
            "headers": [(b"baggage", b"other=val,foo=bar")],
        },
        receive,
        send,
    )
    assert captured_session == []
