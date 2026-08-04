# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""FlushResult must say what actually happened, per signal.

Two ways the old shape lied to a caller:

* one aggregate bool was fanned out to all three signals, so an unreachable
  logs collector reported traces and metrics as timed out even though both
  drained inside the deadline; and
* ``not_owned`` was never set, so a provider a host application installed —
  which ``flush_telemetry`` deliberately does not drain — came back
  ``flushed=True`` with its records still in the host's batch processor.
"""

from __future__ import annotations

import pytest

from provide.telemetry import _provider_drain as drain
from provide.telemetry import runtime as runtime_mod
from provide.telemetry import setup as setup_mod
from provide.telemetry._runtime_types import SignalDrainOutcome, SignalFlushResult
from provide.telemetry.logger import core as logger_core
from provide.telemetry.metrics import provider as metrics_provider
from provide.telemetry.tracing import provider as tracing_provider


class _RecordingProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def force_flush(self) -> None:
        self.calls.append("force_flush")


# ── owned_signals ──────────────────────────────────────────────────────


def test_owned_signals_reports_only_providers_we_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tracing_provider, "_provider_ref", _RecordingProvider())
    monkeypatch.setattr(metrics_provider, "_meter_provider", None)
    monkeypatch.setattr(logger_core, "_otel_log_provider", None)

    assert drain.owned_signals() == {"logs": False, "traces": True, "metrics": False}


# ── flush_signals ──────────────────────────────────────────────────────


def test_flush_signals_reports_each_signal_independently(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(drain, "flush_logging", lambda _timeout: False)
    monkeypatch.setattr(drain, "flush_tracing", lambda _timeout: True)
    monkeypatch.setattr(drain, "flush_metrics", lambda _timeout: True)

    assert setup_mod.flush_signals(0.5) == {"logs": "timed_out", "traces": "flushed", "metrics": "flushed"}


def test_flush_signals_reports_a_raising_drain_as_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    """An exporter that raised never timed anything out — the two must not collapse."""

    def _boom(_timeout: float) -> bool:
        raise RuntimeError("exporter exploded")

    monkeypatch.setattr(drain, "flush_logging", _boom)
    monkeypatch.setattr(drain, "flush_tracing", lambda _timeout: True)
    monkeypatch.setattr(drain, "flush_metrics", lambda _timeout: False)

    assert setup_mod.flush_signals(0.5) == {"logs": "failed", "traces": "flushed", "metrics": "timed_out"}


def test_flush_telemetry_still_aggregates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(drain, "flush_logging", lambda _timeout: False)
    monkeypatch.setattr(drain, "flush_tracing", lambda _timeout: True)
    monkeypatch.setattr(drain, "flush_metrics", lambda _timeout: True)

    assert setup_mod.flush_telemetry(0.5) is False

    monkeypatch.setattr(drain, "flush_logging", lambda _timeout: True)
    assert setup_mod.flush_telemetry(0.5) is True


# ── the facade result ──────────────────────────────────────────────────


def test_one_failing_signal_is_not_reported_on_the_others(monkeypatch: pytest.MonkeyPatch) -> None:
    """Logs unreachable, traces and metrics healthy.

    Reporting all three as timed out makes a caller re-emit or alert on records
    that were already delivered.
    """
    monkeypatch.setattr(drain, "installed_signals", lambda: {"logs": True, "traces": True, "metrics": True})
    monkeypatch.setattr(
        drain,
        "owned_signals",
        lambda: {"logs": True, "traces": True, "metrics": True},
    )
    monkeypatch.setattr(
        setup_mod,
        "flush_signals",
        lambda timeout_seconds=None: {"logs": "timed_out", "traces": "flushed", "metrics": "flushed"},
    )

    result = runtime_mod.TelemetryRuntime().flush()

    assert result.logs == SignalFlushResult(flushed=False, timed_out=True)
    assert result.traces == SignalFlushResult(flushed=True)
    assert result.metrics == SignalFlushResult(flushed=True)


def test_a_host_owned_provider_reports_not_owned(monkeypatch: pytest.MonkeyPatch) -> None:
    """A host's own TracerProvider is installed but is not ours to drain."""
    monkeypatch.setattr(drain, "installed_signals", lambda: {"logs": True, "traces": True, "metrics": False})
    monkeypatch.setattr(
        drain,
        "owned_signals",
        lambda: {"logs": True, "traces": False, "metrics": False},
    )
    monkeypatch.setattr(
        setup_mod,
        "flush_signals",
        lambda timeout_seconds=None: {"logs": "flushed", "traces": "flushed", "metrics": "flushed"},
    )

    result = runtime_mod.TelemetryRuntime().flush()

    assert result.traces == SignalFlushResult(not_owned=True)
    assert result.traces.flushed is False
    assert result.logs == SignalFlushResult(flushed=True)
    assert result.metrics == SignalFlushResult(not_installed=True)


