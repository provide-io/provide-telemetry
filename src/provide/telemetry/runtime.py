# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Runtime config/policy update API."""

from __future__ import annotations

__all__ = [
    "get_runtime_config",
    "reconfigure_telemetry",
    "reload_runtime_from_env",
    "update_runtime_config",
]

import copy
import logging
import threading

from provide.telemetry.backpressure import QueuePolicy, set_queue_policy
from provide.telemetry.config import RuntimeOverrides, TelemetryConfig
from provide.telemetry.resilience import ExporterPolicy, set_exporter_policy
from provide.telemetry.sampling import SamplingPolicy, set_sampling_policy

_logger = logging.getLogger(__name__)

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


def _apply_overrides(base: TelemetryConfig, overrides: RuntimeOverrides) -> TelemetryConfig:
    """Merge non-None override fields into a copy of base config."""
    merged = copy.deepcopy(base)
    if overrides.sampling is not None:
        merged.sampling = overrides.sampling
    if overrides.backpressure is not None:
        merged.backpressure = overrides.backpressure
    if overrides.exporter is not None:
        merged.exporter = overrides.exporter
    if overrides.security is not None:
        merged.security = overrides.security
    if overrides.slo is not None:
        merged.slo = overrides.slo
    if overrides.pii_max_depth is not None:
        merged.pii_max_depth = overrides.pii_max_depth
    return merged


def update_runtime_config(overrides: RuntimeOverrides) -> TelemetryConfig:
    """Merge overrides into the active config and re-apply hot policies."""
    with _lock:
        base = _active_config if _active_config is not None else TelemetryConfig.from_env()
    merged = _apply_overrides(base, overrides)
    apply_runtime_config(merged)
    return get_runtime_config()


def reload_runtime_from_env() -> TelemetryConfig:
    """Reload environment config, apply hot fields, warn on cold-field drift."""
    fresh = TelemetryConfig.from_env()
    with _lock:
        current = _active_config
    if current is not None:
        changed_cold = [k for k in _COLD_KEYS if getattr(current, k) != getattr(fresh, k)]
        if changed_cold:
            _logger.warning(
                "runtime.cold_field_drift",
                extra={"fields": changed_cold, "action": "restart required to apply"},
            )
    overrides = RuntimeOverrides(
        sampling=fresh.sampling,
        backpressure=fresh.backpressure,
        exporter=fresh.exporter,
        security=fresh.security,
        slo=fresh.slo,
        pii_max_depth=fresh.pii_max_depth,
    )
    return update_runtime_config(overrides)


def reconfigure_telemetry(config: TelemetryConfig | None = None) -> TelemetryConfig:
    """Apply hot runtime updates or fail fast when provider replacement would be required."""
    from provide.telemetry.logger import core as logger_core
    from provide.telemetry.metrics import provider as metrics_provider
    from provide.telemetry.setup import setup_telemetry, shutdown_telemetry
    from provide.telemetry.tracing import provider as tracing_provider

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
    overrides = RuntimeOverrides(
        sampling=target.sampling,
        backpressure=target.backpressure,
        exporter=target.exporter,
        security=target.security,
        slo=target.slo,
        pii_max_depth=target.pii_max_depth,
    )
    return update_runtime_config(overrides)


_COLD_KEYS = frozenset(
    {
        "service_name",
        "environment",
        "version",
        "tracing",
        "metrics",
    }
)


def _provider_config_changed(current: TelemetryConfig, target: TelemetryConfig) -> bool:
    return any(getattr(current, k) != getattr(target, k) for k in _COLD_KEYS)


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
