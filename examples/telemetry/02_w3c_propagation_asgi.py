#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""🌐 W3C trace-context propagation through ASGI middleware.

Demonstrates:
- TelemetryMiddleware with auto_slo=True for automatic RED metrics
- W3C traceparent/tracestate/baggage header extraction
- bind_propagation_context / clear_propagation_context lifecycle
- WebSocket context binding via bind_websocket_context
- get_trace_context for downstream correlation
"""

from __future__ import annotations

import asyncio
from typing import Any

from provide.telemetry import (
    TelemetryMiddleware,
    bind_websocket_context,
    clear_websocket_context,
    extract_w3c_context,
    get_logger,
    get_trace_context,
    setup_telemetry,
    shutdown_telemetry,
)
from provide.telemetry.logger.context import get_context
from provide.telemetry.propagation import bind_propagation_context, clear_propagation_context


async def _app(scope: dict[str, Any], _receive: Any, send: Any) -> None:
    log = get_logger("examples.w3c")
    if scope["type"] == "websocket":
        log.info("example.w3c.websocket", context=get_context())
        await send({"type": "websocket.accept"})
        await send({"type": "websocket.close", "code": 1000})
        return
    log.info("example.w3c.received", context=get_context())
    log.info("example.w3c.trace", trace_context=get_trace_context())
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


async def _run_http() -> None:
    """🔗 HTTP request with full W3C header propagation and auto_slo."""
    print("\n🔗 HTTP request with auto_slo=True")
    middleware = TelemetryMiddleware(_app, auto_slo=True)

    async def _receive() -> dict[str, Any]:
        return {"type": "http.request"}

    responses: list[dict[str, Any]] = []

    async def _send(msg: dict[str, Any]) -> None:
        responses.append(msg)

    scope: dict[str, Any] = {
        "type": "http",
        "method": "GET",
        "path": "/api/match",
        "headers": [
            (b"x-request-id", b"req-w3c-1"),
            (b"traceparent", b"00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"),
            (b"tracestate", b"vendor=value"),
            (b"baggage", b"user_id=123"),
        ],
    }

    extracted = extract_w3c_context(scope)
    print(f"  📥 Extracted trace_id={extracted.trace_id}")
    print(f"  📥 Extracted span_id={extracted.span_id}")
    print(f"  📥 Baggage: {extracted.baggage}")

    await middleware(scope, _receive, _send)
    print(f"  ✅ Response status: {responses[0].get('status', '?')}")


async def _run_websocket() -> None:
    """🔌 WebSocket request with context binding."""
    print("\n🔌 WebSocket with auto_slo=True")
    middleware = TelemetryMiddleware(_app, auto_slo=True)

    async def _receive() -> dict[str, Any]:
        return {"type": "websocket.connect"}

    async def _send(_: dict[str, Any]) -> None:
        pass

    scope: dict[str, Any] = {
        "type": "websocket",
        "path": "/ws/game",
        "headers": [
            (b"x-request-id", b"ws-001"),
            (b"x-session-id", b"session-42"),
        ],
    }
    await middleware(scope, _receive, _send)
    print("  ✅ WebSocket lifecycle complete")


async def _run_manual_propagation() -> None:
    """🧪 Manual bind/clear lifecycle (without middleware)."""
    print("\n🧪 Manual propagation context bind/clear")
    scope: dict[str, Any] = {
        "headers": [
            (b"traceparent", b"00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01"),
            (b"tracestate", b"game=chess"),
        ]
    }
    ctx = extract_w3c_context(scope)
    bind_propagation_context(ctx)
    trace_ctx = get_trace_context()
    print(f"  🔍 Bound trace_id={trace_ctx['trace_id']}")
    print(f"  🔍 Bound span_id={trace_ctx['span_id']}")

    clear_propagation_context()
    after = get_trace_context()
    print(f"  🧹 After clear: trace_id={after['trace_id']}")


async def _run_websocket_context() -> None:
    """🎮 bind_websocket_context helper."""
    print("\n🎮 bind_websocket_context for game session")
    ws_scope: dict[str, Any] = {
        "type": "websocket",
        "path": "/ws/game",
        "headers": [
            (b"x-request-id", b"game-session-99"),
            (b"x-session-id", b"session-42"),
            (b"x-actor-id", b"player-7"),
        ],
    }
    token = bind_websocket_context(ws_scope)
    ctx = get_context()
    print(f"  📋 request_id={ctx.get('request_id')}")
    print(f"  📋 session_id={ctx.get('session_id')}")
    print(f"  📋 actor_id={ctx.get('actor_id')}")
    clear_websocket_context(token)


def main() -> None:
    print("🌐 W3C Propagation & ASGI Middleware Demo")
    setup_telemetry()

    asyncio.run(_run_http())
    asyncio.run(_run_websocket())
    asyncio.run(_run_manual_propagation())
    asyncio.run(_run_websocket_context())

    print("\n🏁 Done!")
    shutdown_telemetry()


if __name__ == "__main__":
    main()
