# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Runtime config/policy update API."""

from __future__ import annotations

import threading

from undef.telemetry.backpressure import QueuePolicy, set_queue_policy
from undef.telemetry.config import TelemetryConfig
from undef.telemetry.resilience import ExporterPolicy, set_exporter_policy
from undef.telemetry.sampling import SamplingPolicy, set_sampling_policy

_lock = threading.Lock()
_active_config = TelemetryConfig.from_env({})


def apply_runtime_config(config: TelemetryConfig) -> None:
    global _active_config
    with _lock:
        _active_config = config
        set_sampling_policy("logs", SamplingPolicy(default_rate=config.sampling.logs_rate))
        set_sampling_policy("traces", SamplingPolicy(default_rate=config.sampling.traces_rate))
        set_sampling_policy("metrics", SamplingPolicy(default_rate=config.sampling.metrics_rate))
        set_queue_policy(
            QueuePolicy(
                logs_maxsize=config.backpressure.logs_maxsize,
                traces_maxsize=config.backpressure.traces_maxsize,
                metrics_maxsize=config.backpressure.metrics_maxsize,
            )
        )
        set_exporter_policy(
            "logs",
            ExporterPolicy(
                retries=config.exporter.logs_retries,
                backoff_seconds=config.exporter.logs_backoff_seconds,
                timeout_seconds=config.exporter.logs_timeout_seconds,
                fail_open=config.exporter.logs_fail_open,
                allow_blocking_in_event_loop=config.exporter.logs_allow_blocking_in_event_loop,
            ),
        )
        set_exporter_policy(
            "traces",
            ExporterPolicy(
                retries=config.exporter.traces_retries,
                backoff_seconds=config.exporter.traces_backoff_seconds,
                timeout_seconds=config.exporter.traces_timeout_seconds,
                fail_open=config.exporter.traces_fail_open,
                allow_blocking_in_event_loop=config.exporter.traces_allow_blocking_in_event_loop,
            ),
        )
        set_exporter_policy(
            "metrics",
            ExporterPolicy(
                retries=config.exporter.metrics_retries,
                backoff_seconds=config.exporter.metrics_backoff_seconds,
                timeout_seconds=config.exporter.metrics_timeout_seconds,
                fail_open=config.exporter.metrics_fail_open,
                allow_blocking_in_event_loop=config.exporter.metrics_allow_blocking_in_event_loop,
            ),
        )


def update_runtime_config(config: TelemetryConfig) -> TelemetryConfig:
    apply_runtime_config(config)
    return config


def reload_runtime_from_env() -> TelemetryConfig:
    cfg = TelemetryConfig.from_env()
    apply_runtime_config(cfg)
    return get_runtime_config()


def reconfigure_telemetry(config: TelemetryConfig | None = None) -> TelemetryConfig:
    """Apply hot runtime updates or fail fast when provider replacement would be required."""
    from undef.telemetry.logger import core as logger_core
    from undef.telemetry.metrics import provider as metrics_provider
    from undef.telemetry.setup import setup_telemetry, shutdown_telemetry
    from undef.telemetry.tracing import provider as tracing_provider

    target = config or TelemetryConfig.from_env()
    current = get_runtime_config()
    if _provider_config_changed(current, target):
        if (
            logger_core._has_otel_log_provider()
            or tracing_provider._has_tracing_provider()
            or metrics_provider._has_meter_provider()
        ):
            raise RuntimeError(
                "provider-changing reconfiguration is unsupported after OpenTelemetry providers are installed; "
                "restart the process and call setup_telemetry() with the new config"
            )
        shutdown_telemetry()
        return setup_telemetry(target)
    return update_runtime_config(target)


_COLD_KEYS = frozenset(
    {
        "service_name",
        "environment",
        "version",
        "strict_schema",
        "logging",
        "tracing",
        "metrics",
        "event_schema",
        "slo",
    }
)


def _provider_config_changed(current: TelemetryConfig, target: TelemetryConfig) -> bool:
    current_data = asdict(current)
    target_data = asdict(target)
    return any(current_data.get(k) != target_data.get(k) for k in _COLD_KEYS)


def get_runtime_config() -> TelemetryConfig:
    with _lock:
        if _active_config is None:
            return TelemetryConfig.from_env()
        return copy.deepcopy(_active_config)


def reset_runtime_for_tests() -> None:
    """Clear the cached runtime config snapshot."""
    global _active_config
    with _lock:
        _active_config = None
