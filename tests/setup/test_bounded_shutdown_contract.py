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
from collections.abc import Callable

import pytest

from provide.telemetry import _provider_drain as drain
from provide.telemetry import setup as setup_mod
from provide.telemetry._lifecycle import coordinator
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
    coordinator.publish_setup_state(setup_done=True)
    monkeypatch.setenv("PROVIDE_LOG_INCLUDE_TIMESTAMP", "not-a-bool")
    coordinator.reset()

    setup_mod.shutdown_telemetry()

    assert coordinator.peek().setup_done is False


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
    teardown: Callable[[float], None],
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
        teardown(0.05)
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

    coordinator.publish_setup_state(setup_done=True)
    monkeypatch.setattr(tracing_provider, "_provider_ref", _CountingProvider())
    monkeypatch.setattr(metrics_provider, "_meter_provider", None)
    monkeypatch.setattr(logger_core, "_otel_log_provider", None)

    setup_mod.shutdown_telemetry(0.5)

    assert calls == ["force_flush", "shutdown"]


# ── the deadline is one budget, not one per signal ─────────────────────


def test_three_stalled_providers_share_the_callers_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The budget is for the call, not for each signal in turn.

    Run sequentially the three teardowns each take the whole deadline, so a
    SIGTERM handler that passed the 5s it had left waits 15s and is SIGKILLed
    with records still queued. Run together they cost one deadline.
    """
    providers = [_HangingProvider() for _ in range(3)]
    coordinator.publish_setup_state(setup_done=True)
    monkeypatch.setattr(tracing_provider, "_provider_ref", providers[0])
    monkeypatch.setattr(metrics_provider, "_meter_provider", providers[1])
    monkeypatch.setattr(logger_core, "_otel_log_provider", providers[2])

    started = time.monotonic()
    try:
        setup_mod.shutdown_telemetry(0.2)
        elapsed = time.monotonic() - started
    finally:
        for provider in providers:
            provider.release.set()
        drain._reset_abandoned_workers_for_tests()

    # Sequential would be ~0.6s. Bounded well below that, and at or above the
    # deadline itself so the assertion still fails if nothing was drained.
    assert 0.2 <= elapsed < 0.45, f"three stalled teardowns took {elapsed:.2f}s"
    for provider in providers:
        assert provider.calls[0] == "force_flush"


def test_three_stalled_flushes_share_the_callers_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """flush_signals is bounded the same way, and still answers per signal."""
    providers = [_HangingProvider() for _ in range(3)]
    monkeypatch.setattr(tracing_provider, "_provider_ref", providers[0])
    monkeypatch.setattr(metrics_provider, "_meter_provider", providers[1])
    monkeypatch.setattr(logger_core, "_otel_log_provider", providers[2])

    started = time.monotonic()
    try:
        drained = setup_mod.flush_signals(0.2)
        elapsed = time.monotonic() - started
    finally:
        for provider in providers:
            provider.release.set()
        drain._reset_abandoned_workers_for_tests()

    assert drained == {"logs": "timed_out", "traces": "timed_out", "metrics": "timed_out"}
    assert 0.2 <= elapsed < 0.45, f"three stalled flushes took {elapsed:.2f}s"


# ── run_drains_together ────────────────────────────────────────────────


def test_every_drain_runs_even_though_one_raises() -> None:
    """One exporter raising must not cost the other two their teardown.

    The exception still reaches the caller — a sequential call would have
    surfaced it — but only after every drain has had its turn.
    """
    ran: list[str] = []

    def _boom() -> None:
        ran.append("boom")
        raise RuntimeError("exporter exploded")

    with pytest.raises(RuntimeError, match="exporter exploded"):
        drain.run_drains_together(
            (
                lambda: ran.append("first"),
                _boom,
                lambda: ran.append("last"),
            )
        )

    assert sorted(ran) == ["boom", "first", "last"]


def test_the_first_error_is_the_one_raised() -> None:
    """Two failures report the one that happened first, not the last."""

    def _first() -> None:
        raise ValueError("first")

    def _second() -> None:
        # Ordered well behind _first so which one is "first" is unambiguous.
        time.sleep(0.2)
        raise ValueError("second")

    with pytest.raises(ValueError, match="first"):
        drain.run_drains_together((_first, _second))


def test_a_drain_still_runs_when_no_thread_can_be_started(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """At the process thread limit, tear down inline rather than not at all.

    Slower than the concurrent path, but a provider that never shuts down
    strands its exporter and its queued records for the life of the process.
    """
    ran: list[str] = []

    def _refuse(self: threading.Thread) -> None:
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(threading.Thread, "start", _refuse)

    drain.run_drains_together((lambda: ran.append("a"), lambda: ran.append("b")))

    assert ran == ["a", "b"]


def test_an_inline_drain_still_reports_its_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The spawn-failure fallback must not swallow what the drain raised."""

    def _refuse(self: threading.Thread) -> None:
        raise RuntimeError("can't start new thread")

    def _boom() -> None:
        raise ValueError("inline exploded")

    monkeypatch.setattr(threading.Thread, "start", _refuse)

    with pytest.raises(ValueError, match="inline exploded"):
        drain.run_drains_together((_boom,))


def test_teardown_threads_are_named_for_operator_visibility() -> None:
    """A stuck teardown shows up in py-spy/faulthandler under its own name."""
    names: list[str] = []

    drain.run_drains_together((lambda: names.append(threading.current_thread().name),))

    assert names == ["provide-provider-teardown"]


def test_teardown_threads_are_daemons() -> None:
    """A teardown worker must not be able to block interpreter exit.

    The join below is unbounded, so in the normal path daemon-ness never shows.
    It shows when the join itself is interrupted — a Ctrl-C during a shutdown
    that is waiting on an unreachable collector leaves the workers running, and
    non-daemon threads would then hold the process open at exit, turning an
    interrupted shutdown into a hang.
    """
    observed: list[bool] = []

    drain.run_drains_together((lambda: observed.append(threading.current_thread().daemon),))

    assert observed == [True]
