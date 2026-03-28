# Cross-Language Distributed Tracing E2E Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove that a W3C `traceparent` emitted by the TypeScript library is honoured by the Python backend, producing two spans with the same `trace_id` in OpenObserve.

**Architecture:** A Python pytest e2e test spawns a minimal Python HTTP backend (stdlib `http.server`) and a Node.js TypeScript client (`tsx`) as separate subprocesses. The TS client creates a root OTel span, injects the `traceparent` header into a real HTTP request to the Python backend, and both processes export their spans to a live OpenObserve instance. The pytest test then queries OpenObserve and asserts that both spans share the same `trace_id`.

**Tech Stack:** Python 3.11 stdlib `http.server`, `opentelemetry-api/sdk` (already in `otel` extra), `@undef/telemetry` + `@opentelemetry/*` peer deps, `tsx` (already in TS dev deps via npx), OpenObserve running locally.

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `tests/e2e/backends/__init__.py` | Create | Package marker |
| `tests/e2e/backends/cross_language_server.py` | Create | Stdlib HTTP server; extracts W3C context; emits child OTel span |
| `typescript/scripts/e2e_cross_language_client.ts` | Create | Registers OTel providers; emits root span; injects traceparent into fetch; prints `TRACE_ID=` to stdout; force-flushes |
| `tests/e2e/test_cross_language_trace_e2e.py` | Create | Orchestrates both subprocesses; polls OpenObserve; asserts trace linkage |

---

## Task 1: Python HTTP Backend Server

**Files:**
- Create: `tests/e2e/backends/__init__.py`
- Create: `tests/e2e/backends/cross_language_server.py`

- [ ] **Step 1: Create the package marker**

```python
# tests/e2e/backends/__init__.py
```

- [ ] **Step 2: Write the server script**

```python
# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#
"""Minimal HTTP backend for cross-language distributed tracing E2E tests.

Run standalone:
    UNDEF_TRACE_ENABLED=true \\
    OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://localhost:5080/api/default/v1/traces \\
    OTEL_EXPORTER_OTLP_HEADERS="Authorization=Basic ..." \\
    python tests/e2e/backends/cross_language_server.py --port 18765

Endpoints:
    GET /traced   — extracts W3C traceparent, emits child span, returns 200
    GET /health   — returns 200 immediately (used by test to detect readiness)
    GET /shutdown — calls shutdown_telemetry() and exits (flushes OTel spans)
"""

from __future__ import annotations

import argparse
import http.server
import sys

from opentelemetry import trace
from opentelemetry.propagate import extract as otel_extract

from undef.telemetry import setup_telemetry, shutdown_telemetry
from undef.telemetry.config import TelemetryConfig


def _make_handler() -> type[http.server.BaseHTTPRequestHandler]:
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass  # suppress default access logs

        def _send(self, status: int, body: bytes = b"ok") -> None:
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path == "/health":
                self._send(200)
                return

            if self.path == "/shutdown":
                self._send(200)
                shutdown_telemetry()
                sys.exit(0)

            if self.path == "/traced":
                # Extract W3C traceparent from incoming headers.
                # otel_extract() uses the globally configured W3C propagator,
                # which is registered by setup_telemetry() when OTel is enabled.
                carrier = {k.lower(): v for k, v in self.headers.items()}
                parent_ctx = otel_extract(carrier)

                tracer = trace.get_tracer("py.e2e.backend")
                with tracer.start_as_current_span(
                    "py.e2e.cross_language_handler",
                    context=parent_ctx,
                ):
                    # Span is a child of the incoming traceparent.
                    # The OTel batch processor will export it to OpenObserve.
                    pass

                self._send(200)
                return

            self._send(404, b"not found")

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="Cross-language E2E backend server")
    parser.add_argument("--port", type=int, default=18765)
    args = parser.parse_args()

    cfg = TelemetryConfig.from_env()
    setup_telemetry(cfg)

    # Signal readiness on stdout so the test can detect it.
    print(f"READY port={args.port}", flush=True)

    with http.server.HTTPServer(("127.0.0.1", args.port), _make_handler()) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Smoke-test the server manually**

```bash
cd /Users/tim/code/gh/undef-games/undef-telemetry
UNDEF_TRACE_ENABLED=false uv run python tests/e2e/backends/cross_language_server.py --port 18765 &
sleep 0.5
curl -s http://127.0.0.1:18765/health  # should print: ok
curl -s http://127.0.0.1:18765/shutdown
```

Expected: two `ok` responses, process exits cleanly.

---

## Task 2: TypeScript E2E Client Script

**Files:**
- Create: `typescript/scripts/e2e_cross_language_client.ts`

- [ ] **Step 1: Write the client script**

```typescript
// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
/**
 * Cross-language distributed tracing E2E client.
 *
 * Reads from env:
 *   E2E_BACKEND_URL          — base URL of the Python backend (e.g. http://127.0.0.1:18765)
 *   OPENOBSERVE_USER         — OpenObserve basic-auth username
 *   OPENOBSERVE_PASSWORD     — OpenObserve basic-auth password
 *   OTEL_EXPORTER_OTLP_ENDPOINT — OTLP base endpoint (e.g. http://localhost:5080/api/default)
 *
 * Prints to stdout:
 *   TRACE_ID={traceId}
 *
 * Exit code 0 on success, 1 on any error.
 */

