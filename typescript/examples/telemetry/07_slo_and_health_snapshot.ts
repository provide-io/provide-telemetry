#!/usr/bin/env npx tsx
// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of Provide Telemetry.

/**
 * 📊 SLO metrics pack and health snapshot inspection.
 *
 * Demonstrates:
 * - recordRedMetrics for HTTP request/error/duration (RED pattern)
 * - recordUseMetrics for resource utilization (USE pattern)
 * - classifyError for error taxonomy (server / client / none)
 * - getHealthSnapshot with all fields
 *
 * Run: npx tsx examples/telemetry/07_slo_and_health_snapshot.ts
 */

import {
  classifyError,
  event,
  getHealthSnapshot,
  getLogger,
  recordRedMetrics,
  recordUseMetrics,
  setupTelemetry,
  shutdownTelemetry,
} from '../../src/index.js';

async function main(): Promise<void> {
  console.log('📊 SLO Metrics & Health Snapshot Demo\n');

  setupTelemetry({ serviceName: 'provide-telemetry-examples', consoleOutput: false });
  const log = getLogger('examples.slo');

  // ── 🟢 Successful requests ──────────────────────────────
  console.log('🟢 Recording successful HTTP requests...');
  recordRedMetrics({ route: '/matchmaking', method: 'POST', statusCode: 200, durationMs: 18.2 });
  recordRedMetrics({ route: '/matchmaking', method: 'GET', statusCode: 200, durationMs: 5.1 });
  recordRedMetrics({ route: '/leaderboard', method: 'GET', statusCode: 200, durationMs: 12.7 });
  console.log('  ✅ 3 requests recorded (POST + 2x GET)');

  // ── 🔴 Server errors ────────────────────────────────────
  console.log('\n🔴 Recording server errors...');
  recordRedMetrics({ route: '/matchmaking', method: 'POST', statusCode: 503, durationMs: 210.5 });
  recordRedMetrics({ route: '/inventory', method: 'PUT', statusCode: 500, durationMs: 45.0 });
  console.log('  💥 2 errors recorded (503 + 500)');

  // ── 📈 Resource utilization (USE) ────────────────────────
  console.log('\n📈 Recording resource utilization...');
  recordUseMetrics({ resource: 'cpu', utilization: 61 });
  recordUseMetrics({ resource: 'memory', utilization: 78 });
  recordUseMetrics({ resource: 'disk_io', utilization: 23 });
  console.log('  🖥️  cpu=61%  |  🧠 memory=78%  |  💾 disk_io=23%');

  // ── 🏷️ Error taxonomy ────────────────────────────────────
  console.log('\n🏷️  Error taxonomy classification:');
  const cases: [string, number][] = [
    ['UpstreamTimeout', 503],
    ['InvalidPayload', 400],
    ['NullPointerError', 200],
  ];
  for (const [excName, code] of cases) {
    const taxonomy = classifyError(excName, code);
    const icon: Record<string, string> = { server: '🔴', client: '🟡', unknown: '⚫' };
    console.log(
      `  ${icon[taxonomy.errorType] ?? '❓'} ${excName}(status=${code}) → type=${taxonomy.errorType}, code=${taxonomy.errorCode}`,
    );
    if (code === 503) {
      log.error({ ...event('example', 'slo', 'error'), excName, statusCode: code, ...taxonomy });
    }
  }

  // ── 🩺 Full health snapshot ──────────────────────────────
  console.log('\n🩺 Full HealthSnapshot:');
  const s = getHealthSnapshot();
  console.log(`  📉 Dropped:         logs=${s.logsDropped}  traces=${s.tracesDropped}  metrics=${s.metricsDropped}`);
  console.log(`  📦 Emitted:         logs=${s.logsEmitted}  traces=${s.tracesEmitted}  metrics=${s.metricsEmitted}`);
  console.log(`  🔄 exportRetries:   ${s.exportRetries}`);
  console.log(`  ❌ exportFailures:  ${s.exportFailures}`);
  console.log(`  ⚠️  asyncBlockingRisk: ${s.asyncBlockingRisk}`);
  console.log(`  🔬 exemplarUnsupported: ${s.exemplarUnsupported}`);
  console.log(`  💬 lastExportError: ${s.lastExportError}`);
  console.log(`  ⏱️  exportLatencyMs: ${s.exportLatencyMs}`);

  console.log('\n🏁 Done!');
  await shutdownTelemetry();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
