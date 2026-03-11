#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

from __future__ import annotations

from undef.telemetry import (
    get_health_snapshot,
    get_logger,
    get_runtime_config,
    setup_telemetry,
    shutdown_telemetry,
    update_runtime_config,
)
from undef.telemetry.config import TelemetryConfig


def main() -> None:
    setup_telemetry()
    log = get_logger("examples.runtime")

    cfg_before = get_runtime_config()
    print({"before_logs_rate": cfg_before.sampling.logs_rate})

    log.info("example.runtime.before")

    cfg_after = TelemetryConfig.from_env({"UNDEF_SAMPLING_LOGS_RATE": "0.0"})
    update_runtime_config(cfg_after)
    log.info("example.runtime.after")

    snapshot = get_health_snapshot()
    print(
        {
            "after_logs_rate": get_runtime_config().sampling.logs_rate,
            "dropped_logs": snapshot.dropped_logs,
        }
    )

    shutdown_telemetry()


if __name__ == "__main__":
    main()
