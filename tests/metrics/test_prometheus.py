# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""The Prometheus pull path: status, health families, rendering and the handler.

Everything here runs without the otel extra: the reader base and the OTel
components are stand-ins. The otel-marked test at the end drives the real SDK
through setup_telemetry.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest
import yaml

from provide.telemetry import _otel as otel_helpers
from provide.telemetry.config import MetricsConfig, PrometheusConfig, TelemetryConfig
from provide.telemetry.exceptions import TelemetryError
from provide.telemetry.health import HealthSnapshot
from provide.telemetry.metrics import _prom_render as render
from provide.telemetry.metrics import prometheus as prom
from provide.telemetry.metrics import provider as provider_mod
from provide.telemetry.metrics.provider import _set_meter_for_test, setup_metrics, shutdown_metrics


def _repo_root() -> Path:
    """The directory holding VERSION; mutmut runs these tests from a copy under mutants/."""
    return next(p for p in Path(__file__).resolve().parents if (p / "VERSION").exists())


_FIXTURES: dict[str, Any] = yaml.safe_load(
    (_repo_root() / "spec" / "prometheus_fixtures.yaml").read_text(encoding="utf-8")
)


@pytest.fixture(autouse=True)
def _reset() -> Any:
    _set_meter_for_test(None)
    yield
    _set_meter_for_test(None)


class _FakeBase:
    """Stands in for the SDK's MetricReader: collect() feeds _receive_metrics."""

    data: Any = None

    def __init__(self) -> None:
        self.collected = 0

    def collect(self) -> None:
        self.collected += 1
        self._receive_metrics(self.data)

    def _receive_metrics(self, metrics_data: Any) -> None:  # overridden by the pull reader
        raise NotImplementedError


def _snapshot(values: dict[str, Any]) -> HealthSnapshot:
    full: dict[str, Any] = dict.fromkeys(HealthSnapshot._fields, 0)
    full.update(dict.fromkeys((k for k in full if k.startswith("circuit_state_")), "closed"))
    full["setup_error"] = None
    full.update(values)
    return HealthSnapshot(**full)


# ── status and reasons ──────────────────────────────────────────────────────


@pytest.mark.parametrize("status", sorted(set(prom.REASONS)))
def test_every_non_ready_status_is_a_503_naming_its_reason(status: str) -> None:
    prom.set_status(status)
    with pytest.raises(TelemetryError) as excinfo:
        prom.render_prometheus()
    assert str(excinfo.value) == prom.REASONS[status]
    code, headers, body = prom.response_for("GET", None)
    assert (code, body) == (503, f"{prom.REASONS[status]}\n".encode())
    assert headers == [(b"content-type", b"text/plain; charset=utf-8")]


def test_reasons_cover_the_fixture_states() -> None:
    states = {c["state"] for c in _FIXTURES["handler_status"]}
    mapping = {"not_set_up": prom.NOT_SET_UP, "shut_down": prom.SHUT_DOWN, "metrics_disabled": prom.METRICS_DISABLED}
    mapping |= {"host_provider": prom.HOST_PROVIDER, "ready": prom.READY}
    assert states == set(mapping)
    assert {mapping[s] for s in states} - {prom.READY} <= set(prom.REASONS)


def test_ready_reader_serves_metrics_and_health() -> None:
    reader = prom.pull_reader_class(_FakeBase)()
    prom.mark_ready(reader, render.RenderOptions("UnderscoreEscapingWithSuffixes"))
    body, content_type = prom.render_prometheus()
    assert content_type == render.CONTENT_TYPE_TEXT
    assert 'provide_telemetry_emitted_total{signal="metrics"}' in body.decode()
    assert reader.collected == 1
    _, utf8_type = prom.render_prometheus("text/plain;version=1.0.0;escaping=allow-utf-8")
    assert utf8_type == render.CONTENT_TYPE_UTF8


def test_set_status_forgets_the_reader() -> None:
    prom.mark_ready(prom.pull_reader_class(_FakeBase)(), render.RenderOptions("NoTranslation"))
    prom.set_status(prom.SHUT_DOWN)
    with pytest.raises(TelemetryError, match="shut down"):
        prom.render_prometheus()


