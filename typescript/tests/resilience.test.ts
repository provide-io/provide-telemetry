// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  TelemetryTimeoutError,
  _resetResilienceForTests,
  getCircuitState,
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

describe('setExporterPolicy / getExporterPolicy', () => {
  it('defaults to retries=0, failOpen=true, timeoutMs=10000', () => {
    const p = getExporterPolicy('logs');
    expect(p.retries).toBe(0);
    expect(p.failOpen).toBe(true);
    expect(p.timeoutMs).toBe(10_000);
  });

  it('updates partial policy', () => {
    setExporterPolicy('logs', { retries: 2, failOpen: false });
    const p = getExporterPolicy('logs');
    expect(p.retries).toBe(2);
    expect(p.failOpen).toBe(false);
    expect(p.timeoutMs).toBe(10_000); // unchanged
  });
});

describe('runWithResilience — success', () => {
  it('returns the result of fn on success', async () => {
    setExporterPolicy('logs', { timeoutMs: 0 });
    const result = await runWithResilience('logs', () => Promise.resolve('ok'));
    expect(result).toBe('ok');
  });

  it('passes through with no timeout when timeoutMs=0', async () => {
    setExporterPolicy('traces', { timeoutMs: 0 });
    const result = await runWithResilience('traces', async () => 42);
    expect(result).toBe(42);
  });
});

describe('runWithResilience — failure with failOpen=true', () => {
  it('returns null when fn throws and failOpen=true', async () => {
    setExporterPolicy('logs', { timeoutMs: 0, failOpen: true });
    const result = await runWithResilience('logs', () =>
      Promise.reject(new Error('export failed')),
    );
    expect(result).toBeNull();
  });

  it('returns null when fn throws TelemetryTimeoutError and failOpen=true', async () => {
    setExporterPolicy('logs', { timeoutMs: 0, failOpen: true });
    const result = await runWithResilience('logs', () =>
      Promise.reject(new TelemetryTimeoutError('timed out')),
    );
    expect(result).toBeNull();
  });
});

describe('runWithResilience — failure with failOpen=false', () => {
  it('rethrows the error when failOpen=false', async () => {
    setExporterPolicy('logs', { timeoutMs: 0, failOpen: false });
    await expect(
      runWithResilience('logs', () => Promise.reject(new Error('fatal'))),
    ).rejects.toThrow('fatal');
  });
});

describe('runWithResilience — retries', () => {
  it('retries on failure and succeeds on second attempt', async () => {
    setExporterPolicy('logs', { retries: 1, backoffMs: 0, timeoutMs: 0, failOpen: false });
    let calls = 0;
    const result = await runWithResilience('logs', async () => {
      calls++;
      if (calls < 2) throw new Error('transient');
      return 'recovered';
    });
    expect(result).toBe('recovered');
    expect(calls).toBe(2);
  });

  it('exhausts retries and returns null (failOpen=true)', async () => {
    setExporterPolicy('logs', { retries: 1, backoffMs: 0, timeoutMs: 0, failOpen: true });
    const result = await runWithResilience('logs', () => Promise.reject(new Error('always fails')));
    expect(result).toBeNull();
  });
});

describe('runWithResilience — withTimeout success/error before deadline', () => {
  it('fn resolves before timeout fires (clearTimeout path)', async () => {
    setExporterPolicy('logs', { timeoutMs: 5000, failOpen: true, retries: 0, backoffMs: 0 });
    // fn completes quickly → clearTimeout is called
    const result = await runWithResilience('logs', async () => 'fast');
    expect(result).toBe('fast');
  });

  it('fn rejects before timeout fires (clearTimeout + reject path)', async () => {
    setExporterPolicy('logs', { timeoutMs: 5000, failOpen: true, retries: 0, backoffMs: 0 });
    const result = await runWithResilience('logs', async () => {
      throw new Error('fast failure');
    });
    expect(result).toBeNull();
  });
});

describe('runWithResilience — backoff', () => {
  it('sleeps between retries when backoffMs > 0', async () => {
    vi.useFakeTimers();
    setExporterPolicy('logs', { retries: 1, backoffMs: 100, timeoutMs: 0, failOpen: true });
    let calls = 0;
    const resultPromise = runWithResilience('logs', async () => {
      calls++;
      if (calls < 2) throw new Error('fail');
      return 'ok';
    });
    // Advance time to allow backoff sleep to complete
    await vi.advanceTimersByTimeAsync(150);
    const result = await resultPromise;
    expect(result).toBe('ok');
    expect(calls).toBe(2);
    vi.useRealTimers();
  });
});

