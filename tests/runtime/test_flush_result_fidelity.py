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
from provide.telemetry._runtime_types import RuntimeStatus, SignalFlushResult
from provide.telemetry.logger import core as logger_core
from provide.telemetry.metrics import provider as metrics_provider
from provide.telemetry.tracing import provider as tracing_provider


class _RecordingProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def force_flush(self) -> None:
        self.calls.append("force_flush")


def _status(**providers: bool) -> RuntimeStatus:
    return RuntimeStatus(
        setup_done=True,
        signals={"logs": True, "traces": True, "metrics": True},
        providers=dict(providers),
        fallback={signal: not on for signal, on in providers.items()},
        setup_error=None,
    )


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

    assert setup_mod.flush_signals(0.5) == {"logs": False, "traces": True, "metrics": True}


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
    monkeypatch.setattr(runtime_mod, "get_runtime_status", lambda: _status(logs=True, traces=True, metrics=True))
    monkeypatch.setattr(
        drain,
        "owned_signals",
        lambda: {"logs": True, "traces": True, "metrics": True},
    )
    monkeypatch.setattr(
        setup_mod,
        "flush_signals",
        lambda timeout_seconds=None: {"logs": False, "traces": True, "metrics": True},
    )

    result = runtime_mod.TelemetryRuntime().flush()

    assert result.logs == SignalFlushResult(flushed=False, timed_out=True)
    assert result.traces == SignalFlushResult(flushed=True)
    assert result.metrics == SignalFlushResult(flushed=True)


def test_a_host_owned_provider_reports_not_owned(monkeypatch: pytest.MonkeyPatch) -> None:
    """A host's own TracerProvider is installed but is not ours to drain."""
    monkeypatch.setattr(runtime_mod, "get_runtime_status", lambda: _status(logs=True, traces=True, metrics=False))
    monkeypatch.setattr(
        drain,
        "owned_signals",
        lambda: {"logs": True, "traces": False, "metrics": False},
    )
    monkeypatch.setattr(
        setup_mod,
        "flush_signals",
        lambda timeout_seconds=None: {"logs": True, "traces": True, "metrics": True},
    )

    result = runtime_mod.TelemetryRuntime().flush()

    assert result.traces == SignalFlushResult(not_owned=True)
    assert result.traces.flushed is False
    assert result.logs == SignalFlushResult(flushed=True)
    assert result.metrics == SignalFlushResult(not_installed=True)


@pytest.mark.parametrize(
    ("installed", "owned", "drained", "expected"),
    [
        (False, False, True, SignalFlushResult(not_installed=True)),
        (False, True, True, SignalFlushResult(not_installed=True)),
        (True, False, True, SignalFlushResult(not_owned=True)),
        (True, True, True, SignalFlushResult(flushed=True)),
        (True, True, False, SignalFlushResult(flushed=False, timed_out=True)),
    ],
)
def test_signal_flush_result_truth_table(
    installed: bool, owned: bool, drained: bool, expected: SignalFlushResult
) -> None:
    assert runtime_mod._signal_flush_result(installed, owned, drained) == expected
