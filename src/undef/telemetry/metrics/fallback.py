# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Local fallback metric instrument implementations."""

from __future__ import annotations

from typing import Any

from undef.telemetry.backpressure import release, try_acquire
from undef.telemetry.cardinality import guard_attributes
from undef.telemetry.health import increment_exemplar_unsupported
from undef.telemetry.resilience import run_with_resilience
from undef.telemetry.sampling import should_sample
from undef.telemetry.tracing.context import get_trace_context


def _exemplar() -> dict[str, str]:
    trace_ctx = get_trace_context()
    trace_id = trace_ctx.get("trace_id")
    span_id = trace_ctx.get("span_id")
    if trace_id is None or span_id is None:
        return {}
    return {"trace_id": trace_id, "span_id": span_id}


class Counter:
    def __init__(self, name: str, otel_counter: Any | None = None) -> None:
        self.name = name
        self._otel_counter = otel_counter
        self.value = 0

    def add(self, amount: int, attributes: dict[str, str] | None = None) -> None:
        if not should_sample("metrics", self.name):
            return
        ticket = try_acquire("metrics")
        if ticket is None:
            return
        try:
            self.value += amount
            otel_counter = self._otel_counter
            if otel_counter is not None:
                attrs = guard_attributes(attributes or {})

                def _send() -> None:
                    exemplar = _exemplar()
                    if exemplar:
                        try:
                            otel_counter.add(amount, attrs, exemplar=exemplar)
                            return
                        except TypeError:
                            increment_exemplar_unsupported()
                    otel_counter.add(amount, attrs)

                run_with_resilience("metrics", _send)
        finally:
            release(ticket)


class Gauge:
    def __init__(self, name: str, otel_gauge: Any | None = None) -> None:
        self.name = name
        self._otel_gauge = otel_gauge
        self.value = 0

    def add(self, amount: int, attributes: dict[str, str] | None = None) -> None:
        if not should_sample("metrics", self.name):
            return
        ticket = try_acquire("metrics")
        if ticket is None:
            return
        try:
            self.value += amount
            otel_gauge = self._otel_gauge
            if otel_gauge is not None:
                attrs = guard_attributes(attributes or {})
                run_with_resilience("metrics", lambda: otel_gauge.add(amount, attrs))
        finally:
            release(ticket)


class Histogram:
    def __init__(self, name: str, otel_histogram: Any | None = None) -> None:
        self.name = name
        self._otel_histogram = otel_histogram
        self.records: list[float] = []

    def record(self, value: float, attributes: dict[str, str] | None = None) -> None:
        if not should_sample("metrics", self.name):
            return
        ticket = try_acquire("metrics")
        if ticket is None:
            return
        try:
            self.records.append(value)
            otel_histogram = self._otel_histogram
            if otel_histogram is not None:
                attrs = guard_attributes(attributes or {})

                def _send() -> None:
                    exemplar = _exemplar()
                    if exemplar:
                        try:
                            otel_histogram.record(value, attrs, exemplar=exemplar)
                            return
                        except TypeError:
                            increment_exemplar_unsupported()
                    otel_histogram.record(value, attrs)

                run_with_resilience("metrics", _send)
        finally:
            release(ticket)
