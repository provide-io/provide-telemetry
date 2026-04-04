#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

from __future__ import annotations

from provide.telemetry import (
    classify_error,
    event,
    get_health_snapshot,
    get_logger,
    record_red_metrics,
    record_use_metrics,
    setup_telemetry,
    shutdown_telemetry,
)
from provide.telemetry.config import TelemetryConfig


def main() -> None:
    cfg = TelemetryConfig.from_env(
        {
            "PROVIDE_SLO_ENABLE_RED_METRICS": "true",
            "PROVIDE_SLO_ENABLE_USE_METRICS": "true",
            "PROVIDE_SLO_INCLUDE_ERROR_TAXONOMY": "true",
        }
    )
    setup_telemetry(cfg)

    log = get_logger("examples.slo")
    record_red_metrics(route="/matchmaking", method="POST", status_code=200, duration_ms=18.2)
    record_red_metrics(route="/matchmaking", method="POST", status_code=503, duration_ms=210.5)
    record_use_metrics(resource="cpu", utilization_percent=61)

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
            log.error(event("example", "slo", "error"), exc_name=exc_name, status_code=code, **taxonomy)

    # ── 🩺 Full health snapshot ──────────────────────────────
    print("\n🩺 Full HealthSnapshot (all 25 fields):")
    s = get_health_snapshot()
    print(
        {
            "taxonomy": taxonomy,
            "last_successful_export_metrics": snapshot.last_successful_export_metrics,
            "export_failures_metrics": snapshot.export_failures_metrics,
        }
    )

    shutdown_telemetry()


if __name__ == "__main__":
    main()
