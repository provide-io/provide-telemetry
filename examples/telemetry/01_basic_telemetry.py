#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 MindTenet LLC
# This file is part of Undef Telemetry.
from __future__ import annotations

import time

from undef.telemetry import counter, get_logger, setup_telemetry, shutdown_telemetry, trace


@trace("example.basic.work")
def do_work(iteration: int) -> None:
    get_logger("examples.basic").info("example.basic.iteration", iteration=str(iteration))
    counter("example.basic.requests").add(1, {"iteration": str(iteration)})


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
