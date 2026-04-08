# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests for health snapshot field mapping and reset behaviour.

Split from test_health_mutations.py to stay under the 500 LOC limit.
"""

from __future__ import annotations

import pytest

from provide.telemetry.health import (
    get_health_snapshot,
    increment_async_blocking_risk,
    increment_dropped,
    increment_emitted,
    increment_retries,
    record_export_failure,
    record_export_latency,
    reset_health_for_tests,
    set_setup_error,
)
from provide.telemetry.resilience import reset_resilience_for_tests


@pytest.fixture(autouse=True)
def _reset_health() -> None:
    """Reset all health counters before each test."""
    reset_resilience_for_tests()
    reset_health_for_tests()


# -- get_health_snapshot field mapping --


class TestHealthSnapshotFieldMapping:
    """Verify every snapshot field maps to the correct signal's dict."""

    def test_emitted_maps_correctly(self) -> None:
        increment_emitted("logs", 10)
        increment_emitted("traces", 20)
        increment_emitted("metrics", 30)
        snap = get_health_snapshot()
        assert snap.emitted_logs == 10
        assert snap.emitted_traces == 20
        assert snap.emitted_metrics == 30

    def test_dropped_maps_correctly(self) -> None:
        increment_dropped("logs", 11)
        increment_dropped("traces", 22)
        increment_dropped("metrics", 33)
        snap = get_health_snapshot()
        assert snap.dropped_logs == 11
        assert snap.dropped_traces == 22
        assert snap.dropped_metrics == 33

    def test_retries_maps_correctly(self) -> None:
        increment_retries("logs", 4)
        increment_retries("traces", 5)
        increment_retries("metrics", 6)
        snap = get_health_snapshot()
        assert snap.retries_logs == 4
        assert snap.retries_traces == 5
        assert snap.retries_metrics == 6

    def test_async_blocking_risk_maps_correctly(self) -> None:
        increment_async_blocking_risk("logs", 7)
        increment_async_blocking_risk("traces", 8)
        increment_async_blocking_risk("metrics", 9)
        snap = get_health_snapshot()
        assert snap.async_blocking_risk_logs == 7
        assert snap.async_blocking_risk_traces == 8
        assert snap.async_blocking_risk_metrics == 9

    def test_export_failures_maps_correctly(self) -> None:
        record_export_failure("logs", RuntimeError("a"))
        record_export_failure("traces", RuntimeError("b"))
        record_export_failure("metrics", RuntimeError("c"))
        snap = get_health_snapshot()
        assert snap.export_failures_logs == 1
        assert snap.export_failures_traces == 1
        assert snap.export_failures_metrics == 1

    def test_export_latency_maps_correctly(self) -> None:
        record_export_latency("logs", latency_ms=100.0)
        record_export_latency("traces", latency_ms=200.0)
        record_export_latency("metrics", latency_ms=300.0)
        snap = get_health_snapshot()
        assert snap.export_latency_ms_logs == 100.0
        assert snap.export_latency_ms_traces == 200.0
        assert snap.export_latency_ms_metrics == 300.0

    def test_all_fields_unique_values(self) -> None:
        """Set every signal to distinct values and verify no cross-mapping."""
        increment_emitted("logs", 1)
        increment_emitted("traces", 2)
        increment_emitted("metrics", 3)
        increment_dropped("logs", 4)
        increment_dropped("traces", 5)
        increment_dropped("metrics", 6)
        increment_retries("logs", 7)
        increment_retries("traces", 8)
        increment_retries("metrics", 9)
        increment_async_blocking_risk("logs", 10)
        increment_async_blocking_risk("traces", 11)
        increment_async_blocking_risk("metrics", 12)
        record_export_failure("logs", RuntimeError("e_log"))
        record_export_failure("traces", RuntimeError("e_trace"))
        record_export_failure("metrics", RuntimeError("e_metric"))

        snap = get_health_snapshot()

        assert snap.emitted_logs == 1
        assert snap.emitted_traces == 2
        assert snap.emitted_metrics == 3
        assert snap.dropped_logs == 4
        assert snap.dropped_traces == 5
        assert snap.dropped_metrics == 6
        assert snap.retries_logs == 7
        assert snap.retries_traces == 8
        assert snap.retries_metrics == 9
        assert snap.async_blocking_risk_logs == 10
        assert snap.async_blocking_risk_traces == 11
        assert snap.async_blocking_risk_metrics == 12
        assert snap.export_failures_logs == 1
        assert snap.export_failures_traces == 1
        assert snap.export_failures_metrics == 1

    def test_snapshot_has_exactly_25_fields(self) -> None:
        """Canonical 25-field layout: 8 per signal * 3 + 1 global."""
        from provide.telemetry.health import HealthSnapshot

        assert len(HealthSnapshot._fields) == 25


