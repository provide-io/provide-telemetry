#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""🛡️ Error handling, graceful degradation, and diagnostic logging.

Demonstrates:
- TelemetryError hierarchy for structured exception handling
- ConfigurationError for invalid config (backwards-compatible with ValueError)
- EventSchemaError for invalid event names
- Catching all telemetry errors with a single except clause
- Graceful degradation when OTel is not installed
- Enabling DEBUG logging to diagnose silent OTel fallbacks
- Diagnostic warnings for sampling rate clamping and malformed headers
"""

from __future__ import annotations

import logging

from undef.telemetry import (
    ConfigurationError,
    EventSchemaError,
    TelemetryError,
    counter,
    event_name,
    get_health_snapshot,
    get_logger,
    reconfigure_telemetry,
    setup_telemetry,
    shutdown_telemetry,
    trace,
)
from undef.telemetry.config import SchemaConfig, TelemetryConfig, TracingConfig


def main() -> None:
    print("🛡️  Error Handling & Graceful Degradation Demo\n")

    # ── 🔍 Enable DEBUG to see OTel fallback diagnostics ─────
    print("🔍 Enabling DEBUG logging to expose OTel diagnostics...")
    logging.basicConfig(level=logging.DEBUG, format="  %(name)s: %(message)s", force=True)
    print("  (If OTel is not installed, you'll see debug messages about no-op fallbacks.)\n")

    # ── ⚙️  Normal setup — works with or without OTel ────────
    print("⚙️  Setting up telemetry (works with or without OTel)...")
    cfg = setup_telemetry()
    log = get_logger("examples.errors")
    print(f"  ✅ Setup complete: service={cfg.service_name}\n")

    # ── 🎯 Exception hierarchy ───────────────────────────────
    print("🎯 Exception Hierarchy Demo\n")

    # ConfigurationError — bad config values
    print("  1️⃣  ConfigurationError (invalid config):")
    try:
        TelemetryConfig(tracing=TracingConfig(sample_rate=2.0))
    except ConfigurationError as exc:
        print(f"     Caught ConfigurationError: {exc}")
        print(f"     Is TelemetryError? {isinstance(exc, TelemetryError)}")
        print(f"     Is ValueError?     {isinstance(exc, ValueError)}")

    # Enable strict event naming so malformed names raise EventSchemaError.
    reconfigure_telemetry(TelemetryConfig(event_schema=SchemaConfig(strict_event_name=True)))

    # EventSchemaError — bad event names (requires strict mode)
    print("\n  2️⃣  EventSchemaError (invalid event name):")
    try:
        event_name("only_one_segment")
    except EventSchemaError as exc:
        print(f"     Caught EventSchemaError: {exc}")
        print(f"     Is TelemetryError? {isinstance(exc, TelemetryError)}")

    try:
        event_name("BAD", "UPPER", "case")
    except EventSchemaError as exc:
        print(f"     Caught EventSchemaError: {exc}")

    # Catch-all with TelemetryError
    print("\n  3️⃣  Catch-all with TelemetryError:")
    errors_caught = 0
    for bad_input in [("x",), ("A", "B", "C"), ("a", "b", "c", "d", "e", "f")]:
        try:
            event_name(*bad_input)
        except TelemetryError:
            errors_caught += 1
    print(f"     Caught {errors_caught} errors with single 'except TelemetryError'")

    # Valid names still work
    print("\n  4️⃣  Valid event names:")
    name3 = event_name("auth", "login", "success")
    name4 = event_name("payment", "subscription", "renewal", "success")
    name5 = event_name("game", "match", "round", "score", "submitted")
    print(f"     3-seg: {name3}")
    print(f"     4-seg: {name4}")
    print(f"     5-seg: {name5}")

    # ── 🔇 Graceful degradation ─────────────────────────────
    print("\n🔇 Graceful Degradation Demo\n")

    # Metrics work even without OTel — they just track locally
    c = counter("example.errors.requests", "Demo counter")
    c.add(5, {"route": "/api/test"})
    print(f"  ✅ Counter works without OTel: value={c.value}")

    # Tracing works — uses NoopSpan when OTel isn't configured
    @trace("example.errors.traced_work")
    def do_traced_work() -> str:
        return "completed"

    result = do_traced_work()
    print(f"  ✅ @trace works without OTel: result={result!r}")

    # Logging always works
    log.info("example.errors.degradation_test", status="ok")
    print("  ✅ Structured logging always works")

    # Health snapshot shows the state
    health = get_health_snapshot()
    print(f"  📊 Health: queue_depth_logs={health.queue_depth_logs}, dropped_logs={health.dropped_logs}")

    # ── ⚠️  Diagnostic warnings ──────────────────────────────
    print("\n⚠️  Diagnostic Warning Examples\n")

    # Sampling rate clamping
    print("  1️⃣  Sampling rate clamping (check WARNING logs above):")
    from undef.telemetry.sampling import SamplingPolicy, set_sampling_policy

    set_sampling_policy("logs", SamplingPolicy(default_rate=1.5))
    print("     Set rate=1.5 → clamped to 1.0 with WARNING")

    set_sampling_policy("logs", SamplingPolicy(default_rate=-0.5))
    print("     Set rate=-0.5 → clamped to 0.0 with WARNING")

    # Malformed OTLP headers
    print("\n  2️⃣  Malformed OTLP headers (check WARNING logs above):")
    from undef.telemetry.config import _parse_otlp_headers

    headers = _parse_otlp_headers("good=value,bad-no-equals,another=ok")
    print(f"     Parsed: {headers}")
    print("     'bad-no-equals' logged as WARNING and skipped")

    # ── 🏁 Cleanup ──────────────────────────────────────────
    print("\n🏁 Done!")
    shutdown_telemetry()


if __name__ == "__main__":
    main()
