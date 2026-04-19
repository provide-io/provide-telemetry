// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  CIRCUIT_BASE_COOLDOWN_MS,
  CIRCUIT_BREAKER_THRESHOLD,
  TelemetryTimeoutError,
  _getConsecutiveTimeoutsForTests,
  _getCircuitTrippedAtForTests,
  _getHalfOpenProbingForTests,
  _getOpenCountForTests,
  _setConsecutiveTimeoutsForTests,
  _setCircuitTrippedAtForTests,
  _setHalfOpenProbingForTests,
  _setOpenCountForTests,
  _resetResilienceForTests,
  getCircuitState,
  runWithResilience,
  setExporterPolicy,
} from '../src/resilience';
import { _resetHealthForTests } from '../src/health';

beforeEach(() => {
  _resetResilienceForTests();
  _resetHealthForTests();
});
afterEach(() => {
  _resetResilienceForTests();
  _resetHealthForTests();
});

describe('getCircuitState', () => {
  it('returns closed state by default', () => {
    const cs = getCircuitState('logs');
    expect(cs.state).toBe('closed');
    expect(cs.openCount).toBe(0);
    expect(cs.cooldownRemainingMs).toBe(0);
  });

  it('returns open state after circuit trips', async () => {
    setExporterPolicy('logs', { timeoutMs: 0, failOpen: true, retries: 0 });
    const timeoutFn = () => Promise.reject(new TelemetryTimeoutError('timeout'));
    await runWithResilience('logs', timeoutFn);
    await runWithResilience('logs', timeoutFn);
    await runWithResilience('logs', timeoutFn);
    const cs = getCircuitState('logs');
    expect(cs.state).toBe('open');
    expect(cs.openCount).toBe(1);
    expect(cs.cooldownRemainingMs).toBeGreaterThan(0);
  });

  it('returns half-open state when cooldown expires', async () => {
    vi.useFakeTimers();
    setExporterPolicy('logs', { timeoutMs: 0, failOpen: true, retries: 0 });
    const timeoutFn = () => Promise.reject(new TelemetryTimeoutError('timeout'));
    await runWithResilience('logs', timeoutFn);
    await runWithResilience('logs', timeoutFn);
    await runWithResilience('logs', timeoutFn);
    // openCount=1, cooldown = 30000 * 2^1 = 60000ms
    vi.advanceTimersByTime(61_000);
    const cs = getCircuitState('logs');
    expect(cs.state).toBe('half-open');
    expect(cs.cooldownRemainingMs).toBe(0);
    vi.useRealTimers();
  });
});

describe('runWithResilience — timeout-disabled bypasses circuit gate', () => {
  it('timeoutMs=0 bypasses the breaker even when it is open', async () => {
    setExporterPolicy('metrics', { timeoutMs: 0, failOpen: false, retries: 0 });
    // Pre-load the breaker into open + active cooldown.
    _setConsecutiveTimeoutsForTests('metrics', CIRCUIT_BREAKER_THRESHOLD);
    let called = false;
    const result = await runWithResilience('metrics', async () => {
      called = true;
      return 'allowed';
    });
    expect(called).toBe(true);
    expect(result).toBe('allowed');
  });
});

describe('exponential backoff on circuit breaker', () => {
  it('doubles cooldown after repeated trips', async () => {
    vi.useFakeTimers();
    setExporterPolicy('logs', { timeoutMs: 1000, failOpen: true, retries: 0 });
    const timeoutFn = () => Promise.reject(new TelemetryTimeoutError('timeout'));

    // First trip: 3 consecutive timeouts -> openCount=1, cooldown = 30s * 2^1 = 60s
    await runWithResilience('logs', timeoutFn);
    await runWithResilience('logs', timeoutFn);
    await runWithResilience('logs', timeoutFn);
    expect(getCircuitState('logs').openCount).toBe(1);

    // Wait for first cooldown (60s) to expire, then fail the half-open probe
    vi.advanceTimersByTime(61_000);
    // Half-open probe: timeout -> re-open, openCount=2, cooldown = 30s * 2^2 = 120s
    await runWithResilience('logs', timeoutFn);
    expect(getCircuitState('logs').openCount).toBe(2);

    // At 120s cooldown, 61s should NOT be enough
    vi.advanceTimersByTime(61_000);
    // Still open (120s cooldown, only 61s elapsed)
    let called = false;
    await runWithResilience('logs', async () => {
      called = true;
      return 'ok';
    });
    expect(called).toBe(false); // circuit still open

    // Advance past the 120s cooldown
    vi.advanceTimersByTime(60_000);
    // Now half-open probe should be allowed
    called = false;
    await runWithResilience('logs', async () => {
      called = true;
      return 'ok';
    });
    expect(called).toBe(true);
    vi.useRealTimers();
  });
});

