// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Stress test — 500,000 sampling decisions and reports heap usage.
 */

import { setSamplingPolicy, shouldSample } from '../src/sampling.js';

const N = 500_000;

setSamplingPolicy('logs', { defaultRate: 0.5, overrides: { 'auth.login': 1.0 } });

const heapBefore = process.memoryUsage().heapUsed;
const start = performance.now();

let sampled = 0;
for (let i = 0; i < N; i++) {
  if (shouldSample('logs', i % 2 === 0 ? 'auth.login' : undefined)) sampled++;
}

const elapsed = performance.now() - start;
const heapAfter = process.memoryUsage().heapUsed;

console.log();
console.log('Stress Sampling Results');
console.log(`  Decisions:    ${N.toLocaleString()}`);
console.log(`  Sampled:      ${sampled.toLocaleString()} (${((sampled / N) * 100).toFixed(1)}%)`);
console.log(`  Elapsed:      ${elapsed.toFixed(0)}ms`);
console.log(`  Heap before:  ${(heapBefore / 1024 / 1024).toFixed(1)} MB`);
console.log(`  Heap after:   ${(heapAfter / 1024 / 1024).toFixed(1)} MB`);
console.log(`  Heap delta:   ${((heapAfter - heapBefore) / 1024 / 1024).toFixed(1)} MB`);
console.log();

process.exit(0);
