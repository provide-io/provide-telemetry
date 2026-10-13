#!/usr/bin/env npx tsx
// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of Provide Telemetry.

/**
 * 📈 Prometheus metrics — serve a scrape endpoint from the SDK.
 *
 * Demonstrates:
 * - Enabling the Prometheus pull reader with metricsExporters: ['prometheus']
 *   (env: OTEL_METRICS_EXPORTER=prometheus; add otlp to push as well)
 * - registerOtelProviders(), which attaches the pull reader (Node only)
 * - metricsHandler() from @provide-io/telemetry/prometheus, mounted on a
 *   node:http server (Express and Connect accept it too)
 * - A counter and a histogram with units, plus an observableGauge whose
 *   callback runs on every scrape
 * - One scrape over HTTP, showing the Prometheus names the SDK renders:
 *   dots become underscores, counters gain _total, units become suffixes
 * - The SDK's own health as provide_telemetry_* series in the same scrape
 *
 * Offline and collision-free: the server listens on 127.0.0.1 port 0, so the
 * OS picks a free port. For the SDK's own listener instead, set
 * PROVIDE_METRICS_PROMETHEUS_LISTEN=true (127.0.0.1:9464, /metrics by default).
 *
 * Run: npx tsx examples/telemetry/15_prometheus_metrics.ts
 */

import { createServer } from 'node:http';
import type { AddressInfo } from 'node:net';

import {
  counter,
  getConfig,
  histogram,
  observableGauge,
  registerOtelProviders,
  setupTelemetry,
  shutdownTelemetry,
} from '../../src/index.js';
import { metricsHandler } from '../../src/prometheus.js';

function metricNames(body: string): string[] {
  return body
    .split('\n')
    .filter((line) => line.startsWith('# TYPE '))
    .map((line) => line.split(' ')[2] ?? '');
}

async function main(): Promise<void> {
  console.log('📈 Prometheus Metrics Demo\n');

  // ── ⚙️  Enable the pull reader ─────────────────────────
  setupTelemetry({
    serviceName: 'prometheus-example',
    consoleOutput: false,
    metricsExporters: ['prometheus'],
  });
  await registerOtelProviders(getConfig());
  console.log("⚙️  metricsExporters: ['prometheus'] → pull reader attached");

  // ── 🔌 Mount the handler on the host's server ──────────
  const handler = metricsHandler();
  const server = createServer((req, res) => {
    if (req.url === '/metrics') handler(req, res);
    else res.writeHead(404).end();
  });
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  const url = `http://127.0.0.1:${(server.address() as AddressInfo).port}/metrics`;

  // ── 📊 Record instruments with units ───────────────────
  console.log('\n📊 Recording instruments:');
  counter('example.prom.requests', { description: 'Requests handled', unit: '1' }).add(3, {
    route: '/checkout',
  });
  console.log('  🔹 counter   example.prom.requests (unit 1)    +3');
  const latency = histogram('example.prom.latency', { description: 'Request latency', unit: 'ms' });
  for (const value of [12.5, 40.0, 87.5]) latency.record(value, { route: '/checkout' });
  console.log('  🔹 histogram example.prom.latency (unit ms)    12.5, 40.0, 87.5');
  const queueDepth = 7;
  const depth = observableGauge(
    'example.prom.queue_depth',
    () => [{ value: queueDepth, attributes: { queue: 'jobs' } }],
    { description: 'Jobs waiting', unit: '1' },
  );
  console.log('  🔹 observable gauge example.prom.queue_depth   callback → 7');

  // ── 🔎 One scrape over HTTP ────────────────────────────
  console.log('\n🔎 GET /metrics (loopback, ephemeral port):');
  const response = await fetch(url, { headers: { accept: 'text/plain' } });
  const body = await response.text();
  console.log(`  ✅ ${response.status}  ${response.headers.get('content-type') ?? ''}`);
  const names = metricNames(body);
  console.log(
    '\n🏷️  Your metrics, as Prometheus names them (ms → _milliseconds, 1 → _ratio, counter → _total):',
  );
  for (const name of names.filter((n) => n.startsWith('example_'))) console.log(`  🔸 ${name}`);
  console.log('\n🩺 SDK health series in the same scrape:');
  for (const name of names.filter((n) => n.startsWith('provide_telemetry_'))) {
    console.log(`  🔸 ${name}`);
  }
  const sample = body.split('\n').find((line) => line.startsWith('example_prom_queue_depth'));
  if (sample) console.log(`\n📏 Observable gauge sample: ${sample}`);

  // ── 🧹 Shutdown ────────────────────────────────────────
  depth.unregister();
  await shutdownTelemetry();
  const after = await fetch(url);
  console.log(
    `\n🧹 After shutdown the handler answers ${after.status}: ${(await after.text()).trim()}`,
  );
  await new Promise<void>((resolve) => server.close(() => resolve()));
  console.log('\n🏁 Done!');
}

main().catch((err: unknown) => {
  console.error(err);
  process.exit(1);
});
