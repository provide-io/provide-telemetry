# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Runtime config/policy update API.

Hot-reconfigurable: sampling policies, backpressure queue limits, exporter retry/timeout policies.
NOT hot-reconfigurable: log handlers, tracer providers, meter providers (require full restart).
Use ``reconfigure_telemetry()`` only for hot policy updates. Provider changes after real
OpenTelemetry providers are installed require a full process restart.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "FlushResult",
    "ProviderMode",
    "ReconfigureResult",
    "RuntimeState",
    "RuntimeStatus",
    "SignalFlushResult",
    "TelemetryRuntime",
    "flush",
    "flush_result",
    "get_logger",
    "get_meter",
    "get_runtime_config",
    "get_runtime_status",
    "get_strict_schema",
    "get_tracer",
    "provider_immutable_error",
    "provider_mode",
    "reconfigure_result",
    "reconfigure_telemetry",
    "reload_runtime_from_env",
    "runtime_state",
    "runtime_status",
    "set_strict_schema",
    "shutdown",
    "signal_flush_result",
    "start",
    "telemetry_config",
    "telemetry_runtime",
    "update_runtime_config",
]

import copy
import logging
import threading
from typing import Any

from provide.telemetry._runtime_types import (
    FlushResult,
    ProviderMode,
    ReconfigureResult,
    RuntimeState,
    RuntimeStatus,
    SignalFlushResult,
)
from provide.telemetry.backpressure import QueuePolicy, set_queue_policy
from provide.telemetry.config import RuntimeOverrides, TelemetryConfig
from provide.telemetry.exceptions import ProviderImmutableError
from provide.telemetry.resilience import ExporterPolicy, set_exporter_policy
from provide.telemetry.sampling import SamplingPolicy, set_sampling_policy

_logger = logging.getLogger(__name__)


class provider_mode(StrEnum):
    """Snake-case canonical alias for conformance checks."""

    OWNED = ProviderMode.OWNED.value
    HOST = ProviderMode.HOST.value
    LOCAL = ProviderMode.LOCAL.value


class runtime_state(StrEnum):
    """Snake-case canonical alias for conformance checks."""

    LOCAL = RuntimeState.LOCAL.value
    STARTING = RuntimeState.STARTING.value
    READY = RuntimeState.READY.value
    DEGRADED = RuntimeState.DEGRADED.value
    RECONFIGURING = RuntimeState.RECONFIGURING.value
    STOPPING = RuntimeState.STOPPING.value
    STOPPED = RuntimeState.STOPPED.value


class signal_flush_result(SignalFlushResult):
    """Snake-case canonical alias for conformance checks."""


class flush_result(FlushResult):
    """Snake-case canonical alias for conformance checks."""


class reconfigure_result(ReconfigureResult):
    """Snake-case canonical alias for conformance checks."""


class telemetry_config(TelemetryConfig):
    """Snake-case canonical alias for conformance checks."""


class provider_immutable_error(ProviderImmutableError):
    """Snake-case canonical alias for conformance checks."""


class TelemetryRuntime:
    """Canonical runtime facade around the package module-level telemetry APIs."""

    def __init__(self) -> None:
        self._state = RuntimeState.READY
        self._provider_mode = ProviderMode.OWNED

    def start(self, config: TelemetryConfig | None = None) -> TelemetryConfig:
        from provide.telemetry.setup import setup_telemetry

        started = setup_telemetry(config)
        self._state = RuntimeState.READY
        return started

    def shutdown(self, timeout: float | None = None) -> None:
        from provide.telemetry.setup import shutdown_telemetry

        shutdown_telemetry()
        self._state = RuntimeState.STOPPED if timeout is None else RuntimeState.STOPPING

    def flush(self, timeout: float | None = None) -> bool:
        from provide.telemetry.setup import flush_telemetry

        return flush_telemetry(timeout_seconds=timeout)

    def get_logger(self, name: str) -> Any:
        from provide.telemetry.logger import get_logger

        return get_logger(name)

    def get_tracer(self, name: str) -> Any:
        from provide.telemetry.tracing import get_tracer

        return get_tracer(name)

    def get_meter(self, name: str) -> Any:
        from provide.telemetry.metrics import get_meter

        return get_meter(name)

    def get_runtime_config(self) -> TelemetryConfig:
        return get_runtime_config()

    def get_runtime_status(self) -> dict[str, object]:
        return get_runtime_status()

    def update_config(self, cfg: TelemetryConfig | RuntimeOverrides) -> ReconfigureResult:
        if isinstance(cfg, RuntimeOverrides):
            previous = get_runtime_config()
            result = update_runtime_config(cfg)
            return ReconfigureResult(
                applied=True,
                config=result,
                previous=previous,
                state=self._state,
                status=self._state,
            )
        previous = get_runtime_config()
        return ReconfigureResult(
            applied=True,
            config=reconfigure_telemetry(cfg),
            previous=previous,
            state=self._state,
            status=self._state,
        )


