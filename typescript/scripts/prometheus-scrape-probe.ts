// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

/**
 * Serve a counter and an observable gauge on the standalone listener until stdin closes.
 *
 * Tier 3 of the Prometheus contract: e2e/test_prometheus_scrape_e2e.py starts
 * this with OTEL_METRICS_EXPORTER=prometheus and PROVIDE_METRICS_PROMETHEUS_LISTEN=true
 * (plus a web config for the secured run), waits for "ready" on stdout, and
 * checks what a real Prometheus scraped.
 */

import {
  counter,
  getConfig,
  getHealthSnapshot,
  observableGauge,
  registerOtelProviders,
  setupTelemetry,
  shutdownTelemetry,
} from '../src/index.js';

process.env['PROVIDE_TRACE_ENABLED'] ??= 'false';
setupTelemetry({ consoleOutput: false, captureToWindow: false });
await registerOtelProviders(getConfig());
const error = getHealthSnapshot().setupError;
if (error) {
  console.error(`prometheus-scrape-probe: FAIL — ${error}`);
  process.exit(1);
}
counter('e2e.scrape.requests').add(3);
observableGauge('e2e.scrape.temperature', () => [{ value: 41.5 }], { unit: 'Cel' });
console.log('ready');
process.stdin.resume();
await new Promise<void>((done) => process.stdin.on('end', () => done()));
await shutdownTelemetry();
