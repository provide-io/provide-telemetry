# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Targeted tests that kill surviving mutmut mutants in ``setup_tracing``.

Each test pins a specific observable that distinguishes the real source from
a mutant in ``src/provide/telemetry/tracing/provider.py``:

* signal-literal mutation in ``wrap_exporter("traces", ...)``
* ``or`` -> ``and`` race-discard guard flip
* ``getattr(provider, "shutdown", None)`` argument mutations
* ``callable(shutdown)`` -> ``callable(None)``
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from provide.telemetry import resilience as resilience_mod
from provide.telemetry import resilient_exporter as resilient_exporter_mod
from provide.telemetry.config import TelemetryConfig
from provide.telemetry.tracing import provider as provider_mod
from provide.telemetry.tracing.provider import _reset_tracing_for_tests


def _install_mock_components(
    monkeypatch: pytest.MonkeyPatch,
    *,
    provider: Any,
    mock_otel: SimpleNamespace,
) -> tuple[SimpleNamespace, Mock, Mock, Mock]:
    """Wire up component classes for setup_tracing() with the given provider."""
    resource_cls = SimpleNamespace(create=Mock(return_value="res"))
    provider_cls = Mock(return_value=provider)
    processor_cls = Mock(return_value="processor")
    exporter_cls = Mock(return_value="exporter")
    monkeypatch.setattr(provider_mod, "_HAS_OTEL", True)
    monkeypatch.setattr(provider_mod, "_load_otel_trace_api", lambda: mock_otel)
    monkeypatch.setattr(
        provider_mod,
        "_load_otel_tracing_components",
        lambda: (resource_cls, provider_cls, processor_cls, exporter_cls),
    )
    return resource_cls, provider_cls, processor_cls, exporter_cls


def test_setup_tracing_signal_literal_in_wrap_exporter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kill mutants _50/_54/_55: wrap_exporter signal must be 'traces'."""
    _reset_tracing_for_tests()
    mock_otel = SimpleNamespace(set_tracer_provider=Mock(), get_tracer_provider=lambda: None)
    provider = Mock()
    _install_mock_components(monkeypatch, provider=provider, mock_otel=mock_otel)

    seen: list[Any] = []

    def _spy_wrap_exporter(signal: Any, inner: Any) -> Any:
        seen.append(signal)
        return inner

    monkeypatch.setattr(resilience_mod, "run_with_resilience", lambda _sig, op: op())
    monkeypatch.setattr(resilient_exporter_mod, "wrap_exporter", _spy_wrap_exporter)
    setup_tracing = provider_mod.setup_tracing
    setup_tracing(TelemetryConfig.from_env({"OTEL_EXPORTER_OTLP_ENDPOINT": "http://trace"}))

    assert seen == ["traces"], f"expected signal 'traces', got {seen!r}"


def _trigger_race_discard(monkeypatch: pytest.MonkeyPatch, provider: Any) -> None:
    """Bump _setup_generation during exporter construction so the
    second lock sees ``_setup_generation != gen`` and takes the
    discard path in setup_tracing()."""
    mock_otel = SimpleNamespace(set_tracer_provider=Mock(), get_tracer_provider=lambda: None)
    _install_mock_components(monkeypatch, provider=provider, mock_otel=mock_otel)

    def _bump_and_return(_signal: Any, op: Any) -> Any:
        provider_mod._setup_generation += 1
        return op()

    monkeypatch.setattr(resilience_mod, "run_with_resilience", _bump_and_return)
    monkeypatch.setattr(resilient_exporter_mod, "wrap_exporter", lambda _sig, inner: inner)


def test_setup_tracing_race_discard_calls_provider_shutdown(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kill getattr/callable mutants _58, _59, _60, _61, _62, _64, _65, _66.

    The race-discard branch must compute
    ``getattr(provider, "shutdown", None)`` against the real provider with
    the correct attribute name, and must pass the actual attr to
    ``callable(...)``. Every mutant either returns a non-callable None
    (shutdown skipped) or raises TypeError.
    """
    _reset_tracing_for_tests()
    provider = Mock()
    _trigger_race_discard(monkeypatch, provider)

    provider_mod.setup_tracing(TelemetryConfig.from_env({"OTEL_EXPORTER_OTLP_ENDPOINT": "http://trace"}))

    provider.shutdown.assert_called_once_with()
    assert provider_mod._provider_ref is None
    assert provider_mod._provider_configured is False


