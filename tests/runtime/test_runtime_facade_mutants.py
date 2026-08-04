# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests killing surviving mutants in the TelemetryRuntime facade.

Every test here pins an argument that is forwarded or a field that is assigned,
because the facade's whole job is delegation: a mutant that drops an argument or
nulls a state field leaves the delegation silently wrong.

Covers:
  __init__:            _state / _provider_mode initial values
  start:               config forwarding, READY assignment
  shutdown:            timeout forwarding, STOPPED assignment
  flush:               timeout forwarding, per-signal drained flag
  update_config:       overrides forwarding, state assignment
  _signal_flush_result: timed_out keyword
  get_runtime_status:  setup_error propagation
  __getattr__:         package name forwarding to _lazy.resolve
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from provide.telemetry import runtime as runtime_mod
from provide.telemetry._runtime_types import ProviderMode, RuntimeState, SignalFlushResult
from provide.telemetry.config import RuntimeOverrides, TelemetryConfig


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    runtime_mod.reset_runtime_for_tests()
    yield
    runtime_mod.reset_runtime_for_tests()


def test_init_assigns_ready_and_owned() -> None:
    rt = runtime_mod.TelemetryRuntime()

    assert rt._state is RuntimeState.READY
    assert rt._provider_mode is ProviderMode.OWNED


def test_start_forwards_config_and_sets_ready(monkeypatch: Any) -> None:
    seen: list[TelemetryConfig | None] = []
    cfg = TelemetryConfig(service_name="start-forwards")

    def fake_setup(config: TelemetryConfig | None) -> TelemetryConfig:
        seen.append(config)
        return config or TelemetryConfig()

    monkeypatch.setattr("provide.telemetry.setup.setup_telemetry", fake_setup)
    rt = runtime_mod.TelemetryRuntime()
    rt._state = RuntimeState.DEGRADED

    assert rt.start(cfg) == cfg
    assert seen == [cfg], "start must forward its config, not None"
    assert rt._state is RuntimeState.READY


def test_shutdown_forwards_timeout_and_sets_stopped(monkeypatch: Any) -> None:
    seen: list[float | None] = []

    def fake_shutdown(timeout_seconds: float | None = None) -> None:
        seen.append(timeout_seconds)

    monkeypatch.setattr("provide.telemetry.setup.shutdown_telemetry", fake_shutdown)
    rt = runtime_mod.TelemetryRuntime()

    rt.shutdown(2.5)
    assert seen == [2.5], "shutdown must forward the caller's deadline, not None"
    assert rt._state is RuntimeState.STOPPED


def test_flush_forwards_timeout(monkeypatch: Any) -> None:
    seen: list[float | None] = []

    def fake_flush(timeout_seconds: float | None = None) -> dict[str, str]:
        seen.append(timeout_seconds)
        return {"logs": "flushed", "traces": "flushed", "metrics": "flushed"}

    monkeypatch.setattr("provide.telemetry.setup.flush_signals", fake_flush)
    rt = runtime_mod.TelemetryRuntime()

    rt.flush(0.75)
    assert seen == [0.75], "flush must forward the caller's deadline, not None"


@pytest.mark.parametrize("outcome", ["flushed", "timed_out", "failed"])
def test_flush_applies_drain_outcome_to_every_signal(monkeypatch: Any, outcome: str) -> None:
    monkeypatch.setattr(
        "provide.telemetry.setup.flush_signals",
        lambda timeout_seconds=None: {"logs": outcome, "traces": outcome, "metrics": outcome},
    )
    monkeypatch.setattr(
        "provide.telemetry._provider_drain.owned_signals",
        lambda: {"logs": True, "traces": True, "metrics": True},
    )
    monkeypatch.setattr(
        "provide.telemetry._provider_drain.installed_signals",
        lambda: {"logs": True, "traces": True, "metrics": True},
    )

    result = runtime_mod.TelemetryRuntime().flush()

    # Each signal must carry the real drain outcome — a mutant nulling any one of
    # them flips that signal's flags.
    for signal in (result.logs, result.traces, result.metrics):
        assert signal.flushed is (outcome == "flushed")
        assert signal.timed_out is (outcome == "timed_out")
        assert signal.failed is (outcome == "failed")


def test_signal_flush_result_maps_each_outcome() -> None:
    assert runtime_mod._signal_flush_result(True, True, "timed_out") == SignalFlushResult(
        flushed=False, not_installed=False, timed_out=True
    )
    assert runtime_mod._signal_flush_result(True, True, "flushed") == SignalFlushResult(
        flushed=True, not_installed=False, timed_out=False
    )
    assert runtime_mod._signal_flush_result(True, True, "failed") == SignalFlushResult(
        flushed=False, not_installed=False, timed_out=False, failed=True
    )


def test_update_config_forwards_overrides_and_state(monkeypatch: Any) -> None:
    seen: list[RuntimeOverrides] = []
    applied = TelemetryConfig(service_name="applied")
    overrides = RuntimeOverrides(strict_schema=True)

    def fake_update(cfg: RuntimeOverrides) -> TelemetryConfig:
        seen.append(cfg)
        return applied

    monkeypatch.setattr(runtime_mod, "update_runtime_config", fake_update)
    rt = runtime_mod.TelemetryRuntime()
    rt._state = RuntimeState.DEGRADED

    result = rt.update_config(overrides)

    assert seen == [overrides], "update_config must forward the caller's overrides, not None"
    assert result.current == applied
    assert result.state is RuntimeState.DEGRADED, "state must come from the runtime, not a default"


def test_get_runtime_status_propagates_setup_error(monkeypatch: Any) -> None:
    from provide.telemetry import health as health_mod

    health_mod.reset_health_for_tests()
    health_mod.set_setup_error("boom")

    assert runtime_mod.get_runtime_status().setup_error == "boom"
    health_mod.reset_health_for_tests()


def test_package_getattr_forwards_the_package_name(monkeypatch: Any) -> None:
    import provide.telemetry as pkg
    from provide.telemetry import _lazy

    seen: list[str] = []
    real_resolve = _lazy.resolve

    def spy(package: str, name: str) -> object:
        seen.append(package)
        return real_resolve(package, name)

    monkeypatch.setattr(_lazy, "resolve", spy)
    assert pkg.__getattr__("should_sample") is not None
    assert seen == ["provide.telemetry"], "__getattr__ must pass its own module name"
