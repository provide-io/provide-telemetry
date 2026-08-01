# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests killing surviving mutants in the ASGI middleware's unhandled-exception path.

The scope type selects the event name an unhandled exception is reported under
("http.request.unhandled_exception" vs "websocket.request.unhandled_exception").
Reading the wrong key, or defaulting to the wrong value, files WebSocket failures
under the HTTP event name — so an operator alerting on one signal misses the other.

Covers:
  TelemetryMiddleware.__call__: the scope type key selecting the event name
  TelemetryMiddleware.__call__: seconds-to-milliseconds duration conversion
"""

from __future__ import annotations

from typing import Any

import pytest

from provide.telemetry.asgi import middleware as mw_mod
from provide.telemetry.asgi.middleware import TelemetryMiddleware


class _RecordingLogger:
    def __init__(self) -> None:
        self.errors: list[tuple[str, dict[str, Any]]] = []

    def error(self, event: str, **kw: Any) -> None:
        self.errors.append((event, kw))

    def __getattr__(self, _name: str) -> Any:
        return lambda *a, **k: None


async def _boom_app(scope: Any, receive: Any, send: Any) -> None:
    raise RuntimeError("handler exploded")


def _middleware() -> tuple[TelemetryMiddleware, _RecordingLogger]:
    mw = TelemetryMiddleware(_boom_app, auto_slo=True)
    logger = _RecordingLogger()
    mw._logger = logger  # type: ignore[assignment]
    return mw, logger


async def _run(mw: TelemetryMiddleware, scope: dict[str, Any]) -> None:
    async def _receive() -> dict[str, Any]:
        return {"type": "http.request"}

    async def _send(_message: dict[str, Any]) -> None:
        return None

    with pytest.raises(RuntimeError, match="handler exploded"):
        await mw(scope, _receive, _send)


@pytest.mark.parametrize(
    ("scope_type", "expected_prefix"),
    [("http", "http"), ("websocket", "websocket")],
)
async def test_exception_event_name_follows_the_scope_type(scope_type: str, expected_prefix: str) -> None:
    """The "type" key must be read; a renamed key falls back to the default."""
    mw, logger = _middleware()

    await _run(mw, {"type": scope_type, "path": "/x", "headers": []})

    assert logger.errors, "an unhandled exception must be reported"
    event, _ = logger.errors[0]
    assert event.startswith(expected_prefix)


async def test_duration_is_reported_in_milliseconds(monkeypatch: Any) -> None:
    """1.0s elapsed must record exactly 1000.0ms — 1001.0 is a real drift."""
    recorded: list[float] = []
    ticks = iter([100.0, 101.0])

    monkeypatch.setattr("provide.telemetry.asgi.middleware.time.perf_counter", lambda: next(ticks))
    monkeypatch.setattr(
        mw_mod,
        "record_red_metrics",
        lambda **kw: recorded.append(kw["duration_ms"]),
    )

    mw, _ = _middleware()
    await _run(mw, {"type": "http", "path": "/x", "headers": [], "method": "GET"})

    assert recorded == [1000.0]
