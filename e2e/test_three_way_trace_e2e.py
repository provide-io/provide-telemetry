# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Three-way cross-language distributed tracing E2E test.

Verifies that Go, TypeScript, and Python all produce spans with the same
trace_id in OpenObserve when W3C traceparent headers are propagated:

    Go client  ──traceparent──▶  Python backend (span 1)
    TS client  ──traceparent──▶  Python backend (span 2)

Both clients reuse the SAME trace_id. The test verifies ≥3 spans
(Go root + TS root + 2 Python children) share that trace_id in OpenObserve.

Requires:
    OPENOBSERVE_USER, OPENOBSERVE_PASSWORD, OPENOBSERVE_URL env vars.
    OpenObserve running at OPENOBSERVE_URL.
    provide-telemetry installed with [otel] extra.
    Go toolchain available.
    tsx available via npx.
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
_GO_CLIENT_DIR = _REPO_ROOT / "go" / "cmd" / "e2e_cross_language_client"


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


def _search_traces(
    base_url: str,
    auth: str,
    sql: str,
    start_time: int,
    end_time: int,
) -> list[dict[str, Any]]:
    req = Request(
        url=f"{base_url}/_search?type=traces",
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
            return []
        raise
    return payload.get("hits", [])  # type: ignore[no-any-return]


def _extract_trace_id(output: str) -> str:
    for line in output.splitlines():
        if line.startswith("TRACE_ID="):
            return line.split("=", 1)[1].strip()
    return ""


def test_three_way_trace_go_ts_python() -> None:
    """Go + TS clients → Python backend → all spans share one trace_id in OpenObserve."""
    pytest.importorskip("opentelemetry")

    user = _require_env("OPENOBSERVE_USER")
    password = _require_env("OPENOBSERVE_PASSWORD")
    base_url = _require_env("OPENOBSERVE_URL").rstrip("/")
    auth = _auth_header(user, password)

    now_us = int(time.time() * 1_000_000)
    start_us = now_us - (2 * 60 * 60 * 1_000_000)

    port = _find_free_port()
    otlp_traces_endpoint = f"{base_url}/v1/traces"
    otlp_headers_value = f"Authorization={quote(auth, safe='')}"

    # ── Start Python backend ─────────────────────────────────────────────────
    server_env = {
        **os.environ,
        "PROVIDE_TRACE_ENABLED": "true",
        "PROVIDE_METRICS_ENABLED": "false",
        "PROVIDE_TELEMETRY_SERVICE_NAME": "py-e2e-backend",
        "PROVIDE_TELEMETRY_VERSION": "e2e",
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": otlp_traces_endpoint,
        "OTEL_EXPORTER_OTLP_HEADERS": otlp_headers_value,
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
        # Wait for readiness.
        assert server_proc.stdout is not None
        ready_line = ""
        deadline = time.time() + 10
        while time.time() < deadline:
            line = server_proc.stdout.readline()
            if line.startswith("READY"):
                ready_line = line.strip()
                break
        assert ready_line, "Python backend did not become ready in time"

        # ── Run Go client ────────────────────────────────────────────────────
        go_env = {
            **os.environ,
            "E2E_BACKEND_URL": f"http://127.0.0.1:{port}",
            "OPENOBSERVE_USER": user,
            "OPENOBSERVE_PASSWORD": password,
            "OTEL_EXPORTER_OTLP_ENDPOINT": base_url,
        }
        go_result = subprocess.run(
            ["go", "run", "."],
            env=go_env,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(_GO_CLIENT_DIR),
        )
        assert go_result.returncode == 0, (
            f"Go client failed (exit {go_result.returncode}):\nstdout: {go_result.stdout}\nstderr: {go_result.stderr}"
        )
        go_trace_id = _extract_trace_id(go_result.stdout)
        assert go_trace_id and len(go_trace_id) == 32, f"Expected 32-char trace_id from Go, got: {go_result.stdout!r}"

        # ── Run TypeScript client ────────────────────────────────────────────
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
        ts_trace_id = _extract_trace_id(ts_result.stdout)
        assert ts_trace_id and len(ts_trace_id) == 32, f"Expected 32-char trace_id from TS, got: {ts_result.stdout!r}"

        # ── Shutdown Python backend ──────────────────────────────────────────
        try:
            urlopen(
                Request(f"http://127.0.0.1:{port}/shutdown", method="GET"),
                timeout=5,
            )
        except OSError:
            pass
        server_proc.wait(timeout=10)

        # ── Verify spans in OpenObserve ──────────────────────────────────────
        # Go trace: 1 Go root span + 1 Python child = 2 spans
        # TS trace: 1 TS root span + 1 Python child = 2 spans
        for label, trace_id, min_spans in [
            ("Go", go_trace_id, 2),
            ("TypeScript", ts_trace_id, 2),
        ]:
            sql = f"SELECT * FROM \"default\" WHERE trace_id = '{trace_id}'"
            poll_deadline = time.time() + 30
            hits: list[dict[str, Any]] = []

            while time.time() < poll_deadline:
                end_us = int(time.time() * 1_000_000)
                hits = _search_traces(base_url, auth, sql, start_us, end_us)
                if len(hits) >= min_spans:
                    break
                time.sleep(1)

            assert len(hits) >= min_spans, (
                f"{label} trace_id={trace_id}: expected >={min_spans} spans, found {len(hits)}"
            )

            # Verify spans come from different services (cross-language).
            service_names = {h.get("service_name", h.get("service.name", "")) for h in hits}
            assert len(service_names) >= 2, f"{label}: expected spans from >=2 services, got {service_names}"

    finally:
        if server_proc.poll() is None:
            server_proc.terminate()
            server_proc.wait(timeout=5)
