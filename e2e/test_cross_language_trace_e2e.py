# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Cross-language distributed tracing E2E test.

Verifies that a W3C traceparent emitted by the TypeScript client is
honoured by the Python backend, producing two spans with the same
trace_id in OpenObserve.

Requires:
    OPENOBSERVE_USER, OPENOBSERVE_PASSWORD, OPENOBSERVE_URL env vars.
    OpenObserve running at OPENOBSERVE_URL.
    undef-telemetry installed with [otel] extra.
    tsx available via npx (already a TS dev dep).
"""

from __future__ import annotations

import base64
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

import pytest

pytestmark = pytest.mark.e2e

_REPO_ROOT = Path(__file__).parent.parent
_SERVER_SCRIPT = _REPO_ROOT / "e2e" / "backends" / "cross_language_server.py"
_TS_SCRIPT = _REPO_ROOT / "typescript" / "scripts" / "e2e_cross_language_client.ts"


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        pytest.skip(f"{name} is not set")
    return value


def _auth_header(user: str, password: str) -> str:
    token = base64.b64encode(f"{user}:{password}".encode()).decode("ascii")
    return f"Basic {token}"


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _search_total(
    base_url: str,
    stream_type: str,
    auth: str,
    sql: str,
    start_time: int,
    end_time: int,
) -> int:
    req = Request(
        url=f"{base_url}/_search?type={stream_type}",
        headers={"Authorization": auth, "Content-Type": "application/json"},
        data=json.dumps({"query": {"sql": sql, "start_time": start_time, "end_time": end_time}}).encode("utf-8"),
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


def test_cross_language_trace_links_ts_and_python_spans() -> None:
    pytest.importorskip("opentelemetry")

    user = _require_env("OPENOBSERVE_USER")
    password = _require_env("OPENOBSERVE_PASSWORD")
    base_url = _require_env("OPENOBSERVE_URL").rstrip("/")
    auth = _auth_header(user, password)

    now_us = int(time.time() * 1_000_000)
    start_us = now_us - (2 * 60 * 60 * 1_000_000)  # 2-hour lookback window

    port = _find_free_port()
    otlp_traces_endpoint = f"{base_url}/v1/traces"
    otlp_headers_value = f"Authorization={quote(auth, safe='')}"

    # ── Start Python backend subprocess ──────────────────────────────────────
    server_env = {
        **os.environ,
        "UNDEF_TRACE_ENABLED": "true",
        "UNDEF_METRICS_ENABLED": "false",
        "UNDEF_TELEMETRY_SERVICE_NAME": "py-e2e-backend",
        "UNDEF_TELEMETRY_VERSION": "e2e",
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": otlp_traces_endpoint,
        "OTEL_EXPORTER_OTLP_HEADERS": otlp_headers_value,
        # Fast batch export so spans flush well within the 30-second deadline.
        "OTEL_BSP_SCHEDULE_DELAY": "200",
        "OTEL_BSP_MAX_EXPORT_BATCH_SIZE": "1",
    }
    server_proc = subprocess.Popen(
        [sys.executable, str(_SERVER_SCRIPT), "--port", str(port)],
        env=server_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        # Wait for server to print "READY" (up to 10 seconds).
        assert server_proc.stdout is not None
        ready_line = ""
        deadline = time.time() + 10
        while time.time() < deadline:
            line = server_proc.stdout.readline()
            if line.startswith("READY"):
                ready_line = line.strip()
                break
        assert ready_line, "Python backend did not become ready in time"

        # ── Run TypeScript client subprocess ─────────────────────────────────
        ts_env = {
            **os.environ,
            "E2E_BACKEND_URL": f"http://127.0.0.1:{port}",
            "OPENOBSERVE_USER": user,
            "OPENOBSERVE_PASSWORD": password,
            "OTEL_EXPORTER_OTLP_ENDPOINT": base_url,
        }
        ts_result = subprocess.run(
            ["npx", "--yes", "tsx", str(_TS_SCRIPT)],
            env=ts_env,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(_REPO_ROOT / "typescript"),
        )
        assert ts_result.returncode == 0, (
            f"TS client failed (exit {ts_result.returncode}):\nstdout: {ts_result.stdout}\nstderr: {ts_result.stderr}"
        )

        # Extract trace_id from TS client stdout.
        trace_id: str | None = None
        for line in ts_result.stdout.splitlines():
            if line.startswith("TRACE_ID="):
                trace_id = line.split("=", 1)[1].strip()
                break
        assert trace_id and len(trace_id) == 32, f"Expected 32-char trace_id in TS stdout, got: {ts_result.stdout!r}"

        # Ask the Python backend to flush and exit cleanly.
        try:
            urlopen(
                Request(f"http://127.0.0.1:{port}/shutdown", method="GET"),
                timeout=5,
            )
        except Exception:
            pass  # server may exit before sending a full response — that is fine

        server_proc.wait(timeout=10)

        # ── Poll OpenObserve for two spans sharing the same trace_id ─────────
        sql = f"SELECT * FROM \"default\" WHERE trace_id = '{trace_id}'"
        deadline = time.time() + 30
        span_count = 0

        while time.time() < deadline:
            end_us = int(time.time() * 1_000_000)
            span_count = _search_total(base_url, "traces", auth, sql, start_us, end_us)
            if span_count >= 2:
                break
            time.sleep(1)

        assert span_count >= 2, (
            f"Expected at least 2 spans with trace_id={trace_id!r} in OpenObserve, "
            f"found {span_count}. "
            f"TS stdout: {ts_result.stdout!r}\n"
            f"TS stderr: {ts_result.stderr!r}"
        )

    finally:
        if server_proc.poll() is None:
            server_proc.terminate()
            server_proc.wait(timeout=5)
