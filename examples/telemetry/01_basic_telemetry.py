#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

from __future__ import annotations

import time

from provide.telemetry import (
    bind_context,
    clear_context,
    counter,
    gauge,
    get_logger,
    histogram,
    setup_telemetry,
    shutdown_telemetry,
    trace,
    unbind_context,
)


@trace("example.basic.work")
def do_work(iteration: int) -> None:
    log = get_logger("examples.basic")
    log.info("example.basic.iteration", iteration=str(iteration))
    counter("example.basic.requests", "Total request count").add(1, {"iteration": str(iteration)})
    histogram("example.basic.latency_ms", "Simulated latency", "ms").record(
        iteration * 12.5, {"iteration": str(iteration)}
    )
    gauge("example.basic.active_tasks", "Active task gauge", "1").set(1)


def main() -> None:
    cfg = setup_telemetry()
    log = get_logger("examples.basic")
    log.info(
        "example.basic.start",
        service=cfg.service_name,
        env=cfg.environment,
        version=cfg.version,
    )
    for i in range(3):
        do_work(i)
        time.sleep(0.05)
    log.info("example.basic.complete")
    shutdown_telemetry()


if __name__ == "__main__":
    main()
