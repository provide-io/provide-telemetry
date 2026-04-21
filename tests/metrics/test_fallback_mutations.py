# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests targeting surviving mutation-testing mutants in metrics/fallback.py."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from provide.telemetry.metrics import fallback as fallback_mod
from provide.telemetry.metrics.fallback import Counter, Gauge, Histogram, _exemplar


@pytest.fixture(autouse=True)
def _patch_sampling_and_backpressure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default: allow all sampling/backpressure so we test deeper logic."""
    monkeypatch.setattr(fallback_mod, "_should_sample_unchecked", lambda signal, name: True)
    monkeypatch.setattr(
        fallback_mod,
        "_try_acquire_unchecked",
        lambda signal: SimpleNamespace(signal=signal, token=1),
    )
    monkeypatch.setattr(fallback_mod, "release", lambda ticket: None)  # release is still public


# ── should_sample receives exact args ────────────────────────────────


class TestShouldSampleArgs:
    """Kill mutants that change 'metrics' to None/'XXmetricsXX'/etc."""

    def test_counter_passes_metrics_signal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[tuple[str, str]] = []

        def _spy(signal: str, name: str) -> bool:
            calls.append((signal, name))
            return True

        monkeypatch.setattr(fallback_mod, "_should_sample_unchecked", _spy)
        Counter("my.counter").add(1)
        assert calls == [("metrics", "my.counter")]

    def test_gauge_passes_metrics_signal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[tuple[str, str]] = []

        def _spy(signal: str, name: str) -> bool:
            calls.append((signal, name))
            return True

        monkeypatch.setattr(fallback_mod, "_should_sample_unchecked", _spy)
        Gauge("my.gauge").add(1)
        assert calls == [("metrics", "my.gauge")]

    def test_histogram_passes_metrics_signal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[tuple[str, str]] = []

        def _spy(signal: str, name: str) -> bool:
            calls.append((signal, name))
            return True

        monkeypatch.setattr(fallback_mod, "_should_sample_unchecked", _spy)
        Histogram("my.hist").record(1.0)
        assert calls == [("metrics", "my.hist")]


# ── try_acquire receives exact args ──────────────────────────────────


class TestTryAcquireArgs:
    def test_counter_passes_metrics_to_try_acquire(self, monkeypatch: pytest.MonkeyPatch) -> None:
        signals: list[str] = []

        def _spy(signal: str) -> SimpleNamespace:
            signals.append(signal)
            return SimpleNamespace(signal=signal, token=1)

        monkeypatch.setattr(fallback_mod, "_try_acquire_unchecked", _spy)
        Counter("c").add(1)
        assert signals == ["metrics"]

    def test_gauge_passes_metrics_to_try_acquire(self, monkeypatch: pytest.MonkeyPatch) -> None:
        signals: list[str] = []

        def _spy(signal: str) -> SimpleNamespace:
            signals.append(signal)
            return SimpleNamespace(signal=signal, token=1)

        monkeypatch.setattr(fallback_mod, "_try_acquire_unchecked", _spy)
        Gauge("g").add(1)
        assert signals == ["metrics"]

    def test_histogram_passes_metrics_to_try_acquire(self, monkeypatch: pytest.MonkeyPatch) -> None:
        signals: list[str] = []

        def _spy(signal: str) -> SimpleNamespace:
            signals.append(signal)
            return SimpleNamespace(signal=signal, token=1)

        monkeypatch.setattr(fallback_mod, "_try_acquire_unchecked", _spy)
        Histogram("h").record(1.0)
        assert signals == ["metrics"]


# ── release receives correct ticket ─────────────────────────────────


class TestReleaseArgs:
    def test_counter_releases_correct_ticket(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ticket = SimpleNamespace(signal="metrics", token=42)
        monkeypatch.setattr(fallback_mod, "_try_acquire_unchecked", lambda _: ticket)
        released: list[object] = []
        monkeypatch.setattr(fallback_mod, "release", lambda t: released.append(t))
        Counter("c").add(1)
        assert released == [ticket]
        assert released[0] is ticket  # exact object, not None

    def test_gauge_releases_correct_ticket(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ticket = SimpleNamespace(signal="metrics", token=42)
        monkeypatch.setattr(fallback_mod, "_try_acquire_unchecked", lambda _: ticket)
        released: list[object] = []
        monkeypatch.setattr(fallback_mod, "release", lambda t: released.append(t))
        Gauge("g").add(1)
        assert released == [ticket]
        assert released[0] is ticket

    def test_histogram_releases_correct_ticket(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ticket = SimpleNamespace(signal="metrics", token=42)
        monkeypatch.setattr(fallback_mod, "_try_acquire_unchecked", lambda _: ticket)
        released: list[object] = []
        monkeypatch.setattr(fallback_mod, "release", lambda t: released.append(t))
        Histogram("h").record(1.0)
        assert released == [ticket]
        assert released[0] is ticket


# ── _exemplar or→and mutation ────────────────────────────────────────


class TestExemplarOrVsAnd:
    def test_returns_empty_when_trace_id_set_but_span_id_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Kills: `trace_id is None or span_id is None` → `and`."""
        monkeypatch.setattr(fallback_mod, "get_trace_id", lambda: "a" * 32)
        monkeypatch.setattr(fallback_mod, "get_span_id", lambda: None)
        assert _exemplar() == {}

    def test_returns_empty_when_span_id_set_but_trace_id_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(fallback_mod, "get_trace_id", lambda: None)
        monkeypatch.setattr(fallback_mod, "get_span_id", lambda: "b" * 16)
        assert _exemplar() == {}

    def test_returns_both_when_both_present(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(fallback_mod, "get_trace_id", lambda: "a" * 32)
        monkeypatch.setattr(fallback_mod, "get_span_id", lambda: "b" * 16)
        result = _exemplar()
        assert result == {"trace_id": "a" * 32, "span_id": "b" * 16}


# ── OTel delegation: exact args passed ──────────────────────────────


class TestOtelDelegationArgs:
    def test_counter_otel_add_receives_exact_amount_and_attrs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(fallback_mod, "get_trace_id", lambda: None)
        monkeypatch.setattr(fallback_mod, "get_span_id", lambda: None)
        otel_counter = Mock()
        c = Counter("c", otel_counter=otel_counter)
        c.add(7, {"env": "prod"})
        otel_counter.add.assert_called_once_with(7, {"env": "prod"})

    def test_counter_otel_add_with_exemplar_receives_all_args(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(fallback_mod, "get_trace_id", lambda: "t1")
        monkeypatch.setattr(fallback_mod, "get_span_id", lambda: "s1")
        otel_counter = Mock()
        c = Counter("c", otel_counter=otel_counter)
        c.add(3, {"k": "v"})
        otel_counter.add.assert_called_once_with(3, {"k": "v"}, exemplar={"trace_id": "t1", "span_id": "s1"})

    def test_gauge_otel_add_receives_exact_amount_and_attrs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(fallback_mod, "get_trace_id", lambda: None)
        monkeypatch.setattr(fallback_mod, "get_span_id", lambda: None)
        otel_gauge = Mock()
        g = Gauge("g", otel_gauge=otel_gauge)
        g.add(5, {"region": "us"})
        otel_gauge.add.assert_called_once_with(5, {"region": "us"})

    def test_histogram_otel_record_receives_exact_value_and_attrs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(fallback_mod, "get_trace_id", lambda: None)
        monkeypatch.setattr(fallback_mod, "get_span_id", lambda: None)
        otel_hist = Mock()
        h = Histogram("h", otel_histogram=otel_hist)
        h.record(42.5, {"path": "/api"})
        otel_hist.record.assert_called_once_with(42.5, {"path": "/api"})

    def test_histogram_otel_record_with_exemplar_receives_all_args(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(fallback_mod, "get_trace_id", lambda: "t2")
        monkeypatch.setattr(fallback_mod, "get_span_id", lambda: "s2")
        otel_hist = Mock()
        h = Histogram("h", otel_histogram=otel_hist)
        h.record(9.9, {"k": "v"})
        otel_hist.record.assert_called_once_with(9.9, {"k": "v"}, exemplar={"trace_id": "t2", "span_id": "s2"})


# ── Counter/Gauge/Histogram use self.name correctly ─────────────────


class TestSelfNameUsed:
    def test_counter_uses_self_name_for_sampling(self, monkeypatch: pytest.MonkeyPatch) -> None:
        names: list[str] = []

        def _spy(_s: str, n: str) -> bool:
            names.append(n)
            return True

        monkeypatch.setattr(fallback_mod, "_should_sample_unchecked", _spy)
        Counter("specific.counter.name").add(1)
        assert names == ["specific.counter.name"]

    def test_gauge_uses_self_name_for_sampling(self, monkeypatch: pytest.MonkeyPatch) -> None:
        names: list[str] = []

        def _spy(_s: str, n: str) -> bool:
            names.append(n)
            return True

        monkeypatch.setattr(fallback_mod, "_should_sample_unchecked", _spy)
        Gauge("specific.gauge.name").add(1)
        assert names == ["specific.gauge.name"]

    def test_histogram_uses_self_name_for_sampling(self, monkeypatch: pytest.MonkeyPatch) -> None:
        names: list[str] = []

        def _spy(_s: str, n: str) -> bool:
            names.append(n)
            return True

        monkeypatch.setattr(fallback_mod, "_should_sample_unchecked", _spy)
        Histogram("specific.hist.name").record(1.0)
        assert names == ["specific.hist.name"]


class TestGaugeSet:
    def test_gauge_set_no_otel(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Gauge.set() with no OTel provider updates value without error."""
        monkeypatch.setattr(fallback_mod, "_resolve_otel_for_gauge", lambda _: None, raising=False)
        g = Gauge("g")
        g._resolved = True
        g._otel_gauge = None
        g.set(10)
        assert g.value == 10
        g.set(7)
        assert g.value == 7

    def test_gauge_set_with_otel(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Gauge.set() with OTel forwards delta to otel_gauge.add."""
        otel_gauge = Mock()
        g = Gauge("g", otel_gauge=otel_gauge)
        g.set(10)
        assert g.value == 10
        otel_gauge.add.assert_called_with(10, {})

    def test_gauge_set_evicts_oldest_when_attr_values_exceed_max(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When _attr_values exceeds _ATTR_VALUES_MAX, oldest half is evicted."""
        limit = fallback_mod._ATTR_VALUES_MAX
        monkeypatch.setattr(fallback_mod, "_resolve_otel_for_gauge", lambda _: None, raising=False)
        g = Gauge("g.evict")
        g._resolved = True
        g._otel_gauge = None
        # Populate gauge with limit+1 distinct attribute sets to trigger eviction.
        for i in range(limit + 1):
            g.set(i, attributes={"k": str(i)})
        # After eviction, only ~half of the entries should remain.
        assert len(g._attr_values) <= limit // 2 + 1


class TestGaugeAttrValuesBoundedGrowth:
    """Verify Fix 4: _attr_values does not grow unboundedly."""

    def test_attr_values_bounded_at_max(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """After inserting > _ATTR_VALUES_MAX entries, size stays <= _ATTR_VALUES_MAX."""
        from provide.telemetry.metrics.fallback import _ATTR_VALUES_MAX

        g = Gauge("g")
        g._resolved = True
        g._otel_gauge = None

        for i in range(_ATTR_VALUES_MAX + 500):
            g.set(i, {f"k{i}": f"v{i}"})

        assert len(g._attr_values) <= _ATTR_VALUES_MAX

    def test_most_recent_attrs_preserved_after_eviction(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """After eviction, the most recent attribute set is still present."""
        from provide.telemetry.metrics.fallback import _ATTR_VALUES_MAX

        g = Gauge("g")
        g._resolved = True
        g._otel_gauge = None

        for i in range(_ATTR_VALUES_MAX + 2):
            g.set(i, {f"k{i}": f"v{i}"})

        last_key = tuple(sorted({f"k{_ATTR_VALUES_MAX + 1}": f"v{_ATTR_VALUES_MAX + 1}"}.items()))
        assert last_key in g._attr_values

    def test_no_eviction_below_max(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Inserting exactly _ATTR_VALUES_MAX entries does not trigger eviction."""
        from provide.telemetry.metrics.fallback import _ATTR_VALUES_MAX

        g = Gauge("g")
        g._resolved = True
        g._otel_gauge = None

        for i in range(_ATTR_VALUES_MAX):
            g.set(i, {f"k{i}": f"v{i}"})

        assert len(g._attr_values) == _ATTR_VALUES_MAX
