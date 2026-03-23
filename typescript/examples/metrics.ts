// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: AGPL-3.0-or-later

/**
 * Metrics — mirrors Python examples/telemetry/metrics.py
 *
 * counter / gauge / histogram are backed by @opentelemetry/api.
 * They are always safe to call — no-ops when no OTEL SDK is registered.
 *
 * Run:
 *   npx tsx examples/metrics.ts
 */

import { counter, gauge, getLogger, histogram, setupTelemetry } from '../src/index.js';

setupTelemetry({
  serviceName: 'metrics-demo',
  logLevel: 'info',
  consoleOutput: true,
  captureToWindow: false,
  // otelEnabled: true,  // uncomment to export metrics to OTLP endpoint
});

const log = getLogger('metrics-demo');

// ── Instrument definitions (create once at module level) ───────────────────────

const httpRequests = counter('http.requests', {
  description: 'Total HTTP requests handled',
  unit: 'request',
});

const activeConnections = gauge('db.connections.active', {
  description: 'Number of active database connections',
  unit: 'connection',
});

const requestDuration = histogram('http.request.duration', {
  description: 'HTTP request duration',
  unit: 'ms',
});

// ── Simulated usage ────────────────────────────────────────────────────────────

async function handleRequest(path: string, method: string): Promise<number> {
  const start = Date.now();

  httpRequests.add(1, { path, method });
  activeConnections.add(1);

  try {
    await new Promise((resolve) => setTimeout(resolve, Math.random() * 50));
    const status = 200;
    const duration = Date.now() - start;

    requestDuration.record(duration, { path, method, status: String(status) });
    log.info({ event: 'request_ok', path, method, status, duration_ms: duration });
    return status;
  } finally {
    activeConnections.add(-1);
  }
}

async function main(): Promise<void> {
  log.info({ event: 'demo_start' });

  await Promise.all([
    handleRequest('/api/users', 'GET'),
    handleRequest('/api/orders', 'POST'),
    handleRequest('/api/users/7', 'GET'),
    handleRequest('/api/products', 'GET'),
  ]);

  log.info({ event: 'demo_complete' });
}

main().catch(console.error);
