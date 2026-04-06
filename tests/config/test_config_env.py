# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

from __future__ import annotations

import pytest

from provide.telemetry.config import (
    BackpressureConfig,
    LoggingConfig,
    SamplingConfig,
    TelemetryConfig,
    TracingConfig,
    _parse_bool,
    _parse_env_bool,
    _parse_otlp_headers,
)


def test_parse_bool() -> None:
    assert _parse_bool(None, True) is True
    assert _parse_bool(None, False) is False
    assert _parse_bool("true", False) is True
    assert _parse_bool("YES", False) is True
    assert _parse_bool("0", True) is False


class TestParseEnvBoolTrueVariants:
    """Kill mutants on truthy string literals in _parse_env_bool."""

    def test_1_is_true(self) -> None:
        assert _parse_env_bool("1", False, "f") is True

    def test_true_is_true(self) -> None:
        assert _parse_env_bool("true", False, "f") is True

    def test_yes_is_true(self) -> None:
        assert _parse_env_bool("yes", False, "f") is True

    def test_on_is_true(self) -> None:
        assert _parse_env_bool("on", False, "f") is True

    def test_uppercase_yes_lowered_is_true(self) -> None:
        assert _parse_env_bool("YES", False, "f") is True

    def test_uppercase_on_lowered_is_true(self) -> None:
        assert _parse_env_bool("ON", False, "f") is True


class TestParseEnvBoolFalseVariants:
    """Kill mutants on falsy string literals in _parse_env_bool."""

    def test_0_is_false(self) -> None:
        assert _parse_env_bool("0", True, "f") is False

    def test_false_is_false(self) -> None:
        assert _parse_env_bool("false", True, "f") is False

    def test_no_is_false(self) -> None:
        assert _parse_env_bool("no", True, "f") is False

    def test_off_is_false(self) -> None:
        assert _parse_env_bool("off", True, "f") is False

    def test_uppercase_no_lowered_is_false(self) -> None:
        assert _parse_env_bool("NO", True, "f") is False

    def test_uppercase_off_lowered_is_false(self) -> None:
        assert _parse_env_bool("OFF", True, "f") is False


def test_parse_env_bool_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="invalid boolean for PROVIDE_TRACE_ENABLED"):
        _parse_env_bool("invalid-boolean", True, "PROVIDE_TRACE_ENABLED")


def test_telemetry_from_env_rejects_invalid_boolean_value() -> None:
    with pytest.raises(ValueError, match="invalid boolean for PROVIDE_TRACE_ENABLED"):
        TelemetryConfig.from_env({"PROVIDE_TRACE_ENABLED": "invalid-boolean"})


def test_parse_otlp_headers() -> None:
    assert _parse_otlp_headers(None) == {}
    assert _parse_otlp_headers("") == {}
    assert _parse_otlp_headers("Authorization=Basic%20abc%3D%3D, X-Org=default") == {
        "Authorization": "Basic abc==",
        "X-Org": "default",
    }
    assert _parse_otlp_headers("badpair,no_key=1, =2") == {"no_key": "1"}
    # Preserve inner '=' in values and split only at first '='.
    assert _parse_otlp_headers("Authorization=Basic%20abc%3D%3D") == {"Authorization": "Basic abc=="}
    assert _parse_otlp_headers("x=a=b") == {"x": "a=b"}
    # Skip empty-key pairs and continue parsing later pairs.
    assert _parse_otlp_headers("=drop,X-Org=default") == {"X-Org": "default"}


