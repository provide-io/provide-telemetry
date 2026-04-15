# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Runtime reconfiguration regressions for live schema + OTEL log providers."""

from __future__ import annotations

import pytest

from provide.telemetry import backpressure as backpressure_mod
from provide.telemetry import health as health_mod
from provide.telemetry import resilience as resilience_mod
from provide.telemetry import runtime as runtime_mod
from provide.telemetry import sampling as sampling_mod
from provide.telemetry.config import LoggingConfig, RuntimeOverrides, SchemaConfig, TelemetryConfig


@pytest.fixture(autouse=True)
def _reset() -> None:
    health_mod.reset_health_for_tests()
    sampling_mod.reset_sampling_for_tests()
    backpressure_mod.reset_queues_for_tests()
    resilience_mod.reset_resilience_for_tests()
    runtime_mod.reset_runtime_for_tests()


def test_update_runtime_config_makes_required_keys_live_for_existing_schema_processor() -> None:
    from provide.telemetry.logger.processors import enforce_event_schema

    cfg = TelemetryConfig(event_schema=SchemaConfig(required_keys=()))
    runtime_mod.apply_runtime_config(cfg)
    processor = enforce_event_schema(cfg)

    runtime_mod.update_runtime_config(RuntimeOverrides(event_schema=SchemaConfig(required_keys=("request_id",))))

    result = processor(None, "info", {"event": "auth.login.success"})
    assert "_schema_error" in result
    assert "request_id" in result["_schema_error"]


def test_update_runtime_config_makes_strict_event_name_live_for_existing_schema_processor() -> None:
    from provide.telemetry.logger.processors import enforce_event_schema

    cfg = TelemetryConfig(event_schema=SchemaConfig(strict_event_name=False))
    runtime_mod.apply_runtime_config(cfg)
    processor = enforce_event_schema(cfg)

    runtime_mod.update_runtime_config(RuntimeOverrides(event_schema=SchemaConfig(strict_event_name=True)))

    result = processor(None, "info", {"event": "bad event"})
    assert "_schema_error" in result
    assert "invalid event name" in result["_schema_error"]


def test_update_runtime_config_rejects_provider_changing_logging_with_installed_otel_logger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from provide.telemetry.logger import core as logger_core

    runtime_mod.apply_runtime_config(TelemetryConfig.from_env({"OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://logs"}))
    monkeypatch.setattr(logger_core, "_has_otel_log_provider", lambda: True)

    with pytest.raises(RuntimeError, match="provider-changing logging reconfiguration is unsupported"):
        runtime_mod.update_runtime_config(
            RuntimeOverrides(
                logging=LoggingConfig(
                    level="INFO",
                    fmt="console",
                    include_timestamp=True,
                    include_caller=True,
                    sanitize=True,
                    otlp_endpoint="http://other-logs",
                )
            )
        )


def test_reconfigure_telemetry_rejects_provider_changing_logging_with_installed_otel_logger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from provide.telemetry.logger import core as logger_core
    from provide.telemetry.metrics import provider as metrics_provider
    from provide.telemetry.tracing import provider as tracing_provider

    runtime_mod.apply_runtime_config(TelemetryConfig.from_env({"OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://logs"}))
    monkeypatch.setattr(logger_core, "_has_otel_log_provider", lambda: True)
    monkeypatch.setattr(tracing_provider, "_has_tracing_provider", lambda: False)
    monkeypatch.setattr(metrics_provider, "_has_meter_provider", lambda: False)

    with pytest.raises(RuntimeError, match="provider-changing logging reconfiguration is unsupported"):
        runtime_mod.reconfigure_telemetry(TelemetryConfig.from_env({"OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://other-logs"}))
