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

import logging
from typing import Any

from provide.telemetry._lifecycle import coordinator, copy_config
from provide.telemetry._runtime_policies import apply_policies
from provide.telemetry._runtime_types import (
    FlushResult,
    ProviderMode,
    ReconfigureResult,
    RuntimeState,
    RuntimeStatus,
    SignalDrainOutcome,
    SignalFlushResult,
)
from provide.telemetry.config import RuntimeOverrides, TelemetryConfig
from provide.telemetry.exceptions import ConfigurationError, ProviderImmutableError

_logger = logging.getLogger(__name__)


# Snake-case canonical names required by spec/telemetry-api.yaml. These are true
# aliases, not subclasses: a subclass of a frozen dataclass compares unequal to
# the canonical type (dataclass __eq__ returns NotImplemented across classes),
# and a redeclared enum drifts from the original the moment a member is added.
provider_mode = ProviderMode
runtime_state = RuntimeState
signal_flush_result = SignalFlushResult
flush_result = FlushResult
reconfigure_result = ReconfigureResult
telemetry_config = TelemetryConfig
provider_immutable_error = ProviderImmutableError


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

        # timeout bounds the drain; teardown is local work that always completes,
        # so the terminal state is STOPPED either way (matches Go/Rust/TypeScript)
        # — including when a drain raises, which shutdown_telemetry re-raises
        # after its own cleanup has finished.
        try:
            shutdown_telemetry(timeout_seconds=timeout)
        finally:
            self._state = RuntimeState.STOPPED

    def flush(self, timeout: float | None = None) -> FlushResult:
        from provide.telemetry._provider_drain import installed_signals, owned_signals
        from provide.telemetry.setup import flush_signals

        # Not get_runtime_status(): that reads the runtime config, which with no
        # active config falls back to TelemetryConfig.from_env() and raises on a
        # malformed environment. flush() is a drain path — a SIGTERM handler in
        # a process with a mis-set env var must still get its records out — so
        # it asks the providers directly and never touches config.
        installed = installed_signals()
        owned = owned_signals()
        # Per signal, not one aggregate: the three drain independently against
        # three potentially different endpoints, so an unreachable logs
        # collector must not be reported as a traces and metrics timeout too.
        drained = flush_signals(timeout_seconds=timeout)
        return FlushResult(
            logs=_signal_flush_result(installed["logs"], owned["logs"], drained["logs"]),
            traces=_signal_flush_result(installed["traces"], owned["traces"], drained["traces"]),
            metrics=_signal_flush_result(installed["metrics"], owned["metrics"], drained["metrics"]),
        )

    def get_logger(self, name: str | None = None) -> Any:
        from provide.telemetry.logger import get_logger

        return get_logger(name)

    def get_tracer(self, name: str | None = None) -> Any:
        from provide.telemetry.tracing import get_tracer

        return get_tracer(name)

    def get_meter(self, name: str | None = None) -> Any:
        from provide.telemetry.metrics import get_meter

        return get_meter(name)

    def get_runtime_config(self) -> TelemetryConfig:
        return get_runtime_config()

    def get_runtime_status(self) -> RuntimeStatus:
        return get_runtime_status()

    def update_config(self, cfg: TelemetryConfig | RuntimeOverrides) -> ReconfigureResult:
        previous = get_runtime_config()
        current = update_runtime_config(cfg) if isinstance(cfg, RuntimeOverrides) else reconfigure_telemetry(cfg)
        return ReconfigureResult(applied=True, current=current, previous=previous, state=self._state)


runtime_status = RuntimeStatus
telemetry_runtime = TelemetryRuntime


def _signal_flush_result(installed: bool, owned: bool, outcome: SignalDrainOutcome) -> SignalFlushResult:
    """Per-signal flush outcome.

    A signal with no provider has nothing to drain. A signal whose provider a
    host application installed on the OTel globals is reported installed — that
    is what ``get_tracer()`` resolves — but is not ours to drain: the flush
    helpers leave it alone. Calling that ``flushed`` would tell a caller its
    spans are out when they are still in the host's batch processor, which is
    exactly what a serverless handler flushing before a freeze is asking about.

    *outcome* is a :data:`~provide.telemetry._runtime_types.SignalDrainOutcome`:
    a drain that raised maps to ``failed``, one abandoned at the deadline to
    ``timed_out`` — the same split Go's facade reports.
    """
    if not installed:
        return SignalFlushResult(not_installed=True)
    if not owned:
        return SignalFlushResult(not_owned=True)
    return SignalFlushResult(
        flushed=outcome == "flushed",
        timed_out=outcome == "timed_out",
        failed=outcome == "failed",
    )


_runtime = TelemetryRuntime()


def start(config: TelemetryConfig | None = None) -> TelemetryConfig:
    """Start/refresh runtime setup through the canonical facade."""
    return _runtime.start(config)


def shutdown(timeout: float | None = None) -> None:
    """Shutdown runtime through the canonical facade."""
    _runtime.shutdown(timeout)


