# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests for the canonical runtime facade delegation behavior.

These tests intentionally exercise the thin, compatibility-oriented runtime API
surface introduced in the shared runtime refactor.
"""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from typing import Any

from provide.telemetry import runtime as runtime_mod
from provide.telemetry._runtime_types import FlushResult, RuntimeStatus, SignalFlushResult
from provide.telemetry.config import RuntimeOverrides, TelemetryConfig


class _FakeLoggerModule(ModuleType):
    def get_logger(self, name: str) -> tuple[str, str]:
        return ("logger", name)


class _FakeTracingModule(ModuleType):
    def get_tracer(self, name: str) -> tuple[str, str]:
        return ("tracer", name)

    def trace(self, fn: Any = None) -> Any:
        return fn


class _FakeMetricsModule(ModuleType):
    def get_meter(self, name: str) -> tuple[str, str]:
        return ("meter", name)


def test_runtime_instance_delegates_core_calls(monkeypatch: Any) -> None:
    runtime = runtime_mod.TelemetryRuntime()

    got: list[tuple[Any, ...]] = []

    def fake_setup(cfg: TelemetryConfig | None) -> TelemetryConfig:
        got.append(("setup", cfg))
        return TelemetryConfig(service_name="runtime-test")

    def fake_shutdown(timeout_seconds: float | None = None) -> None:
        got.append(("shutdown", timeout_seconds))

    def fake_flush(timeout_seconds: float | None = None) -> bool:
        got.append(("flush", timeout_seconds))
        return True

    monkeypatch.setattr("provide.telemetry.setup.setup_telemetry", fake_setup)
    monkeypatch.setattr("provide.telemetry.setup.shutdown_telemetry", fake_shutdown)
    monkeypatch.setattr("provide.telemetry.setup.flush_telemetry", fake_flush)

    fake_logger_module = _FakeLoggerModule("provide.telemetry.logger")
    monkeypatch.setitem(sys.modules, "provide.telemetry.logger", fake_logger_module)

    fake_tracing_module = _FakeTracingModule("provide.telemetry.tracing")
    monkeypatch.setitem(sys.modules, "provide.telemetry.tracing", fake_tracing_module)

    fake_metrics_module = _FakeMetricsModule("provide.telemetry.metrics")
    monkeypatch.setitem(sys.modules, "provide.telemetry.metrics", fake_metrics_module)
    runtime_config = TelemetryConfig(service_name="runtime")
    monkeypatch.setattr("provide.telemetry.runtime.get_runtime_config", lambda: runtime_config)
    status = RuntimeStatus(
        setup_done=True,
        signals={"logs": True, "traces": True, "metrics": True},
        providers={"logs": True, "traces": False, "metrics": True},
        fallback={"logs": False, "traces": True, "metrics": False},
        setup_error=None,
    )
    monkeypatch.setattr("provide.telemetry.runtime.get_runtime_status", lambda: status)

    cfg = TelemetryConfig(service_name="configured")
    assert runtime.start(cfg) == TelemetryConfig(service_name="runtime-test")
    runtime.shutdown()
    flushed = runtime.flush(0.1)
    # providers reports traces uninstalled, so only traces is not_installed.
    assert flushed.logs == SignalFlushResult(flushed=True)
    assert flushed.traces == SignalFlushResult(not_installed=True)
    assert flushed.metrics == SignalFlushResult(flushed=True)
    assert runtime.get_logger("svc") == ("logger", "svc")
    assert runtime.get_tracer("svc") == ("tracer", "svc")
    assert runtime.get_meter("svc") == ("meter", "svc")
    assert runtime.get_runtime_config() == runtime_config
    assert runtime.get_runtime_status() == status

    previous_config = TelemetryConfig(service_name="previous")
    updated_config = TelemetryConfig(service_name="updated")

    def fake_get() -> TelemetryConfig:
        return previous_config

    def fake_update(cfg: RuntimeOverrides) -> TelemetryConfig:
        got.append(("update", cfg))
        return updated_config

    monkeypatch.setattr("provide.telemetry.runtime.get_runtime_config", fake_get)
    monkeypatch.setattr("provide.telemetry.runtime.update_runtime_config", fake_update)
    result = runtime.update_config(RuntimeOverrides())
    assert result.applied is True
    assert result.current == updated_config
    assert result.previous == previous_config

    def fake_get_cfg() -> TelemetryConfig:
        return previous_config

    def fake_reconfigure(cfg: TelemetryConfig) -> TelemetryConfig:
        got.append(("reconfigure", cfg))
        return cfg

    monkeypatch.setattr("provide.telemetry.runtime.get_runtime_config", fake_get_cfg)
    monkeypatch.setattr("provide.telemetry.runtime.reconfigure_telemetry", fake_reconfigure)
    runtime.update_config(TelemetryConfig(service_name="other"))
    assert ("reconfigure", TelemetryConfig(service_name="other")) in got


def test_runtime_module_facade_delegates_to_runtime_instance(monkeypatch: Any) -> None:
    got: list[tuple[Any, ...]] = []
    wrapped_config = TelemetryConfig(service_name="wrapped")

    def fake_start(cfg: TelemetryConfig | None = None) -> TelemetryConfig:
        got.append(("start", cfg))
        return cfg or TelemetryConfig()

    def fake_shutdown(timeout: float | None = None) -> None:
        got.append(("shutdown", timeout))

    sentinel = FlushResult(logs=SignalFlushResult(flushed=True))

    def fake_flush(timeout: float | None = None) -> FlushResult:
        got.append(("flush", timeout))
        return sentinel

    stub = SimpleNamespace(
        start=fake_start,
        shutdown=fake_shutdown,
        flush=fake_flush,
        get_logger=lambda name: ("logger", name),
        get_tracer=lambda name: ("tracer", name),
        get_meter=lambda name: ("meter", name),
    )
    monkeypatch.setattr(runtime_mod, "_runtime", stub)

    assert runtime_mod.start(wrapped_config) == wrapped_config
    assert ("start", wrapped_config) in got
    runtime_mod.shutdown(0.5)
    assert ("shutdown", 0.5) in got
    assert runtime_mod.flush(0.25) is sentinel
    assert ("flush", 0.25) in got
    assert runtime_mod.get_logger("svc") == ("logger", "svc")
    assert runtime_mod.get_tracer("svc") == ("tracer", "svc")
    assert runtime_mod.get_meter("svc") == ("meter", "svc")
