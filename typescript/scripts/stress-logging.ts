// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Memory stress test — logs 1,000,000 records and reports peak heap usage.
 * Should complete without crashing.
 */

import { setupTelemetry, getLogger } from '../src/index.js';

setupTelemetry({ serviceName: 'stress-logging', logLevel: 'silent', consoleOutput: false });

const log = getLogger('stress');
const N = 1_000_000;

const heapBefore = process.memoryUsage().heapUsed;
const start = performance.now();

for (let i = 0; i < N; i++) {
  log.info({ event: 'stress.log', i });
}

const elapsed = performance.now() - start;
const heapAfter = process.memoryUsage().heapUsed;
const peakMB = (heapAfter / 1024 / 1024).toFixed(1);
const beforeMB = (heapBefore / 1024 / 1024).toFixed(1);

console.log();
console.log('Stress Logging Results');
console.log(`  Records logged: ${N.toLocaleString()}`);
console.log(`  Elapsed:        ${elapsed.toFixed(0)}ms`);
console.log(`  Heap before:    ${beforeMB} MB`);
console.log(`  Heap after:     ${peakMB} MB`);
console.log(`  Heap delta:     ${((heapAfter - heapBefore) / 1024 / 1024).toFixed(1)} MB`);
console.log();

process.exit(0);
