// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Stress test — 100,000 traced function calls and reports heap usage.
 */

import { setupTelemetry } from '../src/config.js';
import { withTrace } from '../src/tracing.js';

setupTelemetry({ serviceName: 'stress-tracing', logLevel: 'silent', consoleOutput: false });

const N = 100_000;
let sum = 0;

const heapBefore = process.memoryUsage().heapUsed;
const start = performance.now();

for (let i = 0; i < N; i++) {
  withTrace('stress.span', () => {
    sum += 1;
  });
}

const elapsed = performance.now() - start;
const heapAfter = process.memoryUsage().heapUsed;

console.log();
console.log('Stress Tracing Results');
console.log(`  Spans created: ${N.toLocaleString()}`);
console.log(`  Sum (verify):  ${sum.toLocaleString()}`);
console.log(`  Elapsed:       ${elapsed.toFixed(0)}ms`);
console.log(`  Heap before:   ${(heapBefore / 1024 / 1024).toFixed(1)} MB`);
console.log(`  Heap after:    ${(heapAfter / 1024 / 1024).toFixed(1)} MB`);
console.log(`  Heap delta:    ${((heapAfter - heapBefore) / 1024 / 1024).toFixed(1)} MB`);
console.log();

process.exit(0);
