// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * OpenObserve integration example — mirrors Python examples/openobserve/01_emit_all_signals.py
 *
 * Sends traces, metrics, and logs to a local OpenObserve instance via OTLP HTTP.
 *
 * Required env vars:
 *   OPENOBSERVE_URL      e.g. http://localhost:5080/api/default
 *   OPENOBSERVE_USER     e.g. tim@provide.io
 *   OPENOBSERVE_PASSWORD e.g. password
 *
 * Run:
 *   OPENOBSERVE_URL=http://localhost:5080/api/default \
 *   OPENOBSERVE_USER=tim@provide.io \
 *   OPENOBSERVE_PASSWORD=password \
 *   npx tsx examples/openobserve.ts
 */

import {
  BasicTracerProvider,
  BatchSpanProcessor,
  SimpleSpanProcessor,
} from '@opentelemetry/sdk-trace-base';
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-http';
import { MeterProvider, PeriodicExportingMetricReader } from '@opentelemetry/sdk-metrics';
import { OTLPMetricExporter } from '@opentelemetry/exporter-metrics-otlp-http';
import { resourceFromAttributes } from '@opentelemetry/resources';
import { context, metrics, trace } from '@opentelemetry/api';
import { AsyncLocalStorageContextManager } from '@opentelemetry/context-async-hooks';

import { bindContext, counter, getLogger, histogram, setupTelemetry, withTrace } from '../src/index.js';

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
  const runId = String(Date.now());

  const otlpHeaders = { Authorization: auth };

  // ── OTEL SDK setup ──────────────────────────────────────────────────────────

  // Context manager — required for correct async span propagation
  const ctxMgr = new AsyncLocalStorageContextManager();
  ctxMgr.enable();
  context.setGlobalContextManager(ctxMgr);

  // Tracing
  const traceExporter = new OTLPTraceExporter({
    url: `${baseUrl}/v1/traces`,
    headers: otlpHeaders,
  });
  const tracerProvider = new BasicTracerProvider({
    resource: resourceFromAttributes({
      'service.name': 'undef-telemetry-ts-examples',
      'service.version': '0.1.0',
      'deployment.environment': 'development',
    }),
    // SimpleSpanProcessor exports each span immediately (synchronously after span.end())
    spanProcessors: [new SimpleSpanProcessor(traceExporter)],
  });
  trace.setGlobalTracerProvider(tracerProvider);

  // Metrics
  const metricExporter = new OTLPMetricExporter({
    url: `${baseUrl}/v1/metrics`,
    headers: otlpHeaders,
  });
  const meterProvider = new MeterProvider({
    resource: resourceFromAttributes({ 'service.name': 'undef-telemetry-ts-examples' }),
    readers: [new PeriodicExportingMetricReader({ exporter: metricExporter, exportIntervalMillis: 1000 })],
  });
  metrics.setGlobalMeterProvider(meterProvider);

  // ── @undef/telemetry setup ──────────────────────────────────────────────────

  setupTelemetry({
    serviceName: 'undef-telemetry-ts-examples',
    logLevel: 'debug',
    captureToWindow: false,
    consoleOutput: true,
  });

  bindContext({ run_id: runId, example: 'openobserve' });

  const log = getLogger('examples.openobserve');
  const requestsCounter = counter(`example.openobserve.requests.${runId}`, { unit: 'request' });
  const latencyHistogram = histogram(`example.openobserve.latency.${runId}`, { unit: 'ms' });

  // ── Emit signals ────────────────────────────────────────────────────────────

  log.info({ event: 'example.openobserve.start', run_id: runId });

  for (let i = 0; i < 5; i++) {
    const start = Date.now();

    await withTrace(`example.openobserve.work.${runId}`, async () => {
      log.info({
        event: 'example.openobserve.iteration',
        iteration: i,
        run_id: runId,
      });
      requestsCounter.add(1, { iteration: String(i) });
      await new Promise((resolve) => setTimeout(resolve, 50));
    });

    latencyHistogram.record(Date.now() - start, { iteration: String(i) });
  }

  log.info({ event: 'example.openobserve.done', run_id: runId, iterations: 5 });

  // ── Flush and shutdown ──────────────────────────────────────────────────────

  // Force flush before shutdown
  await tracerProvider.forceFlush();
  await meterProvider.forceFlush();
  await new Promise((resolve) => setTimeout(resolve, 1000)); // let exporters drain

  await tracerProvider.shutdown();
  await meterProvider.shutdown();

  console.log(`\nrun_id=${runId}`);
  console.log(`Check OpenObserve at ${baseUrl.replace('/api/default', '')}:`);
  console.log(`  Traces:  stream "default" → search for run_id="${runId}"`);
  console.log(`  Metrics: stream "default" → search for run_id="${runId}"`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
