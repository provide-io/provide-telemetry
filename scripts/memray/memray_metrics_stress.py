#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Memray stress test for metrics instrument recording path."""

from __future__ import annotations

from provide.telemetry.metrics.fallback import Counter, Gauge, Histogram

ATTRS = {"route": "/api/v1/users", "method": "GET", "status_code": "200"}


def main() -> None:
    """Run metrics instrument stress cycles."""
    c = Counter("http.requests.total")
    g = Gauge("connection.pool.size")
    h = Histogram("http.request.duration_ms")

    # Counter.add: 300K calls
    for _ in range(300_000):
        c.add(1, ATTRS)

    # Gauge.set: 200K calls
    for i in range(200_000):
        g.set(i % 100, ATTRS)

    # Histogram.record: 300K calls
    for i in range(300_000):
        h.record(float(i % 1000), ATTRS)

    # No-attributes path: 200K calls (exercises `attributes or {}` branch)
    for _ in range(200_000):
        c.add(1)
        h.record(1.0)


if __name__ == "__main__":
    main()
