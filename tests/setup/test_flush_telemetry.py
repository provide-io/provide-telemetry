# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests for :func:`provide.telemetry.flush_telemetry` and the per-signal drains.

flush_telemetry is the drain half of shutdown_telemetry: providers must be
force-flushed and left installed, every signal must get its attempt even when
an earlier one is abandoned, and the result must report whether all of them
made the deadline.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from provide.telemetry import flush_telemetry
from provide.telemetry.config import ExporterPolicyConfig, TelemetryConfig
from provide.telemetry import _provider_drain as drain
from provide.telemetry.logger import core as logger_core
from provide.telemetry.metrics import provider as metrics_provider
from provide.telemetry.setup import setup_telemetry
from provide.telemetry.tracing import provider as tracing_provider


class _RecordingProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def force_flush(self) -> None:
        self.calls.append("force_flush")

    def shutdown(self) -> None:  # pragma: no cover - flush must never call this
        self.calls.append("shutdown")


# ── per-signal drains ──────────────────────────────────────────────────


def test_flush_tracing_is_a_noop_without_an_installed_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tracing_provider, "_provider_ref", None)
    assert drain.flush_tracing(1.0) is True


def test_flush_tracing_flushes_the_installed_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _RecordingProvider()
    monkeypatch.setattr(tracing_provider, "_provider_ref", provider)
    assert drain.flush_tracing(1.0) is True
    assert provider.calls == ["force_flush"]


def test_flush_metrics_is_a_noop_without_an_installed_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(metrics_provider, "_meter_provider", None)
    assert drain.flush_metrics(1.0) is True


def test_flush_metrics_flushes_the_installed_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _RecordingProvider()
    monkeypatch.setattr(metrics_provider, "_meter_provider", provider)
    assert drain.flush_metrics(1.0) is True
    assert provider.calls == ["force_flush"]


def test_flush_logging_is_a_noop_without_an_installed_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(logger_core, "_otel_log_provider", None)
    assert drain.flush_logging(1.0) is True


def test_flush_logging_flushes_the_installed_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _RecordingProvider()
    monkeypatch.setattr(logger_core, "_otel_log_provider", provider)
    assert drain.flush_logging(1.0) is True
    assert provider.calls == ["force_flush"]


def _spy_bounded_flush(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """Replace bounded_provider_flush with a spy recording (provider, deadline).

    Pins the wiring so a refactor cannot drop the caller's deadline on the floor
    — a flush with no deadline blocks forever instead of returning False.
    """
    captured: dict[str, object] = {}

    def _spy(provider: object, timeout_seconds: float) -> bool:
        captured["provider"] = provider
        captured["timeout"] = timeout_seconds
        return True

    monkeypatch.setattr(drain, "bounded_provider_flush", _spy)
    return captured


def test_flush_tracing_passes_provider_and_deadline_to_the_bounded_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _spy_bounded_flush(monkeypatch)
    sentinel = _RecordingProvider()
    monkeypatch.setattr(tracing_provider, "_provider_ref", sentinel)

    assert drain.flush_tracing(3.5) is True
    assert captured["provider"] is sentinel
    assert captured["timeout"] == 3.5


def test_flush_metrics_passes_provider_and_deadline_to_the_bounded_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _spy_bounded_flush(monkeypatch)
    sentinel = _RecordingProvider()
    monkeypatch.setattr(metrics_provider, "_meter_provider", sentinel)

    assert drain.flush_metrics(2.25) is True
    assert captured["provider"] is sentinel
    assert captured["timeout"] == 2.25


def test_flush_logging_passes_provider_and_deadline_to_the_bounded_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _spy_bounded_flush(monkeypatch)
    sentinel = _RecordingProvider()
    monkeypatch.setattr(logger_core, "_otel_log_provider", sentinel)

    assert drain.flush_logging(0.75) is True
    assert captured["provider"] is sentinel
    assert captured["timeout"] == 0.75


# ── flush_telemetry ────────────────────────────────────────────────────


def _spy_signals(monkeypatch: pytest.MonkeyPatch, results: dict[str, bool]) -> list[tuple[str, float]]:
    """Replace the three per-signal drains with spies recording (signal, deadline)."""
    seen: list[tuple[str, float]] = []

    def _make(signal: str) -> Callable[[float], bool]:
        def _spy(timeout_seconds: float) -> bool:
            seen.append((signal, timeout_seconds))
            return results[signal]

        return _spy

    monkeypatch.setattr(drain, "flush_logging", _make("logs"))
    monkeypatch.setattr(drain, "flush_tracing", _make("traces"))
    monkeypatch.setattr(drain, "flush_metrics", _make("metrics"))
    return seen


def test_flushes_every_signal_and_reports_success(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _spy_signals(monkeypatch, {"logs": True, "traces": True, "metrics": True})
    assert flush_telemetry(timeout_seconds=2.5) is True
    assert [signal for signal, _ in seen] == ["logs", "traces", "metrics"]


def test_explicit_timeout_reaches_every_signal(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _spy_signals(monkeypatch, {"logs": True, "traces": True, "metrics": True})
    flush_telemetry(timeout_seconds=0.25)
    assert [deadline for _, deadline in seen] == [0.25, 0.25, 0.25]


def test_default_timeout_comes_from_the_bounded_shutdown_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    setup_telemetry(TelemetryConfig(exporter=ExporterPolicyConfig(logs_shutdown_timeout_seconds=1.75)))
    seen = _spy_signals(monkeypatch, {"logs": True, "traces": True, "metrics": True})
    flush_telemetry()
    assert [deadline for _, deadline in seen] == [1.75, 1.75, 1.75]


def test_reports_failure_when_any_signal_is_abandoned(monkeypatch: pytest.MonkeyPatch) -> None:
    _spy_signals(monkeypatch, {"logs": True, "traces": False, "metrics": True})
    assert flush_telemetry(timeout_seconds=1.0) is False


def test_a_signal_abandoned_at_the_deadline_does_not_deny_the_others_theirs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Kills a short-circuiting `all(...)` over a generator: logs failing first
    must not stop traces and metrics from being drained."""
    seen = _spy_signals(monkeypatch, {"logs": False, "traces": True, "metrics": True})
    assert flush_telemetry(timeout_seconds=1.0) is False
    assert [signal for signal, _ in seen] == ["logs", "traces", "metrics"]
