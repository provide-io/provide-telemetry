// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Stress test — 200,000 PII sanitizations (flat + nested) and reports heap usage.
 */

import { sanitize, registerPiiRule } from '../src/pii.js';

registerPiiRule({ path: 'ssn', mode: 'redact' });
registerPiiRule({ path: 'card_number', mode: 'hash' });

const N_FLAT = 200_000;
const N_NESTED = 100_000;

const heapBefore = process.memoryUsage().heapUsed;
const start = performance.now();

// Flat payloads
for (let i = 0; i < N_FLAT; i++) {
  const payload: Record<string, unknown> = {
    user: 'alice',
    password: 'secret', // pragma: allowlist secret
    token: 'abc123',
    request_id: `req-${i}`,
  };
  sanitize(payload);
}

// Nested payloads
for (let i = 0; i < N_NESTED; i++) {
  const payload: Record<string, unknown> = {
    user: { name: 'bob', ssn: '123-45-6789' },
    headers: { authorization: 'Bearer xyz', host: 'example.com' },
    meta: { request_id: `req-${i}`, api_key: 'sk-test-123' }, // pragma: allowlist secret
  };
  sanitize(payload);
}

const elapsed = performance.now() - start;
const heapAfter = process.memoryUsage().heapUsed;

console.log();
console.log('Stress PII Results');
console.log(`  Flat payloads:   ${N_FLAT.toLocaleString()}`);
console.log(`  Nested payloads: ${N_NESTED.toLocaleString()}`);
console.log(`  Elapsed:         ${elapsed.toFixed(0)}ms`);
console.log(`  Heap before:     ${(heapBefore / 1024 / 1024).toFixed(1)} MB`);
console.log(`  Heap after:      ${(heapAfter / 1024 / 1024).toFixed(1)} MB`);
console.log(`  Heap delta:      ${((heapAfter - heapBefore) / 1024 / 1024).toFixed(1)} MB`);
console.log();

process.exit(0);