import { setupTelemetry, registerOtelProviders, withTrace, getActiveTraceIds } from '../src/index.js';
import { trace } from '@opentelemetry/api';

async function main(): Promise<void> {
  const backendUrl = process.env['E2E_BACKEND_URL'];
  if (!backendUrl) throw new Error('E2E_BACKEND_URL is required');

  const user = process.env['OPENOBSERVE_USER'];
  const password = process.env['OPENOBSERVE_PASSWORD'];
  if (!user || !password) throw new Error('OPENOBSERVE_USER and OPENOBSERVE_PASSWORD are required');

  const endpoint = process.env['OTEL_EXPORTER_OTLP_ENDPOINT'];
  if (!endpoint) throw new Error('OTEL_EXPORTER_OTLP_ENDPOINT is required');

  // Build auth header directly — avoids the base64-padding issue in env var parsing.
  const auth = Buffer.from(`${user}:${password}`).toString('base64');

  const cfg = {
    serviceName: 'ts-e2e-client',
    environment: 'e2e',
    version: 'e2e',
    logLevel: 'info' as const,
    logFormat: 'json' as const,
    otelEnabled: true,
    otlpEndpoint: endpoint,
    otlpHeaders: { Authorization: `Basic ${auth}` },
    sanitizeFields: [],
    captureToWindow: false,
    consoleOutput: false,
  };

  setupTelemetry(cfg);
  // registerOtelProviders is async — must be awaited before creating spans.
  await registerOtelProviders(cfg);

  let capturedTraceId: string | undefined;

  // withTrace correctly handles async: it uses startActiveSpan and awaits the
  // Promise branch before calling span.end(), so the fetch completes inside the span.
  await withTrace('ts.e2e.cross_language_request', async () => {
    const ids = getActiveTraceIds();
    if (!ids.trace_id || !ids.span_id) {
      throw new Error('No active OTel span — registerOtelProviders may have failed');
    }

    capturedTraceId = ids.trace_id;
    const traceparent = `00-${ids.trace_id}-${ids.span_id}-01`;

    const resp = await fetch(`${backendUrl}/traced`, {
      headers: { traceparent },
    });
    if (!resp.ok) {
      throw new Error(`Backend returned HTTP ${resp.status}`);
    }
    await resp.text();
  });

  if (!capturedTraceId) throw new Error('trace_id was never captured');

  // Force-flush: give the BatchSpanProcessor time to export, then shut down.
  // BasicTracerProvider implements forceFlush() and shutdown().
  const provider = trace.getTracerProvider() as {
    forceFlush?: () => Promise<void>;
    shutdown?: () => Promise<void>;
  };
  if (provider.forceFlush) await provider.forceFlush();
  if (provider.shutdown) await provider.shutdown();

  // Print trace_id for the pytest test to capture.
  console.log(`TRACE_ID=${capturedTraceId}`);
}

main().catch((err: unknown) => {
  console.error('[ts-e2e-client] fatal:', err);
  process.exit(1);
});
```

- [ ] **Step 2: Verify the script parses without type errors**

```bash
cd /Users/tim/code/gh/undef-games/undef-telemetry/typescript
npx tsc --noEmit --project tsconfig.json 2>&1 | head -20
```

Expected: no errors referencing `scripts/e2e_cross_language_client.ts`. If the script is outside `tsconfig.json`'s `include`, create `typescript/tsconfig.scripts.json`:

```json
{
  "extends": "./tsconfig.json",
  "include": ["src/**/*.ts", "scripts/**/*.ts"]
}
```

Then re-run: `npx tsc --noEmit --project tsconfig.scripts.json`

- [ ] **Step 3: Smoke-test the script (requires a running Python backend and OpenObserve)**

```bash
cd /Users/tim/code/gh/undef-games/undef-telemetry/typescript
# Terminal 1 — backend
UNDEF_TRACE_ENABLED=true \
UNDEF_TELEMETRY_SERVICE_NAME=py-e2e-backend \
OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://localhost:5080/api/default/v1/traces \
OTEL_EXPORTER_OTLP_HEADERS="Authorization=$(python3 -c "import base64; print('Basic ' + base64.b64encode(b'tim@provide.io:password').decode())")" \
OTEL_BSP_SCHEDULE_DELAY=200 \
uv run python ../tests/e2e/backends/cross_language_server.py --port 18765 &