def test_pull_reader_keeps_the_latest_collection_and_clears_on_shutdown() -> None:
    reader = prom.pull_reader_class(_FakeBase)()
    reader.data = "metrics-data"
    assert reader.snapshot() == "metrics-data"
    reader.shutdown()
    assert reader._latest is None


def test_options_for_reads_the_prometheus_config() -> None:
    config = TelemetryConfig(
        metrics=MetricsConfig(
            prometheus=PrometheusConfig(translation="NoTranslation", scope_labels=True, target_info=False)
        )
    )
    assert prom.options_for(config) == render.RenderOptions("NoTranslation", scope_labels=True, target_info=False)


# ── health families ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("case", _FIXTURES["health_metrics"], ids=lambda c: c["id"])
def test_health_families_match_the_fixture(case: dict[str, Any]) -> None:
    values = {**_FIXTURES["health_metrics"][0]["snapshot"], **(case.get("snapshot_overrides") or {})}
    families = prom.health_families(_snapshot(values))
    got = {(f.name, tuple(sorted(labels.items()))): value for f in families for _, labels, value in f.samples}
    for want in case["expected_samples"]:
        key = (want["metric"], tuple(sorted(want["labels"].items())))
        assert got[key] == float(want["value"]), key
    if case["id"] == "full_snapshot":
        assert len(got) == len(case["expected_samples"])


def test_health_family_types_and_unknown_circuit_state() -> None:
    families = {f.name: f for f in prom.health_families(_snapshot({"circuit_state_logs": "weird"}))}
    assert families["provide_telemetry_circuit_state"].samples[0] == ("", {"signal": "logs"}, -1.0)
    assert families["provide_telemetry_export_latency_milliseconds"].kind == "gauge"
    assert families["provide_telemetry_emitted_total"].kind == "counter"
    assert families["provide_telemetry_setup_error"].kind == "gauge"
    assert families["provide_telemetry_setup_error"].samples == [("", {}, 0.0)]
    assert families["provide_telemetry_receipt_failures_total"].kind == "counter"
    assert families["provide_telemetry_receipt_failures_total"].samples == [("", {}, 0.0)]
    assert all(suffix == "" for f in families.values() for suffix, _, _ in f.samples)


# ── the handler ─────────────────────────────────────────────────────────────


def test_response_for_methods() -> None:
    prom.mark_ready(prom.pull_reader_class(_FakeBase)(), render.RenderOptions("UnderscoreEscapingWithSuffixes"))
    assert prom.response_for("POST", None) == (
        405,
        [(b"allow", b"GET, HEAD"), (b"content-type", b"text/plain; charset=utf-8")],
        b"method not allowed\n",
    )
    head = prom.response_for("HEAD", None)
    assert head[0] == 200 and head[2] == b""
    assert head[1] == [(b"content-type", render.CONTENT_TYPE_TEXT.encode())]
    assert prom.response_for("GET", None)[2].startswith(b"# TYPE provide_telemetry")


def _call(app: Any, scope: dict[str, Any]) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request"}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    return sent


def test_asgi_app_serves_and_negotiates() -> None:
    prom.mark_ready(prom.pull_reader_class(_FakeBase)(), render.RenderOptions("UnderscoreEscapingWithSuffixes"))
    app = prom.metrics_handler()
    sent = _call(app, {"type": "http", "method": "GET", "headers": [(b"accept", b"text/plain;escaping=allow-utf-8")]})
    assert sent[0]["type"] == "http.response.start" and sent[0]["status"] == 200
    assert sent[0]["headers"] == [(b"content-type", render.CONTENT_TYPE_UTF8.encode())]
    assert sent[1]["type"] == "http.response.body" and b"provide_telemetry_" in sent[1]["body"]
    plain = _call(app, {"type": "http", "method": "GET"})
    assert plain[0]["headers"] == [(b"content-type", render.CONTENT_TYPE_TEXT.encode())]


def test_asgi_app_passes_the_method_and_tolerates_odd_accept_bytes() -> None:
    prom.mark_ready(prom.pull_reader_class(_FakeBase)(), render.RenderOptions("UnderscoreEscapingWithSuffixes"))
    app = prom.metrics_handler()
    assert _call(app, {"type": "http", "method": "POST"})[0]["status"] == 405
    sent = _call(
        app, {"type": "http", "method": "GET", "headers": [(b"accept", b"text/plain;escaping=allow-utf-8, \xff")]}
    )
    assert sent[0]["status"] == 200
    assert sent[0]["headers"] == [(b"content-type", render.CONTENT_TYPE_UTF8.encode())]


