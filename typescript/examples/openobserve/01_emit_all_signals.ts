// SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of Provide Telemetry.

/**
 * Emit all signal types (logs, traces, metrics) to OpenObserve via OTLP HTTP.
 *
 * Required env vars:
 *   OPENOBSERVE_URL      e.g. http://localhost:5080/api/default
 *   OPENOBSERVE_USER     e.g. admin@provide.test
 *   OPENOBSERVE_PASSWORD e.g. password
 *
 * Optional:
 *   PROVIDE_EXAMPLE_RUN_ID  defaults to Date.now()
 *
 * Run:
 *   OPENOBSERVE_URL=http://localhost:5080/api/default \
 *   OPENOBSERVE_USER=admin@provide.test \
 *   OPENOBSERVE_PASSWORD=Complexpass#123 \
 *   npx tsx examples/openobserve/01_emit_all_signals.ts
 */

import * as http from 'node:http';
import * as https from 'node:https';

import {
  bindContext,
  counter,
  getConfig,
  getLogger,
  histogram,
  registerOtelProviders,
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
  const runId = process.env['PROVIDE_EXAMPLE_RUN_ID'] ?? String(Date.now());

  const traceName = `example.openobserve.work.${runId}`;
  const metricName = `example.openobserve.requests.${runId}`;

  // ── @provide-io/telemetry setup ───────────────────────────────────────────────

  setupTelemetry({
    serviceName: 'provide-telemetry-ts-examples',
    logLevel: 'debug',
    consoleOutput: false,
    otelEnabled: true,
    otlpEndpoint: baseUrl,
    otlpHeaders: { Authorization: auth },
    environment: 'development',
    version: 'examples',
  });
  await registerOtelProviders(getConfig());

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

  await shutdownTelemetry();

  console.log(`signals emitted run_id=${runId}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