def test_logging_config_validation() -> None:
    assert LoggingConfig(level="trace").level == "TRACE"
    for level in ("TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        assert LoggingConfig(level=level).level == level
    assert LoggingConfig(fmt="console").fmt == "console"
    assert LoggingConfig(fmt="json").fmt == "json"
    with pytest.raises(ValueError, match="invalid log level: bad"):
        LoggingConfig(level="bad")
    with pytest.raises(ValueError, match="invalid log format: xml"):
        LoggingConfig(fmt="xml")
    with pytest.raises(ValueError, match="invalid log format: JSON"):
        LoggingConfig(fmt="JSON")


def test_tracing_config_validation() -> None:
    assert TracingConfig(sample_rate=0.0).sample_rate == 0.0
    assert TracingConfig(sample_rate=1.0).sample_rate == 1.0
    with pytest.raises(ValueError, match="sample_rate must be between 0 and 1"):
        TracingConfig(sample_rate=1.1)
    with pytest.raises(ValueError, match="sample_rate must be between 0 and 1"):
        TracingConfig(sample_rate=-0.1)


def test_sampling_config_validation_boundaries() -> None:
    cfg = SamplingConfig(logs_rate=0.0, traces_rate=1.0, metrics_rate=0.5)
    assert cfg.logs_rate == 0.0
    assert cfg.traces_rate == 1.0
    assert cfg.metrics_rate == 0.5
    with pytest.raises(ValueError, match="sampling rate must be between 0 and 1"):
        SamplingConfig(logs_rate=-0.01)
    with pytest.raises(ValueError, match="sampling rate must be between 0 and 1"):
        SamplingConfig(metrics_rate=1.01)


def test_backpressure_config_validation_boundaries() -> None:
    cfg = BackpressureConfig(logs_maxsize=0, traces_maxsize=1, metrics_maxsize=2)
    assert cfg.logs_maxsize == 0
    assert cfg.traces_maxsize == 1
    assert cfg.metrics_maxsize == 2
    with pytest.raises(ValueError, match="queue maxsize must be >= 0"):
        BackpressureConfig(logs_maxsize=-1)


def test_new_config_validation_guards() -> None:
    with pytest.raises(ValueError, match="sampling rate must be between 0 and 1"):
        TelemetryConfig.from_env({"PROVIDE_SAMPLING_LOGS_RATE": "1.1"})
    with pytest.raises(ValueError, match="queue maxsize must be >= 0"):
        TelemetryConfig.from_env({"PROVIDE_BACKPRESSURE_LOGS_MAXSIZE": "-1"})


def test_telemetry_from_env_defaults() -> None:
    cfg = TelemetryConfig.from_env({})
    assert cfg.service_name == "provide-service"
    assert cfg.environment == "dev"
    assert cfg.strict_schema is False
    assert cfg.event_schema.required_keys == ()


def test_telemetry_from_env_values() -> None:
    cfg = TelemetryConfig.from_env(
        {
            "PROVIDE_TELEMETRY_SERVICE_NAME": "svc",
            "PROVIDE_TELEMETRY_ENV": "prod",
            "PROVIDE_TELEMETRY_VERSION": "1.2.3",
            "PROVIDE_TELEMETRY_STRICT_SCHEMA": "true",
            "PROVIDE_LOG_LEVEL": "TRACE",
            "PROVIDE_LOG_FORMAT": "json",
            "PROVIDE_LOG_INCLUDE_TIMESTAMP": "false",
            "PROVIDE_LOG_INCLUDE_CALLER": "false",
            "PROVIDE_LOG_SANITIZE": "false",
            "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://logs",
            "OTEL_EXPORTER_OTLP_LOGS_HEADERS": "Authorization=Basic%20logs",
            "PROVIDE_TRACE_ENABLED": "false",
            "PROVIDE_TRACE_SAMPLE_RATE": "0.5",
            "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": "http://trace",
            "OTEL_EXPORTER_OTLP_TRACES_HEADERS": "Authorization=Basic%20trace",
            "PROVIDE_METRICS_ENABLED": "false",
            "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT": "http://metrics",
            "OTEL_EXPORTER_OTLP_METRICS_HEADERS": "Authorization=Basic%20metrics",
            "PROVIDE_TELEMETRY_STRICT_EVENT_NAME": "false",
            "PROVIDE_TELEMETRY_REQUIRED_KEYS": "request_id, session_id",
            "PROVIDE_SAMPLING_LOGS_RATE": "0.9",
            "PROVIDE_SAMPLING_TRACES_RATE": "0.8",
            "PROVIDE_SAMPLING_METRICS_RATE": "0.7",
            "PROVIDE_BACKPRESSURE_LOGS_MAXSIZE": "10",
            "PROVIDE_BACKPRESSURE_TRACES_MAXSIZE": "11",
            "PROVIDE_BACKPRESSURE_METRICS_MAXSIZE": "12",
            "PROVIDE_EXPORTER_LOGS_RETRIES": "1",
            "PROVIDE_EXPORTER_TRACES_RETRIES": "2",
            "PROVIDE_EXPORTER_METRICS_RETRIES": "3",
            "PROVIDE_EXPORTER_LOGS_BACKOFF_SECONDS": "0.1",
            "PROVIDE_EXPORTER_TRACES_BACKOFF_SECONDS": "0.2",
            "PROVIDE_EXPORTER_METRICS_BACKOFF_SECONDS": "0.3",
            "PROVIDE_EXPORTER_LOGS_TIMEOUT_SECONDS": "5.0",
            "PROVIDE_EXPORTER_TRACES_TIMEOUT_SECONDS": "6.0",
            "PROVIDE_EXPORTER_METRICS_TIMEOUT_SECONDS": "7.0",
            "PROVIDE_EXPORTER_LOGS_FAIL_OPEN": "false",
            "PROVIDE_EXPORTER_TRACES_FAIL_OPEN": "false",
            "PROVIDE_EXPORTER_METRICS_FAIL_OPEN": "false",
            "PROVIDE_EXPORTER_LOGS_ALLOW_BLOCKING_EVENT_LOOP": "true",
            "PROVIDE_EXPORTER_TRACES_ALLOW_BLOCKING_EVENT_LOOP": "true",
            "PROVIDE_EXPORTER_METRICS_ALLOW_BLOCKING_EVENT_LOOP": "true",
            "PROVIDE_SLO_ENABLE_RED_METRICS": "true",
            "PROVIDE_SLO_ENABLE_USE_METRICS": "true",
            "PROVIDE_SLO_INCLUDE_ERROR_TAXONOMY": "false",
        }
    )
    assert cfg.service_name == "svc"
    assert cfg.environment == "prod"
    assert cfg.version == "1.2.3"
    assert cfg.strict_schema is True
    assert cfg.logging.level == "TRACE"
    assert cfg.logging.fmt == "json"
    assert cfg.logging.include_timestamp is False
    assert cfg.logging.include_caller is False
    assert cfg.logging.sanitize is False
    assert cfg.logging.otlp_endpoint == "http://logs"
    assert cfg.logging.otlp_headers == {"Authorization": "Basic logs"}
    assert cfg.logging.log_code_attributes is False
    assert cfg.tracing.enabled is False
    assert cfg.tracing.sample_rate == 0.5
    assert cfg.tracing.otlp_endpoint == "http://trace"
    assert cfg.tracing.otlp_headers == {"Authorization": "Basic trace"}
    assert cfg.metrics.enabled is False
    assert cfg.metrics.otlp_endpoint == "http://metrics"
    assert cfg.metrics.otlp_headers == {"Authorization": "Basic metrics"}
    assert cfg.event_schema.strict_event_name is False
    assert cfg.event_schema.required_keys == ("request_id", "session_id")
    assert cfg.sampling.logs_rate == 0.9
    assert cfg.sampling.traces_rate == 0.8
    assert cfg.sampling.metrics_rate == 0.7
    assert cfg.backpressure.logs_maxsize == 10
    assert cfg.backpressure.traces_maxsize == 11
    assert cfg.backpressure.metrics_maxsize == 12
    assert cfg.exporter.logs_retries == 1
    assert cfg.exporter.traces_retries == 2
    assert cfg.exporter.metrics_retries == 3
    assert cfg.exporter.logs_backoff_seconds == 0.1
    assert cfg.exporter.traces_backoff_seconds == 0.2
    assert cfg.exporter.metrics_backoff_seconds == 0.3
    assert cfg.exporter.logs_timeout_seconds == 5.0
    assert cfg.exporter.traces_timeout_seconds == 6.0
    assert cfg.exporter.metrics_timeout_seconds == 7.0
    assert cfg.exporter.logs_fail_open is False
    assert cfg.exporter.traces_fail_open is False
    assert cfg.exporter.metrics_fail_open is False
    assert cfg.exporter.logs_allow_blocking_in_event_loop is True
    assert cfg.exporter.traces_allow_blocking_in_event_loop is True
    assert cfg.exporter.metrics_allow_blocking_in_event_loop is True
    assert cfg.slo.enable_red_metrics is True
    assert cfg.slo.enable_use_metrics is True
    assert cfg.slo.include_error_taxonomy is False


def test_telemetry_otlp_fallback_endpoint() -> None:
    cfg = TelemetryConfig.from_env(
        {
            "OTEL_EXPORTER_OTLP_ENDPOINT": "http://all",
            "OTEL_EXPORTER_OTLP_HEADERS": "Authorization=Basic%20all",
        }
    )
    assert cfg.tracing.otlp_endpoint == "http://all"
    assert cfg.metrics.otlp_endpoint == "http://all"
    assert cfg.logging.otlp_endpoint == "http://all"
    assert cfg.logging.otlp_headers == {"Authorization": "Basic all"}
    assert cfg.tracing.otlp_headers == {"Authorization": "Basic all"}


def test_logging_code_attributes_flag() -> None:
    cfg = TelemetryConfig.from_env({"PROVIDE_LOG_CODE_ATTRIBUTES": "true"})
    assert cfg.logging.log_code_attributes is True
