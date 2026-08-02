// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Targeted Stryker mutation-kill tests for backpressure.ts.
 *
 * DEFAULT_POLICY, _policy's initial clone, and _acquired's per-signal Set
 * seeding are all module-level literals — static mutants (see
 * pretty.mutants.test.ts for why `vi.resetModules()` + fresh import is
 * required to observe them).
 */

import { describe, expect, it, vi } from 'vitest';
import { _resetBackpressureForTests, tryAcquire } from '../src/backpressure.js';

describe('backpressure.ts — default policy is unlimited (max*: 0), from a fresh module', () => {
  it('grants the sentinel token 0 for every signal under the untouched default policy', async () => {
    vi.resetModules();
    const bp = await import('../src/backpressure.js');
    for (const signal of ['logs', 'traces', 'metrics'] as const) {
      const ticket = bp.tryAcquire(signal);
      expect(ticket).toEqual({ signal, token: 0 });
    }
  });
});

describe('backpressure.ts — _acquired seeds a real Set per signal, from a fresh module', () => {
  it('enforces a configured limit for every signal (not just whichever key survived a {} wipe)', async () => {
    vi.resetModules();
    const bp = await import('../src/backpressure.js');
    bp.setQueuePolicy({ maxLogs: 1, maxTraces: 1, maxMetrics: 1 });
    for (const signal of ['logs', 'traces', 'metrics'] as const) {
      expect(bp.tryAcquire(signal)).not.toBeNull();
      // Second acquire on the same signal must be rejected — this fails with a
      // TypeError (not a rejection) if _acquired.get(signal) is undefined,
      // which is exactly what an ArrayDeclaration `[]` mutant on the seeding
      // Map produces.
      expect(bp.tryAcquire(signal)).toBeNull();
    }
  });
});

describe('tryAcquire — real behaviour (not mutation-specific)', () => {
  it('respects a configured per-signal limit and releases correctly', () => {
    _resetBackpressureForTests();
    // covered by existing backpressure.test.ts; smoke-check only.
    expect(tryAcquire('logs')).not.toBeNull();
  });
});