# Terminal 2 — TS client
E2E_BACKEND_URL=http://127.0.0.1:18765 \
OPENOBSERVE_USER=tim@provide.io \
OPENOBSERVE_PASSWORD=password \
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:5080/api/default \
npx tsx scripts/e2e_cross_language_client.ts
```

Expected output from TS client: `TRACE_ID=<32 hex chars>`

---

## Task 3: Pytest E2E Orchestration Test

**Files:**
- Create: `tests/e2e/test_cross_language_trace_e2e.py`

- [ ] **Step 1: Write the test**

```python
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
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen
from typing import Any

import pytest

pytestmark = pytest.mark.e2e

_REPO_ROOT = Path(__file__).parent.parent.parent
_SERVER_SCRIPT = _REPO_ROOT / "tests" / "e2e" / "backends" / "cross_language_server.py"
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
        data=json.dumps(
            {"query": {"sql": sql, "start_time": start_time, "end_time": end_time}}
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
            f"TS client failed (exit {ts_result.returncode}):\n"
            f"stdout: {ts_result.stdout}\n"
            f"stderr: {ts_result.stderr}"
        )

        # Extract trace_id from TS client stdout.
        trace_id: str | None = None
        for line in ts_result.stdout.splitlines():
            if line.startswith("TRACE_ID="):
                trace_id = line.split("=", 1)[1].strip()
                break
        assert trace_id and len(trace_id) == 32, (
            f"Expected 32-char trace_id in TS stdout, got: {ts_result.stdout!r}"
        )

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
        sql = f'SELECT * FROM "default" WHERE trace_id = \'{trace_id}\''
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
```

- [ ] **Step 2: Run the test**

```bash
cd /Users/tim/code/gh/undef-games/undef-telemetry
OPENOBSERVE_USER=tim@provide.io \
OPENOBSERVE_PASSWORD=password \
OPENOBSERVE_URL=http://localhost:5080/api/default \
uv run pytest tests/e2e/test_cross_language_trace_e2e.py \
  --no-cov -v -p no:undef_telemetry -o "addopts="
```

Expected output:
```
tests/e2e/test_cross_language_trace_e2e.py::test_cross_language_trace_links_ts_and_python_spans PASSED
```

- [ ] **Step 3: Verify in OpenObserve UI**

Open `http://localhost:5080` → Traces → filter by `service_name = ts-e2e-client` or `py-e2e-backend`. Both spans should appear under the same trace tree.

---

## Task 4: Confirm quality gates still pass

- [ ] **Step 1: Confirm the default test suite is unaffected**

```bash
cd /Users/tim/code/gh/undef-games/undef-telemetry
uv run python scripts/run_pytest_gate.py 2>&1 | grep -E "passed|failed|TOTAL"
```

Expected: `TOTAL ... 100%` and all tests passing. The new e2e test is excluded by the default `-m "not e2e"` filter.

- [ ] **Step 2: Confirm SPDX headers are present on new Python files**

```bash
uv run python scripts/check_spdx_headers.py
```

Expected: no errors.

- [ ] **Step 3: Confirm LOC gate**

```bash
uv run python scripts/check_max_loc.py --max-lines 500
```

Expected: no files exceed 500 lines.

- [ ] **Step 4: Commit**

```bash
git add \
  tests/e2e/backends/__init__.py \
  tests/e2e/backends/cross_language_server.py \
  typescript/scripts/e2e_cross_language_client.ts \
  tests/e2e/test_cross_language_trace_e2e.py
git commit -m "test(e2e): cross-language distributed trace linkage via W3C traceparent"
```

---

## Self-Review

**Spec coverage check:**
- ✅ TypeScript creates root span → `withTrace('ts.e2e.cross_language_request', ...)` in Task 2
- ✅ Injects `traceparent` header into fetch → `traceparent = \`00-${ids.trace_id}-${ids.span_id}-01\`` in Task 2
- ✅ Python backend extracts `traceparent` → `otel_extract(carrier)` in Task 1
- ✅ Python backend creates child span → `tracer.start_as_current_span(..., context=parent_ctx)` in Task 1
- ✅ Both export to OpenObserve → configured via `OTEL_EXPORTER_OTLP_*` env vars in Task 3
- ✅ Query OpenObserve and verify shared `trace_id` → `_search_total(... WHERE trace_id = ...)` in Task 3
- ✅ Two-subprocess architecture (clean state isolation) → `subprocess.Popen` + `subprocess.run` in Task 3
- ✅ `registerOtelProviders` awaited before span creation → explicit `await` in Task 2
- ✅ Force-flush before exit → `provider.forceFlush()` + `provider.shutdown()` in Task 2
- ✅ Auth header built from raw creds (avoids base64-padding issue in env var parsing) → `Buffer.from(...)` in Task 2
- ✅ Server readiness detection → `READY port=N` on stdout in Task 1
- ✅ Graceful server shutdown with OTel flush → `/shutdown` endpoint calls `shutdown_telemetry()` in Task 1

**Placeholder scan:** No TBDs, no "implement later", no vague steps. All code is complete.

**Type consistency:** `_search_total` signature in Task 3 matches the function body exactly. `TelemetryConfig` shape in Task 2 matches `typescript/src/config.ts` interface field for field.
