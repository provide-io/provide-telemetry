# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Telemetry setup coordinator."""

from __future__ import annotations

__all__ = [
    "flush_telemetry",
    "setup_telemetry",
    "shutdown_telemetry",
]

import logging
import threading
import warnings
from collections.abc import Callable

from provide.telemetry.config import TelemetryConfig
from provide.telemetry.logger.core import _reset_logging_for_tests as _reset_logging
from provide.telemetry.logger.core import configure_logging, shutdown_logging
from provide.telemetry.tracing.provider import _refresh_otel_tracing, setup_tracing, shutdown_tracing
from provide.telemetry.tracing.provider import _reset_tracing_for_tests as _reset_tracing

_logger = logging.getLogger(__name__)
_lock = threading.Lock()
_setup_done = False


def _rollback(completed: list[str]) -> None:
    from provide.telemetry.metrics.provider import shutdown_metrics

    teardowns = {
        "configure_logging": shutdown_logging,
        "setup_tracing": shutdown_tracing,
        "setup_metrics": shutdown_metrics,
    }
    for step in reversed(completed):
        try:
            teardowns[step]()
        except Exception:
            _logger.warning(
                "setup.rollback.step_failed", exc_info=True
            )  # pragma: no mutate — warning log string is non-semantic; rollback proceeds regardless


def _quiet_otel_sdk_loggers() -> None:
    """Suppress OTel SDK export noise that the resilience layer already handles."""
    for name in (
        "opentelemetry.exporter",
        "opentelemetry.sdk",
    ):  # pragma: no mutate — tuple iteration; logger-name strings are OTel module paths pinned by upstream
        logging.getLogger(name).setLevel(
            logging.CRITICAL
        )  # pragma: no mutate — suppression level; any level >= WARNING produces the same operator-observed silence


def setup_telemetry(config: TelemetryConfig | None = None) -> TelemetryConfig:
    from provide.telemetry.metrics.provider import _refresh_otel_metrics, setup_metrics
    from provide.telemetry.runtime import apply_runtime_config
    from provide.telemetry.slo import _rebind_slo_instruments, record_red_metrics, record_use_metrics

    global _setup_done
    cfg = config or TelemetryConfig.from_env()
    with _lock:
        if not _setup_done:
            _quiet_otel_sdk_loggers()
            apply_runtime_config(cfg)
            from provide.telemetry.health import set_setup_error

            completed: list[str] = []
            try:
                configure_logging(cfg, force=True)
                completed.append("configure_logging")
                _refresh_otel_tracing()
                _refresh_otel_metrics()
                setup_tracing(cfg)
                completed.append("setup_tracing")
                setup_metrics(cfg)
                completed.append("setup_metrics")
                _rebind_slo_instruments()
            except Exception as exc:
                _rollback(completed)
                set_setup_error(str(exc))
                warnings.warn(  # pragma: no mutate — best-effort warning emission; exact wording is non-semantic
                    f"telemetry setup failed, running in degraded mode: {exc}",
                    RuntimeWarning,
                    stacklevel=2,  # pragma: no mutate — stacklevel tuning; any small positive int surfaces the caller frame
                )
                # Always restore logging — rollback may have torn it down above.
                configure_logging(cfg, force=True)
            else:
                set_setup_error(None)  # clear any stale error from a prior failed attempt
                _setup_done = True
            if cfg.slo.enable_red_metrics:
                record_red_metrics("startup", "INIT", 200, 0.0)
            if cfg.slo.enable_use_metrics:
                record_use_metrics("startup", 0)
    return cfg


def _reset_setup_state_for_tests() -> None:
    global _setup_done
    with _lock:
        _setup_done = False


