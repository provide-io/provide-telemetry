#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Memray stress test for backpressure queue and health snapshot paths."""

from __future__ import annotations

from provide.telemetry.backpressure import (
    QueuePolicy,
    release,
    set_queue_policy,
    try_acquire,
)
from provide.telemetry.health import get_health_snapshot, reset_health_for_tests

SIGNALS = ("logs", "traces", "metrics")


def main() -> None:
    """Run backpressure and health stress cycles."""
    # Unbounded queue (maxsize=0) acquire/release: 300K cycles per signal
    set_queue_policy(QueuePolicy())
    for _ in range(300_000):
        for sig in SIGNALS:
            ticket = try_acquire(sig)
            release(ticket)

    # Bounded queue acquire/release: 200K cycles
    set_queue_policy(QueuePolicy(logs_maxsize=1000, traces_maxsize=1000, metrics_maxsize=1000))
    for _ in range(200_000):
        for sig in SIGNALS:
            ticket = try_acquire(sig)
            release(ticket)

    # Health snapshot collection: 50K cycles
    for _ in range(50_000):
        get_health_snapshot()

    # Cleanup
    reset_health_for_tests()
    set_queue_policy(QueuePolicy())


if __name__ == "__main__":
    main()
