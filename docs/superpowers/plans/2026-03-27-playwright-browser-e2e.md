# Playwright Browser E2E — Distributed Tracing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove `@provide-io/telemetry` works in a real Chromium browser by loading a Vite-served page that emits an OTel span, injects W3C `traceparent` into a fetch call to the Python backend, and verifying both spans share a `trace_id` in OpenObserve.

**Architecture:** A Vite dev server (`vite.e2e.config.ts`) serves the browser page and acts as a proxy — `/v1` routes to OpenObserve (avoiding CORS on OTLP export) and `/backend` routes to the Python backend (avoiding CORS on the traced fetch). The browser page (`e2e-browser/browser_tracer.ts`) imports `@provide-io/telemetry` as live TypeScript, uses `startActiveSpan` callback to get span context directly (no async context manager needed), exports via the Vite proxy, and writes `trace_id` to the DOM. A pytest test orchestrates the three processes (Python backend, Vite server, Playwright Chromium), reads the DOM result, and polls OpenObserve.

**Tech Stack:** Python `playwright` package (sync API), Vite 8 (already in devDeps), `@opentelemetry/api` + peer deps (already in devDeps), `pytest`, `subprocess`.

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `typescript/e2e-browser/index.html` | Create | HTML page served by Vite; mounts `browser_tracer.ts` |
| `typescript/e2e-browser/browser_tracer.ts` | Create | Browser-side: registers OTel, creates span, fetches backend, writes result to DOM |
| `typescript/vite.e2e.config.ts` | Create | Vite config: proxies `/v1` → OpenObserve and `/backend` → Python backend |
| `typescript/tsconfig.scripts.json` | Modify | Add `e2e-browser/**/*.ts` to include so it type-checks |
| `pyproject.toml` | Modify | Add `playwright>=1.50.0` to dev deps |
| `REUSE.toml` | Modify | Add `CHANGELOG.md`, `SECURITY.md`, and new `typescript/e2e-browser/**` paths |
| `tests/e2e/test_browser_trace_e2e.py` | Create | pytest: starts Vite + Python backend + Playwright; asserts trace linkage in OpenObserve |
| `.github/workflows/ci.yml` | Modify | Add `playwright install --with-deps chromium` to `openobserve-e2e` job |

---

## Task 1: Browser Page Assets and Vite Config

**Files:**
- Create: `typescript/e2e-browser/index.html`
- Create: `typescript/e2e-browser/browser_tracer.ts`
- Create: `typescript/vite.e2e.config.ts`
- Modify: `typescript/tsconfig.scripts.json`

- [ ] **Step 1: Create the HTML entry point**

```html
<!-- SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <title>E2E Browser Tracer</title>
  </head>
  <body>
    <div id="status">loading</div>
    <div id="trace-id"></div>
    <script type="module" src="./browser_tracer.ts"></script>
  </body>
</html>
```

Save to: `typescript/e2e-browser/index.html`

- [ ] **Step 2: Create the browser tracer script**

```typescript
// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
/**
 * Browser-side E2E tracer page script.
 *
 * Reads config from URL query params:
 *   otlpAuth — Authorization header value (e.g. "Basic base64==")
 *
 * OTLP traces are sent to /v1/traces (same-origin, no CORS) — Vite proxies
 * to OpenObserve. The traced fetch goes to /backend/traced (same-origin) —
 * Vite proxies to the Python backend.
 *
 * On completion writes to DOM:
 *   #trace-id — 32-char hex trace_id
 *   #status   — "done" on success, "error: <msg>" on failure
 */

import { registerOtelProviders, setupTelemetry, shutdownTelemetry } from '../src/index.js';
import { trace } from '@opentelemetry/api';

async function run(): Promise<void> {
  const params = new URLSearchParams(window.location.search);
  const otlpAuth = params.get('otlpAuth');
  if (!otlpAuth) throw new Error('Missing required query param: otlpAuth');

  // OTLP export goes to Vite origin — proxied to OpenObserve, no CORS.
  const cfg = {
    serviceName: 'browser-e2e-client',
    environment: 'e2e',
    version: 'e2e',
    logLevel: 'info' as const,
    logFormat: 'json' as const,
    otelEnabled: true,
    otlpEndpoint: window.location.origin,
    otlpHeaders: { Authorization: otlpAuth },
    sanitizeFields: [] as string[],
    captureToWindow: false,
    consoleOutput: false,
  };

  setupTelemetry(cfg);
  await registerOtelProviders(cfg);

  const tracer = trace.getTracer('browser-e2e');
  let traceId = '';

  await new Promise<void>((resolve, reject) => {
    tracer.startActiveSpan('browser.e2e.cross_language_request', async (span) => {
      try {
        // Get span context directly from the callback argument — no async context
        // manager needed (avoids Node.js-only AsyncLocalStorage dependency).
        const spanCtx = span.spanContext();
        traceId = spanCtx.traceId;
        const traceparent = `00-${spanCtx.traceId}-${spanCtx.spanId}-01`;

        // Fetch goes to /backend/traced — Vite proxies to Python backend, no CORS.
        const resp = await fetch('/backend/traced', { headers: { traceparent } });
        if (!resp.ok) throw new Error(`Backend returned HTTP ${resp.status}`);
        await resp.text();
        span.end();
        resolve();
      } catch (err) {
        span.end();
        reject(err);
      }
    });
  });

  // shutdownTelemetry() drains the registered OTel providers (flushes BatchSpanProcessor).
  await shutdownTelemetry();

  document.getElementById('trace-id')!.textContent = traceId;
  document.getElementById('status')!.textContent = 'done';
}

run().catch((err: unknown) => {
  const msg = err instanceof Error ? err.message : String(err);
  document.getElementById('status')!.textContent = `error: ${msg}`;
});
```

