# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Tests targeting surviving mutants in backpressure.py."""

from __future__ import annotations

import pytest

from undef.telemetry.backpressure import (
    QueuePolicy,
    QueueTicket,
    _maxsize,
    get_queue_policy,
    release,
    reset_queues_for_tests,
    set_queue_policy,
    try_acquire,
)
from undef.telemetry.health import get_health_snapshot, reset_health_for_tests


@pytest.fixture(autouse=True)
def _clean_state() -> None:
    """Reset backpressure queues and health counters before each test."""
    reset_queues_for_tests()
    reset_health_for_tests()


# ── _maxsize returns the correct field per signal ──────────────────────


def test_maxsize_returns_traces_maxsize() -> None:
    policy = QueuePolicy(logs_maxsize=10, traces_maxsize=20, metrics_maxsize=30)
    set_queue_policy(policy)
    assert _maxsize("traces") == 20


def test_maxsize_returns_metrics_maxsize() -> None:
    policy = QueuePolicy(logs_maxsize=10, traces_maxsize=20, metrics_maxsize=30)
    set_queue_policy(policy)
    assert _maxsize("metrics") == 30


def test_maxsize_returns_logs_maxsize_for_logs() -> None:
    policy = QueuePolicy(logs_maxsize=10, traces_maxsize=20, metrics_maxsize=30)
    set_queue_policy(policy)
    assert _maxsize("logs") == 10


def test_maxsize_returns_logs_maxsize_for_unknown_signal() -> None:
    policy = QueuePolicy(logs_maxsize=10, traces_maxsize=20, metrics_maxsize=30)
    set_queue_policy(policy)
    assert _maxsize("unknown") == 10


# ── try_acquire with unknown signal falls back to "logs" ───────────────


def test_try_acquire_unknown_signal_falls_back_to_logs() -> None:
    set_queue_policy(QueuePolicy(logs_maxsize=1, traces_maxsize=1, metrics_maxsize=1))
    ticket = try_acquire("bogus")
    assert ticket is not None
    assert ticket.signal == "logs"


# ── token=0 when maxsize is 0 (unbounded) ─────────────────────────────


def test_try_acquire_unbounded_returns_token_zero() -> None:
    set_queue_policy(QueuePolicy(logs_maxsize=0))
    ticket = try_acquire("logs")
    assert ticket is not None
    assert ticket.token == 0


# ── maxsize boundary: at capacity → None, under capacity → ticket ──────


def test_try_acquire_at_capacity_returns_none() -> None:
    set_queue_policy(QueuePolicy(logs_maxsize=2))
    t1 = try_acquire("logs")
    t2 = try_acquire("logs")
    assert t1 is not None
    assert t2 is not None
    # Queue is now full (2/2)
    t3 = try_acquire("logs")
    assert t3 is None


def test_try_acquire_under_capacity_returns_ticket() -> None:
    set_queue_policy(QueuePolicy(logs_maxsize=2))
    t1 = try_acquire("logs")
    assert t1 is not None
    # Queue has 1/2 — still under capacity
    t2 = try_acquire("logs")
    assert t2 is not None
    assert t2.token > 0


def test_try_acquire_exactly_at_boundary() -> None:
    """With maxsize=1, first acquire succeeds, second fails."""
    set_queue_policy(QueuePolicy(logs_maxsize=1))
    t1 = try_acquire("logs")
    assert t1 is not None
    assert t1.token > 0
    t2 = try_acquire("logs")
    assert t2 is None


# ── release with token=0 is a no-op ───────────────────────────────────


def test_release_token_zero_is_noop() -> None:
    set_queue_policy(QueuePolicy(logs_maxsize=5))
    ticket = QueueTicket(signal="logs", token=0)
    # Should not raise or alter queue depth
    release(ticket)
    snap = get_health_snapshot()
    assert snap.queue_depth_logs == 0


def test_release_none_is_noop() -> None:
    release(None)
    snap = get_health_snapshot()
    assert snap.queue_depth_logs == 0


# ── release with unknown signal falls back to "logs" ──────────────────


def test_release_unknown_signal_falls_back_to_logs() -> None:
    set_queue_policy(QueuePolicy(logs_maxsize=5))
    # Acquire on logs to put something in the logs queue
    ticket = try_acquire("logs")
    assert ticket is not None
    snap_before = get_health_snapshot()
    assert snap_before.queue_depth_logs == 1
    # Craft a ticket with an unknown signal but a valid token from the logs queue
    fake_ticket = QueueTicket(signal="unknown", token=ticket.token)
    release(fake_ticket)
    snap_after = get_health_snapshot()
    assert snap_after.queue_depth_logs == 0


# ── set_queue_policy resets queue depth to 0 (not 1) ──────────────────


def test_set_queue_policy_resets_depth_to_zero() -> None:
    set_queue_policy(QueuePolicy(logs_maxsize=5))
    try_acquire("logs")
    try_acquire("logs")
    snap = get_health_snapshot()
    assert snap.queue_depth_logs == 2
    # Reset via new policy
    set_queue_policy(QueuePolicy(logs_maxsize=10))
    snap = get_health_snapshot()
    assert snap.queue_depth_logs == 0
    assert snap.queue_depth_traces == 0
    assert snap.queue_depth_metrics == 0


