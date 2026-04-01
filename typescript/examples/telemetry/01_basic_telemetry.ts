// SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of Provide Telemetry.

/**
 * 🚀 Basic telemetry — logging, tracing, and all three metric types.
 *
 * Demonstrates:
 * - setupTelemetry / shutdownTelemetry lifecycle
 * - getLogger for structured logging
 * - withTrace for automatic span creation
 * - counter, gauge, histogram instrument creation and recording
 * - bindContext / unbindContext / clearContext for structured fields
 *
 * Run: npx tsx examples/telemetry/01_basic_telemetry.ts
 */

import {
  bindContext,
  clearContext,
  counter,
  gauge,
  getConfig,
  getLogger,
  histogram,
  setupTelemetry,
  shutdownTelemetry,
  unbindContext,
  withTrace,
} from '../../src/index.js';

async function doWork(iteration: number): Promise<void> {
  await withTrace('example.basic.work', async () => {
    const log = getLogger('examples.basic');
    log.info({ event: 'example.basic.iteration', iteration: String(iteration) });
    counter('example.basic.requests', { description: 'Total request count' }).add(1, {
      iteration: String(iteration),
    });
    histogram('example.basic.latency_ms', { description: 'Simulated latency', unit: 'ms' }).record(
      iteration * 12.5,
      { iteration: String(iteration) },
    );
    gauge('example.basic.active_tasks', { description: 'Active task gauge', unit: '1' }).add(1);
  });
}

async function main(): Promise<void> {
  console.log('🚀 Basic Telemetry Demo\n');

  setupTelemetry({ serviceName: 'provide-telemetry-examples', consoleOutput: true });
  const cfg = getConfig();
  const log = getLogger('examples.basic');

  console.log(`⚙️  Service: ${cfg.serviceName}  |  Env: ${cfg.environment}  |  Version: ${cfg.version}`);

  // ── 📋 Structured context binding ───────────────────────
  console.log('\n📋 Binding structured context fields...');
  bindContext({ region: 'us-east-1', tier: 'premium' });
  log.info({ event: 'example.basic.start', msg: 'context is bound' });
  console.log('  ✅ Bound: region=us-east-1, tier=premium');

  // ── 🔄 Traced work loop with all metric types ──────────
  console.log('\n🔄 Running traced iterations with counter + histogram + gauge:');
  for (let i = 0; i < 3; i++) {
    await doWork(i);
    await new Promise((r) => setTimeout(r, 50));
    console.log(`  🔹 Iteration ${i}: counter +1, histogram ${i * 12.5}ms, gauge +1`);
  }

  // ── 🧹 Context cleanup ─────────────────────────────────
  console.log("\n🧹 Unbinding 'region', then clearing all context...");
  unbindContext('region');
  log.info({ event: 'example.basic.after_unbind', msg: 'region removed' });
  console.log('  🔸 Unbound: region');

  clearContext();
  log.info({ event: 'example.basic.after_clear', msg: 'all context cleared' });
  console.log('  🔸 Cleared: all context fields');

  console.log('\n🏁 Done!');
  await shutdownTelemetry();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
