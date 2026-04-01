// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of Provide Telemetry.

/**
 * Emit all signal types (logs, traces, metrics) to OpenObserve via OTLP HTTP.
 *
 * Required env vars:
 *   OPENOBSERVE_URL      e.g. http://localhost:5080/api/default
 *   OPENOBSERVE_USER     e.g. admin@provide.test
 *   OPENOBSERVE_PASSWORD e.g. Complexpass#123
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
  event,
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

async function sendJsonLog(baseUrl: string, auth: string, runId: string): Promise<void> {
  const parsed = new URL(`${baseUrl}/default/_json`);
  const payload = Buffer.from(
    JSON.stringify([{ _timestamp: Date.now() * 1000, event: 'example.openobserve.jsonlog', run_id: runId, message: 'openobserve json log ingestion' }]),
  );
  const mod = parsed.protocol === 'https:' ? https : http;
  await new Promise<void>((resolve, reject) => {
    const req = mod.request(
      { hostname: parsed.hostname, port: parsed.port, path: parsed.pathname, method: 'POST',
        headers: { Authorization: auth, 'Content-Type': 'application/json', 'Content-Length': payload.length } },
      (res) => {
        const chunks: Buffer[] = [];
        res.on('data', (c: Buffer) => chunks.push(c));
        res.on('end', () => {
          const body = Buffer.concat(chunks).toString('utf8');
          if ((res.statusCode ?? 0) >= 400) reject(new Error(`JSON log POST failed ${res.statusCode}: ${body}`));
          else resolve();
        });
      },
    );
    req.on('error', reject);
    req.write(payload);
    req.end();
  });
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

  log.info({ ...event('example', 'openobserve', 'start'), run_id: runId });

  for (let i = 0; i < 5; i++) {
    const start = Date.now();
    await withTrace(traceName, async () => {
      log.info({ event: 'example.openobserve.log', run_id: runId, iteration: String(i) });
      requestsCounter.add(1, { iteration: String(i) });
      await new Promise((r) => setTimeout(r, 50));
    });
    latencyHistogram.record(Date.now() - start, { iteration: String(i) });
  }

  log.info({ ...event('example', 'openobserve', 'done'), run_id: runId, iterations: 5 });

  // ── Flush and shutdown ───────────────────────────────────────────────────

  await shutdownTelemetry();

  await sendJsonLog(baseUrl, auth, runId);
  console.log(`signals emitted run_id=${runId}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
