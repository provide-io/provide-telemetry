# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests for degraded-mode setup behaviour (emergency fallback path)."""

from __future__ import annotations

import warnings

import pytest

from provide.telemetry import setup as setup_mod
from provide.telemetry.config import TelemetryConfig
from provide.telemetry.setup import (
    _reset_all_for_tests,
    _reset_setup_state_for_tests,
    setup_telemetry,
)


def test_setup_does_not_raise_on_provider_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """setup_telemetry() should warn instead of raising when a provider fails."""
    _reset_setup_state_for_tests()
    monkeypatch.setattr("provide.telemetry.runtime.apply_runtime_config", lambda _cfg: None)
    monkeypatch.setattr("provide.telemetry.setup.configure_logging", lambda _cfg, **kw: None)
    monkeypatch.setattr("provide.telemetry.setup._refresh_otel_tracing", lambda: None)
    monkeypatch.setattr("provide.telemetry.metrics.provider._refresh_otel_metrics", lambda: None)
    monkeypatch.setattr("provide.telemetry.setup.setup_tracing", lambda _cfg: None)
    monkeypatch.setattr(
        "provide.telemetry.metrics.provider.setup_metrics",
        lambda _cfg: (_ for _ in ()).throw(RuntimeError("metrics boom")),
    )
    monkeypatch.setattr("provide.telemetry.setup.shutdown_logging", lambda: None)
    monkeypatch.setattr("provide.telemetry.setup.shutdown_tracing", lambda: None)
    monkeypatch.setattr("provide.telemetry.metrics.provider.shutdown_metrics", lambda: None)

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        cfg = setup_telemetry()
    assert any("degraded mode" in str(warning.message) for warning in w)
    # After a failed setup, _setup_done must remain False so a retry can succeed.
    assert setup_mod._setup_done is False
    assert isinstance(cfg, TelemetryConfig)


