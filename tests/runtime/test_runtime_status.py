# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

from __future__ import annotations

import dataclasses

import pytest

from provide.telemetry import get_logger
from provide.telemetry._lifecycle import coordinator
from provide.telemetry.logger import core as logger_core
from provide.telemetry.metrics import provider as metrics_provider
from provide.telemetry.runtime import get_runtime_status
from provide.telemetry.setup import _reset_all_for_tests
from provide.telemetry.tracing import provider as tracing_provider


@pytest.fixture(autouse=True)
def reset_full_setup_state() -> None:
    _reset_all_for_tests()


@pytest.fixture(autouse=True)
def no_foreign_otel_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the premise these tests are written against: nobody else's provider.

    ``providers.traces`` / ``providers.metrics`` report what is in play, which
    includes a provider a host application installed on the OTel global. A test
    process is such a host — the OTel SDK honours set_tracer_provider once per
    process and offers no way to undo it, so a provider another test installed
    would otherwise leak in here. Tests that want a provider install one of
    *ours* (``_provider_ref`` / ``_meter_provider``), which is read directly.
    """
    monkeypatch.setattr(tracing_provider, "_load_otel_trace_api", lambda: None)
    monkeypatch.setattr(metrics_provider, "_load_otel_metrics_api", lambda: None)


def test_get_runtime_status_defaults_to_fallback_before_setup() -> None:
    status = get_runtime_status()

    assert status.setup_done is False
    assert status.providers == {"logs": False, "traces": False, "metrics": False}
    assert status.fallback == {"logs": True, "traces": True, "metrics": True}


def test_get_runtime_status_reports_provider_and_signal_state(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeLogProvider:
        pass

    class _FakeMeterProvider:
        pass

    coordinator.publish_setup_state(setup_done=True)
    monkeypatch.setattr(logger_core, "_otel_log_provider", _FakeLogProvider())
    monkeypatch.setattr(tracing_provider, "_provider_ref", None)
    monkeypatch.setattr(metrics_provider, "_meter_provider", _FakeMeterProvider())

    status = get_runtime_status()

    assert status.setup_done is True
    assert status.signals == {"logs": True, "traces": True, "metrics": True}
    assert status.providers == {"logs": True, "traces": False, "metrics": True}
    assert status.fallback == {"logs": False, "traces": True, "metrics": False}


def test_get_runtime_status_clears_provider_state_after_shutdown(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeLogProvider:
        def force_flush(self) -> None:
            pass

        def shutdown(self) -> None:
            pass

    class _FakeTraceProvider:
        def shutdown(self) -> None:
            pass

    class _FakeMeterProvider:
        def shutdown(self) -> None:
            pass

    monkeypatch.setattr(logger_core, "_otel_log_provider", _FakeLogProvider())
    monkeypatch.setattr(logger_core, "_otel_log_global_set", True)
    monkeypatch.setattr(tracing_provider, "_provider_ref", _FakeTraceProvider())
    monkeypatch.setattr(tracing_provider, "_otel_global_set", True)
    monkeypatch.setattr(metrics_provider, "_meter_provider", _FakeMeterProvider())
    monkeypatch.setattr(metrics_provider, "_meter_global_set", True)

    from provide.telemetry.setup import shutdown_telemetry

    shutdown_telemetry()

    status = get_runtime_status()

    assert status.providers == {"logs": False, "traces": False, "metrics": False}
    assert status.fallback == {"logs": True, "traces": True, "metrics": True}


def test_get_runtime_status_lazy_logger_does_not_mark_setup_done() -> None:
    get_logger("lazy.runtime.status")

    status = get_runtime_status()

    assert status.setup_done is False


def test_get_runtime_status_traces_provider_true(monkeypatch: pytest.MonkeyPatch) -> None:
    """When tracing provider is installed, providers.traces must be True.

    Kills get_runtime_status mutmut_9: bool(tracing_provider._has_live_tracing_provider()) → bool(None).
    bool(None) is always False, so this mutant would report traces=False even when provider is active.
    """

    class _FakeTraceProvider:
        pass

    coordinator.publish_setup_state(setup_done=True)
    monkeypatch.setattr(tracing_provider, "_provider_ref", _FakeTraceProvider())

    status = get_runtime_status()

    assert status.providers["traces"] is True
    assert status.fallback["traces"] is False


def test_get_runtime_status_setup_error_key_name() -> None:
    """The status dict must have 'setup_error' key (exact case).

    Kills get_runtime_status mutmut_29: "setup_error" → "XXsetup_errorXX".
    Kills get_runtime_status mutmut_30: "setup_error" → "SETUP_ERROR".
    """
    status = get_runtime_status()

    fields = {f.name for f in dataclasses.fields(status)}
    assert "setup_error" in fields, f"Expected 'setup_error' field, got: {sorted(fields)}"
    assert "XXsetup_errorXX" not in fields
    assert "SETUP_ERROR" not in fields
