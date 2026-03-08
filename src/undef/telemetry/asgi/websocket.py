# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""WebSocket telemetry helpers."""

from __future__ import annotations

from typing import Any

from undef.telemetry.logger.context import bind_context


def bind_websocket_context(scope: dict[str, Any]) -> dict[str, str | None]:
    request_id = _extract_header(scope, b"x-request-id")
    session_id = _extract_header(scope, b"x-session-id")
    actor_id = _extract_header(scope, b"x-actor-id")
    if request_id is not None:
        bind_context(request_id=request_id)
    if session_id is not None:
        bind_context(session_id=session_id)
    if actor_id is not None:
        bind_context(actor_id=actor_id)
    return {"request_id": request_id, "session_id": session_id, "actor_id": actor_id}


def _extract_header(scope: dict[str, Any], key: bytes) -> str | None:
    for name, value in scope.get("headers", []):
        if name.lower() == key:
            return str(value.decode("utf-8"))  # pragma: no mutate
    return None
