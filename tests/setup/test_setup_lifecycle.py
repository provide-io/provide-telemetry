# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

from __future__ import annotations

import threading
import time

import pytest

from provide.telemetry import setup as setup_mod
from provide.telemetry.config import TelemetryConfig
from provide.telemetry.setup import (
    _reset_all_for_tests,
    _reset_setup_state_for_tests,
    setup_telemetry,
    shutdown_telemetry,
)


def test_reconfigure_telemetry_calls_shutdown_then_setup_for_provider_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    from provide.telemetry import runtime as runtime_mod

    _reset_all_for_tests()
    calls: list[str] = []
    runtime_mod.reset_runtime_for_tests()
    runtime_mod.apply_runtime_config(TelemetryConfig(service_name="before"))

    def _fake_shutdown() -> None:
        calls.append("shutdown")

    def _fake_setup(config: TelemetryConfig | None = None) -> TelemetryConfig:
        calls.append("setup")
        return TelemetryConfig()

    monkeypatch.setattr("provide.telemetry.setup.shutdown_telemetry", _fake_shutdown)
    monkeypatch.setattr("provide.telemetry.setup.setup_telemetry", _fake_setup)
    result = runtime_mod.reconfigure_telemetry(TelemetryConfig(service_name="after"))
    assert calls == ["shutdown", "setup"]
    assert isinstance(result, TelemetryConfig)


def test_reconfigure_telemetry_with_config(monkeypatch: pytest.MonkeyPatch) -> None:
    from provide.telemetry import runtime as runtime_mod

    _reset_all_for_tests()
    runtime_mod.reset_runtime_for_tests()
    runtime_mod.apply_runtime_config(TelemetryConfig(service_name="before"))
    seen_configs: list[object] = []

    def _fake_setup(config: TelemetryConfig | None = None) -> TelemetryConfig:
        seen_configs.append(config)
        return TelemetryConfig()

    monkeypatch.setattr("provide.telemetry.setup.shutdown_telemetry", lambda: None)
    monkeypatch.setattr("provide.telemetry.setup.setup_telemetry", _fake_setup)
    cfg = TelemetryConfig(service_name="reconfigured")
    runtime_mod.reconfigure_telemetry(cfg)
    assert seen_configs[0] is cfg


def test_reconfigure_telemetry_hot_runtime_only(monkeypatch: pytest.MonkeyPatch) -> None:
    from provide.telemetry import runtime as runtime_mod

    runtime_mod.reset_runtime_for_tests()
    base = TelemetryConfig(service_name="svc")
    runtime_mod.apply_runtime_config(base)
    updated = TelemetryConfig(service_name="svc")
    updated.sampling.logs_rate = 0.5
    updated.exporter.logs_timeout_seconds = 5.0

    called = {"shutdown": 0, "setup": 0}

    def _fake_shutdown() -> None:
        called["shutdown"] = 1

    def _fake_setup(_cfg: object = None) -> TelemetryConfig:
        called["setup"] = 1
        return TelemetryConfig()

    monkeypatch.setattr("provide.telemetry.setup.shutdown_telemetry", _fake_shutdown)
    monkeypatch.setattr("provide.telemetry.setup.setup_telemetry", _fake_setup)

    result = runtime_mod.reconfigure_telemetry(updated)
    assert called == {"shutdown": 0, "setup": 0}
    assert result.sampling.logs_rate == 0.5
    assert result.exporter.logs_timeout_seconds == 5.0


