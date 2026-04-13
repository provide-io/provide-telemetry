# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests for the rename_event_to_message structlog processor."""

from __future__ import annotations

import json
from typing import Any

from provide.telemetry.logger.processors import rename_event_to_message

# ── Unit tests for the processor itself ─────────────────────────────────────


def test_rename_event_to_msg_renames_event_key() -> None:
    event_dict: dict[str, Any] = {"event": "hello.world", "level": "INFO"}
    result = rename_event_to_message(None, "info", event_dict)
    assert result["message"] == "hello.world"
    assert "event" not in result


def test_rename_event_to_msg_no_op_when_event_absent() -> None:
    event_dict: dict[str, Any] = {"level": "INFO", "service": "probe"}
    result = rename_event_to_message(None, "info", event_dict)
    assert "message" not in result
    assert result == {"level": "INFO", "service": "probe"}


def test_rename_event_to_msg_preserves_other_fields() -> None:
    event_dict: dict[str, Any] = {
        "event": "test.event",
        "level": "DEBUG",
        "service": "svc",
        "trace_id": "abc",
    }
    result = rename_event_to_message(None, "debug", event_dict)
    assert result["message"] == "test.event"
    assert result["level"] == "DEBUG"
    assert result["service"] == "svc"
    assert result["trace_id"] == "abc"
    assert "event" not in result


# ── Integration: JSON format emits 'message' not 'event' ────────────────────


def test_json_logger_emits_msg_field(capsys: Any) -> None:
    """End-to-end: configure_logging in JSON mode must emit 'message', not 'event'."""
    import dataclasses

    from provide.telemetry.config import TelemetryConfig
    from provide.telemetry.logger import core as logger_core

    base = TelemetryConfig.from_env()
    json_logging = dataclasses.replace(
        base.logging,
        fmt="json",
        include_timestamp=False,
        sanitize=False,
    )
    config = dataclasses.replace(base, logging=json_logging)

    try:
        logger_core.configure_logging(config, force=True)
        log = logger_core.get_logger("probe")
        log.info("log.output.parity")
    finally:
        logger_core._reset_logging_for_tests()

    captured = capsys.readouterr()
    output = captured.err.strip()
    assert output, "expected JSON output on stderr"
    record = json.loads(output)
    assert record.get("message") == "log.output.parity", f"expected message field, got: {record}"
    assert "event" not in record, "'event' key must not appear in JSON output"
