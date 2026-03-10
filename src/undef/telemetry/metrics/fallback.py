# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Local fallback metric instrument implementations."""

from __future__ import annotations

from typing import Any


class Counter:
    def __init__(self, name: str, otel_counter: Any | None = None) -> None:
        self.name = name
        self._otel_counter = otel_counter
        self.value = 0

    def add(self, amount: int, attributes: dict[str, str] | None = None) -> None:
        self.value += amount
        if self._otel_counter is not None:
            self._otel_counter.add(amount, attributes or {})


class Gauge:
    def __init__(self, name: str, otel_gauge: Any | None = None) -> None:
        self.name = name
        self._otel_gauge = otel_gauge
        self.value = 0

    def add(self, amount: int, attributes: dict[str, str] | None = None) -> None:
        self.value += amount
        if self._otel_gauge is not None:
            self._otel_gauge.add(amount, attributes or {})


class Histogram:
    def __init__(self, name: str, otel_histogram: Any | None = None) -> None:
        self.name = name
        self._otel_histogram = otel_histogram
        self.records: list[float] = []

    def record(self, value: float, attributes: dict[str, str] | None = None) -> None:
        self.records.append(value)
        if self._otel_histogram is not None:
            self._otel_histogram.record(value, attributes or {})
