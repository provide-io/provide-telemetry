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

# Ceiling on drain workers abandoned at their deadline and still running. Small
# on purpose: past a handful of stuck workers the exporter is not coming back,
# and spawning more only costs threads.
#
# Counts *abandoned* workers only — a worker still inside its deadline is
# running normally and will give its slot back. Counting those instead would
# make concurrent healthy drains (an ASGI app flushing per request against a
# collector that takes 200ms) decline each other and report a failure that did
# not happen.
#
# One budget across all three signals, because what it bounds is threads, and
# those are a process-wide resource. It is deliberately not a health signal for
# any one exporter: the signals can have three different endpoints, and a dead
# logs exporter really can spend the budget that a healthy traces drain would
# otherwise have used.
_MAX_ABANDONED_WORKERS = 8
_abandoned_lock = threading.Lock()
_abandoned_workers = 0


def _warn_drain(message: str) -> None:  # pragma: no mutate — best-effort warning emission
    """Emit an operator-facing drain warning from the caller's frame."""
    warnings.warn(message, RuntimeWarning, stacklevel=3)


def _reset_abandoned_workers_for_tests() -> None:
    """Restore the worker budget (tests that deliberately strand workers).

    Only sound once the stranded workers have actually exited: each decrements
    on its way out, so resetting underneath them drives the counter negative.
    """
    global _abandoned_workers
    with _abandoned_lock:
        _abandoned_workers = 0


def _bounded_provider_call(
    provider: object,
    timeout_seconds: float,
    methods: tuple[str, ...],
    thread_name: str,
    action: str,
    *,
    decline_when_saturated: bool,
) -> bool:
    """Call each of *methods* on *provider*, in order, under a hard deadline.

    OTel SDK's ``BatchLogRecordProcessor.force_flush(timeout_millis)`` silently
    ignores its ``timeout_millis`` parameter, and ``LoggerProvider.shutdown()``
    has no timeout parameter at all — its worker-thread join defaults to 30
    seconds. When the OTLP endpoint is unreachable, that makes the call feel
    like a hang. Running it in a daemon thread with our own deadline restores
    bounded semantics: if the thread exceeds *timeout_seconds*, it is abandoned
    (daemon threads are reclaimed by interpreter exit).

    Abandoned workers are capped when *decline_when_saturated* is set. flush is
    documented for repeated use (a request boundary, a checkpoint), so against
    an unreachable endpoint every call would otherwise strand another thread in
    the exporter's retry loop until interpreter exit — thousands within minutes
    at a few requests per second, ending in "can't start new thread" raised from
    unrelated code. Past _MAX_ABANDONED_WORKERS stranded workers we decline to
    start another and report the drain as failed, which is what it is.

    Shutdown passes *decline_when_saturated* False: it is the last chance to get
    queued records out, it runs at exit rather than per request, and declining
    it because earlier flushes stranded workers would silently drop the whole
    export queue. Its abandoned workers still count toward the budget — they sit
    in the same exporter — they just never close the gate on themselves.

    Missing or non-callable attributes are skipped. Returns True if every call
    completed in time and none of them reported failure — OTel's ``force_flush``
    returns False for an incomplete drain — and False if abandoned, declined, or
    reported incomplete. Re-raises the first exception raised by a call that
    completed.
    """
    global _abandoned_workers
    if decline_when_saturated:
        with _abandoned_lock:
            saturated = _abandoned_workers >= _MAX_ABANDONED_WORKERS
        if saturated:
            _warn_drain(  # pragma: no mutate — warning message string is non-semantic
                f"provider {action} skipped: {_MAX_ABANDONED_WORKERS} earlier drain "
                "workers are still pending against an unresponsive exporter."
            )
            return False

    error: list[BaseException] = []
    incomplete: list[str] = []
    completed = threading.Event()
    # `finished` deliberately duplicates what `completed` already carries.
    #
    # It looks redundant, and collapsing the two by publishing `completed` under
    # _abandoned_lock instead costs a real regression: the worker would then have
    # to win a process-wide lock — contended by every concurrent drain's
    # saturation check and every other worker's exit — before it could signal
    # completion. A flush that finished at 49.9ms of a 50ms budget could be
    # reported as abandoned, warn about dropped records that were exported, and
    # charge a slot. `completed` is therefore set the instant the provider calls
    # return, and `finished` is the lock-guarded flag the two sides arbitrate on.
    finished = False  # pragma: no mutate — falsy initialiser
    counted = False  # pragma: no mutate — falsy initialiser

    def _runner() -> None:
        global _abandoned_workers
        nonlocal finished
        try:
            for method in methods:
                call = getattr(provider, method, None)
                if callable(call) and call() is False:
                    # force_flush(timeout_millis) returns False when it gave up
                    # with records still queued. Dropping that on the floor
                    # would report a lossy drain as a clean one — the exact
                    # failure a caller flushing before a serverless freeze is
                    # asking about.
                    incomplete.append(method)
        except BaseException as exc:
            error.append(exc)
        finally:
            # Signalled before the lock, so a caller waiting on its deadline is
            # never held up by lock contention. See `finished` above.
            completed.set()
            with _abandoned_lock:
                finished = True
                if counted:
                    _abandoned_workers -= 1

    worker = threading.Thread(target=_runner, name=thread_name, daemon=True)
    try:
        worker.start()
    except RuntimeError:
        # "can't start new thread" — the process is at its thread limit. Nothing
        # was drained and nothing was stranded; say so rather than raising out
        # of a bool-returning drain.
        _warn_drain(  # pragma: no mutate — warning message string is non-semantic
            f"provider {action} skipped: could not start a drain worker."
        )
        return False
    if not completed.wait(timeout_seconds):
        with _abandoned_lock:
            if not finished:
                counted = True
                _abandoned_workers += 1
        _warn_drain(  # pragma: no mutate — warning message string is non-semantic
            f"provider {action} exceeded {timeout_seconds}s deadline; abandoning "
            "background flush. Records still in the export queue will be dropped."
        )
        return False
    if error:
        raise error[0]
    if incomplete:
        _warn_drain(  # pragma: no mutate — warning message string is non-semantic
            f"provider {action} reported an incomplete drain from {', '.join(incomplete)}; records may still be queued."
        )
        return False
    return True


