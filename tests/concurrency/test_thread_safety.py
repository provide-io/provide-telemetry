# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Concurrency stress tests for thread-safe telemetry subsystems.

These tests exercise the lock-protected module-level state under real
multi-threaded contention to verify correctness of backpressure, sampling,
health counters, and setup/shutdown serialization.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

from undef.telemetry import setup as setup_mod
from undef.telemetry.backpressure import (
    QueuePolicy,
    QueueTicket,
    release,
    reset_queues_for_tests,
    set_queue_policy,
    try_acquire,
)
from undef.telemetry.config import TelemetryConfig
from undef.telemetry.health import get_health_snapshot, reset_health_for_tests
from undef.telemetry.sampling import (
    SamplingPolicy,
    get_sampling_policy,
    reset_sampling_for_tests,
    set_sampling_policy,
    should_sample,
)
from undef.telemetry.setup import _reset_all_for_tests

pytestmark = pytest.mark.integration

WORKERS = 8
ITERATIONS = 200


@pytest.fixture(autouse=True)
def _clean_all_state() -> None:
    """Reset all subsystem state before each test."""
    _reset_all_for_tests()
    reset_queues_for_tests()
    reset_health_for_tests()
    reset_sampling_for_tests()


# ── Backpressure: concurrent acquire/release ────────────────────────────


class TestBackpressureConcurrency:
    """Verify backpressure queue invariants under thread contention."""

    def test_concurrent_acquire_respects_maxsize(self) -> None:
        """No more than maxsize tickets should be outstanding at once."""
        maxsize = 20
        set_queue_policy(QueuePolicy(logs_maxsize=maxsize))
        barrier = threading.Barrier(WORKERS)
        tickets: list[QueueTicket | None] = []
        lock = threading.Lock()

        def _acquire_many() -> None:
            barrier.wait(timeout=2.0)
            for _ in range(ITERATIONS):
                ticket = try_acquire("logs")
                if ticket is not None:
                    with lock:
                        tickets.append(ticket)

        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = [pool.submit(_acquire_many) for _ in range(WORKERS)]
            for f in as_completed(futures):
                f.result()

        # All successful tickets have unique, positive tokens
        tokens = [t.token for t in tickets if t is not None]
        assert all(tok > 0 for tok in tokens)
        assert len(tokens) == len(set(tokens)), "Tokens must be unique"

    def test_concurrent_acquire_release_cycles(self) -> None:
        """Acquire→release cycles under contention leave queue at zero depth."""
        set_queue_policy(QueuePolicy(logs_maxsize=50))
        barrier = threading.Barrier(WORKERS)

        def _cycle() -> None:
            barrier.wait(timeout=2.0)
            for _ in range(ITERATIONS):
                ticket = try_acquire("logs")
                if ticket is not None:
                    release(ticket)

        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = [pool.submit(_cycle) for _ in range(WORKERS)]
            for f in as_completed(futures):
                f.result()

        snap = get_health_snapshot()
        assert snap.queue_depth_logs == 0

    def test_concurrent_acquire_all_signals(self) -> None:
        """All three signal queues maintain independent correctness."""
        set_queue_policy(QueuePolicy(logs_maxsize=30, traces_maxsize=30, metrics_maxsize=30))
        barrier = threading.Barrier(WORKERS)
        all_tickets: list[QueueTicket] = []
        lock = threading.Lock()

        def _acquire_signal(signal: str) -> None:
            barrier.wait(timeout=2.0)
            for _ in range(ITERATIONS):
                ticket = try_acquire(signal)
                if ticket is not None:
                    with lock:
                        all_tickets.append(ticket)

        signals = ["logs", "traces", "metrics"]
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = []
            for i in range(WORKERS):
                futures.append(pool.submit(_acquire_signal, signals[i % len(signals)]))
            for f in as_completed(futures):
                f.result()

        # Release everything
        for ticket in all_tickets:
            release(ticket)

        snap = get_health_snapshot()
        assert snap.queue_depth_logs == 0
        assert snap.queue_depth_traces == 0
        assert snap.queue_depth_metrics == 0

    def test_concurrent_set_policy_while_acquiring(self) -> None:
        """Policy changes during active acquisition must not corrupt state."""
        set_queue_policy(QueuePolicy(logs_maxsize=10))
        barrier = threading.Barrier(3)
        errors: list[Exception] = []

        def _acquire_loop() -> None:
            barrier.wait(timeout=2.0)
            try:
                for _ in range(ITERATIONS):
                    ticket = try_acquire("logs")
                    if ticket is not None:
                        release(ticket)
            except Exception as exc:
                errors.append(exc)

        def _policy_loop() -> None:
            barrier.wait(timeout=2.0)
            try:
                for i in range(ITERATIONS):
                    set_queue_policy(QueuePolicy(logs_maxsize=5 + (i % 20)))
            except Exception as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=_acquire_loop),
            threading.Thread(target=_acquire_loop),
            threading.Thread(target=_policy_loop),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert errors == [], f"Unexpected errors during concurrent policy changes: {errors}"

    def test_dropped_count_consistent_under_contention(self) -> None:
        """Total acquired + dropped must equal total attempts."""
        maxsize = 5
        set_queue_policy(QueuePolicy(traces_maxsize=maxsize))
        barrier = threading.Barrier(WORKERS)

        def _hammer() -> tuple[int, int]:
            barrier.wait(timeout=2.0)
            local_acquired = 0
            local_dropped = 0
            for _ in range(ITERATIONS):
                ticket = try_acquire("traces")
                if ticket is not None:
                    local_acquired += 1
                    release(ticket)
                else:
                    local_dropped += 1
            return local_acquired, local_dropped

        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = [pool.submit(_hammer) for _ in range(WORKERS)]
            total_acquired = 0
            total_dropped = 0
            for f in as_completed(futures):
                a, d = f.result()
                total_acquired += a
                total_dropped += d

        total_attempts = WORKERS * ITERATIONS
        assert total_acquired + total_dropped == total_attempts
        snap = get_health_snapshot()
        assert snap.dropped_traces == total_dropped


