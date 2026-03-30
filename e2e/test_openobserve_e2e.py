# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

from __future__ import annotations

import base64
import json
import os
import time
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

import pytest

from undef.telemetry import counter, get_logger, setup_telemetry, shutdown_telemetry, trace
from undef.telemetry.config import TelemetryConfig
from undef.telemetry.setup import _reset_all_for_tests

pytestmark = pytest.mark.e2e


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        pytest.skip(f"{name} is not set")
    return value


def _auth_header(user: str, password: str) -> str:
    token = base64.b64encode(f"{user}:{password}".encode()).decode("ascii")
    return f"Basic {token}"


def _get_stream_doc_total(base_url: str, stream_type: str, auth: str) -> int:
    streams = _get_streams(base_url, stream_type, auth)
    return int(sum(int(item.get("stats", {}).get("doc_num", 0)) for item in streams))


def _get_streams(base_url: str, stream_type: str, auth: str) -> list[dict[str, Any]]:
    req = Request(
        url=f"{base_url}/streams?type={stream_type}",
        headers={"Authorization": auth},
        method="GET",
    )
    with urlopen(req, timeout=10) as response:
        payload: dict[str, Any] = json.loads(response.read().decode("utf-8"))
    return list(payload.get("list", []))


def _search_total(base_url: str, stream_type: str, auth: str, sql: str, start_time: int, end_time: int) -> int:
    req = Request(
        url=f"{base_url}/_search?type={stream_type}",
        headers={"Authorization": auth, "Content-Type": "application/json"},
        data=json.dumps(
            {
                "query": {
                    "sql": sql,
                    "start_time": start_time,
                    "end_time": end_time,
                }
            }
        ).encode("utf-8"),
        method="POST",
    )
    try:
        with urlopen(req, timeout=10) as response:
            payload: dict[str, Any] = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8")
        if "Search stream not found" in detail:
            return 0
        raise
    return int(payload.get("total", 0))


def test_openobserve_trace_and_metric_ingestion_e2e(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("opentelemetry")
    user = _require_env("OPENOBSERVE_USER")
    password = _require_env("OPENOBSERVE_PASSWORD")
    base_url = _require_env("OPENOBSERVE_URL").rstrip("/")
    auth = _auth_header(user, password)

    now_us = int(time.time() * 1_000_000)
    start_us = now_us - (2 * 60 * 60 * 1_000_000)
    before_traces = _search_total(
        base_url,
        "traces",
        auth,
        "select * from \"default\" where operation_name = 'e2e.openobserve.span'",
        start_us,
        now_us,
    )

    _reset_all_for_tests()

    # Keep E2E feedback tight by reducing exporter flush intervals.
    monkeypatch.setenv("OTEL_BSP_SCHEDULE_DELAY", "200")
    monkeypatch.setenv("OTEL_METRIC_EXPORT_INTERVAL", "1000")

    cfg = TelemetryConfig.from_env(
        {
            "UNDEF_TELEMETRY_SERVICE_NAME": "undef-telemetry-e2e",
            "UNDEF_TELEMETRY_VERSION": "e2e",
            "UNDEF_TRACE_ENABLED": "true",
            "UNDEF_METRICS_ENABLED": "true",
            "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": f"{base_url}/v1/traces",
            "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT": f"{base_url}/v1/metrics",
            "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": f"{base_url}/v1/logs",
            "OTEL_EXPORTER_OTLP_HEADERS": f"Authorization={quote(auth, safe='')}",
        }
    )

    setup_telemetry(cfg)

    metric_suffix = str(int(time.time()))
    metric_name = f"e2e.requests.{metric_suffix}"
    metric_stream_name = metric_name.replace(".", "_")
    before_metrics = _search_total(
        base_url,
        "metrics",
        auth,
        f'select * from "{metric_stream_name}"',
        start_us,
        now_us,
    )

    @trace("e2e.openobserve.span")
    def _work(iteration: int) -> None:
        get_logger("e2e").info("e2e.openobserve.log", iteration=str(iteration))
        counter(metric_name).add(1, {"iteration": str(iteration)})

    for i in range(3):
        _work(i)

    shutdown_telemetry()

    deadline = time.time() + 30
    traces_ok = False
    metrics_ok = False

    while time.time() < deadline:
        end_us = int(time.time() * 1_000_000)
        after_traces = _search_total(
            base_url,
            "traces",
            auth,
            "select * from \"default\" where operation_name = 'e2e.openobserve.span'",
            start_us,
            end_us,
        )
        after_metrics = _search_total(
            base_url,
            "metrics",
            auth,
            f'select * from "{metric_stream_name}"',
            start_us,
            end_us,
        )
        traces_ok = after_traces > before_traces
        metrics_ok = after_metrics > before_metrics
        if traces_ok and metrics_ok:
            break
        time.sleep(1)

    assert traces_ok, "trace docs were not ingested by OpenObserve"
    assert metrics_ok, "metric docs were not ingested by OpenObserve"
