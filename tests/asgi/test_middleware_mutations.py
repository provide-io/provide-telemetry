# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Tests targeting surviving mutation-testing mutants in asgi/middleware.py."""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import Mock

import pytest

from undef.telemetry.asgi import middleware as middleware_mod
from undef.telemetry.asgi.middleware import TelemetryMiddleware, _resolve_route


async def _noop_app(scope: dict[str, Any], receive: Any, send: Any) -> None:
    pass


async def _noop_send(msg: dict[str, Any]) -> None:
    pass


async def _noop_receive() -> dict[str, Any]:
    return {"type": "noop"}


# ── __init__ default auto_slo ────────────────────────────────────────


class TestInitDefaults:
    def test_auto_slo_defaults_to_false(self) -> None:
        """Kills: `auto_slo: bool = False` → `True`."""
        mw = TelemetryMiddleware(_noop_app)
        assert mw.auto_slo is False

    def test_auto_slo_true_sets_logger(self, monkeypatch: pytest.MonkeyPatch) -> None:
        logger_names: list[str | None] = []

        def _get_logger(name: str | None = None) -> Mock:
            logger_names.append(name)
            return Mock()

        monkeypatch.setattr(middleware_mod, "get_logger", _get_logger)
        monkeypatch.setattr(middleware_mod, "register_cardinality_limit", lambda *a, **kw: None)
        mw = TelemetryMiddleware(_noop_app, auto_slo=True)
        assert mw.auto_slo is True
        assert logger_names == ["undef.asgi"]

    def test_auto_slo_false_has_no_logger(self) -> None:
        mw = TelemetryMiddleware(_noop_app)
        assert mw._logger is None


# ── WebSocket accept → status_code = 101 ────────────────────────────


