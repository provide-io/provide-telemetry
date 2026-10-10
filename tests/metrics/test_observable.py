# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Observable instruments: registration, gates, failures and unregistering."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any, cast

import pytest

from provide.telemetry.consent import ConsentLevel, set_consent_level
from provide.telemetry.health import get_health_snapshot, reset_health_for_tests
from provide.telemetry.metrics import observable as obs
from provide.telemetry.metrics import provider as provider_mod
from provide.telemetry.metrics.provider import _set_meter_for_test


class _Observation:
    def __init__(self, value: float, attributes: dict[str, str]) -> None:
        self.value, self.attributes = value, attributes


class _OtelMetrics:
    Observation = _Observation


class _Meter:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.fail = fail

    def __getattr__(self, factory: str) -> Any:
        def create(name: str, **kwargs: Any) -> object:
            if self.fail:
                raise RuntimeError("no instrument for you")
            self.calls.append((factory, name, kwargs))
            return object()

        return create

    def collect(self) -> list[Any]:
        return [_Observation(-1.0, {})] if not self.calls else self.calls[-1][2]["callbacks"][0](None)


@pytest.fixture
def meter(monkeypatch: pytest.MonkeyPatch) -> _Meter:
    fake = _Meter()
    monkeypatch.setattr(obs, "get_meter", lambda: fake)
    monkeypatch.setattr(obs, "_load_otel_metrics_api", lambda: _OtelMetrics)
    return fake


@pytest.fixture(autouse=True)
def _clean() -> Any:
    reset_health_for_tests()
    set_consent_level(ConsentLevel.FULL)
    yield
    set_consent_level(ConsentLevel.FULL)
    _set_meter_for_test(None)


def _values(observations: Iterable[Any]) -> list[tuple[float, dict[str, str]]]:
    return [(o.value, o.attributes) for o in observations]


@pytest.mark.parametrize(
    ("register", "factory"),
    [
        (obs.observable_counter, "create_observable_counter"),
        (obs.observable_gauge, "create_observable_gauge"),
        (obs.observable_up_down_counter, "create_observable_up_down_counter"),
    ],
)
def test_registers_with_the_matching_factory(register: Any, factory: str, meter: _Meter) -> None:
    handle = register("queue.depth", lambda: [obs.Observation(3, {"queue": "a"})], "Depth", "1")
    assert handle.name == "queue.depth" and handle.registered is True
    (called, name, kwargs), *_ = meter.calls
    assert (called, name, kwargs["description"], kwargs["unit"]) == (factory, "queue.depth", "Depth", "1")
    assert len(kwargs["callbacks"]) == 1
    observations = meter.collect()
    assert _values(observations) == [(3.0, {"queue": "a"})]
    assert type(observations[0].value) is float


def test_defaults_and_attribute_free_observations(meter: _Meter) -> None:
    obs.observable_gauge("g", lambda: [obs.Observation(1.5), obs.Observation(2, {})])
    kwargs = meter.calls[0][2]
    assert (kwargs["description"], kwargs["unit"]) == ("", "")
    assert _values(meter.collect()) == [(1.5, {}), (2.0, {})]
    assert get_health_snapshot().emitted_metrics == 2


def test_attributes_are_copied(meter: _Meter) -> None:
    attributes = {"k": "v"}
    obs.observable_gauge("g", lambda: [obs.Observation(1, attributes)])
    reported = meter.collect()[0].attributes
    assert reported == attributes and reported is not attributes


def test_unregister_stops_the_callback(meter: _Meter) -> None:
    calls: list[int] = []

    def callback() -> list[obs.Observation]:
        calls.append(1)
        return [obs.Observation(1)]

    handle = obs.observable_counter("c", callback)
    assert len(meter.collect()) == 1
    handle.unregister()
    handle.unregister()  # twice is a no-op
    assert handle.registered is False
    assert meter.collect() == [] and calls == [1]


