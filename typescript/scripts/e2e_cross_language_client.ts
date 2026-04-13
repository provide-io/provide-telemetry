// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
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

import { trace } from '@opentelemetry/api';

import { setupTelemetry, registerOtelProviders, withTrace, getActiveTraceIds } from '../src/index';

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

  // registerOtelProviders installs the AsyncLocalStorageContextManager so
  // startActiveSpan propagates spans through async boundaries automatically.
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

  // Force-flush: drain the BatchSpanProcessor and shut down.
  // trace.getTracerProvider() returns a ProxyTracerProvider; the real BasicTracerProvider
  // (which has forceFlush/shutdown) is accessible via getDelegate().
  const proxy = trace.getTracerProvider() as { getDelegate?: () => unknown };
  const provider = (proxy.getDelegate?.() ?? proxy) as {
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
