# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Configuration models for undef telemetry."""

from __future__ import annotations

import os
from collections.abc import Mapping
from urllib.parse import unquote

from pydantic import BaseModel, Field, field_validator


class LoggingConfig(BaseModel):
    level: str = "INFO"
    fmt: str = "console"  # console | json
    include_timestamp: bool = True
    include_caller: bool = True
    sanitize: bool = True
    otlp_endpoint: str | None = None
    otlp_headers: dict[str, str] = Field(default_factory=dict)
    log_code_attributes: bool = False

    @field_validator("level")
    @classmethod
    def validate_level(cls, value: str) -> str:
        allowed = {"TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        normalized = value.upper()
        if normalized not in allowed:
            raise ValueError(f"invalid log level: {value}")
        return normalized

    @field_validator("fmt")
    @classmethod
    def validate_fmt(cls, value: str) -> str:
        if value not in {"console", "json"}:
            raise ValueError(f"invalid log format: {value}")
        return value


class TracingConfig(BaseModel):
    enabled: bool = True
    sample_rate: float = 1.0
    otlp_endpoint: str | None = None
    otlp_headers: dict[str, str] = Field(default_factory=dict)

    @field_validator("sample_rate")
    @classmethod
    def validate_rate(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("sample_rate must be between 0 and 1")
        return value


class MetricsConfig(BaseModel):
    enabled: bool = True
    otlp_endpoint: str | None = None
    otlp_headers: dict[str, str] = Field(default_factory=dict)


class SchemaConfig(BaseModel):
    strict_event_name: bool = True
    required_keys: tuple[str, ...] = ()


class SamplingConfig(BaseModel):
    logs_rate: float = 1.0
    traces_rate: float = 1.0
    metrics_rate: float = 1.0

    @field_validator("logs_rate", "traces_rate", "metrics_rate")
    @classmethod
    def validate_rate(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("sampling rate must be between 0 and 1")
        return value


class BackpressureConfig(BaseModel):
    logs_maxsize: int = 0
    traces_maxsize: int = 0
    metrics_maxsize: int = 0

    @field_validator("logs_maxsize", "traces_maxsize", "metrics_maxsize")
    @classmethod
    def validate_maxsize(cls, value: int) -> int:
        if value < 0:
            raise ValueError("queue maxsize must be >= 0")
        return value


class ExporterPolicyConfig(BaseModel):
    logs_retries: int = 0
    traces_retries: int = 0
    metrics_retries: int = 0
    logs_backoff_seconds: float = 0.0
    traces_backoff_seconds: float = 0.0
    metrics_backoff_seconds: float = 0.0
    logs_timeout_seconds: float = 10.0
    traces_timeout_seconds: float = 10.0
    metrics_timeout_seconds: float = 10.0
    logs_fail_open: bool = True
    traces_fail_open: bool = True
    metrics_fail_open: bool = True


class SLOConfig(BaseModel):
    enable_red_metrics: bool = False
    enable_use_metrics: bool = False
    include_error_taxonomy: bool = True


class TelemetryConfig(BaseModel):
    service_name: str = "undef-service"
    environment: str = "dev"
    version: str = "0.0.0"
    strict_schema: bool = False
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    tracing: TracingConfig = Field(default_factory=TracingConfig)
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)
    event_schema: SchemaConfig = Field(default_factory=SchemaConfig)
    sampling: SamplingConfig = Field(default_factory=SamplingConfig)
    backpressure: BackpressureConfig = Field(default_factory=BackpressureConfig)
    exporter: ExporterPolicyConfig = Field(default_factory=ExporterPolicyConfig)
    slo: SLOConfig = Field(default_factory=SLOConfig)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> TelemetryConfig:
        data = env if env is not None else os.environ
        return cls(
            service_name=data.get("UNDEF_TELEMETRY_SERVICE_NAME", "undef-service"),
            environment=data.get("UNDEF_TELEMETRY_ENV", "dev"),
            version=data.get("UNDEF_TELEMETRY_VERSION", "0.0.0"),
            strict_schema=_parse_bool(data.get("UNDEF_TELEMETRY_STRICT_SCHEMA"), False),
            logging=LoggingConfig(
                level=data.get("UNDEF_LOG_LEVEL", "INFO"),
                fmt=data.get("UNDEF_LOG_FORMAT", "console"),
                include_timestamp=_parse_bool(data.get("UNDEF_LOG_INCLUDE_TIMESTAMP"), True),
                include_caller=_parse_bool(data.get("UNDEF_LOG_INCLUDE_CALLER"), True),
                sanitize=_parse_bool(data.get("UNDEF_LOG_SANITIZE"), True),
                log_code_attributes=_parse_bool(data.get("UNDEF_LOG_CODE_ATTRIBUTES"), False),
                otlp_endpoint=data.get("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT") or data.get("OTEL_EXPORTER_OTLP_ENDPOINT"),
                otlp_headers=_parse_otlp_headers(
                    data.get("OTEL_EXPORTER_OTLP_LOGS_HEADERS") or data.get("OTEL_EXPORTER_OTLP_HEADERS")
                ),
            ),
            tracing=TracingConfig(
                enabled=_parse_bool(data.get("UNDEF_TRACE_ENABLED"), True),
                sample_rate=float(data.get("UNDEF_TRACE_SAMPLE_RATE", "1.0")),
                otlp_endpoint=data.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") or data.get("OTEL_EXPORTER_OTLP_ENDPOINT"),
                otlp_headers=_parse_otlp_headers(
                    data.get("OTEL_EXPORTER_OTLP_TRACES_HEADERS") or data.get("OTEL_EXPORTER_OTLP_HEADERS")
                ),
            ),
            metrics=MetricsConfig(
                enabled=_parse_bool(data.get("UNDEF_METRICS_ENABLED"), True),
                otlp_endpoint=data.get("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT")
                or data.get("OTEL_EXPORTER_OTLP_ENDPOINT"),
                otlp_headers=_parse_otlp_headers(
                    data.get("OTEL_EXPORTER_OTLP_METRICS_HEADERS") or data.get("OTEL_EXPORTER_OTLP_HEADERS")
                ),
            ),
            event_schema=SchemaConfig(
                strict_event_name=_parse_bool(data.get("UNDEF_TELEMETRY_STRICT_EVENT_NAME"), True),
                required_keys=tuple(
                    k.strip() for k in data.get("UNDEF_TELEMETRY_REQUIRED_KEYS", "").split(",") if k.strip()
                ),
            ),
            sampling=SamplingConfig(
                logs_rate=float(data.get("UNDEF_SAMPLING_LOGS_RATE", "1.0")),
                traces_rate=float(data.get("UNDEF_SAMPLING_TRACES_RATE", "1.0")),
                metrics_rate=float(data.get("UNDEF_SAMPLING_METRICS_RATE", "1.0")),
            ),
            backpressure=BackpressureConfig(
                logs_maxsize=int(data.get("UNDEF_BACKPRESSURE_LOGS_MAXSIZE", "0")),
                traces_maxsize=int(data.get("UNDEF_BACKPRESSURE_TRACES_MAXSIZE", "0")),
                metrics_maxsize=int(data.get("UNDEF_BACKPRESSURE_METRICS_MAXSIZE", "0")),
            ),
            exporter=ExporterPolicyConfig(
                logs_retries=int(data.get("UNDEF_EXPORTER_LOGS_RETRIES", "0")),
                traces_retries=int(data.get("UNDEF_EXPORTER_TRACES_RETRIES", "0")),
                metrics_retries=int(data.get("UNDEF_EXPORTER_METRICS_RETRIES", "0")),
                logs_backoff_seconds=float(data.get("UNDEF_EXPORTER_LOGS_BACKOFF_SECONDS", "0.0")),
                traces_backoff_seconds=float(data.get("UNDEF_EXPORTER_TRACES_BACKOFF_SECONDS", "0.0")),
                metrics_backoff_seconds=float(data.get("UNDEF_EXPORTER_METRICS_BACKOFF_SECONDS", "0.0")),
                logs_timeout_seconds=float(data.get("UNDEF_EXPORTER_LOGS_TIMEOUT_SECONDS", "10.0")),
                traces_timeout_seconds=float(data.get("UNDEF_EXPORTER_TRACES_TIMEOUT_SECONDS", "10.0")),
                metrics_timeout_seconds=float(data.get("UNDEF_EXPORTER_METRICS_TIMEOUT_SECONDS", "10.0")),
                logs_fail_open=_parse_bool(data.get("UNDEF_EXPORTER_LOGS_FAIL_OPEN"), True),
                traces_fail_open=_parse_bool(data.get("UNDEF_EXPORTER_TRACES_FAIL_OPEN"), True),
                metrics_fail_open=_parse_bool(data.get("UNDEF_EXPORTER_METRICS_FAIL_OPEN"), True),
            ),
            slo=SLOConfig(
                enable_red_metrics=_parse_bool(data.get("UNDEF_SLO_ENABLE_RED_METRICS"), False),
                enable_use_metrics=_parse_bool(data.get("UNDEF_SLO_ENABLE_USE_METRICS"), False),
                include_error_taxonomy=_parse_bool(data.get("UNDEF_SLO_INCLUDE_ERROR_TAXONOMY"), True),
            ),
        )


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_otlp_headers(value: str | None) -> dict[str, str]:
    if not value:
        return {}
    headers: dict[str, str] = {}
    for pair in value.split(","):
        if "=" not in pair:
            continue
        key, raw = pair.split("=", 1)
        key = key.strip()
        if not key:
            continue
        headers[key] = unquote(raw.strip())
    return headers