def test_setup_done_false_after_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """_setup_done must remain False after a failed setup so retries are allowed."""
    _reset_setup_state_for_tests()
    monkeypatch.setattr("provide.telemetry.runtime.apply_runtime_config", lambda _cfg: None)
    monkeypatch.setattr("provide.telemetry.setup.configure_logging", lambda _cfg, **kw: None)
    monkeypatch.setattr("provide.telemetry.setup._refresh_otel_tracing", lambda: None)
    monkeypatch.setattr("provide.telemetry.metrics.provider._refresh_otel_metrics", lambda: None)
    monkeypatch.setattr("provide.telemetry.setup.setup_tracing", lambda _cfg: None)
    monkeypatch.setattr(
        "provide.telemetry.metrics.provider.setup_metrics",
        lambda _cfg: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr("provide.telemetry.setup.shutdown_logging", lambda: None)
    monkeypatch.setattr("provide.telemetry.setup.shutdown_tracing", lambda: None)
    monkeypatch.setattr("provide.telemetry.metrics.provider.shutdown_metrics", lambda: None)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        setup_telemetry()

    assert setup_mod._setup_done is False


def test_health_snapshot_reflects_setup_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """After degraded setup, health snapshot shows the error."""
    from provide.telemetry.health import get_health_snapshot, reset_health_for_tests
    from provide.telemetry.resilience import reset_resilience_for_tests

    _reset_all_for_tests()
    reset_resilience_for_tests()
    reset_health_for_tests()
    monkeypatch.setattr("provide.telemetry.runtime.apply_runtime_config", lambda _cfg: None)
    monkeypatch.setattr("provide.telemetry.setup.configure_logging", lambda _cfg, **kw: None)
    monkeypatch.setattr("provide.telemetry.setup._refresh_otel_tracing", lambda: None)
    monkeypatch.setattr("provide.telemetry.metrics.provider._refresh_otel_metrics", lambda: None)
    monkeypatch.setattr("provide.telemetry.setup.setup_tracing", lambda _cfg: None)
    monkeypatch.setattr(
        "provide.telemetry.metrics.provider.setup_metrics",
        lambda _cfg: (_ for _ in ()).throw(RuntimeError("metrics boom")),
    )
    monkeypatch.setattr("provide.telemetry.setup.shutdown_logging", lambda: None)
    monkeypatch.setattr("provide.telemetry.setup.shutdown_tracing", lambda: None)
    monkeypatch.setattr("provide.telemetry.metrics.provider.shutdown_metrics", lambda: None)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        setup_telemetry()
    snap = get_health_snapshot()
    assert snap.setup_error == "metrics boom"


def test_setup_fallback_calls_configure_logging_when_it_was_not_completed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When configure_logging itself fails, the except block retries it."""
    _reset_setup_state_for_tests()
    log_calls = {"count": 0}

    def _failing_then_ok(cfg: object, **kw: object) -> None:
        log_calls["count"] += 1
        if log_calls["count"] == 1:
            raise RuntimeError("log init failed")

    monkeypatch.setattr("provide.telemetry.runtime.apply_runtime_config", lambda _cfg: None)
    monkeypatch.setattr("provide.telemetry.setup.configure_logging", _failing_then_ok)
    monkeypatch.setattr("provide.telemetry.setup._refresh_otel_tracing", lambda: None)
    monkeypatch.setattr("provide.telemetry.metrics.provider._refresh_otel_metrics", lambda: None)
    monkeypatch.setattr("provide.telemetry.setup.setup_tracing", lambda _cfg: None)
    monkeypatch.setattr("provide.telemetry.metrics.provider.setup_metrics", lambda _cfg: None)
    monkeypatch.setattr("provide.telemetry.setup.shutdown_logging", lambda: None)
    monkeypatch.setattr("provide.telemetry.setup.shutdown_tracing", lambda: None)
    monkeypatch.setattr("provide.telemetry.metrics.provider.shutdown_metrics", lambda: None)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        setup_telemetry()
    # configure_logging called twice: once failing, once in fallback
    assert log_calls["count"] == 2
    # configure_logging itself raised, so setup failed — _setup_done must be False
    assert setup_mod._setup_done is False


def test_setup_error_cleared_after_recovery(monkeypatch: pytest.MonkeyPatch) -> None:
    """A successful setup clears any stale error left by a prior failed attempt."""
    from provide.telemetry.health import get_health_snapshot, set_setup_error

    _reset_all_for_tests()

    # Plant a stale error as if a previous setup call had failed.
    set_setup_error("stale error from prior attempt")

    monkeypatch.setattr("provide.telemetry.runtime.apply_runtime_config", lambda _cfg: None)
    monkeypatch.setattr("provide.telemetry.setup.configure_logging", lambda _cfg, **kw: None)
    monkeypatch.setattr("provide.telemetry.setup._refresh_otel_tracing", lambda: None)
    monkeypatch.setattr("provide.telemetry.metrics.provider._refresh_otel_metrics", lambda: None)
    monkeypatch.setattr("provide.telemetry.setup.setup_tracing", lambda _cfg: None)
    monkeypatch.setattr("provide.telemetry.metrics.provider.setup_metrics", lambda _cfg: None)
    monkeypatch.setattr("provide.telemetry.slo._rebind_slo_instruments", lambda: None)

    setup_telemetry()

    assert get_health_snapshot().setup_error is None


def test_retry_after_degraded_setup_reruns_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    """After a failed setup, a second call retries the full setup sequence."""
    _reset_setup_state_for_tests()
    call_count = {"runtime": 0}
    monkeypatch.setattr(
        "provide.telemetry.runtime.apply_runtime_config",
        lambda _cfg: call_count.__setitem__("runtime", call_count["runtime"] + 1),
    )
    monkeypatch.setattr("provide.telemetry.setup.configure_logging", lambda _cfg, **kw: None)
    monkeypatch.setattr("provide.telemetry.setup._refresh_otel_tracing", lambda: None)
    monkeypatch.setattr("provide.telemetry.metrics.provider._refresh_otel_metrics", lambda: None)
    monkeypatch.setattr("provide.telemetry.setup.setup_tracing", lambda _cfg: None)
    monkeypatch.setattr(
        "provide.telemetry.metrics.provider.setup_metrics",
        lambda _cfg: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr("provide.telemetry.setup.shutdown_logging", lambda: None)
    monkeypatch.setattr("provide.telemetry.setup.shutdown_tracing", lambda: None)
    monkeypatch.setattr("provide.telemetry.metrics.provider.shutdown_metrics", lambda: None)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        setup_telemetry()
        setup_telemetry()
    # Both calls run setup since _setup_done stays False after failure
    assert call_count["runtime"] == 2


def test_retry_after_failure_with_fixed_config_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """After a failed setup, a subsequent call with a fixed config succeeds."""
    _reset_setup_state_for_tests()
    attempt = {"n": 0}

    def _setup_metrics_fn(_cfg: object) -> None:
        attempt["n"] += 1
        if attempt["n"] == 1:
            raise RuntimeError("transient failure")

    monkeypatch.setattr("provide.telemetry.runtime.apply_runtime_config", lambda _cfg: None)
    monkeypatch.setattr("provide.telemetry.setup.configure_logging", lambda _cfg, **kw: None)
    monkeypatch.setattr("provide.telemetry.setup._refresh_otel_tracing", lambda: None)
    monkeypatch.setattr("provide.telemetry.metrics.provider._refresh_otel_metrics", lambda: None)
    monkeypatch.setattr("provide.telemetry.setup.setup_tracing", lambda _cfg: None)
    monkeypatch.setattr("provide.telemetry.metrics.provider.setup_metrics", _setup_metrics_fn)
    monkeypatch.setattr("provide.telemetry.setup.shutdown_logging", lambda: None)
    monkeypatch.setattr("provide.telemetry.setup.shutdown_tracing", lambda: None)
    monkeypatch.setattr("provide.telemetry.metrics.provider.shutdown_metrics", lambda: None)
    monkeypatch.setattr("provide.telemetry.slo._rebind_slo_instruments", lambda: None)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        setup_telemetry()

    assert setup_mod._setup_done is False

    setup_telemetry()
    assert setup_mod._setup_done is True
