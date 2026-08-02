# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""The bounded-shutdown contract: the caller's deadline reaches every teardown.

``shutdown_telemetry(timeout_seconds=…)`` is what a SIGTERM handler calls with
the time it has left. Three things have to hold for that to mean anything:

* resolving the deadline must not raise, or a mis-set environment aborts the
  teardown before it starts and leaves every provider installed;
* every per-signal teardown must be bounded by it, not only the logs one; and
* nothing may drain twice, or the wall time doubles against a slow collector.
"""

from __future__ import annotations

import threading
import time

import pytest

from provide.telemetry import _provider_drain as drain
from provide.telemetry import setup as setup_mod
from provide.telemetry.config import ExporterPolicyConfig
from provide.telemetry.exceptions import ConfigurationError
from provide.telemetry.logger import core as logger_core
from provide.telemetry.metrics import provider as metrics_provider
from provide.telemetry.tracing import provider as tracing_provider


class _HangingProvider:
    """A provider whose drain never returns, like an unreachable OTLP endpoint."""

    def __init__(self) -> None:
        self.release = threading.Event()
        self.calls: list[str] = []

    def force_flush(self) -> None:
        self.calls.append("force_flush")
        self.release.wait(timeout=5.0)

    def shutdown(self) -> None:
        self.calls.append("shutdown")
        self.release.wait(timeout=5.0)


# ── resolve_drain_deadline ─────────────────────────────────────────────


def test_explicit_deadline_is_used_verbatim() -> None:
    assert drain.resolve_drain_deadline(0.25) == 0.25
    # Zero is a real caller choice ("do not bound"), not a missing value.
    assert drain.resolve_drain_deadline(0.0) == 0.0


def test_none_reads_the_active_configured_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    from provide.telemetry.config import TelemetryConfig

    cfg = TelemetryConfig(exporter=ExporterPolicyConfig(logs_shutdown_timeout_seconds=1.75))
    monkeypatch.setattr("provide.telemetry.runtime.get_runtime_config", lambda: cfg)
    assert drain.resolve_drain_deadline(None) == 1.75


def test_a_malformed_environment_falls_back_instead_of_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no active config, get_runtime_config() re-parses the environment.

    A bad PROVIDE_* value makes that raise. Letting it escape aborts shutdown
    before any teardown runs — precisely in a process whose environment is
    mis-set, which is when the operator most needs the drain.
    """

    def _boom() -> object:
        raise ConfigurationError("invalid boolean for PROVIDE_LOG_INCLUDE_TIMESTAMP")

    monkeypatch.setattr("provide.telemetry.runtime.get_runtime_config", _boom)
    assert drain.resolve_drain_deadline(None) == ExporterPolicyConfig().logs_shutdown_timeout_seconds


def test_shutdown_survives_a_malformed_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end form of the above: teardown still happens."""
    monkeypatch.setattr(setup_mod, "_setup_done", True)
    monkeypatch.setenv("PROVIDE_LOG_INCLUDE_TIMESTAMP", "not-a-bool")
    monkeypatch.setattr("provide.telemetry.runtime._active_config", None)

    setup_mod.shutdown_telemetry()

    assert setup_mod._setup_done is False


# ── every teardown is bounded ──────────────────────────────────────────


@pytest.mark.parametrize(
    ("module", "attribute", "teardown"),
    [
        (tracing_provider, "_provider_ref", tracing_provider.shutdown_tracing),
        (metrics_provider, "_meter_provider", metrics_provider.shutdown_metrics),
        (logger_core, "_otel_log_provider", logger_core.shutdown_logging),
    ],
)
def test_teardown_returns_within_the_callers_deadline(
    monkeypatch: pytest.MonkeyPatch,
    module: object,
    attribute: str,
    teardown: object,
) -> None:
    """A stuck provider must not outlast the deadline the caller passed.

    Unbounded, each of these blocks for the OTel SDK's own 30s worker join, so a
    pod with a 5s termination grace period is SIGKILLed with records still
    queued.
    """
    provider = _HangingProvider()
    monkeypatch.setattr(module, attribute, provider)
    started = time.monotonic()
    try:
        teardown(0.05)  # type: ignore[operator]
        elapsed = time.monotonic() - started
    finally:
        provider.release.set()
        drain._reset_abandoned_workers_for_tests()

    assert elapsed < 2.0, f"teardown ran {elapsed:.2f}s past a 0.05s deadline"
    assert provider.calls[0] == "force_flush"


def test_shutdown_does_not_drain_twice(monkeypatch: pytest.MonkeyPatch) -> None:
    """No separate pre-drain: each teardown already flushes before it shuts down.

    A pre-drain exports every signal a second time, roughly doubling shutdown
    wall time against a slow collector for no extra guarantee.
    """
    calls: list[str] = []

    class _CountingProvider:
        def force_flush(self) -> None:
            calls.append("force_flush")

        def shutdown(self) -> None:
            calls.append("shutdown")

    monkeypatch.setattr(setup_mod, "_setup_done", True)
    monkeypatch.setattr(tracing_provider, "_provider_ref", _CountingProvider())
    monkeypatch.setattr(metrics_provider, "_meter_provider", None)
    monkeypatch.setattr(logger_core, "_otel_log_provider", None)

    setup_mod.shutdown_telemetry(0.5)

    assert calls == ["force_flush", "shutdown"]