def _reset_all_for_tests() -> None:
    from provide.telemetry.backpressure import reset_queues_for_tests as _reset_queues
    from provide.telemetry.cardinality import clear_cardinality_limits as _reset_cardinality
    from provide.telemetry.health import reset_health_for_tests as _reset_health
    from provide.telemetry.metrics.provider import _set_meter_for_test as _reset_metrics
    from provide.telemetry.pii import reset_pii_rules_for_tests as _reset_pii
    from provide.telemetry.resilience import reset_resilience_for_tests as _reset_resilience
    from provide.telemetry.runtime import reset_runtime_for_tests as _reset_runtime
    from provide.telemetry.sampling import reset_sampling_for_tests as _reset_sampling
    from provide.telemetry.slo import _reset_slo_for_tests as _reset_slo

    global _setup_done
    with _lock:
        _setup_done = False
    _reset_logging()
    _reset_tracing()
    _reset_metrics(None)
    _reset_slo()
    _reset_resilience()
    _reset_health()
    _reset_queues()
    _reset_pii()
    _reset_cardinality()
    _reset_sampling()
    _reset_runtime()


def _drain_signal(signal: str, drain: Callable[[float], bool], deadline: float) -> bool:
    """Run one signal's drain, reporting a raised exporter error as a failed drain.

    ``bounded_provider_flush`` re-raises what ``force_flush`` raised — the right
    contract for the primitive, the wrong one for a bool-returning public API
    called at a request boundary.
    """
    try:
        return drain(deadline)
    except Exception as exc:
        _logger.warning("telemetry.flush.signal_failed", extra={"signal": signal, "error": str(exc)})
        return False


def flush_telemetry(timeout_seconds: float | None = None) -> bool:
    """Force-flush installed providers without tearing them down.

    The drain half of :func:`shutdown_telemetry`: every provider *we* installed
    (logs, traces, metrics) is force-flushed under a bounded deadline and stays
    installed and usable afterwards. Use it where records must be out before
    control returns — a request boundary, a checkpoint, a serverless freeze —
    rather than shutting telemetry down and paying to set it up again.

    *timeout_seconds* defaults to the bounded-shutdown deadline
    (``PROVIDE_EXPORTER_LOGS_SHUTDOWN_TIMEOUT_SECONDS``, 5.0s) and is applied
    per signal. Returns True when every signal flushed within the deadline,
    False when any was abandoned; a signal whose provider we never installed
    counts as nothing to flush.

    A provider a host application installed on the OTel globals is not ours to
    drain and is left alone.
    """
    from provide.telemetry._provider_drain import flush_logging, flush_metrics, flush_tracing
    from provide.telemetry.runtime import get_runtime_config

    deadline = (
        get_runtime_config().exporter.logs_shutdown_timeout_seconds if timeout_seconds is None else timeout_seconds
    )
    # Materialise before reducing, and route each through _drain_signal: every
    # signal must get its drain attempt even when an earlier one is abandoned at
    # the deadline *or* raises. `all()` over a generator would let a slow logs
    # endpoint deny traces and metrics theirs, and an exception escaping here
    # would break the documented bool contract inside a caller's request handler.
    results = [
        _drain_signal("logs", flush_logging, deadline),
        _drain_signal("traces", flush_tracing, deadline),
        _drain_signal("metrics", flush_metrics, deadline),
    ]
    return all(results)


def shutdown_telemetry(timeout_seconds: float | None = None) -> None:
    """Flush and tear down telemetry providers and reset runtime policies.

    *timeout_seconds* bounds the drain that precedes teardown — the part that can
    hang on an unreachable collector — and defaults to the configured
    bounded-shutdown deadline. A caller in a SIGTERM handler passes the time it
    has left so the drain cannot overrun its termination grace period; teardown
    itself is local work and always completes.
    """
    from provide.telemetry.backpressure import reset_queues_for_tests as _reset_queues
    from provide.telemetry.metrics.provider import shutdown_metrics
    from provide.telemetry.resilience import reset_resilience_for_tests as _reset_resilience
    from provide.telemetry.runtime import reset_runtime_for_tests as _reset_runtime
    from provide.telemetry.sampling import reset_sampling_for_tests as _reset_sampling

    # Drain under the caller's deadline before teardown. Taken outside _lock:
    # flush_telemetry reads runtime config, and the per-signal shutdowns below
    # re-flush what this leaves behind.
    flush_telemetry(timeout_seconds)

    global _setup_done
    with _lock:
        _setup_done = False
        shutdown_tracing()
        shutdown_metrics()
        shutdown_logging()
        _reset_runtime()
        _reset_sampling()
        _reset_queues()
        _reset_resilience()