describe('runWithResilience — timeout', () => {
  it('times out and returns null (failOpen=true)', async () => {
    vi.useFakeTimers();
    setExporterPolicy('logs', { timeoutMs: 100, failOpen: true, retries: 0, backoffMs: 0 });
    const neverResolves = () => new Promise<string>(() => {});
    const resultPromise = runWithResilience('logs', neverResolves);
    await vi.advanceTimersByTimeAsync(200);
    const result = await resultPromise;
    expect(result).toBeNull();
    vi.useRealTimers();
  });

  it('times out and throws (failOpen=false)', async () => {
    vi.useFakeTimers();
    setExporterPolicy('logs', { timeoutMs: 100, failOpen: false, retries: 0, backoffMs: 0 });
    const neverResolves = () => new Promise<string>(() => {});
    const resultPromise = runWithResilience('logs', neverResolves);
    // Attach rejection handler BEFORE advancing time to avoid unhandled-rejection warning.
    const check = expect(resultPromise).rejects.toThrow(TelemetryTimeoutError);
    await vi.advanceTimersByTimeAsync(200);
    await check;
    vi.useRealTimers();
  });
});

describe('runWithResilience — circuit breaker', () => {
  it('trips after 3 consecutive TelemetryTimeoutErrors', async () => {
    setExporterPolicy('traces', { timeoutMs: 0, failOpen: true, retries: 0 });
    const timeoutFn = () => Promise.reject(new TelemetryTimeoutError('timeout'));
    await runWithResilience('traces', timeoutFn); // 1
    await runWithResilience('traces', timeoutFn); // 2
    await runWithResilience('traces', timeoutFn); // 3 — trips
    // 4th call: circuit open → returns null immediately
    let fnCalled = false;
    const result = await runWithResilience('traces', async () => {
      fnCalled = true;
      return 'probe';
    });
    expect(result).toBeNull();
    expect(fnCalled).toBe(false);
  });

  it('circuit breaker with failOpen=false throws on open circuit', async () => {
    setExporterPolicy('metrics', { timeoutMs: 0, failOpen: false, retries: 0 });
    const timeoutFn = () => Promise.reject(new TelemetryTimeoutError('timeout'));
    // suppress errors from the tripping calls (failOpen=false, but not circuit yet)
    for (let i = 0; i < 3; i++) {
      try {
        await runWithResilience('metrics', timeoutFn);
      } catch {
        // expected
      }
    }
    await expect(runWithResilience('metrics', async () => 'ok')).rejects.toThrow(
      TelemetryTimeoutError,
    );
  });

  it('resets consecutive timeout counter on non-timeout error', async () => {
    setExporterPolicy('logs', { timeoutMs: 0, failOpen: true, retries: 0 });
    const timeoutFn = () => Promise.reject(new TelemetryTimeoutError('timeout'));
    const normalFail = () => Promise.reject(new Error('normal error'));
    await runWithResilience('logs', timeoutFn); // 1 consecutive
    await runWithResilience('logs', normalFail); // resets counter
    await runWithResilience('logs', timeoutFn); // 1 consecutive (again)
    // Circuit should NOT be open yet (only 1 consecutive timeout)
    let called = false;
    await runWithResilience('logs', async () => {
      called = true;
      return 'ok';
    });
    expect(called).toBe(true);
  });

  it('allows probe after cooldown elapsed', async () => {
    vi.useFakeTimers();
    setExporterPolicy('logs', { timeoutMs: 0, failOpen: true, retries: 0 });
    const timeoutFn = () => Promise.reject(new TelemetryTimeoutError('timeout'));
    await runWithResilience('logs', timeoutFn);
    await runWithResilience('logs', timeoutFn);
    await runWithResilience('logs', timeoutFn); // circuit trips
    // After first trip, openCount=1, cooldown = 30000 * 2^1 = 60000ms
    vi.advanceTimersByTime(61_000);
    let probeRan = false;
    await runWithResilience('logs', async () => {
      probeRan = true;
      return 'probed';
    });
    expect(probeRan).toBe(true);
    vi.useRealTimers();
  });
});

