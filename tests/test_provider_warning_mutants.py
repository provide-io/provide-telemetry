# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests pinning operator-facing warning text emitted by the provider setup paths.

These warnings are the only signal an operator gets for two silent-failure modes:
provider setup blocking an event loop, and a drain being abandoned with records
still queued. The wording tells them what to change ("Call setup_telemetry()
before starting the event loop") and the drain text names the consequence
("records ... will be dropped"), so the strings are contract, not decoration.

stacklevel is captured off warnings.warn rather than read from the recorded
frame: mutmut runs mutated code through a trampoline that adds a stack frame, so
frame identity shifts under mutation while the passed argument does not.

Covers:
  tracing.provider.setup_tracing / metrics.provider.setup_metrics: event-loop warning
  _provider_drain._bounded_provider_call: saturation and abandoned-drain warnings
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from typing import Any

import pytest

from provide.telemetry import _provider_drain as drain_mod
from provide.telemetry.metrics import provider as metrics_provider
from provide.telemetry.tracing import provider as tracing_provider


def _capture_warn(monkeypatch: Any, module: Any) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def fake_warn(message: object, category: object = None, stacklevel: int = 1, **kw: Any) -> None:
        calls.append({"message": str(message), "category": category, "stacklevel": stacklevel})

    monkeypatch.setattr(module.warnings, "warn", fake_warn)
    return calls


@pytest.mark.parametrize(
    ("module", "setup_fn", "prefix"),
    [
        (tracing_provider, "setup_tracing", "setup_tracing()"),
        (metrics_provider, "setup_metrics", "setup_metrics()"),
    ],
    ids=["tracing", "metrics"],
)
def test_event_loop_setup_warning_text(monkeypatch: Any, module: Any, setup_fn: str, prefix: str) -> None:
    from provide.telemetry import resilience as resilience_mod

    calls = _capture_warn(monkeypatch, module)
    monkeypatch.setattr(resilience_mod, "_is_running_in_event_loop", lambda: True)

    from provide.telemetry.config import TelemetryConfig

    getattr(module, setup_fn)(TelemetryConfig())

    assert len(calls) >= 1
    assert calls[0]["message"] == (
        f"{prefix} called from an active event loop; "
        "provider initialization may stall the event loop. "
        "Call setup_telemetry() before starting the event loop."
    )
    assert calls[0]["category"] is RuntimeWarning
    assert calls[0]["stacklevel"] == 2


def test_no_event_loop_warning_outside_a_loop(monkeypatch: Any) -> None:
    from provide.telemetry import resilience as resilience_mod

    calls = _capture_warn(monkeypatch, tracing_provider)
    monkeypatch.setattr(resilience_mod, "_is_running_in_event_loop", lambda: False)

    from provide.telemetry.config import TelemetryConfig

    tracing_provider.setup_tracing(TelemetryConfig())

    # Filter to our own category: patching the shared warnings.warn also catches
    # unrelated third-party warnings raised during import.
    assert [c for c in calls if c["category"] is RuntimeWarning] == []


# ── _provider_drain warnings ────────────────────────────────────────────────


class _NoopProvider:
    def force_flush(self) -> None:
        return None

    def shutdown(self) -> None:
        return None


@pytest.fixture(autouse=True)
def _reset_drain() -> Iterator[None]:
    drain_mod._reset_abandoned_workers_for_tests()
    yield
    drain_mod._reset_abandoned_workers_for_tests()


def test_saturated_drain_declines_with_the_documented_message(monkeypatch: Any) -> None:
    calls = _capture_warn(monkeypatch, drain_mod)
    monkeypatch.setattr(drain_mod, "_abandoned_workers", drain_mod._MAX_ABANDONED_WORKERS)

    result = drain_mod._bounded_provider_call(
        _NoopProvider(), 1.0, ("force_flush",), "t", "flush", decline_when_saturated=True
    )

    assert result is False
    assert calls[0]["message"] == (
        f"provider flush skipped: {drain_mod._MAX_ABANDONED_WORKERS} earlier drain "
        "workers are still pending against an unresponsive exporter."
    )
    assert calls[0]["category"] is RuntimeWarning


def test_saturation_check_is_skipped_when_not_requested(monkeypatch: Any) -> None:
    """decline_when_saturated=False must not consult the budget at all.

    A None mutation is falsy and would behave the same, so this pairs with the
    saturated case above: the flag has to be honoured in both directions.
    """
    calls = _capture_warn(monkeypatch, drain_mod)
    monkeypatch.setattr(drain_mod, "_abandoned_workers", drain_mod._MAX_ABANDONED_WORKERS)

    result = drain_mod._bounded_provider_call(
        _NoopProvider(), 5.0, ("shutdown",), "t", "shutdown", decline_when_saturated=False
    )

    assert result is True, "an over-budget shutdown must still run"
    assert calls == []


def test_abandoned_drain_names_the_consequence(monkeypatch: Any) -> None:
    calls = _capture_warn(monkeypatch, drain_mod)

    finished = threading.Event()

    class _Slow:
        """Outlives the deadline, then finishes.

        Deliberately bounded rather than blocking indefinitely: `wait(None)` is a
        mutation of the deadline, and against a never-finishing worker it hangs,
        which mutmut reports as a timeout instead of a kill. A worker that
        finishes shortly after the deadline makes the mutated call return True
        with no warning, so the assertions below fail fast and kill it.
        """

        def force_flush(self) -> None:
            time.sleep(0.2)
            finished.set()

    result = drain_mod._bounded_provider_call(
        _Slow(), 0.01, ("force_flush",), "t", "flush", decline_when_saturated=False
    )
    # The abandoned worker decrements the budget on its way out, so it has to be
    # gone before the autouse reset runs — otherwise the counter goes negative
    # and leaks into whichever test runs next. Sync on the counter, not on the
    # worker's own event: the decrement happens after force_flush returns, so the
    # event fires marginally too early to be a safe barrier.
    assert finished.wait(timeout=5), "the stranded worker must finish"
    deadline = time.monotonic() + 5.0
    while drain_mod._abandoned_workers != 0 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert drain_mod._abandoned_workers == 0, "the budget must be settled before teardown"

    assert result is False
    assert calls[0]["message"] == (
        "provider flush exceeded 0.01s deadline; abandoning "
        "background flush. Records still in the export queue will be dropped."
    )
    assert calls[0]["category"] is RuntimeWarning
    assert calls[0]["stacklevel"] == 3


def test_incomplete_drain_names_every_reporting_method(monkeypatch: Any) -> None:
    """Multiple incomplete methods must be joined with ", ".

    A mangled separator runs the method names together, so the operator cannot
    tell which of the provider's drain calls reported records still queued.
    """
    calls = _capture_warn(monkeypatch, drain_mod)

    class _Incomplete:
        def force_flush(self) -> bool:
            return False

        def shutdown(self) -> bool:
            return False

    result = drain_mod._bounded_provider_call(
        _Incomplete(), 5.0, ("force_flush", "shutdown"), "t", "flush", decline_when_saturated=False
    )

    assert result is False
    assert calls[0]["message"] == (
        "provider flush reported an incomplete drain from force_flush, shutdown; records may still be queued."
    )


def test_shutdown_never_declines_for_want_of_budget(monkeypatch: Any) -> None:
    """bounded_provider_shutdown must pass decline_when_saturated=False.

    A None would be falsy in the same way, so this pins the call by observing the
    behaviour it selects: shutdown is the last chance to drain, and must run even
    when the abandoned-worker budget is exhausted.
    """
    calls = _capture_warn(monkeypatch, drain_mod)
    monkeypatch.setattr(drain_mod, "_abandoned_workers", drain_mod._MAX_ABANDONED_WORKERS)

    assert drain_mod.bounded_provider_shutdown(_NoopProvider(), 5.0) is True
    assert [c for c in calls if "skipped" in c["message"]] == []


# ── Cross-context runtime-context guard ─────────────────────────────────────


def _stub_context_runtime(monkeypatch: Any, install: object) -> None:
    """Put a fake context_runtime module in place of the OTel-only real one.

    ``setup_tracing`` imports it lazily, so replacing the sys.modules entry is
    enough — and it lets these tests run in the no-otel gate, where the real
    module cannot be imported at all.
    """
    import sys
    import types

    module = types.ModuleType("provide.telemetry.tracing.context_runtime")
    module.install_safe_runtime_context = install  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
    monkeypatch.setitem(sys.modules, "provide.telemetry.tracing.context_runtime", module)


def test_runtime_context_attribute_error_warns_and_setup_continues(monkeypatch: Any) -> None:
    """A renamed private OTel attribute costs the guard, not the setup.

    The swap reads ``opentelemetry.context._RUNTIME_CONTEXT`` and the runtime's
    ``_current_context``. Both are private, so an SDK that renames one raises
    AttributeError here — which must degrade to a warning naming the failure,
    never abort setup_tracing.
    """
    from provide.telemetry.config import TelemetryConfig

    def _raise() -> bool:
        raise AttributeError("_RUNTIME_CONTEXT")

    calls = _capture_warn(monkeypatch, tracing_provider)
    monkeypatch.setattr(tracing_provider, "_HAS_OTEL", True)
    _stub_context_runtime(monkeypatch, _raise)

    try:
        tracing_provider.setup_tracing(TelemetryConfig())
    finally:
        tracing_provider._reset_tracing_for_tests()

    warned = [c for c in calls if c["category"] is RuntimeWarning]
    assert len(warned) == 1
    assert warned[0]["message"] == (
        "cross-context-safe OTel runtime context unavailable, continuing without it: _RUNTIME_CONTEXT"
    )
    assert warned[0]["stacklevel"] == 2


def test_runtime_context_import_error_is_silent(monkeypatch: Any) -> None:
    """An absent SDK is the ordinary no-otel case: install is skipped without a word."""
    import sys

    from provide.telemetry.config import TelemetryConfig

    calls = _capture_warn(monkeypatch, tracing_provider)
    monkeypatch.setattr(tracing_provider, "_HAS_OTEL", True)
    # A None entry makes the lazy import raise ImportError even where the real
    # module is installed, so the test means the same thing in both gates.
    monkeypatch.setitem(sys.modules, "provide.telemetry.tracing.context_runtime", None)

    try:
        tracing_provider.setup_tracing(TelemetryConfig())
    finally:
        tracing_provider._reset_tracing_for_tests()

    assert [c for c in calls if c["category"] is RuntimeWarning] == []


def test_runtime_context_installed_when_available(monkeypatch: Any) -> None:
    """The ordinary path calls the installer exactly once and warns about nothing."""
    from provide.telemetry.config import TelemetryConfig

    installed: list[bool] = []

    calls = _capture_warn(monkeypatch, tracing_provider)
    monkeypatch.setattr(tracing_provider, "_HAS_OTEL", True)
    _stub_context_runtime(monkeypatch, lambda: installed.append(True))

    try:
        tracing_provider.setup_tracing(TelemetryConfig())
    finally:
        tracing_provider._reset_tracing_for_tests()

    assert installed == [True]
    assert [c for c in calls if c["category"] is RuntimeWarning] == []
