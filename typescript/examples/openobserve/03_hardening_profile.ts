// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of Provide Telemetry.

/**
 * OpenObserve hardening profile — PII masking, cardinality, sampling,
 * backpressure, exporter resilience, and RED/USE SLO metrics, all active.
 *
 * Required env vars:
 *   OPENOBSERVE_URL      e.g. http://localhost:5080/api/default
 *   OPENOBSERVE_USER     e.g. admin@provide.test
 *   OPENOBSERVE_PASSWORD e.g. Complexpass#123
 *
 * Run:
 *   OPENOBSERVE_URL=http://localhost:5080/api/default \
 *   OPENOBSERVE_USER=admin@provide.test \
 *   OPENOBSERVE_PASSWORD=Complexpass#123 \
 *   npx tsx examples/openobserve/03_hardening_profile.ts
 */

import {
  eventName,
  getConfig,
  getHealthSnapshot,
  getLogger,
  recordRedMetrics,
  recordUseMetrics,
  registerCardinalityLimit,
  registerOtelProviders,
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

  // ── Hardening guardrails (before setup, so they're active from the start) ──

  registerPiiRule({ path: 'user.email', mode: 'hash' });
  registerPiiRule({ path: 'user.full_name', mode: 'truncate', truncateTo: 4 });
  registerCardinalityLimit('player_id', { maxValues: 50, ttlSeconds: 300 });

  // Per-signal sampling — matches Python's PROVIDE_SAMPLING_*_RATE=1.0
  setSamplingPolicy('logs', { defaultRate: 1.0 });
  setSamplingPolicy('traces', { defaultRate: 1.0 });
  setSamplingPolicy('metrics', { defaultRate: 1.0 });

  setQueuePolicy({ maxLogs: 0, maxMetrics: 0, maxTraces: 64 });

  // Per-signal resilience — matches Python's PROVIDE_EXPORTER_*_RETRIES=1
  setExporterPolicy('logs', { retries: 1, backoffMs: 0, failOpen: true, timeoutMs: 5000 });
  setExporterPolicy('traces', { retries: 1, backoffMs: 0, failOpen: true, timeoutMs: 5000 });
  setExporterPolicy('metrics', { retries: 1, backoffMs: 0, failOpen: true, timeoutMs: 5000 });

  // ── @provide-io/telemetry setup ───────────────────────────────────────────

  setupTelemetry({
    serviceName: 'provide-telemetry-hardening-example',
    logLevel: 'debug',
    consoleOutput: false,
    otelEnabled: true,
    otlpEndpoint: baseUrl,
    otlpHeaders: { Authorization: auth },
    environment: 'development',
    version: 'hardening',
    strictSchema: true,
  });
  await registerOtelProviders(getConfig());

  const log = getLogger('examples.openobserve.hardening');
  const tokenValue = process.env['PROVIDE_EXAMPLE_TOKEN'] ?? 'example-token-from-env';

  // ── Emit with hardening active ───────────────────────────────────────────

  for (let i = 0; i < 5; i++) {
    await withTrace(event('example', 'openobserve', 'work').event, async () => {
      log.info({
        ...event('example', 'openobserve', 'log'),
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

  await shutdownTelemetry();

  const health = getHealthSnapshot();
  console.log(JSON.stringify({ health }));
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
