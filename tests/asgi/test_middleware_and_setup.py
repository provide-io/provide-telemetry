# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

from __future__ import annotations

from typing import Any

import pytest

from undef.telemetry.asgi import middleware as middleware_mod
from undef.telemetry.asgi.middleware import TelemetryMiddleware, _extract_header, _resolve_route
from undef.telemetry.asgi.websocket import _extract_header as ws_extract_header
from undef.telemetry.asgi.websocket import bind_websocket_context
from undef.telemetry.logger import get_context
from undef.telemetry.tracing import get_trace_context


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
    from undef.telemetry.logger.context import restore_context

    events: list[dict[str, Any]] = []

    async def send(msg: dict[str, Any]) -> None:
        events.append(msg)

    async def receive() -> dict[str, Any]:
        return {"type": "noop"}

    # Reset context to empty before test to ensure clean slate
    restore_context({})
    pre_ctx = get_context()

    middleware = TelemetryMiddleware(_dummy_app)
    scope = {
        "type": "http",
        "headers": [(b"x-request-id", b"r1"), (b"x-session-id", b"s1")],
    }
    await middleware(scope, receive, send)
    assert events[0]["scope_type"] == "http"
    # After middleware, context should be restored to pre-request state
    assert get_context() == pre_ctx


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
    calls: list[tuple[str, Any]] = []

    def _bind_context(**kwargs: str | None) -> None:
        calls.append(("bind", kwargs))

    def _get_context() -> dict[str, object]:
        return {}

    def _restore_context(snapshot: dict[str, object]) -> None:
        calls.append(("restore", snapshot))

    monkeypatch.setattr(middleware_mod, "bind_context", _bind_context)
    monkeypatch.setattr(middleware_mod, "get_context", _get_context)
    monkeypatch.setattr(middleware_mod, "restore_context", _restore_context)
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
    assert calls[-1] == ("restore", {})


@pytest.mark.asyncio
async def test_middleware_passes_through_lifespan_without_context_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    bind = pytest.MonkeyPatch()
    restore = pytest.MonkeyPatch()
    try:
        bind_spy = {"count": 0}
        restore_spy = {"count": 0}

        def _bind_context(**kwargs: str | None) -> None:
            _ = kwargs
            bind_spy["count"] += 1

        def _restore_context(snapshot: dict[str, object]) -> None:
            restore_spy["count"] += 1

        bind.setattr(middleware_mod, "bind_context", _bind_context)
        restore.setattr(middleware_mod, "restore_context", _restore_context)

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
        assert restore_spy["count"] == 0
    finally:
        bind.undo()
        restore.undo()


def test_extract_header_none() -> None:
    assert _extract_header({"headers": []}, b"x-request-id") is None
    assert _extract_header({}, b"x-request-id") is None


def test_extract_header_positive_and_case_insensitive_name() -> None:
    scope = {"headers": [(b"X-Request-Id", b"rid"), (b"x-session-id", b"sid")]}
    assert _extract_header(scope, b"x-request-id") == "rid"
    assert _extract_header(scope, b"x-session-id") == "sid"
    assert _extract_header(scope, b"x-missing") is None


def test_extract_header_decodes_non_utf8_via_latin1() -> None:
    scope = {"headers": [(b"x-request-id", b"\xff")]}
    assert _extract_header(scope, b"x-request-id") == "\xff"
    assert ws_extract_header(scope, b"x-request-id") == "\xff"


@pytest.mark.asyncio
async def test_middleware_ignores_malformed_header_bytes_without_crashing() -> None:
    events: list[dict[str, Any]] = []

    async def send(msg: dict[str, Any]) -> None:
        events.append(msg)

    async def receive() -> dict[str, Any]:
        return {"type": "noop"}

    middleware = TelemetryMiddleware(_dummy_app)
    await middleware({"type": "http", "headers": [(b"x-request-id", b"\xff")]}, receive, send)
    assert events[0]["scope_type"] == "http"


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