describe('half-open probe — success decays openCount', () => {
  it('decrements openCount on successful half-open probe', async () => {
    vi.useFakeTimers();
    setExporterPolicy('logs', { timeoutMs: 1000, failOpen: true, retries: 0 });
    const timeoutFn = () => Promise.reject(new TelemetryTimeoutError('timeout'));

    // Trip circuit: openCount -> 1
    await runWithResilience('logs', timeoutFn);
    await runWithResilience('logs', timeoutFn);
    await runWithResilience('logs', timeoutFn);
    expect(getCircuitState('logs').openCount).toBe(1);

    // Wait for cooldown (60s = 30000 * 2^1), succeed the half-open probe
    vi.advanceTimersByTime(61_000);
    await runWithResilience('logs', async () => 'ok');

    // openCount should decay: max(0, 1-1) = 0
    expect(getCircuitState('logs').openCount).toBe(0);
    expect(getCircuitState('logs').state).toBe('closed');
    vi.useRealTimers();
  });
});

describe('half-open probe — failure on non-timeout re-opens', () => {
  it('re-opens circuit and increments openCount on non-timeout failure during half-open', async () => {
    vi.useFakeTimers();
    setExporterPolicy('logs', { timeoutMs: 1000, failOpen: true, retries: 0 });
    const timeoutFn = () => Promise.reject(new TelemetryTimeoutError('timeout'));
    const normalFail = () => Promise.reject(new Error('non-timeout'));

    // Trip circuit: openCount -> 1
    await runWithResilience('logs', timeoutFn);
    await runWithResilience('logs', timeoutFn);
    await runWithResilience('logs', timeoutFn);
    expect(getCircuitState('logs').openCount).toBe(1);

    // Wait for cooldown (60s = 30000 * 2^1), then fail with a non-timeout error during half-open
    vi.advanceTimersByTime(61_000);
    await runWithResilience('logs', normalFail);

    // Should re-open with openCount incremented to 2
    expect(getCircuitState('logs').openCount).toBe(2);
    expect(getCircuitState('logs').state).toBe('open');
    vi.useRealTimers();
  });
});

describe('half-open probe — concurrent probe rejection', () => {
  it('rejects concurrent callers while half-open probe is in flight (failOpen=false)', async () => {
    setExporterPolicy('logs', { retries: 0, backoffMs: 0, timeoutMs: 5000, failOpen: false });
    // Trip the circuit breaker
    _setConsecutiveTimeoutsForTests('logs', CIRCUIT_BREAKER_THRESHOLD);
    _setOpenCountForTests('logs', 1);
    _setCircuitTrippedAtForTests('logs', Date.now() - CIRCUIT_BASE_COOLDOWN_MS * 2); // cooldown expired
    // Simulate a probe already in progress
    _setHalfOpenProbingForTests('logs', true);

    let fnCalled = false;
    await expect(
      runWithResilience('logs', async () => {
        fnCalled = true;
      }),
    ).rejects.toThrow('probe in progress');
    expect(fnCalled).toBe(false);
  });

  it('rejects concurrent callers while half-open probe is in flight (failOpen=true)', async () => {
    setExporterPolicy('logs', { retries: 0, backoffMs: 0, timeoutMs: 5000, failOpen: true });
    _setConsecutiveTimeoutsForTests('logs', CIRCUIT_BREAKER_THRESHOLD);
    _setOpenCountForTests('logs', 1);
    _setCircuitTrippedAtForTests('logs', Date.now() - CIRCUIT_BASE_COOLDOWN_MS * 2);
    _setHalfOpenProbingForTests('logs', true);

    let fnCalled = false;
    const result = await runWithResilience('logs', async () => {
      fnCalled = true;
    });
    expect(fnCalled).toBe(false);
    expect(result).toBeNull();
  });
});

