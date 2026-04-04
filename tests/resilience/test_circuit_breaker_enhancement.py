# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests for circuit breaker exponential backoff and half-open probe logic."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from provide.telemetry import health as health_mod
from provide.telemetry import resilience as resilience_mod
from provide.telemetry.resilience import (
    _CIRCUIT_BASE_COOLDOWN,
    _CIRCUIT_BREAKER_THRESHOLD,
    _CIRCUIT_MAX_COOLDOWN,
    ExporterPolicy,
    get_circuit_state,
    reset_resilience_for_tests,
    run_with_resilience,
    set_exporter_policy,
)


@pytest.fixture(autouse=True)
def _reset() -> None:
    health_mod.reset_health_for_tests()
    reset_resilience_for_tests()


# ── get_circuit_state basics ─────────────────────────────────────


class TestGetCircuitState:
    def test_closed_by_default(self) -> None:
        state, oc, remaining = get_circuit_state("logs")
        assert state == "closed"
        assert oc == 0
        assert remaining == 0.0

    def test_open_after_threshold_timeouts(self) -> None:
        with resilience_mod._lock:
            resilience_mod._consecutive_timeouts["logs"] = _CIRCUIT_BREAKER_THRESHOLD
            resilience_mod._circuit_tripped_at["logs"] = time.monotonic()
            resilience_mod._open_count["logs"] = 1
        state, oc, remaining = get_circuit_state("logs")
        assert state == "open"
        assert oc == 1
        assert remaining > 0

    def test_half_open_when_cooldown_expired(self) -> None:
        with resilience_mod._lock:
            resilience_mod._consecutive_timeouts["logs"] = _CIRCUIT_BREAKER_THRESHOLD
            resilience_mod._circuit_tripped_at["logs"] = time.monotonic() - _CIRCUIT_BASE_COOLDOWN - 1
            resilience_mod._open_count["logs"] = 0
        state, _oc, remaining = get_circuit_state("logs")
        assert state == "half-open"
        assert remaining == 0.0

    def test_half_open_when_probing_flag_set(self) -> None:
        with resilience_mod._lock:
            resilience_mod._half_open_probing["traces"] = True
            resilience_mod._open_count["traces"] = 2
        state, oc, remaining = get_circuit_state("traces")
        assert state == "half-open"
        assert oc == 2
        assert remaining == 0.0

    def test_invalid_signal_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown signal"):
            get_circuit_state("invalid")

    def test_per_signal_isolation(self) -> None:
        with resilience_mod._lock:
            resilience_mod._consecutive_timeouts["logs"] = _CIRCUIT_BREAKER_THRESHOLD
            resilience_mod._circuit_tripped_at["logs"] = time.monotonic()
            resilience_mod._open_count["logs"] = 1
        assert get_circuit_state("logs")[0] == "open"
        assert get_circuit_state("traces")[0] == "closed"
        assert get_circuit_state("metrics")[0] == "closed"


# ── Exponential backoff ──────────────────────────────────────────


class TestExponentialBackoff:
    def test_cooldown_doubles_with_open_count(self) -> None:
        now = time.monotonic()
        with resilience_mod._lock:
            resilience_mod._consecutive_timeouts["logs"] = _CIRCUIT_BREAKER_THRESHOLD
            resilience_mod._circuit_tripped_at["logs"] = now
            resilience_mod._open_count["logs"] = 2
        _, _, remaining = get_circuit_state("logs")
        expected_cooldown = _CIRCUIT_BASE_COOLDOWN * (2**2)
        assert remaining <= expected_cooldown
        assert remaining > _CIRCUIT_BASE_COOLDOWN

    def test_cooldown_capped_at_max(self) -> None:
        now = time.monotonic()
        with resilience_mod._lock:
            resilience_mod._consecutive_timeouts["logs"] = _CIRCUIT_BREAKER_THRESHOLD
            resilience_mod._circuit_tripped_at["logs"] = now
            resilience_mod._open_count["logs"] = 100
        _, _, remaining = get_circuit_state("logs")
        assert remaining <= _CIRCUIT_MAX_COOLDOWN

    def test_open_count_increments_on_threshold_trip(self) -> None:
        set_exporter_policy(
            "logs",
            ExporterPolicy(timeout_seconds=1.0, retries=0, fail_open=True),
        )
        with patch.object(
            resilience_mod,
            "_run_attempt_with_timeout",
            side_effect=TimeoutError("timed out"),
        ):
            for _ in range(_CIRCUIT_BREAKER_THRESHOLD):
                run_with_resilience("logs", lambda: None)
        with resilience_mod._lock:
            assert resilience_mod._open_count["logs"] == 1


