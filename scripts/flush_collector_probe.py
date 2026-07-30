#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Prove ``flush_telemetry()`` puts records on the wire without tearing providers down.

Why a standalone process rather than a case in tests/integration: the collector
is verified by grepping its debug log after the run, which cannot tell *when* a
record arrived. If this process also called ``shutdown_telemetry()``, shutdown's
own drain would be an equally good explanation for anything that showed up, and
the check would pass with flush completely broken.

So this exits without shutting down. Every signal named below can only have
reached the collector because flush sent it.

It also emits a second batch *after* the flush and asserts the providers are
still installed, which is the other half of the contract — flush drains, it does
not tear down.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from provide.telemetry import (
    counter,
    flush_telemetry,
    get_logger,
    get_runtime_status,
    setup_telemetry,
    trace,
)
from provide.telemetry.config import TelemetryConfig


def _signal_endpoint(base: str, signal: str) -> str:
    return f"{base.rstrip('/')}/v1/{signal}"


def _fail(message: str) -> None:
    print(f"flush-collector-probe: FAIL — {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    endpoint = os.getenv("PROVIDE_TEST_OTLP_ENDPOINT")
    if not endpoint:
        print("flush-collector-probe: PROVIDE_TEST_OTLP_ENDPOINT unset; skipping", file=sys.stderr)
        return 0

    setup_telemetry(
        TelemetryConfig.from_env(
            {
                "PROVIDE_TELEMETRY_SERVICE_NAME": "provide-telemetry-integration",
                "PROVIDE_TRACE_ENABLED": "true",
                "PROVIDE_METRICS_ENABLED": "true",
                "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": _signal_endpoint(endpoint, "traces"),
                "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT": _signal_endpoint(endpoint, "metrics"),
                "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": _signal_endpoint(endpoint, "logs"),
            }
        )
    )

    before = get_runtime_status()
    providers = before["providers"]
    assert isinstance(providers, dict)
    if not all(providers.get(signal) for signal in ("traces", "metrics", "logs")):
        _fail(f"providers not installed before flush: {providers}")

    # Batch one — only a working flush can deliver this, since we never shut down.
    @trace("integration.flush.span")
    def _work() -> None:
        get_logger("integration.flush").info("integration.flush.log", suite="flush")
        counter("integration.flush.requests").add(1, {"suite": "flush"})

    _work()

    if not flush_telemetry():
        _fail("flush_telemetry() reported an incomplete drain against a reachable collector")

    # Flush drains; it must not tear down.
    after = get_runtime_status()
    after_providers = after["providers"]
    assert isinstance(after_providers, dict)
    if not all(after_providers.get(signal) for signal in ("traces", "metrics", "logs")):
        _fail(f"flush tore providers down: {after_providers}")
    if not after["setup_done"]:
        _fail("flush cleared setup state")

    @trace("integration.flush.after.span")
    def _work_again() -> None:
        get_logger("integration.flush").info("integration.flush.after.log", suite="flush-after")
        counter("integration.flush.requests").add(1, {"suite": "flush-after"})

    _work_again()

    if not flush_telemetry():
        _fail("a second flush_telemetry() reported an incomplete drain; flush is not repeatable")

    print("flush-collector-probe: OK — flushed twice, providers still installed", file=sys.stderr)
    # Deliberately no shutdown_telemetry(): see the module docstring.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