describe('getCircuitState — unknown signal defaults', () => {
  it('returns closed state with zero openCount for unknown signal', () => {
    const cs = getCircuitState('unknown-signal');
    expect(cs.state).toBe('closed');
    expect(cs.openCount).toBe(0);
    expect(cs.cooldownRemainingMs).toBe(0);
  });
});

describe('half-open probe mutation-kills', () => {
  it('probe rejection error message contains "probe in progress" (kills StringLiteral mutation)', async () => {
    setExporterPolicy('logs', { retries: 0, timeoutMs: 5000, failOpen: false });
    _setConsecutiveTimeoutsForTests('logs', CIRCUIT_BREAKER_THRESHOLD);
    _setHalfOpenProbingForTests('logs', true);
    await expect(runWithResilience('logs', async () => {})).rejects.toThrow('probe in progress');
  });

  it('normal (non-probe) success does not decay openCount (kills ConditionalExpression -> true on halfOpenProbing check)', async () => {
    setExporterPolicy('logs', { retries: 0, timeoutMs: 0, failOpen: true });
    _setOpenCountForTests('logs', 2); // would decay to 1 if the if-block runs when it shouldn't
    _setHalfOpenProbingForTests('logs', false); // not probing

    await runWithResilience('logs', async () => 'ok');

    expect(_getOpenCountForTests('logs')).toBe(2); // must not decay on normal success
  });

  it('probe success decays openCount from 2 to 1 not to 0 (kills Math.max -> Math.min)', async () => {
    setExporterPolicy('logs', { retries: 0, timeoutMs: 1000, failOpen: true });
    _setConsecutiveTimeoutsForTests('logs', CIRCUIT_BREAKER_THRESHOLD);
    _setOpenCountForTests('logs', 2);
    _setCircuitTrippedAtForTests('logs', Date.now() - CIRCUIT_BASE_COOLDOWN_MS * 10); // cooldown expired

    await runWithResilience('logs', async () => 'ok');

    expect(_getOpenCountForTests('logs')).toBe(1); // 2-1=1, not 0
  });

  it('getCircuitState returns half-open when _halfOpenProbing is set (kills ConditionalExpression/BlockStatement on line 187)', () => {
    _setConsecutiveTimeoutsForTests('logs', CIRCUIT_BREAKER_THRESHOLD);
    _setOpenCountForTests('logs', 1);
    _setCircuitTrippedAtForTests('logs', Date.now());
    _setHalfOpenProbingForTests('logs', true);

    const cs = getCircuitState('logs');
    expect(cs.state).toBe('half-open');
    expect(cs.cooldownRemainingMs).toBe(0);
  });

  it('non-probe success resets consecutiveTimeouts to 0 even when it was 2 (kills else-BlockStatement mutation)', async () => {
    setExporterPolicy('logs', { retries: 0, timeoutMs: 0, failOpen: true });
    _setConsecutiveTimeoutsForTests('logs', 2); // < threshold, so CB is closed, fn runs normally (not half-open probe)
    _setHalfOpenProbingForTests('logs', false);

    await runWithResilience('logs', async () => 'ok');

    expect(_getConsecutiveTimeoutsForTests('logs')).toBe(0); // else-block must reset to 0
  });

  it('getCircuitState uses exponential (2**N) not linear (2*N) cooldown (kills ArithmeticOperator / -> *)', () => {
    _setConsecutiveTimeoutsForTests('logs', CIRCUIT_BREAKER_THRESHOLD);
    _setOpenCountForTests('logs', 3);
    _setCircuitTrippedAtForTests('logs', Date.now());

    const cs = getCircuitState('logs');
    expect(cs.state).toBe('open');
    expect(cs.cooldownRemainingMs).toBeGreaterThan(200_000); // 240s > 200s; linear 180s < 200s
  });
});

