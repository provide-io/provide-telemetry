# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Configuration models for provide.telemetry."""

from __future__ import annotations

__all__ = [
    "BackpressureConfig",
    "ExporterPolicyConfig",
    "LoggingConfig",
    "MetricsConfig",
    "SLOConfig",
    "SamplingConfig",
    "SchemaConfig",
    "SecurityConfig",
    "TelemetryConfig",
    "TracingConfig",
]

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import unquote

from provide.telemetry.exceptions import ConfigurationError

_logger = logging.getLogger(__name__)

_VALID_COLORS = frozenset({"dim", "bold", "red", "green", "yellow", "blue", "cyan", "white", "none"})


@dataclass(slots=True)
class LoggingConfig:
    level: str = "INFO"
    fmt: str = "console"  # console | json
    include_timestamp: bool = True
    include_caller: bool = True
    sanitize: bool = True
    otlp_endpoint: str | None = None
    otlp_headers: dict[str, str] = field(default_factory=dict)
    log_code_attributes: bool = False
    pretty_key_color: str = "dim"
    pretty_value_color: str = ""
    pretty_fields: tuple[str, ...] = ()
    module_levels: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.level = _normalize_level(self.level)
        _validate_fmt(self.fmt)
        _validate_color(self.pretty_key_color, "pretty_key_color")
        _validate_color(self.pretty_value_color, "pretty_value_color")


@dataclass(slots=True)
class TracingConfig:
    enabled: bool = True
    sample_rate: float = 1.0
    otlp_endpoint: str | None = None
    otlp_headers: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_rate(self.sample_rate, "sample_rate must be between 0 and 1")


@dataclass(slots=True)
class MetricsConfig:
    enabled: bool = True
    otlp_endpoint: str | None = None
    otlp_headers: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class SchemaConfig:
    strict_event_name: bool = False
    required_keys: tuple[str, ...] = ()


@dataclass(slots=True)
class SamplingConfig:
    logs_rate: float = 1.0
    traces_rate: float = 1.0
    metrics_rate: float = 1.0

    def __post_init__(self) -> None:
        _validate_rate(self.logs_rate, "sampling rate must be between 0 and 1")
        _validate_rate(self.traces_rate, "sampling rate must be between 0 and 1")
        _validate_rate(self.metrics_rate, "sampling rate must be between 0 and 1")


@dataclass(slots=True)
class BackpressureConfig:
    logs_maxsize: int = 0
    traces_maxsize: int = 0
    metrics_maxsize: int = 0

    def __post_init__(self) -> None:
        _validate_non_negative(self.logs_maxsize, "queue maxsize must be >= 0")
        _validate_non_negative(self.traces_maxsize, "queue maxsize must be >= 0")
        _validate_non_negative(self.metrics_maxsize, "queue maxsize must be >= 0")


@dataclass(slots=True)
class ExporterPolicyConfig:
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
    logs_allow_blocking_in_event_loop: bool = False
    traces_allow_blocking_in_event_loop: bool = False
    metrics_allow_blocking_in_event_loop: bool = False


@dataclass(slots=True)
class SLOConfig:
    enable_red_metrics: bool = False
    enable_use_metrics: bool = False
    include_error_taxonomy: bool = True


@dataclass(slots=True)
class SecurityConfig:
    max_attr_value_length: int = 1024
    max_attr_count: int = 64
    max_nesting_depth: int = 8

    def __post_init__(self) -> None:
        _validate_non_negative(self.max_attr_value_length, "max_attr_value_length must be >= 0")
        _validate_non_negative(self.max_attr_count, "max_attr_count must be >= 0")
        _validate_non_negative(self.max_nesting_depth, "max_nesting_depth must be >= 0")