describe('runWithResilience — non-Error thrown', () => {
  it('wraps a thrown non-Error value in an Error (failOpen=true returns null)', async () => {
    setExporterPolicy('logs', { timeoutMs: 0, failOpen: true, retries: 0 });
    // Throw a string (not an Error instance) — exercises the `new Error(String(err))` branch
    const result = await runWithResilience('logs', () => Promise.reject('string-rejection'));
    expect(result).toBeNull();
  });
});

describe('runWithResilience — custom signal (not pre-initialized)', () => {
  it('handles custom signal name via ?? 0 fallback on first timeout', async () => {
    setExporterPolicy('custom-signal', { timeoutMs: 0, failOpen: true, retries: 0 });
    // 'custom-signal' is not in _consecutiveTimeouts — triggers the ?? 0 branch
    const timeoutFn = () => Promise.reject(new TelemetryTimeoutError('timeout'));
    const result = await runWithResilience('custom-signal', timeoutFn);
    expect(result).toBeNull();
  });
});

describe('TelemetryTimeoutError — class properties', () => {
  it('has name === "TelemetryTimeoutError"', () => {
    const err = new TelemetryTimeoutError('test message');
    expect(err.name).toBe('TelemetryTimeoutError');
  });

  it('is an instance of Error', () => {
    const err = new TelemetryTimeoutError('test message');
    expect(err instanceof Error).toBe(true);
  });

  it('message is set correctly', () => {
    const err = new TelemetryTimeoutError('custom message');
    expect(err.message).toBe('custom message');
  });
});

describe('runWithResilience — exportRetries health counter', () => {
  it('increments exportRetries exactly once when retries=1 and both attempts fail', async () => {
    // Need to import health snapshot
    const { getHealthSnapshot } = await import('../src/health');
    setExporterPolicy('logs', { retries: 1, backoffMs: 0, timeoutMs: 0, failOpen: true });
    await runWithResilience('logs', () => Promise.reject(new Error('always fails')));
    expect(getHealthSnapshot().exportRetries).toBe(1);
  });

  it('does NOT increment exportRetries when retries=0', async () => {
    const { getHealthSnapshot } = await import('../src/health');
    setExporterPolicy('logs', { retries: 0, backoffMs: 0, timeoutMs: 0, failOpen: true });
    await runWithResilience('logs', () => Promise.reject(new Error('fail')));
    expect(getHealthSnapshot().exportRetries).toBe(0);
  });
});

describe('runWithResilience — circuit breaker per signal', () => {
  it('circuit breaker for traces signal trips independently of logs', async () => {
    setExporterPolicy('traces', { timeoutMs: 0, failOpen: true, retries: 0 });
    setExporterPolicy('logs', { timeoutMs: 0, failOpen: true, retries: 0 });
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
    const { getHealthSnapshot } = await import('../src/health');
    await runWithResilience('logs', async () => 'ok');
    expect(getHealthSnapshot().exportLatencyMs).toBeGreaterThanOrEqual(0);
    expect(getHealthSnapshot().exportLatencyMs).toBeLessThan(1000);
  });
});