describe('getCircuitState — half-open during active probe', () => {
  it('reports half-open while probe fn is executing', async () => {
    vi.useFakeTimers();
    setExporterPolicy('logs', { timeoutMs: 0, failOpen: true, retries: 0 });
    const timeoutFn = () => Promise.reject(new TelemetryTimeoutError('timeout'));
    await runWithResilience('logs', timeoutFn);
    await runWithResilience('logs', timeoutFn);
    await runWithResilience('logs', timeoutFn);
    // openCount=1, cooldown=60s
    vi.advanceTimersByTime(61_000);

    let stateInsideProbe: string | undefined;
    await runWithResilience('logs', async () => {
      stateInsideProbe = getCircuitState('logs').state;
      return 'ok';
    });
    expect(stateInsideProbe).toBe('half-open');
    vi.useRealTimers();
  });
});

describe('resilience — encapsulated state getter/setter functions', () => {
  it('_getConsecutiveTimeoutsForTests returns 0 by default', () => {
    expect(_getConsecutiveTimeoutsForTests('logs')).toBe(0);
  });

  it('_setConsecutiveTimeoutsForTests / _getConsecutiveTimeoutsForTests round-trip', () => {
    _setConsecutiveTimeoutsForTests('logs', 5);
    expect(_getConsecutiveTimeoutsForTests('logs')).toBe(5);
  });

  it('_getOpenCountForTests returns 0 by default', () => {
    expect(_getOpenCountForTests('logs')).toBe(0);
  });

  it('_setOpenCountForTests / _getOpenCountForTests round-trip', () => {
    _setOpenCountForTests('traces', 3);
    expect(_getOpenCountForTests('traces')).toBe(3);
  });

  it('_getHalfOpenProbingForTests returns false by default', () => {
    expect(_getHalfOpenProbingForTests('logs')).toBe(false);
  });

  it('_setHalfOpenProbingForTests / _getHalfOpenProbingForTests round-trip', () => {
    _setHalfOpenProbingForTests('metrics', true);
    expect(_getHalfOpenProbingForTests('metrics')).toBe(true);
  });

  it('_getCircuitTrippedAtForTests returns 0 by default', () => {
    expect(_getCircuitTrippedAtForTests('logs')).toBe(0);
  });

  it('_setCircuitTrippedAtForTests / _getCircuitTrippedAtForTests round-trip', () => {
    const now = Date.now();
    _setCircuitTrippedAtForTests('logs', now);
    expect(_getCircuitTrippedAtForTests('logs')).toBe(now);
  });

  it('_resetResilienceForTests resets all getter values to zero/false', () => {
    _setConsecutiveTimeoutsForTests('logs', 99);
    _setOpenCountForTests('logs', 99);
    _setHalfOpenProbingForTests('logs', true);
    _setCircuitTrippedAtForTests('logs', 12345);
    _resetResilienceForTests();
    expect(_getConsecutiveTimeoutsForTests('logs')).toBe(0);
    expect(_getOpenCountForTests('logs')).toBe(0);
    expect(_getHalfOpenProbingForTests('logs')).toBe(false);
    expect(_getCircuitTrippedAtForTests('logs')).toBe(0);
  });

  it('_getHalfOpenProbingForTests returns false for an unknown signal (covers ?? false branch)', () => {
    expect(_getHalfOpenProbingForTests('__unknown_signal__')).toBe(false);
  });

  it('_getConsecutiveTimeoutsForTests returns 0 for an unknown signal (covers ?? 0 branch)', () => {
    expect(_getConsecutiveTimeoutsForTests('__unknown_signal__')).toBe(0);
  });

  it('_getOpenCountForTests returns 0 for an unknown signal (covers ?? 0 branch)', () => {
    expect(_getOpenCountForTests('__unknown_signal__')).toBe(0);
  });

  it('_getCircuitTrippedAtForTests returns 0 for an unknown signal (covers ?? 0 branch)', () => {
    expect(_getCircuitTrippedAtForTests('__unknown_signal__')).toBe(0);
  });
});

// Mutation-kill tests (per-signal isolation, error messages, reset, health, etc.) live in resilience.mutation.test.ts
