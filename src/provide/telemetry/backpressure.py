# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Bounded queue controls for telemetry signal paths."""

from __future__ import annotations

import itertools
import threading
from collections import deque
from dataclasses import dataclass

from provide.telemetry.health import increment_dropped

Signal = str


@dataclass(frozen=True, slots=True)
class QueuePolicy:
    logs_maxsize: int = 0
    traces_maxsize: int = 0
    metrics_maxsize: int = 0


@dataclass(frozen=True, slots=True)
class QueueTicket:
    signal: Signal
    token: int


_lock = threading.Lock()
_tokens = itertools.count(1)
_policy = QueuePolicy()
_queues: dict[Signal, deque[int]] = {
    "logs": deque(),
    "traces": deque(),
    "metrics": deque(),
}
_VALID_SIGNALS = frozenset(_queues)

# Pre-allocated tickets for unlimited queues — avoid allocation per call.
_UNLIMITED_TICKETS: dict[Signal, QueueTicket] = {
    sig: QueueTicket(signal=sig, token=0)
    for sig in _queues  # pragma: no mutate
}


def _validate_signal(signal: Signal) -> Signal:
    if signal not in _VALID_SIGNALS:
        raise ValueError(f"unknown signal {signal!r}, expected one of {sorted(_VALID_SIGNALS)}")
    return signal


def set_queue_policy(policy: QueuePolicy) -> None:
    global _policy
    with _lock:
        _policy = policy


def get_queue_policy() -> QueuePolicy:
    with _lock:
        return _policy


def _maxsize(signal: Signal) -> int:
    if signal == "traces":
        return _policy.traces_maxsize
    if signal == "metrics":
        return _policy.metrics_maxsize
    return _policy.logs_maxsize


def try_acquire(signal: Signal) -> QueueTicket | None:
    signal = _validate_signal(signal)
    return _try_acquire_unchecked(signal)


def _try_acquire_unchecked(signal: Signal) -> QueueTicket | None:
    """Hot-path acquire — caller must pass a validated signal."""
    # Fast path: unlimited queue — no lock, no allocation.
    # GIL makes _policy reference read + frozen dataclass field read atomic.
    maxsize = _maxsize(signal)
    if maxsize <= 0:
        return _UNLIMITED_TICKETS[signal]
    with _lock:
        queue = _queues[signal]
        if len(queue) >= maxsize:
            increment_dropped(signal)
            return None
        token = next(_tokens)
        queue.append(token)
        return QueueTicket(signal=signal, token=token)


def release(ticket: QueueTicket | None) -> None:
    if ticket is None:
        return
    if ticket.token == 0:
        return
    with _lock:
        queue = _queues[ticket.signal if ticket.signal in _queues else "logs"]
        try:
            queue.remove(ticket.token)
        except ValueError:
            return


def reset_queues_for_tests() -> None:
    global _policy, _tokens
    with _lock:
        _policy = QueuePolicy()
        _tokens = itertools.count(1)
        for signal in ("logs", "traces", "metrics"):
            _queues[signal].clear()
