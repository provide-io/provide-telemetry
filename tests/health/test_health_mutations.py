# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests to kill all surviving mutants in health.py."""

from __future__ import annotations

import pytest

from provide.telemetry.health import (
    _known_signal,
    get_health_snapshot,
    increment_async_blocking_risk,
    increment_dropped,
    increment_emitted,
    increment_retries,
    record_export_failure,
    record_export_latency,
    reset_health_for_tests,
)


@pytest.fixture(autouse=True)
def _reset_health() -> None:
    """Reset all health counters before each test."""
    reset_health_for_tests()


# ── _known_signal ──────────────────────────────────────────────


class TestKnownSignal:
    def test_logs_returns_logs(self) -> None:
        assert _known_signal("logs") == "logs"

    def test_traces_returns_traces(self) -> None:
        assert _known_signal("traces") == "traces"

    def test_metrics_returns_metrics(self) -> None:
        assert _known_signal("metrics") == "metrics"

    def test_unknown_signal_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="unknown signal"):
            _known_signal("unknown")

    def test_empty_string_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="unknown signal"):
            _known_signal("")


# ── increment_emitted ─────────────────────────────────────────


class TestIncrementEmitted:
    def test_default_amount_is_one(self) -> None:
        increment_emitted("logs")
        snap = get_health_snapshot()
        assert snap.emitted_logs == 1

    def test_cumulative_across_calls(self) -> None:
        increment_emitted("logs")
        increment_emitted("logs")
        snap = get_health_snapshot()
        assert snap.emitted_logs == 2

    def test_traces_signal(self) -> None:
        increment_emitted("traces")
        snap = get_health_snapshot()
        assert snap.emitted_traces == 1

    def test_metrics_signal(self) -> None:
        increment_emitted("metrics")
        snap = get_health_snapshot()
        assert snap.emitted_metrics == 1

    def test_negative_amount_clamped_to_zero(self) -> None:
        increment_emitted("logs", -5)
        snap = get_health_snapshot()
        assert snap.emitted_logs == 0

    def test_zero_amount_no_change(self) -> None:
        increment_emitted("logs", 0)
        snap = get_health_snapshot()
        assert snap.emitted_logs == 0

    def test_custom_amount(self) -> None:
        increment_emitted("logs", 10)
        snap = get_health_snapshot()
        assert snap.emitted_logs == 10

    def test_signals_are_independent(self) -> None:
        increment_emitted("logs", 3)
        increment_emitted("traces", 5)
        increment_emitted("metrics", 7)
        snap = get_health_snapshot()
        assert snap.emitted_logs == 3
        assert snap.emitted_traces == 5
        assert snap.emitted_metrics == 7

    def test_unknown_signal_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="unknown signal"):
            increment_emitted("bogus")


# ── increment_dropped ─────────────────────────────────────────


class TestIncrementDropped:
    def test_default_amount_is_one(self) -> None:
        increment_dropped("logs")
        snap = get_health_snapshot()
        assert snap.dropped_logs == 1

    def test_cumulative_across_calls(self) -> None:
        increment_dropped("logs")
        increment_dropped("logs")
        snap = get_health_snapshot()
        assert snap.dropped_logs == 2

    def test_traces_signal(self) -> None:
        increment_dropped("traces")
        snap = get_health_snapshot()
        assert snap.dropped_traces == 1

    def test_metrics_signal(self) -> None:
        increment_dropped("metrics")
        snap = get_health_snapshot()
        assert snap.dropped_metrics == 1

    def test_negative_amount_clamped_to_zero(self) -> None:
        increment_dropped("logs", -5)
        snap = get_health_snapshot()
        assert snap.dropped_logs == 0

    def test_zero_amount_no_change(self) -> None:
        increment_dropped("logs", 0)
        snap = get_health_snapshot()
        assert snap.dropped_logs == 0

    def test_custom_amount(self) -> None:
        increment_dropped("logs", 10)
        snap = get_health_snapshot()
        assert snap.dropped_logs == 10

    def test_signals_are_independent(self) -> None:
        increment_dropped("logs", 3)
        increment_dropped("traces", 5)
        increment_dropped("metrics", 7)
        snap = get_health_snapshot()
        assert snap.dropped_logs == 3
        assert snap.dropped_traces == 5
        assert snap.dropped_metrics == 7


# ── increment_retries ─────────────────────────────────────────


class TestIncrementRetries:
    def test_default_amount_is_one(self) -> None:
        increment_retries("logs")
        snap = get_health_snapshot()
        assert snap.retries_logs == 1

    def test_cumulative_across_calls(self) -> None:
        increment_retries("traces")
        increment_retries("traces")
        snap = get_health_snapshot()
        assert snap.retries_traces == 2

    def test_metrics_signal(self) -> None:
        increment_retries("metrics")
        snap = get_health_snapshot()
        assert snap.retries_metrics == 1

    def test_negative_amount_clamped_to_zero(self) -> None:
        increment_retries("logs", -1)
        snap = get_health_snapshot()
        assert snap.retries_logs == 0

    def test_zero_amount_no_change(self) -> None:
        increment_retries("logs", 0)
        snap = get_health_snapshot()
        assert snap.retries_logs == 0

    def test_signals_are_independent(self) -> None:
        increment_retries("logs", 2)
        increment_retries("traces", 4)
        increment_retries("metrics", 6)
        snap = get_health_snapshot()
        assert snap.retries_logs == 2
        assert snap.retries_traces == 4
        assert snap.retries_metrics == 6


