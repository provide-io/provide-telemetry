# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest

from undef.telemetry.config import TelemetryConfig
from undef.telemetry.metrics import api as api_mod
from undef.telemetry.metrics import counter, gauge, histogram
from undef.telemetry.metrics import fallback as fallback_mod
from undef.telemetry.metrics import instruments as instruments_mod
from undef.telemetry.metrics import provider as provider_mod
from undef.telemetry.metrics.provider import _set_meter_for_test, get_meter, setup_metrics, shutdown_metrics


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
    assert h.records == [1.5, 2.5]


def test_metric_wrappers_with_meter() -> None:
    provider_mod._HAS_OTEL_METRICS = True
    mock_meter = Mock()
    mock_counter = Mock()
    mock_gauge = Mock()
    mock_hist = Mock()
    mock_meter.create_counter.return_value = mock_counter
    mock_meter.create_up_down_counter.return_value = mock_gauge
    mock_meter.create_histogram.return_value = mock_hist
    _set_meter_for_test(mock_meter)

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
    assert h.records == [1.0, 2.0]
    mock_counter.add.assert_any_call(1, {"k": "v"})
    mock_counter.add.assert_any_call(1, {})
    mock_gauge.add.assert_any_call(-1, {"k": "v"})
    mock_gauge.add.assert_any_call(-1, {})
    mock_hist.record.assert_any_call(1.0, {"k": "v"})
    mock_hist.record.assert_any_call(2.0, {})


def test_metric_wrapper_exceptions_fallback() -> None:
    mock_meter = Mock()
    mock_meter.create_counter.side_effect = RuntimeError("boom")
    mock_meter.create_up_down_counter.side_effect = RuntimeError("boom")
    mock_meter.create_histogram.side_effect = RuntimeError("boom")
    _set_meter_for_test(mock_meter)
    assert counter("c")._otel_counter is None
    assert gauge("g")._otel_gauge is None
    assert histogram("h")._otel_histogram is None


def test_metric_factory_calls_expected_meter_methods() -> None:
    mock_meter = Mock()
    mock_counter = Mock()
    mock_gauge = Mock()
    mock_hist = Mock()
    mock_meter.create_counter.return_value = mock_counter
    mock_meter.create_up_down_counter.return_value = mock_gauge
    mock_meter.create_histogram.return_value = mock_hist
    _set_meter_for_test(mock_meter)

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
    cfg = TelemetryConfig.from_env({"UNDEF_METRICS_ENABLED": "false"})
    setup_metrics(cfg)  # disabled

    _set_meter_for_test(None)
    monkeypatch.setattr(provider_mod, "_HAS_OTEL_METRICS", False)
    setup_metrics(TelemetryConfig())  # no otel

    _set_meter_for_test(None)
    monkeypatch.setattr(provider_mod, "_HAS_OTEL_METRICS", False)
    enabled_cfg = TelemetryConfig.from_env({"UNDEF_METRICS_ENABLED": "true"})
    setup_metrics(enabled_cfg)
    assert provider_mod._meter is None


def test_setup_metrics_short_circuits_when_otel_missing_even_if_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_meter_for_test(None)
    monkeypatch.setattr(provider_mod, "_HAS_OTEL_METRICS", False)

    def _boom_components() -> object:
        raise AssertionError("components loader should not be called")

    def _boom_api() -> object:
        raise AssertionError("api loader should not be called")

    monkeypatch.setattr(provider_mod, "_load_otel_metrics_components", _boom_components)
    monkeypatch.setattr(provider_mod, "_load_otel_metrics_api", _boom_api)
    setup_metrics(TelemetryConfig.from_env({"UNDEF_METRICS_ENABLED": "true"}))


