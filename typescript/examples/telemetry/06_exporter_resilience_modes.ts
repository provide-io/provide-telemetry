// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of Provide Telemetry.

/**
 * 🛡️ Exporter resilience — retries, timeouts, and failure policies.
 *
 * Demonstrates:
 * - ExporterPolicy with failOpen=true vs failOpen=false
 * - timeoutMs for deadline enforcement
 * - getExporterPolicy to inspect active policy
 * - runWithResilience for resilient async exports
 * - Health snapshot: per-signal retries, exportFailures, exportLatencyMs
 *
 * Run: npx tsx examples/telemetry/06_exporter_resilience_modes.ts
 */

import {
  getCircuitState,
  getExporterPolicy,
  getHealthSnapshot,
  runWithResilience,
  setExporterPolicy,
  setupTelemetry,
  shutdownTelemetry,
  TelemetryTimeoutError,
} from '../../src/index.js';

async function main(): Promise<void> {
  console.log('🛡️  Exporter Resilience Demo\n');

  setupTelemetry({ serviceName: 'provide-telemetry-examples', consoleOutput: false });

  // ── 🟢 Fail-open: returns null on failure ────────────
  console.log('🟢 Fail-open mode (retries=1, backoffMs=0)');
  setExporterPolicy('logs', { retries: 1, backoffMs: 0, failOpen: true, timeoutMs: 0 });

  let attemptsOpen = 0;
  const result = await runWithResilience('logs', async () => {
    attemptsOpen++;
    throw new Error('simulated exporter failure');
  });
  const policy = getExporterPolicy('logs');
  console.log(`  📦 Result: ${result}`);
  console.log(`  🔄 Attempts: ${attemptsOpen}`);
  console.log(`  📋 Policy: retries=${policy.retries}, failOpen=${policy.failOpen}`);

  // ── 🔴 Fail-closed: throws on failure ────────────────
  console.log('\n🔴 Fail-closed mode (retries=1, backoffMs=0)');
  setExporterPolicy('logs', { retries: 1, backoffMs: 0, failOpen: false, timeoutMs: 0 });

  let attemptsClosed = 0;
  try {
    await runWithResilience('logs', async () => {
      attemptsClosed++;
      throw new Error('simulated hard failure');
    });
  } catch (err) {
    console.log(`  💥 Caught: ${(err as Error).message}`);
    console.log(`  🔄 Attempts: ${attemptsClosed}`);
  }

  // ── ⏱️ Timeout enforcement ────────────────────────────
  console.log('\n⏱️  Timeout enforcement (timeoutMs=50)');
  setExporterPolicy('traces', { retries: 0, timeoutMs: 50, failOpen: true });

  const timedOut = await runWithResilience('traces', async () => {
    await new Promise((r) => setTimeout(r, 200));
    return 'too late';
  });
  console.log(`  📦 Result: ${timedOut}  (null = timed out, fail-open)`);

  // ── 🔌 Circuit breaker with exponential backoff ─────────
  console.log('\n🔌 Circuit breaker (exponential backoff + half-open probing)');
  setExporterPolicy('metrics', { retries: 0, timeoutMs: 10, failOpen: true });

  for (let i = 0; i < 4; i++) {
    await runWithResilience('metrics', async () => {
      throw new TelemetryTimeoutError('simulated timeout');
    });
  }

  const circuit = getCircuitState('metrics');
  console.log(`  🔌 Circuit state:     ${circuit.state}`);
  console.log(`  📈 Open count:        ${circuit.openCount}`);
  console.log(`  ⏳ Cooldown remaining: ${(circuit.cooldownRemainingMs / 1000).toFixed(1)}s`);

  // ── 📊 Health snapshot ────────────────────────────────
  console.log('\n📊 Health snapshot after all operations:');
  const snapshot = getHealthSnapshot();
  console.log(`  🔄 retriesMetrics:          ${snapshot.retriesMetrics}`);
  console.log(`  ❌ exportFailuresMetrics:   ${snapshot.exportFailuresMetrics}`);
  console.log(`  ⏱️  exportLatencyMsMetrics: ${snapshot.exportLatencyMsMetrics}`);
  console.log(`  🔌 circuitStateMetrics: ${snapshot.circuitStateMetrics}`);
  console.log(`  📈 circuitOpenCount:    ${snapshot.circuitOpenCountMetrics}`);
  console.log(`  🛑 setupError:          ${snapshot.setupError}`);

  console.log('\n🏁 Done!');
  await shutdownTelemetry();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
