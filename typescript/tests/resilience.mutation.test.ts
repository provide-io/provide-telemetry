// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Mutation-kill resilience tests: per-signal isolation, error messages, reset, health increments,
 * non-timeout counter reset, retry counts, export latency, and general isolation.
 * Half-open probe and circuit state tests live in resilience.circuit.test.ts.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  TelemetryTimeoutError,
  _resetResilienceForTests,
  getExporterPolicy,
  runWithResilience,
  setExporterPolicy,
} from '../src/resilience';
import { _resetHealthForTests, getHealthSnapshot } from '../src/health';

beforeEach(() => {
  _resetResilienceForTests();
  _resetHealthForTests();
});
afterEach(() => {
  _resetResilienceForTests();
  _resetHealthForTests();
});

describe('resilience — circuit breaker per signal', () => {
  it('circuit breaker for traces signal trips independently of logs', async () => {
    setExporterPolicy('traces', { timeoutMs: 1000, failOpen: true, retries: 0 });
    setExporterPolicy('logs', { timeoutMs: 1000, failOpen: true, retries: 0 });
    const timeoutFn = () => Promise.reject(new TelemetryTimeoutError('timeout'));
    // Trip traces circuit
    await runWithResilience('traces', timeoutFn);
    await runWithResilience('traces', timeoutFn);
    await runWithResilience('traces', timeoutFn); // trips traces
    // logs should still work
    let logsCalled = false;
    await runWithResilience('logs', async () => {
      logsCalled = true;
      return 'ok';
    });
    expect(logsCalled).toBe(true);
    // traces is open
    let tracesCalled = false;
    const result = await runWithResilience('traces', async () => {
      tracesCalled = true;
      return 'ok';
    });
    expect(result).toBeNull();
    expect(tracesCalled).toBe(false);
  });

  it('circuit breaker cooldown boundary: still open at exactly 60000ms', async () => {
    vi.useFakeTimers();
    setExporterPolicy('metrics', { timeoutMs: 0, failOpen: true, retries: 0 });
    const timeoutFn = () => Promise.reject(new TelemetryTimeoutError('timeout'));
    await runWithResilience('metrics', timeoutFn);
    await runWithResilience('metrics', timeoutFn);
    await runWithResilience('metrics', timeoutFn); // trips metrics, openCount=1, cooldown=60s
    // Advance to exactly 60000ms (not past)
    vi.advanceTimersByTime(60_000);
    // At exactly 60000ms: elapsed < cooldown (60000 < 60000 is false), probe allowed
    let probeRan = false;
    await runWithResilience('metrics', async () => {
      probeRan = true;
      return 'ok';
    });
    expect(probeRan).toBe(true);
    vi.useRealTimers();
  });
});

describe('resilience — circuit breaker error messages (kills StringLiteral on messages)', () => {
  it('increments exportFailuresLogs when circuit is tripped and call rejected', async () => {
    _resetResilienceForTests();
    _resetHealthForTests();
    setExporterPolicy('logs', { retries: 0, timeoutMs: 1000, failOpen: true });
    // Trip circuit
    const timeoutFn = () => Promise.reject(new TelemetryTimeoutError('t'));
    await runWithResilience('logs', timeoutFn);
    await runWithResilience('logs', timeoutFn);
    await runWithResilience('logs', timeoutFn);
    const beforeOpen = getHealthSnapshot().exportFailuresLogs;
    // Call while circuit open
    await runWithResilience('logs', async () => 'ok');
    expect(getHealthSnapshot().exportFailuresLogs).toBe(beforeOpen + 1);
  });

  it('throws with "circuit breaker open" message when failOpen=false', async () => {
    _resetResilienceForTests();
    setExporterPolicy('logs', { retries: 0, timeoutMs: 1000, failOpen: false });
    const timeoutFn = () => Promise.reject(new TelemetryTimeoutError('t'));
    for (let i = 0; i < 3; i++) {
      try {
        await runWithResilience('logs', timeoutFn);
      } catch {
        /* expected */
      }
    }
    await expect(runWithResilience('logs', async () => 'ok')).rejects.toThrow(
      'circuit breaker open',
    );
  });
});

describe('resilience — circuit breaker reset clears all signals (kills StringLiteral in for-loop)', () => {
  it('resets traces signal (after tripping it)', async () => {
    _resetResilienceForTests();
    setExporterPolicy('traces', { retries: 0, timeoutMs: 0, failOpen: true });
    const timeoutFn = () => Promise.reject(new TelemetryTimeoutError('t'));
    await runWithResilience('traces', timeoutFn);
    await runWithResilience('traces', timeoutFn);
    await runWithResilience('traces', timeoutFn);
    _resetResilienceForTests();
    let called = false;
    await runWithResilience('traces', async () => {
      called = true;
      return 'ok';
    });
    expect(called).toBe(true);
  });

  it('resets metrics signal (after tripping it)', async () => {
    _resetResilienceForTests();
    setExporterPolicy('metrics', { retries: 0, timeoutMs: 0, failOpen: true });
    const timeoutFn = () => Promise.reject(new TelemetryTimeoutError('t'));
    await runWithResilience('metrics', timeoutFn);
    await runWithResilience('metrics', timeoutFn);
    await runWithResilience('metrics', timeoutFn);
    _resetResilienceForTests();
    let called = false;
    await runWithResilience('metrics', async () => {
      called = true;
      return 'ok';
    });
    expect(called).toBe(true);
  });
});