def test_scrape_options_pass_through_to_the_renderer() -> None:
    reader = prom.pull_reader_class(_FakeBase)()
    reader.data = _metrics_data()
    prom.mark_ready(reader, render.RenderOptions("NoTranslation", scope_labels=True, target_info=False))
    utf8_body = prom.render_prometheus("text/plain;escaping=allow-utf-8")[0].decode()
    assert '{"app.requests",otel_scope_name="s"} 2' in utf8_body
    assert "target_info" not in utf8_body
    escaped_body = prom.render_prometheus()[0].decode()
    assert 'app_requests{otel_scope_name="s"} 2' in escaped_body


def _metrics_data() -> Any:
    sum_data = type("Sum", (), {"is_monotonic": True, "data_points": [SimpleNamespace(value=2, attributes={})]})()
    metric = SimpleNamespace(name="app.requests", unit="", description="", data=sum_data)
    scope = SimpleNamespace(scope=SimpleNamespace(name="s", version=None), metrics=[metric])
    return SimpleNamespace(
        resource_metrics=[
            SimpleNamespace(resource=SimpleNamespace(attributes={"service.name": "x"}), scope_metrics=[scope])
        ]
    )


def test_asgi_app_defaults_to_get_and_ignores_other_scopes() -> None:
    prom.set_status(prom.NOT_SET_UP)
    app = prom.metrics_handler()
    assert _call(app, {"type": "http"})[0]["status"] == 503
    assert _call(app, {"type": "lifespan"}) == []


# ── setup_metrics integration (stand-in OTel components) ────────────────────


def _install(monkeypatch: pytest.MonkeyPatch, *, live_host: bool = False, base: Any = _FakeBase) -> Mock:
    provider_cls = Mock(return_value=Mock())
    otel = SimpleNamespace(
        set_meter_provider=Mock(),
        get_meter=Mock(return_value="meter"),
        get_meter_provider=lambda: "host" if live_host else None,
    )
    monkeypatch.setattr(provider_mod, "_HAS_OTEL_METRICS", True)
    monkeypatch.setattr(provider_mod, "_load_otel_metrics_api", lambda: otel)
    monkeypatch.setattr(
        provider_mod,
        "_load_otel_metrics_components",
        lambda: (provider_cls, SimpleNamespace(create=Mock(return_value="res")), Mock(), Mock()),
    )
    monkeypatch.setattr(otel_helpers, "is_live_provider", lambda p: p == "host")
    monkeypatch.setattr(otel_helpers, "load_metric_reader_base", lambda: base)
    return provider_cls


def _config(**env: str) -> TelemetryConfig:
    return TelemetryConfig.from_env(env)


def _status() -> str:
    return prom._status


def test_setup_attaches_the_pull_reader_and_marks_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    provider_cls = _install(monkeypatch)
    setup_metrics(_config(OTEL_METRICS_EXPORTER="prometheus", PROVIDE_METRICS_PROMETHEUS_TRANSLATION="NoTranslation"))
    readers = provider_cls.call_args.kwargs["metric_readers"]
    assert len(readers) == 1 and isinstance(readers[0], _FakeBase)
    assert _status() == prom.READY
    assert prom._serving == (readers[0], render.RenderOptions("NoTranslation"))
    shutdown_metrics(timeout_seconds=0.1)
    assert _status() == prom.SHUT_DOWN


@pytest.mark.parametrize(
    ("env", "kwargs", "status"),
    [
        ({}, {}, prom.NOT_SELECTED),
        ({"OTEL_METRICS_EXPORTER": "prometheus"}, {"live_host": True}, prom.HOST_PROVIDER),
        ({"OTEL_METRICS_EXPORTER": "prometheus"}, {"base": None}, prom.OTEL_MISSING),
        ({"OTEL_METRICS_EXPORTER": "prometheus", "PROVIDE_METRICS_ENABLED": "false"}, {}, prom.METRICS_DISABLED),
    ],
    ids=["not-selected", "host-provider", "no-reader-base", "metrics-disabled"],
)
def test_setup_records_why_it_cannot_serve(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str], kwargs: dict[str, Any], status: str
) -> None:
    provider_cls = _install(monkeypatch, **kwargs)
    setup_metrics(_config(**env))
    assert _status() == status
    if status != prom.METRICS_DISABLED:
        assert provider_cls.call_args.kwargs["metric_readers"] == []