def test_setup_metrics_with_otel(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_meter_for_test(None)
    mock_otel = SimpleNamespace(set_meter_provider=Mock(), get_meter=Mock(return_value="meter"))
    provider_cls = Mock(return_value="provider")
    resource_cls = SimpleNamespace(create=Mock(return_value="res"))
    reader_cls = Mock(return_value="reader")
    exporter_cls = Mock(return_value="exporter")
    monkeypatch.setattr(provider_mod, "_HAS_OTEL_METRICS", True)
    monkeypatch.setattr(provider_mod, "_load_otel_metrics_api", lambda: mock_otel)
    monkeypatch.setattr(
        provider_mod,
        "_load_otel_metrics_components",
        lambda: (provider_cls, resource_cls, reader_cls, exporter_cls),
    )

    cfg = TelemetryConfig.from_env({"OTEL_EXPORTER_OTLP_ENDPOINT": "http://metrics"})
    setup_metrics(cfg)
    resource_cls.create.assert_called_once_with({"service.name": "undef-service", "service.version": "0.0.0"})
    provider_cls.assert_called_once_with(resource="res", metric_readers=["reader"])
    exporter_cls.assert_called_once_with(endpoint="http://metrics", headers={}, timeout=10.0)
    reader_cls.assert_called_once_with("exporter")
    mock_otel.set_meter_provider.assert_called_once_with("provider")
    mock_otel.get_meter.assert_called_once_with("undef.telemetry")
    assert get_meter() == "meter"
    assert provider_mod._meter_provider == "provider"
    # already configured branch
    setup_metrics(cfg)


def test_get_meter_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_meter_for_test("existing")
    assert get_meter() == "existing"

    _set_meter_for_test(None)
    monkeypatch.setattr(provider_mod, "_HAS_OTEL_METRICS", False)
    assert get_meter() is None

    mock_otel = Mock()
    mock_otel.get_meter.return_value = "dynamic"
    monkeypatch.setattr(provider_mod, "_HAS_OTEL_METRICS", True)
    monkeypatch.setattr(provider_mod, "_load_otel_metrics_api", lambda: mock_otel)
    assert get_meter("x") == "dynamic"
    get_meter()
    mock_otel.get_meter.assert_any_call("undef.telemetry")
    get_meter("x")
    mock_otel.get_meter.assert_any_call("x")
    assert None not in [args[0][0] for args in mock_otel.get_meter.call_args_list]


def test_setup_metrics_without_exporter(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_meter_for_test(None)
    mock_otel = SimpleNamespace(set_meter_provider=Mock(), get_meter=Mock(return_value="m2"))
    provider_cls = Mock(return_value="provider")
    resource_cls = SimpleNamespace(create=Mock(return_value="res"))
    reader_cls = Mock(return_value="reader")
    exporter_cls = Mock(return_value="exporter")
    monkeypatch.setattr(provider_mod, "_HAS_OTEL_METRICS", True)
    monkeypatch.setattr(provider_mod, "_load_otel_metrics_api", lambda: mock_otel)
    monkeypatch.setattr(
        provider_mod,
        "_load_otel_metrics_components",
        lambda: (provider_cls, resource_cls, reader_cls, exporter_cls),
    )
    cfg = TelemetryConfig.from_env({})
    setup_metrics(cfg)
    assert get_meter() == "m2"


def test_setup_metrics_with_only_one_otel_dependency_available(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_meter_for_test(None)
    monkeypatch.setattr(provider_mod, "_HAS_OTEL_METRICS", True)
    monkeypatch.setattr(provider_mod, "_load_otel_metrics_components", lambda: None)
    monkeypatch.setattr(provider_mod, "_load_otel_metrics_api", lambda: SimpleNamespace(get_meter=Mock()))
    setup_metrics(TelemetryConfig.from_env({"UNDEF_METRICS_ENABLED": "true"}))
    assert provider_mod._meter is None

    _set_meter_for_test(None)
    components = (Mock(), SimpleNamespace(create=Mock(return_value="res")), Mock(), Mock())
    monkeypatch.setattr(provider_mod, "_load_otel_metrics_components", lambda: components)
    monkeypatch.setattr(provider_mod, "_load_otel_metrics_api", lambda: None)
    setup_metrics(TelemetryConfig.from_env({"UNDEF_METRICS_ENABLED": "true"}))
    assert provider_mod._meter is None


def test_setup_metrics_with_exporter_endpoint_but_resilience_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_meter_for_test(None)
    mock_otel = SimpleNamespace(set_meter_provider=Mock(), get_meter=Mock(return_value="meter"))
    provider_cls = Mock(return_value="provider")
    resource_cls = SimpleNamespace(create=Mock(return_value="res"))
    reader_cls = Mock(return_value="reader")
    exporter_cls = Mock(return_value="exporter")
    monkeypatch.setattr(provider_mod, "_HAS_OTEL_METRICS", True)
    monkeypatch.setattr(provider_mod, "_load_otel_metrics_api", lambda: mock_otel)
    monkeypatch.setattr(
        provider_mod,
        "_load_otel_metrics_components",
        lambda: (provider_cls, resource_cls, reader_cls, exporter_cls),
    )
    monkeypatch.setattr(provider_mod, "run_with_resilience", lambda _signal, _op: None)
    setup_metrics(TelemetryConfig.from_env({"OTEL_EXPORTER_OTLP_ENDPOINT": "http://metrics"}))
    provider_cls.assert_called_once_with(resource="res", metric_readers=[])


def test_shutdown_metrics_calls_provider_shutdown() -> None:
    provider = Mock()
    provider_mod._meter_provider = provider
    provider_mod._meter = "meter"
    shutdown_metrics()
    provider.shutdown.assert_called_once()
    assert provider_mod._meter is None
    assert provider_mod._meter_provider is None


def test_shutdown_metrics_provider_absent_and_noncallable() -> None:
    provider_mod._meter_provider = None
    provider_mod._meter = None
    shutdown_metrics()
    assert provider_mod._meter is None
    assert provider_mod._meter_provider is None

    provider_mod._meter_provider = SimpleNamespace(shutdown="nope")
    provider_mod._meter = "meter"
    shutdown_metrics()
    assert provider_mod._meter is None
    assert provider_mod._meter_provider is None

    provider_mod._meter_provider = SimpleNamespace()
    provider_mod._meter = "meter"
    shutdown_metrics()
    assert provider_mod._meter is None
    assert provider_mod._meter_provider is None


def test_set_meter_for_test_resets_provider_exactly_to_none() -> None:
    provider_mod._meter_provider = object()
    _set_meter_for_test("meter")
    assert provider_mod._meter_provider is None


def test_metric_factories_default_description_and_unit() -> None:
    mock_meter = Mock()
    mock_meter.create_counter.return_value = Mock()
    mock_meter.create_up_down_counter.return_value = Mock()
    mock_meter.create_histogram.return_value = Mock()
    _set_meter_for_test(mock_meter)

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


def test_metric_sampling_and_backpressure_drop_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_meter_for_test(None)
    monkeypatch.setattr("undef.telemetry.metrics.fallback.should_sample", lambda _signal, _name: False)
    c = counter("c")
    c.add(5)
    assert c.value == 0

    monkeypatch.setattr("undef.telemetry.metrics.fallback.should_sample", lambda _signal, _name: True)
    monkeypatch.setattr("undef.telemetry.metrics.fallback.try_acquire", lambda _signal: None)
    g = gauge("g")
    g.add(3)
    assert g.value == 0
    h = histogram("h")
    h.record(1.0)
    assert h.records == []


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
    monkeypatch.setattr("undef.telemetry.metrics.fallback.should_sample", lambda _signal, _name: True)
    monkeypatch.setattr(
        "undef.telemetry.metrics.fallback.try_acquire",
        lambda _signal: SimpleNamespace(signal="metrics", token=1),
    )
    monkeypatch.setattr("undef.telemetry.metrics.fallback.release", lambda _ticket: None)
    monkeypatch.setattr(
        "undef.telemetry.metrics.fallback.get_trace_context",
        lambda: {"trace_id": "a" * 32, "span_id": "b" * 16},
    )
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
    monkeypatch.setattr("undef.telemetry.metrics.fallback.should_sample", lambda _signal, _name: True)
    monkeypatch.setattr(
        "undef.telemetry.metrics.fallback.try_acquire",
        lambda _signal: SimpleNamespace(signal="metrics", token=1),
    )
    monkeypatch.setattr("undef.telemetry.metrics.fallback.release", lambda _ticket: None)
    monkeypatch.setattr(
        "undef.telemetry.metrics.fallback.get_trace_context",
        lambda: {"trace_id": "a" * 32, "span_id": "b" * 16},
    )
    c.add(1)
    h.record(1.0)
    counter_kwargs = cast(dict[str, Any], counter_impl.calls[0][1])
    hist_kwargs = cast(dict[str, Any], hist_impl.calls[0][1])
    assert cast(dict[str, str], counter_kwargs["exemplar"])["trace_id"] == "a" * 32
    assert cast(dict[str, str], hist_kwargs["exemplar"])["span_id"] == "b" * 16


def test_metric_exemplar_empty_context_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "undef.telemetry.metrics.fallback.get_trace_context", lambda: {"trace_id": None, "span_id": None}
    )
    assert fallback_mod._exemplar() == {}


def test_metric_early_return_branches_for_sampling_and_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("undef.telemetry.metrics.fallback.should_sample", lambda _signal, name: name != "no-sample")
    monkeypatch.setattr(
        "undef.telemetry.metrics.fallback.try_acquire",
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
    assert h.records == []

    c2 = instruments_mod.Counter("queue-none")
    c2.add(1)
    assert c2.value == 0
