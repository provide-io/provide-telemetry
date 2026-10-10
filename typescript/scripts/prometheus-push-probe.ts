// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

/**
 * Record the push_ingestion instruments and push them to Prometheus over OTLP.
 *
 * Tier 1 of the Prometheus contract: no Prometheus-specific code, only the
 * ordinary OTLP metrics exporter pointed at a Prometheus 3 OTLP receiver. The
 * instruments are listed in spec/prometheus_fixtures.yaml (push_ingestion); the
 * E2E test in e2e/test_prometheus_push_e2e.py queries them back.
 *
 * Inputs (environment):
 *   OTEL_EXPORTER_OTLP_METRICS_ENDPOINT   e.g. http://127.0.0.1:9090/api/v1/otlp/v1/metrics
 *   PROVIDE_TELEMETRY_SERVICE_NAME        becomes the Prometheus job label
 *   PROVIDE_PROM_PROBE_PREFIX             dotted metric-name prefix for this run
 */

import {
  counter,
  gauge,
  getConfig,
  histogram,
  registerOtelProviders,
  setupTelemetry,
  shutdownTelemetry,
} from '../src/index.js';

const prefix = process.env['PROVIDE_PROM_PROBE_PREFIX'];
const endpoint = process.env['OTEL_EXPORTER_OTLP_METRICS_ENDPOINT'];
if (!prefix || !endpoint) {
  console.error('prometheus-push-probe: endpoint or prefix unset');
  process.exit(2);
}

setupTelemetry({
  serviceName: process.env['PROVIDE_TELEMETRY_SERVICE_NAME'] ?? 'prometheus-push-probe',
  otelEnabled: true,
  tracingEnabled: false,
  metricsEnabled: true,
  consoleOutput: false,
  captureToWindow: false,
});
await registerOtelProviders(getConfig());

counter(`${prefix}.requests`).add(3, { route: '/a' });
histogram(`${prefix}.request.duration`, { unit: 'ms' }).record(12, { route: '/a' });
gauge(`${prefix}.cpu.utilization`, { unit: '1' }).set(1, { core: '0' });

// Shutdown drains the periodic reader, which is what puts the data on the wire.
await shutdownTelemetry();
console.error('prometheus-push-probe: OK');