def test_setup_tracing_race_discard_no_exception_when_provider_has_no_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Kill mutant _63: ``getattr(provider, "shutdown")`` without default.

    Without the ``None`` default, a provider that lacks ``shutdown`` raises
    AttributeError; the real code returns None and returns cleanly.
    """
    _reset_tracing_for_tests()
    # Provider must satisfy the ``add_span_processor`` call but MUST NOT expose
    # a ``shutdown`` attribute — that's the whole point of this test.
    provider = SimpleNamespace(add_span_processor=lambda _proc: None)
    assert not hasattr(provider, "shutdown")
    _trigger_race_discard(monkeypatch, provider)

    # Must not raise — real code returns None default, mutant _63 would AttributeError.
    provider_mod.setup_tracing(TelemetryConfig.from_env({"OTEL_EXPORTER_OTLP_ENDPOINT": "http://trace"}))
    assert provider_mod._provider_ref is None
    assert provider_mod._provider_configured is False


def test_setup_tracing_race_guard_uses_or_not_and(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kill mutant _56: ``or`` -> ``and`` in the race-discard guard.

    We set ``_provider_configured = True`` *after* the first-lock snapshot
    but before the second-lock check, keeping ``_setup_generation`` equal
    to the snapshot.  With ``or`` the discard path is taken (provider
    shutdown, global setter not called); with ``and`` both clauses must
    be true so the discard is skipped.

    We can't flip ``_provider_configured`` mid-flight without a thread,
    but we can install a fresh provider reference and rely on the
    fact that ``_provider_configured`` is checked *inside* the lock.
    So instead we trigger the discard via the other arm (generation
    bump) plus a sentinel check: under ``and``, the *guard itself*
    would incorrectly fall through to set_tracer_provider unless
    *both* sides are true.

    Setting ``_provider_configured = True`` as part of the side-effect
    during exporter construction makes the guard evaluate:
      - real (or): True or (gen==gen_snap) -> True -> discard
      - mutant (and): True and (gen==gen_snap) -> True and False... wait.

    Simpler: bump _provider_configured=True AND leave generation unchanged.
      - real (or): True or False -> True  -> discard (shutdown called)
      - mutant (and): True and False -> False -> no discard -> set_tracer_provider
        is called on our provider.
    """
    _reset_tracing_for_tests()
    provider = Mock()
    mock_set_tracer_provider = Mock()
    mock_otel = SimpleNamespace(
        set_tracer_provider=mock_set_tracer_provider,
        get_tracer_provider=lambda: None,
    )
    _install_mock_components(monkeypatch, provider=provider, mock_otel=mock_otel)

    def _install_external_configured(_signal: Any, op: Any) -> Any:
        # Simulate another thread finishing setup between the first lock
        # release and our second lock acquisition. Generation is unchanged
        # so only the left-hand clause of the guard is true — which
        # distinguishes ``or`` from ``and``.
        provider_mod._provider_configured = True
        return op()

    monkeypatch.setattr(resilience_mod, "run_with_resilience", _install_external_configured)
    monkeypatch.setattr(resilient_exporter_mod, "wrap_exporter", lambda _sig, inner: inner)

    provider_mod.setup_tracing(TelemetryConfig.from_env({"OTEL_EXPORTER_OTLP_ENDPOINT": "http://trace"}))

    # Discard path: our provider was shut down and the global setter was NOT
    # called for it.
    provider.shutdown.assert_called_once_with()
    mock_set_tracer_provider.assert_not_called()
    # Clean up leaked state.
    _reset_tracing_for_tests()
