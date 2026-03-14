#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""⚡ Performance characteristics of the telemetry library.

Demonstrates:
- Import time of the full undef.telemetry package
- configure_logging() cost
- Hot-path instrument ops: counter.add(), gauge.set(), histogram.record()
- Sampling decision throughput via should_sample()
- Event name construction via event_name()
- Full setup_telemetry() / shutdown_telemetry() lifecycle cost
- Lazy-loading verification: processors.py has no direct slo dependency
"""

from __future__ import annotations

import ast
import time
from pathlib import Path


def _bench(fn: object, iterations: int = 10_000) -> float:
    """Run *fn* for *iterations* and return ns/op."""
    callable_fn = fn  # type: ignore[assignment]
    start = time.perf_counter_ns()
    for _ in range(iterations):
        callable_fn()
    elapsed_ns = time.perf_counter_ns() - start
    ns_per_op = elapsed_ns / iterations
    return ns_per_op


def _fmt(ns: float) -> str:
    if ns >= 1_000_000:
        return f"{ns / 1_000_000:>10.2f} ms"
    if ns >= 1_000:
        return f"{ns / 1_000:>10.2f} us"
    return f"{ns:>10.0f} ns"


def main() -> None:
    print("⚡ Performance Characteristics\n")

    rows: list[tuple[str, str]] = []

    # ── 📦 Full package import ───────────────────────────────────────
    print("📦 Full Package Import\n")
    t0 = time.perf_counter_ns()
    __import__("undef.telemetry")
    t1 = time.perf_counter_ns()
    rows.append(("import undef.telemetry", _fmt(t1 - t0)))

    # ── ⚙️  configure_logging ────────────────────────────────────────
    print("⚙️  Logging Configuration\n")
    from undef.telemetry.config import TelemetryConfig
    from undef.telemetry.logger.core import configure_logging

    cfg = TelemetryConfig()

    def do_configure() -> None:
        configure_logging(cfg)

    rows.append(("configure_logging()", _fmt(_bench(do_configure, iterations=100))))

    # ── 🔥 Hot-path ops ──────────────────────────────────────────────
    print("🔥 Hot-Path Instrument Operations\n")
    from undef.telemetry import counter, event_name, gauge, histogram
    from undef.telemetry.sampling import should_sample

    c = counter("perf.example.requests", "bench counter")
    g = gauge("perf.example.active", "bench gauge")
    h = histogram("perf.example.latency", "bench histogram", unit="ms")

    rows.append(("counter.add(1)", _fmt(_bench(lambda: c.add(1)))))
    rows.append(("gauge.set(42)", _fmt(_bench(lambda: g.set(42)))))
    rows.append(("histogram.record(3.14)", _fmt(_bench(lambda: h.record(3.14)))))
    rows.append(
        (
            'should_sample("logs", "x")',
            _fmt(_bench(lambda: should_sample("logs", "perf.test"))),
        )
    )
    rows.append(
        (
            'event_name("a","b","c")',
            _fmt(_bench(lambda: event_name("perf", "bench", "op"))),
        )
    )

    # ── 🔄 Full lifecycle ────────────────────────────────────────────
    print("🔄 Setup / Shutdown Lifecycle\n")
    from undef.telemetry import setup_telemetry, shutdown_telemetry

    shutdown_telemetry()

    def lifecycle() -> None:
        setup_telemetry()
        shutdown_telemetry()

    rows.append(("setup + shutdown cycle", _fmt(_bench(lifecycle, iterations=50))))

    # ── 📊 Results table ─────────────────────────────────────────────
    print("📊 Results\n")
    max_label = max(len(r[0]) for r in rows)
    for label, value in rows:
        print(f"    {label:<{max_label}}  {value}")

    # ── 🔌 Lazy-loading verification ─────────────────────────────────
    print("\n🔌 Lazy-Loading Verification\n")
    print("    processors.py uses a lazy import for classify_error (from slo.py)")
    print("    so it has no direct module-level dependency on the metrics subsystem.")
    print("    Verifying via AST analysis...\n")

    from undef.telemetry.logger import processors as proc_mod

    src = Path(str(proc_mod.__file__)).read_text()
    tree = ast.parse(src)
    slo_at_top = any(isinstance(stmt, ast.ImportFrom) and stmt.module and "slo" in stmt.module for stmt in tree.body)
    if slo_at_top:
        print("    ❌ slo is imported at module level (eager)")
    else:
        print("    ✅ No top-level slo import in processors.py (lazy, deferred to call time)")

    print("\n🏁 Done!")


if __name__ == "__main__":
    main()
