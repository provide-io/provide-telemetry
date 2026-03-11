#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

from __future__ import annotations

import asyncio
from typing import Any

from undef.telemetry import (
    TelemetryMiddleware,
    extract_w3c_context,
    get_logger,
    get_trace_context,
    setup_telemetry,
    shutdown_telemetry,
)
from undef.telemetry.logger import get_context


async def _app(_scope: dict[str, Any], _receive: Any, _send: Any) -> None:
    log = get_logger("examples.w3c")
    log.info("example.w3c.received", context=get_context())
    log.info("example.w3c.context", trace_context=get_trace_context())


async def _run_once() -> None:
    middleware = TelemetryMiddleware(_app)

    async def _receive() -> dict[str, Any]:
        return {"type": "http.request"}

    async def _send(_: dict[str, Any]) -> None:
        return None

    scope = {
        "type": "http",
        "headers": [
            (b"x-request-id", b"req-w3c-1"),
            (b"traceparent", b"00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"),
            (b"tracestate", b"vendor=value"),
            (b"baggage", b"user_id=123"),
        ],
    }
    extracted = extract_w3c_context(scope)
    get_logger("examples.w3c").info("example.w3c.extracted", extracted=extracted)
    await middleware(scope, _receive, _send)


def main() -> None:
    setup_telemetry()
    asyncio.run(_run_once())
    shutdown_telemetry()


if __name__ == "__main__":
    main()
