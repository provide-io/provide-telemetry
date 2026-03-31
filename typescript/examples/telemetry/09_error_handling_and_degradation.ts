// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of Provide Telemetry.

/**
 * 🛡️ Error handling, graceful degradation, and diagnostic logging.
 *
 * Demonstrates:
 * - TelemetryError hierarchy for structured exception handling
 * - ConfigurationError for invalid/post-init config changes
 * - EventSchemaError for invalid event names
 * - Catching all telemetry errors with a single catch clause
 * - Graceful degradation without OTEL SDK (noop instruments)
 * - Diagnostic sampling-rate clamping via setSamplingPolicy
 *
 * Run: npx tsx examples/telemetry/09_error_handling_and_degradation.ts
 */

import {
  ConfigurationError,
  EventSchemaError,
  TelemetryError,
  counter,
  eventName,
  getHealthSnapshot,
  getLogger,
  setSamplingPolicy,
  setupTelemetry,
  shutdownTelemetry,
  withTrace,
} from '../../src/index.js';

async function main(): Promise<void> {
  console.log('🛡️  Error Handling & Graceful Degradation Demo\n');

  // ── ⚙️  Normal setup — works with or without OTEL ────────
  console.log('⚙️  Setting up telemetry (works with or without OTEL SDK)...');
  setupTelemetry({ serviceName: 'provide-telemetry-examples', consoleOutput: false });
  const log = getLogger('examples.errors');
  console.log('  ✅ Setup complete\n');

  // ── 🎯 Exception hierarchy ───────────────────────────────
  console.log('🎯 Exception Hierarchy Demo\n');

  // ConfigurationError
  console.log('  1️⃣  ConfigurationError:');
  try {
    throw new ConfigurationError('Cannot change OTEL provider config after initialization');
  } catch (err) {
    if (err instanceof ConfigurationError) {
      console.log(`     Caught ConfigurationError: ${err.message}`);
      console.log(`     Is TelemetryError? ${err instanceof TelemetryError}`);
      console.log(`     Is Error?          ${err instanceof Error}`);
    }
  }

  // EventSchemaError — bad event names
  console.log('\n  2️⃣  EventSchemaError (invalid event name):');
  try {
    eventName('only_one_segment');
  } catch (err) {
    if (err instanceof EventSchemaError) {
      console.log(`     Caught EventSchemaError: ${err.message}`);
      console.log(`     Is TelemetryError? ${err instanceof TelemetryError}`);
    }
  }

  try {
    eventName('BAD', 'UPPER', 'case');
  } catch (err) {
    if (err instanceof EventSchemaError) {
      console.log(`     Caught EventSchemaError: ${err.message}`);
    }
  }

  // Catch-all with TelemetryError
  console.log('\n  3️⃣  Catch-all with TelemetryError:');
  let errorsCaught = 0;
  const badInputs: string[][] = [
    ['x'],                            // too few segments
    ['A', 'B', 'C'],                  // uppercase
    ['a', 'b', 'c', 'd', 'e', 'f'],  // too many segments
  ];
  for (const segs of badInputs) {
    try {
      eventName(...segs);
    } catch (err) {
      if (err instanceof TelemetryError) errorsCaught++;
    }
  }
  console.log(`     Caught ${errorsCaught} errors with single 'catch (err instanceof TelemetryError)'`);

  // Valid names still work
  console.log('\n  4️⃣  Valid event names:');
  const name3 = eventName('auth', 'login', 'success');
  const name4 = eventName('payment', 'subscription', 'renewal', 'success');
  const name5 = eventName('game', 'match', 'round', 'score', 'submitted');
  console.log(`     3-seg: ${name3}`);
  console.log(`     4-seg: ${name4}`);
  console.log(`     5-seg: ${name5}`);

  // ── 🔇 Graceful degradation ─────────────────────────────
  console.log('\n🔇 Graceful Degradation Demo\n');

  // Metrics work without OTEL — OTEL API returns noop instruments
  const c = counter('example.errors.requests', { description: 'Demo counter' });
  c.add(5, { route: '/api/test' });
  console.log('  ✅ counter.add(5) works without OTEL SDK — noop instrument');

  // Tracing works — uses NoopSpan when OTEL isn't configured
  const result = await withTrace('example.errors.traced_work', async () => 'completed');
  console.log(`  ✅ withTrace works without OTEL SDK: result=${JSON.stringify(result)}`);

  // Logging always works
  log.info({ event: 'example.errors.degradation_test', status: 'ok' });
  console.log('  ✅ Structured logging always works');

  // Health snapshot shows the state
  const health = getHealthSnapshot();
  console.log(`  📊 Health: exportFailures=${health.exportFailures}, logsDropped=${health.logsDropped}`);

  // ── ⚠️  Sampling rate clamping diagnostic ────────────────
  console.log('\n⚠️  Sampling rate clamping (rate clamped to [0,1]):\n');

  setSamplingPolicy({ defaultRate: 1.5 });
  console.log('  1️⃣  Set rate=1.5 → clamped to 1.0');

  setSamplingPolicy({ defaultRate: -0.5 });
  console.log('  2️⃣  Set rate=-0.5 → clamped to 0.0');

  setSamplingPolicy({ defaultRate: 1.0 }); // restore

  console.log('\n🏁 Done!');
  await shutdownTelemetry();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
