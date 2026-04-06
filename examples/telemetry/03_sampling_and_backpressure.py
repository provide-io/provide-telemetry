#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

from __future__ import annotations

import asyncio

from provide.telemetry import (
    QueuePolicy,
    SamplingPolicy,
    counter,
    event,
    get_health_snapshot,
    get_logger,
    set_queue_policy,
    set_sampling_policy,
    setup_telemetry,
    shutdown_telemetry,
    trace,
)


@trace(event("example", "sampling", "concurrent"))
async def _traced_work(task_id: int) -> None:
    await asyncio.sleep(0.15)
    counter("example.sampling.counter").add(1, {"task_id": str(task_id)})


async def _run() -> None:
    log = get_logger("examples.sampling")

    set_sampling_policy("logs", SamplingPolicy(default_rate=0.0))
    set_sampling_policy("metrics", SamplingPolicy(default_rate=1.0))
    set_sampling_policy("traces", SamplingPolicy(default_rate=1.0))
    set_queue_policy(QueuePolicy(logs_maxsize=0, metrics_maxsize=0, traces_maxsize=1))

    tasks = [asyncio.create_task(_traced_work(i)) for i in range(5)]
    await asyncio.gather(*tasks)

    # This event itself is sampled out (logs rate=0%).
    log.info(event("example", "sampling", "done"))

    snapshot = get_health_snapshot()
    print(f"  📉 dropped_logs:         {snapshot.dropped_logs}")
    print(f"  📉 dropped_traces:       {snapshot.dropped_traces}")
    print(f"  📉 dropped_metrics:      {snapshot.dropped_metrics}")
    print(f"  📤 export_failures_traces: {snapshot.export_failures_traces}")

    print("\n🏁 Done!")


def main() -> None:
    setup_telemetry()
    asyncio.run(_run())
    shutdown_telemetry()


if __name__ == "__main__":
    main()
