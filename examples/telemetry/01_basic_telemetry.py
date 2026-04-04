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
    event,
    gauge,
    get_logger,
    histogram,
    setup_telemetry,
    shutdown_telemetry,
    trace,
    unbind_context,
)


@trace(event("example", "basic", "work"))
def do_work(iteration: int) -> None:
    log = get_logger("examples.basic")
    log.info(event("example", "basic", "iteration"), iteration=str(iteration))
    counter("example.basic.requests", "Total request count").add(1, {"iteration": str(iteration)})
    histogram("example.basic.latency_ms", "Simulated latency", "ms").record(
        iteration * 12.5, {"iteration": str(iteration)}
    )
    gauge("example.basic.active_tasks", "Active task gauge", "1").set(1)


def main() -> None:
    cfg = setup_telemetry()
    log = get_logger("examples.basic")

    print(f"⚙️  Service: {cfg.service_name}  |  Env: {cfg.environment}  |  Version: {cfg.version}")

    # ── 📋 Structured context binding ───────────────────────
    print("\n📋 Binding structured context fields...")
    bind_context(region="us-east-1", tier="premium")
    log.info(event("example", "basic", "start"), msg="context is bound")
    print("  ✅ Bound: region=us-east-1, tier=premium")

    # ── 🔄 Traced work loop with all metric types ──────────
    print("\n🔄 Running traced iterations with counter + histogram + gauge:")
    for i in range(3):
        do_work(i)
        time.sleep(0.05)
        print(f"  🔹 Iteration {i}: counter +1, histogram {i * 12.5}ms, gauge +1")

    # ── 🧹 Context cleanup ─────────────────────────────────
    print("\n🧹 Unbinding 'region', then clearing all context...")
    unbind_context("region")
    log.info(event("example", "basic", "after_unbind"), msg="region removed")
    print("  🔸 Unbound: region")

    clear_context()
    log.info(event("example", "basic", "after_clear"), msg="all context cleared")
    print("  🔸 Cleared: all context fields")

    print("\n🏁 Done!")
    shutdown_telemetry()


if __name__ == "__main__":
    main()