@pytest.mark.parametrize(
    ("exporter", "status"), [("prometheus", prom.OTEL_MISSING), ("otlp", prom.NOT_SELECTED)], ids=["asked", "not-asked"]
)
def test_setup_without_the_sdk(monkeypatch: pytest.MonkeyPatch, exporter: str, status: str) -> None:
    monkeypatch.setattr(provider_mod, "_HAS_OTEL_METRICS", False)
    setup_metrics(_config(OTEL_METRICS_EXPORTER=exporter))
    assert _status() == status


def test_otlp_exporter_failure_is_setup_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch)
    monkeypatch.setattr(provider_mod, "run_with_resilience", lambda signal, op: None)
    setup_metrics(
        _config(OTEL_METRICS_EXPORTER="otlp,prometheus", OTEL_EXPORTER_OTLP_METRICS_ENDPOINT="http://c:4318/v1/metrics")
    )
    assert _status() == prom.SETUP_FAILED


def test_otlp_not_selected_builds_no_otlp_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    provider_cls = _install(monkeypatch)
    setup_metrics(
        _config(OTEL_METRICS_EXPORTER="prometheus", OTEL_EXPORTER_OTLP_METRICS_ENDPOINT="http://c:4318/v1/metrics")
    )
    readers = provider_cls.call_args.kwargs["metric_readers"]
    assert [type(r) for r in readers] == [type(readers[0])] and isinstance(readers[0], _FakeBase)


def test_reset_returns_to_not_set_up() -> None:
    prom.set_status(prom.READY)
    _set_meter_for_test(None)
    assert _status() == prom.NOT_SET_UP


def test_setup_after_our_own_earlier_provider_is_process_locked(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, live_host=True)
    monkeypatch.setattr(provider_mod, "_meter_global_set", True)
    setup_metrics(_config(OTEL_METRICS_EXPORTER="prometheus"))
    assert _status() == prom.PROCESS_LOCKED


_E2E_SCRIPT = """
from provide.telemetry import counter, gauge, render_prometheus, setup_telemetry, shutdown_telemetry
from provide.telemetry.config import TelemetryConfig
setup_telemetry(TelemetryConfig.from_env({"OTEL_METRICS_EXPORTER": "prometheus", "PROVIDE_TRACE_ENABLED": "false"}))
counter("real.e2e.requests").add(3, {"route": "/a"})
gauge("real.e2e.cpu", unit="1").set(1)
body, content_type = render_prometheus()
print(content_type)
print(body.decode())
shutdown_telemetry()
"""


@pytest.mark.otel
def test_real_sdk_end_to_end() -> None:
    """In a fresh process: OpenTelemetry sets the global MeterProvider once per process."""
    import subprocess  # nosec B404 — fixed script, no user input
    import sys

    out = subprocess.run(  # nosec B603
        [sys.executable, "-c", _E2E_SCRIPT], capture_output=True, text=True, timeout=60, check=True
    ).stdout
    assert out.splitlines()[0] == render.CONTENT_TYPE_TEXT
    assert 'real_e2e_requests_total{route="/a"} 3' in out
    assert "real_e2e_cpu_ratio 1" in out
    assert "target_info{" in out


def test_load_metric_reader_base(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def _module(name: str) -> SimpleNamespace:
        seen.append(name)
        return SimpleNamespace(MetricReader=_FakeBase)

    monkeypatch.setattr(otel_helpers, "_import_module", _module)
    assert otel_helpers.load_metric_reader_base() is _FakeBase
    assert seen == ["opentelemetry.sdk.metrics.export"]


def test_load_metric_reader_base_without_the_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    def _missing(name: str) -> None:
        raise ImportError(name)

    monkeypatch.setattr(otel_helpers, "_import_module", _missing)
    assert otel_helpers.load_metric_reader_base() is None


def test_snapshot_before_any_collection_delivers_data_is_none() -> None:
    class _SilentBase(_FakeBase):
        def collect(self) -> None:  # an unregistered SDK reader collects nothing
            self.collected += 1

    assert prom.pull_reader_class(_SilentBase)().snapshot() is None