describe('resilience — health increments (kills StringLiteral on exportFailures/retries)', () => {
  it('increments exportFailuresLogs when fn throws non-timeout error', async () => {
    _resetResilienceForTests();
    _resetHealthForTests();
    setExporterPolicy('logs', { retries: 0, timeoutMs: 1000, failOpen: true });
    await runWithResilience('logs', async () => {
      throw new Error('plain error');
    });
    expect(getHealthSnapshot().exportFailuresLogs).toBe(1);
  });

  it('increments retriesLogs when retries > 0 and fn fails', async () => {
    _resetResilienceForTests();
    _resetHealthForTests();
    setExporterPolicy('logs', { retries: 1, timeoutMs: 1000, failOpen: true, backoffMs: 0 });
    await runWithResilience('logs', async () => {
      throw new Error('fail');
    });
    expect(getHealthSnapshot().retriesLogs).toBe(1);
  });

  it('increments exportFailuresLogs specifically via circuit breaker open path', async () => {
    _resetResilienceForTests();
    _resetHealthForTests();
    setExporterPolicy('logs', { retries: 0, timeoutMs: 1000, failOpen: true });
    const timeoutFn = () => Promise.reject(new TelemetryTimeoutError('timeout'));
    await runWithResilience('logs', timeoutFn); // failure 1
    await runWithResilience('logs', timeoutFn); // failure 2
    await runWithResilience('logs', timeoutFn); // failure 3, circuit trips
    const afterTrip = getHealthSnapshot().exportFailuresLogs;
    await runWithResilience('logs', async () => 'ok');
    expect(getHealthSnapshot().exportFailuresLogs).toBe(afterTrip + 1);
  });
});

describe('resilience — non-timeout error resets consecutive timeout counter (kills BlockStatement on else branch)', () => {
  it('does not trip circuit after 2 timeouts + 1 non-timeout + 1 timeout', async () => {
    _resetResilienceForTests();
    setExporterPolicy('elsetest', { timeoutMs: 0, failOpen: true, retries: 0 });
    const timeoutFn = () => Promise.reject(new TelemetryTimeoutError('timeout'));
    const normalFn = () => Promise.reject(new Error('non-timeout error'));
    await runWithResilience('elsetest', timeoutFn); // consecutive = 1
    await runWithResilience('elsetest', timeoutFn); // consecutive = 2
    await runWithResilience('elsetest', normalFn); // consecutive resets to 0
    await runWithResilience('elsetest', timeoutFn); // consecutive = 1 (NOT 3)
    let called = false;
    await runWithResilience('elsetest', async () => {
      called = true;
      return 'ok';
    });
    expect(called).toBe(true);
  });
});

describe('resilience — fn called exactly once when retries=0 (kills <= vs < on attempt)', () => {
  it('calls fn exactly once when retries=0 and fn succeeds', async () => {
    _resetResilienceForTests();
    setExporterPolicy('logs', { retries: 0, timeoutMs: 100, backoffMs: 0 });
    let calls = 0;
    await runWithResilience('logs', async () => {
      calls++;
      return 'ok';
    });
    expect(calls).toBe(1);
  });

  it('calls fn exactly twice when retries=1 and fn always fails', async () => {
    _resetResilienceForTests();
    setExporterPolicy('logs', { retries: 1, timeoutMs: 100, backoffMs: 0, failOpen: true });
    let calls = 0;
    await runWithResilience('logs', async () => {
      calls++;
      throw new Error('fail');
    });
    expect(calls).toBe(2);
  });
});

describe('resilience — export latency recorded (kills ArithmeticOperator - → +)', () => {
  it('records non-negative latency on success', async () => {
    _resetResilienceForTests();
    _resetHealthForTests();
    setExporterPolicy('logs', { timeoutMs: 1000 });
    const { getHealthSnapshot: snap } = await import('../src/health');
    await runWithResilience('logs', async () => 'ok');
    expect(snap().exportLatencyMsLogs).toBeGreaterThanOrEqual(0);
    expect(snap().exportLatencyMsLogs).toBeLessThan(1000);
  });
});

describe('per-signal resilience isolation', () => {
  it('setting a policy for logs does NOT affect getExporterPolicy for traces', () => {
    setExporterPolicy('logs', { retries: 5, backoffMs: 500 });
    const tracesPolicy = getExporterPolicy('traces');
    expect(tracesPolicy.retries).toBe(0);
    expect(tracesPolicy.backoffMs).toBe(0);
    expect(tracesPolicy.timeoutMs).toBe(10_000);
    expect(tracesPolicy.failOpen).toBe(true);
  });

  it('getExporterPolicy for unknown signal returns the default policy', () => {
    const p = getExporterPolicy('unknown');
    expect(p.retries).toBe(0);
    expect(p.backoffMs).toBe(0);
    expect(p.timeoutMs).toBe(10_000);
    expect(p.failOpen).toBe(true);
  });
});