def test_reconfigure_telemetry_raises_when_otel_provider_replacement_required(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from provide.telemetry import runtime as runtime_mod
    from provide.telemetry.logger import core as logger_core
    from provide.telemetry.metrics import provider as metrics_provider
    from provide.telemetry.tracing import provider as tracing_provider

    runtime_mod.reset_runtime_for_tests()
    runtime_mod.apply_runtime_config(TelemetryConfig(service_name="svc"))
    monkeypatch.setattr(logger_core, "_otel_log_provider", SimpleNamespace())
    monkeypatch.setattr(tracing_provider, "_provider_ref", None)
    monkeypatch.setattr(metrics_provider, "_meter_provider", None)

    with pytest.raises(RuntimeError, match="provider-changing reconfiguration is unsupported"):
        runtime_mod.reconfigure_telemetry(TelemetryConfig(service_name="renamed"))


def test_refresh_otel_metrics_updates_cached_boolean(monkeypatch: pytest.MonkeyPatch) -> None:
    from provide.telemetry.metrics import provider as pmod

    monkeypatch.setattr(pmod, "_HAS_OTEL_METRICS", False)
    monkeypatch.setattr(pmod, "_has_otel_metrics", lambda: True)
    pmod._refresh_otel_metrics()
    assert pmod._HAS_OTEL_METRICS is True


def test_refresh_otel_tracing_updates_cached_boolean(monkeypatch: pytest.MonkeyPatch) -> None:
    from provide.telemetry.tracing import provider as tmod

    monkeypatch.setattr(tmod, "_HAS_OTEL", False)
    monkeypatch.setattr(tmod, "_has_otel", lambda: True)
    tmod._refresh_otel_tracing()
    assert tmod._HAS_OTEL is True


def test_setup_telemetry_calls_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_setup_state_for_tests()
    calls: list[str] = []
    monkeypatch.setattr("provide.telemetry.setup.apply_runtime_config", lambda _cfg: None)
    monkeypatch.setattr("provide.telemetry.setup.configure_logging", lambda _cfg, **kw: None)
    monkeypatch.setattr("provide.telemetry.setup._refresh_otel_tracing", lambda: calls.append("refresh_tracing"))
    monkeypatch.setattr("provide.telemetry.setup._refresh_otel_metrics", lambda: calls.append("refresh_metrics"))
    monkeypatch.setattr("provide.telemetry.setup.setup_tracing", lambda _cfg: None)
    monkeypatch.setattr("provide.telemetry.setup.setup_metrics", lambda _cfg: None)
    setup_telemetry()
    assert "refresh_tracing" in calls
    assert "refresh_metrics" in calls


def test_setup_telemetry_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_setup_state_for_tests()
    calls = {"runtime": 0, "log": 0, "trace": 0, "metrics": 0, "red": 0, "use": 0}
    seen_cfg: dict[str, object] = {}

    def _runtime(cfg: object) -> None:
        calls["runtime"] += 1
        seen_cfg["runtime"] = cfg

    def _log(cfg: object, **kw: object) -> None:
        calls["log"] += 1
        seen_cfg["log"] = cfg

    def _trace(cfg: object) -> None:
        calls["trace"] += 1
        seen_cfg["trace"] = cfg

    def _metrics(cfg: object) -> None:
        calls["metrics"] += 1
        seen_cfg["metrics"] = cfg

    def _red(_route: str, _method: str, _status_code: int, _duration_ms: float) -> None:
        calls["red"] += 1

    def _use(_resource: str, _utilization_percent: int) -> None:
        calls["use"] += 1

    import provide.telemetry.slo as slo_mod

    monkeypatch.setattr("provide.telemetry.setup.apply_runtime_config", _runtime)
    monkeypatch.setattr("provide.telemetry.setup.configure_logging", _log)
    monkeypatch.setattr("provide.telemetry.setup._refresh_otel_tracing", lambda: None)
    monkeypatch.setattr("provide.telemetry.setup._refresh_otel_metrics", lambda: None)
    monkeypatch.setattr("provide.telemetry.setup.setup_tracing", _trace)
    monkeypatch.setattr("provide.telemetry.setup.setup_metrics", _metrics)
    monkeypatch.setattr(slo_mod, "record_red_metrics", _red)
    monkeypatch.setattr(slo_mod, "record_use_metrics", _use)

    cfg1 = setup_telemetry()
    cfg2 = setup_telemetry()
    assert cfg1.service_name == cfg2.service_name
    assert calls == {"runtime": 1, "log": 1, "trace": 1, "metrics": 1, "red": 0, "use": 0}
    assert seen_cfg["runtime"] is cfg1
    assert seen_cfg["log"] is cfg1
    assert seen_cfg["trace"] is cfg1
    assert seen_cfg["metrics"] is cfg1


def test_setup_telemetry_emits_slo_startup_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_setup_state_for_tests()
    calls = {"red": 0, "use": 0}
    import provide.telemetry.slo as slo_mod

    monkeypatch.setattr("provide.telemetry.setup.apply_runtime_config", lambda _cfg: None)
    monkeypatch.setattr("provide.telemetry.setup.configure_logging", lambda _cfg, **kw: None)
    monkeypatch.setattr("provide.telemetry.setup._refresh_otel_tracing", lambda: None)
    monkeypatch.setattr("provide.telemetry.setup._refresh_otel_metrics", lambda: None)
    monkeypatch.setattr("provide.telemetry.setup.setup_tracing", lambda _cfg: None)
    monkeypatch.setattr("provide.telemetry.setup.setup_metrics", lambda _cfg: None)
    monkeypatch.setattr(slo_mod, "record_red_metrics", lambda *_args: calls.__setitem__("red", 1))
    monkeypatch.setattr(slo_mod, "record_use_metrics", lambda *_args: calls.__setitem__("use", 1))
    setup_telemetry(
        TelemetryConfig.from_env({"PROVIDE_SLO_ENABLE_RED_METRICS": "true", "PROVIDE_SLO_ENABLE_USE_METRICS": "true"})
    )
    assert calls == {"red": 1, "use": 1}


def test_shutdown_telemetry(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {"log": 0, "trace": 0, "metrics": 0}

    def _log() -> None:
        called["log"] += 1

    def _trace() -> None:
        called["trace"] += 1

    def _metrics() -> None:
        called["metrics"] += 1

    monkeypatch.setattr("provide.telemetry.setup.shutdown_logging", _log)
    monkeypatch.setattr("provide.telemetry.setup.shutdown_tracing", _trace)
    monkeypatch.setattr("provide.telemetry.setup.shutdown_metrics", _metrics)
    shutdown_telemetry()
    assert called == {"log": 1, "trace": 1, "metrics": 1}


def test_shutdown_telemetry_resets_setup_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(setup_mod, "_setup_done", True)
    monkeypatch.setattr("provide.telemetry.setup.shutdown_logging", lambda: None)
    monkeypatch.setattr("provide.telemetry.setup.shutdown_tracing", lambda: None)
    monkeypatch.setattr("provide.telemetry.setup.shutdown_metrics", lambda: None)
    shutdown_telemetry()
    assert setup_mod._setup_done is False


def test_reset_all_for_tests_sets_setup_done_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(setup_mod, "_setup_done", True)
    _reset_all_for_tests()
    assert setup_mod._setup_done is False


def test_reset_setup_state_sets_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(setup_mod, "_setup_done", True)
    _reset_setup_state_for_tests()
    assert setup_mod._setup_done is False


def test_setup_rollback_on_tracing_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_setup_state_for_tests()
    called = {"log_shutdown": 0, "trace_shutdown": 0, "metrics_shutdown": 0}
    monkeypatch.setattr("provide.telemetry.setup.apply_runtime_config", lambda _cfg: None)
    monkeypatch.setattr("provide.telemetry.setup.configure_logging", lambda _cfg, **kw: None)
    monkeypatch.setattr("provide.telemetry.setup._refresh_otel_tracing", lambda: None)
    monkeypatch.setattr("provide.telemetry.setup._refresh_otel_metrics", lambda: None)
    monkeypatch.setattr(
        "provide.telemetry.setup.setup_tracing", lambda _cfg: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    monkeypatch.setattr("provide.telemetry.setup.setup_metrics", lambda _cfg: None)
    monkeypatch.setattr(
        "provide.telemetry.setup.shutdown_logging",
        lambda: called.__setitem__("log_shutdown", called["log_shutdown"] + 1),
    )
    monkeypatch.setattr(
        "provide.telemetry.setup.shutdown_tracing",
        lambda: called.__setitem__("trace_shutdown", called["trace_shutdown"] + 1),
    )
    monkeypatch.setattr(
        "provide.telemetry.setup.shutdown_metrics",
        lambda: called.__setitem__("metrics_shutdown", called["metrics_shutdown"] + 1),
    )
    with pytest.raises(RuntimeError, match="boom"):
        setup_telemetry()
    # Only logging was completed before tracing failed, so only logging is rolled back
    assert called["log_shutdown"] == 1
    assert called["trace_shutdown"] == 0
    assert called["metrics_shutdown"] == 0
    assert setup_mod._setup_done is False


def test_setup_rollback_on_metrics_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_setup_state_for_tests()
    called = {"log_shutdown": 0, "trace_shutdown": 0, "metrics_shutdown": 0}
    monkeypatch.setattr("provide.telemetry.setup.apply_runtime_config", lambda _cfg: None)
    monkeypatch.setattr("provide.telemetry.setup.configure_logging", lambda _cfg, **kw: None)
    monkeypatch.setattr("provide.telemetry.setup._refresh_otel_tracing", lambda: None)
    monkeypatch.setattr("provide.telemetry.setup._refresh_otel_metrics", lambda: None)
    monkeypatch.setattr("provide.telemetry.setup.setup_tracing", lambda _cfg: None)
    monkeypatch.setattr(
        "provide.telemetry.setup.setup_metrics", lambda _cfg: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    monkeypatch.setattr(
        "provide.telemetry.setup.shutdown_logging",
        lambda: called.__setitem__("log_shutdown", called["log_shutdown"] + 1),
    )
    monkeypatch.setattr(
        "provide.telemetry.setup.shutdown_tracing",
        lambda: called.__setitem__("trace_shutdown", called["trace_shutdown"] + 1),
    )
    monkeypatch.setattr(
        "provide.telemetry.setup.shutdown_metrics",
        lambda: called.__setitem__("metrics_shutdown", called["metrics_shutdown"] + 1),
    )
    with pytest.raises(RuntimeError, match="boom"):
        setup_telemetry()
    # Logging + tracing completed, so both rolled back in reverse
    assert called["log_shutdown"] == 1
    assert called["trace_shutdown"] == 1
    assert called["metrics_shutdown"] == 0
    assert setup_mod._setup_done is False


def test_rollback_continues_when_teardown_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """If a teardown step raises during rollback, remaining teardowns still execute."""
    _reset_setup_state_for_tests()
    called = {"log_shutdown": 0, "trace_shutdown": 0}
    monkeypatch.setattr("provide.telemetry.setup.apply_runtime_config", lambda _cfg: None)
    monkeypatch.setattr("provide.telemetry.setup.configure_logging", lambda _cfg, **kw: None)
    monkeypatch.setattr("provide.telemetry.setup._refresh_otel_tracing", lambda: None)
    monkeypatch.setattr("provide.telemetry.setup._refresh_otel_metrics", lambda: None)
    monkeypatch.setattr("provide.telemetry.setup.setup_tracing", lambda _cfg: None)
    monkeypatch.setattr(
        "provide.telemetry.setup.setup_metrics", lambda _cfg: (_ for _ in ()).throw(RuntimeError("boom"))
    )

    def _trace_shutdown_raises() -> None:
        called["trace_shutdown"] += 1
        raise OSError("teardown exploded")

    monkeypatch.setattr(
        "provide.telemetry.setup.shutdown_logging",
        lambda: called.__setitem__("log_shutdown", called["log_shutdown"] + 1),
    )
    monkeypatch.setattr("provide.telemetry.setup.shutdown_tracing", _trace_shutdown_raises)
    monkeypatch.setattr("provide.telemetry.setup.shutdown_metrics", lambda: None)

    with pytest.raises(RuntimeError, match="boom"):
        setup_telemetry()
    # Tracing teardown raised, but logging teardown must still have been called
    assert called["trace_shutdown"] == 1
    assert called["log_shutdown"] == 1
    assert setup_mod._setup_done is False


def test_shutdown_and_setup_are_serialized(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_setup_state_for_tests()
    monkeypatch.setattr(setup_mod, "_setup_done", True)
    calls = {"runtime": 0, "log": 0, "trace": 0, "metrics": 0}
    shutdown_started = threading.Event()
    allow_shutdown_to_continue = threading.Event()

    def _runtime(_cfg: object) -> None:
        calls["runtime"] += 1

    def _log(_cfg: object, **kw: object) -> None:
        calls["log"] += 1

    def _trace(_cfg: object) -> None:
        calls["trace"] += 1

    def _metrics(_cfg: object) -> None:
        calls["metrics"] += 1

    def _shutdown_log() -> None:
        shutdown_started.set()
        assert allow_shutdown_to_continue.wait(timeout=1.0)

    monkeypatch.setattr("provide.telemetry.setup.apply_runtime_config", _runtime)
    monkeypatch.setattr("provide.telemetry.setup.configure_logging", _log)
    monkeypatch.setattr("provide.telemetry.setup._refresh_otel_tracing", lambda: None)
    monkeypatch.setattr("provide.telemetry.setup._refresh_otel_metrics", lambda: None)
    monkeypatch.setattr("provide.telemetry.setup.setup_tracing", _trace)
    monkeypatch.setattr("provide.telemetry.setup.setup_metrics", _metrics)
    monkeypatch.setattr("provide.telemetry.setup.shutdown_logging", _shutdown_log)
    monkeypatch.setattr("provide.telemetry.setup.shutdown_tracing", lambda: None)
    monkeypatch.setattr("provide.telemetry.setup.shutdown_metrics", lambda: None)

    shutdown_thread = threading.Thread(target=shutdown_telemetry, daemon=True)
    setup_thread = threading.Thread(target=lambda: setup_telemetry(TelemetryConfig()), daemon=True)
    shutdown_thread.start()
    assert shutdown_started.wait(timeout=1.0)
    setup_thread.start()
    time.sleep(0.05)
    # setup_telemetry should still be blocked until shutdown releases the lifecycle lock.
    assert calls == {"runtime": 0, "log": 0, "trace": 0, "metrics": 0}
    allow_shutdown_to_continue.set()
    shutdown_thread.join(timeout=1.0)
    setup_thread.join(timeout=1.0)
    assert calls == {"runtime": 1, "log": 1, "trace": 1, "metrics": 1}
    assert setup_mod._setup_done is True
