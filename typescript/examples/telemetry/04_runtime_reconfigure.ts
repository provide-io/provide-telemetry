// SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of Undef Telemetry.

/**
 * 🔄 Runtime reconfiguration — hot-swap config without restart.
 *
 * Demonstrates:
 * - getRuntimeConfig / updateRuntimeConfig for hot updates
 * - reconfigureTelemetry for provider-safe reconfiguration
 * - reloadRuntimeFromEnv to re-read environment variables
 * - ConfigurationError when attempting to change OTEL provider fields post-init
 *
 * Run: npx tsx examples/telemetry/04_runtime_reconfigure.ts
 */

import {
  ConfigurationError,
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

  setupTelemetry({ serviceName: 'undef-telemetry-examples', logLevel: 'info', consoleOutput: false });
  const log = getLogger('examples.runtime');

  // ── 📊 Inspect current config ────────────────────────
  const cfgBefore = getRuntimeConfig();
  console.log(`📊 Before: serviceName=${cfgBefore.serviceName}  logLevel=${cfgBefore.logLevel}`);

  log.info({ event: 'example.runtime.before' });

  // ── 🔧 Hot-swap log level ─────────────────────────────
  console.log('\n🔧 Hot-swapping logLevel to warn...');
  updateRuntimeConfig({ logLevel: 'warn' });
  const cfgAfter = getRuntimeConfig();
  console.log(`  ✅ After update: logLevel=${cfgAfter.logLevel}`);

  log.info({ event: 'example.runtime.dropped' }); // suppressed at warn level

  // ── ♻️ Non-breaking reconfigure ──────────────────────
  console.log('\n♻️  reconfigureTelemetry() — safe reconfigure (no provider change)...');
  reconfigureTelemetry({ logLevel: 'info', serviceName: 'undef-telemetry-examples-v2' });
  const cfgRestarted = getRuntimeConfig();
  console.log(`  ✅ Reconfigured: serviceName=${cfgRestarted.serviceName}  logLevel=${cfgRestarted.logLevel}`);

  log.info({ event: 'example.runtime.reconfigured' });

  // ── 🌍 Reload from environment ───────────────────────
  console.log('\n🌍 reloadRuntimeFromEnv() — re-reads process.env...');
  reloadRuntimeFromEnv();
  const cfgReloaded = getRuntimeConfig();
  console.log(`  ✅ Reloaded: logLevel=${cfgReloaded.logLevel}`);

  // ── 🚫 ConfigurationError on provider-changing fields ──
  console.log('\n🚫 Attempting to change otelEnabled after providers registered...');
  // Simulate providers being registered by marking them (normally done by registerOtelProviders)
  // This is commented out in this example since we don't want to actually register providers:
  //   import { _markProvidersRegistered } from '../../src/runtime.js';
  //   _markProvidersRegistered();
  //   try { reconfigureTelemetry({ otelEnabled: true }); }
  //   catch (err) { ... }
  // Instead, show the error class is catchable:
  try {
    throw new ConfigurationError('Cannot change OTEL provider config after providers are initialized');
  } catch (err) {
    if (err instanceof ConfigurationError) {
      console.log(`  💥 ConfigurationError: ${err.message}`);
    }
  }

  console.log('\n🏁 Done!');
  await shutdownTelemetry();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