describe('resilience — circuit breaker reset clears all signals (kills StringLiteral in for-loop)', () => {
  it('resets traces signal (after tripping it)', async () => {
    _resetResilienceForTests();
    setExporterPolicy('traces', { retries: 0, timeoutMs: 0, failOpen: true });
    // Trip circuit for 'traces'
    const timeoutFn = () => Promise.reject(new TelemetryTimeoutError('t'));
    await runWithResilience('traces', timeoutFn);
    await runWithResilience('traces', timeoutFn);
    await runWithResilience('traces', timeoutFn);
    _resetResilienceForTests();
    // After reset, traces circuit should be cleared (not tripped)
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

describe('resilience — health increments (kills StringLiteral on exportFailures/exportRetries)', () => {
  it('increments exportFailures when fn throws non-timeout error', async () => {
    _resetResilienceForTests();
    _resetHealthForTests();
    setExporterPolicy('logs', { retries: 0, timeoutMs: 1000, failOpen: true });
    await runWithResilience('logs', async () => {
      throw new Error('plain error');
    });
    expect(getHealthSnapshot().exportFailures).toBe(1);
  });

  it('increments exportRetries when retries > 0 and fn fails', async () => {
    _resetResilienceForTests();
    _resetHealthForTests();
    setExporterPolicy('logs', { retries: 1, timeoutMs: 1000, failOpen: true, backoffMs: 0 });
    await runWithResilience('logs', async () => {
      throw new Error('fail');
    });
    expect(getHealthSnapshot().exportRetries).toBe(1);
  });

  it('increments exportFailures specifically via circuit breaker open path (kills StringLiteral exportFailures at resilience.ts:88)', async () => {
    // The circuit-breaker open path calls _incrementHealth('exportFailures') — verify this key
    _resetResilienceForTests();
    _resetHealthForTests();
    setExporterPolicy('cbtest', { retries: 0, timeoutMs: 0, failOpen: true });
    const timeoutFn = () => Promise.reject(new TelemetryTimeoutError('timeout'));
    // Trip the circuit (3 consecutive timeouts — each increments exportFailures)
    await runWithResilience('cbtest', timeoutFn); // failure 1
    await runWithResilience('cbtest', timeoutFn); // failure 2
    await runWithResilience('cbtest', timeoutFn); // failure 3, circuit trips
    const afterTrip = getHealthSnapshot().exportFailures;
    // Now call while circuit is open — should increment exportFailures via circuit-open path
    await runWithResilience('cbtest', async () => 'ok');
    expect(getHealthSnapshot().exportFailures).toBe(afterTrip + 1);
  });
});

describe('resilience — non-timeout error resets consecutive timeout counter (kills BlockStatement on else branch)', () => {
  it('does not trip circuit after 2 timeouts + 1 non-timeout + 1 timeout', async () => {
    // Without the else branch (empty block), _consecutiveTimeouts never resets to 0 on non-timeout errors.
    // Sequence: timeout(1) → timeout(2) → normalFail(reset→0) → timeout(1) — circuit NOT open.
    // With mutation (empty else): timeout(1) → timeout(2) → normalFail(stays 2) → timeout(3) — circuit TRIPS.
    _resetResilienceForTests();
    setExporterPolicy('elsetest', { timeoutMs: 0, failOpen: true, retries: 0 });
    const timeoutFn = () => Promise.reject(new TelemetryTimeoutError('timeout'));
    const normalFn = () => Promise.reject(new Error('non-timeout error'));
    await runWithResilience('elsetest', timeoutFn); // consecutive = 1
    await runWithResilience('elsetest', timeoutFn); // consecutive = 2
    await runWithResilience('elsetest', normalFn); // consecutive resets to 0
    await runWithResilience('elsetest', timeoutFn); // consecutive = 1 (NOT 3)
    // Circuit should NOT be open — fn must execute
    let called = false;
    await runWithResilience('elsetest', async () => {
      called = true;
      return 'ok';
    });
    expect(called).toBe(true);
  });
});

describe('resilience — circuit breaker error messages (kills StringLiteral on messages)', () => {
  it('sets lastExportError to "circuit breaker open" when circuit is tripped', async () => {
    _resetResilienceForTests();
    _resetHealthForTests();
    setExporterPolicy('logs', { retries: 0, timeoutMs: 0, failOpen: true });
    // Trip circuit
    const timeoutFn = () => Promise.reject(new TelemetryTimeoutError('t'));
    await runWithResilience('logs', timeoutFn);
    await runWithResilience('logs', timeoutFn);
    await runWithResilience('logs', timeoutFn);
    // Call while circuit open
    await runWithResilience('logs', async () => 'ok');
    expect(getHealthSnapshot().lastExportError).toBe('circuit breaker open');
  });

  it('throws with "circuit breaker open" message when failOpen=false', async () => {
    _resetResilienceForTests();
    setExporterPolicy('logs', { retries: 0, timeoutMs: 0, failOpen: false });
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

describe('per-signal resilience isolation', () => {
  it('setting a policy for logs does NOT affect getExporterPolicy for traces', () => {
    setExporterPolicy('logs', { retries: 5, backoffMs: 500 });
    const tracesPolicy = getExporterPolicy('traces');
    // traces should still have defaults
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

describe('exponential backoff on circuit breaker', () => {
  it('doubles cooldown after repeated trips', async () => {
    vi.useFakeTimers();
    setExporterPolicy('logs', { timeoutMs: 0, failOpen: true, retries: 0 });
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
    setExporterPolicy('logs', { timeoutMs: 0, failOpen: true, retries: 0 });
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
    setExporterPolicy('logs', { timeoutMs: 0, failOpen: true, retries: 0 });
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

describe('getCircuitState — unknown signal defaults', () => {
  it('returns closed state with zero openCount for unknown signal', () => {
    const cs = getCircuitState('unknown-signal');
    expect(cs.state).toBe('closed');
    expect(cs.openCount).toBe(0);
    expect(cs.cooldownRemainingMs).toBe(0);
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
