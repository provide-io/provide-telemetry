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

// --- Print table ---
const header = ['Operation', 'Count', 'Time (ms)', 'ops/sec'];
const rows = results.map((r) => [
  r.operation,
  r.count.toLocaleString(),
  r.ms.toFixed(1),
  r.opsPerSec.toLocaleString(),
]);

const colWidths = header.map((h, i) =>
  Math.max(h.length, ...rows.map((r) => r[i].length)),
);

const sep = colWidths.map((w) => '-'.repeat(w)).join(' | ');
const fmtRow = (cols: string[]) =>
  cols.map((c, i) => c.padStart(colWidths[i])).join(' | ');

console.log();
console.log('Performance Smoke Test Results');
console.log(sep);
console.log(fmtRow(header));
console.log(sep);
for (const row of rows) console.log(fmtRow(row));
console.log(sep);
console.log();

process.exit(0);
