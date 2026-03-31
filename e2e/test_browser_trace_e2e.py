# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Browser-based cross-language distributed tracing E2E test.

Verifies that a W3C traceparent emitted by a real Chromium browser tab
(running @provide/telemetry via Vite) is honoured by the Python backend,
producing two spans with the same trace_id in OpenObserve.

Requires:
    OPENOBSERVE_USER, OPENOBSERVE_PASSWORD, OPENOBSERVE_URL env vars.
    OpenObserve running at OPENOBSERVE_URL.
    playwright Python package with Chromium:
        uv run python -m playwright install chromium
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
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

import pytest

pytestmark = pytest.mark.e2e

_REPO_ROOT = Path(__file__).parent.parent
_SERVER_SCRIPT = _REPO_ROOT / "e2e" / "backends" / "cross_language_server.py"
_TS_DIR = _REPO_ROOT / "typescript"


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


def _wait_for_port(port: int, timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.2)
    return False


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


def test_browser_trace_links_browser_and_python_spans() -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("playwright not installed; run: uv run python -m playwright install chromium")
    pytest.importorskip("opentelemetry")

    user = _require_env("OPENOBSERVE_USER")
    password = _require_env("OPENOBSERVE_PASSWORD")
    base_url = _require_env("OPENOBSERVE_URL").rstrip("/")
    auth = _auth_header(user, password)

    now_us = int(time.time() * 1_000_000)
    start_us = now_us - (2 * 60 * 60 * 1_000_000)  # 2-hour lookback window

    backend_port = _find_free_port()
    vite_port = _find_free_port()
    otlp_traces_endpoint = f"{base_url}/v1/traces"
    otlp_headers_value = f"Authorization={quote(auth, safe='')}"

    # ── Start Python backend ──────────────────────────────────────────────────
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
        [sys.executable, str(_SERVER_SCRIPT), "--port", str(backend_port)],
        env=server_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    # ── Start Vite dev server ─────────────────────────────────────────────────
    vite_env = {
        **os.environ,
        "E2E_OTLP_ENDPOINT": base_url,
        "E2E_BACKEND_PORT": str(backend_port),
    }
    vite_proc = subprocess.Popen(
        [
            "npx",
            "vite",
            "--config",
            "vite.e2e.config.ts",
            "--port",
            str(vite_port),
        ],
        env=vite_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=str(_TS_DIR),
    )

    try:
        # Wait for Python backend READY signal.
        assert server_proc.stdout is not None
        ready_line = ""
        deadline = time.time() + 10
        while time.time() < deadline:
            line = server_proc.stdout.readline()
            if line.startswith("READY"):
                ready_line = line.strip()
                break
        assert ready_line, "Python backend did not become ready in time"

        # Wait for Vite to be accepting connections.
        assert _wait_for_port(vite_port, timeout=30), f"Vite dev server did not start on port {vite_port} within 30s"
        # ── Launch Chromium ───────────────────────────────────────────────────
        qs = urlencode({"otlpAuth": auth})
        page_url = f"http://127.0.0.1:{vite_port}/?{qs}"

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            console_messages: list[str] = []
            page.on("console", lambda msg: console_messages.append(msg.text))
            # Retry page load — Vite may still be building the module graph
            # after the port is open.
            for _attempt in range(3):
                resp = page.goto(page_url, wait_until="networkidle")
                if resp and resp.ok:
                    break
                time.sleep(1.0)

            # Poll #status until it leaves "loading" (up to 30s).
            status_el = page.locator("#status")
            status = "loading"
            deadline = time.time() + 30
            while time.time() < deadline and status == "loading":
                text = status_el.text_content(timeout=1000)
                status = text or "loading"
                if status == "loading":
                    time.sleep(0.5)

            assert status == "done", f"Browser tracer failed. #status={status!r}\nConsole messages: {console_messages}"
            trace_id = page.locator("#trace-id").text_content() or ""
            browser.close()

        assert len(trace_id) == 32, f"Expected 32-char trace_id from browser DOM, got: {trace_id!r}"

        # Flush and stop the Python backend.
        try:
            urlopen(
                Request(f"http://127.0.0.1:{backend_port}/shutdown", method="GET"),
                timeout=5,
            )
        except Exception:
            pass  # server exits before finishing the response — that is fine
        server_proc.wait(timeout=10)

        # ── Poll OpenObserve for two spans sharing trace_id ───────────────────
        sql = f"SELECT * FROM \"default\" WHERE trace_id = '{trace_id}'"
        deadline = time.time() + 30
        span_count = 0
        while time.time() < deadline:
            end_us = int(time.time() * 1_000_000)
            span_count = _search_total(base_url, "traces", auth, sql, start_us, end_us)
            if span_count >= 2:
                break
            time.sleep(1)

        assert span_count >= 2, f"Expected >=2 spans with trace_id={trace_id!r} in OpenObserve, found {span_count}."

    finally:
        vite_proc.terminate()
        vite_proc.wait(timeout=10)
        if server_proc.poll() is None:
            server_proc.terminate()
            server_proc.wait(timeout=5)
