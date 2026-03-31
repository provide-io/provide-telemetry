#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""📊 SLO metrics pack and full health snapshot inspection.

Demonstrates:
- record_red_metrics for HTTP request/error/duration (RED)
- record_use_metrics for resource utilization (USE)
- classify_error for error taxonomy
- HealthSnapshot with all 24 fields
- SLO config via TelemetryConfig environment overrides
"""

from __future__ import annotations

from undef.telemetry import (
    classify_error,
    get_health_snapshot,
    get_logger,
    record_red_metrics,
    record_use_metrics,
    setup_telemetry,
    shutdown_telemetry,
)
from undef.telemetry.config import TelemetryConfig


def main() -> None:
    print("📊 SLO Metrics & Health Snapshot Demo\n")

    cfg = TelemetryConfig.from_env(
        {
            "UNDEF_SLO_ENABLE_RED_METRICS": "true",
            "UNDEF_SLO_ENABLE_USE_METRICS": "true",
            "UNDEF_SLO_INCLUDE_ERROR_TAXONOMY": "true",
        }
    )
    setup_telemetry(cfg)
    log = get_logger("examples.slo")

    # ── 🟢 Successful requests ──────────────────────────────
    print("🟢 Recording successful HTTP requests...")
    record_red_metrics(route="/matchmaking", method="POST", status_code=200, duration_ms=18.2)
    record_red_metrics(route="/matchmaking", method="GET", status_code=200, duration_ms=5.1)
    record_red_metrics(route="/leaderboard", method="GET", status_code=200, duration_ms=12.7)
    print("  ✅ 3 requests recorded (POST + 2x GET)")

    # ── 🔴 Server errors ────────────────────────────────────
    print("\n🔴 Recording server errors...")
    record_red_metrics(route="/matchmaking", method="POST", status_code=503, duration_ms=210.5)
    record_red_metrics(route="/inventory", method="PUT", status_code=500, duration_ms=45.0)
    print("  💥 2 errors recorded (503 + 500)")

    # ── 📈 Resource utilization (USE) ────────────────────────
    print("\n📈 Recording resource utilization...")
    record_use_metrics(resource="cpu", utilization_percent=61)
    record_use_metrics(resource="memory", utilization_percent=78)
    record_use_metrics(resource="disk_io", utilization_percent=23)
    print("  🖥️  cpu=61%  |  🧠 memory=78%  |  💾 disk_io=23%")

    # ── 🏷️ Error taxonomy ────────────────────────────────────
    print("\n🏷️  Error taxonomy classification:")
    cases = [
        ("UpstreamTimeout", 503),
        ("InvalidPayload", 400),
        ("NullPointerError", None),
    ]
    for exc_name, code in cases:
        taxonomy = classify_error(exc_name, code)
        icon = {"server": "🔴", "client": "🟡", "internal": "⚫"}.get(taxonomy["error_type"], "❓")
        print(f"  {icon} {exc_name}(status={code}) → type={taxonomy['error_type']}, code={taxonomy['error_code']}")
        if code == 503:
            log.error("example.slo.error", exc_name=exc_name, status_code=code, **taxonomy)

    # ── 🩺 Full health snapshot ──────────────────────────────
    print("\n🩺 Full HealthSnapshot (all 25 fields):")
    s = get_health_snapshot()
    print(
        f"  📦 Queue depths:       logs={s.queue_depth_logs}  traces={s.queue_depth_traces}  metrics={s.queue_depth_metrics}"
    )
    print(f"  📉 Dropped:            logs={s.dropped_logs}  traces={s.dropped_traces}  metrics={s.dropped_metrics}")
    print(f"  🔄 Retries:            logs={s.retries_logs}  traces={s.retries_traces}  metrics={s.retries_metrics}")
    print(
        f"  ⚠️  Async block risk:  logs={s.async_blocking_risk_logs}  traces={s.async_blocking_risk_traces}  metrics={s.async_blocking_risk_metrics}"
    )
    print(
        f"  ❌ Export failures:    logs={s.export_failures_logs}  traces={s.export_failures_traces}  metrics={s.export_failures_metrics}"
    )
    print(f"  🔬 Exemplar unsupported: {s.exemplar_unsupported_total}")
    print(
        f"  💬 Last errors:        logs={s.last_error_logs}  traces={s.last_error_traces}  metrics={s.last_error_metrics}"
    )
    print(
        f"  ✅ Last success:       logs={s.last_successful_export_logs}  traces={s.last_successful_export_traces}  metrics={s.last_successful_export_metrics}"
    )
    print(
        f"  ⏱️  Export latency(ms): logs={s.export_latency_ms_logs}  traces={s.export_latency_ms_traces}  metrics={s.export_latency_ms_metrics}"
    )

    print("\n🏁 Done!")
    shutdown_telemetry()


if __name__ == "__main__":
    main()
