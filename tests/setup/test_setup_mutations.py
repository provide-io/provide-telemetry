# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Tests targeting surviving mutation-testing mutants in setup.py.

Key mutants: string key mutations in _rollback teardowns dict,
completed.append() arg mutations, and SLO metric argument mutations.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from undef.telemetry.config import SLOConfig, TelemetryConfig
from undef.telemetry.setup import _reset_setup_state_for_tests, _rollback, setup_telemetry


@pytest.fixture(autouse=True)
def _reset() -> None:
    _reset_setup_state_for_tests()


# ---------------------------------------------------------------------------
# _rollback: string key mutations in teardowns dict
# ---------------------------------------------------------------------------


def test_rollback_calls_shutdown_metrics_when_setup_metrics_completed() -> None:
    """Kill mutant: 'setup_metrics' -> 'XXsetup_metricsXX' or 'SETUP_METRICS'.

    If the key is mutated, _rollback won't find the teardown for setup_metrics
    and will raise KeyError.
    """
    mock_shutdown_logging = MagicMock()
    mock_shutdown_tracing = MagicMock()
    mock_shutdown_metrics = MagicMock()

    with (
        pytest.MonkeyPatch.context() as mp,
    ):
        mp.setattr("undef.telemetry.setup.shutdown_logging", mock_shutdown_logging)
        mp.setattr("undef.telemetry.setup.shutdown_tracing", mock_shutdown_tracing)
        mp.setattr("undef.telemetry.setup.shutdown_metrics", mock_shutdown_metrics)

        _rollback(["configure_logging", "setup_tracing", "setup_metrics"])

    # All three shutdowns called in reverse order
    mock_shutdown_metrics.assert_called_once()
    mock_shutdown_tracing.assert_called_once()
    mock_shutdown_logging.assert_called_once()


def test_rollback_reverse_order() -> None:
    """Verify rollback calls teardowns in reverse order of completion."""
    order: list[str] = []

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("undef.telemetry.setup.shutdown_logging", lambda: order.append("logging"))
        mp.setattr("undef.telemetry.setup.shutdown_tracing", lambda: order.append("tracing"))
        mp.setattr("undef.telemetry.setup.shutdown_metrics", lambda: order.append("metrics"))

        _rollback(["configure_logging", "setup_tracing", "setup_metrics"])

    assert order == ["metrics", "tracing", "logging"]


def test_rollback_only_completed_steps() -> None:
    """Only roll back steps that were actually completed."""
    mock_shutdown_logging = MagicMock()
    mock_shutdown_tracing = MagicMock()
    mock_shutdown_metrics = MagicMock()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("undef.telemetry.setup.shutdown_logging", mock_shutdown_logging)
        mp.setattr("undef.telemetry.setup.shutdown_tracing", mock_shutdown_tracing)
        mp.setattr("undef.telemetry.setup.shutdown_metrics", mock_shutdown_metrics)

        _rollback(["configure_logging"])

    mock_shutdown_logging.assert_called_once()
    mock_shutdown_tracing.assert_not_called()
    mock_shutdown_metrics.assert_not_called()


# ---------------------------------------------------------------------------
# setup_telemetry: completed.append() arg mutations
# ---------------------------------------------------------------------------


def test_setup_metrics_failure_triggers_rollback_of_logging_and_tracing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Kill mutant: completed.append(None) or append('XXsetup_metricsXX').

    When setup_metrics fails, the completed list should contain
    'configure_logging' and 'setup_tracing', so their teardowns are called.
    The key thing: if append args are mutated, rollback will fail with KeyError.
    """
    shutdown_calls: list[str] = []

    monkeypatch.setattr("undef.telemetry.setup.apply_runtime_config", lambda _: None)
    monkeypatch.setattr("undef.telemetry.setup.configure_logging", lambda _: None)
    monkeypatch.setattr("undef.telemetry.setup._refresh_otel_tracing", lambda: None)
    monkeypatch.setattr("undef.telemetry.setup._refresh_otel_metrics", lambda: None)
    monkeypatch.setattr("undef.telemetry.setup.setup_tracing", lambda _: None)
    monkeypatch.setattr(
        "undef.telemetry.setup.setup_metrics",
        lambda _: (_ for _ in ()).throw(RuntimeError("metrics_boom")),
    )
    monkeypatch.setattr(
        "undef.telemetry.setup.shutdown_logging",
        lambda: shutdown_calls.append("logging"),
    )
    monkeypatch.setattr(
        "undef.telemetry.setup.shutdown_tracing",
        lambda: shutdown_calls.append("tracing"),
    )
    monkeypatch.setattr(
        "undef.telemetry.setup.shutdown_metrics",
        lambda: shutdown_calls.append("metrics"),
    )

    with pytest.raises(RuntimeError, match="metrics_boom"):
        setup_telemetry()

    # Logging and tracing completed, so both should be rolled back
    assert "logging" in shutdown_calls
    assert "tracing" in shutdown_calls
    # Metrics did not complete, so shutdown_metrics should NOT be called
    assert "metrics" not in shutdown_calls


# ---------------------------------------------------------------------------
# setup_telemetry: SLO record_red_metrics exact args
# ---------------------------------------------------------------------------


def test_setup_telemetry_slo_red_metrics_exact_args(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kill mutants that change record_red_metrics args.

    Expected: record_red_metrics("startup", "INIT", 200, 0.0)
    """
    red_mock = MagicMock()
    monkeypatch.setattr("undef.telemetry.setup.apply_runtime_config", lambda _: None)
    monkeypatch.setattr("undef.telemetry.setup.configure_logging", lambda _: None)
    monkeypatch.setattr("undef.telemetry.setup._refresh_otel_tracing", lambda: None)
    monkeypatch.setattr("undef.telemetry.setup._refresh_otel_metrics", lambda: None)
    monkeypatch.setattr("undef.telemetry.setup.setup_tracing", lambda _: None)
    monkeypatch.setattr("undef.telemetry.setup.setup_metrics", lambda _: None)
    monkeypatch.setattr("undef.telemetry.setup._rebind_slo_instruments", lambda: None)
    monkeypatch.setattr("undef.telemetry.setup.record_red_metrics", red_mock)
    monkeypatch.setattr("undef.telemetry.setup.record_use_metrics", lambda *_: None)

    cfg = TelemetryConfig(slo=SLOConfig(enable_red_metrics=True))
    setup_telemetry(cfg)

    red_mock.assert_called_once_with("startup", "INIT", 200, 0.0)


