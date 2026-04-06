#!/usr/bin/env npx tsx
// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of Provide Telemetry.

/**
 * 🏰 Full production hardening profile — all guardrails active.
 *
 * Demonstrates a complete hardening setup combining:
 * - PII masking on sensitive fields
 * - Cardinality limits to prevent metric explosion
 * - Sampling policies with per-key overrides
 * - Backpressure queue limits
 * - Exporter resilience with fail-open policy
 * - SLO RED/USE metrics recording
 * - Runtime reconfiguration mid-flight
 * - Full HealthSnapshot inspection
 *
 * Run: npx tsx examples/telemetry/08_full_hardening_profile.ts
 */

import {
  counter,
  event,
  getHealthSnapshot,
  getLogger,
  getRuntimeConfig,
  guardAttributes,
  histogram,
  recordRedMetrics,
  recordUseMetrics,
  registerCardinalityLimit,
  registerPiiRule,
  setExporterPolicy,
  setQueuePolicy,
  setSamplingPolicy,
  setupTelemetry,
  shutdownTelemetry,
  updateRuntimeConfig,
} from '../../src/index.js';

async function main(): Promise<void> {
  console.log('🏰 Full Production Hardening Profile\n');

  setupTelemetry({ serviceName: 'provide-telemetry-hardening', consoleOutput: false });
  const log = getLogger('examples.hardening');

  // ── 🔒 PII masking ─────────────────────────────────────
  console.log('🔒 PII masking: hash emails, drop credit cards');
  registerPiiRule({ path: 'user.email', mode: 'hash' });
  registerPiiRule({ path: 'credit_card', mode: 'drop' });
  log.info({
    ...event('example', 'hardening', 'user_event'),
    user: { email: 'player@game.io', name: 'Hero' },
    credit_card: '4111111111111111',
  });
  console.log('  ✅ PII rules active');

  // ── 🚧 Cardinality limits ──────────────────────────────
  console.log('\n🚧 Cardinality limit: max 3 unique player_ids');
  registerCardinalityLimit('player_id', { maxValues: 3, ttlSeconds: 300 });
  const metric = counter('example.hardening.actions', { description: 'Player actions' });
  for (const pid of ['p1', 'p2', 'p3', 'p4', 'p5']) {
    const attrs = guardAttributes({ player_id: pid });
    metric.add(1, attrs);
    const icon = attrs['player_id'] !== pid ? '⚠️' : '✅';
    console.log(`  ${icon} player_id=${pid} → guarded=${attrs['player_id']}`);
  }

  // ── 🎲 Sampling policies ───────────────────────────────
  console.log('\n🎲 Sampling: 50% default, critical overrides=100%');
  setSamplingPolicy({ defaultRate: 0.5, overrides: { 'example.critical': 1.0 } });
  // Reset to 100% so rest of example emits all events
  setSamplingPolicy({ defaultRate: 1.0 });

  // ── 🚧 Backpressure ────────────────────────────────────
  console.log('\n🚧 Backpressure: traces queue max=2');
  setQueuePolicy({ maxLogs: 0, maxMetrics: 0, maxTraces: 2 });
  // Reset to unlimited
  setQueuePolicy({ maxLogs: 0, maxMetrics: 0, maxTraces: 0 });

  // ── 🛡️ Exporter resilience ─────────────────────────────
  console.log('\n🛡️  Exporter resilience: fail-open with 2 retries');
  setExporterPolicy({ retries: 2, backoffMs: 10, failOpen: true, timeoutMs: 1000 });

  // ── 📊 SLO RED/USE metrics ─────────────────────────────
  console.log('\n📊 Recording SLO metrics...');
  recordRedMetrics({ route: '/game/start', method: 'POST', statusCode: 200, durationMs: 22.0 });
  recordRedMetrics({ route: '/game/start', method: 'POST', statusCode: 500, durationMs: 150.0 });
  recordUseMetrics({ resource: 'cpu', utilization: 55 });
  histogram('example.hardening.latency', { description: 'Request latency', unit: 'ms' }).record(22.0);
  console.log('  ✅ RED: 2 requests (1 success, 1 error)');
  console.log('  ✅ USE: cpu=55%');

  // ── 🔧 Runtime reconfiguration ─────────────────────────
  console.log('\n🔧 Hot-swapping serviceName mid-flight...');
  const current = getRuntimeConfig();
  console.log(`  📋 Before: serviceName=${current.serviceName}`);
  updateRuntimeConfig({ serviceName: 'provide-telemetry-hardening-v2' });
  const updated = getRuntimeConfig();
  console.log(`  ✅ After:  serviceName=${updated.serviceName}`);

  // ── 🩺 Health snapshot ──────────────────────────────────
  console.log('\n🩺 Health snapshot summary:');
  const s = getHealthSnapshot();
  console.log(`  📉 Dropped:        logs=${s.logsDropped}  traces=${s.tracesDropped}  metrics=${s.metricsDropped}`);
  console.log(`  🔄 retriesLogs:            ${s.retriesLogs}`);
  console.log(`  ❌ exportFailuresLogs:     ${s.exportFailuresLogs}`);
  console.log(`  ⚠️  asyncRiskLogs:         ${s.asyncBlockingRiskLogs}`);

  console.log('\n🏁 All guardrails active — production-ready!');
  await shutdownTelemetry();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
