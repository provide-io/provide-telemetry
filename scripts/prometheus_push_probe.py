#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Record the push_ingestion instruments and push them to Prometheus over OTLP.

Tier 1 of the Prometheus contract: no Prometheus-specific code, only the
ordinary OTLP metrics exporter pointed at a Prometheus 3 OTLP receiver. The
instruments are listed in spec/prometheus_fixtures.yaml (push_ingestion); the
E2E test in e2e/test_prometheus_push_e2e.py queries them back.

Inputs (environment):
    OTEL_EXPORTER_OTLP_METRICS_ENDPOINT   e.g. http://127.0.0.1:9090/api/v1/otlp/v1/metrics
    PROVIDE_TELEMETRY_SERVICE_NAME        becomes the Prometheus job label
    PROVIDE_PROM_PROBE_PREFIX             dotted metric-name prefix for this run
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from provide.telemetry import counter, gauge, histogram, setup_telemetry, shutdown_telemetry
from provide.telemetry.config import TelemetryConfig


def main() -> int:
    prefix = os.environ.get("PROVIDE_PROM_PROBE_PREFIX")
    if not prefix or not os.environ.get("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT"):
        print("prometheus-push-probe: endpoint or prefix unset", file=sys.stderr)
        return 2
    os.environ.setdefault("PROVIDE_TRACE_ENABLED", "false")
    setup_telemetry(TelemetryConfig.from_env())
    counter(f"{prefix}.requests").add(3, {"route": "/a"})
    histogram(f"{prefix}.request.duration", unit="ms").record(12.0, {"route": "/a"})
    gauge(f"{prefix}.cpu.utilization", unit="1").set(1, {"core": "0"})
    # Shutdown drains the periodic reader, which is what puts the data on the wire.
    shutdown_telemetry()
    print("prometheus-push-probe: OK", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
