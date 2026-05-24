// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
// @vitest-environment node

/**
 * Regression: shutdownTelemetry must not hang when the OTLP logs endpoint
 * is unreachable.
 *
 * Mirrors the Python regression at
 * tests/regression/test_shutdown_unreachable_endpoint.py. The Python side
 * fixed the same class of bug (BatchLogRecordProcessor.force_flush blocking
 * indefinitely on an unreachable collector). TypeScript's shutdownTelemetry
 * previously awaited `Promise.allSettled(providers.map(p => p.forceFlush()))`
 * with no per-promise timeout, so a hanging forceFlush would hang the whole
 * shutdownTelemetry call. The fix wraps each forceFlush+shutdown pair with
 * a deadline derived from `PROVIDE_EXPORTER_LOGS_SHUTDOWN_TIMEOUT_SECONDS`.
 */

import { createServer, type Server } from 'node:net';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import {
  getConfig,
  getLogger,
  registerOtelProviders,
  resetTelemetryState,
  setupTelemetry,
  shutdownTelemetry,
} from '../../src/index.js';

async function reserveClosedPort(): Promise<number> {
  // Bind a TCP port, capture its number, then close so connects fail fast
  // with ECONNREFUSED (instead of timing out at the OS level, which would
  // mask whether our deadline actually fired).
  return new Promise<number>((resolve, reject) => {
    const server: Server = createServer();
    server.unref();
    server.listen(0, '127.0.0.1', () => {
      const addr = server.address();
      if (addr === null || typeof addr === 'string') {
        server.close();
        reject(new Error('failed to allocate a localhost port'));
        return;
      }
      const port = addr.port;
      server.close(() => resolve(port));
    });
  });
}

describe('shutdownTelemetry — unreachable OTLP logs endpoint', () => {
  beforeEach(() => {
    resetTelemetryState();
  });
  afterEach(async () => {
    await shutdownTelemetry();
    resetTelemetryState();
    delete process.env['OTEL_EXPORTER_OTLP_ENDPOINT'];
    delete process.env['OTEL_EXPORTER_OTLP_LOGS_ENDPOINT'];
    delete process.env['PROVIDE_EXPORTER_LOGS_SHUTDOWN_TIMEOUT_SECONDS'];
    delete process.env['PROVIDE_LOG_OTLP_ENABLED'];
  });

  it('returns within the deadline when the logs endpoint refuses connections', async () => {
    const port = await reserveClosedPort();
    const endpoint = `http://127.0.0.1:${port}`;

    setupTelemetry({
      serviceName: 'shutdown-unreachable-regression',
      otelEnabled: true,
      tracingEnabled: false,
      metricsEnabled: false,
      otlpEndpoint: endpoint,
      // Aggressive deadline so a regression in the bounded shutdown is
      // immediately visible. Pre-fix this would hang indefinitely; post-fix
      // the deadline forces shutdownTelemetry to return.
      exporterLogsShutdownTimeoutMs: 250,
      consoleOutput: false,
      captureToWindow: false,
    });
    await registerOtelProviders(getConfig());

    // Emit a log so the BatchLogRecordProcessor has something to flush;
    // an empty queue would let force_flush resolve instantly even without
    // the fix.
    getLogger('shutdown-unreachable-regression').info({
      event: 'shutdown_unreachable_probe',
    });

    const started = performance.now();
    await shutdownTelemetry();
    const elapsed = performance.now() - started;

    // 250ms deadline + node + GC noise. Pre-fix this would never return
    // within any bound because Promise.allSettled awaits the OTel exporter's
    // own retry chain.
    expect(elapsed).toBeLessThan(2000);
  });

  it('PROVIDE_LOG_OTLP_ENABLED=false avoids the OTLP log path entirely', async () => {
    const port = await reserveClosedPort();
    const endpoint = `http://127.0.0.1:${port}`;

    setupTelemetry({
      serviceName: 'shutdown-unreachable-disabled-regression',
      otelEnabled: true,
      tracingEnabled: false,
      metricsEnabled: false,
      otlpEndpoint: endpoint,
      // Disable the OTLP log provider — when otlpLogsEnabled=false the
      // SDK is never installed, so there's nothing to flush.
      otlpLogsEnabled: false,
      // Use the default deadline; the test asserts the path is fast on its
      // own, not because of the deadline.
      consoleOutput: false,
      captureToWindow: false,
    });
    await registerOtelProviders(getConfig());

    getLogger('shutdown-unreachable-disabled-regression').info({
      event: 'shutdown_unreachable_disabled_probe',
    });

    const started = performance.now();
    await shutdownTelemetry();
    const elapsed = performance.now() - started;

    // No OTLP log provider was registered, so flush is trivially fast.
    expect(elapsed).toBeLessThan(1000);
  });
});
