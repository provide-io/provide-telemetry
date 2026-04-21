# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Targeted tests that kill surviving mutmut mutants in ``setup_metrics``.

Each test pins a specific observable that distinguishes the real source from
a mutant in ``src/provide/telemetry/metrics/provider.py``:

* signal-literal mutations in ``run_with_resilience("metrics", ...)`` and
  ``wrap_exporter("metrics", ...)``
* ``or`` -> ``and`` race-discard guard flip
* ``getattr(provider, "shutdown", None)`` argument mutations (missing arg,
  positional ``None`` substitutions, attribute-name casing/sentinel)
* ``callable(shutdown)`` -> ``callable(None)``
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from provide.telemetry.config import TelemetryConfig
from provide.telemetry.metrics import provider as provider_mod
from provide.telemetry.metrics.provider import _set_meter_for_test, setup_metrics


def _fake_otel_api(**kw: Any) -> SimpleNamespace:
    kw.setdefault("get_meter_provider", lambda: None)
    return SimpleNamespace(**kw)


def _install_mock_components(
    monkeypatch: pytest.MonkeyPatch,
    *,
    provider: Any,
    mock_otel: SimpleNamespace,
) -> tuple[Mock, SimpleNamespace, Mock, Mock]:
    """Wire up component classes for setup_metrics() with the given provider."""
    provider_cls = Mock(return_value=provider)
    resource_cls = SimpleNamespace(create=Mock(return_value="res"))
    reader_cls = Mock(return_value="reader")
    exporter_cls = Mock(return_value="exporter")
    monkeypatch.setattr(provider_mod, "_HAS_OTEL_METRICS", True)
    monkeypatch.setattr(provider_mod, "_load_otel_metrics_api", lambda: mock_otel)
    monkeypatch.setattr(
        provider_mod,
        "_load_otel_metrics_components",
        lambda: (provider_cls, resource_cls, reader_cls, exporter_cls),
    )
    return provider_cls, resource_cls, reader_cls, exporter_cls


