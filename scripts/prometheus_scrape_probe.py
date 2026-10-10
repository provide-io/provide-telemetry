#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Serve a counter and an observable gauge on the standalone listener until stdin closes.

Tier 3 of the Prometheus contract: e2e/test_prometheus_scrape_e2e.py starts
this with OTEL_METRICS_EXPORTER=prometheus and PROVIDE_METRICS_PROMETHEUS_LISTEN=true
(plus a web config for the secured run), waits for "ready" on stdout, and
checks what a real Prometheus scraped.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from provide.telemetry import (
    Observation,
    counter,
    get_health_snapshot,
    observable_gauge,
    setup_telemetry,
    shutdown_telemetry,
)
from provide.telemetry.config import TelemetryConfig


def main() -> int:
    os.environ.setdefault("PROVIDE_TRACE_ENABLED", "false")
    setup_telemetry(TelemetryConfig.from_env())
    error = get_health_snapshot().setup_error
    if error:
        print(f"prometheus-scrape-probe: FAIL — {error}", file=sys.stderr)
        return 1
    counter("e2e.scrape.requests").add(3)
    observable_gauge("e2e.scrape.temperature", lambda: [Observation(41.5)], unit="Cel")
    print("ready", flush=True)
    sys.stdin.read()
    shutdown_telemetry()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
