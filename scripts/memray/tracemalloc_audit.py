#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""tracemalloc-based audit: counts Python-level allocations per hot-path call."""

from __future__ import annotations

import tracemalloc

from provide.telemetry.backpressure import QueuePolicy, release, set_queue_policy, try_acquire
from provide.telemetry.health import get_health_snapshot
from provide.telemetry.logger.context import bind_context, get_context
from provide.telemetry.logger.processors import merge_runtime_context, sanitize_sensitive_fields
from provide.telemetry.pii import sanitize_payload
from provide.telemetry.sampling import should_sample
from provide.telemetry.schema.events import event_name
from provide.telemetry.tracing.context import get_span_id, get_trace_id, set_trace_context


def _measure(label: str, iterations: int, fn: object) -> None:
    """Run fn() iterations times, report per-call allocation stats."""
    callable_fn = fn  # type: ignore[assignment]
    # Warmup
    for _ in range(min(100, iterations)):
        callable_fn()

    tracemalloc.start()
    snap1 = tracemalloc.take_snapshot()
    for _ in range(iterations):
        callable_fn()
    snap2 = tracemalloc.take_snapshot()
    tracemalloc.stop()

    stats = snap2.compare_to(snap1, "lineno")
    total_blocks = sum(s.count_diff for s in stats if s.count_diff > 0)
    total_bytes = sum(s.size_diff for s in stats if s.size_diff > 0)
    per_call_blocks = total_blocks / iterations if iterations > 0 else 0
    per_call_bytes = total_bytes / iterations if iterations > 0 else 0

    print(
        f"{label:45s}  {per_call_blocks:8.2f} allocs/call  {per_call_bytes:8.1f} bytes/call  ({total_blocks:,} total)"
    )
    if total_blocks > 0:
        top = sorted(stats, key=lambda s: s.count_diff, reverse=True)[:3]
        for s in top:
            if s.count_diff > 0:
                print(f"  {s.traceback}  +{s.count_diff} blocks  +{s.size_diff} bytes")


def main() -> None:
    """Audit per-call allocation cost of every hot-path function."""
    n = 50_000
    print(f"tracemalloc audit — {n:,} iterations per function\n")
    print(f"{'Function':45s}  {'allocs/call':>16s}  {'bytes/call':>14s}  {'total blocks':>16s}")
    print("-" * 100)

    # Logger context
    bind_context(session_id="sess-001", user_id="u-1234")
    _measure("get_context()", n, get_context)

    # Trace context — direct accessors
    set_trace_context("abc123", "def456")
    _measure("get_trace_id()", n, get_trace_id)
    _measure("get_span_id()", n, get_span_id)

    # merge_runtime_context processor
    sanitize = sanitize_sensitive_fields(enabled=True)
    payload = {"event": "test", "password": "secret", "request_id": "r1"}
    _measure(
        "merge_runtime_context()",
        n,
        lambda: merge_runtime_context(None, "info", dict(payload)),
    )

    # sanitize processor
    _measure(
        "sanitize_sensitive_fields()()",
        n,
        lambda: sanitize(None, "info", dict(payload)),
    )

    # event_name
    _measure("event_name(3 segments)", n, lambda: event_name("auth", "login", "success"))

    # sanitize_payload
    _measure(
        "sanitize_payload(flat, enabled)",
        n,
        lambda: sanitize_payload(payload, enabled=True),
    )
    _measure(
        "sanitize_payload(flat, disabled)",
        n,
        lambda: sanitize_payload(payload, enabled=False),
    )

    # should_sample
    _measure("should_sample('logs')", n, lambda: should_sample("logs"))
    _measure("should_sample('logs', key=...)", n, lambda: should_sample("logs", key="auth.login"))

    # backpressure
    set_queue_policy(QueuePolicy())
    _measure(
        "try_acquire + release (unbounded)",
        n,
        lambda: release(try_acquire("logs")),
    )

    # health snapshot
    _measure("get_health_snapshot()", n, get_health_snapshot)


if __name__ == "__main__":
    main()
