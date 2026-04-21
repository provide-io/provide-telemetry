#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""🛡️ Exporter resilience — retries, timeouts, and failure policies.

Demonstrates:
- ExporterPolicy with fail_open=True vs fail_open=False
- timeout_seconds for deadline enforcement
- get_exporter_policy to inspect active policy
- Health snapshot: retries, export failures, latency, last error
"""

from __future__ import annotations

import time

from provide.telemetry import ExporterPolicy, get_exporter_policy, get_health_snapshot, set_exporter_policy
from provide.telemetry.resilience import get_circuit_state, run_with_resilience


def main() -> None:
    print("🛡️  Exporter Resilience Demo\n")

    # ── 🟢 Fail-open: returns None on failure ────────────
    print("🟢 Fail-open mode (retries=1, backoff=0s)")
    set_exporter_policy("logs", ExporterPolicy(retries=1, backoff_seconds=0.0, fail_open=True))

    attempts_open = {"count": 0}

    def flaky_fail_open() -> str:
        attempts_open["count"] += 1
        raise RuntimeError("simulated exporter failure")

    result = run_with_resilience("logs", flaky_fail_open)
    policy = get_exporter_policy("logs")
    print(f"  📦 Result: {result}")
    print(f"  🔄 Attempts: {attempts_open['count']}")
    print(f"  📋 Policy: retries={policy.retries}, fail_open={policy.fail_open}")

    # ── 🔴 Fail-closed: raises on failure ────────────────
    print("\n🔴 Fail-closed mode (retries=1, backoff=0s)")
    set_exporter_policy("logs", ExporterPolicy(retries=1, backoff_seconds=0.0, fail_open=False))

    attempts_closed = {"count": 0}

    def flaky_fail_closed() -> str:
        attempts_closed["count"] += 1
        raise RuntimeError("simulated hard failure")

    try:
        run_with_resilience("logs", flaky_fail_closed)
    except RuntimeError as exc:
        print(f"  💥 Caught: {exc}")
        print(f"  🔄 Attempts: {attempts_closed['count']}")

    # ── ⏱️ Timeout enforcement ────────────────────────────
    print("\n⏱️  Timeout enforcement (timeout=0.05s)")
    set_exporter_policy(
        "traces",
        ExporterPolicy(retries=0, timeout_seconds=0.05, fail_open=True),
    )

    def slow_export() -> str:
        time.sleep(0.2)
        return "too late"

    timed_out = run_with_resilience("traces", slow_export)
    print(f"  📦 Result: {timed_out}  (None = timed out, fail-open)")

    # ── 🔌 Circuit breaker with exponential backoff ─────────
    print("\n🔌 Circuit breaker (exponential backoff + half-open probing)")
    set_exporter_policy(
        "metrics",
        ExporterPolicy(retries=0, timeout_seconds=0.01, fail_open=True),
    )

    def always_timeout() -> str:
        time.sleep(1)
        return "never"

    for _i in range(4):
        run_with_resilience("metrics", always_timeout)

    state, open_count, cooldown_remaining = get_circuit_state("metrics")
    print(f"  🔌 Circuit state:     {state}")
    print(f"  📈 Open count:        {open_count}")
    print(f"  ⏳ Cooldown remaining: {cooldown_remaining:.1f}s")

    # ── 📊 Health snapshot ────────────────────────────────
    print("\n📊 Health snapshot after all operations:")
    snapshot = get_health_snapshot()
    print(f"  🔄 retries_logs:          {snapshot.retries_logs}")
    print(f"  ❌ export_failures_logs:   {snapshot.export_failures_logs}")
    print(f"  ❌ export_failures_traces:  {snapshot.export_failures_traces}")
    print(f"  ⏱️  latency_ms_traces:     {snapshot.export_latency_ms_traces}")
    print(f"  🔌 circuit_state_metrics:  {snapshot.circuit_state_metrics}")
    print(f"  📈 circuit_open_count:     {snapshot.circuit_open_count_metrics}")
    print(f"  🛑 setup_error:           {snapshot.setup_error}")

    print("\n🏁 Done!")


if __name__ == "__main__":
    main()
