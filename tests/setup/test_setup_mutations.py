# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests targeting surviving mutation-testing mutants in setup.py.

Key mutants: string key mutations in _rollback teardowns dict,
completed.append() arg mutations, and SLO metric argument mutations.
"""

from __future__ import annotations

import warnings
from unittest.mock import MagicMock

import pytest

from provide.telemetry.config import SLOConfig, TelemetryConfig
from provide.telemetry.setup import _reset_setup_state_for_tests, _rollback, setup_telemetry


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
        mp.setattr("provide.telemetry.setup.shutdown_logging", mock_shutdown_logging)
        mp.setattr("provide.telemetry.setup.shutdown_tracing", mock_shutdown_tracing)
        mp.setattr("provide.telemetry.metrics.provider.shutdown_metrics", mock_shutdown_metrics)

        _rollback(["configure_logging", "setup_tracing", "setup_metrics"])

    # All three shutdowns called in reverse order
    mock_shutdown_metrics.assert_called_once()
    mock_shutdown_tracing.assert_called_once()
    mock_shutdown_logging.assert_called_once()


def test_rollback_reverse_order() -> None:
    """Verify rollback calls teardowns in reverse order of completion."""
    order: list[str] = []

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("provide.telemetry.setup.shutdown_logging", lambda: order.append("logging"))
        mp.setattr("provide.telemetry.setup.shutdown_tracing", lambda: order.append("tracing"))
        mp.setattr("provide.telemetry.metrics.provider.shutdown_metrics", lambda: order.append("metrics"))

        _rollback(["configure_logging", "setup_tracing", "setup_metrics"])

    assert order == ["metrics", "tracing", "logging"]


def test_rollback_only_completed_steps() -> None:
    """Only roll back steps that were actually completed."""
    mock_shutdown_logging = MagicMock()
    mock_shutdown_tracing = MagicMock()
    mock_shutdown_metrics = MagicMock()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("provide.telemetry.setup.shutdown_logging", mock_shutdown_logging)
        mp.setattr("provide.telemetry.setup.shutdown_tracing", mock_shutdown_tracing)
        mp.setattr("provide.telemetry.metrics.provider.shutdown_metrics", mock_shutdown_metrics)

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

    monkeypatch.setattr("provide.telemetry.runtime.apply_runtime_config", lambda _: None)
    monkeypatch.setattr("provide.telemetry.setup.configure_logging", lambda _, **kw: None)
    monkeypatch.setattr("provide.telemetry.setup._refresh_otel_tracing", lambda: None)
    monkeypatch.setattr("provide.telemetry.metrics.provider._refresh_otel_metrics", lambda: None)
    monkeypatch.setattr("provide.telemetry.setup.setup_tracing", lambda _: None)
    monkeypatch.setattr(
        "provide.telemetry.metrics.provider.setup_metrics",
        lambda _: (_ for _ in ()).throw(RuntimeError("metrics_boom")),
    )
    monkeypatch.setattr(
        "provide.telemetry.setup.shutdown_logging",
        lambda: shutdown_calls.append("logging"),
    )
    monkeypatch.setattr(
        "provide.telemetry.setup.shutdown_tracing",
        lambda: shutdown_calls.append("tracing"),
    )
    monkeypatch.setattr(
        "provide.telemetry.metrics.provider.shutdown_metrics",
        lambda: shutdown_calls.append("metrics"),
    )

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        setup_telemetry()
    assert any("degraded mode" in str(warning.message) for warning in w)

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
    import provide.telemetry.slo as slo_mod

    red_mock = MagicMock()
    monkeypatch.setattr("provide.telemetry.runtime.apply_runtime_config", lambda _: None)
    monkeypatch.setattr("provide.telemetry.setup.configure_logging", lambda _, **kw: None)
    monkeypatch.setattr("provide.telemetry.setup._refresh_otel_tracing", lambda: None)
    monkeypatch.setattr("provide.telemetry.metrics.provider._refresh_otel_metrics", lambda: None)
    monkeypatch.setattr("provide.telemetry.setup.setup_tracing", lambda _: None)
    monkeypatch.setattr("provide.telemetry.metrics.provider.setup_metrics", lambda _: None)
    monkeypatch.setattr(slo_mod, "_rebind_slo_instruments", lambda: None)
    monkeypatch.setattr(slo_mod, "record_red_metrics", red_mock)
    monkeypatch.setattr(slo_mod, "record_use_metrics", lambda *_: None)

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
    import provide.telemetry.slo as slo_mod

    use_mock = MagicMock()
    monkeypatch.setattr("provide.telemetry.runtime.apply_runtime_config", lambda _: None)
    monkeypatch.setattr("provide.telemetry.setup.configure_logging", lambda _, **kw: None)
    monkeypatch.setattr("provide.telemetry.setup._refresh_otel_tracing", lambda: None)
    monkeypatch.setattr("provide.telemetry.metrics.provider._refresh_otel_metrics", lambda: None)
    monkeypatch.setattr("provide.telemetry.setup.setup_tracing", lambda _: None)
    monkeypatch.setattr("provide.telemetry.metrics.provider.setup_metrics", lambda _: None)
    monkeypatch.setattr(slo_mod, "_rebind_slo_instruments", lambda: None)
    monkeypatch.setattr(slo_mod, "record_red_metrics", lambda *_: None)
    monkeypatch.setattr(slo_mod, "record_use_metrics", use_mock)

    cfg = TelemetryConfig(slo=SLOConfig(enable_use_metrics=True))
    setup_telemetry(cfg)

    use_mock.assert_called_once_with("startup", 0)


def test_setup_telemetry_slo_both_metrics_exact_args(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kill all SLO arg mutations at once with both enabled."""
    import provide.telemetry.slo as slo_mod

    red_mock = MagicMock()
    use_mock = MagicMock()
    monkeypatch.setattr("provide.telemetry.runtime.apply_runtime_config", lambda _: None)
    monkeypatch.setattr("provide.telemetry.setup.configure_logging", lambda _, **kw: None)
    monkeypatch.setattr("provide.telemetry.setup._refresh_otel_tracing", lambda: None)
    monkeypatch.setattr("provide.telemetry.metrics.provider._refresh_otel_metrics", lambda: None)
    monkeypatch.setattr("provide.telemetry.setup.setup_tracing", lambda _: None)
    monkeypatch.setattr("provide.telemetry.metrics.provider.setup_metrics", lambda _: None)
    monkeypatch.setattr(slo_mod, "_rebind_slo_instruments", lambda: None)
    monkeypatch.setattr(slo_mod, "record_red_metrics", red_mock)
    monkeypatch.setattr(slo_mod, "record_use_metrics", use_mock)

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
    import provide.telemetry.slo as slo_mod

    shutdown_calls: list[str] = []

    monkeypatch.setattr("provide.telemetry.runtime.apply_runtime_config", lambda _: None)
    monkeypatch.setattr("provide.telemetry.setup.configure_logging", lambda _, **kw: None)
    monkeypatch.setattr("provide.telemetry.setup._refresh_otel_tracing", lambda: None)
    monkeypatch.setattr("provide.telemetry.metrics.provider._refresh_otel_metrics", lambda: None)
    monkeypatch.setattr("provide.telemetry.setup.setup_tracing", lambda _: None)
    monkeypatch.setattr("provide.telemetry.metrics.provider.setup_metrics", lambda _: None)
    monkeypatch.setattr(
        slo_mod,
        "_rebind_slo_instruments",
        lambda: (_ for _ in ()).throw(RuntimeError("rebind_boom")),
    )
    monkeypatch.setattr(
        "provide.telemetry.setup.shutdown_logging",
        lambda: shutdown_calls.append("logging"),
    )
    monkeypatch.setattr(
        "provide.telemetry.setup.shutdown_tracing",
        lambda: shutdown_calls.append("tracing"),
    )
    monkeypatch.setattr(
        "provide.telemetry.metrics.provider.shutdown_metrics",
        lambda: shutdown_calls.append("metrics"),
    )

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        setup_telemetry()
    assert any("degraded mode" in str(warning.message) for warning in w)

    # All three steps completed before _rebind_slo_instruments failed
    assert "logging" in shutdown_calls
    assert "tracing" in shutdown_calls
    assert "metrics" in shutdown_calls


