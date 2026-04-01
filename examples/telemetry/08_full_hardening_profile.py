#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""🏰 Full production hardening profile — all guardrails active.

Demonstrates a complete hardening setup combining:
- PII masking on sensitive fields
- Cardinality limits to prevent metric explosion
- Sampling policies with per-key overrides
- Backpressure queue limits
- Exporter resilience with fail-open policy
- SLO RED/USE metrics recording
- Runtime reconfiguration mid-flight
- Full HealthSnapshot inspection
"""

from __future__ import annotations

from provide.telemetry import (
    ExporterPolicy,
    PIIRule,
    QueuePolicy,
    SamplingPolicy,
    counter,
    get_health_snapshot,
    get_logger,
    get_runtime_config,
    histogram,
    record_red_metrics,
    record_use_metrics,
    register_cardinality_limit,
    register_pii_rule,
    set_exporter_policy,
    set_queue_policy,
    set_sampling_policy,
    setup_telemetry,
    shutdown_telemetry,
    update_runtime_config,
)
from provide.telemetry.cardinality import guard_attributes
from provide.telemetry.config import TelemetryConfig


def main() -> None:
    print("🏰 Full Production Hardening Profile\n")

    cfg = TelemetryConfig.from_env(
        {
            "PROVIDE_SLO_ENABLE_RED_METRICS": "true",
            "PROVIDE_SLO_ENABLE_USE_METRICS": "true",
            "PROVIDE_SLO_INCLUDE_ERROR_TAXONOMY": "true",
        }
    )
    setup_telemetry(cfg)
    log = get_logger("examples.hardening")

    # ── 🔒 PII masking ─────────────────────────────────────
    print("🔒 PII masking: hash emails, drop credit cards")
    register_pii_rule(PIIRule(path=("user", "email"), mode="hash"))
    register_pii_rule(PIIRule(path=("credit_card",), mode="drop"))
    log.info(
        "example.hardening.user_event",
        user={"email": "player@game.io", "name": "Hero"},
        credit_card="4111111111111111",
    )
    print("  ✅ PII rules active")

    # ── 🚧 Cardinality limits ──────────────────────────────
    print("\n🚧 Cardinality limit: max 3 unique player_ids")
    register_cardinality_limit("player_id", max_values=3, ttl_seconds=300)
    metric = counter("example.hardening.actions", "Player actions")
    for pid in ("p1", "p2", "p3", "p4", "p5"):
        attrs = guard_attributes({"player_id": pid})
        metric.add(1, attrs)
        icon = "⚠️" if attrs["player_id"] != pid else "✅"
        print(f"  {icon} player_id={pid} → guarded={attrs['player_id']}")

    # ── 🎲 Sampling policies ───────────────────────────────
    print("\n🎲 Sampling: logs=50%, traces=100%, critical overrides=100%")
    set_sampling_policy(
        "logs",
        SamplingPolicy(default_rate=0.5, overrides={"example.critical": 1.0}),
    )
    set_sampling_policy("traces", SamplingPolicy(default_rate=1.0))

    # ── 🚧 Backpressure ────────────────────────────────────
    print("\n🚧 Backpressure: traces queue max=2")
    set_queue_policy(QueuePolicy(logs_maxsize=0, metrics_maxsize=0, traces_maxsize=2))

    # ── 🛡️ Exporter resilience ─────────────────────────────
    print("\n🛡️  Exporter resilience: fail-open with 2 retries")
    set_exporter_policy(
        "logs",
        ExporterPolicy(retries=2, backoff_seconds=0.01, fail_open=True, timeout_seconds=1.0),
    )

    # ── 📊 SLO RED/USE metrics ─────────────────────────────
    print("\n📊 Recording SLO metrics...")
    record_red_metrics(route="/game/start", method="POST", status_code=200, duration_ms=22.0)
    record_red_metrics(route="/game/start", method="POST", status_code=500, duration_ms=150.0)
    record_use_metrics(resource="cpu", utilization_percent=55)
    histogram("example.hardening.latency", "Request latency", "ms").record(22.0)
    print("  ✅ RED: 2 requests (1 success, 1 error)")
    print("  ✅ USE: cpu=55%")

    # ── 🔧 Runtime reconfiguration ─────────────────────────
    print("\n🔧 Hot-swapping log sampling to 100%...")
    current = get_runtime_config()
    print(f"  📋 Before: logs_rate={current.sampling.logs_rate}")
    new_cfg = TelemetryConfig.from_env({"PROVIDE_SAMPLING_LOGS_RATE": "1.0"})
    updated = update_runtime_config(new_cfg)
    print(f"  ✅ After:  logs_rate={updated.sampling.logs_rate}")

    # ── 🩺 Health snapshot ──────────────────────────────────
    print("\n🩺 Health snapshot summary:")
    s = get_health_snapshot()
    print(f"  📉 Dropped:         logs={s.dropped_logs}  traces={s.dropped_traces}  metrics={s.dropped_metrics}")
    print(f"  🔄 Retries:         logs={s.retries_logs}  traces={s.retries_traces}")
    print(f"  ❌ Export failures: logs={s.export_failures_logs}  traces={s.export_failures_traces}")
    print(f"  ⚠️  Async risks:    logs={s.async_blocking_risk_logs}  traces={s.async_blocking_risk_traces}")
    print(f"  💬 Last errors:     logs={s.last_error_logs}  traces={s.last_error_traces}")

    print("\n🏁 All guardrails active — production-ready!")
    shutdown_telemetry()


if __name__ == "__main__":
    main()
