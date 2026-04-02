// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Backpressure stress test — sets a small queue limit and floods with logs.
 * Should show drops in the health snapshot.
 */

import { setupTelemetry, getLogger, setQueuePolicy, getHealthSnapshot } from '../src/index.js';

setupTelemetry({ serviceName: 'stress-backpressure', logLevel: 'silent', consoleOutput: false });

setQueuePolicy({ maxLogs: 100 });

const log = getLogger('stress-bp');
const N = 100_000;

const heapBefore = process.memoryUsage().heapUsed;
const start = performance.now();

for (let i = 0; i < N; i++) {
  log.info({ event: 'stress.backpressure', i });
}

const elapsed = performance.now() - start;
const heapAfter = process.memoryUsage().heapUsed;
const health = getHealthSnapshot();

console.log();
console.log('Stress Backpressure Results');
console.log(`  Records attempted: ${N.toLocaleString()}`);
console.log(`  Elapsed:           ${elapsed.toFixed(0)}ms`);
console.log(`  Heap before:       ${(heapBefore / 1024 / 1024).toFixed(1)} MB`);
console.log(`  Heap after:        ${(heapAfter / 1024 / 1024).toFixed(1)} MB`);
console.log(`  Health snapshot:   ${JSON.stringify(health, null, 2)}`);
console.log();

process.exit(0);