class runtime_status(RuntimeStatus):
    """Snake-case canonical alias for conformance checks."""


class telemetry_runtime(TelemetryRuntime):
    """Snake-case canonical alias for conformance checks."""


_lock = threading.Lock()
_active_config: TelemetryConfig | None = None
# Serializes concurrent reconfigure_telemetry() calls against each other.
# Note: this does not fully prevent races with concurrent setup_telemetry() calls,
# which would require process-level coordination. It only serializes concurrent
# reconfigure_telemetry() callers.
_reconfigure_lock = threading.Lock()

_runtime = TelemetryRuntime()


def start(config: TelemetryConfig | None = None) -> TelemetryConfig:
    """Start/refresh runtime setup through the canonical facade."""
    return _runtime.start(config)


def shutdown(timeout: float | None = None) -> None:
    """Shutdown runtime through the canonical facade."""
    _runtime.shutdown(timeout)


def flush(timeout: float | None = None) -> bool:
    """Flush runtime through the canonical facade."""
    return _runtime.flush(timeout)


def get_logger(name: str) -> Any:
    """Return a logger from the canonical runtime facade."""
    return _runtime.get_logger(name)


def get_tracer(name: str) -> Any:
    """Return a tracer from the canonical runtime facade."""
    return _runtime.get_tracer(name)


def get_meter(name: str) -> Any:
    """Return a meter from the canonical runtime facade."""
    return _runtime.get_meter(name)


def _apply_policies(snapshot: TelemetryConfig) -> None:
    """Push hot policy values from a config snapshot to signal subsystems. Lock-free."""
    set_sampling_policy(
        "logs", SamplingPolicy(default_rate=snapshot.sampling.logs_rate)
    )  # pragma: no mutate — signal name string is the API contract; pinned across reloads
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
            from provide.telemetry.logger.core import _has_real_otel_log_provider

            if _has_real_otel_log_provider():
                raise ProviderImmutableError(
                    "provider-changing logging reconfiguration is unsupported after OpenTelemetry log providers "
                    "are installed. Restart the process and call setup_telemetry() with the new config."
                )
        _active_config = merged
    _apply_policies(merged)
    if logging_changed:
        from provide.telemetry.logger.core import (
            configure_logging,  # pragma: no mutate — lazy import to avoid circular dependency at module load; path is a stable public name
        )

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
                logger_core._has_real_otel_log_provider()
                or tracing_provider._has_live_tracing_provider()
                or metrics_provider._has_live_meter_provider()
            ):
                raise ProviderImmutableError(
                    "provider-changing reconfiguration is unsupported after OpenTelemetry providers are installed. "
                    "Restart the process and call setup_telemetry() with the new config."
                )
            shutdown_telemetry()
            return setup_telemetry(target)
        if _logging_provider_config_changed(current, target) and logger_core._has_real_otel_log_provider():
            raise ProviderImmutableError(
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
    from provide.telemetry import setup as setup_mod
    from provide.telemetry.health import get_health_snapshot
    from provide.telemetry.logger import core as logger_core
    from provide.telemetry.metrics import provider as metrics_provider
    from provide.telemetry.tracing import provider as tracing_provider

    cfg = get_runtime_config()
    with setup_mod._lock:
        setup_done = setup_mod._setup_done
    # traces and metrics report what is in play, not what we installed: a host
    # application's own provider owns the OTel global, and get_tracer() /
    # get_meter() resolve it, so reporting it as fallback would be a lie. Logs
    # stays install-scoped — our records reach OTel through the handler *we*
    # attach, so a foreign logger provider is genuinely not in our path.
    providers = {
        "logs": bool(logger_core._has_real_otel_log_provider()),
        "traces": bool(tracing_provider._has_effective_tracing_provider()),
        "metrics": bool(metrics_provider._has_effective_meter_provider()),
    }
    return {
        "setup_done": setup_done,
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