@dataclass(slots=True)
class TelemetryConfig:
    service_name: str = "provide-service"
    environment: str = "dev"
    version: str = "0.0.0"
    strict_schema: bool = False
    pii_max_depth: int = 8
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    tracing: TracingConfig = field(default_factory=TracingConfig)
    metrics: MetricsConfig = field(default_factory=MetricsConfig)
    event_schema: SchemaConfig = field(default_factory=SchemaConfig)
    sampling: SamplingConfig = field(default_factory=SamplingConfig)
    backpressure: BackpressureConfig = field(default_factory=BackpressureConfig)
    exporter: ExporterPolicyConfig = field(default_factory=ExporterPolicyConfig)
    slo: SLOConfig = field(default_factory=SLOConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)

    def __post_init__(self) -> None:
        _validate_non_negative(self.pii_max_depth, "pii_max_depth must be >= 0")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> TelemetryConfig:
        data = env if env is not None else os.environ
        return cls(
            service_name=data.get("PROVIDE_TELEMETRY_SERVICE_NAME", "provide-service"),
            environment=data.get("PROVIDE_TELEMETRY_ENV", "dev"),
            version=data.get("PROVIDE_TELEMETRY_VERSION", "0.0.0"),
            strict_schema=_parse_env_bool(
                data.get("PROVIDE_TELEMETRY_STRICT_SCHEMA"), False, "PROVIDE_TELEMETRY_STRICT_SCHEMA"
            ),
            pii_max_depth=_parse_env_int(data.get("PROVIDE_LOG_PII_MAX_DEPTH", "8"), "PROVIDE_LOG_PII_MAX_DEPTH"),
            logging=LoggingConfig(
                level=data.get("PROVIDE_LOG_LEVEL", "INFO"),
                fmt=data.get("PROVIDE_LOG_FORMAT", "console"),
                include_timestamp=_parse_env_bool(
                    data.get("PROVIDE_LOG_INCLUDE_TIMESTAMP"), True, "PROVIDE_LOG_INCLUDE_TIMESTAMP"
                ),
                include_caller=_parse_env_bool(
                    data.get("PROVIDE_LOG_INCLUDE_CALLER"), True, "PROVIDE_LOG_INCLUDE_CALLER"
                ),
                sanitize=_parse_env_bool(data.get("PROVIDE_LOG_SANITIZE"), True, "PROVIDE_LOG_SANITIZE"),
                log_code_attributes=_parse_env_bool(
                    data.get("PROVIDE_LOG_CODE_ATTRIBUTES"), False, "PROVIDE_LOG_CODE_ATTRIBUTES"
                ),
                otlp_endpoint=data.get("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT") or data.get("OTEL_EXPORTER_OTLP_ENDPOINT"),
                otlp_headers=_parse_otlp_headers(
                    data.get("OTEL_EXPORTER_OTLP_LOGS_HEADERS") or data.get("OTEL_EXPORTER_OTLP_HEADERS")
                ),
                pretty_key_color=data.get("PROVIDE_LOG_PRETTY_KEY_COLOR", "dim"),
                pretty_value_color=data.get("PROVIDE_LOG_PRETTY_VALUE_COLOR", ""),
                pretty_fields=tuple(
                    f.strip() for f in data.get("PROVIDE_LOG_PRETTY_FIELDS", "").split(",") if f.strip()
                ),
                module_levels=_parse_module_levels(data.get("PROVIDE_LOG_MODULE_LEVELS", "")),
            ),
            tracing=TracingConfig(
                enabled=_parse_env_bool(data.get("PROVIDE_TRACE_ENABLED"), True, "PROVIDE_TRACE_ENABLED"),
                sample_rate=_parse_env_float(data.get("PROVIDE_TRACE_SAMPLE_RATE", "1.0"), "PROVIDE_TRACE_SAMPLE_RATE"),
                otlp_endpoint=data.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") or data.get("OTEL_EXPORTER_OTLP_ENDPOINT"),
                otlp_headers=_parse_otlp_headers(
                    data.get("OTEL_EXPORTER_OTLP_TRACES_HEADERS") or data.get("OTEL_EXPORTER_OTLP_HEADERS")
                ),
            ),
            metrics=MetricsConfig(
                enabled=_parse_env_bool(data.get("PROVIDE_METRICS_ENABLED"), True, "PROVIDE_METRICS_ENABLED"),
                otlp_endpoint=data.get("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT")
                or data.get("OTEL_EXPORTER_OTLP_ENDPOINT"),
                otlp_headers=_parse_otlp_headers(
                    data.get("OTEL_EXPORTER_OTLP_METRICS_HEADERS") or data.get("OTEL_EXPORTER_OTLP_HEADERS")
                ),
            ),
            event_schema=SchemaConfig(
                strict_event_name=_parse_env_bool(
                    data.get("PROVIDE_TELEMETRY_STRICT_EVENT_NAME"), False, "PROVIDE_TELEMETRY_STRICT_EVENT_NAME"
                ),
                required_keys=tuple(
                    k.strip() for k in data.get("PROVIDE_TELEMETRY_REQUIRED_KEYS", "").split(",") if k.strip()
                ),
            ),
            sampling=SamplingConfig(
                logs_rate=_parse_env_float(data.get("PROVIDE_SAMPLING_LOGS_RATE", "1.0"), "PROVIDE_SAMPLING_LOGS_RATE"),
                traces_rate=_parse_env_float(
                    data.get("PROVIDE_SAMPLING_TRACES_RATE", "1.0"), "PROVIDE_SAMPLING_TRACES_RATE"
                ),
                metrics_rate=_parse_env_float(
                    data.get("PROVIDE_SAMPLING_METRICS_RATE", "1.0"), "PROVIDE_SAMPLING_METRICS_RATE"
                ),
            ),
            backpressure=BackpressureConfig(
                logs_maxsize=_parse_env_int(
                    data.get("PROVIDE_BACKPRESSURE_LOGS_MAXSIZE", "0"), "PROVIDE_BACKPRESSURE_LOGS_MAXSIZE"
                ),
                traces_maxsize=_parse_env_int(
                    data.get("PROVIDE_BACKPRESSURE_TRACES_MAXSIZE", "0"), "PROVIDE_BACKPRESSURE_TRACES_MAXSIZE"
                ),
                metrics_maxsize=_parse_env_int(
                    data.get("PROVIDE_BACKPRESSURE_METRICS_MAXSIZE", "0"), "PROVIDE_BACKPRESSURE_METRICS_MAXSIZE"
                ),
            ),
            exporter=ExporterPolicyConfig(
                logs_retries=_parse_env_int(
                    data.get("PROVIDE_EXPORTER_LOGS_RETRIES", "0"), "PROVIDE_EXPORTER_LOGS_RETRIES"
                ),
                traces_retries=_parse_env_int(
                    data.get("PROVIDE_EXPORTER_TRACES_RETRIES", "0"), "PROVIDE_EXPORTER_TRACES_RETRIES"
                ),
                metrics_retries=_parse_env_int(
                    data.get("PROVIDE_EXPORTER_METRICS_RETRIES", "0"), "PROVIDE_EXPORTER_METRICS_RETRIES"
                ),
                logs_backoff_seconds=_parse_env_float(
                    data.get("PROVIDE_EXPORTER_LOGS_BACKOFF_SECONDS", "0.0"), "PROVIDE_EXPORTER_LOGS_BACKOFF_SECONDS"
                ),
                traces_backoff_seconds=_parse_env_float(
                    data.get("PROVIDE_EXPORTER_TRACES_BACKOFF_SECONDS", "0.0"),
                    "PROVIDE_EXPORTER_TRACES_BACKOFF_SECONDS",
                ),
                metrics_backoff_seconds=_parse_env_float(
                    data.get("PROVIDE_EXPORTER_METRICS_BACKOFF_SECONDS", "0.0"),
                    "PROVIDE_EXPORTER_METRICS_BACKOFF_SECONDS",
                ),
                logs_timeout_seconds=_parse_env_float(
                    data.get("PROVIDE_EXPORTER_LOGS_TIMEOUT_SECONDS", "10.0"), "PROVIDE_EXPORTER_LOGS_TIMEOUT_SECONDS"
                ),
                traces_timeout_seconds=_parse_env_float(
                    data.get("PROVIDE_EXPORTER_TRACES_TIMEOUT_SECONDS", "10.0"),
                    "PROVIDE_EXPORTER_TRACES_TIMEOUT_SECONDS",
                ),
                metrics_timeout_seconds=_parse_env_float(
                    data.get("PROVIDE_EXPORTER_METRICS_TIMEOUT_SECONDS", "10.0"),
                    "PROVIDE_EXPORTER_METRICS_TIMEOUT_SECONDS",
                ),
                logs_fail_open=_parse_env_bool(
                    data.get("PROVIDE_EXPORTER_LOGS_FAIL_OPEN"), True, "PROVIDE_EXPORTER_LOGS_FAIL_OPEN"
                ),
                traces_fail_open=_parse_env_bool(
                    data.get("PROVIDE_EXPORTER_TRACES_FAIL_OPEN"), True, "PROVIDE_EXPORTER_TRACES_FAIL_OPEN"
                ),
                metrics_fail_open=_parse_env_bool(
                    data.get("PROVIDE_EXPORTER_METRICS_FAIL_OPEN"), True, "PROVIDE_EXPORTER_METRICS_FAIL_OPEN"
                ),
                logs_allow_blocking_in_event_loop=_parse_env_bool(
                    data.get("PROVIDE_EXPORTER_LOGS_ALLOW_BLOCKING_EVENT_LOOP"),
                    False,
                    "PROVIDE_EXPORTER_LOGS_ALLOW_BLOCKING_EVENT_LOOP",
                ),
                traces_allow_blocking_in_event_loop=_parse_env_bool(
                    data.get("PROVIDE_EXPORTER_TRACES_ALLOW_BLOCKING_EVENT_LOOP"),
                    False,
                    "PROVIDE_EXPORTER_TRACES_ALLOW_BLOCKING_EVENT_LOOP",
                ),
                metrics_allow_blocking_in_event_loop=_parse_env_bool(
                    data.get("PROVIDE_EXPORTER_METRICS_ALLOW_BLOCKING_EVENT_LOOP"),
                    False,
                    "PROVIDE_EXPORTER_METRICS_ALLOW_BLOCKING_EVENT_LOOP",
                ),
            ),
            slo=SLOConfig(
                enable_red_metrics=_parse_env_bool(
                    data.get("PROVIDE_SLO_ENABLE_RED_METRICS"), False, "PROVIDE_SLO_ENABLE_RED_METRICS"
                ),
                enable_use_metrics=_parse_env_bool(
                    data.get("PROVIDE_SLO_ENABLE_USE_METRICS"), False, "PROVIDE_SLO_ENABLE_USE_METRICS"
                ),
                include_error_taxonomy=_parse_env_bool(
                    data.get("PROVIDE_SLO_INCLUDE_ERROR_TAXONOMY"), True, "PROVIDE_SLO_INCLUDE_ERROR_TAXONOMY"
                ),
            ),
            security=SecurityConfig(
                max_attr_value_length=_parse_env_int(
                    data.get("PROVIDE_SECURITY_MAX_ATTR_VALUE_LENGTH", "1024"), "PROVIDE_SECURITY_MAX_ATTR_VALUE_LENGTH"
                ),
                max_attr_count=_parse_env_int(
                    data.get("PROVIDE_SECURITY_MAX_ATTR_COUNT", "64"), "PROVIDE_SECURITY_MAX_ATTR_COUNT"
                ),
                max_nesting_depth=_parse_env_int(
                    data.get("PROVIDE_SECURITY_MAX_NESTING_DEPTH", "8"), "PROVIDE_SECURITY_MAX_NESTING_DEPTH"
                ),
            ),
        )


