# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Async task cancellation tests for ASGI middleware.

Verifies that the TelemetryMiddleware properly cleans up context
(propagation + logger) even when the request task is cancelled.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from undef.telemetry.asgi import middleware as middleware_mod
from undef.telemetry.asgi.middleware import TelemetryMiddleware
from undef.telemetry.logger.context import clear_context, get_context
from undef.telemetry.tracing.context import get_trace_context, set_trace_context


@pytest.fixture(autouse=True)
def _clean_context() -> None:
    """Ensure context is clean before each test."""
    clear_context()
    set_trace_context(None, None)


async def _noop_receive() -> dict[str, Any]:
    return {"type": "noop"}


async def _noop_send(_msg: dict[str, Any]) -> None:
    return None


async def test_middleware_cleans_context_on_cancellation() -> None:
    """CancelledError during request processing still runs finally block."""
    app_entered = asyncio.Event()

    async def _blocking_app(_scope: dict[str, Any], _recv: Any, _send: Any) -> None:
        app_entered.set()
        await asyncio.sleep(999)  # block until cancelled

    middleware = TelemetryMiddleware(_blocking_app)
    scope = {
        "type": "http",
        "headers": [(b"x-request-id", b"cancel-test"), (b"x-session-id", b"sess-cancel")],
    }

    task = asyncio.create_task(middleware(scope, _noop_receive, _noop_send))
    await asyncio.wait_for(app_entered.wait(), timeout=5)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=5)

    # Context must be cleared even after cancellation
    assert get_context() == {}
    assert get_trace_context() == {"trace_id": None, "span_id": None}


async def test_middleware_cleans_context_on_cancellation_with_auto_slo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancellation with auto_slo=True still cleans up and records metrics."""
    red_calls: list[dict[str, object]] = []

    def _record_red_metrics(route: str, method: str, status_code: int, duration_ms: float) -> None:
        red_calls.append({"route": route, "method": method, "status_code": status_code})

    monkeypatch.setattr(middleware_mod, "record_red_metrics", _record_red_metrics)

    app_entered = asyncio.Event()

    async def _blocking_app(_scope: dict[str, Any], _recv: Any, _send: Any) -> None:
        app_entered.set()
        await asyncio.sleep(999)

    middleware = TelemetryMiddleware(_blocking_app, auto_slo=True)
    scope = {
        "type": "http",
        "path": "/slow",
        "method": "POST",
        "headers": [(b"x-request-id", b"cancel-slo")],
    }

    task = asyncio.create_task(middleware(scope, _noop_receive, _noop_send))
    await asyncio.wait_for(app_entered.wait(), timeout=5)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=5)

    assert get_context() == {}
    # auto_slo metrics recorded in finally block before re-raising
    assert len(red_calls) == 1
    assert red_calls[0]["status_code"] == 500
    assert red_calls[0]["method"] == "POST"


async def test_middleware_websocket_cancellation_cleans_context() -> None:
    """WebSocket connections cancelled mid-stream still clean up."""
    app_entered = asyncio.Event()

    async def _ws_app(_scope: dict[str, Any], _recv: Any, _send: Any) -> None:
        app_entered.set()
        await asyncio.sleep(999)

    middleware = TelemetryMiddleware(_ws_app)
    scope = {
        "type": "websocket",
        "headers": [(b"x-request-id", b"ws-cancel"), (b"x-session-id", b"ws-sess")],
    }

    task = asyncio.create_task(middleware(scope, _noop_receive, _noop_send))
    await asyncio.wait_for(app_entered.wait(), timeout=5)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=5)

    assert get_context() == {}
    assert get_trace_context() == {"trace_id": None, "span_id": None}


async def test_middleware_concurrent_requests_isolated_context() -> None:
    """Multiple concurrent HTTP requests maintain isolated contexts."""
    seen_contexts: dict[str, dict[str, object]] = {}
    ready = asyncio.Event()
    proceed = asyncio.Event()

    async def _capturing_app(scope: dict[str, Any], _recv: Any, _send: Any) -> None:
        rid = scope["_test_id"]
        seen_contexts[rid] = dict(get_context())
        if rid == "first":
            ready.set()
            await asyncio.sleep(0)  # yield to let second request start
            await proceed.wait()

    middleware = TelemetryMiddleware(_capturing_app)

    async def _run_request(request_id: str, test_id: str) -> None:
        scope = {
            "type": "http",
            "headers": [(b"x-request-id", request_id.encode())],
            "_test_id": test_id,
        }
        await middleware(scope, _noop_receive, _noop_send)

    task1 = asyncio.create_task(_run_request("req-aaa", "first"))
    await ready.wait()
    task2 = asyncio.create_task(_run_request("req-bbb", "second"))
    await asyncio.sleep(0)  # let second complete
    proceed.set()
    await asyncio.gather(task1, task2)

    assert seen_contexts["first"]["request_id"] == "req-aaa"
    assert seen_contexts["second"]["request_id"] == "req-bbb"
    assert get_context() == {}