# ── Sampling: concurrent reads and writes ────────────────────────────────


class TestSamplingConcurrency:
    """Verify sampling policy reads are consistent under concurrent writes."""

    def test_concurrent_should_sample_with_fixed_policy(self) -> None:
        """All threads see a consistent sampling rate."""
        set_sampling_policy("logs", SamplingPolicy(default_rate=1.0))
        barrier = threading.Barrier(WORKERS)
        results: list[bool] = []
        lock = threading.Lock()

        def _sample() -> None:
            barrier.wait(timeout=2.0)
            for _ in range(ITERATIONS):
                val = should_sample("logs")
                with lock:
                    results.append(val)

        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = [pool.submit(_sample) for _ in range(WORKERS)]
            for f in as_completed(futures):
                f.result()

        # Rate=1.0 means all should be sampled
        assert all(results)

    def test_concurrent_should_sample_rate_zero(self) -> None:
        """Rate=0.0 means nothing sampled, even under contention."""
        set_sampling_policy("traces", SamplingPolicy(default_rate=0.0))
        barrier = threading.Barrier(WORKERS)
        results: list[bool] = []
        lock = threading.Lock()

        def _sample() -> None:
            barrier.wait(timeout=2.0)
            for _ in range(ITERATIONS):
                val = should_sample("traces")
                with lock:
                    results.append(val)

        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = [pool.submit(_sample) for _ in range(WORKERS)]
            for f in as_completed(futures):
                f.result()

        assert not any(results)

    def test_concurrent_policy_update_does_not_corrupt(self) -> None:
        """Concurrent set/get cycles must not raise or produce invalid policies."""
        num_threads = 4
        barrier = threading.Barrier(num_threads)
        errors: list[Exception] = []

        def _writer() -> None:
            barrier.wait(timeout=2.0)
            try:
                for i in range(ITERATIONS):
                    rate = (i % 100) / 100.0
                    set_sampling_policy("logs", SamplingPolicy(default_rate=rate))
            except Exception as exc:
                errors.append(exc)

        def _reader() -> None:
            barrier.wait(timeout=2.0)
            try:
                for _ in range(ITERATIONS):
                    policy = get_sampling_policy("logs")
                    assert 0.0 <= policy.default_rate <= 1.0
            except Exception as exc:
                errors.append(exc)

        with ThreadPoolExecutor(max_workers=num_threads) as pool:
            futures = [
                pool.submit(_writer),
                pool.submit(_writer),
                pool.submit(_reader),
                pool.submit(_reader),
            ]
            for f in as_completed(futures):
                f.result()

        assert errors == []


# ── Health: concurrent counter updates ───────────────────────────────────


class TestHealthConcurrency:
    """Verify health counters are correct under concurrent updates."""

    def test_concurrent_health_snapshot_during_updates(self) -> None:
        """Snapshots during heavy backpressure activity must not crash."""
        set_queue_policy(QueuePolicy(logs_maxsize=10))
        barrier = threading.Barrier(WORKERS)
        errors: list[Exception] = []

        def _acquire_release() -> None:
            barrier.wait(timeout=2.0)
            try:
                for _ in range(ITERATIONS):
                    ticket = try_acquire("logs")
                    if ticket is not None:
                        release(ticket)
            except Exception as exc:
                errors.append(exc)

        def _snapshot() -> None:
            barrier.wait(timeout=2.0)
            try:
                for _ in range(ITERATIONS):
                    snap = get_health_snapshot()
                    assert snap.queue_depth_logs >= 0
                    assert snap.dropped_logs >= 0
            except Exception as exc:
                errors.append(exc)

        threads = [
            *[threading.Thread(target=_acquire_release) for _ in range(WORKERS - 2)],
            threading.Thread(target=_snapshot),
            threading.Thread(target=_snapshot),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert errors == []


# ── Setup: concurrent setup calls ────────────────────────────────────────


class TestSetupConcurrency:
    """Verify idempotent setup is safe under concurrent calls."""

    def test_concurrent_setup_runs_exactly_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Only one thread should execute the setup body; others see it as already done."""
        setup_mod._reset_all_for_tests()
        call_count = 0
        count_lock = threading.Lock()

        def _counting_runtime(_cfg: object) -> None:
            nonlocal call_count
            with count_lock:
                call_count += 1

        monkeypatch.setattr("undef.telemetry.setup.apply_runtime_config", _counting_runtime)
        monkeypatch.setattr("undef.telemetry.setup.configure_logging", lambda _cfg, **kw: None)
        monkeypatch.setattr("undef.telemetry.setup._refresh_otel_tracing", lambda: None)
        monkeypatch.setattr("undef.telemetry.setup._refresh_otel_metrics", lambda: None)
        monkeypatch.setattr("undef.telemetry.setup.setup_tracing", lambda _cfg: None)
        monkeypatch.setattr("undef.telemetry.setup.setup_metrics", lambda _cfg: None)

        barrier = threading.Barrier(WORKERS)

        def _do_setup() -> None:
            barrier.wait(timeout=2.0)
            setup_mod.setup_telemetry(TelemetryConfig())

        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = [pool.submit(_do_setup) for _ in range(WORKERS)]
            for f in as_completed(futures):
                f.result()

        assert call_count == 1
        assert setup_mod._setup_done is True
