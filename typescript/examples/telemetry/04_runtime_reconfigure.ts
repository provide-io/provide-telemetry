#!/usr/bin/env npx tsx
// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of Provide Telemetry.

/**
 * 🔄 Runtime reconfiguration — hot-swap config without restart.
 *
 * Demonstrates:
 * - getRuntimeConfig / updateRuntimeConfig for hot updates
 * - reconfigureTelemetry for provider-safe reconfiguration
 * - reloadRuntimeFromEnv to re-read environment variables
 * - provider-changing OTEL fields requiring restart after live registration
 *
 * Run: npx tsx examples/telemetry/04_runtime_reconfigure.ts
 */

import {
  event,
  getHealthSnapshot,
  getLogger,
  getRuntimeConfig,
  reconfigureTelemetry,
  reloadRuntimeFromEnv,
  setupTelemetry,
  shutdownTelemetry,
  updateRuntimeConfig,
} from '../../src/index.js';

async function main(): Promise<void> {
  console.log('🔄 Runtime Reconfiguration Demo\n');

  setupTelemetry({ serviceName: 'provide-telemetry-examples', logLevel: 'info', consoleOutput: false });
  const log = getLogger('examples.runtime');

  // ── 📊 Inspect current config ────────────────────────
  const cfgBefore = getRuntimeConfig();
  console.log(`📊 Before: serviceName=${cfgBefore.serviceName}  logLevel=${cfgBefore.logLevel}`);

  log.info({ ...event('example', 'runtime', 'before') });

  // ── 🔧 Hot-swap log level ─────────────────────────────
  console.log('\n🔧 Hot-swapping logLevel to warn...');
  updateRuntimeConfig({ logLevel: 'warn' });
  const cfgAfter = getRuntimeConfig();
  console.log(`  ✅ After update: logLevel=${cfgAfter.logLevel}`);

  log.info({ ...event('example', 'runtime', 'dropped') }); // suppressed at warn level

  // ── ♻️ Non-breaking reconfigure ──────────────────────
  console.log('\n♻️  reconfigureTelemetry() — safe reconfigure (no provider change)...');
  reconfigureTelemetry({ logLevel: 'info', serviceName: 'provide-telemetry-examples-v2' });
  const cfgRestarted = getRuntimeConfig();
  console.log(`  ✅ Reconfigured: serviceName=${cfgRestarted.serviceName}  logLevel=${cfgRestarted.logLevel}`);

  log.info({ ...event('example', 'runtime', 'reconfigured') });

  const healthAfter = getHealthSnapshot();
  console.log(`  📊 Health after reconfigure: logsDropped=${healthAfter.logsDropped} exportFailuresLogs=${healthAfter.exportFailuresLogs}`);

  // ── 🌍 Reload from environment ───────────────────────
  console.log('\n🌍 reloadRuntimeFromEnv() — re-reads process.env hot fields only...');
  reloadRuntimeFromEnv();
  const cfgReloaded = getRuntimeConfig();
  console.log(`  ✅ Reloaded: logLevel=${cfgReloaded.logLevel}`);

  // ── 🚫 Provider-changing fields after live registration ───────────────
  console.log('\n🚫 Provider-changing fields are rejected after OTEL providers are live.');
  console.log(
    '  Reconfigure with otelEnabled / otlpEndpoint / otlpHeaders only before registerOtelProviders(),',
  );
  console.log('  or restart the process and call setupTelemetry() with the new provider config.');

  console.log('\n🏁 Done!');
  await shutdownTelemetry();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
