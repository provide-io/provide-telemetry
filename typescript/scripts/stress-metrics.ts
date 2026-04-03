// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Metric stress test — creates 1000 counters, each called 100 times.
 * Reports peak heap and total accumulated value.
 */

import { setupTelemetry, counter } from '../src/index.js';

setupTelemetry({ serviceName: 'stress-metrics', logLevel: 'silent' });

const NUM_COUNTERS = 1_000;
const CALLS_PER_COUNTER = 100;

const heapBefore = process.memoryUsage().heapUsed;
const start = performance.now();

const counters = [];
for (let i = 0; i < NUM_COUNTERS; i++) {
  counters.push(counter(`stress.counter.${i}`, { description: `counter ${i}` }));
}

for (const c of counters) {
  for (let j = 0; j < CALLS_PER_COUNTER; j++) {
    c.add(1);
  }
}

const elapsed = performance.now() - start;
const heapAfter = process.memoryUsage().heapUsed;

const totalValue = counters.reduce((sum, c) => sum + (c.value ?? 0), 0);

console.log();
console.log('Stress Metrics Results');
console.log(`  Counters created: ${NUM_COUNTERS.toLocaleString()}`);
console.log(`  Calls per counter: ${CALLS_PER_COUNTER}`);
console.log(`  Total add() calls: ${(NUM_COUNTERS * CALLS_PER_COUNTER).toLocaleString()}`);
console.log(`  Total value:       ${totalValue.toLocaleString()}`);
console.log(`  Elapsed:           ${elapsed.toFixed(0)}ms`);
console.log(`  Heap before:       ${(heapBefore / 1024 / 1024).toFixed(1)} MB`);
console.log(`  Heap after:        ${(heapAfter / 1024 / 1024).toFixed(1)} MB`);
console.log();

process.exit(0);
