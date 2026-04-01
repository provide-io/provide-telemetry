#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

from __future__ import annotations

import asyncio

from undef.telemetry import (
    QueuePolicy,
    SamplingPolicy,
    counter,
    get_health_snapshot,
    get_logger,
    set_queue_policy,
    set_sampling_policy,
    setup_telemetry,
    shutdown_telemetry,
    trace,
)


@trace("example.sampling.concurrent")
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

    # This event itself is sampled out from the logger pipeline.
    log.info("example.sampling.done")

    snapshot = get_health_snapshot()
    print(
        {
            "dropped_logs": snapshot.dropped_logs,
            "dropped_traces": snapshot.dropped_traces,
            "dropped_metrics": snapshot.dropped_metrics,
            "queue_depth_traces": snapshot.queue_depth_traces,
        }
    )


def main() -> None:
    setup_telemetry()
    asyncio.run(_run())
    shutdown_telemetry()


if __name__ == "__main__":
    main()
