# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""ASGI middleware for telemetry context propagation."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from undef.telemetry.logger.context import bind_context, clear_context

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]


class TelemetryMiddleware:
    def __init__(self, app: Callable[[Scope, Receive, Send], Awaitable[None]]) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return

        request_id = _extract_header(scope, b"x-request-id") or uuid.uuid4().hex
        session_id = _extract_header(scope, b"x-session-id")
        bind_context(request_id=request_id)
        if session_id is not None:
            bind_context(session_id=session_id)
        try:
            await self.app(scope, receive, send)
        finally:
            clear_context()


def _extract_header(scope: Scope, key: bytes) -> str | None:
    for name, value in scope.get("headers", []):
        if name.lower() == key:
            return str(value.decode("utf-8"))  # pragma: no mutate
    return None
