#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""🎲 Sampling policies and backpressure queue controls.

Demonstrates:
- SamplingPolicy with default_rate and per-key overrides
- set_sampling_policy / get_sampling_policy / should_sample
- QueuePolicy with per-signal maxsize
- set_queue_policy / get_queue_policy
- HealthSnapshot: dropped counts and queue depths
"""

from __future__ import annotations

import asyncio

from provide.telemetry import (
    QueuePolicy,
    SamplingPolicy,
    counter,
    event,
    get_health_snapshot,
    get_logger,
    get_queue_policy,
    get_sampling_policy,
    set_queue_policy,
    set_sampling_policy,
    setup_telemetry,
    should_sample,
    shutdown_telemetry,
    trace,
)


@trace(event("example", "sampling", "concurrent"))
async def _traced_work(task_id: int) -> None:
    await asyncio.sleep(0.15)
    counter("example.sampling.counter").add(1, {"task_id": str(task_id)})


async def _run() -> None:
    log = get_logger("examples.sampling")

    # ── 🎲 Sampling policies with overrides ─────────────────
    print("🎲 Setting sampling policies...")
    set_sampling_policy(
        "logs",
        SamplingPolicy(default_rate=0.0, overrides={"example.critical": 1.0}),
    )
    set_sampling_policy("metrics", SamplingPolicy(default_rate=1.0))
    set_sampling_policy("traces", SamplingPolicy(default_rate=1.0))

    # ── 🔍 Inspect active policies ──────────────────────────
    logs_policy = get_sampling_policy("logs")
    print(f"  📋 logs:    default_rate={logs_policy.default_rate}, overrides={logs_policy.overrides}")
    print(f"  📋 metrics: default_rate={get_sampling_policy('metrics').default_rate}")
    print(f"  📋 traces:  default_rate={get_sampling_policy('traces').default_rate}")

    # ── 🎯 should_sample with overrides ─────────────────────
    print("\n🎯 should_sample() decisions:")
    for key in ("example.routine", "example.critical"):
        sampled = should_sample("logs", key=key)
        icon = "✅" if sampled else "❌"
        print(f"  {icon} logs/{key}: sampled={sampled}")

    # ── 🚧 Backpressure queue limits ────────────────────────
    print("\n🚧 Setting queue policy (traces_maxsize=1)...")
    set_queue_policy(QueuePolicy(logs_maxsize=0, metrics_maxsize=0, traces_maxsize=1))
    qp = get_queue_policy()
    print(f"  📋 Queue policy: logs={qp.logs_maxsize}, traces={qp.traces_maxsize}, metrics={qp.metrics_maxsize}")

    # ── ⚡ Concurrent traced work (will saturate queue) ─────
    print("\n⚡ Launching 5 concurrent traced tasks...")
    tasks = [asyncio.create_task(_traced_work(i)) for i in range(5)]
    await asyncio.gather(*tasks)
    print("  ✅ All tasks completed")

    # This event itself is sampled out (logs rate=0%).
    log.info(event("example", "sampling", "done"))

    # ── 📊 Health snapshot ──────────────────────────────────
    print("\n📊 Health snapshot after saturation:")
    snapshot = get_health_snapshot()
    print(f"  📉 dropped_logs:         {snapshot.dropped_logs}")
    print(f"  📉 dropped_traces:       {snapshot.dropped_traces}")
    print(f"  📉 dropped_metrics:      {snapshot.dropped_metrics}")
    print(f"  📤 export_failures_traces: {snapshot.export_failures_traces}")

    print("\n🏁 Done!")


def main() -> None:
    print("🎲 Sampling & Backpressure Demo\n")
    setup_telemetry()
    asyncio.run(_run())
    shutdown_telemetry()


if __name__ == "__main__":
    main()
