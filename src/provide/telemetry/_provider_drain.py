# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Bounded provider lifecycle calls, and the per-signal drains built on them.

``shutdown`` tears a provider down; ``flush`` drains it and leaves it installed.
Both run under a hard deadline because the OTel SDK does not honour one itself
(see :func:`_bounded_provider_call`).
"""

from __future__ import annotations

__all__ = [
    "bounded_provider_flush",
    "bounded_provider_shutdown",
    "flush_logging",
    "flush_metrics",
    "flush_tracing",
]

import threading
import warnings


def _bounded_provider_call(
    provider: object,
    timeout_seconds: float,
    methods: tuple[str, ...],
    thread_name: str,
    action: str,
) -> bool:
    """Call each of *methods* on *provider*, in order, under a hard deadline.

    OTel SDK's ``BatchLogRecordProcessor.force_flush(timeout_millis)`` silently
    ignores its ``timeout_millis`` parameter, and ``LoggerProvider.shutdown()``
    has no timeout parameter at all — its worker-thread join defaults to 30
    seconds. When the OTLP endpoint is unreachable, that makes the call feel
    like a hang. Running it in a daemon thread with our own deadline restores
    bounded semantics: if the thread exceeds *timeout_seconds*, it is abandoned
    (daemon threads are reclaimed by interpreter exit).

    Missing or non-callable attributes are skipped. Returns True if every call
    completed in time, False if abandoned. Re-raises the first exception raised
    by a call that completed.
    """
    error: list[BaseException] = []
    completed = threading.Event()

    def _runner() -> None:
        try:
            for method in methods:
                call = getattr(provider, method, None)
                if callable(call):
                    call()
        except BaseException as exc:
            error.append(exc)
        finally:
            completed.set()

    worker = threading.Thread(target=_runner, name=thread_name, daemon=True)
    worker.start()
    if not completed.wait(timeout_seconds):
        warnings.warn(  # pragma: no mutate — best-effort warning emission; exact wording is non-semantic
            f"provider {action} exceeded {timeout_seconds}s deadline; "  # pragma: no mutate — warning message string is non-semantic
            "abandoning background flush. Records still in the export queue "  # pragma: no mutate — warning message string is non-semantic
            "will be dropped.",  # pragma: no mutate — warning message string is non-semantic
            RuntimeWarning,
            stacklevel=2,  # pragma: no mutate — stacklevel tuning; any small positive int surfaces the caller frame
        )
        return False
    if error:
        raise error[0]
    return True


def bounded_provider_shutdown(provider: object, timeout_seconds: float) -> bool:
    """Run ``provider.force_flush()`` then ``provider.shutdown()`` under a hard deadline.

    Returns True if both calls completed in time, False if abandoned.
    Re-raises any exception raised by force_flush/shutdown when completed.
    """
    return _bounded_provider_call(
        provider,
        timeout_seconds,
        ("force_flush", "shutdown"),
        # Operator-visible thread name; asserted by test_thread_is_named_for_operator_visibility.
        "provide-provider-shutdown",
        "shutdown",
    )


def bounded_provider_flush(provider: object, timeout_seconds: float) -> bool:
    """Run ``provider.force_flush()`` under a hard deadline, leaving it installed.

    The drain half of :func:`bounded_provider_shutdown`: the provider keeps its
    exporter and stays usable afterwards, so a caller that must know its records
    are out (before returning a response, before a serverless freeze) does not
    have to tear telemetry down to get that guarantee.

    Returns True if the flush completed in time, False if abandoned.
    Re-raises any exception raised by force_flush when completed.
    """
    return _bounded_provider_call(
        provider,
        timeout_seconds,
        ("force_flush",),
        # Operator-visible thread name; asserted by test_flush_thread_is_named_for_operator_visibility.
        "provide-provider-flush",
        "flush",
    )


def flush_tracing(timeout_seconds: float) -> bool:
    """Force-flush the installed tracer provider, leaving it installed and usable.

    Returns True when there is nothing to flush or the flush completed within
    *timeout_seconds*, False when the flush was abandoned at the deadline.
    """
    from provide.telemetry.tracing import provider as tracing_provider

    with tracing_provider._provider_lock:
        provider = tracing_provider._provider_ref
    if provider is None:
        return True
    return bounded_provider_flush(provider, timeout_seconds)


def flush_metrics(timeout_seconds: float) -> bool:
    """Force-flush the installed meter provider, leaving it installed and usable.

    Returns True when there is nothing to flush or the flush completed within
    *timeout_seconds*, False when the flush was abandoned at the deadline.
    """
    from provide.telemetry.metrics import provider as metrics_provider

    with metrics_provider._meter_lock:
        provider = metrics_provider._meter_provider
    if provider is None:
        return True
    return bounded_provider_flush(provider, timeout_seconds)


def flush_logging(timeout_seconds: float) -> bool:
    """Force-flush the installed OTel log provider, leaving it installed and usable.

    Returns True when there is nothing to flush or the flush completed within
    *timeout_seconds*, False when the flush was abandoned at the deadline.
    """
    from provide.telemetry.logger import core as logger_core

    with logger_core._lock:
        provider = logger_core._otel_log_provider
    if provider is None:
        return True
    return bounded_provider_flush(provider, timeout_seconds)
