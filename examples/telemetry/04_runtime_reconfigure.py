#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

from __future__ import annotations

from provide.telemetry import (
    get_health_snapshot,
    get_logger,
    get_runtime_config,
    setup_telemetry,
    shutdown_telemetry,
    update_runtime_config,
)
from provide.telemetry.config import TelemetryConfig


def main() -> None:
    setup_telemetry()
    log = get_logger("examples.runtime")

    cfg_before = get_runtime_config()
    print({"before_logs_rate": cfg_before.sampling.logs_rate})

    log.info("example.runtime.before")

    # ── 🔧 Hot-swap sampling rate to 0% ──────────────────
    print("\n🔧 Hot-swapping sampling rate to 0%...")
    cfg_after = TelemetryConfig.from_env({"PROVIDE_SAMPLING_LOGS_RATE": "0.0"})
    updated = update_runtime_config(cfg_after)
    print(f"  ✅ After update: logs_rate={updated.sampling.logs_rate}")

    log.info("example.runtime.dropped")

    snapshot = get_health_snapshot()
    print(
        {
            "after_logs_rate": get_runtime_config().sampling.logs_rate,
            "dropped_logs": snapshot.dropped_logs,
        }
    )

    # ── ♻️ Full provider restart via reconfigure ─────────
    print("\n♻️  reconfigure_telemetry() — full shutdown+setup cycle...")
    cfg_restarted = reconfigure_telemetry(TelemetryConfig.from_env({"PROVIDE_SAMPLING_LOGS_RATE": "1.0"}))
    print(f"  ✅ Restarted: logs_rate={cfg_restarted.sampling.logs_rate}")

    log.info("example.runtime.restarted")

    # ── 🌍 Reload from environment ───────────────────────
    print("\n🌍 reload_runtime_from_env() — re-reads os.environ...")
    reloaded = reload_runtime_from_env()
    print(f"  ✅ Reloaded: logs_rate={reloaded.sampling.logs_rate}")

    print("\n🏁 Done!")
    shutdown_telemetry()


if __name__ == "__main__":
    main()
