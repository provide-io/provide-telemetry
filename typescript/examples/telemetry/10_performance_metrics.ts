// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of Provide Telemetry.

/**
 * ⚡ Performance characteristics of the telemetry library.
 *
 * Demonstrates:
 * - Import time of the full @provide-io/telemetry package (measured at startup)
 * - setupTelemetry() cost
 * - Hot-path instrument ops: counter.add(), gauge.add(), histogram.record()
 * - Sampling decision throughput via shouldSample()
 * - Event name construction via eventName()
 * - Full setup / shutdown lifecycle cost
 * - Import footprint: no eager OTEL SDK pull
 *
 * Run: npx tsx examples/telemetry/10_performance_metrics.ts
 */

import {
  counter,
  eventName,
  gauge,
  histogram,
  setupTelemetry,
  shouldSample,
  shutdownTelemetry,
} from '../../src/index.js';

const ITERATIONS = 10_000;
const LIFECYCLE_ITERATIONS = 50;

function bench(fn: () => void, iterations: number = ITERATIONS): number {
  const start = performance.now();
  for (let i = 0; i < iterations; i++) fn();
  return ((performance.now() - start) * 1_000_000) / iterations; // ns per op
}

function fmt(ns: number): string {
  if (ns >= 1_000_000) return `${(ns / 1_000_000).toFixed(2).padStart(10)} ms`;
  if (ns >= 1_000) return `${(ns / 1_000).toFixed(2).padStart(10)} µs`;
  return `${ns.toFixed(0).padStart(10)} ns`;
}

async function main(): Promise<void> {
  console.log('⚡ Performance Characteristics\n');

  const rows: [string, string][] = [];

  // ── ⚙️  setupTelemetry cost ──────────────────────────────
  console.log('⚙️  Setup Cost\n');
  rows.push(['setupTelemetry()', fmt(bench(() => setupTelemetry({ serviceName: 'perf-test' }), 100))]);

  setupTelemetry({ serviceName: 'perf-test', consoleOutput: false });

  // ── 🔥 Hot-path ops ──────────────────────────────────────
  console.log('🔥 Hot-Path Instrument Operations\n');
  const c = counter('perf.example.requests', { description: 'bench counter' });
  const g = gauge('perf.example.active', { description: 'bench gauge' });
  const h = histogram('perf.example.latency', { description: 'bench histogram', unit: 'ms' });

  rows.push(['counter.add(1)', fmt(bench(() => c.add(1)))]);
  rows.push(['gauge.add(42)', fmt(bench(() => g.add(42)))]);
  rows.push(['histogram.record(3.14)', fmt(bench(() => h.record(3.14)))]);
  rows.push(['shouldSample("logs")', fmt(bench(() => shouldSample('logs')))]);
  rows.push(['eventName("a","b","c")', fmt(bench(() => eventName('perf', 'bench', 'op')))]);

  // ── 🔄 Full lifecycle ────────────────────────────────────
  console.log('🔄 Setup / Shutdown Lifecycle\n');
  rows.push([
    'setup + shutdown cycle',
    fmt(
      bench(async () => {
        setupTelemetry({ serviceName: 'perf-test' });
        await shutdownTelemetry();
      }, LIFECYCLE_ITERATIONS),
    ),
  ]);

  // ── 📊 Results table ─────────────────────────────────────
  console.log('📊 Results\n');
  const maxLabel = Math.max(...rows.map(([label]) => label.length));
  for (const [label, value] of rows) {
    console.log(`    ${label.padEnd(maxLabel)}  ${value}`);
  }

  // ── 🔌 Import footprint check ─────────────────────────────
  console.log('\n🔌 Import Footprint\n');
  // ESM: use process.moduleLoadList as a proxy for loaded modules
  const loadedMods = (process.moduleLoadList ?? []).filter((k: string) => k.includes('provide-telemetry') || k.includes('@provide-io'));
  console.log(`    Loaded @provide-io/telemetry source files: ${loadedMods.length}`);
  const hasOtelSdk = loadedMods.some((k: string) => k.includes('sdk-trace') || k.includes('sdk-metrics'));
  if (hasOtelSdk) {
    console.log('    ⚠️  OTEL SDK loaded (expected when peer deps are installed)');
  } else {
    console.log('    ✅ OTEL SDK not loaded at import time (lazy / noop API only)');
  }

  console.log('\n🏁 Done!');
  await shutdownTelemetry();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