def test_without_a_provider_the_callback_never_runs(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(obs, "get_meter", lambda: None)
    monkeypatch.setattr(obs, "_load_otel_metrics_api", lambda: _OtelMetrics)
    with caplog.at_level(logging.WARNING, logger=obs.__name__):
        handle = obs.observable_gauge("g", lambda: pytest.fail("never called"))
        assert handle.registered is False
        handle.unregister()
        monkeypatch.setattr(obs, "get_meter", _Meter)
        monkeypatch.setattr(obs, "_load_otel_metrics_api", lambda: None)
        assert obs.observable_gauge("g", lambda: []).registered is False
    assert caplog.records == []  # nothing to create against is not a creation failure


def test_creation_failure_is_logged_and_returns_an_unattached_handle(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(obs, "get_meter", lambda: _Meter(fail=True))
    monkeypatch.setattr(obs, "_load_otel_metrics_api", lambda: _OtelMetrics)
    with caplog.at_level(logging.WARNING, logger=obs.__name__):
        handle = obs.observable_gauge("g", lambda: [])
    assert handle.registered is False
    (record,) = caplog.records
    assert record.message == "metrics.observable.create_failed"
    assert record.__dict__["instrument"] == "g"
    assert record.exc_info and record.exc_info[0] is RuntimeError


def test_a_failing_callback_contributes_nothing_and_warns_once(meter: _Meter, caplog: pytest.LogCaptureFixture) -> None:
    results: list[Any] = [ValueError("boom"), ValueError("again"), [obs.Observation(4)]]

    def callback() -> list[obs.Observation]:
        result = results.pop(0)
        if isinstance(result, Exception):
            raise result
        return list(result)

    obs.observable_gauge("flaky", callback)
    with caplog.at_level(logging.WARNING, logger=obs.__name__):
        assert meter.collect() == []
        assert meter.collect() == []
    assert _values(meter.collect()) == [(4.0, {})]
    (record,) = caplog.records
    assert record.message == "metrics.observable_callback_failed"
    assert record.levelno == logging.WARNING
    assert record.__dict__["instrument"] == "flaky"
    assert record.exc_info and "boom" in str(record.exc_info[1])
    assert get_health_snapshot().emitted_metrics == 1


def test_a_bad_observation_counts_as_a_failure(meter: _Meter) -> None:
    obs.observable_gauge("g", lambda: [obs.Observation(1), obs.Observation(cast(Any, "x"))])
    assert meter.collect() == []
    assert get_health_snapshot().emitted_metrics == 0


def test_consent_gates_collection(meter: _Meter, monkeypatch: pytest.MonkeyPatch) -> None:
    from provide.telemetry import consent

    obs.observable_gauge("g", lambda: [obs.Observation(1)])
    asked: list[str] = []

    def deny(signal: str) -> bool:
        asked.append(signal)
        return False

    monkeypatch.setattr(consent, "should_allow", deny)
    assert meter.collect() == [] and asked == ["metrics"]
    monkeypatch.undo()
    set_consent_level(ConsentLevel.NONE)
    assert meter.collect() == []
    set_consent_level(ConsentLevel.FULL)
    assert len(meter.collect()) == 1


def test_runtime_metrics_flag_gates_collection(meter: _Meter) -> None:
    from provide.telemetry._lifecycle import coordinator
    from provide.telemetry.config import TelemetryConfig

    obs.observable_gauge("g", lambda: [obs.Observation(1)])
    try:
        for config, expected in [
            (TelemetryConfig.from_env({"PROVIDE_METRICS_ENABLED": "false"}), 0),
            (TelemetryConfig.from_env({}), 1),
            (None, 1),
        ]:
            coordinator.publish(config, setup_done=False)
            assert len(meter.collect()) == expected
    finally:
        coordinator.reset()


def test_the_default_seams_are_the_provider_functions() -> None:
    assert vars(obs)["get_meter"] is provider_mod.get_meter
    assert vars(obs)["_load_otel_metrics_api"] is provider_mod._load_otel_metrics_api


@pytest.mark.otel
def test_observables_reach_the_real_sdk() -> None:
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import InMemoryMetricReader

    reader = InMemoryMetricReader()
    meter = MeterProvider(metric_readers=[reader]).get_meter("provide.telemetry")
    _set_meter_for_test(meter)
    provider_mod._meter_provider = object()  # get_meter() serves the cached meter only with a provider
    try:
        values = iter([5, 7])
        handle = obs.observable_counter("jobs.done", lambda: [obs.Observation(next(values), {"queue": "a"})], unit="1")
        obs.observable_gauge("temp", lambda: [obs.Observation(21.5)], unit="Cel")
        obs.observable_up_down_counter("in.flight", lambda: [obs.Observation(-2)])
        assert handle.registered

        def points() -> dict[str, list[Any]]:
            data = reader.get_metrics_data()
            assert data is not None
            return {
                m.name: list(m.data.data_points)
                for rm in data.resource_metrics
                for sm in rm.scope_metrics
                for m in sm.metrics
            }

        first = points()
        assert [p.value for p in first["jobs.done"]] == [5]
        assert dict(first["jobs.done"][0].attributes) == {"queue": "a"}
        assert [p.value for p in first["temp"]] == [21.5]
        assert [p.value for p in first["in.flight"]] == [-2]
        handle.unregister()
        assert "jobs.done" not in points() or points()["jobs.done"] == []
    finally:
        provider_mod._meter_provider = None
