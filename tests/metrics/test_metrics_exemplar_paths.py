# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests for exemplar attachment, sampling/backpressure drop paths in metric fallbacks."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

from provide.telemetry.backpressure import reset_queues_for_tests
from provide.telemetry.metrics import counter, gauge, histogram
from provide.telemetry.metrics import fallback as fallback_mod
from provide.telemetry.metrics import instruments as instruments_mod
from provide.telemetry.metrics.provider import _set_meter_for_test
from provide.telemetry.sampling import reset_sampling_for_tests
from provide.telemetry.tracing.context import set_trace_context


@pytest.fixture(autouse=True)
def _reset_trace_context() -> None:
    set_trace_context(None, None)
    reset_sampling_for_tests()
    reset_queues_for_tests()


def test_metric_sampling_and_backpressure_drop_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_meter_for_test(None)
    monkeypatch.setattr("provide.telemetry.metrics.fallback._should_sample_unchecked", lambda _signal, _name: False)
    c = counter("c")
    c.add(5)
    assert c.value == 0

    monkeypatch.setattr("provide.telemetry.metrics.fallback._should_sample_unchecked", lambda _signal, _name: True)
    monkeypatch.setattr("provide.telemetry.metrics.fallback._try_acquire_unchecked", lambda _signal: None)
    g = gauge("g")
    g.add(3)
    assert g.value == 0
    h = histogram("h")
    h.record(1.0)
    assert h.count == 0


def test_metric_exemplar_and_resilience_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Counter:
        def __init__(self) -> None:
            self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

        def add(self, *args: object, **kwargs: object) -> None:
            self.calls.append((args, kwargs))
            if "exemplar" in kwargs:
                raise TypeError("unsupported")

    class _Histogram:
        def __init__(self) -> None:
            self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

        def record(self, *args: object, **kwargs: object) -> None:
            self.calls.append((args, kwargs))
            if "exemplar" in kwargs:
                raise TypeError("unsupported")

    counter_impl = _Counter()
    hist_impl = _Histogram()
    c = instruments_mod.Counter("ctr", counter_impl)
    h = instruments_mod.Histogram("hist", hist_impl)
    monkeypatch.setattr("provide.telemetry.metrics.fallback._should_sample_unchecked", lambda _signal, _name: True)
    monkeypatch.setattr(
        "provide.telemetry.metrics.fallback._try_acquire_unchecked",
        lambda _signal: SimpleNamespace(signal="metrics", token=1),
    )
    monkeypatch.setattr("provide.telemetry.metrics.fallback.release", lambda _ticket: None)
    monkeypatch.setattr("provide.telemetry.metrics.fallback.get_trace_id", lambda: "a" * 32)
    monkeypatch.setattr("provide.telemetry.metrics.fallback.get_span_id", lambda: "b" * 16)
    c.add(1, {"user_id": "u1"})
    h.record(1.0, {"user_id": "u2"})
    assert len(counter_impl.calls) == 2
    assert len(hist_impl.calls) == 2


def test_metric_exemplar_supported_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Counter:
        def __init__(self) -> None:
            self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

        def add(self, *args: object, **kwargs: object) -> None:
            self.calls.append((args, kwargs))

    class _Histogram:
        def __init__(self) -> None:
            self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

        def record(self, *args: object, **kwargs: object) -> None:
            self.calls.append((args, kwargs))

    counter_impl = _Counter()
    hist_impl = _Histogram()
    c = instruments_mod.Counter("ctr", counter_impl)
    h = instruments_mod.Histogram("hist", hist_impl)
    monkeypatch.setattr("provide.telemetry.metrics.fallback._should_sample_unchecked", lambda _signal, _name: True)
    monkeypatch.setattr(
        "provide.telemetry.metrics.fallback._try_acquire_unchecked",
        lambda _signal: SimpleNamespace(signal="metrics", token=1),
    )
    monkeypatch.setattr("provide.telemetry.metrics.fallback.release", lambda _ticket: None)
    monkeypatch.setattr("provide.telemetry.metrics.fallback.get_trace_id", lambda: "a" * 32)
    monkeypatch.setattr("provide.telemetry.metrics.fallback.get_span_id", lambda: "b" * 16)
    c.add(1)
    h.record(1.0)
    counter_kwargs = cast(dict[str, Any], counter_impl.calls[0][1])
    hist_kwargs = cast(dict[str, Any], hist_impl.calls[0][1])
    assert cast(dict[str, str], counter_kwargs["exemplar"])["trace_id"] == "a" * 32
    assert cast(dict[str, str], hist_kwargs["exemplar"])["span_id"] == "b" * 16


def test_metric_exemplar_empty_context_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("provide.telemetry.metrics.fallback.get_trace_id", lambda: None)
    monkeypatch.setattr("provide.telemetry.metrics.fallback.get_span_id", lambda: None)
    assert fallback_mod._exemplar() == {}


def test_metric_early_return_branches_for_sampling_and_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "provide.telemetry.metrics.fallback._should_sample_unchecked", lambda _signal, name: name != "no-sample"
    )
    monkeypatch.setattr(
        "provide.telemetry.metrics.fallback._try_acquire_unchecked",
        lambda _signal: None,
    )

    c = instruments_mod.Counter("no-sample")
    c.add(1)
    assert c.value == 0

    g = instruments_mod.Gauge("no-sample")
    g.add(2)
    assert g.value == 0

    h = instruments_mod.Histogram("no-sample")
    h.record(3.0)
    assert h.count == 0
    c2 = instruments_mod.Counter("queue-none")
    c2.add(1)
    assert c2.value == 0