class TestWebSocketAcceptStatus:
    @pytest.mark.asyncio
    async def test_websocket_accept_sets_exactly_101(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Kills: `status_code = 101` → `102` or `None`."""
        recorded: list[dict[str, object]] = []

        def _record(route: str, method: str, status_code: int, duration_ms: float) -> None:
            recorded.append({"status_code": status_code})

        monkeypatch.setattr(middleware_mod, "record_red_metrics", _record)

        async def app(_scope: dict[str, Any], _recv: Any, send_fn: Any) -> None:
            await send_fn({"type": "websocket.accept"})

        mw = TelemetryMiddleware(app, auto_slo=True)
        await mw({"type": "websocket", "path": "/ws", "headers": []}, _noop_receive, _noop_send)
        assert recorded[0]["status_code"] == 101


# ── Exception handler logs with exc_info=True ────────────────────────


class TestExcInfoTrue:
    @pytest.mark.asyncio
    async def test_exception_log_has_exc_info_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Kills: `exc_info=True` → `False`/`None`/removed."""
        logged_kwargs: list[dict[str, object]] = []

        class _StubLogger:
            def error(self, event: str, **kwargs: object) -> None:
                logged_kwargs.append(kwargs)

        monkeypatch.setattr(middleware_mod, "get_logger", lambda _: _StubLogger())
        monkeypatch.setattr(middleware_mod, "record_red_metrics", lambda **kw: None)

        async def app(_scope: dict[str, Any], _recv: Any, _send: Any) -> None:
            raise ValueError("boom")

        mw = TelemetryMiddleware(app, auto_slo=True)
        with pytest.raises(ValueError, match="boom"):
            await mw({"type": "http", "path": "/err", "method": "GET", "headers": []}, _noop_receive, _noop_send)
        assert len(logged_kwargs) == 1
        assert logged_kwargs[0]["exc_info"] is True


# ── Duration calculation: * 1000, not / or + ─────────────────────────


class TestDurationCalculation:
    @pytest.mark.asyncio
    async def test_duration_ms_uses_multiplication(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Kills: `* 1000.0` → `/ 1000.0` or `+ 1000.0` or `* 1001.0`."""
        durations: list[float] = []

        def _record(route: str, method: str, status_code: int, duration_ms: float) -> None:
            durations.append(duration_ms)

        monkeypatch.setattr(middleware_mod, "record_red_metrics", _record)

        # Use a simple counter that returns 100.0 for even calls and 100.05
        # for odd calls. The middleware calls perf_counter at start (call N)
        # and end (call N+1), so we get a 50ms diff regardless of how many
        # calls other modules (e.g. resilience) make before the middleware.
        # We achieve this by replacing time in the middleware module directly.
        import types

        fake_time = types.SimpleNamespace(perf_counter=time.perf_counter)
        values = iter([100.0, 100.05])
        fake_time.perf_counter = lambda: next(values)
        monkeypatch.setattr(middleware_mod, "time", fake_time)

        async def app(_scope: dict[str, Any], _recv: Any, send_fn: Any) -> None:
            await send_fn({"type": "http.response.start", "status": 200})

        mw = TelemetryMiddleware(app, auto_slo=True)
        await mw({"type": "http", "path": "/ok", "method": "GET", "headers": []}, _noop_receive, _noop_send)

        assert len(durations) == 1
        # 0.05 * 1000 = 50.0; division would give 0.00005; addition would give 1000.05
        assert 49.0 <= durations[0] <= 51.0


# ── _resolve_route fallback "unknown" ────────────────────────────────


class TestResolveRouteFallback:
    def test_no_path_returns_unknown_normalized(self) -> None:
        """Kills: `scope.get('path', 'unknown')` → default mutated."""
        result = _resolve_route({})
        assert result == "unknown"

    def test_no_route_no_path_returns_unknown(self) -> None:
        result = _resolve_route({"route": None})
        assert result == "unknown"


# ── send(message) called with original message, not None ─────────────


class TestSendCalledWithOriginalMessage:
    @pytest.mark.asyncio
    async def test_wrapped_send_passes_original_message(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Kills: `await send(message)` → `await send(None)`."""
        monkeypatch.setattr(middleware_mod, "record_red_metrics", lambda **kw: None)
        sent_messages: list[dict[str, Any]] = []

        async def capture_send(msg: dict[str, Any]) -> None:
            sent_messages.append(msg)

        original_msg = {"type": "http.response.start", "status": 200}

        async def app(_scope: dict[str, Any], _recv: Any, send_fn: Any) -> None:
            await send_fn(original_msg)

        mw = TelemetryMiddleware(app, auto_slo=True)
        await mw(
            {"type": "http", "path": "/ok", "method": "GET", "headers": []},
            _noop_receive,
            capture_send,
        )
        assert len(sent_messages) == 1
        assert sent_messages[0] is original_msg


# ── auto_slo and _logger: `and` vs `or` ─────────────────────────────


class TestAutoSloAndLogger:
    @pytest.mark.asyncio
    async def test_no_log_when_auto_slo_false_even_with_exception(self) -> None:
        """Kills: `self.auto_slo and self._logger is not None` → `or`."""
        error_calls: list[str] = []

        class _SpyLogger:
            def error(self, event: str, **kwargs: object) -> None:
                error_calls.append(event)

        # Manually set a logger but keep auto_slo=False
        mw = TelemetryMiddleware(_noop_app)
        mw._logger = _SpyLogger()  # type: ignore[assignment]
        # auto_slo is False, so even with _logger set, no logging should happen

        async def app(_s: dict[str, Any], _r: Any, _send: Any) -> None:
            raise RuntimeError("boom")

        mw.app = app
        with pytest.raises(RuntimeError):
            await mw({"type": "http", "path": "/", "headers": []}, _noop_receive, _noop_send)
        assert error_calls == []


# ── scope.get("method", "UNKNOWN") default ─────────────────────────


class TestMethodDefault:
    @pytest.mark.asyncio
    async def test_http_scope_without_method_uses_unknown(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Kills: `scope.get('method', 'UNKNOWN')` → default mutated."""
        recorded: list[dict[str, object]] = []

        def _record(route: str, method: str, status_code: int, duration_ms: float) -> None:
            recorded.append({"method": method})

        monkeypatch.setattr(middleware_mod, "record_red_metrics", _record)

        async def app(_s: dict[str, Any], _r: Any, send_fn: Any) -> None:
            await send_fn({"type": "http.response.start", "status": 200})

        mw = TelemetryMiddleware(app, auto_slo=True)
        # http scope without "method" key
        await mw({"type": "http", "path": "/x", "headers": []}, _noop_receive, _noop_send)
        assert recorded[0]["method"] == "UNKNOWN"


# ── scope.get("type", "http") in exception handler ──────────────────


class TestExceptionScopeType:
    @pytest.mark.asyncio
    async def test_exception_event_name_uses_scope_type(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Kills: `scope.get('type', 'http')` key/default mutations in error handler."""
        logged_events: list[str] = []

        class _StubLogger:
            def error(self, event: str, **kwargs: object) -> None:
                logged_events.append(event)

        monkeypatch.setattr(middleware_mod, "get_logger", lambda _: _StubLogger())
        monkeypatch.setattr(middleware_mod, "record_red_metrics", lambda **kw: None)

        async def app(_s: dict[str, Any], _r: Any, _send: Any) -> None:
            raise RuntimeError("boom")

        mw = TelemetryMiddleware(app, auto_slo=True)
        with pytest.raises(RuntimeError):
            await mw({"type": "http", "path": "/err", "method": "GET", "headers": []}, _noop_receive, _noop_send)
        assert len(logged_events) == 1
        assert "http" in logged_events[0]

    @pytest.mark.asyncio
    async def test_exception_exc_name_is_class_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Kills: `exc.__class__.__name__` mutations."""
        logged_kwargs: list[dict[str, object]] = []

        class _StubLogger:
            def error(self, event: str, **kwargs: object) -> None:
                logged_kwargs.append(kwargs)

        monkeypatch.setattr(middleware_mod, "get_logger", lambda _: _StubLogger())
        monkeypatch.setattr(middleware_mod, "record_red_metrics", lambda **kw: None)

        async def app(_s: dict[str, Any], _r: Any, _send: Any) -> None:
            raise ValueError("test")

        mw = TelemetryMiddleware(app, auto_slo=True)
        with pytest.raises(ValueError):
            await mw({"type": "http", "path": "/err", "method": "GET", "headers": []}, _noop_receive, _noop_send)
        assert logged_kwargs[0]["exc_name"] == "ValueError"


# ── scope.get("path", "unknown") in exception handler ───────────────


class TestExceptionPathDefault:
    @pytest.mark.asyncio
    async def test_exception_path_default_is_unknown(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Kills: `scope.get('path', 'unknown')` default mutated in error handler."""
        logged_kwargs: list[dict[str, object]] = []

        class _StubLogger:
            def error(self, event: str, **kwargs: object) -> None:
                logged_kwargs.append(kwargs)

        monkeypatch.setattr(middleware_mod, "get_logger", lambda _: _StubLogger())
        monkeypatch.setattr(middleware_mod, "record_red_metrics", lambda **kw: None)

        async def app(_s: dict[str, Any], _r: Any, _send: Any) -> None:
            raise RuntimeError("boom")

        mw = TelemetryMiddleware(app, auto_slo=True)
        # scope without "path" key
        with pytest.raises(RuntimeError):
            await mw({"type": "http", "headers": []}, _noop_receive, _noop_send)
        assert logged_kwargs[0]["path"] == "unknown"


# ── WebSocket message.get("type") key/value checks ──────────────────


class TestWebSocketMessageType:
    @pytest.mark.asyncio
    async def test_websocket_close_with_int_code_overrides(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Kills mutations on message.get('type') == 'websocket.close' and code handling."""
        recorded: list[dict[str, object]] = []

        def _record(route: str, method: str, status_code: int, duration_ms: float) -> None:
            recorded.append({"status_code": status_code})

        monkeypatch.setattr(middleware_mod, "record_red_metrics", _record)

        async def app(_scope: dict[str, Any], _recv: Any, send_fn: Any) -> None:
            await send_fn({"type": "websocket.accept"})
            await send_fn({"type": "websocket.close", "code": 1001})

        mw = TelemetryMiddleware(app, auto_slo=True)
        await mw({"type": "websocket", "path": "/ws", "headers": []}, _noop_receive, _noop_send)
        # After accept (101) then close with 1001, final status_code = 1001
        assert recorded[0]["status_code"] == 1001

    @pytest.mark.asyncio
    async def test_http_response_start_captures_status(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Kills mutations on message.get('type') == 'http.response.start'."""
        recorded: list[dict[str, object]] = []

        def _record(route: str, method: str, status_code: int, duration_ms: float) -> None:
            recorded.append({"status_code": status_code})

        monkeypatch.setattr(middleware_mod, "record_red_metrics", _record)

        async def app(_scope: dict[str, Any], _recv: Any, send_fn: Any) -> None:
            await send_fn({"type": "http.response.start", "status": 418})

        mw = TelemetryMiddleware(app, auto_slo=True)
        await mw({"type": "http", "path": "/tea", "method": "GET", "headers": []}, _noop_receive, _noop_send)
        assert recorded[0]["status_code"] == 418
