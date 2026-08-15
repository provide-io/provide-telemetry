# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""The three ConsoleRenderer sites must render plain, colorless tracebacks.

structlog's default exception formatter is RichTracebackFormatter with
show_locals=True, which prints local variables from every frame — a
secret held in a local leaks into rendered output through any
``logger.error(..., exc_info=True)``. Each construction site pins
``exception_formatter=plain_traceback``; these tests hold the pin by
raising with a sentinel local and asserting it never renders.
"""

from __future__ import annotations

import sys
from typing import Any

import structlog

from provide.telemetry.logger.core import _plain_console_renderer
from provide.telemetry.testing import configure_caplog_for_structlog

_SENTINEL = "LOCAL-SECRET-c9d2"


def _exc_info_with_sentinel() -> Any:
    try:
        leaked_local = _SENTINEL  # noqa: F841 — exists to appear in frame locals
        raise ValueError("boom")
    except ValueError:
        return sys.exc_info()


def _render(renderer: Any) -> str:
    # The level key matters: ConsoleRenderer(colors=True) styles it with
    # ANSI, so its presence is what lets the no-escape assertion kill a
    # colors mutant in every venv — the otel-less mutation venv included.
    event: dict[str, Any] = {
        "event": "op.fail.error",
        "level": "error",
        "exc_info": _exc_info_with_sentinel(),
    }
    # structlog's renderer contract: (logger, method_name, event_dict) -> str.
    out = renderer(None, "error", event)
    assert isinstance(out, str)
    return out


def _assert_plain_and_leak_free(rendered: str) -> None:
    assert "Traceback (most recent call last)" in rendered
    assert "boom" in rendered
    assert _SENTINEL not in rendered
    assert "\x1b" not in rendered


def test_the_emergency_renderer_is_plain_colorless_and_leak_free() -> None:
    _assert_plain_and_leak_free(_render(_plain_console_renderer()))


def test_configure_logging_console_branch_renders_leak_free(capsys: Any) -> None:
    from provide.telemetry import setup_telemetry, shutdown_telemetry
    from provide.telemetry.config import TelemetryConfig

    cfg = TelemetryConfig.from_env()
    cfg.logging.fmt = "console"
    setup_telemetry(cfg)
    try:
        structlog.get_logger("leak").error("op.fail.error", exc_info=_exc_info_with_sentinel())
    finally:
        shutdown_telemetry()

    err = capsys.readouterr().err
    assert "op.fail.error" in err
    assert _SENTINEL not in err
    assert "\x1b" not in err


def test_the_caplog_helper_renders_leak_free() -> None:
    configure_caplog_for_structlog()
    try:
        renderer = structlog.get_config()["processors"][-1]
        _assert_plain_and_leak_free(_render(renderer))
    finally:
        structlog.reset_defaults()
