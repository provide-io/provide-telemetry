# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Per-export resilience wrappers for OTel log/span/metric exporters.

The resilience layer (`resilience.py`) wraps individual export operations with
retries, timeouts, and a per-signal circuit breaker. Historically these wrappers
were only applied when the underlying exporter was *constructed*; actual
`export()` calls went straight through OTel's Batch processors with no policy
enforcement. ``ResilientExporter`` closes that gap: it delegates every attribute
to the wrapped exporter but routes ``export()`` through ``run_with_resilience``
so that retries, timeouts, and circuit-breaker state transitions match the
documented contract on every batch.
"""

from __future__ import annotations

__all__ = ["ResilientExporter", "wrap_exporter"]

from typing import Any

from provide.telemetry.resilience import run_with_resilience


def _load_failure_result(signal: str) -> Any:
    """Return the OTel FAILURE enum for *signal* (logs/traces/metrics).

    The failure enum is the canonical way to signal "this batch was dropped"
    to OTel's Batch processors. Import is lazy so this module stays usable
    when only a subset of OTel extras are installed.
    """
    if signal == "logs":
        from opentelemetry.sdk._logs.export import LogExportResult

        return LogExportResult.FAILURE
    if signal == "traces":
        from opentelemetry.sdk.trace.export import SpanExportResult

        return SpanExportResult.FAILURE
    if signal == "metrics":
        from opentelemetry.sdk.metrics.export import MetricExportResult

        return MetricExportResult.FAILURE
    raise ValueError(f"unknown signal {signal!r}")


class ResilientExporter:
    """Policy-enforcing proxy around an OTel exporter.

    Every attribute except ``export`` is forwarded to the wrapped exporter.
    ``export`` runs under ``run_with_resilience`` so retries, timeouts, and
    circuit-breaker state apply to live transport traffic — not only to the
    construction-time probe performed by each provider's setup code.
    """

    __slots__ = ("_failure_result", "_inner", "_signal")

    def __init__(self, signal: str, inner: Any, failure_result: Any | None = None) -> None:
        self._signal = signal
        self._inner = inner
        self._failure_result = failure_result if failure_result is not None else _load_failure_result(signal)

    def export(self, *args: Any, **kwargs: Any) -> Any:
        inner_export = self._inner.export
        result = run_with_resilience(self._signal, lambda: inner_export(*args, **kwargs))
        if result is None:
            # fail_open policy ran out of retries / circuit is open. Return the
            # canonical FAILURE enum so OTel's Batch processor records the drop
            # without raising inside its worker thread.
            return self._failure_result
        return result

    def shutdown(self, *args: Any, **kwargs: Any) -> Any:
        return self._inner.shutdown(*args, **kwargs)

    def force_flush(self, *args: Any, **kwargs: Any) -> Any:
        # Not every OTel exporter defines force_flush on the base class, but
        # the OTLP implementations all do. Forward unchanged.
        return self._inner.force_flush(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        # Fallback for any other attribute the OTel SDK may probe (e.g. private
        # helpers on specific exporter subclasses).
        return getattr(self._inner, name)


def wrap_exporter(signal: str, inner: Any) -> ResilientExporter:
    """Wrap *inner* so every export() call applies the *signal* resilience policy."""
    return ResilientExporter(signal, inner)
