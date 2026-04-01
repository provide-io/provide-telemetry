#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

from __future__ import annotations

import base64
import json
import os
import time
from collections.abc import Callable
from http.client import HTTPConnection, HTTPSConnection
from urllib.parse import quote, urlparse

from provide.telemetry import counter, get_logger, setup_telemetry, shutdown_telemetry, trace
from provide.telemetry.config import TelemetryConfig


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        msg = f"missing required env var: {name}"
        raise RuntimeError(msg)
    return value


def _auth_header(user: str, password: str) -> str:
    token = base64.b64encode(f"{user}:{password}".encode()).decode("ascii")
    return f"Basic {token}"


def _send_openobserve_json_log(base_url: str, auth: str, run_id: str) -> None:
    payload = [
        {
            "_timestamp": int(time.time() * 1_000_000),
            "event": "example.openobserve.jsonlog",
            "run_id": run_id,
            "message": "openobserve json log ingestion",
        }
    ]
    parsed = urlparse(f"{base_url}/default/_json")
    if parsed.scheme not in {"http", "https"}:
        msg = f"unsupported URL scheme: {parsed.scheme}"
        raise RuntimeError(msg)
    if not parsed.hostname:
        msg = "missing hostname in OPENOBSERVE_URL"
        raise RuntimeError(msg)
    conn_cls = HTTPSConnection if parsed.scheme == "https" else HTTPConnection
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    conn = conn_cls(parsed.hostname, port=port, timeout=10)
    conn.request(
        "POST",
        path,
        body=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": auth, "Content-Type": "application/json"},
    )
    response = conn.getresponse()
    _ = response.read()
    conn.close()
    if response.status >= 400:
        msg = f"OpenObserve API returned status {response.status}"
        raise RuntimeError(msg)


def _make_work(trace_name: str, metric_name: str) -> Callable[[int], None]:
    @trace(trace_name)
    def _work(iteration: int) -> None:
        get_logger("examples.openobserve").info("example.openobserve.log", iteration=str(iteration))
        counter(metric_name).add(1, {"iteration": str(iteration)})

    return _work


def main() -> None:
    base_url = _require_env("OPENOBSERVE_URL").rstrip("/")
    user = _require_env("OPENOBSERVE_USER")
    password = _require_env("OPENOBSERVE_PASSWORD")
    auth = _auth_header(user, password)
    run_id = os.getenv("PROVIDE_EXAMPLE_RUN_ID", str(int(time.time())))
    trace_name = f"example.openobserve.work.{run_id}"
    metric_name = f"example.openobserve.requests.{run_id}"

    os.environ["OTEL_BSP_SCHEDULE_DELAY"] = "200"
    os.environ["OTEL_METRIC_EXPORT_INTERVAL"] = "1000"

    cfg = TelemetryConfig.from_env(
        {
            "PROVIDE_TELEMETRY_SERVICE_NAME": "provide-telemetry-examples",
            "PROVIDE_TELEMETRY_VERSION": "examples",
            "PROVIDE_TRACE_ENABLED": "true",
            "PROVIDE_METRICS_ENABLED": "true",
            "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": f"{base_url}/v1/traces",
            "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT": f"{base_url}/v1/metrics",
            "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": f"{base_url}/v1/logs",
            "OTEL_EXPORTER_OTLP_HEADERS": f"Authorization={quote(auth, safe='')}",
        }
    )
    setup_telemetry(cfg)

    work = _make_work(trace_name, metric_name)
    for i in range(5):
        work(i)
        time.sleep(0.05)

    shutdown_telemetry()
    _send_openobserve_json_log(base_url, auth, run_id)
    print(f"signals emitted run_id={run_id}")


if __name__ == "__main__":
    main()
