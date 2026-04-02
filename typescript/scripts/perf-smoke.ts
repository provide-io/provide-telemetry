// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Performance smoke test — measures throughput of core telemetry operations.
 * Report-only: exits 0 regardless of results.
 */

import { setupTelemetry, getLogger, counter } from '../src/index';

setupTelemetry({ serviceName: 'perf-smoke', logLevel: 'silent' });

const N = 10_000;

// --- Logging throughput ---
const log = getLogger('perf');
const logStart = performance.now();
for (let i = 0; i < N; i++) {
  log.info({ event: 'perf.test.log', i });
}
const logMs = performance.now() - logStart;
const logOps = Math.round(N / (logMs / 1000));

// --- Counter throughput ---
const c = counter('perf.test.counter', { description: 'perf smoke counter' });
const counterStart = performance.now();
for (let i = 0; i < N; i++) {
  c.add(1);
}
const counterMs = performance.now() - counterStart;
const counterOps = Math.round(N / (counterMs / 1000));

console.log(`Logging:  ${N} calls in ${logMs.toFixed(1)}ms  (${logOps.toLocaleString()} ops/sec)`);
console.log(`Counter:  ${N} calls in ${counterMs.toFixed(1)}ms  (${counterOps.toLocaleString()} ops/sec)`);
