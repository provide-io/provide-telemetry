// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Targeted Stryker mutation-kill tests for resilience.ts — the pieces not
 * already covered by resilience.mutation.test.ts / resilience.circuit.test.ts.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  CIRCUIT_BREAKER_THRESHOLD,
  TelemetryTimeoutError,
  _getConsecutiveTimeoutsForTests,
  _resetResilienceForTests,
  _setCircuitTrippedAtForTests,
  _setConsecutiveTimeoutsForTests,
  runWithResilience,
  setExporterPolicy,
} from '../src/resilience.js';

afterEach(() => _resetResilienceForTests());

describe('resilience.ts — DEFAULT_POLICY, from a fresh module', () => {
  it('is a real, fail-open policy for an unregistered signal', async () => {
    vi.resetModules();
    const r = await import('../src/resilience.js');
    const policy = r.getExporterPolicy('never-configured-signal');
    expect(policy.failOpen).toBe(true);
    expect(policy.timeoutMs).toBe(10_000);
    expect(policy.retries).toBe(0);
    expect(policy.backoffMs).toBe(0);
  });
});

describe('runWithResilience — timeoutMs: 0 bypasses the circuit breaker entirely', () => {
  it('does not reject even when consecutiveTimeouts is already at threshold', async () => {
    const signal = 'bypass-probe';
    setExporterPolicy(signal, { timeoutMs: 0, failOpen: false });
    _setConsecutiveTimeoutsForTests(signal, CIRCUIT_BREAKER_THRESHOLD);
    _setCircuitTrippedAtForTests(signal, Date.now());

    // With timeoutMs > 0 required to consult the breaker, and it's exactly 0
    // here, the call must run fn() directly rather than rejecting.
    const result = await runWithResilience(signal, async () => 'ok');
    expect(result).toBe('ok');
  });
});

describe('runWithResilience — circuit-breaker cooldown boundary (fake timers for exact ms control)', () => {
  it('at exactly elapsed === cooldown, the probe is allowed through (< not <=)', async () => {
    vi.useFakeTimers();
    try {
      const signal = 'cooldown-exact-boundary';
      setExporterPolicy(signal, { timeoutMs: 100, failOpen: true });
      _setConsecutiveTimeoutsForTests(signal, CIRCUIT_BREAKER_THRESHOLD);
      _setCircuitTrippedAtForTests(signal, Date.now());
      // CIRCUIT_BASE_COOLDOWN_MS * 2**0 = 30_000ms for openCount=0. Advance the
      // clock by exactly that much: elapsed === cooldown precisely.
      vi.advanceTimersByTime(30_000);

      // `elapsed < cooldown` is false at exact equality, so real code takes the
      // half-open probe branch and runs fn(). An `elapsed <= cooldown` mutant
      // would treat this as still-cooling and reject instead.
      const result = await runWithResilience(signal, async () => 'probe-ran');
      expect(result).toBe('probe-ran');
    } finally {
      vi.useRealTimers();
    }
  });

  it('one millisecond before the boundary, the breaker stays closed', async () => {
    vi.useFakeTimers();
    try {
      const signal = 'cooldown-just-before';
      setExporterPolicy(signal, { timeoutMs: 100, failOpen: true });
      _setConsecutiveTimeoutsForTests(signal, CIRCUIT_BREAKER_THRESHOLD);
      _setCircuitTrippedAtForTests(signal, Date.now());
      vi.advanceTimersByTime(29_999);

      const result = await runWithResilience(signal, async () => 'unreachable');
      expect(result).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });
});

describe('runWithResilience — non-timeout errors reset the timeout counter, not the circuit', () => {
  it('resets consecutiveTimeouts to 0 after a plain (non-timeout) error, fail-open', async () => {
    const signal = 'plain-error-reset';
    setExporterPolicy(signal, { timeoutMs: 100, failOpen: true, retries: 0 });
    _setConsecutiveTimeoutsForTests(signal, 2);

    const result = await runWithResilience(signal, async () => {
      throw new Error('not a timeout');
    });

    expect(result).toBeNull();
    expect(_getConsecutiveTimeoutsForTests(signal)).toBe(0);
  });

  it('a genuine TelemetryTimeoutError increments the timeout counter instead', async () => {
    const signal = 'timeout-error-increments';
    setExporterPolicy(signal, { timeoutMs: 100, failOpen: true, retries: 0 });
    _setConsecutiveTimeoutsForTests(signal, 0);

    await runWithResilience(signal, async () => {
      throw new TelemetryTimeoutError('simulated timeout');
    });

    expect(_getConsecutiveTimeoutsForTests(signal)).toBe(1);
  });
});
