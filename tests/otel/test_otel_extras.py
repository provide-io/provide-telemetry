# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

from __future__ import annotations

import pytest

from provide.telemetry.config import TelemetryConfig
from provide.telemetry.logger import core as logger_core
from provide.telemetry.logger.core import _reset_logging_for_tests
from provide.telemetry.metrics import provider as metrics_provider
from provide.telemetry.setup import shutdown_telemetry
from provide.telemetry.tracing import provider as tracing_provider
from provide.telemetry.tracing.provider import _reset_tracing_for_tests

pytestmark = pytest.mark.otel


def test_otel_import_available_for_marked_suite() -> None:
    pytest.importorskip("opentelemetry")


def test_setup_tracing_with_real_otel_imports() -> None:
    pytest.importorskip("opentelemetry")
    _reset_tracing_for_tests()
    cfg = TelemetryConfig.from_env({"PROVIDE_TRACE_ENABLED": "true"})
    tracing_provider.setup_tracing(cfg)
    # setup may no-op safely depending on runtime, but must not raise
    assert isinstance(tracing_provider._provider_configured, bool)
    shutdown_telemetry()


def test_setup_metrics_with_real_otel_imports() -> None:
    pytest.importorskip("opentelemetry")
    metrics_provider._set_meter_for_test(None)
    cfg = TelemetryConfig.from_env({"PROVIDE_METRICS_ENABLED": "true"})
    metrics_provider.setup_metrics(cfg)
    assert metrics_provider._HAS_OTEL_METRICS is True
    shutdown_telemetry()


def test_setup_logging_with_real_otel_imports() -> None:
    pytest.importorskip("opentelemetry")
    _reset_logging_for_tests()
    cfg = TelemetryConfig.from_env(
        {
            "PROVIDE_LOG_LEVEL": "INFO",
            "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://127.0.0.1:4318/v1/logs",
        }
    )
    logger_core.configure_logging(cfg)
    assert logger_core._configured is True
    shutdown_telemetry()
