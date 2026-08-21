# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Telemetry setup coordinator."""

from __future__ import annotations

__all__ = [
    "flush_signals",
    "flush_telemetry",
    "setup_telemetry",
    "shutdown_telemetry",
]

import logging
import warnings
from collections.abc import Callable

# Setup, reconfiguration and shutdown are the same kind of operation on the
# same state, so they all take coordinator.operations. Two independent locks
# were the defect: neither waited on the other, so a shutdown could tear down
# providers a concurrent setup had just installed.
from provide.telemetry._lifecycle import coordinator
from provide.telemetry._runtime_types import SignalDrainOutcome
from provide.telemetry.config import TelemetryConfig
from provide.telemetry.consent import _load_consent_from_env
from provide.telemetry.logger.core import _reset_logging_for_tests as _reset_logging
from provide.telemetry.logger.core import configure_logging, shutdown_logging
from provide.telemetry.tracing.provider import _refresh_otel_tracing, setup_tracing, shutdown_tracing
from provide.telemetry.tracing.provider import _reset_tracing_for_tests as _reset_tracing

_logger = logging.getLogger(__name__)


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
    """Configure telemetry once, idempotently, under the lifecycle lock.

    A repeated call returns the *active* generation's config rather than
    applying the caller's. It also declines to look at the caller's argument at
    all, which is the honest version of ignoring it: reading
    ``TelemetryConfig.from_env()`` first meant a second ``setup_telemetry()``
    could raise ``ConfigurationError`` over an environment the running process
    had already decided not to adopt.
    """
    from provide.telemetry.metrics.provider import _refresh_otel_metrics, setup_metrics
    from provide.telemetry.runtime import apply_runtime_config, get_runtime_config
    from provide.telemetry.slo import _rebind_slo_instruments, record_red_metrics, record_use_metrics

    with coordinator.operations:
        if coordinator.peek().setup_done:
            return get_runtime_config()
        cfg = config or TelemetryConfig.from_env()
        # Consent is read here, not by TelemetryConfig: PROVIDE_CONSENT_LEVEL is
        # an operator opt-out that must bind whether or not a config was passed.
        _load_consent_from_env()
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
            # Published last, once every provider is installed: the generation
            # that says setup_done is the generation whose providers exist.
            coordinator.publish_setup_state(setup_done=True)
        if cfg.slo.enable_red_metrics:
            record_red_metrics("startup", "INIT", 200, 0.0)
        if cfg.slo.enable_use_metrics:
            record_use_metrics("startup", 0)
    return cfg


def _reset_setup_state_for_tests() -> None:
    with coordinator.operations:
        coordinator.publish_setup_state(setup_done=False)


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

    with coordinator.operations:
        coordinator.publish_setup_state(setup_done=False)
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


