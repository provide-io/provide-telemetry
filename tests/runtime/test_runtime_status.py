# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

from __future__ import annotations

import pytest

from provide.telemetry import get_logger
from provide.telemetry.logger import core as logger_core
from provide.telemetry.metrics import provider as metrics_provider
from provide.telemetry.runtime import get_runtime_status
from provide.telemetry.setup import _reset_all_for_tests, setup_telemetry
from provide.telemetry.tracing import provider as tracing_provider


@pytest.fixture(autouse=True)
def reset_full_setup_state() -> None:
    _reset_all_for_tests()


def test_get_runtime_status_defaults_to_fallback_before_setup() -> None:
    status = get_runtime_status()

    assert status["setup_done"] is False
    assert status["providers"] == {"logs": False, "traces": False, "metrics": False}
    assert status["fallback"] == {"logs": True, "traces": True, "metrics": True}


def test_get_runtime_status_reports_provider_and_signal_state(monkeypatch: pytest.MonkeyPatch) -> None:
    setup_telemetry()
    monkeypatch.setattr(logger_core, "_has_otel_log_provider", lambda: True)
    monkeypatch.setattr(tracing_provider, "_has_tracing_provider", lambda: False)
    monkeypatch.setattr(metrics_provider, "_has_meter_provider", lambda: True)

    status = get_runtime_status()

    assert status["setup_done"] is True
    assert status["signals"] == {"logs": True, "traces": True, "metrics": True}
    assert status["providers"] == {"logs": True, "traces": False, "metrics": True}
    assert status["fallback"] == {"logs": False, "traces": True, "metrics": False}


def test_get_runtime_status_lazy_logger_does_not_mark_setup_done() -> None:
    get_logger("lazy.runtime.status")

    status = get_runtime_status()

    assert status["setup_done"] is False


def test_get_runtime_status_traces_provider_true(monkeypatch: pytest.MonkeyPatch) -> None:
    """When tracing provider is installed, providers.traces must be True.

    Kills get_runtime_status mutmut_9: bool(tracing_provider._has_tracing_provider()) → bool(None).
    bool(None) is always False, so this mutant would report traces=False even when provider is active.
    """
    setup_telemetry()
    monkeypatch.setattr(tracing_provider, "_has_tracing_provider", lambda: True)

    status = get_runtime_status()

    assert status["providers"]["traces"] is True  # type: ignore
    assert status["fallback"]["traces"] is False  # type: ignore


def test_get_runtime_status_setup_error_key_name() -> None:
    """The status dict must have 'setup_error' key (exact case).

    Kills get_runtime_status mutmut_29: "setup_error" → "XXsetup_errorXX".
    Kills get_runtime_status mutmut_30: "setup_error" → "SETUP_ERROR".
    """
    status = get_runtime_status()

    assert "setup_error" in status, f"Expected 'setup_error' key, got keys: {list(status.keys())}"
    assert "XXsetup_errorXX" not in status
    assert "SETUP_ERROR" not in status
