# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Regression tests for mutation survivors found in the 2026-03-25 mutation gate run.

All tests in this file use monkeypatching so they work regardless of whether
the optional opentelemetry extras are installed — and therefore run inside the
mutation gate's test selection (which excludes the otel/integration markers).
"""

from __future__ import annotations

import pytest

from undef.telemetry import _otel as otel_mod


# ── _otel.load_otel_trace_api: exact import name ──────────────────────────────
# Mutants: change "opentelemetry.trace" → None / garbled / uppercase.
# The otel-marked tests for this function require OTel to be installed;
# these tests work without it by capturing the name passed to _import_module.


def test_load_otel_trace_api_passes_exact_module_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kills mutants that replace 'opentelemetry.trace' with None, garbled, or uppercase."""
    captured: list[str | None] = []

    def _fake_import(name: str | None) -> object:
        captured.append(name)
        return object()

    monkeypatch.setattr(otel_mod, "_import_module", _fake_import)
    result = otel_mod.load_otel_trace_api()
    assert captured == ["opentelemetry.trace"]
    assert result is not None


# ── _otel.load_otel_metrics_api: exact import name ────────────────────────────


def test_load_otel_metrics_api_passes_exact_module_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kills mutants that replace 'opentelemetry.metrics' with garbled or uppercase."""
    captured: list[str | None] = []

    def _fake_import(name: str | None) -> object:
        captured.append(name)
        return object()

    monkeypatch.setattr(otel_mod, "_import_module", _fake_import)
    result = otel_mod.load_otel_metrics_api()
    assert captured == ["opentelemetry.metrics"]
    assert result is not None


# ── tracing/provider._load_otel_trace_api: _HAS_OTEL guard ────────────────────
# Mutant: flips `if not _HAS_OTEL` → `if _HAS_OTEL`, making the function
# return None when OTel IS present instead of delegating to _otel.


def test_load_otel_trace_api_delegates_when_has_otel_true(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kills the mutant that returns None when _HAS_OTEL is True."""
    from undef.telemetry.tracing import provider as pmod

    sentinel = object()
    monkeypatch.setattr(pmod, "_HAS_OTEL", True)
    monkeypatch.setattr(pmod._otel, "load_otel_trace_api", lambda: sentinel)
    assert pmod._load_otel_trace_api() is sentinel


# ── metrics/provider._load_otel_metrics_api: _HAS_OTEL_METRICS guard ──────────


def test_load_otel_metrics_api_delegates_when_has_otel_metrics_true(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kills the mutant that returns None when _HAS_OTEL_METRICS is True."""
    from undef.telemetry.metrics import provider as mmod

    sentinel = object()
    monkeypatch.setattr(mmod, "_HAS_OTEL_METRICS", True)
    monkeypatch.setattr(mmod._otel, "load_otel_metrics_api", lambda: sentinel)
    assert mmod._load_otel_metrics_api() is sentinel


# ── _otel.load_otel_tracing_components: exact import names + attribute access ──
# 16 mutants: each import name replaced with None/garbled, and each attribute
# access (.Resource, .TracerProvider, .BatchSpanProcessor, .OTLPSpanExporter)
# replaced with None.


def test_load_otel_tracing_components_passes_correct_module_names(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kills mutants that replace any import name with None or a garbage string."""
    from types import SimpleNamespace

    modules: dict[str, object] = {
        "opentelemetry.sdk.resources": SimpleNamespace(Resource="R"),
        "opentelemetry.sdk.trace": SimpleNamespace(TracerProvider="TP"),
        "opentelemetry.sdk.trace.export": SimpleNamespace(BatchSpanProcessor="BSP"),
        "opentelemetry.exporter.otlp.proto.http.trace_exporter": SimpleNamespace(OTLPSpanExporter="OSE"),
    }
    captured: list[str | None] = []

    def _fake_import(name: str | None) -> object:
        captured.append(name)
        if name not in modules:
            raise ImportError(name)
        return modules[name]  # type: ignore[index]

    monkeypatch.setattr(otel_mod, "_import_module", _fake_import)
    result = otel_mod.load_otel_tracing_components()
    assert captured == [
        "opentelemetry.sdk.resources",
        "opentelemetry.sdk.trace",
        "opentelemetry.sdk.trace.export",
        "opentelemetry.exporter.otlp.proto.http.trace_exporter",
    ]
    assert result == ("R", "TP", "BSP", "OSE")


def test_load_otel_tracing_components_extracts_correct_attributes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kills mutants that swap attribute names (.Resource → None, etc.)."""
    from types import SimpleNamespace

    r = object()
    tp = object()
    bsp = object()
    ose = object()
    modules = {
        "opentelemetry.sdk.resources": SimpleNamespace(Resource=r),
        "opentelemetry.sdk.trace": SimpleNamespace(TracerProvider=tp),
        "opentelemetry.sdk.trace.export": SimpleNamespace(BatchSpanProcessor=bsp),
        "opentelemetry.exporter.otlp.proto.http.trace_exporter": SimpleNamespace(OTLPSpanExporter=ose),
    }
    monkeypatch.setattr(otel_mod, "_import_module", lambda name: modules[name])  # type: ignore[index]
    result = otel_mod.load_otel_tracing_components()
    assert result == (r, tp, bsp, ose)


# ── _otel.load_otel_metrics_components: exact import names + attribute access ──
# 16 mutants: same pattern for metrics SDK imports.


def test_load_otel_metrics_components_passes_correct_module_names(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kills mutants that replace any import name with None or a garbage string."""
    from types import SimpleNamespace

    modules: dict[str, object] = {
        "opentelemetry.sdk.metrics": SimpleNamespace(MeterProvider="MP"),
        "opentelemetry.sdk.resources": SimpleNamespace(Resource="R"),
        "opentelemetry.sdk.metrics.export": SimpleNamespace(PeriodicExportingMetricReader="PEMR"),
        "opentelemetry.exporter.otlp.proto.http.metric_exporter": SimpleNamespace(OTLPMetricExporter="OME"),
    }
    captured: list[str | None] = []

    def _fake_import(name: str | None) -> object:
        captured.append(name)
        if name not in modules:
            raise ImportError(name)
        return modules[name]  # type: ignore[index]

    monkeypatch.setattr(otel_mod, "_import_module", _fake_import)
    result = otel_mod.load_otel_metrics_components()
    assert captured == [
        "opentelemetry.sdk.metrics",
        "opentelemetry.sdk.resources",
        "opentelemetry.sdk.metrics.export",
        "opentelemetry.exporter.otlp.proto.http.metric_exporter",
    ]
    assert result == ("MP", "R", "PEMR", "OME")


def test_load_otel_metrics_components_extracts_correct_attributes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kills mutants that swap attribute names (.MeterProvider → None, etc.)."""
    from types import SimpleNamespace

    mp = object()
    r = object()
    pemr = object()
    ome = object()
    modules = {
        "opentelemetry.sdk.metrics": SimpleNamespace(MeterProvider=mp),
        "opentelemetry.sdk.resources": SimpleNamespace(Resource=r),
        "opentelemetry.sdk.metrics.export": SimpleNamespace(PeriodicExportingMetricReader=pemr),
        "opentelemetry.exporter.otlp.proto.http.metric_exporter": SimpleNamespace(OTLPMetricExporter=ome),
    }
    monkeypatch.setattr(otel_mod, "_import_module", lambda name: modules[name])  # type: ignore[index]
    result = otel_mod.load_otel_metrics_components()
    assert result == (mp, r, pemr, ome)
