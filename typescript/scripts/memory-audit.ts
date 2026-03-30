// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Memory/performance audit for TypeScript telemetry hot paths.
 *
 * Measures RSS delta and per-call timing for every hot-path function.
 * Exits with code 1 if any function exceeds thresholds.
 */

import { performance } from 'node:perf_hooks';

import { tryAcquire, release, setQueuePolicy } from '../src/backpressure';
import { guardAttributes, registerCardinalityLimit, clearCardinalityLimits } from '../src/cardinality';
import { getHealthSnapshot } from '../src/health';
import { sanitize } from '../src/pii';
import { shouldSample } from '../src/sampling';
import { eventName } from '../src/schema';

const MAX_NS_PER_OP = 1000;
const MAX_RSS_DELTA_MB = 50;

interface BenchResult {
  name: string;
  calls: number;
  nsPerOp: number;
  rssDeltaMB: number;
}

function benchmarkFn(name: string, iterations: number, fn: () => void): BenchResult {
  // Warmup
  for (let i = 0; i < Math.min(1000, iterations); i++) fn();

  // Force GC if available
  if (globalThis.gc) globalThis.gc();

  const rssBefore = process.memoryUsage().rss;
  const start = performance.now();

  for (let i = 0; i < iterations; i++) fn();

  const elapsed = performance.now() - start;
  const rssAfter = process.memoryUsage().rss;

  return {
    name,
    calls: iterations,
    nsPerOp: (elapsed * 1_000_000) / iterations,
    rssDeltaMB: (rssAfter - rssBefore) / (1024 * 1024),
  };
}

function main(): number {
  const results: BenchResult[] = [];
  const n = 500_000;
  const nSmall = 200_000;

  // shouldSample
  results.push(benchmarkFn('shouldSample()', n, () => shouldSample('logs')));

  // eventName
  results.push(benchmarkFn('eventName(3 seg)', n, () => eventName('auth', 'login', 'success')));

  // sanitize (PII)
  const payload = { password: 'secret', token: 'abc', user_id: 'u1' };
  results.push(
    benchmarkFn('sanitize(flat)', nSmall, () => {
      const copy = { ...payload };
      sanitize(copy);
    }),
  );

  // guardAttributes
  clearCardinalityLimits();
  results.push(
    benchmarkFn('guardAttributes()', nSmall, () =>
      guardAttributes({ route: '/api/users', method: 'GET' }),
    ),
  );

  // tryAcquire + release
  setQueuePolicy({ maxLogs: 0, maxTraces: 0, maxMetrics: 0 });
  results.push(
    benchmarkFn('tryAcquire+release', nSmall, () => {
      const ticket = tryAcquire('logs');
      if (ticket) release(ticket);
    }),
  );

  // getHealthSnapshot
  results.push(benchmarkFn('getHealthSnapshot()', 50_000, () => getHealthSnapshot()));

  // Print results table
  console.log('');
  console.log(
    `${'Function'.padEnd(30)}  ${'Calls'.padStart(10)}  ${'ns/op'.padStart(10)}  ${'RSS delta MB'.padStart(14)}  ${'Result'.padStart(8)}`,
  );
  console.log('-'.repeat(80));

  let failures = 0;
  for (const r of results) {
    const pass = r.nsPerOp <= MAX_NS_PER_OP && r.rssDeltaMB <= MAX_RSS_DELTA_MB;
    const status = pass ? 'PASS' : 'FAIL';
    if (!pass) failures++;
    console.log(
      `${r.name.padEnd(30)}  ${r.calls.toLocaleString().padStart(10)}  ${r.nsPerOp.toFixed(1).padStart(10)}  ${r.rssDeltaMB.toFixed(2).padStart(14)}  ${status.padStart(8)}`,
    );
  }

  console.log('');
  if (failures > 0) {
    console.log(`${failures} benchmark(s) exceeded thresholds (max ${MAX_NS_PER_OP} ns/op, max ${MAX_RSS_DELTA_MB} MB RSS)`);
    return 1;
  }
  console.log('All benchmarks within thresholds.');
  return 0;
}

process.exit(main());