def test_set_queue_policy_iterates_all_three_signals() -> None:
    """Ensure the for-loop touches logs, traces, AND metrics."""
    set_queue_policy(QueuePolicy(logs_maxsize=5, traces_maxsize=5, metrics_maxsize=5))
    try_acquire("logs")
    try_acquire("traces")
    try_acquire("metrics")
    snap = get_health_snapshot()
    assert snap.queue_depth_logs == 1
    assert snap.queue_depth_traces == 1
    assert snap.queue_depth_metrics == 1
    # Reset
    set_queue_policy(QueuePolicy())
    snap = get_health_snapshot()
    assert snap.queue_depth_logs == 0
    assert snap.queue_depth_traces == 0
    assert snap.queue_depth_metrics == 0


# ── cumulative acquire yields non-zero positive tokens ─────────────────


def test_cumulative_acquire_tokens_are_positive_and_unique() -> None:
    set_queue_policy(QueuePolicy(logs_maxsize=10))
    tokens: list[int] = []
    for _ in range(5):
        ticket = try_acquire("logs")
        assert ticket is not None
        assert ticket.token > 0
        tokens.append(ticket.token)
    assert len(set(tokens)) == 5, "All tokens must be unique"


# ── increment_dropped is called when queue is full ─────────────────────


def test_increment_dropped_on_full_queue() -> None:
    set_queue_policy(QueuePolicy(logs_maxsize=1))
    try_acquire("logs")  # fills queue
    snap_before = get_health_snapshot()
    assert snap_before.dropped_logs == 0
    # This should be rejected → increment_dropped
    result = try_acquire("logs")
    assert result is None
    snap_after = get_health_snapshot()
    assert snap_after.dropped_logs == 1


def test_increment_dropped_multiple_rejections() -> None:
    set_queue_policy(QueuePolicy(traces_maxsize=1))
    try_acquire("traces")
    for _i in range(3):
        assert try_acquire("traces") is None
    snap = get_health_snapshot()
    assert snap.dropped_traces == 3


# ── get_queue_policy returns current policy ────────────────────────────


def test_get_queue_policy_returns_current() -> None:
    policy = QueuePolicy(logs_maxsize=7, traces_maxsize=8, metrics_maxsize=9)
    set_queue_policy(policy)
    assert get_queue_policy() == policy


# ── release updates queue depth correctly ──────────────────────────────


def test_release_decrements_queue_depth() -> None:
    set_queue_policy(QueuePolicy(logs_maxsize=5))
    t1 = try_acquire("logs")
    t2 = try_acquire("logs")
    assert t1 is not None
    assert t2 is not None
    snap = get_health_snapshot()
    assert snap.queue_depth_logs == 2
    release(t1)
    snap = get_health_snapshot()
    assert snap.queue_depth_logs == 1
    release(t2)
    snap = get_health_snapshot()
    assert snap.queue_depth_logs == 0


def test_release_updates_correct_signal_queue_depth() -> None:
    """Kills set_queue_depth(None, ...) mutant - verifies signal is passed correctly."""
    set_queue_policy(QueuePolicy(traces_maxsize=5))
    ticket = try_acquire("traces")
    assert ticket is not None
    snap = get_health_snapshot()
    assert snap.queue_depth_traces == 1
    assert snap.queue_depth_logs == 0
    release(ticket)
    snap = get_health_snapshot()
    assert snap.queue_depth_traces == 0
    assert snap.queue_depth_logs == 0


def test_release_with_already_released_token_is_safe() -> None:
    set_queue_policy(QueuePolicy(logs_maxsize=5))
    ticket = try_acquire("logs")
    assert ticket is not None
    release(ticket)
    # Double release should not raise
    release(ticket)
    snap = get_health_snapshot()
    assert snap.queue_depth_logs == 0


# ── maxsize <= 0 vs < 0 boundary (kills the <= 0 → < 0 mutant) ───────


def test_maxsize_negative_still_unbounded() -> None:
    """Negative maxsize should behave the same as 0 (unbounded)."""
    set_queue_policy(QueuePolicy(logs_maxsize=-1))
    ticket = try_acquire("logs")
    assert ticket is not None
    assert ticket.token == 0


def test_maxsize_zero_is_unbounded() -> None:
    set_queue_policy(QueuePolicy(logs_maxsize=0))
    ticket = try_acquire("logs")
    assert ticket is not None
    assert ticket.token == 0


# ── len(queue) >= maxsize vs > maxsize boundary ───────────────────────


def test_acquire_rejected_at_exactly_maxsize() -> None:
    """When len(queue) == maxsize, the next acquire must be rejected.

    This kills the mutant that changes >= to >.
    """
    set_queue_policy(QueuePolicy(metrics_maxsize=3))
    for _ in range(3):
        t = try_acquire("metrics")
        assert t is not None
    # len(queue) is now exactly 3 == maxsize; must reject
    assert try_acquire("metrics") is None


# ── token=0 → token=1 mutant killer ──────────────────────────────────


def test_unbounded_ticket_token_is_exactly_zero() -> None:
    """Explicitly verify the token is 0, not 1."""
    set_queue_policy(QueuePolicy(logs_maxsize=0))
    ticket = try_acquire("logs")
    assert ticket is not None
    assert ticket.token == 0
    assert ticket.token != 1


# ── release token==0 vs token==1 mutant killer ────────────────────────


def test_release_token_one_removes_from_queue() -> None:
    """A ticket with token=1 (non-zero) SHOULD be removed from the queue,
    unlike token=0 which is a no-op. This kills the == 0 → == 1 mutant."""
    set_queue_policy(QueuePolicy(logs_maxsize=10))
    ticket = try_acquire("logs")
    assert ticket is not None
    assert ticket.token > 0
    snap = get_health_snapshot()
    assert snap.queue_depth_logs == 1
    release(ticket)
    snap = get_health_snapshot()
    assert snap.queue_depth_logs == 0
