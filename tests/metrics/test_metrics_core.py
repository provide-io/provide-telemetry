# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from provide.telemetry.backpressure import reset_queues_for_tests
from provide.telemetry.config import TelemetryConfig
from provide.telemetry.metrics import api as api_mod
from provide.telemetry.metrics import counter, gauge, histogram
from provide.telemetry.metrics import instruments as instruments_mod
from provide.telemetry.metrics import provider as provider_mod
from provide.telemetry.metrics.provider import _set_meter_for_test, get_meter, setup_metrics, shutdown_metrics
from provide.telemetry.sampling import reset_sampling_for_tests
from provide.telemetry.tracing.context import set_trace_context


def _fake_otel_api(**kw: Any) -> SimpleNamespace:
    kw.setdefault("get_meter_provider", lambda: None)
    return SimpleNamespace(**kw)


@pytest.fixture(autouse=True)
def _reset_trace_context() -> None:
    set_trace_context(None, None)
    reset_sampling_for_tests()
    reset_queues_for_tests()


def test_metric_wrappers_without_meter(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_meter_for_test(None)
    monkeypatch.setattr(provider_mod, "_HAS_OTEL_METRICS", False)
    c = counter("c")
    g = gauge("g")
    h = histogram("h")
    assert c.name == "c"
    assert g.name == "g"
    assert h.name == "h"
    c.add(2)
    g.add(3)
    h.record(1.5)
    c.add(1)
    g.add(-1)
    h.record(2.5)
    assert c.value == 3
    assert g.value == 2
    assert h.count == 2
    assert h.total == 4.0
    assert h.min == 1.5
    assert h.max == 2.5


def test_metric_wrappers_with_meter(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_meter = Mock()
    mock_counter = Mock()
    mock_gauge = Mock()
    mock_hist = Mock()
    mock_meter.create_counter.return_value = mock_counter
    mock_meter.create_up_down_counter.return_value = mock_gauge
    mock_meter.create_histogram.return_value = mock_hist
    _set_meter_for_test(mock_meter)
    monkeypatch.setattr(provider_mod, "_meter_provider", True)  # gate: get_meter() requires non-None provider
    # Ensure get_meter() doesn't early-exit regardless of whether OTel is installed.
    monkeypatch.setattr(provider_mod, "_load_otel_metrics_api", lambda: SimpleNamespace())

    c = counter("c", "d", "u")
    g = gauge("g", "d", "u")
    h = histogram("h", "d", "u")
    assert c.name == "c"
    assert g.name == "g"
    assert h.name == "h"
    c.add(1, {"k": "v"})
    g.add(-1, {"k": "v"})
    h.record(1.0, {"k": "v"})
    c.add(1)
    g.add(-1)
    h.record(2.0)
    assert mock_counter.add.call_count == 2
    assert mock_gauge.add.call_count == 2
    assert mock_hist.record.call_count == 2
    assert c.value == 2
    assert g.value == -2
    assert h.count == 2
    assert h.total == 3.0
    mock_counter.add.assert_any_call(1, {"k": "v"})
    mock_counter.add.assert_any_call(1, {})
    mock_gauge.add.assert_any_call(-1, {"k": "v"})
    mock_gauge.add.assert_any_call(-1, {})
    mock_hist.record.assert_any_call(1.0, {"k": "v"})
    mock_hist.record.assert_any_call(2.0, {})


def test_gauge_set_per_attribute_delta(monkeypatch: pytest.MonkeyPatch) -> None:
    """Gauge.set() must compute delta against per-attribute state, not a global scalar.

    Bug: without per-attr tracking, g.set(50, B) after g.set(100, A) computes
    delta = 50-100 = -50 and sends add(-50, B) to OTel instead of add(+50, B).
    """
    mock_meter = Mock()
    mock_otel_gauge = Mock()
    mock_meter.create_up_down_counter.return_value = mock_otel_gauge
    _set_meter_for_test(mock_meter)
    monkeypatch.setattr(provider_mod, "_meter_provider", True)
    monkeypatch.setattr(provider_mod, "_load_otel_metrics_api", lambda: SimpleNamespace())

    g = gauge("g_multiattr", "d", "u")
    g.set(100, {"container": "A"})
    g.set(50, {"container": "B"})
    g.set(200, {"container": "A"})

    # First call: A goes from 0→100, delta=+100
    mock_otel_gauge.add.assert_any_call(100, {"container": "A"})
    # Second call: B goes from 0→50, delta=+50 (was -50 before fix)
    mock_otel_gauge.add.assert_any_call(50, {"container": "B"})
    # Third call: A goes from 100→200, delta=+100
    mock_otel_gauge.add.assert_any_call(100, {"container": "A"})
    assert g.value == 250  # deltas: +100 (A) + 50 (B) + 100 (A update) = 250


def test_metric_wrapper_exceptions_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_meter = Mock()
    mock_meter.create_counter.side_effect = RuntimeError("boom")
    mock_meter.create_up_down_counter.side_effect = RuntimeError("boom")
    mock_meter.create_histogram.side_effect = RuntimeError("boom")
    _set_meter_for_test(mock_meter)
    monkeypatch.setattr(provider_mod, "_meter_provider", True)  # gate: get_meter() uses cache with mock meter
    monkeypatch.setattr(provider_mod, "_load_otel_metrics_api", lambda: SimpleNamespace())
    assert counter("c")._otel_counter is None
    assert gauge("g")._otel_gauge is None
    assert histogram("h")._otel_histogram is None


def test_metric_factory_calls_expected_meter_methods(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_meter = Mock()
    mock_counter = Mock()
    mock_gauge = Mock()
    mock_hist = Mock()
    mock_meter.create_counter.return_value = mock_counter
    mock_meter.create_up_down_counter.return_value = mock_gauge
    mock_meter.create_histogram.return_value = mock_hist
    _set_meter_for_test(mock_meter)
    monkeypatch.setattr(provider_mod, "_meter_provider", True)  # gate: get_meter() requires non-None provider
    monkeypatch.setattr(provider_mod, "_load_otel_metrics_api", lambda: SimpleNamespace())

    counter("ctr", "desc", "ms")
    gauge("gg", "desc2", "1")
    histogram("hh", "desc3", "s")

    mock_meter.create_counter.assert_called_once_with(name="ctr", description="desc", unit="ms")
    mock_meter.create_up_down_counter.assert_called_once_with(name="gg", description="desc2", unit="1")
    mock_meter.create_histogram.assert_called_once_with(name="hh", description="desc3", unit="s")


def test_metric_wrapper_no_meter_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api_mod, "get_meter", lambda: None)
    assert instruments_mod.counter("c")._otel_counter is None
    assert instruments_mod.gauge("g")._otel_gauge is None
    assert instruments_mod.histogram("h")._otel_histogram is None


def test_setup_metrics_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_meter_for_test(None)
    provider_mod._HAS_OTEL_METRICS = True
    cfg = TelemetryConfig.from_env({"PROVIDE_METRICS_ENABLED": "false"})
    setup_metrics(cfg)  # disabled

    _set_meter_for_test(None)
    monkeypatch.setattr(provider_mod, "_HAS_OTEL_METRICS", False)
    setup_metrics(TelemetryConfig())  # no otel

    _set_meter_for_test(None)
    monkeypatch.setattr(provider_mod, "_HAS_OTEL_METRICS", False)
    enabled_cfg = TelemetryConfig.from_env({"PROVIDE_METRICS_ENABLED": "true"})
    setup_metrics(enabled_cfg)
    assert provider_mod._meters.get("provide.telemetry") is None


def test_setup_metrics_short_circuits_when_otel_missing_even_if_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_meter_for_test(None)
    monkeypatch.setattr(provider_mod, "_HAS_OTEL_METRICS", False)

    def _boom_components() -> object:
        raise AssertionError("components loader should not be called")

    def _boom_api() -> object:
        raise AssertionError("api loader should not be called")

    monkeypatch.setattr(provider_mod, "_load_otel_metrics_components", _boom_components)
    monkeypatch.setattr(provider_mod, "_load_otel_metrics_api", _boom_api)
    setup_metrics(TelemetryConfig.from_env({"PROVIDE_METRICS_ENABLED": "true"}))


def test_setup_metrics_with_otel(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_meter_for_test(None)
    mock_otel = _fake_otel_api(set_meter_provider=Mock(), get_meter=Mock(return_value="meter"))
    provider_cls = Mock(return_value="provider")
    resource_cls = SimpleNamespace(create=Mock(return_value="res"))
    reader_cls = Mock(return_value="reader")
    exporter_cls = Mock(return_value="exporter")
    monkeypatch.setattr(provider_mod, "_HAS_OTEL_METRICS", True)
    monkeypatch.setattr(provider_mod, "_load_otel_metrics_api", lambda: mock_otel)
    monkeypatch.setattr(
        provider_mod, "_load_otel_metrics_components", lambda: (provider_cls, resource_cls, reader_cls, exporter_cls)
    )
    # Bypass resilience layer to avoid mutmut trampoline interference during clean test
    monkeypatch.setattr(provider_mod, "run_with_resilience", lambda _sig, op: op())
    cfg = TelemetryConfig.from_env({"OTEL_EXPORTER_OTLP_ENDPOINT": "http://metrics"})
    setup_metrics(cfg)
    resource_cls.create.assert_called_once_with({"service.name": "provide-service", "service.version": "0.0.0"})
    provider_cls.assert_called_once_with(resource="res", metric_readers=["reader"])
    exporter_cls.assert_called_once_with(endpoint="http://metrics", headers={}, timeout=10.0)
    reader_cls.assert_called_once_with("exporter")
    mock_otel.set_meter_provider.assert_called_once_with("provider")
    mock_otel.get_meter.assert_called_once_with("provide.telemetry")
    assert get_meter() == "meter"
    assert provider_mod._meter_provider == "provider"
    setup_metrics(cfg)  # already configured branch


def test_get_meter_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_meter_for_test("existing")
    monkeypatch.setattr(provider_mod, "_meter_provider", True)
    monkeypatch.setattr(provider_mod, "_load_otel_metrics_api", lambda: SimpleNamespace())
    assert get_meter() == "existing"

    # Reset API patch so subsequent sub-tests exercise the no-API paths.
    monkeypatch.setattr(provider_mod, "_load_otel_metrics_api", lambda: None)
    _set_meter_for_test(None)
    monkeypatch.setattr(provider_mod, "_HAS_OTEL_METRICS", False)
    assert get_meter() is None

    # Provider set but OTel API unavailable → fallback return None
    _set_meter_for_test(None)
    monkeypatch.setattr(provider_mod, "_meter_provider", True)
    monkeypatch.setattr(provider_mod, "_HAS_OTEL_METRICS", False)
    assert get_meter("no_api") is None

    mock_otel = Mock()
    mock_otel.get_meter.return_value = "dynamic"
    monkeypatch.setattr(provider_mod, "_HAS_OTEL_METRICS", True)
    monkeypatch.setattr(provider_mod, "_meter_provider", True)
    monkeypatch.setattr(provider_mod, "_load_otel_metrics_api", lambda: mock_otel)
    assert get_meter("x") == "dynamic"
    get_meter()
    mock_otel.get_meter.assert_any_call("provide.telemetry")
    get_meter("x")
    mock_otel.get_meter.assert_any_call("x")
    assert None not in [args[0][0] for args in mock_otel.get_meter.call_args_list]


def test_setup_metrics_without_exporter(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_meter_for_test(None)
    mock_otel = _fake_otel_api(set_meter_provider=Mock(), get_meter=Mock(return_value="m2"))
    provider_cls = Mock(return_value="provider")
    resource_cls = SimpleNamespace(create=Mock(return_value="res"))
    reader_cls = Mock(return_value="reader")
    exporter_cls = Mock(return_value="exporter")
    monkeypatch.setattr(provider_mod, "_HAS_OTEL_METRICS", True)
    monkeypatch.setattr(provider_mod, "_load_otel_metrics_api", lambda: mock_otel)
    monkeypatch.setattr(
        provider_mod, "_load_otel_metrics_components", lambda: (provider_cls, resource_cls, reader_cls, exporter_cls)
    )
    setup_metrics(TelemetryConfig.from_env({}))
    assert get_meter() == "m2"


def test_setup_metrics_with_only_one_otel_dependency_available(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_meter_for_test(None)
    monkeypatch.setattr(provider_mod, "_HAS_OTEL_METRICS", True)
    monkeypatch.setattr(provider_mod, "_load_otel_metrics_components", lambda: None)
    monkeypatch.setattr(
        provider_mod,
        "_load_otel_metrics_api",
        lambda: _fake_otel_api(get_meter=Mock()),
    )
    setup_metrics(TelemetryConfig.from_env({"PROVIDE_METRICS_ENABLED": "true"}))
    assert provider_mod._meters.get("provide.telemetry") is None

    _set_meter_for_test(None)
    components = (Mock(), SimpleNamespace(create=Mock(return_value="res")), Mock(), Mock())
    monkeypatch.setattr(provider_mod, "_load_otel_metrics_components", lambda: components)
    monkeypatch.setattr(provider_mod, "_load_otel_metrics_api", lambda: None)
    setup_metrics(TelemetryConfig.from_env({"PROVIDE_METRICS_ENABLED": "true"}))
    assert provider_mod._meters.get("provide.telemetry") is None


def test_setup_metrics_with_exporter_endpoint_but_resilience_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_meter_for_test(None)
    mock_otel = _fake_otel_api(set_meter_provider=Mock(), get_meter=Mock(return_value="meter"))
    provider_cls = Mock(return_value="provider")
    resource_cls = SimpleNamespace(create=Mock(return_value="res"))
    reader_cls = Mock(return_value="reader")
    exporter_cls = Mock(return_value="exporter")
    monkeypatch.setattr(provider_mod, "_HAS_OTEL_METRICS", True)
    monkeypatch.setattr(provider_mod, "_load_otel_metrics_api", lambda: mock_otel)
    monkeypatch.setattr(
        provider_mod, "_load_otel_metrics_components", lambda: (provider_cls, resource_cls, reader_cls, exporter_cls)
    )
    monkeypatch.setattr(provider_mod, "run_with_resilience", lambda _s, _o: None)
    setup_metrics(TelemetryConfig.from_env({"OTEL_EXPORTER_OTLP_ENDPOINT": "http://metrics"}))
    provider_cls.assert_called_once_with(resource="res", metric_readers=[])


def test_shutdown_metrics_calls_provider_shutdown() -> None:
    provider = Mock()
    provider_mod._meter_provider = provider
    provider_mod._meters["provide.telemetry"] = "meter"
    shutdown_metrics()
    provider.shutdown.assert_called_once()
    assert provider_mod._meters.get("provide.telemetry") is None
    assert provider_mod._meter_provider is None


def test_shutdown_metrics_provider_absent_and_noncallable() -> None:
    provider_mod._meter_provider = None
    provider_mod._meters.clear()
    shutdown_metrics()
    assert provider_mod._meters.get("provide.telemetry") is None
    assert provider_mod._meter_provider is None

    provider_mod._meter_provider = SimpleNamespace(shutdown="nope")
    provider_mod._meters["provide.telemetry"] = "meter"
    shutdown_metrics()
    assert provider_mod._meters.get("provide.telemetry") is None
    assert provider_mod._meter_provider is None

    provider_mod._meter_provider = SimpleNamespace()
    provider_mod._meters["provide.telemetry"] = "meter"
    shutdown_metrics()
    assert provider_mod._meters.get("provide.telemetry") is None
    assert provider_mod._meter_provider is None


def test_invalid_backpressure_signal_raises() -> None:
    from provide.telemetry.backpressure import QueueTicket, release, try_acquire

    with pytest.raises(ValueError, match="unknown signal"):
        try_acquire("trace")
    with pytest.raises(ValueError, match="unknown signal"):
        release(QueueTicket(signal="trace", token=1))


def test_set_meter_for_test_resets_provider_exactly_to_none() -> None:
    provider_mod._meter_provider = object()
    _set_meter_for_test("meter")
    assert provider_mod._meter_provider is None


def test_get_meter_caches_by_name(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_meter_for_test(None)
    monkeypatch.setattr(provider_mod, "_meter_provider", True)  # gate: get_meter() requires non-None provider
    mock_otel = Mock()
    mock_otel.get_meter.side_effect = lambda name: f"meter-{name}"
    monkeypatch.setattr(provider_mod, "_HAS_OTEL_METRICS", True)
    monkeypatch.setattr(provider_mod, "_load_otel_metrics_api", lambda: mock_otel)
    # Default meter
    m1 = get_meter()
    assert m1 == "meter-provide.telemetry"
    # Custom meter is different
    m2 = get_meter("custom")
    assert m2 == "meter-custom"
    assert m1 != m2


def test_metric_factories_default_description_and_unit(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_meter = Mock()
    mock_meter.create_counter.return_value = Mock()
    mock_meter.create_up_down_counter.return_value = Mock()
    mock_meter.create_histogram.return_value = Mock()
    _set_meter_for_test(mock_meter)
    monkeypatch.setattr(provider_mod, "_meter_provider", True)  # gate: get_meter() requires non-None provider
    monkeypatch.setattr(provider_mod, "_load_otel_metrics_api", lambda: SimpleNamespace())

    c = counter("ctr")
    g = gauge("gg")
    h = histogram("hh")

    assert c.name == "ctr"
    assert g.name == "gg"
    assert h.name == "hh"
    mock_meter.create_counter.assert_called_once_with(name="ctr", description="", unit="")
    mock_meter.create_up_down_counter.assert_called_once_with(name="gg", description="", unit="")
    mock_meter.create_histogram.assert_called_once_with(name="hh", description="", unit="")
    assert provider_mod.get_meter.__defaults__ == (None,)
    assert instruments_mod.counter.__defaults__ == (None, None)
    assert instruments_mod.gauge.__defaults__ == (None, None)
    assert instruments_mod.histogram.__defaults__ == (None, None)


def test_metric_exception_fallback_preserves_name() -> None:
    meter = Mock()
    meter.create_counter.side_effect = RuntimeError("x")
    meter.create_up_down_counter.side_effect = RuntimeError("x")
    meter.create_histogram.side_effect = RuntimeError("x")
    _set_meter_for_test(meter)
    assert counter("c").name == "c"
    assert gauge("g").name == "g"
    assert histogram("h").name == "h"
