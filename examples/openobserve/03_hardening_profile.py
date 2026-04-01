#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

from __future__ import annotations

import os
import time
from base64 import b64encode
from urllib.parse import quote

from provide.telemetry import (
    PIIRule,
    event_name,
    get_health_snapshot,
    get_logger,
    register_cardinality_limit,
    register_pii_rule,
    setup_telemetry,
    shutdown_telemetry,
    trace,
)
from provide.telemetry.config import TelemetryConfig


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        msg = f"missing required env var: {name}"
        raise RuntimeError(msg)
    return value


@trace(event_name("example", "openobserve", "work"))
def _emit(iteration: int) -> None:
    token_value = os.getenv("PROVIDE_EXAMPLE_TOKEN", "example-token-from-env")
    get_logger("examples.openobserve.hardening").info(
        event_name("example", "openobserve", "log"),
        iteration=iteration,
        user={"email": "ops@example.com", "full_name": "Operator Example"},
        token=token_value,
    )


def main() -> None:
    base_url = _require_env("OPENOBSERVE_URL").rstrip("/")
    user = _require_env("OPENOBSERVE_USER")
    password = _require_env("OPENOBSERVE_PASSWORD")

    auth = f"Basic {b64encode(f'{user}:{password}'.encode()).decode('ascii')}"
    cfg = TelemetryConfig.from_env(
        {
            "PROVIDE_TELEMETRY_SERVICE_NAME": "provide-telemetry-hardening-example",
            "PROVIDE_TELEMETRY_VERSION": "hardening",
            "PROVIDE_SAMPLING_LOGS_RATE": "1.0",
            "PROVIDE_SAMPLING_TRACES_RATE": "1.0",
            "PROVIDE_SAMPLING_METRICS_RATE": "1.0",
            "PROVIDE_BACKPRESSURE_TRACES_MAXSIZE": "64",
            "PROVIDE_EXPORTER_LOGS_RETRIES": "1",
            "PROVIDE_EXPORTER_TRACES_RETRIES": "1",
            "PROVIDE_EXPORTER_METRICS_RETRIES": "1",
            "OTEL_EXPORTER_OTLP_HEADERS": f"Authorization={quote(auth, safe='')}",
            "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": f"{base_url}/v1/traces",
            "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT": f"{base_url}/v1/metrics",
            "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": f"{base_url}/v1/logs",
            "PROVIDE_SLO_ENABLE_RED_METRICS": "true",
            "PROVIDE_SLO_ENABLE_USE_METRICS": "true",
        }
    )

    register_pii_rule(PIIRule(path=("user", "email"), mode="hash"))
    register_pii_rule(PIIRule(path=("user", "full_name"), mode="truncate", truncate_to=4))
    register_cardinality_limit("player_id", max_values=50, ttl_seconds=300)

    setup_telemetry(cfg)

    for i in range(5):
        _emit(i)
        time.sleep(0.05)

    shutdown_telemetry()
    print({"health": get_health_snapshot()})


if __name__ == "__main__":
    main()
