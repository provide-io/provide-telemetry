# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Targeted mutation-kill tests for render_with_backpressure_extra."""

from __future__ import annotations

from typing import Any

from provide.telemetry.logger.processors import (
    _BACKPRESSURE_TICKET_KEY,
    render_with_backpressure_extra,
)


def test_render_with_backpressure_forwards_real_logger_and_method_name() -> None:
    """Mutants: `renderer(None, method_name, event_dict)` and
    `renderer(logger, None, event_dict)` replace the logger and method_name
    arguments with None. Pin: the wrapped renderer must receive the real
    logger object and method name that its caller passed in.
    """
    received: dict[str, Any] = {}

    def _renderer(logger: Any, method_name: str, event_dict: dict[str, Any]) -> str:
        received["logger"] = logger
        received["method_name"] = method_name
        received["event_dict"] = event_dict
        return "rendered"

    processor = render_with_backpressure_extra(_renderer)
    sentinel_logger = object()
    event = {"event": "evt.test", _BACKPRESSURE_TICKET_KEY: "tok"}
    args, kwargs = processor(sentinel_logger, "info", event)

    assert received["logger"] is sentinel_logger, "renderer must receive the caller-supplied logger, not None"
    assert received["method_name"] == "info", "renderer must receive the caller-supplied method_name, not None"
    assert args == ("rendered",)
    assert kwargs == {"extra": {_BACKPRESSURE_TICKET_KEY: "tok"}}


def test_render_with_backpressure_no_extra_when_no_ticket() -> None:
    def _renderer(_l: Any, _m: str, _e: dict[str, Any]) -> str:
        return "x"

    processor = render_with_backpressure_extra(_renderer)
    args, kwargs = processor(object(), "info", {"event": "evt"})
    assert args == ("x",)
    assert kwargs == {}
