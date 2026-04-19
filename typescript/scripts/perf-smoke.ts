// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Performance smoke test — measures throughput of core telemetry operations.
 * Report-only: exits 0 regardless of results.
 */

// --- Import time ---
const importStart = performance.now();
const mod = await import('../src/index.js');
const importMs = performance.now() - importStart;

const { setupTelemetry, getLogger, counter, withTrace, sanitize } = mod;

// In tsx's ESM loader path, propagation.ts initializes AsyncLocalStorage
// via a fire-and-forget `await import('node:async_hooks')` because top-level
// await is forbidden in CJS output. Yield a tick so that init resolves
// before setupTelemetry runs its ALS-availability check.
await new Promise((resolve) => setTimeout(resolve, 50));

setupTelemetry({ serviceName: 'perf-smoke', logLevel: 'silent' });

interface Result {
  operation: string;
  count: number;
  ms: number;
  opsPerSec: number;
}

const results: Result[] = [];

function bench(operation: string, count: number, fn: () => void): void {
  const start = performance.now();
  for (let i = 0; i < count; i++) fn();
  const ms = performance.now() - start;
  results.push({ operation, count, ms, opsPerSec: Math.round(count / (ms / 1000)) });
}

// --- Import time (special case, already measured) ---
results.push({
  operation: 'import()',
  count: 1,
  ms: importMs,
  opsPerSec: Math.round(1 / (importMs / 1000)),
});

// --- Logging throughput ---
const log = getLogger('perf');
bench('logger.info()', 100_000, () => {
  log.info({ event: 'perf.test.log' });
});

// --- Counter throughput ---
const c = counter('perf.test.counter', { description: 'perf smoke counter' });
bench('counter.add(1)', 100_000, () => {
  c.add(1);
});

// --- Trace throughput ---
bench('withTrace()', 10_000, () => {
  withTrace('perf.span', () => {});
});

// --- PII sanitization throughput ---
const piiPayload = { email: 'user@example.com', password: 'secret123', name: 'Test User' }; // pragma: allowlist secret
bench('sanitize()', 10_000, () => {
  sanitize(piiPayload);
});

// --- Output ---
// JSON-emit mode (--emit-json or PERF_EMIT_JSON=1) prints a single flat
// {op_name: ns_per_op} blob suitable for piping into scripts/perf_check.py.
// Default mode keeps the human-readable table for interactive use.
const emitJson = process.argv.includes('--emit-json') || process.env['PERF_EMIT_JSON'] === '1';

if (emitJson) {
  const blob: Record<string, number> = {};
  for (const r of results) {
    // ns_per_op = (ms * 1_000_000) / count
    blob[r.operation] = Math.round((r.ms * 1_000_000) / r.count);
  }
  console.log(JSON.stringify(blob));
  process.exit(0);
}

const header = ['Operation', 'Count', 'Time (ms)', 'ops/sec'];
const rows = results.map((r) => [
  r.operation,
  r.count.toLocaleString(),
  r.ms.toFixed(1),
  r.opsPerSec.toLocaleString(),
]);

const colWidths = header.map((h, i) => Math.max(h.length, ...rows.map((r) => r[i].length)));

const sep = colWidths.map((w) => '-'.repeat(w)).join(' | ');
const fmtRow = (cols: string[]) => cols.map((c, i) => c.padStart(colWidths[i])).join(' | ');

console.log();
console.log('Performance Smoke Test Results');
console.log(sep);
console.log(fmtRow(header));
console.log(sep);
for (const row of rows) console.log(fmtRow(row));
console.log(sep);
console.log();

process.exit(0);
