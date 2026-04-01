// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of Provide Telemetry.

/**
 * Emit all signal types (logs, traces, metrics) to OpenObserve via OTLP HTTP.
 *
 * Required env vars:
 *   OPENOBSERVE_URL      e.g. http://localhost:5080/api/default
 *   OPENOBSERVE_USER     e.g. someuserexample@provide.test
 *   OPENOBSERVE_PASSWORD e.g. password
 *
 * Optional:
 *   PROVIDE_EXAMPLE_RUN_ID  defaults to Date.now()
 *
 * Run:
 *   OPENOBSERVE_URL=http://localhost:5080/api/default \
 *   OPENOBSERVE_USER=someuserexample@provide.test \
 *   OPENOBSERVE_PASSWORD=password \
 *   npx tsx examples/openobserve/01_emit_all_signals.ts
 */

import { AsyncLocalStorageContextManager } from '@opentelemetry/context-async-hooks';
import { OTLPMetricExporter } from '@opentelemetry/exporter-metrics-otlp-http';
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-http';
import { resourceFromAttributes } from '@opentelemetry/resources';
import { MeterProvider, PeriodicExportingMetricReader } from '@opentelemetry/sdk-metrics';
import { BasicTracerProvider, SimpleSpanProcessor } from '@opentelemetry/sdk-trace-base';
import { context, metrics, trace } from '@opentelemetry/api';

import { bindContext, counter, getLogger, histogram, setupTelemetry, withTrace } from '../../src/index.js';

function requireEnv(name: string): string {
  const val = process.env[name];
  if (!val) throw new Error(`missing required env var: ${name}`);
  return val;
}

function authHeader(user: string, password: string): string {
  return `Basic ${Buffer.from(`${user}:${password}`).toString('base64')}`;
}

async function main(): Promise<void> {
  const baseUrl = requireEnv('OPENOBSERVE_URL').replace(/\/$/, '');
  const user = requireEnv('OPENOBSERVE_USER');
  const password = requireEnv('OPENOBSERVE_PASSWORD');
  const auth = authHeader(user, password);
  const runId = process.env['PROVIDE_EXAMPLE_RUN_ID'] ?? String(Date.now());

  const traceName = `example.openobserve.work.${runId}`;
  const metricName = `example.openobserve.requests.${runId}`;

  const otlpHeaders = { Authorization: auth };

  // ── OTEL SDK setup ────────────────────────────────────────────────────────

  const ctxMgr = new AsyncLocalStorageContextManager();
  ctxMgr.enable();
  context.setGlobalContextManager(ctxMgr);

  const traceExporter = new OTLPTraceExporter({ url: `${baseUrl}/v1/traces`, headers: otlpHeaders });
  const tracerProvider = new BasicTracerProvider({
    resource: resourceFromAttributes({
      'service.name': 'provide-telemetry-ts-examples',
      'service.version': '0.1.0',
      'deployment.environment': 'development',
    }),
    spanProcessors: [new SimpleSpanProcessor(traceExporter)],
  });
  trace.setGlobalTracerProvider(tracerProvider);

  const metricExporter = new OTLPMetricExporter({ url: `${baseUrl}/v1/metrics`, headers: otlpHeaders });
  const meterProvider = new MeterProvider({
    resource: resourceFromAttributes({ 'service.name': 'provide-telemetry-ts-examples' }),
    readers: [new PeriodicExportingMetricReader({ exporter: metricExporter, exportIntervalMillis: 1000 })],
  });
  metrics.setGlobalMeterProvider(meterProvider);

  // ── @provide-io/telemetry setup ───────────────────────────────────────────────

  setupTelemetry({
    serviceName: 'provide-telemetry-ts-examples',
    logLevel: 'debug',
    consoleOutput: false,
  });

  bindContext({ run_id: runId, example: 'openobserve' });

  const log = getLogger('examples.openobserve');
  const requestsCounter = counter(metricName, { unit: 'request' });
  const latencyHistogram = histogram(`example.openobserve.latency.${runId}`, { unit: 'ms' });

  // ── Emit signals ─────────────────────────────────────────────────────────

  log.info({ event: 'example.openobserve.start', run_id: runId });

  for (let i = 0; i < 5; i++) {
    const start = Date.now();
    await withTrace(traceName, async () => {
      log.info({ event: 'example.openobserve.log', iteration: String(i), run_id: runId });
      requestsCounter.add(1, { iteration: String(i) });
      await new Promise((r) => setTimeout(r, 50));
    });
    latencyHistogram.record(Date.now() - start, { iteration: String(i) });
  }

  log.info({ event: 'example.openobserve.done', run_id: runId, iterations: 5 });

  // ── Flush and shutdown ───────────────────────────────────────────────────

  await tracerProvider.forceFlush();
  await meterProvider.forceFlush();
  await new Promise((r) => setTimeout(r, 1000));
  await tracerProvider.shutdown();
  await meterProvider.shutdown();

  console.log(`signals emitted run_id=${runId}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
