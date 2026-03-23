// SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of Undef Telemetry.

/**
 * 🎲 Sampling policies and backpressure queue controls.
 *
 * Demonstrates:
 * - SamplingPolicy with defaultRate and per-key overrides
 * - setSamplingPolicy / getSamplingPolicy / shouldSample
 * - QueuePolicy with per-signal maxSize limits
 * - setQueuePolicy / getQueuePolicy / tryAcquire / release
 * - getHealthSnapshot: dropped counts
 *
 * Run: npx tsx examples/telemetry/03_sampling_and_backpressure.ts
 */

import {
  counter,
  getHealthSnapshot,
  getLogger,
  getQueuePolicy,
  getSamplingPolicy,
  release,
  setQueuePolicy,
  setSamplingPolicy,
  setupTelemetry,
  shouldSample,
  shutdownTelemetry,
  tryAcquire,
  withTrace,
} from '../../src/index.js';

async function tracedWork(taskId: number): Promise<void> {
  await withTrace('example.sampling.concurrent', async () => {
    await new Promise((r) => setTimeout(r, 15));
    counter('example.sampling.counter').add(1, { task_id: String(taskId) });
  });
}

async function run(): Promise<void> {
  const log = getLogger('examples.sampling');

  // ── 🎲 Sampling policies with overrides ─────────────────
  console.log('🎲 Setting sampling policies...');
  setSamplingPolicy({ defaultRate: 0.0, overrides: { 'example.critical': 1.0 } });

  const logsPolicy = getSamplingPolicy();
  console.log(`  📋 defaultRate=${logsPolicy.defaultRate}, overrides=${JSON.stringify(logsPolicy.overrides)}`);

  // ── 🎯 shouldSample with overrides ─────────────────────
  console.log('\n🎯 shouldSample() decisions:');
  for (const key of ['example.routine', 'example.critical']) {
    const sampled = shouldSample(key);
    const icon = sampled ? '✅' : '❌';
    console.log(`  ${icon} ${key}: sampled=${sampled}`);
  }

  // Reset to full sampling for the work below
  setSamplingPolicy({ defaultRate: 1.0 });

  // ── 🚧 Backpressure queue limits ────────────────────────
  console.log('\n🚧 Setting queue policy (maxTraces=1)...');
  setQueuePolicy({ maxLogs: 0, maxMetrics: 0, maxTraces: 1 });
  const qp = getQueuePolicy();
  console.log(`  📋 Queue policy: logs=${qp.maxLogs}, traces=${qp.maxTraces}, metrics=${qp.maxMetrics}`);

  // ── tryAcquire / release demo ───────────────────────────
  console.log('\n🔑 tryAcquire / release demo (maxTraces=1):');
  const ticket1 = tryAcquire('traces');
  const ticket2 = tryAcquire('traces'); // should be null — at capacity
  console.log(`  ticket1=${ticket1 !== null ? `token=${ticket1.token}` : 'null'}`);
  console.log(`  ticket2=${ticket2 !== null ? `token=${ticket2.token}` : 'null (backpressure applied)'}`);
  if (ticket1) release(ticket1);
  console.log('  released ticket1');
  const ticket3 = tryAcquire('traces'); // should succeed now
  console.log(`  ticket3=${ticket3 !== null ? `token=${ticket3.token} (slot freed)` : 'null'}`);
  if (ticket3) release(ticket3);

  // ── ⚡ Concurrent traced work ──────────────────────────
  console.log('\n⚡ Launching 5 concurrent traced tasks...');
  setQueuePolicy({ maxLogs: 0, maxMetrics: 0, maxTraces: 0 }); // unlimited
  await Promise.all(Array.from({ length: 5 }, (_, i) => tracedWork(i)));
  console.log('  ✅ All tasks completed');

  // This event is sampled out (rate=0 override was reset, logs rate=1 now).
  log.info({ event: 'example.sampling.done' });

  // ── 📊 Health snapshot ──────────────────────────────────
  console.log('\n📊 Health snapshot:');
  const snapshot = getHealthSnapshot();
  console.log(`  📉 logsDropped:    ${snapshot.logsDropped}`);
  console.log(`  📉 tracesDropped:  ${snapshot.tracesDropped}`);
  console.log(`  📉 metricsDropped: ${snapshot.metricsDropped}`);

  console.log('\n🏁 Done!');
}

async function main(): Promise<void> {
  console.log('🎲 Sampling & Backpressure Demo\n');
  setupTelemetry({ serviceName: 'undef-telemetry-examples', consoleOutput: false });
  await run();
  await shutdownTelemetry();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