# -- reset_health_for_tests --


class TestResetHealthForTests:
    def test_resets_emitted_to_zero(self) -> None:
        for sig in ("logs", "traces", "metrics"):
            increment_emitted(sig, 100)
        reset_health_for_tests()
        snap = get_health_snapshot()
        assert snap.emitted_logs == 0
        assert snap.emitted_traces == 0
        assert snap.emitted_metrics == 0

    def test_resets_dropped_to_zero(self) -> None:
        for sig in ("logs", "traces", "metrics"):
            increment_dropped(sig, 50)
        reset_health_for_tests()
        snap = get_health_snapshot()
        assert snap.dropped_logs == 0
        assert snap.dropped_traces == 0
        assert snap.dropped_metrics == 0

    def test_resets_retries_to_zero(self) -> None:
        for sig in ("logs", "traces", "metrics"):
            increment_retries(sig, 50)
        reset_health_for_tests()
        snap = get_health_snapshot()
        assert snap.retries_logs == 0
        assert snap.retries_traces == 0
        assert snap.retries_metrics == 0

    def test_resets_async_blocking_risk_to_zero(self) -> None:
        for sig in ("logs", "traces", "metrics"):
            increment_async_blocking_risk(sig, 50)
        reset_health_for_tests()
        snap = get_health_snapshot()
        assert snap.async_blocking_risk_logs == 0
        assert snap.async_blocking_risk_traces == 0
        assert snap.async_blocking_risk_metrics == 0

    def test_resets_export_failures_to_zero(self) -> None:
        for sig in ("logs", "traces", "metrics"):
            record_export_failure(sig, RuntimeError("err"))
        reset_health_for_tests()
        snap = get_health_snapshot()
        assert snap.export_failures_logs == 0
        assert snap.export_failures_traces == 0
        assert snap.export_failures_metrics == 0

    def test_resets_export_latency_to_zero(self) -> None:
        for sig in ("logs", "traces", "metrics"):
            record_export_latency(sig, latency_ms=99.9)
        reset_health_for_tests()
        snap = get_health_snapshot()
        assert snap.export_latency_ms_logs == 0.0
        assert snap.export_latency_ms_traces == 0.0
        assert snap.export_latency_ms_metrics == 0.0

    def test_reset_values_are_exact(self) -> None:
        """Ensure reset uses 0 not 1, 0.0 not 1.0."""
        increment_emitted("logs", 10)
        increment_dropped("logs", 10)
        increment_retries("logs", 10)
        increment_async_blocking_risk("logs", 10)
        record_export_failure("logs", RuntimeError("x"))
        record_export_latency("logs", latency_ms=50.0)

        reset_health_for_tests()
        snap = get_health_snapshot()

        assert snap.emitted_logs == 0
        assert snap.dropped_logs == 0
        assert snap.retries_logs == 0
        assert snap.async_blocking_risk_logs == 0
        assert snap.export_failures_logs == 0
        assert snap.export_latency_ms_logs == 0.0

    def test_reset_clears_setup_error(self) -> None:
        set_setup_error("broken")
        reset_health_for_tests()
        snap = get_health_snapshot()
        assert snap.setup_error is None


# -- Circuit state fields in snapshot --


