#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Memray stress test for @trace decorator context save/restore path."""

from __future__ import annotations

from undef.telemetry.tracing.context import get_span_id, get_trace_id, set_trace_context
from undef.telemetry.tracing.decorators import trace


@trace("sync_operation")
def _sync_fn() -> int:
    return 1


def main() -> None:
    """Run tracing decorator stress cycles."""
    # Set up initial trace context
    set_trace_context("root-trace-id", "root-span-id")

    # Sync decorated function: 200K calls
    # Each call exercises: should_sample → try_acquire → get_trace_id/get_span_id
    #   → start_as_current_span → _sync_otel_trace_context → set_trace_context → release
    for _ in range(200_000):
        _sync_fn()

    # Direct context accessors: 500K calls (simulates the hot path without OTel overhead)
    for _ in range(500_000):
        get_trace_id()
        get_span_id()

    # Context save/restore cycle: 200K calls
    for _ in range(200_000):
        prev_trace = get_trace_id()
        prev_span = get_span_id()
        set_trace_context("child-trace", "child-span")
        set_trace_context(prev_trace, prev_span)


if __name__ == "__main__":
    main()
