# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Cross-language distributed tracing E2E test.

Verifies that a W3C traceparent emitted by the TypeScript client is
honoured by the Python backend, producing two spans with the same
trace_id in OpenObserve.

Requires:
    OPENOBSERVE_USER, OPENOBSERVE_PASSWORD, OPENOBSERVE_URL env vars.
    OpenObserve running at OPENOBSERVE_URL.
    provide-telemetry installed with [otel] extra.
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
_RUST_DIR = _REPO_ROOT / "rust"


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


def _start_backend(backend_lang: str, port: int, base_url: str, otlp_headers_value: str) -> subprocess.Popen[str]:
    server_env = {
        **os.environ,
        "PROVIDE_TRACE_ENABLED": "true",
        "PROVIDE_METRICS_ENABLED": "false",
        "PROVIDE_TELEMETRY_VERSION": "e2e",
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": f"{base_url}/v1/traces",
        "OTEL_EXPORTER_OTLP_HEADERS": otlp_headers_value,
        "OTEL_BSP_SCHEDULE_DELAY": "200",
        "OTEL_BSP_MAX_EXPORT_BATCH_SIZE": "1",
    }
    if backend_lang == "python":
        server_env["PROVIDE_TELEMETRY_SERVICE_NAME"] = "py-e2e-backend"
        command = [sys.executable, str(_SERVER_SCRIPT), "--port", str(port)]
        cwd = str(_REPO_ROOT)
    elif backend_lang == "rust":
        server_env["PROVIDE_TELEMETRY_SERVICE_NAME"] = "rust-e2e-backend"
        command = [
            "cargo",
            "run",
            "--quiet",
            "--features",
            "otel",
            "--example",
            "e2e_cross_language_server",
            "--",
            "--port",
            str(port),
        ]
        cwd = str(_RUST_DIR)
    else:
        raise AssertionError(f"unsupported backend_lang={backend_lang!r}")

    return subprocess.Popen(
        command,
        env=server_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=cwd,
    )


def _run_client(client_lang: str, backend_url: str, base_url: str, auth: str) -> subprocess.CompletedProcess[str]:
    if client_lang == "typescript":
        client_env = {
            **os.environ,
            "E2E_BACKEND_URL": backend_url,
            "OPENOBSERVE_USER": _require_env("OPENOBSERVE_USER"),
            "OPENOBSERVE_PASSWORD": _require_env("OPENOBSERVE_PASSWORD"),
            "OTEL_EXPORTER_OTLP_ENDPOINT": base_url,
        }
        return subprocess.run(
            ["npx", "--yes", "tsx", str(_TS_SCRIPT)],
            env=client_env,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(_REPO_ROOT / "typescript"),
        )
    if client_lang == "rust":
        client_env = {
            **os.environ,
            "E2E_BACKEND_URL": backend_url,
            "OTEL_EXPORTER_OTLP_ENDPOINT": base_url,
            "OTEL_EXPORTER_OTLP_HEADERS": f"Authorization={quote(auth, safe='')}",
        }
        return subprocess.run(
            [
                "cargo",
                "run",
                "--quiet",
                "--features",
                "otel",
                "--example",
                "e2e_cross_language_client",
            ],
            env=client_env,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(_RUST_DIR),
        )
    raise AssertionError(f"unsupported client_lang={client_lang!r}")


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


@pytest.mark.parametrize(
    ("backend_lang", "client_lang"),
    [("python", "typescript"), ("rust", "typescript"), ("python", "rust")],
)
def test_cross_language_trace_links_spans(backend_lang: str, client_lang: str) -> None:
    pytest.importorskip("opentelemetry")

    user = _require_env("OPENOBSERVE_USER")
    password = _require_env("OPENOBSERVE_PASSWORD")
    base_url = _require_env("OPENOBSERVE_URL").rstrip("/")
    auth = _auth_header(user, password)

    now_us = int(time.time() * 1_000_000)
    start_us = now_us - (2 * 60 * 60 * 1_000_000)  # 2-hour lookback window

    port = _find_free_port()
    otlp_headers_value = f"Authorization={quote(auth, safe='')}"
    server_proc = _start_backend(backend_lang, port, base_url, otlp_headers_value)

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

        result = _run_client(client_lang, f"http://127.0.0.1:{port}", base_url, auth)
        assert result.returncode == 0, (
            f"{client_lang} client failed (exit {result.returncode}):\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

        # Extract trace_id from client stdout.
        trace_id: str | None = None
        for line in result.stdout.splitlines():
            if line.startswith("TRACE_ID="):
                trace_id = line.split("=", 1)[1].strip()
                break
        assert trace_id and len(trace_id) == 32, f"Expected 32-char trace_id in client stdout, got: {result.stdout!r}"

        # Ask the Python backend to flush and exit cleanly.
        try:
            urlopen(
                Request(f"http://127.0.0.1:{port}/shutdown", method="GET"),
                timeout=5,
            )
        except OSError:
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
            f"client stdout: {result.stdout!r}\n"
            f"client stderr: {result.stderr!r}"
        )

    finally:
        if server_proc.poll() is None:
            server_proc.terminate()
            server_proc.wait(timeout=5)
