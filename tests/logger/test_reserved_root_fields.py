# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Reserved root fields: the SDK's stamped value replaces a caller-supplied one.

``service``, ``env``, ``version``, ``trace_id`` and ``span_id`` say which
process and which trace wrote a record. A caller passing ``service="billing"``
as an ordinary keyword used to keep it (``setdefault``), so one service's
records could read as another's. Where the SDK has a value -- a non-empty
config field, a live span -- it wins; where it has none, the caller's stands.
These are the cross-language contract cases ``reserved_root_fields_sdk_wins``
and ``reserved_root_fields_unstamped_caller_stands``.
"""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Iterator
from typing import Any

import pytest

from provide.telemetry.config import LoggingConfig, TelemetryConfig
from provide.telemetry.logger.core import _reset_logging_for_tests, configure_logging, get_logger
from provide.telemetry.logger.processors import add_standard_fields
from provide.telemetry.logger.sink import clear_log_output, set_log_output
from provide.telemetry.tracing.context import set_trace_context

_LIVE_TRACE = "aabbccdd11223344aabbccdd11223344"
_LIVE_SPAN = "aabb001122334455"
_CALLER: dict[str, Any] = {
    "service": "caller-service",
    "env": "caller-env",
    "version": "9.9.9",
    "trace_id": "deadbeefdeadbeefdeadbeefdeadbeef",
    "span_id": "deadbeefdeadbeef",
}


@pytest.fixture
def emit() -> Iterator[Any]:
    root = logging.getLogger()
    saved, saved_level = list(root.handlers), root.level
    buffer = io.StringIO()

    def _emit(config: TelemetryConfig) -> dict[str, Any]:
        _reset_logging_for_tests()
        set_log_output(buffer)
        configure_logging(config, force=True)
        get_logger("reserved").info("reserved.fields.ok", **_CALLER)
        line: dict[str, Any] = json.loads(buffer.getvalue().strip().splitlines()[-1])
        return line

    try:
        yield _emit
    finally:
        set_trace_context(None, None)
        clear_log_output()
        _reset_logging_for_tests()
        root.handlers[:] = saved
        root.setLevel(saved_level)


def test_sdk_stamped_values_replace_caller_supplied_ones(emit: Any) -> None:
    set_trace_context(_LIVE_TRACE, _LIVE_SPAN)
    line = emit(
        TelemetryConfig(service_name="svc", environment="prod", version="1.2.3", logging=LoggingConfig(fmt="json"))
    )
    assert (line["service"], line["env"], line["version"]) == ("svc", "prod", "1.2.3")
    assert (line["trace_id"], line["span_id"]) == (_LIVE_TRACE, _LIVE_SPAN)


def test_caller_values_stand_where_the_sdk_stamps_nothing(emit: Any) -> None:
    set_trace_context(None, None)
    line = emit(TelemetryConfig(service_name="svc", environment="", version="", logging=LoggingConfig(fmt="json")))
    # A non-empty config value still wins; an empty one leaves the caller's.
    assert line["service"] == "svc"
    assert (line["env"], line["version"]) == ("caller-env", "9.9.9")
    # No live span: the caller's trace and span ids are the only ones there are.
    assert (line["trace_id"], line["span_id"]) == (_CALLER["trace_id"], _CALLER["span_id"])


@pytest.mark.parametrize(
    ("configured", "supplied", "expected"),
    [("svc", "caller", "svc"), ("svc", None, "svc"), ("", "caller", "caller"), ("", None, "")],
    ids=["sdk-wins", "sdk-fills", "caller-stands", "empty-filled"],
)
def test_add_standard_fields_stamping_rule(configured: str, supplied: str | None, expected: str) -> None:
    processor = add_standard_fields(
        TelemetryConfig(service_name="s", environment=configured, version=configured, logging=LoggingConfig(fmt="json"))
    )
    event: dict[str, Any] = {} if supplied is None else {"env": supplied, "version": supplied}
    result = processor(None, "info", event)
    assert (result["env"], result["version"]) == (expected, expected)
