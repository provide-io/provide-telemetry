# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""PROVIDE_METRICS_HEALTH_OTLP: health series as observable instruments."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from provide.telemetry.config import TelemetryConfig
from provide.telemetry.consent import ConsentLevel, set_consent_level
from provide.telemetry.health import get_health_snapshot, increment_emitted, reset_health_for_tests
from provide.telemetry.metrics import _health_otlp
from provide.telemetry.metrics import _prom_render as render
from provide.telemetry.metrics import prometheus as prom
from provide.telemetry.metrics import provider as provider_mod
from provide.telemetry.metrics.provider import _set_meter_for_test, setup_metrics


class _Meter:
    def __init__(self) -> None:
        self.instruments: dict[str, tuple[str, Any]] = {}

    def create_observable_counter(self, name: str, *, callbacks: list[Any]) -> None:
        self.instruments[name] = ("counter", callbacks)

    def create_observable_gauge(self, name: str, *, callbacks: list[Any]) -> None:
        self.instruments[name] = ("gauge", callbacks)

    def collect(self, name: str) -> list[tuple[float, dict[str, str]]]:
        (callback,) = self.instruments[name][1]
        return list(callback(None))


def _make(value: float, labels: dict[str, str]) -> tuple[float, dict[str, str]]:
    return value, labels


@pytest.fixture(autouse=True)
def _clean() -> Any:
    _set_meter_for_test(None)
    reset_health_for_tests()
    set_consent_level(ConsentLevel.FULL)
    yield
    set_consent_level(ConsentLevel.FULL)
    _set_meter_for_test(None)


def test_registers_every_health_family_with_its_kind() -> None:
    meter = _Meter()
    _health_otlp.register(meter, _make)
    expected = {f.name: f.kind for f in prom.health_families(get_health_snapshot())}
    assert {name: kind for name, (kind, _) in meter.instruments.items()} == expected
    assert len(meter.instruments) == 11


def test_observations_follow_the_live_snapshot_without_counting_themselves() -> None:
    meter = _Meter()
    _health_otlp.register(meter, _make)
    assert meter.collect("provide_telemetry_emitted_total") == [
        (0.0, {"signal": "logs"}),
        (0.0, {"signal": "traces"}),
        (0.0, {"signal": "metrics"}),
    ]
    increment_emitted("metrics", 2)
    for _ in range(3):
        assert meter.collect("provide_telemetry_emitted_total")[2] == (2.0, {"signal": "metrics"})
    assert get_health_snapshot().emitted_metrics == 2
    assert meter.collect("provide_telemetry_circuit_state") == [
        (0.0, {"signal": "logs"}),
        (0.0, {"signal": "traces"}),
        (0.0, {"signal": "metrics"}),
    ]
    assert meter.collect("provide_telemetry_setup_error") == [(0.0, {})]
    assert meter.collect("provide_telemetry_receipt_failures_total") == [(0.0, {})]


def test_observations_are_not_consent_gated() -> None:
    meter = _Meter()
    _health_otlp.register(meter, _make)
    set_consent_level(ConsentLevel.NONE)
    assert len(meter.collect("provide_telemetry_dropped_total")) == 3


def _install(monkeypatch: pytest.MonkeyPatch) -> Mock:
    provider = Mock()
    otel = SimpleNamespace(
        set_meter_provider=Mock(),
        get_meter=Mock(return_value="meter"),
        get_meter_provider=lambda: None,
        Observation=_make,
    )
    monkeypatch.setattr(provider_mod, "_HAS_OTEL_METRICS", True)
    monkeypatch.setattr(provider_mod, "_load_otel_metrics_api", lambda: otel)
    monkeypatch.setattr(
        provider_mod,
        "_load_otel_metrics_components",
        lambda: (Mock(return_value=provider), SimpleNamespace(create=Mock(return_value="res")), Mock(), Mock()),
    )
    return provider