# ── setup.py: configure_logging must receive force=True ───────────────


def test_setup_telemetry_passes_force_true_to_configure_logging(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kills mutants that change configure_logging(cfg, force=True) to force=False/None/absent."""
    from provide.telemetry.setup import _reset_setup_state_for_tests

    _reset_setup_state_for_tests()
    force_values: list[object] = []

    def _capture_force(cfg: object, *, force: object = False) -> None:
        force_values.append(force)

    monkeypatch.setattr("provide.telemetry.runtime.apply_runtime_config", lambda _cfg: None)
    monkeypatch.setattr("provide.telemetry.setup.configure_logging", _capture_force)
    monkeypatch.setattr("provide.telemetry.setup._refresh_otel_tracing", lambda: None)
    monkeypatch.setattr("provide.telemetry.metrics.provider._refresh_otel_metrics", lambda: None)
    import provide.telemetry.slo as slo_mod

    monkeypatch.setattr("provide.telemetry.setup.setup_tracing", lambda _cfg: None)
    monkeypatch.setattr("provide.telemetry.metrics.provider.setup_metrics", lambda _cfg: None)
    monkeypatch.setattr(slo_mod, "_rebind_slo_instruments", lambda: None)
    setup_telemetry()
    assert force_values == [True]


# ── logger/core.py: configure_logging default must be force=False ─────


def test_configure_logging_second_call_is_noop_without_force(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kills mutant that changes `force: bool = False` to `True`.

    If force defaults to True, the second call reconfigures even with the same config.
    inspect.signature is unreliable against mutmut trampolines, so we test behavior.
    """
    import structlog as sl

    from provide.telemetry.logger import core as lcore

    lcore._reset_logging_for_tests()
    cfg = TelemetryConfig()
    lcore.configure_logging(cfg)  # First call — configures

    reconfigure_calls: list[object] = []
    monkeypatch.setattr(sl, "configure", lambda **kw: reconfigure_calls.append(kw))
    lcore.configure_logging(cfg)  # Second call without force — must be no-op
    assert reconfigure_calls == []


# ── runtime.py: _provider_config_changed treats backpressure as hot ───


def test_provider_config_changed_backpressure_is_hot_reload(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kills mutants that corrupt the 'backpressure' key in the hot-key tuple."""
    from provide.telemetry import runtime as runtime_mod
    from provide.telemetry.config import BackpressureConfig, TelemetryConfig

    base = TelemetryConfig(service_name="svc")
    modified = TelemetryConfig(service_name="svc")
    modified.backpressure = BackpressureConfig(logs_maxsize=9999)
    assert not runtime_mod._provider_config_changed(base, modified)


# ── runtime.py: reconfigure_telemetry error message ──────────────────


def test_reconfigure_telemetry_error_message_exact(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kills mutants that corrupt the RuntimeError message text."""
    from provide.telemetry import runtime as runtime_mod
    from provide.telemetry.logger import core as logger_core

    runtime_mod.reset_runtime_for_tests()
    runtime_mod.apply_runtime_config(TelemetryConfig(service_name="svc"))
    logger_core._otel_log_provider = object()
    try:
        with pytest.raises(RuntimeError) as exc_info:
            runtime_mod.reconfigure_telemetry(TelemetryConfig(service_name="renamed"))
        msg = str(exc_info.value)
        assert "OpenTelemetry" in msg
        assert "setup_telemetry()" in msg
        assert "Restart the process" in msg
    finally:
        logger_core._otel_log_provider = None


# ── runtime.py: reconfigure_telemetry or-logic for all three providers


# ── setup.py: warning type and fallback configure_logging in error path ──


def test_setup_telemetry_error_warning_is_runtime_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kills: RuntimeWarning -> None or removal of RuntimeWarning arg."""
    _reset_setup_state_for_tests()
    monkeypatch.setattr("provide.telemetry.runtime.apply_runtime_config", lambda _: None)
    monkeypatch.setattr("provide.telemetry.setup.configure_logging", lambda _, **kw: None)
    monkeypatch.setattr("provide.telemetry.setup._refresh_otel_tracing", lambda: None)
    monkeypatch.setattr("provide.telemetry.metrics.provider._refresh_otel_metrics", lambda: None)
    monkeypatch.setattr("provide.telemetry.setup.setup_tracing", lambda _: (_ for _ in ()).throw(RuntimeError("boom")))

    with pytest.warns(RuntimeWarning, match="degraded mode"):
        setup_telemetry()


def test_setup_telemetry_fallback_configure_logging_uses_correct_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Kills: 'configure_logging' -> 'XXconfigure_loggingXX' or 'CONFIGURE_LOGGING'.

    When configure_logging itself fails (not in completed), the fallback path
    must call configure_logging(cfg, force=True).
    """
    _reset_setup_state_for_tests()
    fallback_calls: list[tuple[object, bool]] = []

    def _fail_configure(cfg: object, *, force: bool = False) -> None:
        if not fallback_calls:
            # First call (normal path) - fail to NOT add to completed
            raise RuntimeError("config failed")
        fallback_calls.append((cfg, force))

    def _spy_configure(cfg: object, *, force: bool = False) -> None:
        fallback_calls.append((cfg, force))

    first_call = {"count": 0}

    def _configure_that_fails_then_succeeds(cfg: object, *, force: bool = False) -> None:
        first_call["count"] += 1
        if first_call["count"] == 1:
            raise RuntimeError("initial config failed")
        fallback_calls.append((cfg, force))

    monkeypatch.setattr("provide.telemetry.runtime.apply_runtime_config", lambda _: None)
    monkeypatch.setattr("provide.telemetry.setup.configure_logging", _configure_that_fails_then_succeeds)
    monkeypatch.setattr("provide.telemetry.setup._refresh_otel_tracing", lambda: None)
    monkeypatch.setattr("provide.telemetry.metrics.provider._refresh_otel_metrics", lambda: None)
    monkeypatch.setattr("provide.telemetry.setup.setup_tracing", lambda _: None)
    monkeypatch.setattr("provide.telemetry.metrics.provider.setup_metrics", lambda _: None)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        cfg = TelemetryConfig()
        setup_telemetry(cfg)

    # Fallback configure_logging must be called with force=True
    assert len(fallback_calls) == 1
    assert fallback_calls[0][1] is True  # force=True


def test_setup_telemetry_fallback_passes_cfg_not_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Kills: configure_logging(cfg, ...) -> configure_logging(None, ...)."""
    _reset_setup_state_for_tests()
    fallback_cfgs: list[object] = []
    first_call = {"count": 0}

    def _configure_spy(cfg: object, *, force: bool = False) -> None:
        first_call["count"] += 1
        if first_call["count"] == 1:
            raise RuntimeError("initial failed")
        fallback_cfgs.append(cfg)

    monkeypatch.setattr("provide.telemetry.runtime.apply_runtime_config", lambda _: None)
    monkeypatch.setattr("provide.telemetry.setup.configure_logging", _configure_spy)
    monkeypatch.setattr("provide.telemetry.setup._refresh_otel_tracing", lambda: None)
    monkeypatch.setattr("provide.telemetry.metrics.provider._refresh_otel_metrics", lambda: None)
    monkeypatch.setattr("provide.telemetry.setup.setup_tracing", lambda _: None)
    monkeypatch.setattr("provide.telemetry.metrics.provider.setup_metrics", lambda _: None)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        cfg = TelemetryConfig()
        setup_telemetry(cfg)

    assert len(fallback_cfgs) == 1
    assert fallback_cfgs[0] is not None
    assert isinstance(fallback_cfgs[0], TelemetryConfig)


def test_reconfigure_telemetry_raises_when_only_metrics_provider_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kills mutant that changes `or` to `and` in the provider-installed guard."""
    from provide.telemetry import runtime as runtime_mod
    from provide.telemetry.logger import core as logger_core
    from provide.telemetry.metrics import provider as metrics_provider
    from provide.telemetry.tracing import provider as tracing_provider

    runtime_mod.reset_runtime_for_tests()
    runtime_mod.apply_runtime_config(TelemetryConfig(service_name="svc"))
    logger_core._otel_log_provider = None
    tracing_provider._provider_ref = None
    monkeypatch.setattr(metrics_provider, "_meter_provider", object())
    with pytest.raises(RuntimeError, match="provider-changing reconfiguration"):
        runtime_mod.reconfigure_telemetry(TelemetryConfig(service_name="renamed"))


# ── setup.py: "configure_logging" not in completed (mutmut_31/32) ───────


def test_setup_fallback_skipped_when_logging_already_completed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When logging succeeds but metrics fails, no fallback configure_logging call."""
    _reset_setup_state_for_tests()
    calls = {"n": 0}
    monkeypatch.setattr("provide.telemetry.runtime.apply_runtime_config", lambda _: None)
    monkeypatch.setattr(
        "provide.telemetry.setup.configure_logging", lambda *a, **kw: calls.__setitem__("n", calls["n"] + 1)
    )
    monkeypatch.setattr("provide.telemetry.setup._refresh_otel_tracing", lambda: None)
    monkeypatch.setattr("provide.telemetry.metrics.provider._refresh_otel_metrics", lambda: None)
    monkeypatch.setattr("provide.telemetry.setup.setup_tracing", lambda _: None)
    monkeypatch.setattr(
        "provide.telemetry.metrics.provider.setup_metrics", lambda _: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    monkeypatch.setattr("provide.telemetry.setup.shutdown_logging", lambda: None)
    monkeypatch.setattr("provide.telemetry.setup.shutdown_tracing", lambda: None)
    monkeypatch.setattr("provide.telemetry.metrics.provider.shutdown_metrics", lambda: None)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        setup_telemetry()
    assert calls["n"] == 1  # initial only, no fallback