def flush(timeout: float | None = None) -> FlushResult:
    """Flush runtime through the canonical facade."""
    return _runtime.flush(timeout)


def get_logger(name: str | None = None) -> Any:
    """Return a logger from the canonical runtime facade."""
    return _runtime.get_logger(name)


def get_tracer(name: str | None = None) -> Any:
    """Return a tracer from the canonical runtime facade."""
    return _runtime.get_tracer(name)


def get_meter(name: str | None = None) -> Any:
    """Return a meter from the canonical runtime facade."""
    return _runtime.get_meter(name)


def apply_runtime_config(config: TelemetryConfig) -> None:
    """Apply a config snapshot to runtime signal policies, then publish it.

    Policies first, publication second. Publishing first made the generation
    visible while the sampling, queue and exporter policies it describes were
    still being installed, so a concurrent reader could act on a config that
    was not yet in force.
    """
    with coordinator.operations:
        apply_policies(config)
        # publish() takes its own copy, so the caller keeps ownership of the
        # object it passed and cannot mutate the published generation later.
        coordinator.publish(config, setup_done=coordinator.peek().setup_done)


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
    merged = copy_config(base)
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


def _require_live_config() -> TelemetryConfig:
    """Return the published config, or refuse when telemetry is not set up.

    Reconfiguring something that was never configured is a caller error, not a
    shorthand for setup. All three runtime write paths used to fall back to
    ``TelemetryConfig.from_env()`` here, so they quietly performed a first-time
    setup from whatever the environment happened to hold — and then reported
    ``setup_done`` with no providers installed and no shutdown owed.

    Reads keep the fallback on purpose: ``get_runtime_config`` and the drain
    path must not raise on a malformed environment. It is writes that refuse.

    Callers hold ``coordinator.operations``, so this cannot race a concurrent
    ``setup_telemetry``.
    """
    live = coordinator.peek().config
    if live is None:
        raise ConfigurationError("telemetry not set up: call setup_telemetry first")
    return live


def update_runtime_config(overrides: RuntimeOverrides) -> TelemetryConfig:
    """Merge overrides into the active config and re-apply hot policies.

    When logging config changes, the structlog pipeline is rebuilt so
    level/format/module-level changes take effect immediately.
    """
    logging_changed = False  # pragma: no mutate — None is also falsy; equivalent mutation
    with coordinator.operations:
        base = _require_live_config()
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
        # Everything the new generation promises is installed before the
        # generation exists. A reader that sees generation N+1 can rely on
        # N+1's policies and logging pipeline already being in force.
        apply_policies(merged)
        if logging_changed:
            from provide.telemetry.logger.core import (
                configure_logging,  # pragma: no mutate — lazy import to avoid circular dependency at module load; path is a stable public name
            )

            configure_logging(merged, force=True)
        coordinator.publish(merged, setup_done=coordinator.peek().setup_done)
    return get_runtime_config()


def reload_runtime_from_env() -> TelemetryConfig:
    """Reload environment config, apply hot fields, warn on cold-field drift."""
    fresh = TelemetryConfig.from_env()
    current = coordinator.peek().config
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

    with coordinator.operations:
        # Guarded here as well as in update_runtime_config: the
        # provider-changed branch below routes through shutdown + setup and
        # never reaches it.
        current = _require_live_config()
        target = config or TelemetryConfig.from_env()
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
    """Return a defensive copy of the active runtime config snapshot.

    The copy carries ``receipt_sink`` by reference, so a caller that passed a
    sink to ``setup_telemetry`` gets that same object back and can assert
    against the receipts it actually receives.
    """
    config = coordinator.snapshot().config
    if config is None:
        return TelemetryConfig.from_env()
    return config


def get_runtime_status() -> RuntimeStatus:
    """Return runtime/provider status using the shared cross-language shape."""
    from provide.telemetry._provider_drain import installed_signals
    from provide.telemetry.health import get_health_snapshot

    cfg = get_runtime_config()
    # From the generation, not from a lifecycle lock. Status is the call an
    # operator makes *while* something is wrong, and waiting on the lock would
    # make it block behind the very shutdown it is being used to observe.
    setup_done = coordinator.peek().setup_done
    providers = installed_signals()
    return RuntimeStatus(
        setup_done=setup_done,
        signals={
            "logs": True,
            "traces": cfg.tracing.enabled,
            "metrics": cfg.metrics.enabled,
        },
        providers=providers,
        fallback={signal: not installed for signal, installed in providers.items()},
        setup_error=get_health_snapshot().setup_error,
    )


def _is_strict_event_name() -> bool:
    """Check strict event-name mode without deepcopy (hot-path optimised).

    No lock needed: CPython's GIL makes single reference reads atomic.
    Worst case we read a slightly stale config, which is acceptable for
    a boolean configuration flag.
    """
    cfg = coordinator.peek().config
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
    """Publish an empty generation, clearing the cached runtime config."""
    with coordinator.operations:
        coordinator.publish(None, setup_done=coordinator.peek().setup_done)