@pytest.mark.parametrize(("value", "registered"), [("true", True), ("false", False)])
def test_setup_registers_on_the_installed_provider(
    monkeypatch: pytest.MonkeyPatch, value: str, registered: bool
) -> None:
    provider = _install(monkeypatch)
    calls: list[tuple[Any, Any]] = []
    monkeypatch.setattr(_health_otlp, "register", lambda meter, make: calls.append((meter, make)))
    setup_metrics(TelemetryConfig.from_env({"OTEL_METRICS_EXPORTER": "none", "PROVIDE_METRICS_HEALTH_OTLP": value}))
    if registered:
        assert calls == [(provider.get_meter.return_value, _make)]
        provider.get_meter.assert_called_once_with("provide.telemetry")
    else:
        assert calls == []


def test_setup_does_not_register_when_another_setup_won(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch)
    calls: list[Any] = []
    monkeypatch.setattr(_health_otlp, "register", lambda meter, make: calls.append(meter))
    config = TelemetryConfig.from_env({"OTEL_METRICS_EXPORTER": "none", "PROVIDE_METRICS_HEALTH_OTLP": "true"})
    setup_metrics(config)
    setup_metrics(config)  # a provider is already installed: once per provider
    assert len(calls) == 1


def _data(*names: str) -> Any:
    def metric(name: str) -> Any:
        sum_data = type("Sum", (), {"is_monotonic": True, "data_points": [SimpleNamespace(value=7, attributes={})]})()
        return SimpleNamespace(name=name, unit="", description="", data=sum_data)

    scope = SimpleNamespace(scope=SimpleNamespace(name="s", version=None), metrics=[metric(n) for n in names])
    return SimpleNamespace(
        resource_metrics=[SimpleNamespace(resource=SimpleNamespace(attributes={}), scope_metrics=[scope])]
    )


def test_scrape_serves_each_health_family_once() -> None:
    class _Reader:
        def snapshot(self) -> Any:
            return _data("provide_telemetry_emitted_total", "provide_telemetry_setup_error", "app.requests")

    config = TelemetryConfig.from_env({"PROVIDE_METRICS_HEALTH_OTLP": "true"})
    prom.mark_ready(_Reader(), prom.options_for(config))
    body = prom.render_prometheus()[0].decode()
    assert body.count("# TYPE provide_telemetry_emitted_total counter") == 1
    assert body.count("# TYPE provide_telemetry_setup_error gauge") == 1
    assert "provide_telemetry_emitted_total 7" not in body  # the reader's copy is gone
    assert "app_requests_total 7" in body


def test_renderer_skip_is_by_instrument_name() -> None:
    opts = render.RenderOptions("UnderscoreEscapingWithSuffixes", skip=frozenset({"b"}))
    assert [f.name for f in render.families_from(_data("a", "b", "c"), opts)] == ["a_total", "c_total"]


_REAL_SCRIPT = """
from provide.telemetry import render_prometheus, setup_telemetry, shutdown_telemetry
from provide.telemetry.config import TelemetryConfig
from provide.telemetry.metrics import prometheus
setup_telemetry(TelemetryConfig.from_env({
    "OTEL_METRICS_EXPORTER": "prometheus", "PROVIDE_METRICS_HEALTH_OTLP": "true", "PROVIDE_TRACE_ENABLED": "false",
}))
reader = prometheus._serving[0]
names = sorted({m.name for rm in reader.snapshot().resource_metrics for sm in rm.scope_metrics for m in sm.metrics})
print(",".join(names))
print(render_prometheus()[0].decode())
shutdown_telemetry()
"""


@pytest.mark.otel
def test_real_sdk_exports_health_instruments_and_scrapes_them_once() -> None:
    pytest.importorskip("opentelemetry.sdk.metrics")
    import subprocess  # nosec B404 — fixed script, no user input
    import sys

    out = subprocess.run(  # nosec B603
        [sys.executable, "-c", _REAL_SCRIPT], capture_output=True, text=True, timeout=60, check=True
    ).stdout
    first, _, body = out.partition("\n")
    assert set(first.split(",")) >= prom.HEALTH_METRIC_NAMES
    for name in prom.HEALTH_METRIC_NAMES:
        assert body.count(f"# TYPE {name} ") == 1, name
    assert 'provide_telemetry_emitted_total{signal="metrics"}' in body
