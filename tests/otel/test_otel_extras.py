# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

from __future__ import annotations

import pytest

from undef.telemetry.config import TelemetryConfig
from undef.telemetry.logger import core as logger_core
from undef.telemetry.metrics import provider as metrics_provider
from undef.telemetry.setup import shutdown_telemetry
from undef.telemetry.tracing import provider as tracing_provider

pytestmark = pytest.mark.otel


def test_otel_import_available_for_marked_suite() -> None:
    pytest.importorskip("opentelemetry")


def test_setup_tracing_with_real_otel_imports() -> None:
    pytest.importorskip("opentelemetry")
    tracing_provider._provider_configured = False
    cfg = TelemetryConfig.from_env({"UNDEF_TRACE_ENABLED": "true"})
    tracing_provider.setup_tracing(cfg)
    # setup may no-op safely depending on runtime, but must not raise
    assert isinstance(tracing_provider._provider_configured, bool)
    shutdown_telemetry()


def test_setup_metrics_with_real_otel_imports() -> None:
    pytest.importorskip("opentelemetry")
    metrics_provider._set_meter_for_test(None)
    cfg = TelemetryConfig.from_env({"UNDEF_METRICS_ENABLED": "true"})
    metrics_provider.setup_metrics(cfg)
    assert metrics_provider._HAS_OTEL_METRICS is True
    shutdown_telemetry()


def test_setup_logging_with_real_otel_imports() -> None:
    pytest.importorskip("opentelemetry")
    logger_core._configured = False
    logger_core._active_config = None
    logger_core._otel_log_provider = None
    cfg = TelemetryConfig.from_env(
        {
            "UNDEF_LOG_LEVEL": "INFO",
            "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://127.0.0.1:4318/v1/logs",
        }
    )
    logger_core.configure_logging(cfg)
    assert logger_core._configured is True
    shutdown_telemetry()
