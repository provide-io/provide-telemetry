# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Setup warns about ignored OTEL_METRICS_EXPORTER entries and reports them as setup_error.

See prometheus_metrics.metrics_exporter_warnings in spec/telemetry-api.yaml.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest

from provide.telemetry import _otlp_tls, get_health_snapshot, setup_telemetry, shutdown_telemetry
from provide.telemetry.config import TelemetryConfig
from provide.telemetry.exceptions import ConfigurationError
from provide.telemetry.setup import _reset_all_for_tests

_EVENT = "config.metrics_exporter.value_ignored"
_UNKNOWN = "OTEL_METRICS_EXPORTER: unknown exporter statsd, ignored"
_CONSOLE = "OTEL_METRICS_EXPORTER: console is not supported by provide-telemetry, ignored"
_FALLBACK = "OTEL_METRICS_EXPORTER: no supported exporter left, using otlp"


@pytest.fixture(autouse=True)
def _clean() -> Iterator[None]:
    _reset_all_for_tests()
    yield
    shutdown_telemetry()
    _reset_all_for_tests()


class _Records(logging.Handler):
    """Attached to the setup logger itself: configure_logging replaces the root handlers caplog uses."""

    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def records() -> Iterator[list[logging.LogRecord]]:
    handler = _Records()
    logger = logging.getLogger("provide.telemetry.setup")
    logger.addHandler(handler)
    try:
        yield handler.records
    finally:
        logger.removeHandler(handler)


def _ignored(records: list[logging.LogRecord]) -> list[str]:
    return [r.__dict__["reason"] for r in records if r.getMessage() == _EVENT]


def _config(exporter: str) -> TelemetryConfig:
    return TelemetryConfig.from_env({"OTEL_METRICS_EXPORTER": exporter, "PROVIDE_TRACE_ENABLED": "false"})


def test_setup_succeeds_logs_each_once_and_records_setup_error(records: list[logging.LogRecord]) -> None:
    cfg = _config("console")
    assert setup_telemetry(cfg).metrics.exporters == ("otlp",)
    assert _ignored(records) == [_CONSOLE, _FALLBACK]
    assert all(r.levelno == logging.WARNING for r in records if r.getMessage() == _EVENT)
    assert get_health_snapshot().setup_error == f"{_CONSOLE}; {_FALLBACK}"
    # A repeated setup is a no-op: nothing is logged twice.
    setup_telemetry(cfg)
    assert len(_ignored(records)) == 2


def test_ignored_entries_come_before_tls_problems(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("provide.telemetry.setup.take_tls_problems", lambda: "OTEL_EXPORTER_OTLP_CERTIFICATE=/x: gone")
    setup_telemetry(_config("otlp,statsd"))
    assert get_health_snapshot().setup_error == f"{_UNKNOWN}; OTEL_EXPORTER_OTLP_CERTIFICATE=/x: gone"


def test_a_clean_value_records_nothing(records: list[logging.LogRecord]) -> None:
    _otlp_tls._problems.clear()
    setup_telemetry(_config("prometheus"))
    assert _ignored(records) == []
    assert get_health_snapshot().setup_error is None


def test_strict_config_fails_parsing_before_setup() -> None:
    with pytest.raises(ConfigurationError, match=r"^PROVIDE_TELEMETRY_STRICT_CONFIG: "):
        TelemetryConfig.from_env({"OTEL_METRICS_EXPORTER": "otlp,statsd", "PROVIDE_TELEMETRY_STRICT_CONFIG": "true"})
