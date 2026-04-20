// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  TelemetryTimeoutError,
  _resetResilienceForTests,
  getExporterPolicy,
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
    // timeoutMs > 0 so the breaker gate engages (timeout=0 explicitly bypasses it,
    // matching Python/Go contract). The fn itself rejects synchronously with a
    // TelemetryTimeoutError so the wrapper-imposed timeout never elapses.
    setExporterPolicy('traces', { timeoutMs: 1000, failOpen: true, retries: 0 });
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
    setExporterPolicy('metrics', { timeoutMs: 1000, failOpen: false, retries: 0 });
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

describe('runWithResilience — retriesLogs health counter', () => {
  it('increments retriesLogs exactly once when retries=1 and both attempts fail', async () => {
    // Need to import health snapshot
    const { getHealthSnapshot } = await import('../src/health');
    setExporterPolicy('logs', { retries: 1, backoffMs: 0, timeoutMs: 0, failOpen: true });
    await runWithResilience('logs', () => Promise.reject(new Error('always fails')));
    expect(getHealthSnapshot().retriesLogs).toBe(1);
  });

  it('does NOT increment retriesLogs when retries=0', async () => {
    const { getHealthSnapshot } = await import('../src/health');
    setExporterPolicy('logs', { retries: 0, backoffMs: 0, timeoutMs: 0, failOpen: true });
    await runWithResilience('logs', () => Promise.reject(new Error('fail')));
    expect(getHealthSnapshot().retriesLogs).toBe(0);
  });
});

// Circuit-breaker-specific tests (getCircuitState, half-open probes, exponential backoff,
// state getter/setter functions, per-signal isolation) live in resilience.circuit.test.ts
