# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Runtime config/policy update API.

Hot-reconfigurable: sampling policies, backpressure queue limits, exporter retry/timeout policies.
NOT hot-reconfigurable: log handlers, tracer providers, meter providers (require full restart).
Use ``reconfigure_telemetry()`` for a full shutdown+setup cycle when providers must change.
"""

from __future__ import annotations

__all__ = [
    "get_runtime_config",
    "get_runtime_status",
    "get_strict_schema",
    "reconfigure_telemetry",
    "reload_runtime_from_env",
    "set_strict_schema",
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
_active_config: TelemetryConfig | None = None
# Serializes concurrent reconfigure_telemetry() calls against each other.
# Note: this does not fully prevent races with concurrent setup_telemetry() calls,
# which would require process-level coordination. It only serializes concurrent
# reconfigure_telemetry() callers.
_reconfigure_lock = threading.Lock()


def _apply_policies(snapshot: TelemetryConfig) -> None:
    """Push hot policy values from a config snapshot to signal subsystems. Lock-free."""
    set_sampling_policy("logs", SamplingPolicy(default_rate=snapshot.sampling.logs_rate))  # pragma: no mutate
    set_sampling_policy(
        "traces",
        SamplingPolicy(default_rate=min(snapshot.sampling.traces_rate, snapshot.tracing.sample_rate)),
    )
    set_sampling_policy("metrics", SamplingPolicy(default_rate=snapshot.sampling.metrics_rate))
    set_queue_policy(
        QueuePolicy(
            logs_maxsize=snapshot.backpressure.logs_maxsize,
            traces_maxsize=snapshot.backpressure.traces_maxsize,
            metrics_maxsize=snapshot.backpressure.metrics_maxsize,
        )
    )
    set_exporter_policy(
        "logs",
        ExporterPolicy(
            retries=snapshot.exporter.logs_retries,
            backoff_seconds=snapshot.exporter.logs_backoff_seconds,
            timeout_seconds=snapshot.exporter.logs_timeout_seconds,
            fail_open=snapshot.exporter.logs_fail_open,
            allow_blocking_in_event_loop=snapshot.exporter.logs_allow_blocking_in_event_loop,
        ),
    )
    set_exporter_policy(
        "traces",
        ExporterPolicy(
            retries=snapshot.exporter.traces_retries,
            backoff_seconds=snapshot.exporter.traces_backoff_seconds,
            timeout_seconds=snapshot.exporter.traces_timeout_seconds,
            fail_open=snapshot.exporter.traces_fail_open,
            allow_blocking_in_event_loop=snapshot.exporter.traces_allow_blocking_in_event_loop,
        ),
    )
    set_exporter_policy(
        "metrics",
        ExporterPolicy(
            retries=snapshot.exporter.metrics_retries,
            backoff_seconds=snapshot.exporter.metrics_backoff_seconds,
            timeout_seconds=snapshot.exporter.metrics_timeout_seconds,
            fail_open=snapshot.exporter.metrics_fail_open,
            allow_blocking_in_event_loop=snapshot.exporter.metrics_allow_blocking_in_event_loop,
        ),
    )


def apply_runtime_config(config: TelemetryConfig) -> None:
    """Apply a config snapshot to runtime signal policies."""
    global _active_config
    with _lock:
        snapshot = copy.deepcopy(config)
        _active_config = snapshot
    _apply_policies(snapshot)


def _overrides_from_config(cfg: TelemetryConfig) -> RuntimeOverrides:
    """Extract the hot-reloadable fields from a full TelemetryConfig."""
    return RuntimeOverrides(
        sampling=cfg.sampling,
        backpressure=cfg.backpressure,
        exporter=cfg.exporter,
        security=cfg.security,
        slo=cfg.slo,
        pii_max_depth=cfg.pii_max_depth,
        strict_schema=cfg.strict_schema,
        logging=cfg.logging,
        event_schema=cfg.event_schema,
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
    if overrides.strict_schema is not None:
        merged.strict_schema = overrides.strict_schema
    if overrides.logging is not None:
        merged.logging = overrides.logging
    if overrides.event_schema is not None:
        merged.event_schema = overrides.event_schema
    return merged


def _logging_provider_config_changed(current: TelemetryConfig, target: TelemetryConfig) -> bool:
    return (
        current.logging.otlp_endpoint != target.logging.otlp_endpoint
        or current.logging.otlp_headers != target.logging.otlp_headers
        or current.exporter.logs_timeout_seconds != target.exporter.logs_timeout_seconds
    )


def update_runtime_config(overrides: RuntimeOverrides) -> TelemetryConfig:
    """Merge overrides into the active config and re-apply hot policies.

    When logging config changes, the structlog pipeline is rebuilt so
    level/format/module-level changes take effect immediately.
    """
    global _active_config
    logging_changed = False  # pragma: no mutate — None is also falsy; equivalent mutation
    with _lock:
        base = _active_config if _active_config is not None else TelemetryConfig.from_env()
        if overrides.logging is not None and overrides.logging != base.logging:
            logging_changed = True
        merged = _apply_overrides(base, overrides)
        if _logging_provider_config_changed(base, merged):
            from provide.telemetry.logger.core import _has_otel_log_provider

            if _has_otel_log_provider():
                raise RuntimeError(
                    "provider-changing logging reconfiguration is unsupported after OpenTelemetry log providers "
                    "are installed. Use reconfigure_telemetry() for full provider replacement, or restart the "
                    "process and call setup_telemetry() with the new config."
                )
        _active_config = merged
    _apply_policies(merged)
    if logging_changed:
        from provide.telemetry.logger.core import configure_logging  # pragma: no mutate

        configure_logging(merged, force=True)
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
    return update_runtime_config(_overrides_from_config(fresh))


def reconfigure_telemetry(config: TelemetryConfig | None = None) -> TelemetryConfig:
    """Apply hot runtime updates or fail fast when provider replacement would be required."""
    from provide.telemetry.logger import core as logger_core
    from provide.telemetry.metrics import provider as metrics_provider
    from provide.telemetry.setup import setup_telemetry, shutdown_telemetry
    from provide.telemetry.tracing import provider as tracing_provider

    with _reconfigure_lock:
        target = config or TelemetryConfig.from_env()
        current = get_runtime_config()
        if _provider_config_changed(current, target):
            if (
                logger_core._has_otel_log_provider()
                or tracing_provider._has_tracing_provider()
                or metrics_provider._has_meter_provider()
            ):
                raise RuntimeError(
                    "provider-changing reconfiguration is unsupported after OpenTelemetry providers are installed. "
                    "Restart the process and call setup_telemetry() with the new config."
                )
            shutdown_telemetry()
            return setup_telemetry(target)
        if _logging_provider_config_changed(current, target) and logger_core._has_otel_log_provider():
            raise RuntimeError(
                "provider-changing logging reconfiguration is unsupported after OpenTelemetry log providers "
                "are installed (endpoint/headers/timeout change). Restart the process and call "
                "setup_telemetry() with the new config."
            )
        return update_runtime_config(_overrides_from_config(target))


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
    """Return a defensive copy of the active runtime config snapshot."""
    with _lock:
        if _active_config is None:
            return TelemetryConfig.from_env()
        return copy.deepcopy(_active_config)


def get_runtime_status() -> dict[str, object]:
    """Return runtime/provider status using the shared cross-language shape."""
    from provide.telemetry.health import get_health_snapshot
    from provide.telemetry.logger import core as logger_core
    from provide.telemetry.metrics import provider as metrics_provider
    from provide.telemetry.tracing import provider as tracing_provider

    cfg = get_runtime_config()
    providers = {
        "logs": bool(logger_core._has_otel_log_provider()),
        "traces": bool(tracing_provider._has_tracing_provider()),
        "metrics": bool(metrics_provider._has_meter_provider()),
    }
    return {
        "setup_done": _active_config is not None or logger_core._configured,
        "signals": {
            "logs": True,
            "traces": cfg.tracing.enabled,
            "metrics": cfg.metrics.enabled,
        },
        "providers": providers,
        "fallback": {signal: not installed for signal, installed in providers.items()},
        "setup_error": get_health_snapshot().setup_error,
    }


def _is_strict_event_name() -> bool:
    """Check strict event-name mode without deepcopy (hot-path optimised).

    No lock needed: CPython's GIL makes single reference reads atomic.
    Worst case we read a slightly stale config, which is acceptable for
    a boolean configuration flag.
    """
    cfg = _active_config
    if cfg is None:
        return False
    return cfg.strict_schema or cfg.event_schema.strict_event_name


def set_strict_schema(enabled: bool) -> None:
    """Convenience wrapper: enable or disable strict event-schema validation.

    Equivalent to ``update_runtime_config(RuntimeOverrides(strict_schema=enabled))``.
    Thread-safe via the runtime config lock.
    """
    update_runtime_config(RuntimeOverrides(strict_schema=enabled))


def get_strict_schema() -> bool:
    """Return the current strict-schema flag from the active runtime config."""
    return get_runtime_config().strict_schema


def reset_runtime_for_tests() -> None:
    """Clear the cached runtime config snapshot."""
    global _active_config
    with _lock:
        _active_config = None
