# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""A stamped value that replaces a different caller value is counted and reported.

reserved_root_fields.replacement_reporting in spec/telemetry-api.yaml, and the
contract case ``reserved_root_fields_replacement_reported``. Replacing a field
silently loses the caller's data -- a ``version`` meaning a schema version, say
-- so it adds to ``reserved_field_replacements``, and the first replacement of
each field in the process logs one warning naming the field.
"""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Callable, Iterator
from typing import Any

import pytest

from provide.telemetry.config import LoggingConfig, TelemetryConfig
from provide.telemetry.health import get_health_snapshot, reset_health_for_tests
from provide.telemetry.logger import _reserved_fields
from provide.telemetry.logger.context import bind_context, clear_context
from provide.telemetry.logger.core import _reset_logging_for_tests, configure_logging, get_logger
from provide.telemetry.logger.sink import clear_log_output, set_log_output
from provide.telemetry.sampling import SamplingPolicy, reset_sampling_for_tests, set_sampling_policy
from provide.telemetry.tracing.context import set_trace_context

_LIVE_TRACE = "aabbccdd11223344aabbccdd11223344"
_LIVE_SPAN = "aabb001122334455"
_WARNING = "logger.reserved_field.replaced"

Emit = Callable[..., list[dict[str, Any]]]


def _config(fmt: str = "json", **overrides: Any) -> TelemetryConfig:
    values: dict[str, Any] = {"service_name": "svc", "environment": "prod", "version": "1.2.3"}
    values.update(overrides)
    return TelemetryConfig(logging=LoggingConfig(fmt=fmt), **values)


@pytest.fixture
def emit() -> Iterator[Callable[[TelemetryConfig], Emit]]:
    root = logging.getLogger()
    saved, saved_level = list(root.handlers), root.level
    buffer = io.StringIO()
    reset_health_for_tests()

    def _configure(config: TelemetryConfig) -> Emit:
        _reset_logging_for_tests()
        set_log_output(buffer)
        configure_logging(config, force=True)

        def _emit(event: str = "reserved.fields.ok", **fields: Any) -> list[dict[str, Any]]:
            buffer.truncate(0)
            buffer.seek(0)
            get_logger("reserved").info(event, **fields)
            return [json.loads(line) for line in buffer.getvalue().splitlines() if line.startswith("{")]

        return _emit

    try:
        yield _configure
    finally:
        set_trace_context(None, None)
        clear_context()
        clear_log_output()
        _reset_logging_for_tests()
        reset_sampling_for_tests()
        root.handlers[:] = saved
        root.setLevel(saved_level)


def _replacements() -> int:
    return get_health_snapshot().reserved_field_replacements


def _warnings(lines: list[dict[str, Any]]) -> list[str]:
    return [line["field"] for line in lines if line.get("message") == _WARNING]


def test_a_replaced_field_is_counted_and_warned_about_once(emit: Any) -> None:
    log = emit(_config())

    first = log(version="9.9.9", env="forged")
    assert _warnings(first) == ["env", "version"]
    # The warnings come first, so the record they explain is the one after them.
    assert first[-1]["message"] == "reserved.fields.ok"
    assert first[-1]["version"] == "1.2.3"
    assert _replacements() == 2

    again = log(version="8.8.8")
    assert _warnings(again) == []
    assert _replacements() == 3


def test_the_warning_names_the_field_and_never_the_callers_value(emit: Any) -> None:
    lines = emit(_config())(version="secret-build-7")
    warning = next(line for line in lines if line.get("message") == _WARNING)
    assert warning["field"] == "version"
    assert warning["level"] == "WARN"
    assert "secret-build-7" not in json.dumps(warning)


def test_a_caller_value_equal_to_the_stamped_one_is_not_a_replacement(emit: Any) -> None:
    lines = emit(_config())(version="1.2.3", service="svc")
    assert _warnings(lines) == []
    assert _replacements() == 0


def test_an_empty_config_value_replaces_nothing(emit: Any) -> None:
    lines = emit(_config(version=""))(version="9.9.9")
    assert lines[-1]["version"] == "9.9.9"
    assert _replacements() == 0


def test_a_human_renderer_stamps_no_identity_so_replaces_none(emit: Any) -> None:
    emit(_config(fmt="console"))(version="9.9.9", service="other")
    assert _replacements() == 0


def test_trace_ids_count_only_while_a_span_is_live(emit: Any) -> None:
    log = emit(_config())
    log(trace_id="deadbeefdeadbeefdeadbeefdeadbeef", span_id="deadbeefdeadbeef")
    assert _replacements() == 0

    set_trace_context(_LIVE_TRACE, _LIVE_SPAN)
    lines = log(trace_id="deadbeefdeadbeefdeadbeefdeadbeef", span_id="deadbeefdeadbeef")
    assert _warnings(lines) == ["trace_id", "span_id"]
    assert _replacements() == 2

    log(trace_id=_LIVE_TRACE)
    assert _replacements() == 2


def test_a_bound_context_value_counts_like_a_per_call_one(emit: Any) -> None:
    log = emit(_config())
    bind_context(env="forged")
    assert _warnings(log()) == ["env"]
    assert _replacements() == 1


def test_a_record_refused_at_admission_is_neither_counted_nor_carried_over(emit: Any) -> None:
    log = emit(_config())
    set_trace_context(_LIVE_TRACE, _LIVE_SPAN)
    set_sampling_policy("logs", SamplingPolicy(default_rate=0.0))
    assert log(trace_id="deadbeefdeadbeefdeadbeefdeadbeef") == []
    assert _replacements() == 0

    # The refused record's trace-id replacement was noted before sampling
    # refused it. The next record notes its own, so it is not charged for it.
    set_sampling_policy("logs", SamplingPolicy(default_rate=1.0))
    assert _warnings(log()) == []
    assert _replacements() == 0


def test_the_warned_set_is_per_process_and_reset_between_tests(emit: Any) -> None:
    log = emit(_config())
    assert _warnings(log(version="9.9.9")) == ["version"]
    _reserved_fields._reset_reserved_fields_for_tests()
    assert _warnings(log(version="9.9.9")) == ["version"]
