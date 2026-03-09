# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

from __future__ import annotations

import pytest

from undef.telemetry.config import LoggingConfig, TelemetryConfig, TracingConfig, _parse_bool, _parse_otlp_headers


def test_parse_bool() -> None:
    assert _parse_bool(None, True) is True
    assert _parse_bool(None, False) is False
    assert _parse_bool("true", False) is True
    assert _parse_bool("YES", False) is True
    assert _parse_bool("0", True) is False


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
    with pytest.raises(ValueError):
        LoggingConfig(level="bad")
    with pytest.raises(ValueError):
        LoggingConfig(fmt="xml")


def test_tracing_config_validation() -> None:
    with pytest.raises(ValueError):
        TracingConfig(sample_rate=1.1)


def test_telemetry_from_env_defaults() -> None:
    cfg = TelemetryConfig.from_env({})
    assert cfg.service_name == "undef-service"
    assert cfg.environment == "dev"
    assert cfg.strict_schema is False
    assert cfg.event_schema.required_keys == ()


def test_telemetry_from_env_values() -> None:
    cfg = TelemetryConfig.from_env(
        {
            "UNDEF_TELEMETRY_SERVICE_NAME": "svc",
            "UNDEF_TELEMETRY_ENV": "prod",
            "UNDEF_TELEMETRY_VERSION": "1.2.3",
            "UNDEF_TELEMETRY_STRICT_SCHEMA": "true",
            "UNDEF_LOG_LEVEL": "TRACE",
            "UNDEF_LOG_FORMAT": "json",
            "UNDEF_LOG_INCLUDE_TIMESTAMP": "false",
            "UNDEF_LOG_INCLUDE_CALLER": "false",
            "UNDEF_LOG_SANITIZE": "false",
            "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://logs",
            "OTEL_EXPORTER_OTLP_LOGS_HEADERS": "Authorization=Basic%20logs",
            "UNDEF_TRACE_ENABLED": "false",
            "UNDEF_TRACE_SAMPLE_RATE": "0.5",
            "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": "http://trace",
            "OTEL_EXPORTER_OTLP_TRACES_HEADERS": "Authorization=Basic%20trace",
            "UNDEF_METRICS_ENABLED": "false",
            "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT": "http://metrics",
            "OTEL_EXPORTER_OTLP_METRICS_HEADERS": "Authorization=Basic%20metrics",
            "UNDEF_TELEMETRY_STRICT_EVENT_NAME": "false",
            "UNDEF_TELEMETRY_REQUIRED_KEYS": "request_id, session_id",
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
    assert cfg.tracing.enabled is False
    assert cfg.tracing.sample_rate == 0.5
    assert cfg.tracing.otlp_endpoint == "http://trace"
    assert cfg.tracing.otlp_headers == {"Authorization": "Basic trace"}
    assert cfg.metrics.enabled is False
    assert cfg.metrics.otlp_endpoint == "http://metrics"
    assert cfg.metrics.otlp_headers == {"Authorization": "Basic metrics"}
    assert cfg.event_schema.strict_event_name is False
    assert cfg.event_schema.required_keys == ("request_id", "session_id")


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
    assert cfg.metrics.otlp_headers == {"Authorization": "Basic all"}