def test_flush_does_not_raise_on_a_malformed_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """flush() is a drain path: a SIGTERM handler in a process with a mis-set
    env var must get a FlushResult back, not a ConfigurationError.

    With no active config, get_runtime_status()'s config read would raise here —
    which is exactly why flush() must not go through it.
    """
    monkeypatch.setenv("PROVIDE_SAMPLING_LOGS_RATE", "banana")
    runtime_mod.reset_runtime_for_tests()

    from provide.telemetry._runtime_types import FlushResult

    assert isinstance(runtime_mod.flush(2.0), FlushResult)
    # The default-deadline path resolves its deadline without raising too.
    assert isinstance(runtime_mod.flush(), FlushResult)


def test_a_raising_exporter_reports_failed_not_timed_out(monkeypatch: pytest.MonkeyPatch) -> None:
    """A force_flush that raised in milliseconds never timed anything out.

    Go reports Failed for this and TimedOut only for a missed deadline —
    collapsing the two makes cross-language dashboards misclassify an outage.
    """

    class _Raising:
        def force_flush(self) -> None:
            raise RuntimeError("bad auth header")

    monkeypatch.setattr(logger_core, "_otel_log_provider", _Raising())
    monkeypatch.setattr(tracing_provider, "_provider_ref", None)
    monkeypatch.setattr(metrics_provider, "_meter_provider", None)
    monkeypatch.setattr(drain, "installed_signals", lambda: {"logs": True, "traces": False, "metrics": False})

    result = runtime_mod.TelemetryRuntime().flush(1.0)

    assert result.logs == SignalFlushResult(failed=True)
    assert result.logs.timed_out is False
    assert bool(result) is False


def test_a_hanging_exporter_reports_timed_out_not_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    import threading

    release = threading.Event()

    class _Hanging:
        def force_flush(self) -> None:
            release.wait(10.0)

    monkeypatch.setattr(logger_core, "_otel_log_provider", _Hanging())
    monkeypatch.setattr(tracing_provider, "_provider_ref", None)
    monkeypatch.setattr(metrics_provider, "_meter_provider", None)
    monkeypatch.setattr(drain, "installed_signals", lambda: {"logs": True, "traces": False, "metrics": False})

    try:
        result = runtime_mod.TelemetryRuntime().flush(0.05)
    finally:
        # Unblock the abandoned worker so it exits and gives its slot back.
        release.set()

    assert result.logs == SignalFlushResult(timed_out=True)
    assert result.logs.failed is False
    assert bool(result) is False


# ── FlushResult truthiness ─────────────────────────────────────────────


def test_flush_result_truthiness_preserves_the_bool_contract() -> None:
    """``if not telemetry.flush(): alert()`` predates the per-signal shape and
    must keep meaning what it did — an always-truthy result would permanently
    mask failed drains as success.
    """
    from provide.telemetry._runtime_types import FlushResult

    assert bool(FlushResult()) is True
    assert (
        bool(
            FlushResult(
                logs=SignalFlushResult(not_installed=True),
                traces=SignalFlushResult(not_owned=True),
                metrics=SignalFlushResult(flushed=True),
            )
        )
        is True
    )
    # Each signal and each failure kind must flip it on its own.
    assert bool(FlushResult(logs=SignalFlushResult(timed_out=True))) is False
    assert bool(FlushResult(traces=SignalFlushResult(timed_out=True))) is False
    assert bool(FlushResult(metrics=SignalFlushResult(timed_out=True))) is False
    assert bool(FlushResult(logs=SignalFlushResult(failed=True))) is False
    assert bool(FlushResult(traces=SignalFlushResult(failed=True))) is False
    assert bool(FlushResult(metrics=SignalFlushResult(failed=True))) is False


@pytest.mark.parametrize(
    ("installed", "owned", "outcome", "expected"),
    [
        (False, False, "flushed", SignalFlushResult(not_installed=True)),
        (False, True, "flushed", SignalFlushResult(not_installed=True)),
        (True, False, "flushed", SignalFlushResult(not_owned=True)),
        (True, True, "flushed", SignalFlushResult(flushed=True)),
        (True, True, "timed_out", SignalFlushResult(flushed=False, timed_out=True)),
        (True, True, "failed", SignalFlushResult(flushed=False, failed=True)),
    ],
)
def test_signal_flush_result_truth_table(
    installed: bool, owned: bool, outcome: SignalDrainOutcome, expected: SignalFlushResult
) -> None:
    assert runtime_mod._signal_flush_result(installed, owned, outcome) == expected
