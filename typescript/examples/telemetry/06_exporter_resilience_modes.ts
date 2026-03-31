// SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
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
 * - Health snapshot: exportRetries, exportFailures, exportLatencyMs, lastExportError
 *
 * Run: npx tsx examples/telemetry/06_exporter_resilience_modes.ts
 */

import {
  getExporterPolicy,
  getHealthSnapshot,
  runWithResilience,
  setExporterPolicy,
  setupTelemetry,
  shutdownTelemetry,
} from '../../src/index.js';

async function main(): Promise<void> {
  console.log('🛡️  Exporter Resilience Demo\n');

  setupTelemetry({ serviceName: 'provide-telemetry-examples', consoleOutput: false });

  // ── 🟢 Fail-open: returns null on failure ────────────
  console.log('🟢 Fail-open mode (retries=1, backoffMs=0)');
  setExporterPolicy({ retries: 1, backoffMs: 0, failOpen: true, timeoutMs: 0 });

  let attemptsOpen = 0;
  const result = await runWithResilience('logs', async () => {
    attemptsOpen++;
    throw new Error('simulated exporter failure');
  });
  const policy = getExporterPolicy();
  console.log(`  📦 Result: ${result}`);
  console.log(`  🔄 Attempts: ${attemptsOpen}`);
  console.log(`  📋 Policy: retries=${policy.retries}, failOpen=${policy.failOpen}`);

  // ── 🔴 Fail-closed: throws on failure ────────────────
  console.log('\n🔴 Fail-closed mode (retries=1, backoffMs=0)');
  setExporterPolicy({ retries: 1, backoffMs: 0, failOpen: false, timeoutMs: 0 });

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
  setExporterPolicy({ retries: 0, timeoutMs: 50, failOpen: true });

  const timedOut = await runWithResilience('traces', async () => {
    await new Promise((r) => setTimeout(r, 200));
    return 'too late';
  });
  console.log(`  📦 Result: ${timedOut}  (null = timed out, fail-open)`);

  // ── 📊 Health snapshot ────────────────────────────────
  console.log('\n📊 Health snapshot after all operations:');
  const snapshot = getHealthSnapshot();
  console.log(`  🔄 exportRetries:    ${snapshot.exportRetries}`);
  console.log(`  ❌ exportFailures:   ${snapshot.exportFailures}`);
  console.log(`  💬 lastExportError:  ${snapshot.lastExportError}`);
  console.log(`  ⏱️  exportLatencyMs: ${snapshot.exportLatencyMs}`);

  console.log('\n🏁 Done!');
  await shutdownTelemetry();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