def _drain_signal(signal: str, drain: Callable[[float], bool], deadline: float) -> SignalDrainOutcome:
    """Run one signal's drain, distinguishing a raised error from a missed deadline.

    ``bounded_provider_flush`` re-raises what ``force_flush`` raised — the right
    contract for the primitive, the wrong one for a public API called at a
    request boundary, so the exception is absorbed here. It is reported as
    ``"failed"``, not ``"timed_out"``: an exporter that raised in milliseconds
    (bad auth header, TLS failure) never timed anything out, and a caller
    alerting on the distinction must not see the two collapsed.
    """
    try:
        drained = drain(deadline)
    except Exception as exc:
        _logger.warning("telemetry.flush.signal_failed", extra={"signal": signal, "error": str(exc)})
        return "failed"
    return "flushed" if drained else "timed_out"


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

    Use :func:`flush_signals` when you need to know *which* signal failed.
    """
    return all(outcome == "flushed" for outcome in flush_signals(timeout_seconds).values())


def flush_signals(timeout_seconds: float | None = None) -> dict[str, SignalDrainOutcome]:
    """Force-flush installed providers, reporting the outcome per signal.

    The per-signal form of :func:`flush_telemetry`. The signals drain
    independently against three potentially different endpoints, so one
    unreachable collector says nothing about the other two — collapsing them to
    a single bool makes a caller re-emit or alert on records that were
    delivered. Keys are ``"logs"``, ``"traces"`` and ``"metrics"``; each value
    is ``"flushed"`` (drained in time — including a signal with no provider of
    ours, which has nothing to flush), ``"timed_out"`` (abandoned at the
    deadline) or ``"failed"`` (the flush raised).

    *timeout_seconds* bounds the call as a whole, not each signal in turn: the
    three drains run concurrently, so one unreachable collector cannot spend the
    budget the other two needed.
    """
    from provide.telemetry._provider_drain import (
        flush_logging,
        flush_metrics,
        flush_tracing,
        resolve_drain_deadline,
        run_drains_together,
    )

    deadline = resolve_drain_deadline(timeout_seconds)
    # Every signal must get its drain attempt even when another is abandoned at
    # the deadline *or* raises. Draining one after another would let a slow logs
    # endpoint deny traces and metrics theirs, and an exception escaping here
    # would break the documented contract inside a caller's request handler —
    # _drain_signal absorbs the latter.
    drained: dict[str, SignalDrainOutcome] = {}

    def _record(signal: str, drain: Callable[[float], bool]) -> Callable[[], None]:
        def _run() -> None:
            drained[signal] = _drain_signal(signal, drain, deadline)

        return _run

    run_drains_together(
        (
            _record("logs", flush_logging),
            _record("traces", flush_tracing),
            _record("metrics", flush_metrics),
        )
    )
    return drained


def shutdown_telemetry(timeout_seconds: float | None = None) -> None:
    """Flush and tear down telemetry providers and reset runtime policies.

    *timeout_seconds* bounds the whole drain-and-teardown — the part that can
    hang on an unreachable collector — and defaults to the configured
    bounded-shutdown deadline. A caller in a SIGTERM handler passes the time it
    has left so shutdown cannot overrun its termination grace period.

    The three per-signal teardowns run *concurrently* for that reason. Run in
    sequence they each take the deadline in turn, so three stalled providers
    would spend three times the grace period the caller budgeted for one.

    There is deliberately no separate pre-drain: every per-signal teardown
    runs ``force_flush`` then ``shutdown`` under the same deadline, so draining
    first would export each signal twice and roughly double the wall time
    against a slow collector.

    A drain that raises does not abort the teardown: the runtime resets always
    complete first, and the first drain error is then re-raised to the caller.
    """
    from provide.telemetry._provider_drain import run_drains_together
    from provide.telemetry.backpressure import reset_queues_for_tests as _reset_queues
    from provide.telemetry.metrics.provider import shutdown_metrics
    from provide.telemetry.resilience import reset_resilience_for_tests as _reset_resilience
    from provide.telemetry.runtime import reset_runtime_for_tests as _reset_runtime
    from provide.telemetry.sampling import reset_sampling_for_tests as _reset_sampling

    with coordinator.operations:
        # The stopped generation is published before anything is torn down. An
        # operator running get_runtime_status() *during* a teardown that is
        # hanging on an unreachable collector needs to be told telemetry is
        # stopping, not handed the config of the world being dismantled — and
        # each per-signal teardown detaches its provider before draining it, so
        # the status read never queues behind the drain either.
        coordinator.publish_setup_state(setup_done=False)
        try:
            run_drains_together(
                (
                    lambda: shutdown_tracing(timeout_seconds),
                    lambda: shutdown_metrics(timeout_seconds),
                    lambda: shutdown_logging(timeout_seconds),
                )
            )
        finally:
            # The resets are local work that must complete even when a drain
            # raised (bad auth header, TLS failure): every per-signal teardown
            # above has already detached its provider, so skipping them would
            # leave stale runtime policies behind a teardown that did happen.
            # The first drain error still propagates once cleanup is done —
            # cleanup completes first, the error is not swallowed.
            _reset_runtime()
            _reset_sampling()
            _reset_queues()
            _reset_resilience()
