# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

from __future__ import annotations

import pytest

from undef.telemetry import setup as setup_mod
from undef.telemetry.config import TelemetryConfig
from undef.telemetry.setup import _reset_setup_state_for_tests, setup_telemetry, shutdown_telemetry


def test_setup_telemetry_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_setup_state_for_tests()
    calls = {"runtime": 0, "log": 0, "trace": 0, "metrics": 0, "red": 0, "use": 0}
    seen_cfg: dict[str, object] = {}

    def _runtime(cfg: object) -> None:
        calls["runtime"] += 1
        seen_cfg["runtime"] = cfg

    def _log(cfg: object) -> None:
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

    monkeypatch.setattr("undef.telemetry.setup.apply_runtime_config", _runtime)
    monkeypatch.setattr("undef.telemetry.setup.configure_logging", _log)
    monkeypatch.setattr("undef.telemetry.setup.setup_tracing", _trace)
    monkeypatch.setattr("undef.telemetry.setup.setup_metrics", _metrics)
    monkeypatch.setattr("undef.telemetry.setup.record_red_metrics", _red)
    monkeypatch.setattr("undef.telemetry.setup.record_use_metrics", _use)

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
    monkeypatch.setattr("undef.telemetry.setup.apply_runtime_config", lambda _cfg: None)
    monkeypatch.setattr("undef.telemetry.setup.configure_logging", lambda _cfg: None)
    monkeypatch.setattr("undef.telemetry.setup.setup_tracing", lambda _cfg: None)
    monkeypatch.setattr("undef.telemetry.setup.setup_metrics", lambda _cfg: None)
    monkeypatch.setattr("undef.telemetry.setup.record_red_metrics", lambda *_args: calls.__setitem__("red", 1))
    monkeypatch.setattr("undef.telemetry.setup.record_use_metrics", lambda *_args: calls.__setitem__("use", 1))
    setup_telemetry(
        TelemetryConfig.from_env({"UNDEF_SLO_ENABLE_RED_METRICS": "true", "UNDEF_SLO_ENABLE_USE_METRICS": "true"})
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

    monkeypatch.setattr("undef.telemetry.setup.shutdown_logging", _log)
    monkeypatch.setattr("undef.telemetry.setup.shutdown_tracing", _trace)
    monkeypatch.setattr("undef.telemetry.setup.shutdown_metrics", _metrics)
    shutdown_telemetry()
    assert called == {"log": 1, "trace": 1, "metrics": 1}


def test_reset_setup_state_sets_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(setup_mod, "_setup_done", True)
    _reset_setup_state_for_tests()
    assert setup_mod._setup_done is False