Save to: `typescript/e2e-browser/browser_tracer.ts`

- [ ] **Step 3: Create the Vite E2E config**

```typescript
// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
/**
 * Vite config for the browser E2E test.
 *
 * Two proxies eliminate CORS:
 *   /v1      → OpenObserve OTLP endpoint (trace export)
 *   /backend → Python test backend (traced fetch), path prefix stripped
 *
 * Env vars consumed at startup:
 *   E2E_OTLP_ENDPOINT   — OTLP base URL  (e.g. http://localhost:5080/api/default)
 *   E2E_BACKEND_PORT    — Python backend port (e.g. 18765)
 */
import { defineConfig } from 'vite';

export default defineConfig({
  root: 'e2e-browser',
  server: {
    fs: {
      // Allow Vite to serve files from typescript/ (parent of e2e-browser/).
      allow: ['..'],
    },
    proxy: {
      '/v1': {
        target: process.env['E2E_OTLP_ENDPOINT'] ?? 'http://localhost:5080/api/default',
        changeOrigin: true,
      },
      '/backend': {
        target: `http://127.0.0.1:${process.env['E2E_BACKEND_PORT'] ?? '18765'}`,
        changeOrigin: true,
        rewrite: (path: string) => path.replace(/^\/backend/, ''),
      },
    },
  },
});
```

Save to: `typescript/vite.e2e.config.ts`

- [ ] **Step 4: Add e2e-browser to tsconfig.scripts.json**

Read `typescript/tsconfig.scripts.json`. Change the `include` line from:
```json
"include": ["src/**/*.ts", "scripts/**/*.ts"]
```
to:
```json
"include": ["src/**/*.ts", "scripts/**/*.ts", "e2e-browser/**/*.ts", "vite.e2e.config.ts"]
```

- [ ] **Step 5: Verify TypeScript type-checks**

```bash
cd /Users/tim/code/gh/provide-io/provide-telemetry/typescript
npx tsc --noEmit -p tsconfig.scripts.json 2>&1; echo "exit: $?"
```

Expected: `exit: 0` — no type errors.

- [ ] **Step 6: Smoke-test Vite server starts**

```bash
cd /Users/tim/code/gh/provide-io/provide-telemetry/typescript
E2E_OTLP_ENDPOINT=http://localhost:5080/api/default \
E2E_BACKEND_PORT=18765 \
npx vite --config vite.e2e.config.ts --port 19877 &
VPID=$!
sleep 3
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:19877/
kill $VPID
```

Expected: `200` — Vite is serving the HTML page.

- [ ] **Step 7: Commit browser assets**

```bash
git add \
  typescript/e2e-browser/index.html \
  typescript/e2e-browser/browser_tracer.ts \
  typescript/vite.e2e.config.ts \
  typescript/tsconfig.scripts.json
