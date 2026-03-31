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
    increment_exemplar_unsupported,
    increment_retries,
    record_export_failure,
    record_export_success,
    reset_health_for_tests,
    set_queue_depth,
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


# ── set_queue_depth ────────────────────────────────────────────


class TestSetQueueDepth:
    def test_set_queue_depth_logs(self) -> None:
        set_queue_depth("logs", 5)
        snap = get_health_snapshot()
        assert snap.queue_depth_logs == 5

    def test_set_queue_depth_traces(self) -> None:
        set_queue_depth("traces", 7)
        snap = get_health_snapshot()
        assert snap.queue_depth_traces == 7

    def test_set_queue_depth_metrics(self) -> None:
        set_queue_depth("metrics", 3)
        snap = get_health_snapshot()
        assert snap.queue_depth_metrics == 3

    def test_clamps_negative_to_zero(self) -> None:
        set_queue_depth("logs", -10)
        snap = get_health_snapshot()
        assert snap.queue_depth_logs == 0

    def test_zero_depth_accepted(self) -> None:
        set_queue_depth("logs", 5)
        set_queue_depth("logs", 0)
        snap = get_health_snapshot()
        assert snap.queue_depth_logs == 0

    def test_unknown_signal_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="unknown signal"):
            set_queue_depth("bogus", 42)


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

    def test_stores_error_string_not_none(self) -> None:
        exc = ValueError("test error")
        record_export_failure("logs", exc)
        snap = get_health_snapshot()
        assert snap.last_error_logs == "test error"

    def test_traces_error_stored(self) -> None:
        record_export_failure("traces", RuntimeError("trace err"))
        snap = get_health_snapshot()
        assert snap.last_error_traces == "trace err"

    def test_metrics_error_stored(self) -> None:
        record_export_failure("metrics", RuntimeError("metric err"))
        snap = get_health_snapshot()
        assert snap.last_error_metrics == "metric err"

    def test_signals_are_independent(self) -> None:
        record_export_failure("logs", RuntimeError("log err"))
        record_export_failure("traces", RuntimeError("trace err"))
        snap = get_health_snapshot()
        assert snap.export_failures_logs == 1
        assert snap.export_failures_traces == 1
        assert snap.export_failures_metrics == 0
        assert snap.last_error_logs == "log err"
        assert snap.last_error_traces == "trace err"
        assert snap.last_error_metrics is None


# ── record_export_success ──────────────────────────────────────


class TestRecordExportSuccess:
    def test_records_timestamp(self) -> None:
        record_export_success("logs", latency_ms=1.5)
        snap = get_health_snapshot()
        assert isinstance(snap.last_successful_export_logs, (int, float))
        assert snap.last_successful_export_logs > 0

    def test_records_latency(self) -> None:
        record_export_success("traces", latency_ms=42.0)
        snap = get_health_snapshot()
        assert snap.export_latency_ms_traces == 42.0

    def test_clamps_negative_latency_to_zero(self) -> None:
        record_export_success("logs", latency_ms=-5.0)
        snap = get_health_snapshot()
        assert snap.export_latency_ms_logs == 0.0

    def test_zero_latency_accepted(self) -> None:
        record_export_success("logs", latency_ms=0.0)
        snap = get_health_snapshot()
        assert snap.export_latency_ms_logs == 0.0

    def test_default_latency_is_zero(self) -> None:
        """Kills latency_ms: float = 0.0 -> 1.0 default arg mutant."""
        record_export_success("logs")
        snap = get_health_snapshot()
        assert snap.export_latency_ms_logs == 0.0

    def test_clears_last_error_to_none(self) -> None:
        record_export_failure("logs", RuntimeError("err"))
        snap = get_health_snapshot()
        assert snap.last_error_logs == "err"

        record_export_success("logs", latency_ms=1.0)
        snap = get_health_snapshot()
        assert snap.last_error_logs is None
        # Ensure it's actually None, not empty string
        assert snap.last_error_logs != ""

    def test_traces_success(self) -> None:
        record_export_success("traces", latency_ms=10.0)
        snap = get_health_snapshot()
        assert isinstance(snap.last_successful_export_traces, (int, float))
        assert snap.last_successful_export_traces > 0
        assert snap.export_latency_ms_traces == 10.0

    def test_metrics_success(self) -> None:
        record_export_success("metrics", latency_ms=20.0)
        snap = get_health_snapshot()
        assert isinstance(snap.last_successful_export_metrics, (int, float))
        assert snap.last_successful_export_metrics > 0
        assert snap.export_latency_ms_metrics == 20.0

    def test_signals_are_independent(self) -> None:
        record_export_success("logs", latency_ms=1.0)
        record_export_success("traces", latency_ms=2.0)
        snap = get_health_snapshot()
        assert isinstance(snap.last_successful_export_logs, (int, float))
        assert isinstance(snap.last_successful_export_traces, (int, float))
        assert snap.last_successful_export_metrics is None
        assert snap.export_latency_ms_logs == 1.0
        assert snap.export_latency_ms_traces == 2.0
        assert snap.export_latency_ms_metrics == 0.0


# ── increment_exemplar_unsupported ─────────────────────────────


class TestIncrementExemplarUnsupported:
    def test_default_amount_is_one(self) -> None:
        increment_exemplar_unsupported()
        snap = get_health_snapshot()
        assert snap.exemplar_unsupported_total == 1

    def test_cumulative_across_calls(self) -> None:
        increment_exemplar_unsupported()
        increment_exemplar_unsupported()
        snap = get_health_snapshot()
        assert snap.exemplar_unsupported_total == 2

    def test_negative_amount_clamped_to_zero(self) -> None:
        increment_exemplar_unsupported(-3)
        snap = get_health_snapshot()
        assert snap.exemplar_unsupported_total == 0

    def test_zero_amount_no_change(self) -> None:
        increment_exemplar_unsupported(0)
        snap = get_health_snapshot()
        assert snap.exemplar_unsupported_total == 0

    def test_custom_amount(self) -> None:
        increment_exemplar_unsupported(5)
        snap = get_health_snapshot()
        assert snap.exemplar_unsupported_total == 5


# TestHealthSnapshotFieldMapping and TestResetHealthForTests
# moved to test_health_snapshot_mapping.py (500 LOC limit).