# ── Half-open probe ──────────────────────────────────────────────


class TestHalfOpenProbe:
    def _trip_circuit(self, signal: str, open_count: int = 1) -> None:
        cooldown = min(_CIRCUIT_BASE_COOLDOWN * (2**open_count), _CIRCUIT_MAX_COOLDOWN)
        with resilience_mod._lock:
            resilience_mod._consecutive_timeouts[signal] = _CIRCUIT_BREAKER_THRESHOLD
            resilience_mod._circuit_tripped_at[signal] = time.monotonic() - cooldown - 1.0
            resilience_mod._open_count[signal] = open_count

    def test_half_open_success_closes_and_decays(self) -> None:
        self._trip_circuit("logs", open_count=2)
        set_exporter_policy("logs", ExporterPolicy(timeout_seconds=1.0, retries=0, fail_open=True))
        run_with_resilience("logs", lambda: "ok")
        state, oc, _ = get_circuit_state("logs")
        assert state == "closed"
        assert oc == 1

    def test_half_open_timeout_reopens_and_increments(self) -> None:
        self._trip_circuit("logs", open_count=2)
        set_exporter_policy("logs", ExporterPolicy(timeout_seconds=1.0, retries=0, fail_open=True))
        with patch.object(
            resilience_mod,
            "_run_attempt_with_timeout",
            side_effect=TimeoutError("timed out"),
        ):
            run_with_resilience("logs", lambda: None)
        with resilience_mod._lock:
            assert resilience_mod._open_count["logs"] == 3
            assert resilience_mod._half_open_probing["logs"] is False

    def test_half_open_exception_reopens_and_increments(self) -> None:
        self._trip_circuit("traces", open_count=1)
        set_exporter_policy("traces", ExporterPolicy(timeout_seconds=1.0, retries=0, fail_open=True))

        def _raise() -> None:
            raise ValueError("boom")

        run_with_resilience("traces", _raise)
        with resilience_mod._lock:
            assert resilience_mod._open_count["traces"] == 2
            assert resilience_mod._half_open_probing["traces"] is False

    def test_decay_to_zero_does_not_go_negative(self) -> None:
        self._trip_circuit("metrics", open_count=0)
        set_exporter_policy("metrics", ExporterPolicy(timeout_seconds=1.0, retries=0, fail_open=True))
        run_with_resilience("metrics", lambda: "ok")
        _, oc, _ = get_circuit_state("metrics")
        assert oc == 0


# ── Reset ────────────────────────────────────────────────────────


class TestResetResilienceNewState:
    def test_reset_clears_open_count(self) -> None:
        with resilience_mod._lock:
            resilience_mod._open_count["logs"] = 5
        reset_resilience_for_tests()
        with resilience_mod._lock:
            assert resilience_mod._open_count["logs"] == 0
            assert resilience_mod._open_count["traces"] == 0
            assert resilience_mod._open_count["metrics"] == 0

    def test_reset_clears_half_open_probing(self) -> None:
        with resilience_mod._lock:
            resilience_mod._half_open_probing["logs"] = True
        reset_resilience_for_tests()
        with resilience_mod._lock:
            assert resilience_mod._half_open_probing["logs"] is False
            assert resilience_mod._half_open_probing["traces"] is False
            assert resilience_mod._half_open_probing["metrics"] is False
