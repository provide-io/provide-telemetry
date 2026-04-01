#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

from __future__ import annotations

import base64
import json
import os
import runpy
import time
from http.client import HTTPConnection, HTTPSConnection
from typing import cast
from urllib.parse import urlparse


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        msg = f"missing required env var: {name}"
        raise RuntimeError(msg)
    return value


def _auth_header(user: str, password: str) -> str:
    token = base64.b64encode(f"{user}:{password}".encode()).decode("ascii")
    return f"Basic {token}"


def _request_json(url: str, auth: str, method: str = "GET", body: dict[str, object] | None = None) -> dict[str, object]:
    parsed = urlparse(url)
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

    payload = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Authorization": auth}
    if payload is not None:
        headers["Content-Type"] = "application/json"

    conn = conn_cls(parsed.hostname, port=port, timeout=10)
    conn.request(method, path, body=payload, headers=headers)
    response = conn.getresponse()
    raw = response.read()
    conn.close()
    if response.status >= 400:
        msg = f"OpenObserve API returned status {response.status}: {raw.decode('utf-8', errors='replace')}"
        raise RuntimeError(msg)
    return cast(dict[str, object], json.loads(raw.decode("utf-8")))


def _search_total(base_url: str, stream_type: str, auth: str, sql: str, start_us: int, end_us: int) -> int:
    try:
        response = _request_json(
            f"{base_url}/_search?type={stream_type}",
            auth,
            method="POST",
            body={
                "query": {
                    "sql": sql,
                    "start_time": start_us,
                    "end_time": end_us,
                }
            },
        )
    except RuntimeError as exc:
        if "Search stream not found" in str(exc):
            return 0
        raise
    total = response.get("total", 0)
    if isinstance(total, int):
        return total
    if isinstance(total, str):
        return int(total)
    return 0


def _search_hits(base_url: str, stream_type: str, auth: str, start_us: int, end_us: int) -> list[dict[str, object]]:
    sql = 'select * from "default" order by _timestamp desc limit 500'
    response = _request_json(
        f"{base_url}/_search?type={stream_type}",
        auth,
        method="POST",
        body={
            "query": {
                "sql": sql,
                "start_time": start_us,
                "end_time": end_us,
            }
        },
    )
    raw_hits = response.get("hits", [])
    if isinstance(raw_hits, list):
        return [cast(dict[str, object], hit) for hit in raw_hits if isinstance(hit, dict)]
    return []


def _stream_names(base_url: str, stream_type: str, auth: str) -> set[str]:
    response = _request_json(f"{base_url}/streams?type={stream_type}", auth)
    raw_list = response.get("list", [])
    if not isinstance(raw_list, list):
        return set()
    names: set[str] = set()
    for item in raw_list:
        if isinstance(item, dict):
            names.add(str(cast(dict[str, object], item).get("name", "")))
    return names


def _required_signals_from_env() -> set[str]:
    raw = os.getenv("OPENOBSERVE_REQUIRED_SIGNALS", "logs")
    requested = {part.strip().lower() for part in raw.split(",") if part.strip()}
    if not requested:
        requested = {"logs"}
    valid = {"logs", "metrics", "traces"}
    invalid = requested - valid
    if invalid:
        msg = (
            "invalid OPENOBSERVE_REQUIRED_SIGNALS entries: "
            f"{', '.join(sorted(invalid))}; expected only logs,metrics,traces"
        )
        raise RuntimeError(msg)
    return requested


def main() -> None:
    base_url = _require_env("OPENOBSERVE_URL").rstrip("/")
    user = _require_env("OPENOBSERVE_USER")
    password = _require_env("OPENOBSERVE_PASSWORD")
    auth = _auth_header(user, password)
    run_id = str(int(time.time()))
    os.environ["UNDEF_EXAMPLE_RUN_ID"] = run_id

    start_us = int(time.time() * 1_000_000) - (2 * 60 * 60 * 1_000_000)
    trace_name = f"example.openobserve.work.{run_id}"
    metric_stream = f"example_openobserve_requests_{run_id}"
    log_event = f"example.openobserve.jsonlog.{run_id}"

    before_logs = len(
        [
            hit
            for hit in _search_hits(base_url, "logs", auth, start_us, int(time.time() * 1_000_000))
            if hit.get("event") == log_event
        ]
    )
    before_traces = len(
        [
            hit
            for hit in _search_hits(base_url, "traces", auth, start_us, int(time.time() * 1_000_000))
            if hit.get("operation_name") == trace_name
        ]
    )
    before_metric_streams = _stream_names(base_url, "metrics", auth)
    before = {
        "logs": before_logs,
        "metrics_stream_present": metric_stream in before_metric_streams,
        "traces": before_traces,
    }
    required_signals = _required_signals_from_env()
    print(f"before={before}")
    print(f"required_signals={sorted(required_signals)}")

    runpy.run_path("examples/openobserve/01_emit_all_signals.py", run_name="__main__")

    deadline = time.time() + 30
    after = dict(before)
    while time.time() < deadline:
        end_us = int(time.time() * 1_000_000)
        log_hits = _search_hits(base_url, "logs", auth, start_us, end_us)
        trace_hits = _search_hits(base_url, "traces", auth, start_us, end_us)
        metric_streams = _stream_names(base_url, "metrics", auth)
        after = {
            "logs": len([hit for hit in log_hits if hit.get("event") == log_event]),
            "metrics_stream_present": metric_stream in metric_streams,
            "traces": len([hit for hit in trace_hits if hit.get("operation_name") == trace_name]),
        }
        logs_ok = after["logs"] > before["logs"] if "logs" in required_signals else True
        metrics_ok = bool(after["metrics_stream_present"]) if "metrics" in required_signals else True
        traces_ok = after["traces"] > before["traces"] if "traces" in required_signals else True
        if logs_ok and metrics_ok and traces_ok:
            break
        time.sleep(1)

    print(f"after={after}")
    missing: list[str] = []
    if "logs" in required_signals and after["logs"] <= before["logs"]:
        missing.append("logs")
    if "metrics" in required_signals and not after["metrics_stream_present"]:
        missing.append("metrics")
    if "traces" in required_signals and after["traces"] <= before["traces"]:
        missing.append("traces")
    if missing:
        msg = f"ingestion did not increase for: {', '.join(missing)}"
        raise RuntimeError(msg)
    print("verification passed")


if __name__ == "__main__":
    main()