def test_setup_metrics_signal_literal_in_run_with_resilience(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kill mutants _18/_22/_23: run_with_resilience signal must be 'metrics'."""
    _set_meter_for_test(None)
    mock_otel = _fake_otel_api(set_meter_provider=Mock(), get_meter=Mock(return_value="meter"))
    _install_mock_components(monkeypatch, provider=Mock(), mock_otel=mock_otel)

    seen: list[Any] = []

    def _spy_run_with_resilience(signal: Any, op: Any) -> Any:
        seen.append(signal)
        return op()

    monkeypatch.setattr(provider_mod, "run_with_resilience", _spy_run_with_resilience)
    monkeypatch.setattr(provider_mod, "wrap_exporter", lambda _sig, inner: inner)
    setup_metrics(TelemetryConfig.from_env({"OTEL_EXPORTER_OTLP_ENDPOINT": "http://metrics"}))

    assert seen == ["metrics"], f"expected signal 'metrics', got {seen!r}"


def test_setup_metrics_signal_literal_in_wrap_exporter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kill mutants _35/_39/_40: wrap_exporter signal must be 'metrics'."""
    _set_meter_for_test(None)
    mock_otel = _fake_otel_api(set_meter_provider=Mock(), get_meter=Mock(return_value="meter"))
    _install_mock_components(monkeypatch, provider=Mock(), mock_otel=mock_otel)

    seen: list[Any] = []

    def _spy_wrap_exporter(signal: Any, inner: Any) -> Any:
        seen.append(signal)
        return inner

    monkeypatch.setattr(provider_mod, "run_with_resilience", lambda _sig, op: op())
    monkeypatch.setattr(provider_mod, "wrap_exporter", _spy_wrap_exporter)
    setup_metrics(TelemetryConfig.from_env({"OTEL_EXPORTER_OTLP_ENDPOINT": "http://metrics"}))

    assert seen == ["metrics"], f"expected signal 'metrics', got {seen!r}"


def _trigger_race_discard(
    monkeypatch: pytest.MonkeyPatch,
    provider: Any,
) -> None:
    """Install components such that the race-discard branch executes.

    The first lock captures ``gen = _setup_generation``. We bump
    ``_setup_generation`` during exporter construction so that by the
    time we re-enter the lock the condition
    ``_meter_provider is not None or _setup_generation != gen`` is True
    (via the ``!=`` clause), forcing the discard path.
    """
    mock_otel = _fake_otel_api(set_meter_provider=Mock(), get_meter=Mock(return_value="meter"))
    _install_mock_components(monkeypatch, provider=provider, mock_otel=mock_otel)

    def _bump_and_return(_signal: Any, op: Any) -> Any:
        provider_mod._setup_generation += 1
        return op()

    monkeypatch.setattr(provider_mod, "run_with_resilience", _bump_and_return)
    monkeypatch.setattr(provider_mod, "wrap_exporter", lambda _sig, inner: inner)


def test_setup_metrics_race_discard_calls_provider_shutdown(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kill getattr/callable mutants _55..59, _61, _62, _63.

    When the race-discard branch fires, the code must:
      1. compute ``shutdown = getattr(provider, "shutdown", None)`` against the
         real provider (not None, not a wrong name) and
      2. ``callable(shutdown)`` must evaluate the actual shutdown, not None.

    Mutants that substitute None for arg positions, rename the attr, or
    pass ``callable(None)`` will each skip the shutdown call OR raise
    TypeError, both of which break this assertion.
    """
    _set_meter_for_test(None)
    provider = Mock()
    _trigger_race_discard(monkeypatch, provider)

    setup_metrics(TelemetryConfig.from_env({"OTEL_EXPORTER_OTLP_ENDPOINT": "http://metrics"}))

    provider.shutdown.assert_called_once_with()
    # Our provider was discarded — _meter_provider stays None.
    assert provider_mod._meter_provider is None


def test_setup_metrics_race_discard_no_exception_when_provider_has_no_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Kill mutant _60: ``getattr(provider, "shutdown")`` without default.

    With no default, a provider lacking ``shutdown`` raises AttributeError;
    the real code (``getattr(..., None)``) returns None and bails cleanly.
    """
    _set_meter_for_test(None)
    provider = SimpleNamespace()  # no .shutdown attribute
    _trigger_race_discard(monkeypatch, provider)

    # Must not raise — real code returns None default, mutant _60 would AttributeError.
    setup_metrics(TelemetryConfig.from_env({"OTEL_EXPORTER_OTLP_ENDPOINT": "http://metrics"}))
    assert provider_mod._meter_provider is None


def test_setup_metrics_race_guard_uses_or_not_and(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kill mutant _52: ``or`` -> ``and`` in the race-discard guard.

    Trigger the branch via ``_meter_provider`` having been installed between
    the first lock (snapshot ``gen``) and the second — but keep generation
    unchanged.  With ``or`` the discard branch is taken and provider.shutdown
    is called; with ``and`` both clauses must be true so the discard is
    skipped, ``set_meter_provider`` is invoked on our provider and
    provider.shutdown is NOT called.
    """
    _set_meter_for_test(None)
    provider = Mock()
    mock_set_meter_provider = Mock()
    mock_otel = _fake_otel_api(
        set_meter_provider=mock_set_meter_provider,
        get_meter=Mock(return_value="meter"),
    )
    _install_mock_components(monkeypatch, provider=provider, mock_otel=mock_otel)

    sentinel = object()

    def _install_external_provider(_signal: Any, op: Any) -> Any:
        # Simulate another thread having installed a provider between the
        # first lock release and the second lock acquisition. Generation
        # stays equal to `gen`, so only the left-hand clause of the guard
        # fires — which distinguishes `or` from `and`.
        provider_mod._meter_provider = sentinel
        return op()

    monkeypatch.setattr(provider_mod, "run_with_resilience", _install_external_provider)
    monkeypatch.setattr(provider_mod, "wrap_exporter", lambda _sig, inner: inner)

    setup_metrics(TelemetryConfig.from_env({"OTEL_EXPORTER_OTLP_ENDPOINT": "http://metrics"}))

    # Discard path taken: our provider was shut down, global setter never called
    # on it, and the "other thread's" sentinel is still installed.
    provider.shutdown.assert_called_once_with()
    mock_set_meter_provider.assert_not_called()
    assert provider_mod._meter_provider is sentinel
    # Clean up so global module state doesn't leak.
    _set_meter_for_test(None)