# ── increment_async_blocking_risk ──────────────────────────────


class TestIncrementAsyncBlockingRisk:
    def test_default_amount_is_one(self) -> None:
        increment_async_blocking_risk("logs")
        snap = get_health_snapshot()
        assert snap.async_blocking_risk_logs == 1

    def test_cumulative_across_calls(self) -> None:
        increment_async_blocking_risk("metrics")
        increment_async_blocking_risk("metrics")
        snap = get_health_snapshot()
        assert snap.async_blocking_risk_metrics == 2

    def test_traces_signal(self) -> None:
        increment_async_blocking_risk("traces")
        snap = get_health_snapshot()
        assert snap.async_blocking_risk_traces == 1

    def test_negative_amount_clamped_to_zero(self) -> None:
        increment_async_blocking_risk("logs", -1)
        snap = get_health_snapshot()
        assert snap.async_blocking_risk_logs == 0

    def test_zero_amount_no_change(self) -> None:
        increment_async_blocking_risk("logs", 0)
        snap = get_health_snapshot()
        assert snap.async_blocking_risk_logs == 0

    def test_signals_are_independent(self) -> None:
        increment_async_blocking_risk("logs", 1)
        increment_async_blocking_risk("traces", 3)
        increment_async_blocking_risk("metrics", 5)
        snap = get_health_snapshot()
        assert snap.async_blocking_risk_logs == 1
        assert snap.async_blocking_risk_traces == 3
        assert snap.async_blocking_risk_metrics == 5


# ── record_export_failure ──────────────────────────────────────


class TestRecordExportFailure:
    def test_increments_failure_count(self) -> None:
        record_export_failure("logs", RuntimeError("boom"))
        snap = get_health_snapshot()
        assert snap.export_failures_logs == 1

    def test_increments_by_one_not_two(self) -> None:
        record_export_failure("logs", RuntimeError("a"))
        snap = get_health_snapshot()
        assert snap.export_failures_logs == 1

    def test_failure_count_cumulative(self) -> None:
        record_export_failure("traces", RuntimeError("a"))
        record_export_failure("traces", RuntimeError("b"))
        snap = get_health_snapshot()
        assert snap.export_failures_traces == 2

    def test_signals_are_independent(self) -> None:
        record_export_failure("logs", RuntimeError("log err"))
        record_export_failure("traces", RuntimeError("trace err"))
        snap = get_health_snapshot()
        assert snap.export_failures_logs == 1
        assert snap.export_failures_traces == 1
        assert snap.export_failures_metrics == 0


# ── record_export_latency ─────────────────────────────────────


class TestRecordExportLatency:
    def test_records_latency(self) -> None:
        record_export_latency("traces", latency_ms=42.0)
        snap = get_health_snapshot()
        assert snap.export_latency_ms_traces == 42.0

    def test_clamps_negative_latency_to_zero(self) -> None:
        record_export_latency("logs", latency_ms=-5.0)
        snap = get_health_snapshot()
        assert snap.export_latency_ms_logs == 0.0

    def test_zero_latency_accepted(self) -> None:
        record_export_latency("logs", latency_ms=0.0)
        snap = get_health_snapshot()
        assert snap.export_latency_ms_logs == 0.0

    def test_default_latency_is_zero(self) -> None:
        """Kills latency_ms: float = 0.0 -> 1.0 default arg mutant."""
        record_export_latency("logs")
        snap = get_health_snapshot()
        assert snap.export_latency_ms_logs == 0.0

    def test_traces_latency(self) -> None:
        record_export_latency("traces", latency_ms=10.0)
        snap = get_health_snapshot()
        assert snap.export_latency_ms_traces == 10.0

    def test_metrics_latency(self) -> None:
        record_export_latency("metrics", latency_ms=20.0)
        snap = get_health_snapshot()
        assert snap.export_latency_ms_metrics == 20.0

    def test_signals_are_independent(self) -> None:
        record_export_latency("logs", latency_ms=1.0)
        record_export_latency("traces", latency_ms=2.0)
        snap = get_health_snapshot()
        assert snap.export_latency_ms_logs == 1.0
        assert snap.export_latency_ms_traces == 2.0
        assert snap.export_latency_ms_metrics == 0.0

    def test_unknown_signal_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="unknown signal"):
            record_export_latency("bogus", latency_ms=1.0)


# TestHealthSnapshotFieldMapping and TestResetHealthForTests
# moved to test_health_snapshot_mapping.py (500 LOC limit).
