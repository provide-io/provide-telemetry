# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Cross-signal isolation tests: queue, sampling, and health counters.

Verifies that the three telemetry signals (logs, traces, metrics) are
independently managed — a policy change or failure on one signal must
not affect the others.
"""

from __future__ import annotations

import pytest

from undef.telemetry import backpressure as backpressure_mod
from undef.telemetry import health as health_mod
from undef.telemetry import sampling as sampling_mod
from undef.telemetry.backpressure import QueuePolicy, QueueTicket, release, set_queue_policy, try_acquire
from undef.telemetry.health import get_health_snapshot, record_export_failure, reset_health_for_tests
from undef.telemetry.sampling import SamplingPolicy, reset_sampling_for_tests, set_sampling_policy, should_sample


@pytest.fixture(autouse=True)
def _clean_state() -> None:
    backpressure_mod.reset_queues_for_tests()
    reset_health_for_tests()
    reset_sampling_for_tests()


class TestQueueIsolation:
    """Bounded queue on one signal must not affect the other two."""

    def test_full_logs_queue_does_not_block_traces_or_metrics(self) -> None:
        set_queue_policy(QueuePolicy(logs_maxsize=1, traces_maxsize=0, metrics_maxsize=0))

        # Fill the logs queue
        logs_ticket = try_acquire("logs")
        assert isinstance(logs_ticket, QueueTicket) and logs_ticket.signal == "logs"

        # Logs queue is now full — next acquire returns None
        assert try_acquire("logs") is None

        # Traces and metrics are unbounded (maxsize=0) — always succeed
        traces_ticket = try_acquire("traces")
        assert isinstance(traces_ticket, QueueTicket) and traces_ticket.signal == "traces"

        metrics_ticket = try_acquire("metrics")
        assert isinstance(metrics_ticket, QueueTicket) and metrics_ticket.signal == "metrics"

        snap = get_health_snapshot()
        assert snap.queue_depth_logs == 1
        assert snap.queue_depth_traces == 0
        assert snap.queue_depth_metrics == 0

        release(logs_ticket)
        release(traces_ticket)
        release(metrics_ticket)

    def test_releasing_logs_ticket_does_not_affect_traces_depth(self) -> None:
        set_queue_policy(QueuePolicy(logs_maxsize=5, traces_maxsize=5, metrics_maxsize=0))

        logs_t = try_acquire("logs")
        traces_t = try_acquire("traces")
        assert isinstance(logs_t, QueueTicket)
        assert isinstance(traces_t, QueueTicket)

        snap_before = get_health_snapshot()
        assert snap_before.queue_depth_logs == 1
        assert snap_before.queue_depth_traces == 1

        release(logs_t)

        snap_after = get_health_snapshot()
        assert snap_after.queue_depth_logs == 0
        assert snap_after.queue_depth_traces == 1  # unchanged

        release(traces_t)


class TestSamplingIsolation:
    """Sampling rate changes on one signal must not affect the other two."""

    def test_drop_all_logs_keeps_traces_and_metrics_at_full_rate(self) -> None:
        set_sampling_policy("logs", SamplingPolicy(default_rate=0.0))
        set_sampling_policy("traces", SamplingPolicy(default_rate=1.0))
        set_sampling_policy("metrics", SamplingPolicy(default_rate=1.0))

        logs_sampled = sum(1 for _ in range(100) if should_sample("logs"))
        traces_sampled = sum(1 for _ in range(100) if should_sample("traces"))
        metrics_sampled = sum(1 for _ in range(100) if should_sample("metrics"))

        assert logs_sampled == 0
        assert traces_sampled == 100
        assert metrics_sampled == 100

    def test_changing_traces_rate_does_not_alter_logs_or_metrics(self) -> None:
        set_sampling_policy("logs", SamplingPolicy(default_rate=1.0))
        set_sampling_policy("traces", SamplingPolicy(default_rate=1.0))
        set_sampling_policy("metrics", SamplingPolicy(default_rate=1.0))

        # Now drop all traces
        set_sampling_policy("traces", SamplingPolicy(default_rate=0.0))

        assert should_sample("logs") is True
        assert should_sample("traces") is False
        assert should_sample("metrics") is True


class TestHealthCounterIsolation:
    """Export failure on one signal must not increment counters for the others."""

    def test_logs_failure_does_not_increment_traces_or_metrics(self) -> None:
        record_export_failure("logs", ValueError("logs exploded"))

        snap = get_health_snapshot()
        assert snap.export_failures_logs == 1
        assert snap.export_failures_traces == 0
        assert snap.export_failures_metrics == 0

        assert snap.last_error_logs == "logs exploded"
        assert snap.last_error_traces is None
        assert snap.last_error_metrics is None

    def test_multiple_failures_on_different_signals_are_counted_independently(self) -> None:
        record_export_failure("logs", RuntimeError("log err"))
        record_export_failure("logs", RuntimeError("log err 2"))
        record_export_failure("traces", TimeoutError("trace timeout"))

        snap = get_health_snapshot()
        assert snap.export_failures_logs == 2
        assert snap.export_failures_traces == 1
        assert snap.export_failures_metrics == 0

        assert snap.last_error_logs == "log err 2"
        assert snap.last_error_traces == "trace timeout"
        assert snap.last_error_metrics is None
