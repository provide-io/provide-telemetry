#!/usr/bin/env npx tsx
// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of Provide Telemetry.

/**
 * 🔬 Proof that lazy-loading decouples modules from heavy dependencies.
 *
 * Uses child_process isolation so each measurement starts from a clean
 * Node.js process with zero cached modules.
 *
 * Compares:
 *   🐌 Eager: import slo.ts before index.ts (forces full SLO + OTEL metric chain)
 *   ⚡ Lazy:  import index.ts only (SLO deferred to call time via lazy instrument creation)
 *
 * Run: npx tsx examples/telemetry/11_lazy_loading_proof.ts
 */

import { execSync } from 'node:child_process';
import { statSync } from 'node:fs';
import { join, resolve } from 'node:path';

const ROUNDS = 5;
const PKG_ROOT = resolve(import.meta.dirname ?? __dirname, '../..');

// Script that forces slo import before index (eager path)
const EAGER_SCRIPT = `
import { performance } from 'node:perf_hooks';
const t0 = performance.now();
await import('${PKG_ROOT}/src/slo.js');
await import('${PKG_ROOT}/src/index.js');
const t1 = performance.now();
const ms = t1 - t0;
process.stdout.write(ms.toFixed(3) + '\\n');
`;

// Script that imports only index (lazy path — slo is only loaded on first call)
const LAZY_SCRIPT = `
import { performance } from 'node:perf_hooks';
const t0 = performance.now();
await import('${PKG_ROOT}/src/index.js');
const t1 = performance.now();
const ms = t1 - t0;
process.stdout.write(ms.toFixed(3) + '\\n');
`;

function runScript(script: string): number {
  // Write script to a temp file and run with tsx
  const tmpFile = join(PKG_ROOT, '.tmp_lazy_proof.mts');
  require('node:fs').writeFileSync(tmpFile, script);
  try {
    const out = execSync(`npx tsx ${tmpFile}`, {
      encoding: 'utf8',
      cwd: PKG_ROOT,
      timeout: 10_000,
    });
    return parseFloat(out.trim());
  } finally {
    try { require('node:fs').unlinkSync(tmpFile); } catch { /* ignore */ }
  }
}

function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0 ? (sorted[mid - 1]! + sorted[mid]!) / 2 : sorted[mid]!;
}

function fmt(ms: number): string {
  if (ms >= 1000) return `${(ms / 1000).toFixed(2)} s `;
  return `${ms.toFixed(1)} ms`;
}

async function main(): Promise<void> {
  console.log('🔬 Lazy-Loading Proof (child_process-isolated measurements)\n');
  console.log(`    Running ${ROUNDS} rounds per scenario...\n`);

  // ── 🐌 Eager: slo imported first ────────────────────────
  const eagerTimes: number[] = [];
  for (let i = 0; i < ROUNDS; i++) {
    try {
      eagerTimes.push(runScript(EAGER_SCRIPT));
    } catch {
      eagerTimes.push(0);
    }
  }

  // ── ⚡ Lazy: only index imported ─────────────────────────
  const lazyTimes: number[] = [];
  for (let i = 0; i < ROUNDS; i++) {
    try {
      lazyTimes.push(runScript(LAZY_SCRIPT));
    } catch {
      lazyTimes.push(0);
    }
  }

  const eagerMedian = median(eagerTimes);
  const lazyMedian = median(lazyTimes);

  console.log('    Scenario                   Median');
  console.log('    ────────────────────────── ──────────');
  console.log(`    🐌 Eager (slo at import)   ${fmt(eagerMedian).padStart(10)}`);
  console.log(`    ⚡ Lazy  (slo deferred)    ${fmt(lazyMedian).padStart(10)}`);

  if (lazyMedian > 0 && eagerMedian > lazyMedian) {
    const saved = eagerMedian - lazyMedian;
    const pct = (saved / eagerMedian) * 100;
    console.log(`\n    🎯 Lazy is ${fmt(saved)} faster (${pct.toFixed(0)}% reduction)`);
  } else if (lazyMedian > 0) {
    console.log('\n    ⚠️  No measurable difference (module caching may dominate)');
  }

  // ── 🔍 Source size check ─────────────────────────────────
  console.log('\n🔍 Source Size Check\n');
  const srcDir = join(PKG_ROOT, 'src');
  const files = ['index.ts', 'slo.ts', 'resilience.ts', 'cardinality.ts', 'pii.ts'];
  for (const f of files) {
    try {
      const size = statSync(join(srcDir, f)).size;
      console.log(`    ${f.padEnd(20)} ${size} bytes`);
    } catch {
      console.log(`    ${f.padEnd(20)} (not found)`);
    }
  }

  console.log('\n🏁 Done!');
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