def _validate_color(value: str, field: str) -> None:
    if not value:
        return
    if value not in _VALID_COLORS:
        raise ConfigurationError(f"invalid color name for {field}: {value!r}")


def _normalize_level(value: str) -> str:
    allowed = {"TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    normalized = value.upper()
    if normalized not in allowed:
        raise ConfigurationError(f"invalid log level: {value}")
    return normalized


def _validate_fmt(value: str) -> None:
    if value not in {"console", "json", "pretty"}:
        raise ConfigurationError(f"invalid log format: {value}")


def _validate_rate(value: float, message: str) -> None:
    if not 0.0 <= value <= 1.0:
        raise ConfigurationError(message)


def _validate_non_negative(value: int, message: str) -> None:
    if value < 0:
        raise ConfigurationError(message)


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_env_bool(value: str | None, default: bool, field: str) -> bool:
    if value is None or not value.strip():
        return default
    lowered = value.strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"invalid boolean for {field}: {value!r} (expected one of: 1,true,yes,on,0,false,no,off)")


def _parse_module_levels(raw: str) -> dict[str, str]:
    """Parse ``module=LEVEL,module2=LEVEL2`` into a dict.

    Example: ``PROVIDE_LOG_MODULE_LEVELS="provide.server=DEBUG,asyncio=WARNING"``
    """
    if not raw or not raw.strip():  # pragma: no mutate
        return {}
    result: dict[str, str] = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if "=" not in pair:
            continue
        module, level_str = pair.split("=", 1)
        module = module.strip()
        level_str = _normalize_level(level_str.strip())
        if module:
            result[module] = level_str
    return result


def _parse_env_float(value: str, field: str) -> float:
    try:
        return float(value)
    except ValueError:
        raise ConfigurationError(f"invalid float for {field}: {value!r}") from None


def _parse_env_int(value: str, field: str) -> int:
    try:
        return int(value)
    except ValueError:
        raise ConfigurationError(f"invalid integer for {field}: {value!r}") from None


def _parse_otlp_headers(value: str | None) -> dict[str, str]:
    if not value:
        return {}
    headers: dict[str, str] = {}
    for pair in value.split(","):
        if "=" not in pair:
            stripped = pair.strip()
            if stripped:
                _logger.warning("config.otlp.header_malformed")  # pragma: no mutate
            continue
        key, raw = pair.split("=", 1)
        key = unquote(key.strip())
        if not key:
            continue
        headers[key] = unquote(raw.strip())
    return headers