class TestHealthSnapshotCircuitState:
    def test_circuit_state_defaults_to_closed(self) -> None:
        snap = get_health_snapshot()
        assert snap.circuit_state_logs == "closed"
        assert snap.circuit_state_traces == "closed"
        assert snap.circuit_state_metrics == "closed"
        assert snap.circuit_open_count_logs == 0
        assert snap.circuit_open_count_traces == 0
        assert snap.circuit_open_count_metrics == 0

    def test_resilience_module_cache_initialized_correctly(self) -> None:
        """Kill mutmut_1 (is None -> is not None) and mutmut_2 (_resilience_mod = resilience -> None).

        Reset the module cache to None, then verify get_health_snapshot still works.
        Mutmut_1 would skip the import when _resilience_mod IS None, causing AttributeError.
        Mutmut_2 would never cache the module, re-importing every call (but functionally works).
        """
        import provide.telemetry.health as health_mod

        # Force _resilience_mod to None so the cache-init branch must run
        health_mod._resilience_mod = None
        snap = get_health_snapshot()
        # If the caching worked, _resilience_mod should now be set (not None)
        assert health_mod._resilience_mod is not None
        assert snap.circuit_state_logs == "closed"

    def test_setup_error_none_by_default(self) -> None:
        snap = get_health_snapshot()
        assert snap.setup_error is None

    def test_setup_error_reflected_in_snapshot(self) -> None:
        set_setup_error("provider init failed")
        snap = get_health_snapshot()
        assert snap.setup_error == "provider init failed"

    def test_setup_error_can_be_cleared(self) -> None:
        set_setup_error("err")
        set_setup_error(None)
        snap = get_health_snapshot()
        assert snap.setup_error is None

    def test_circuit_open_count_distinct_from_state(self) -> None:
        """Trip the circuit breaker to get non-zero open_count."""
        import time

        from provide.telemetry.resilience import (
            _CIRCUIT_BREAKER_THRESHOLD,
            ExporterPolicy,
            reset_resilience_for_tests,
            run_with_resilience,
            set_exporter_policy,
        )

        reset_resilience_for_tests()
        reset_health_for_tests()
        set_exporter_policy(
            "logs",
            ExporterPolicy(timeout_seconds=0.01, retries=0, fail_open=True),
        )
        for _ in range(_CIRCUIT_BREAKER_THRESHOLD):
            run_with_resilience("logs", lambda: time.sleep(1.0))

        snap = get_health_snapshot()
        assert snap.circuit_state_logs == "open"
        assert isinstance(snap.circuit_open_count_logs, int)
        assert snap.circuit_open_count_logs >= 1

    def test_circuit_open_count_per_signal_mapping(self) -> None:
        """Kill mutants swapping indices for traces and metrics signals."""
        import time

        from provide.telemetry.resilience import (
            _CIRCUIT_BREAKER_THRESHOLD,
            ExporterPolicy,
            reset_resilience_for_tests,
            run_with_resilience,
            set_exporter_policy,
        )

        reset_resilience_for_tests()
        reset_health_for_tests()
        for sig in ("traces", "metrics"):
            set_exporter_policy(
                sig,
                ExporterPolicy(timeout_seconds=0.01, retries=0, fail_open=True),
            )
            for _ in range(_CIRCUIT_BREAKER_THRESHOLD):
                run_with_resilience(sig, lambda: time.sleep(1.0))

        snap = get_health_snapshot()
        assert snap.circuit_state_traces == "open"
        assert snap.circuit_open_count_traces >= 1
        assert snap.circuit_state_metrics == "open"
        assert snap.circuit_open_count_metrics >= 1

    def test_circuit_open_count_traces_is_count_not_cooldown(self) -> None:
        """Kill mutmut_106: cs_traces[1] -> cs_traces[2].

        Index 1 is open_count (small int), index 2 is cooldown_remaining (large float).
        Assert the value is exactly an int and small.
        """
        import time

        from provide.telemetry.resilience import (
            _CIRCUIT_BREAKER_THRESHOLD,
            ExporterPolicy,
            reset_resilience_for_tests,
            run_with_resilience,
            set_exporter_policy,
        )

        reset_resilience_for_tests()
        reset_health_for_tests()
        set_exporter_policy(
            "traces",
            ExporterPolicy(timeout_seconds=0.01, retries=0, fail_open=True),
        )
        for _ in range(_CIRCUIT_BREAKER_THRESHOLD):
            run_with_resilience("traces", lambda: time.sleep(1.0))

        snap = get_health_snapshot()
        assert snap.circuit_state_traces == "open"
        # open_count is a small int (1); cooldown_remaining is a large float (~60.0)
        assert type(snap.circuit_open_count_traces) is int
        assert snap.circuit_open_count_traces == 1

    def test_circuit_open_count_metrics_is_count_not_cooldown(self) -> None:
        """Kill mutmut_107: cs_metrics[1] -> cs_metrics[2]."""
        import time

        from provide.telemetry.resilience import (
            _CIRCUIT_BREAKER_THRESHOLD,
            ExporterPolicy,
            reset_resilience_for_tests,
            run_with_resilience,
            set_exporter_policy,
        )

        reset_resilience_for_tests()
        reset_health_for_tests()
        set_exporter_policy(
            "metrics",
            ExporterPolicy(timeout_seconds=0.01, retries=0, fail_open=True),
        )
        for _ in range(_CIRCUIT_BREAKER_THRESHOLD):
            run_with_resilience("metrics", lambda: time.sleep(1.0))

        snap = get_health_snapshot()
        assert snap.circuit_state_metrics == "open"
        assert type(snap.circuit_open_count_metrics) is int
        assert snap.circuit_open_count_metrics == 1
