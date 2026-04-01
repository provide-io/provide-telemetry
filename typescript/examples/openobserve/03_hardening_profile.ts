// SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of Provide Telemetry.

/**
 * OpenObserve hardening profile — PII masking, cardinality, sampling,
 * backpressure, exporter resilience, and RED/USE SLO metrics, all active.
 *
 * Required env vars:
 *   OPENOBSERVE_URL      e.g. http://localhost:5080/api/default
 *   OPENOBSERVE_USER     e.g. someuserexample@provide.test
 *   OPENOBSERVE_PASSWORD e.g. password
 *
 * Run:
 *   OPENOBSERVE_URL=http://localhost:5080/api/default \
 *   OPENOBSERVE_USER=someuserexample@provide.test \
 *   OPENOBSERVE_PASSWORD=password \
 *   npx tsx examples/openobserve/03_hardening_profile.ts
 */

import { AsyncLocalStorageContextManager } from '@opentelemetry/context-async-hooks';
import { OTLPMetricExporter } from '@opentelemetry/exporter-metrics-otlp-http';
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-http';
import { resourceFromAttributes } from '@opentelemetry/resources';
import { MeterProvider, PeriodicExportingMetricReader } from '@opentelemetry/sdk-metrics';
import { BasicTracerProvider, SimpleSpanProcessor } from '@opentelemetry/sdk-trace-base';
import { context, metrics, trace } from '@opentelemetry/api';

import {
  eventName,
  getHealthSnapshot,
  getLogger,
  recordRedMetrics,
  recordUseMetrics,
  registerCardinalityLimit,
  registerPiiRule,
  setExporterPolicy,
  setQueuePolicy,
  setSamplingPolicy,
  setupTelemetry,
  shutdownTelemetry,
  withTrace,
} from '../../src/index.js';

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
  const otlpHeaders = { Authorization: auth };

  // ── OTEL SDK setup ────────────────────────────────────────────────────────

  const ctxMgr = new AsyncLocalStorageContextManager();
  ctxMgr.enable();
  context.setGlobalContextManager(ctxMgr);

  const tracerProvider = new BasicTracerProvider({
    resource: resourceFromAttributes({
      'service.name': 'provide-telemetry-hardening-example',
      'service.version': 'hardening',
    }),
    spanProcessors: [new SimpleSpanProcessor(
      new OTLPTraceExporter({ url: `${baseUrl}/v1/traces`, headers: otlpHeaders }),
    )],
  });
  trace.setGlobalTracerProvider(tracerProvider);

  const meterProvider = new MeterProvider({
    resource: resourceFromAttributes({ 'service.name': 'provide-telemetry-hardening-example' }),
    readers: [new PeriodicExportingMetricReader({
      exporter: new OTLPMetricExporter({ url: `${baseUrl}/v1/metrics`, headers: otlpHeaders }),
      exportIntervalMillis: 1000,
    })],
  });
  metrics.setGlobalMeterProvider(meterProvider);

  // ── Hardening guardrails ─────────────────────────────────────────────────

  registerPiiRule({ path: 'user.email', mode: 'hash' });
  registerPiiRule({ path: 'user.full_name', mode: 'truncate', truncateTo: 4 });
  registerCardinalityLimit('player_id', { maxValues: 50, ttlSeconds: 300 });
  setSamplingPolicy({ defaultRate: 1.0 });
  setQueuePolicy({ maxLogs: 0, maxMetrics: 0, maxTraces: 64 });
  setExporterPolicy({ retries: 1, backoffMs: 0, failOpen: true, timeoutMs: 5000 });

  // ── @provide-io/telemetry setup ───────────────────────────────────────────────

  setupTelemetry({
    serviceName: 'provide-telemetry-hardening-example',
    consoleOutput: false,
  });

  const log = getLogger('examples.openobserve.hardening');
  const tokenValue = process.env['PROVIDE_EXAMPLE_TOKEN'] ?? 'example-token-from-env';

  // ── Emit with hardening active ───────────────────────────────────────────

  for (let i = 0; i < 5; i++) {
    await withTrace(eventName('example', 'openobserve', 'work'), async () => {
      log.info({
        event: eventName('example', 'openobserve', 'log'),
        iteration: i,
        user: { email: 'ops@example.com', full_name: 'Operator Example' },
        token: tokenValue,
      });
      recordRedMetrics({ route: '/example', method: 'GET', statusCode: 200, durationMs: 10 + i });
      recordUseMetrics({ resource: 'cpu', utilization: 40 + i * 5 });
    });
    await new Promise((r) => setTimeout(r, 50));
  }

  // ── Flush and shutdown ───────────────────────────────────────────────────

  await tracerProvider.forceFlush();
  await meterProvider.forceFlush();
  await new Promise((r) => setTimeout(r, 1000));
  await tracerProvider.shutdown();
  await meterProvider.shutdown();
  await shutdownTelemetry();

  const health = getHealthSnapshot();
  console.log(JSON.stringify({ health }));
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