git commit -m "feat(browser-e2e): add Vite-served browser tracer page and proxy config"
```

---

## Task 2: Add playwright Python Dependency

**Files:**
- Modify: `pyproject.toml`
- Modify: `REUSE.toml`

- [ ] **Step 1: Add playwright to dev deps**

In `pyproject.toml`, find the `dev = [` block in `[dependency-groups]`. Add `"playwright>=1.50.0",` to the list (alphabetical order, between `"pip-licenses..."` and `"pre-commit..."`).

Full updated block (show only the changed lines):
```toml
  "pip-licenses>=5.0.0",
  "playwright>=1.50.0",
  "pre-commit>=4.0.1",
```

- [ ] **Step 2: Fix REUSE.toml for new top-level markdown files**

`CHANGELOG.md` and `SECURITY.md` are not covered by any REUSE.toml annotation. Add them to the first `[[annotations]]` block's `path` list:

In `REUSE.toml`, find:
```toml
path = [
  "README.md",
  "CLAUDE.md",
  "docs/**",
```

Change to:
```toml
path = [
  "README.md",
  "CLAUDE.md",
  "CHANGELOG.md",
  "SECURITY.md",
  "docs/**",
```

- [ ] **Step 3: Sync and install Chromium**

```bash
cd /Users/tim/code/gh/provide-io/provide-telemetry
uv sync --group dev
uv run python -m playwright install chromium
```

Expected: playwright installs cleanly, then downloads Chromium (first run only, ~100 MB).

- [ ] **Step 4: Verify playwright works**

```bash
uv run python -c "
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    page = b.new_page()
    page.goto('about:blank')
    print('title:', repr(page.title()))
    b.close()
"
```

Expected: `title: ''` — Chromium launched successfully.

- [ ] **Step 5: Verify reuse lint passes**

```bash
cd /Users/tim/code/gh/provide-io/provide-telemetry
uvx reuse lint 2>&1 | tail -5
```

Expected: `Congratulations! Your project is compliant with version 3.3 of the REUSE Specification.`

If any new files are flagged, add their paths to the appropriate `[[annotations]]` block in `REUSE.toml`.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml REUSE.toml uv.lock
git commit -m "chore: add playwright dev dep; fix REUSE annotations for CHANGELOG and SECURITY"
```

---

## Task 3: Write the Pytest Browser E2E Test

**Files:**
- Create: `tests/e2e/test_browser_trace_e2e.py`

- [ ] **Step 1: Write the test**

```python
# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Provide Telemetry.
#
"""Browser-based cross-language distributed tracing E2E test.

Verifies that a W3C traceparent emitted by a real Chromium browser tab
(running @provide-io/telemetry via Vite) is honoured by the Python backend,
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

_REPO_ROOT = Path(__file__).parent.parent.parent
_SERVER_SCRIPT = _REPO_ROOT / "tests" / "e2e" / "backends" / "cross_language_server.py"
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
            "npx", "vite",
            "--config", "vite.e2e.config.ts",
            "--port", str(vite_port),
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
        assert _wait_for_port(vite_port, timeout=30), (
            f"Vite dev server did not start on port {vite_port} within 30s"
        )
        # Brief settle so Vite finishes module graph construction.
        time.sleep(1.0)

        # ── Launch Chromium ───────────────────────────────────────────────────
        qs = urlencode({"otlpAuth": auth})
        page_url = f"http://127.0.0.1:{vite_port}/?{qs}"

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(page_url, wait_until="networkidle")

            # Poll #status until it leaves "loading" (up to 30s).
            status_el = page.locator("#status")
            status = "loading"
            deadline = time.time() + 30
            while time.time() < deadline and status == "loading":
                text = status_el.text_content(timeout=1000)
                status = text or "loading"
                if status == "loading":
                    time.sleep(0.5)

            assert status == "done", (
                f"Browser tracer failed. #status={status!r}\n"
                f"Console messages: {[m.text for m in page.context.pages[0:1]]}"
            )
            trace_id = page.locator("#trace-id").text_content() or ""
            browser.close()

        assert len(trace_id) == 32, (
            f"Expected 32-char trace_id from browser DOM, got: {trace_id!r}"
        )

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

        assert span_count >= 2, (
            f"Expected >=2 spans with trace_id={trace_id!r} in OpenObserve, "
            f"found {span_count}."
        )

    finally:
        vite_proc.terminate()
        vite_proc.wait(timeout=10)
        if server_proc.poll() is None:
            server_proc.terminate()
            server_proc.wait(timeout=5)
```

Save to: `tests/e2e/test_browser_trace_e2e.py`

- [ ] **Step 2: Run the test**

```bash
cd /Users/tim/code/gh/provide-io/provide-telemetry
OPENOBSERVE_USER=tim@provide.io \
OPENOBSERVE_PASSWORD=password \
OPENOBSERVE_URL=http://localhost:5080/api/default \
uv run --extra otel pytest tests/e2e/test_browser_trace_e2e.py \
  --no-cov -v -p no:provide_telemetry -o "addopts=" -s 2>&1
```

Expected:
```
tests/e2e/test_browser_trace_e2e.py::test_browser_trace_links_browser_and_python_spans PASSED
```

If the test fails with `#status=error: ...`, the error message in the DOM is the browser tracer's exception. Common causes:
- `error: No active OTel span` — `registerOtelProviders` failed silently; check that peer deps are in `node_modules` (they are, as devDependencies).
- `error: Backend returned HTTP 502` — Vite proxy didn't reach backend; check `E2E_BACKEND_PORT` matches backend start port.
- `error: Missing required query param: otlpAuth` — URL encoding issue; verify `urlencode()` output.

- [ ] **Step 3: Commit**

```bash
git add tests/e2e/test_browser_trace_e2e.py
git commit -m "test(e2e): browser distributed trace linkage via Playwright + Vite proxy"
```

---

## Task 4: Wire into CI and Verify Quality Gates

**Files:**
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Add playwright install to the openobserve-e2e CI job**

In `.github/workflows/ci.yml`, find the `openobserve-e2e` job's steps. After `- run: npm ci` (working-directory: typescript), add:

```yaml
      - run: uv run python -m playwright install --with-deps chromium
```

The `--with-deps` flag also installs Chromium's system library dependencies on Linux (required on fresh Ubuntu runners).

Full updated steps sequence for the openobserve-e2e job:
```yaml
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - uses: actions/setup-node@v4
        with:
          node-version: "22"
          cache: npm
          cache-dependency-path: typescript/package-lock.json
      - run: npm ci
        working-directory: typescript
      - run: uv sync --group dev --extra otel
      - run: uv run python -m playwright install --with-deps chromium
      - name: Run OpenObserve E2E
        run: |
          if [ -z "${OPENOBSERVE_URL}" ] || [ -z "${OPENOBSERVE_USER}" ] || [ -z "${OPENOBSERVE_PASSWORD}" ]; then
            echo "OPENOBSERVE_* not configured; skipping e2e run."
            exit 0
          fi
          uv run python scripts/run_pytest_gate.py -m e2e --no-cov -q
```

- [ ] **Step 2: Confirm the default test suite is unaffected**

```bash
cd /Users/tim/code/gh/provide-io/provide-telemetry
uv run python scripts/run_pytest_gate.py 2>&1 | tail -3
```

Expected: `Required test coverage of 100% reached. Total coverage: 100.00%` and `1144 passed`.
The new e2e test is excluded by the default `-m "not e2e"` filter.

- [ ] **Step 3: Confirm SPDX headers on new Python file**

```bash
uv run python scripts/check_spdx_headers.py
```

Expected: `SPDX header check passed: all Python files are compliant.`

- [ ] **Step 4: Confirm REUSE compliance**

```bash
uvx reuse lint 2>&1 | tail -3
```

Expected: `Congratulations! Your project is compliant...`

If `CHANGELOG.md` or `SECURITY.md` are flagged and you haven't updated REUSE.toml in Task 2 yet, do it now:
```toml
path = [
  "README.md",
  "CLAUDE.md",
  "CHANGELOG.md",
  "SECURITY.md",
  "docs/**",
  ...
```

- [ ] **Step 5: Confirm TypeScript gates unaffected**

```bash
cd /Users/tim/code/gh/provide-io/provide-telemetry/typescript
npm run test:coverage 2>&1 | grep -E "Tests |All files"
```

Expected: `Tests  763 passed (763)` and `All files | 100 | 100 | 100 | 100 |`

- [ ] **Step 6: Final commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add playwright chromium install to openobserve-e2e job"
```

---

## Self-Review

**Spec coverage:**
- ✅ Real Chromium browser (not Node.js) — `p.chromium.launch(headless=True)` in Task 3
- ✅ Vite dev server serves the page — `vite.e2e.config.ts` with `root: 'e2e-browser'` in Task 1
- ✅ Imports `@provide-io/telemetry` as live TypeScript — `browser_tracer.ts` imports from `../src/index.js` in Task 1
- ✅ Creates a root OTel span — `tracer.startActiveSpan('browser.e2e.cross_language_request', ...)` in Task 1
- ✅ Injects W3C traceparent into fetch — `traceparent = \`00-${traceId}-${spanId}-01\`` in Task 1
- ✅ Fetch call to Python backend — `/backend/traced` (proxied via Vite) in Task 1
- ✅ Force-flushes — `shutdownTelemetry()` in Task 1
- ✅ pytest orchestrates all three processes — `subprocess.Popen` × 2 + `sync_playwright()` in Task 3
- ✅ Polls OpenObserve — `_search_total()` with 30s window in Task 3
- ✅ Verifies two spans share `trace_id` — `span_count >= 2` assertion in Task 3
- ✅ Browser ESM context — Vite serves as ESM, `<script type="module">` in Task 1
- ✅ CORS handled — Vite proxy routes `/v1` (OTLP) and `/backend` (Python) same-origin in Task 1
- ✅ No AsyncLocalStorage (browser context) — span obtained directly from `startActiveSpan` callback, no `getActiveSpan()` in Task 1

**Placeholder scan:** All steps contain complete code. No TBDs.

**Type consistency:**
- `_search_total` signature in Task 3 matches exactly the same helper in the existing `test_cross_language_trace_e2e.py`
- `TelemetryConfig` fields in `browser_tracer.ts` match `typescript/src/config.ts` interface field-for-field
- `startActiveSpan` callback signature: `(span) => Promise<void>` — span has `.spanContext()` returning `{ traceId: string, spanId: string }`