def bounded_provider_shutdown(provider: object, timeout_seconds: float) -> bool:
    """Run ``provider.force_flush()`` then ``provider.shutdown()`` under a hard deadline.

    Returns True if both calls completed in time and the flush reported success,
    False if abandoned or the flush reported an incomplete drain. Never declines
    for want of budget: this is the last chance to get queued records out.
    Re-raises any exception raised by force_flush/shutdown when completed.
    """
    return _bounded_provider_call(
        provider,
        timeout_seconds,
        ("force_flush", "shutdown"),
        # Operator-visible thread name; asserted by test_thread_is_named_for_operator_visibility.
        "provide-provider-shutdown",
        "shutdown",
        decline_when_saturated=False,
    )


def bounded_provider_flush(provider: object, timeout_seconds: float) -> bool:
    """Run ``provider.force_flush()`` under a hard deadline, leaving it installed.

    The drain half of :func:`bounded_provider_shutdown`: the provider keeps its
    exporter and stays usable afterwards, so a caller that must know its records
    are out (before returning a response, before a serverless freeze) does not
    have to tear telemetry down to get that guarantee.

    Returns True if the flush completed in time and reported success, False if
    abandoned, declined for want of budget, or reported an incomplete drain.
    Re-raises any exception raised by force_flush when completed.
    """
    return _bounded_provider_call(
        provider,
        timeout_seconds,
        ("force_flush",),
        # Operator-visible thread name; asserted by test_flush_thread_is_named_for_operator_visibility.
        "provide-provider-flush",
        "flush",
        decline_when_saturated=True,
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