def test_resolve_route_with_starlette_route() -> None:
    route = type("Route", (), {"path": "/users/{user_id}"})()
    scope: dict[str, Any] = {"path": "/users/12345", "route": route}
    assert _resolve_route(scope) == "/users/{user_id}"


def test_resolve_route_without_route_key() -> None:
    scope: dict[str, Any] = {"path": "/users/12345"}
    assert _resolve_route(scope) == "/users/{id}"


def test_resolve_route_with_route_no_path_attr() -> None:
    scope: dict[str, Any] = {"path": "/users/12345", "route": object()}
    assert _resolve_route(scope) == "/users/{id}"


def test_cardinality_limit_registered_on_auto_slo() -> None:
    from undef.telemetry import cardinality as cardinality_mod

    cardinality_mod.clear_cardinality_limits()
    TelemetryMiddleware(_dummy_app, auto_slo=True)
    limits = cardinality_mod.get_cardinality_limits()
    assert "route" in limits
    assert limits["route"].max_values == 200
    cardinality_mod.clear_cardinality_limits()


def test_cardinality_limit_not_registered_without_auto_slo() -> None:
    from undef.telemetry import cardinality as cardinality_mod

    cardinality_mod.clear_cardinality_limits()
    TelemetryMiddleware(_dummy_app, auto_slo=False)
    assert "route" not in cardinality_mod.get_cardinality_limits()


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


@pytest.mark.asyncio
async def test_middleware_extracts_w3c_headers_and_clears_trace_context() -> None:
    seen_trace_ctx: dict[str, str | None] = {}

    async def send(_: dict[str, Any]) -> None:
        return None

    async def receive() -> dict[str, Any]:
        return {"type": "noop"}

    async def app(scope: dict[str, Any], _recv: Any, _send: Any) -> None:
        assert scope["type"] == "http"
        seen_trace_ctx.update(get_trace_context())
        traceparent = get_context()["traceparent"]
        assert isinstance(traceparent, str)
        assert traceparent.startswith("00-")
        assert get_context()["tracestate"] == "vendor=value"

    middleware = TelemetryMiddleware(app)
    await middleware(
        {
            "type": "http",
            "headers": [
                (b"x-request-id", b"rw"),
                (b"traceparent", b"00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"),
                (b"tracestate", b"vendor=value"),
            ],
        },
        receive,
        send,
    )
    assert seen_trace_ctx == {"trace_id": "4bf92f3577b34da6a3ce929d0e0e4736", "span_id": "00f067aa0ba902b7"}
    assert get_trace_context() == {"trace_id": None, "span_id": None}


@pytest.mark.asyncio
async def test_middleware_auto_slo_records_red_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    def _record_red_metrics(route: str, method: str, status_code: int, duration_ms: float) -> None:
        calls.append(
            {
                "route": route,
                "method": method,
                "status_code": status_code,
                "duration_ms": duration_ms,
            }
        )

    monkeypatch.setattr(middleware_mod, "record_red_metrics", _record_red_metrics)

    async def send(_: dict[str, Any]) -> None:
        return None

    async def receive() -> dict[str, Any]:
        return {"type": "noop"}

    async def app(_scope: dict[str, Any], _recv: Any, send_fn: Any) -> None:
        await send_fn({"type": "http.response.start", "status": 204})
        await send_fn({"type": "http.response.body", "body": b""})

    middleware = TelemetryMiddleware(app, auto_slo=True)
    route_obj = type("Route", (), {"path": "/ok"})()
    await middleware(
        {"type": "http", "path": "/ok/123", "method": "GET", "headers": [], "route": route_obj}, receive, send
    )
    assert len(calls) == 1
    assert calls[0]["route"] == "/ok"  # resolved from route.path, not raw path
    assert calls[0]["method"] == "GET"
    assert calls[0]["status_code"] == 204
    assert isinstance(calls[0]["duration_ms"], float)


