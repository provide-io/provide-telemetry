# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Regression tests for code review issues (batch 3): circuit breaker,
shutdown runtime reset, force-reconfigure, resolve concurrency, timeout backoff."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from provide.telemetry.config import TelemetryConfig
from provide.telemetry.health import reset_health_for_tests
from provide.telemetry.resilience import (
    ExporterPolicy,
    reset_resilience_for_tests,
    run_with_resilience,
    set_exporter_policy,
)


@pytest.fixture(autouse=True)
def _clean_state() -> None:
    reset_health_for_tests()
    reset_resilience_for_tests()


# ── Issue #17: circuit breaker in resilience ───────────────────────────


class TestCircuitBreaker:
    def test_circuit_breaker_opens_after_consecutive_timeouts(self) -> None:
        """After 3 consecutive timeouts, circuit breaker should open."""
        set_exporter_policy("logs", ExporterPolicy(retries=0, fail_open=True, timeout_seconds=0.01))

        def _slow_op() -> str:
            import time

            time.sleep(1.0)
            return "never"

        for _ in range(3):
            assert run_with_resilience("logs", _slow_op) is None

        call_count = {"n": 0}

        def _should_not_run() -> str:
            call_count["n"] += 1
            return "bad"

        assert run_with_resilience("logs", _should_not_run) is None
        assert call_count["n"] == 0

    def test_circuit_breaker_resets_on_success(self) -> None:
        from provide.telemetry import resilience as r_mod

        set_exporter_policy("logs", ExporterPolicy(retries=0, fail_open=True, timeout_seconds=0.0))
        with r_mod._lock:
            r_mod._consecutive_timeouts["logs"] = 2
        assert run_with_resilience("logs", lambda: "ok") == "ok"
        with r_mod._lock:
            assert r_mod._consecutive_timeouts["logs"] == 0

    def test_circuit_breaker_raises_when_fail_closed(self) -> None:
        import time

        from provide.telemetry import resilience as r_mod

        set_exporter_policy("logs", ExporterPolicy(retries=0, fail_open=False, timeout_seconds=1.0))
        with r_mod._lock:
            r_mod._consecutive_timeouts["logs"] = 3
            r_mod._circuit_tripped_at["logs"] = time.monotonic()
        with pytest.raises(TimeoutError, match="circuit breaker open"):
            run_with_resilience("logs", lambda: "bad")

    def test_non_timeout_error_resets_consecutive_counter(self) -> None:
        from provide.telemetry import resilience as r_mod

        set_exporter_policy("logs", ExporterPolicy(retries=0, fail_open=True, timeout_seconds=0.0))
        with r_mod._lock:
            r_mod._consecutive_timeouts["logs"] = 2
        run_with_resilience("logs", lambda: (_ for _ in ()).throw(RuntimeError("not a timeout")))
        with r_mod._lock:
            assert r_mod._consecutive_timeouts["logs"] == 0

    def test_timeout_increments_consecutive_counter(self) -> None:
        import time as _time

        from provide.telemetry import resilience as r_mod

        set_exporter_policy("logs", ExporterPolicy(retries=0, fail_open=True, timeout_seconds=0.01))
        run_with_resilience("logs", lambda: _time.sleep(1.0))
        with r_mod._lock:
            assert r_mod._consecutive_timeouts["logs"] == 1

    def test_half_open_allows_probe_after_cooldown(self) -> None:
        """After cooldown expires, circuit breaker enters half-open and lets one call through."""
        import time

        from provide.telemetry import resilience as r_mod

        set_exporter_policy("logs", ExporterPolicy(retries=0, fail_open=True, timeout_seconds=0.0))
        with r_mod._lock:
            r_mod._consecutive_timeouts["logs"] = 3
            # Trip time far enough in the past to exceed cooldown
            r_mod._circuit_tripped_at["logs"] = time.monotonic() - r_mod._CIRCUIT_BREAKER_COOLDOWN - 1.0
        # Should let the probe through (half-open) and succeed → reset breaker
        assert run_with_resilience("logs", lambda: "recovered") == "recovered"
        with r_mod._lock:
            assert r_mod._consecutive_timeouts["logs"] == 0

    def test_half_open_probe_failure_re_trips_breaker(self) -> None:
        """If the half-open probe times out, the breaker re-trips with a fresh timestamp."""
        import time as _time

        from provide.telemetry import resilience as r_mod

        set_exporter_policy("logs", ExporterPolicy(retries=0, fail_open=True, timeout_seconds=0.01))
        with r_mod._lock:
            r_mod._consecutive_timeouts["logs"] = 3
            r_mod._circuit_tripped_at["logs"] = _time.monotonic() - r_mod._CIRCUIT_BREAKER_COOLDOWN - 1.0
        # Probe should be allowed through but will timeout → re-trip
        assert run_with_resilience("logs", lambda: _time.sleep(1.0)) is None
        with r_mod._lock:
            assert r_mod._consecutive_timeouts["logs"] >= r_mod._CIRCUIT_BREAKER_THRESHOLD
            # Trip timestamp should be recent (re-armed)
            assert _time.monotonic() - r_mod._circuit_tripped_at["logs"] < 5.0

    def test_circuit_breaker_stays_closed_within_cooldown(self) -> None:
        """Breaker stays open (rejecting calls) within the cooldown window."""
        import time

        from provide.telemetry import resilience as r_mod

        set_exporter_policy("logs", ExporterPolicy(retries=0, fail_open=True, timeout_seconds=1.0))
        call_count = {"n": 0}
        with r_mod._lock:
            r_mod._consecutive_timeouts["logs"] = 3
            r_mod._circuit_tripped_at["logs"] = time.monotonic()  # just tripped
        result = run_with_resilience("logs", lambda: call_count.update(n=call_count["n"] + 1))
        assert result is None
        assert call_count["n"] == 0

    def test_zero_timeout_skips_circuit_breaker(self) -> None:
        """When timeout_seconds=0, the circuit breaker check is skipped entirely."""
        import time

        from provide.telemetry import resilience as r_mod

        set_exporter_policy("logs", ExporterPolicy(retries=0, fail_open=True, timeout_seconds=0.0))
        with r_mod._lock:
            r_mod._consecutive_timeouts["logs"] = 10  # well above threshold
            r_mod._circuit_tripped_at["logs"] = time.monotonic()  # recently tripped
        # Should NOT be blocked — timeout_seconds=0 means no timeout, so no circuit breaker
        assert run_with_resilience("logs", lambda: "bypassed") == "bypassed"

    def test_cooldown_exact_boundary_allows_probe(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """At exactly the cooldown boundary, the breaker should allow a probe."""
        import time

        from provide.telemetry import resilience as r_mod

        set_exporter_policy("logs", ExporterPolicy(retries=0, fail_open=True, timeout_seconds=1.0))
        # Freeze time so elapsed == _CIRCUIT_BREAKER_COOLDOWN exactly.
        # With `<`, this should pass through (half-open). With `<=`, it would block.
        frozen = 1000.0
        monkeypatch.setattr(time, "monotonic", lambda: frozen)
        with r_mod._lock:
            r_mod._consecutive_timeouts["logs"] = 3
            r_mod._circuit_tripped_at["logs"] = frozen - r_mod._CIRCUIT_BREAKER_COOLDOWN
        assert run_with_resilience("logs", lambda: "probe_ok") == "probe_ok"

    def test_reset_clears_circuit_tripped_at(self) -> None:
        """reset_resilience_for_tests must set _circuit_tripped_at to 0.0."""
        from provide.telemetry import resilience as r_mod

        with r_mod._lock:
            r_mod._circuit_tripped_at["logs"] = 999.0
        reset_resilience_for_tests()
        with r_mod._lock:
            assert r_mod._circuit_tripped_at["logs"] == 0.0


# ── Issue #18: shutdown_telemetry resets runtime policies ──────────────


class TestShutdownResetsRuntime:
    def test_shutdown_clears_runtime_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from provide.telemetry import runtime as runtime_mod
        from provide.telemetry.setup import _reset_setup_state_for_tests, shutdown_telemetry

        _reset_setup_state_for_tests()
        runtime_mod.apply_runtime_config(TelemetryConfig(service_name="before-shutdown"))
        assert runtime_mod.get_runtime_config().service_name == "before-shutdown"
        monkeypatch.setattr("provide.telemetry.setup.shutdown_logging", lambda: None)
        monkeypatch.setattr("provide.telemetry.setup.shutdown_tracing", lambda: None)
        monkeypatch.setattr("provide.telemetry.setup.shutdown_metrics", lambda: None)
        shutdown_telemetry()
        assert runtime_mod.get_runtime_config().service_name != "before-shutdown"


# ── Issue #19: configure_logging force parameter ──────────────────────


class TestConfigureLoggingForce:
    def test_force_reconfigures_even_with_same_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from provide.telemetry.logger import core as core_mod
        from provide.telemetry.logger.core import configure_logging

        monkeypatch.setattr(core_mod, "_build_handlers", lambda _cfg, _level: [])
        cfg = TelemetryConfig.from_env({})
        configure_logging(cfg)
        assert core_mod._configured is True
        calls = {"n": 0}

        def _counting_build(config: object, level: object) -> list[object]:
            calls["n"] += 1
            return []

        monkeypatch.setattr(core_mod, "_build_handlers", _counting_build)
        configure_logging(cfg)
        assert calls["n"] == 0
        configure_logging(cfg, force=True)
        assert calls["n"] == 1


# ── Issue #20: fallback resolve double-check under concurrency ────────


class TestFallbackResolveConcurrency:
    def test_counter_double_check_returns_cached_on_race(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from provide.telemetry.metrics import fallback as fb_mod
        from provide.telemetry.metrics.fallback import Counter

        c = Counter("test.counter")
        sentinel = Mock()
        monkeypatch.setattr("provide.telemetry.metrics.provider.get_meter", lambda: Mock())
        real_lock = fb_mod._RESOLVE_LOCK

        class _IL:
            def __enter__(self) -> _IL:
                real_lock.acquire()
                c._resolved = True
                c._otel_counter = sentinel
                return self

            def __exit__(self, *a: object) -> None:
                real_lock.release()

        monkeypatch.setattr(fb_mod, "_RESOLVE_LOCK", _IL())
        assert c._resolve_otel() is sentinel
        monkeypatch.setattr(fb_mod, "_RESOLVE_LOCK", real_lock)

    def test_gauge_double_check_returns_cached_on_race(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from provide.telemetry.metrics import fallback as fb_mod
        from provide.telemetry.metrics.fallback import Gauge

        g = Gauge("test.gauge")
        sentinel = Mock()
        monkeypatch.setattr("provide.telemetry.metrics.provider.get_meter", lambda: Mock())
        real_lock = fb_mod._RESOLVE_LOCK

        class _IL:
            def __enter__(self) -> _IL:
                real_lock.acquire()
                g._resolved = True
                g._otel_gauge = sentinel
                return self

            def __exit__(self, *a: object) -> None:
                real_lock.release()

        monkeypatch.setattr(fb_mod, "_RESOLVE_LOCK", _IL())
        assert g._resolve_otel() is sentinel
        monkeypatch.setattr(fb_mod, "_RESOLVE_LOCK", real_lock)

    def test_histogram_double_check_returns_cached_on_race(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from provide.telemetry.metrics import fallback as fb_mod
        from provide.telemetry.metrics.fallback import Histogram

        h = Histogram("test.histo")
        sentinel = Mock()
        monkeypatch.setattr("provide.telemetry.metrics.provider.get_meter", lambda: Mock())
        real_lock = fb_mod._RESOLVE_LOCK

        class _IL:
            def __enter__(self) -> _IL:
                real_lock.acquire()
                h._resolved = True
                h._otel_histogram = sentinel
                return self

            def __exit__(self, *a: object) -> None:
                real_lock.release()

        monkeypatch.setattr(fb_mod, "_RESOLVE_LOCK", _IL())
        assert h._resolve_otel() is sentinel
        monkeypatch.setattr(fb_mod, "_RESOLVE_LOCK", real_lock)


# ── Issue #21: timeout retry with backoff covers sleep path ───────────


class TestTimeoutRetryWithBackoff:
    def test_timeout_retry_sleeps_on_backoff(self) -> None:
        import time as _time

        set_exporter_policy(
            "logs", ExporterPolicy(retries=1, backoff_seconds=0.001, fail_open=True, timeout_seconds=0.01)
        )
        assert run_with_resilience("logs", lambda: _time.sleep(1.0)) is None
