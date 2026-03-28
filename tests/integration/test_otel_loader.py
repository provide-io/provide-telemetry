# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest

from undef.telemetry import _otel

pytestmark = pytest.mark.otel


def test_has_otel_handles_import_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_otel, "_import_module", lambda _: (_ for _ in ()).throw(ImportError()))
    assert _otel.has_otel() is False


def test_load_otel_metrics_components_success(monkeypatch: pytest.MonkeyPatch) -> None:
    modules = {
        "opentelemetry": object(),
        "opentelemetry.sdk.metrics": SimpleNamespace(MeterProvider="mp"),
        "opentelemetry.sdk.resources": SimpleNamespace(Resource="res"),
        "opentelemetry.sdk.metrics.export": SimpleNamespace(PeriodicExportingMetricReader="reader"),
        "opentelemetry.exporter.otlp.proto.http.metric_exporter": SimpleNamespace(OTLPMetricExporter="exp"),
    }
    monkeypatch.setattr(_otel, "_import_module", lambda name: modules[name])
    assert _otel.load_otel_metrics_components() == ("mp", "res", "reader", "exp")


def test_load_instrumentation_logging_handler_missing_attr(monkeypatch: pytest.MonkeyPatch) -> None:
    modules = {
        "opentelemetry.instrumentation.logging.handler": SimpleNamespace(),
    }
    monkeypatch.setattr(_otel, "_import_module", lambda name: modules[name])
    assert _otel.load_instrumentation_logging_handler() is None


def test_import_module_forwards_name_exactly(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str | None] = []

    def _fake_import_module(name: str | None) -> object:
        seen.append(name)
        return object()

    monkeypatch.setattr(importlib, "import_module", _fake_import_module)
    _otel._import_module("opentelemetry.trace")
    assert seen == ["opentelemetry.trace"]
