# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Stress and saturation tests for the backpressure subsystem.

Exercises edge cases around queue saturation, rapid policy changes,
and high-volume acquire/release patterns.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

from provide.telemetry.backpressure import (
    QueuePolicy,
    QueueTicket,
    release,
    reset_queues_for_tests,
    set_queue_policy,
    try_acquire,
)
from provide.telemetry.health import get_health_snapshot, reset_health_for_tests

pytestmark = pytest.mark.integration

STRESS_WORKERS = 12
STRESS_ITERATIONS = 500


@pytest.fixture(autouse=True)
def _clean_state() -> None:
    reset_queues_for_tests()
    reset_health_for_tests()


class TestBackpressureSaturation:
    """Test behavior when queues are at or near capacity."""

    def test_saturated_queue_drops_all_excess(self) -> None:
        """Once the queue hits capacity, every subsequent acquire is dropped."""
        set_queue_policy(QueuePolicy(logs_maxsize=3))
        tickets = []
        for _ in range(3):
            t = try_acquire("logs")
            assert isinstance(t, QueueTicket)
            tickets.append(t)

        # All further attempts must be None
        for _ in range(100):
            assert try_acquire("logs") is None

        snap = get_health_snapshot()
        assert snap.dropped_logs == 100
        assert snap.queue_depth_logs == 3

        # Release one — next acquire should succeed
        release(tickets[0])
        t = try_acquire("logs")
        assert isinstance(t, QueueTicket) and t.signal == "logs"
        assert snap.queue_depth_logs == 3  # snap is frozen at read time

    def test_rapid_saturate_drain_cycles(self) -> None:
        """Repeatedly fill and drain the queue to max capacity."""
        maxsize = 10
        set_queue_policy(QueuePolicy(metrics_maxsize=maxsize))

        for _cycle in range(50):
            tickets = []
            for _ in range(maxsize):
                t = try_acquire("metrics")
                assert isinstance(t, QueueTicket)
                tickets.append(t)
            # At capacity
            assert try_acquire("metrics") is None
            # Drain
            for t in tickets:
                release(t)

        snap = get_health_snapshot()
        assert snap.queue_depth_metrics == 0
        assert snap.dropped_metrics == 50  # one drop per cycle

    def test_concurrent_saturation_total_consistency(self) -> None:
        """Under full contention, acquired + dropped equals total attempts."""
        maxsize = 8
        set_queue_policy(QueuePolicy(logs_maxsize=maxsize))
        barrier = threading.Barrier(STRESS_WORKERS)

        def _hammer() -> tuple[int, int]:
            barrier.wait(timeout=3.0)
            local_tickets: list[QueueTicket] = []
            local_dropped = 0
            for _ in range(STRESS_ITERATIONS):
                ticket = try_acquire("logs")
                if ticket is not None:
                    local_tickets.append(ticket)
                    # Hold briefly then release
                    release(ticket)
                else:
                    local_dropped += 1
            return len(local_tickets), local_dropped

        with ThreadPoolExecutor(max_workers=STRESS_WORKERS) as pool:
            futures = [pool.submit(_hammer) for _ in range(STRESS_WORKERS)]
            total_acquired = 0
            total_dropped = 0
            for f in as_completed(futures):
                a, d = f.result()
                total_acquired += a
                total_dropped += d

        total_attempts = STRESS_WORKERS * STRESS_ITERATIONS
        assert total_acquired + total_dropped == total_attempts

        snap = get_health_snapshot()
        assert snap.dropped_logs == total_dropped
        assert snap.queue_depth_logs == 0

    def test_all_signals_saturate_independently(self) -> None:
        """Saturating one signal does not affect another signal's queue."""
        set_queue_policy(QueuePolicy(logs_maxsize=2, traces_maxsize=3, metrics_maxsize=4))

        # Fill logs
        for _ in range(2):
            _t = try_acquire("logs")
            assert isinstance(_t, QueueTicket) and _t.signal == "logs"
        assert try_acquire("logs") is None

        # Traces should still work
        for _ in range(3):
            _t = try_acquire("traces")
            assert isinstance(_t, QueueTicket) and _t.signal == "traces"
        assert try_acquire("traces") is None

        # Metrics should still work
        for _ in range(4):
            _t = try_acquire("metrics")
            assert isinstance(_t, QueueTicket) and _t.signal == "metrics"
        assert try_acquire("metrics") is None

        snap = get_health_snapshot()
        assert snap.dropped_logs == 1
        assert snap.dropped_traces == 1
        assert snap.dropped_metrics == 1
        assert snap.queue_depth_logs == 2
        assert snap.queue_depth_traces == 3
        assert snap.queue_depth_metrics == 4

    def test_concurrent_mixed_signals_no_cross_contamination(self) -> None:
        """Threads operating on different signals don't interfere."""
        set_queue_policy(QueuePolicy(logs_maxsize=100, traces_maxsize=100, metrics_maxsize=100))
        barrier = threading.Barrier(3)

        def _work(signal: str) -> list[QueueTicket]:
            barrier.wait(timeout=2.0)
            tickets = []
            for _ in range(STRESS_ITERATIONS):
                t = try_acquire(signal)
                if t is not None:
                    tickets.append(t)
                    release(t)
            return tickets

        with ThreadPoolExecutor(max_workers=3) as pool:
            fl = pool.submit(_work, "logs")
            ft = pool.submit(_work, "traces")
            fm = pool.submit(_work, "metrics")

            logs_tickets = fl.result()
            traces_tickets = ft.result()
            metrics_tickets = fm.result()

        # Each signal should have gotten all its tickets
        assert len(logs_tickets) == STRESS_ITERATIONS
        assert len(traces_tickets) == STRESS_ITERATIONS
        assert len(metrics_tickets) == STRESS_ITERATIONS

        # All tokens are unique across all signals (global counter)
        all_tokens = (
            [t.token for t in logs_tickets] + [t.token for t in traces_tickets] + [t.token for t in metrics_tickets]
        )
        assert len(all_tokens) == len(set(all_tokens)), "Tokens must be globally unique"

        snap = get_health_snapshot()
        assert snap.queue_depth_logs == 0
        assert snap.queue_depth_traces == 0
        assert snap.queue_depth_metrics == 0
        assert snap.dropped_logs == 0
        assert snap.dropped_traces == 0
        assert snap.dropped_metrics == 0