@pytest.mark.asyncio
async def test_middleware_auto_slo_handles_non_int_http_status(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    def _record_red_metrics(route: str, method: str, status_code: int, duration_ms: float) -> None:
        calls.append(
            {
                "route": route,
                "method": method,
                "status_code": status_code,
                "duration_ms": duration_ms,
            }
        )

    monkeypatch.setattr(middleware_mod, "record_red_metrics", _record_red_metrics)

    async def send(_: dict[str, Any]) -> None:
        return None

    async def receive() -> dict[str, Any]:
        return {"type": "noop"}

    async def app(_scope: dict[str, Any], _recv: Any, send_fn: Any) -> None:
        await send_fn({"type": "http.response.start", "status": "oops"})
        await send_fn({"type": "http.response.body", "body": b""})

    middleware = TelemetryMiddleware(app, auto_slo=True)
    await middleware({"type": "http", "path": "/bad-status", "method": "GET", "headers": []}, receive, send)
    assert len(calls) == 1
    # Non-int status leaves default value untouched.
    assert calls[0]["status_code"] == 500


@pytest.mark.asyncio
async def test_middleware_auto_slo_logs_unhandled_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[tuple[str, dict[str, object]]] = []

    class _StubLogger:
        def error(self, event: str, **kwargs: object) -> None:
            events.append((event, kwargs))

    monkeypatch.setattr(middleware_mod, "get_logger", lambda _name: _StubLogger())
    monkeypatch.setattr(middleware_mod, "record_red_metrics", lambda *_args, **_kwargs: None)

    async def send(_: dict[str, Any]) -> None:
        return None

    async def receive() -> dict[str, Any]:
        return {"type": "noop"}

    async def app(_scope: dict[str, Any], _recv: Any, _send: Any) -> None:
        raise RuntimeError("boom")

    middleware = TelemetryMiddleware(app, auto_slo=True)
    with pytest.raises(RuntimeError, match="boom"):
        await middleware({"type": "http", "path": "/err", "method": "GET", "headers": []}, receive, send)

    assert len(events) == 1
    event_name_value, fields = events[0]
    assert event_name_value == "http.request.unhandled_exception"
    assert fields["exc_name"] == "RuntimeError"
    assert fields["path"] == "/err"


@pytest.mark.asyncio
async def test_middleware_exception_without_auto_slo(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[tuple[str, dict[str, object]]] = []

    class _StubLogger:
        def error(self, event: str, **kwargs: object) -> None:
            events.append((event, kwargs))

    monkeypatch.setattr(middleware_mod, "get_logger", lambda _name: _StubLogger())

    async def send(_: dict[str, Any]) -> None:
        return None

    async def receive() -> dict[str, Any]:
        return {"type": "noop"}

    async def app(_scope: dict[str, Any], _recv: Any, _send: Any) -> None:
        raise RuntimeError("boom")

    middleware = TelemetryMiddleware(app)
    with pytest.raises(RuntimeError, match="boom"):
        await middleware({"type": "http", "path": "/err", "headers": []}, receive, send)
    assert events == []


@pytest.mark.asyncio
async def test_middleware_auto_slo_websocket_status_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    def _record_red_metrics(route: str, method: str, status_code: int, duration_ms: float) -> None:
        calls.append(
            {
                "route": route,
                "method": method,
                "status_code": status_code,
                "duration_ms": duration_ms,
            }
        )

    monkeypatch.setattr(middleware_mod, "record_red_metrics", _record_red_metrics)

    async def send(_: dict[str, Any]) -> None:
        return None

    async def receive() -> dict[str, Any]:
        return {"type": "noop"}

    async def app(_scope: dict[str, Any], _recv: Any, send_fn: Any) -> None:
        await send_fn({"type": "websocket.accept"})
        await send_fn({"type": "websocket.close", "code": "bad"})
        await send_fn({"type": "websocket.close", "code": 1008})

    middleware = TelemetryMiddleware(app, auto_slo=True)
    await middleware({"type": "websocket", "path": "/ws", "headers": []}, receive, send)
    assert len(calls) == 1
    assert calls[0]["method"] == "WS"
    assert calls[0]["status_code"] == 1008