# ---------------------------------------------------------------------------
# setup_telemetry: SLO record_use_metrics exact args
# ---------------------------------------------------------------------------


def test_setup_telemetry_slo_use_metrics_exact_args(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kill mutants that change record_use_metrics args.

    Expected: record_use_metrics("startup", 0)
    """
    use_mock = MagicMock()
    monkeypatch.setattr("undef.telemetry.setup.apply_runtime_config", lambda _: None)
    monkeypatch.setattr("undef.telemetry.setup.configure_logging", lambda _: None)
    monkeypatch.setattr("undef.telemetry.setup._refresh_otel_tracing", lambda: None)
    monkeypatch.setattr("undef.telemetry.setup._refresh_otel_metrics", lambda: None)
    monkeypatch.setattr("undef.telemetry.setup.setup_tracing", lambda _: None)
    monkeypatch.setattr("undef.telemetry.setup.setup_metrics", lambda _: None)
    monkeypatch.setattr("undef.telemetry.setup._rebind_slo_instruments", lambda: None)
    monkeypatch.setattr("undef.telemetry.setup.record_red_metrics", lambda *_: None)
    monkeypatch.setattr("undef.telemetry.setup.record_use_metrics", use_mock)

    cfg = TelemetryConfig(slo=SLOConfig(enable_use_metrics=True))
    setup_telemetry(cfg)

    use_mock.assert_called_once_with("startup", 0)


def test_setup_telemetry_slo_both_metrics_exact_args(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kill all SLO arg mutations at once with both enabled."""
    red_mock = MagicMock()
    use_mock = MagicMock()
    monkeypatch.setattr("undef.telemetry.setup.apply_runtime_config", lambda _: None)
    monkeypatch.setattr("undef.telemetry.setup.configure_logging", lambda _: None)
    monkeypatch.setattr("undef.telemetry.setup._refresh_otel_tracing", lambda: None)
    monkeypatch.setattr("undef.telemetry.setup._refresh_otel_metrics", lambda: None)
    monkeypatch.setattr("undef.telemetry.setup.setup_tracing", lambda _: None)
    monkeypatch.setattr("undef.telemetry.setup.setup_metrics", lambda _: None)
    monkeypatch.setattr("undef.telemetry.setup._rebind_slo_instruments", lambda: None)
    monkeypatch.setattr("undef.telemetry.setup.record_red_metrics", red_mock)
    monkeypatch.setattr("undef.telemetry.setup.record_use_metrics", use_mock)

    cfg = TelemetryConfig(slo=SLOConfig(enable_red_metrics=True, enable_use_metrics=True))
    setup_telemetry(cfg)

    red_mock.assert_called_once_with("startup", "INIT", 200, 0.0)
    use_mock.assert_called_once_with("startup", 0)


# ---------------------------------------------------------------------------
# setup_telemetry: completed list correct step names (string key consistency)
# ---------------------------------------------------------------------------


def test_setup_telemetry_completed_list_has_correct_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify the completed list uses exact step names matching _rollback teardowns.

    If completed.append() uses wrong strings, rollback will KeyError.
    We test this by making _rebind_slo_instruments fail (after all 3 steps complete)
    and checking that all 3 teardowns are called.
    """
    shutdown_calls: list[str] = []

    monkeypatch.setattr("undef.telemetry.setup.apply_runtime_config", lambda _: None)
    monkeypatch.setattr("undef.telemetry.setup.configure_logging", lambda _: None)
    monkeypatch.setattr("undef.telemetry.setup._refresh_otel_tracing", lambda: None)
    monkeypatch.setattr("undef.telemetry.setup._refresh_otel_metrics", lambda: None)
    monkeypatch.setattr("undef.telemetry.setup.setup_tracing", lambda _: None)
    monkeypatch.setattr("undef.telemetry.setup.setup_metrics", lambda _: None)
    monkeypatch.setattr(
        "undef.telemetry.setup._rebind_slo_instruments",
        lambda: (_ for _ in ()).throw(RuntimeError("rebind_boom")),
    )
    monkeypatch.setattr(
        "undef.telemetry.setup.shutdown_logging",
        lambda: shutdown_calls.append("logging"),
    )
    monkeypatch.setattr(
        "undef.telemetry.setup.shutdown_tracing",
        lambda: shutdown_calls.append("tracing"),
    )
    monkeypatch.setattr(
        "undef.telemetry.setup.shutdown_metrics",
        lambda: shutdown_calls.append("metrics"),
    )

    with pytest.raises(RuntimeError, match="rebind_boom"):
        setup_telemetry()

    # All three steps completed before _rebind_slo_instruments failed
    assert "logging" in shutdown_calls
    assert "tracing" in shutdown_calls
    assert "metrics" in shutdown_calls
