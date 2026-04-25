# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""End-to-end test: module-level override can PROMOTE a module's effective
log level above the global default.

Regression guard for the bug where :func:`configure_logging` pinned the
stdlib root to ``config.logging.level`` but computed ``effective_level``
(the min of default + all module overrides) only for structlog's
``FilteringBoundLogger``.  Net effect: when default was ``INFO`` and a
module had ``DEBUG`` promoted via ``module_levels``, stdlib's root still
dropped the DEBUG record before it ever reached structlog's per-module
``_LevelFilter`` processor.

Pure unit coverage of ``_LevelFilter`` did not catch this because the
processor only sees records that made it through stdlib; the bug lives
above it in the pipeline.
"""

from __future__ import annotations

import json

import pytest

from provide.telemetry.config import TelemetryConfig
from provide.telemetry.logger.core import (
    _reset_logging_for_tests,
    configure_logging,
    get_logger,
)


def _parse_records(stderr_text: str) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for line in stderr_text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def _cfg_with_module_override() -> TelemetryConfig:
    return TelemetryConfig.from_env(
        {
            "PROVIDE_LOG_LEVEL": "INFO",
            "PROVIDE_LOG_FORMAT": "json",
            "PROVIDE_LOG_INCLUDE_TIMESTAMP": "false",
            "PROVIDE_LOG_INCLUDE_CALLER": "false",
            "PROVIDE_LOG_MODULE_LEVELS": "probe.child=DEBUG",
        }
    )


def test_module_level_override_promotes_above_global_default(capfd: pytest.CaptureFixture[str]) -> None:
    """DEBUG on an overridden module reaches output even when global is INFO."""
    _reset_logging_for_tests()
    configure_logging(_cfg_with_module_override())
    try:
        get_logger("probe.child").debug("debug.event.reached")
    finally:
        _reset_logging_for_tests()

    captured = capfd.readouterr()
    records = _parse_records(captured.err)
    messages = [r.get("message") for r in records]
    assert "debug.event.reached" in messages, (
        f"Expected the DEBUG event to reach output when probe.child is promoted to DEBUG; got stderr: {captured.err!r}"
    )


def test_unpromoted_module_still_filtered_at_global_info(capfd: pytest.CaptureFixture[str]) -> None:
    """DEBUG on a NON-overridden module is still dropped at global INFO."""
    _reset_logging_for_tests()
    configure_logging(_cfg_with_module_override())
    try:
        get_logger("probe.sibling").debug("debug.should.drop")
    finally:
        _reset_logging_for_tests()

    captured = capfd.readouterr()
    records = _parse_records(captured.err)
    messages = [r.get("message") for r in records]
    assert "debug.should.drop" not in messages, (
        f"Expected the DEBUG event on an unpromoted module to stay filtered at global INFO; got records: {records}"
    )
