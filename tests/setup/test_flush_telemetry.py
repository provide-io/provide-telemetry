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

import logging
from collections.abc import Callable

import pytest

from provide.telemetry import _provider_drain as drain
from provide.telemetry import flush_telemetry
from provide.telemetry.config import ExporterPolicyConfig, TelemetryConfig
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
    assert sorted(signal for signal, _ in seen) == ["logs", "metrics", "traces"]


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
    must not stop traces and metrics from being drained.

    Sorted, not ordered: the three drains run concurrently, so which finishes
    first is not part of the contract — that each one ran is.
    """
    seen = _spy_signals(monkeypatch, {"logs": False, "traces": True, "metrics": True})
    assert flush_telemetry(timeout_seconds=1.0) is False
    assert sorted(signal for signal, _ in seen) == ["logs", "metrics", "traces"]


# ── failure handling ───────────────────────────────────────────────────


def test_a_raising_signal_does_not_abort_the_others_or_escape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """bounded_provider_flush re-raises; flush_telemetry must not.

    The primitive's re-raise is right for a primitive and wrong for a public
    bool API called at a request boundary — the caller would get an unhandled
    exception in its handler and lose the two drains that never ran.
    """
    seen: list[str] = []

    def _boom(_timeout: float) -> bool:
        seen.append("logs")
        raise RuntimeError("exporter exploded")

    def _ok(signal: str) -> Callable[[float], bool]:
        def _spy(_timeout: float) -> bool:
            seen.append(signal)
            return True

        return _spy

    monkeypatch.setattr(drain, "flush_logging", _boom)
    monkeypatch.setattr(drain, "flush_tracing", _ok("traces"))
    monkeypatch.setattr(drain, "flush_metrics", _ok("metrics"))

    assert flush_telemetry(timeout_seconds=1.0) is False
    assert sorted(seen) == ["logs", "metrics", "traces"]


def test_declines_to_strand_more_workers_than_the_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """Repeated flushes against a dead exporter must not accumulate threads.

    flush_telemetry is documented for per-request use; without a cap each
    timed-out call strands another daemon thread in the exporter's retry loop
    until interpreter exit.
    """
    import threading
    import time

    from provide.telemetry import _provider_drain

    release = threading.Event()

    class _Hanging:
        def force_flush(self) -> None:
            release.wait(10.0)

    def _stuck() -> int:
        return len([t for t in threading.enumerate() if t.name == "provide-provider-flush"])

    # Start from a full budget, and measure the delta: earlier tests in this
    # process may have stranded workers of their own.
    _provider_drain._reset_abandoned_workers_for_tests()
    before = _stuck()
    try:
        attempts = _provider_drain._MAX_ABANDONED_WORKERS + 3
        results = [_provider_drain.bounded_provider_flush(_Hanging(), timeout_seconds=0.01) for _ in range(attempts)]
        assert all(r is False for r in results)
        # Past the budget we decline rather than spawn: at most the budget's
        # worth of new workers, not one per call.
        spawned = _stuck() - before
        assert spawned <= _provider_drain._MAX_ABANDONED_WORKERS
        assert spawned < attempts

        # Shutdown is the last chance to get queued records out, so a budget
        # spent by flushes must not disarm it.
        drained: list[str] = []

        class _Recording:
            def force_flush(self) -> None:
                drained.append("force_flush")

            def shutdown(self) -> None:
                drained.append("shutdown")

        assert _provider_drain.bounded_provider_shutdown(_Recording(), timeout_seconds=5.0) is True
        assert drained == ["force_flush", "shutdown"]
    finally:
        # Release first, then wait for every stranded worker to unwind before
        # zeroing the counter: they each decrement on the way out, so resetting
        # underneath them would drive the shared budget negative for the rest
        # of the session and silently disable the cap for later tests.
        release.set()
        deadline = time.monotonic() + 10.0
        while _stuck() > before and time.monotonic() < deadline:
            time.sleep(0.01)
        _provider_drain._reset_abandoned_workers_for_tests()


@pytest.mark.parametrize(
    ("signal", "attr"),
    [("logs", "flush_logging"), ("traces", "flush_tracing"), ("metrics", "flush_metrics")],
)
def test_a_failed_signal_is_reported_to_operators_with_its_name(
    signal: str, attr: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The swallowed exception must still be visible, and say which signal failed.

    Reporting False without naming the signal would turn an exporter fault into
    an unexplained boolean. Parametrised across all three because each carries
    its own label into the log record.
    """

    def _boom(_timeout: float) -> bool:
        raise RuntimeError("exporter exploded")

    for name in ("flush_logging", "flush_tracing", "flush_metrics"):
        monkeypatch.setattr(drain, name, _boom if name == attr else (lambda _t: True))

    with caplog.at_level(logging.WARNING, logger="provide.telemetry.setup"):
        assert flush_telemetry(timeout_seconds=1.0) is False

    records = [r for r in caplog.records if r.getMessage() == "telemetry.flush.signal_failed"]
    assert len(records) == 1
    # extra= fields land as dynamic LogRecord attributes, which mypy cannot see.
    assert getattr(records[0], "signal", None) == signal
    assert "exporter exploded" in getattr(records[0], "error", "")
