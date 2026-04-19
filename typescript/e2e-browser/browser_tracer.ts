// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
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

import {
  getConfig,
  registerOtelProviders,
  setupTelemetry,
  shutdownTelemetry,
} from '../src/index.js';
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
  // Pass the merged config (cfg above is a Partial<TelemetryConfig> overlay
  // that is missing required defaults like tracingEnabled). setupTelemetry
  // stores the merged result; getConfig() returns it. Using cfg directly
  // here would leave tracingEnabled undefined and skip provider registration
  // entirely, so trace.getTracer() would return a no-op ProxyTracer and the
  // emitted traceparent would be all-zero.
  await registerOtelProviders(getConfig());

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
