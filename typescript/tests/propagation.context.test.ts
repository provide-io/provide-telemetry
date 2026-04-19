// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  _disablePropagationALSForTest,
  _resetPropagationForTests,
  _restorePropagationALSForTest,
  bindPropagationContext,
  clearPropagationContext,
  extractW3cContext,
  getActivePropagationContext,
  isFallbackMode,
} from '../src/propagation';
import { _resetContext, getContext } from '../src/context';
import { getTraceContext, _resetTraceContext } from '../src/tracing';

afterEach(() => _resetPropagationForTests());

const VALID_TRACEPARENT = '00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01';

describe('bindPropagationContext / clearPropagationContext', () => {
  it('binds context and makes it active', () => {
    const ctx = extractW3cContext({ traceparent: VALID_TRACEPARENT });
    bindPropagationContext(ctx);
    const active = getActivePropagationContext();
    expect(active.traceId).toBe('4bf92f3577b34da6a3ce929d0e0e4736'); // pragma: allowlist secret
  });

  it('restores previous context on clear', () => {
    bindPropagationContext({ traceId: 'aaa', spanId: 'bbb' });
    bindPropagationContext({ traceId: 'xxx', spanId: 'yyy' });
    clearPropagationContext();
    const active = getActivePropagationContext();
    expect(active.traceId).toBe('aaa');
    expect(active.spanId).toBe('bbb');
  });

  it('clears to empty when stack is empty', () => {
    bindPropagationContext({ traceId: 'abc' });
    clearPropagationContext();
    clearPropagationContext();
    const active = getActivePropagationContext();
    expect(active.traceId).toBeUndefined();
  });

  it('nested bind/clear restores correctly', () => {
    bindPropagationContext({ traceId: 'outer' });
    bindPropagationContext({ traceId: 'inner' });
    expect(getActivePropagationContext().traceId).toBe('inner');
    clearPropagationContext();
    expect(getActivePropagationContext().traceId).toBe('outer');
    clearPropagationContext();
    expect(getActivePropagationContext().traceId).toBeUndefined();
  });

  it('isolates concurrent propagation contexts when AsyncLocalStorage is available', async () => {
    const first = new Promise(
      (resolve: (value: ReturnType<typeof getActivePropagationContext>) => void) => {
        setTimeout(async () => {
          bindPropagationContext({ traceId: 'first', spanId: '1111' });
          await Promise.resolve();
          const active = getActivePropagationContext();
          clearPropagationContext();
          resolve(active);
        }, 0);
      },
    );

    const second = new Promise(
      (resolve: (value: ReturnType<typeof getActivePropagationContext>) => void) => {
        setTimeout(async () => {
          bindPropagationContext({ traceId: 'second', spanId: '2222' });
          await Promise.resolve();
          const active = getActivePropagationContext();
          clearPropagationContext();
          resolve(active);
        }, 0);
      },
    );

    const [activeFirst, activeSecond] = await Promise.all([first, second]);
    expect(activeFirst.traceId).toBe('first');
    expect(activeSecond.traceId).toBe('second');
  });

  it('falls back to process-global propagation state when ALS is disabled', () => {
    const saved = _disablePropagationALSForTest();
    try {
      bindPropagationContext({ traceId: 'fallback', spanId: '9999' });
      expect(getActivePropagationContext().traceId).toBe('fallback');
      clearPropagationContext();
      expect(getActivePropagationContext().traceId).toBeUndefined();
    } finally {
      _restorePropagationALSForTest(saved);
      _resetPropagationForTests();
    }
  });

  it('clones fallback stack into ALS store when ALS is restored without an active store', () => {
    const saved = _disablePropagationALSForTest();
    try {
      bindPropagationContext({ traceId: 'outer', spanId: '1111' });
      bindPropagationContext({ traceId: 'inner', spanId: '2222' });
    } finally {
      _restorePropagationALSForTest(saved);
    }

    bindPropagationContext({ traceId: 'als', spanId: '3333' });
    expect(getActivePropagationContext().traceId).toBe('als');
    clearPropagationContext();
    expect(getActivePropagationContext().traceId).toBe('inner');
    clearPropagationContext();
    expect(getActivePropagationContext().traceId).toBe('outer');
    clearPropagationContext();
    expect(getActivePropagationContext().traceId).toBeUndefined();
  });
});

describe('bindPropagationContext — baggage.* auto-injection', () => {
  afterEach(() => {
    _resetPropagationForTests();
    _resetContext();
  });

  it('injects baggage entries as baggage.* log context fields', () => {
    bindPropagationContext({ baggage: 'userId=alice,sessionId=xyz' });
    const ctx = getContext();
    expect(ctx['baggage.userId']).toBe('alice');
    expect(ctx['baggage.sessionId']).toBe('xyz');
  });

  it('does not inject baggage.* fields when baggage is absent', () => {
    bindPropagationContext({ traceId: 'abc' });
    const ctx = getContext();
    const baggageKeys = Object.keys(ctx).filter((k) => k.startsWith('baggage.'));
    expect(baggageKeys).toHaveLength(0);
  });

  it('does not inject baggage.* fields when baggage is empty string', () => {
    bindPropagationContext({ baggage: '' });
    const ctx = getContext();
    const baggageKeys = Object.keys(ctx).filter((k) => k.startsWith('baggage.'));
    expect(baggageKeys).toHaveLength(0);
  });
});

describe('clearPropagationContext — baggage.* key removal', () => {
  afterEach(() => {
    _resetPropagationForTests();
    _resetContext();
  });

  it('removes baggage.* keys when the frame is cleared', () => {
    bindPropagationContext({ baggage: 'userId=alice,sessionId=xyz' });
    expect(getContext()['baggage.userId']).toBe('alice');
    clearPropagationContext();
    const ctx = getContext();
    expect(ctx['baggage.userId']).toBeUndefined();
    expect(ctx['baggage.sessionId']).toBeUndefined();
  });

  it('only removes baggage.* keys from the cleared frame, not outer frames', () => {
    bindPropagationContext({ baggage: 'outer=1' });
    bindPropagationContext({ baggage: 'inner=2' });
    expect(getContext()['baggage.outer']).toBe('1');
    expect(getContext()['baggage.inner']).toBe('2');
    clearPropagationContext();
    expect(getContext()['baggage.inner']).toBeUndefined();
    expect(getContext()['baggage.outer']).toBe('1');
    clearPropagationContext();
    expect(getContext()['baggage.outer']).toBeUndefined();
  });

  it('handles clear on frame with no baggage without error', () => {
    bindPropagationContext({ traceId: 'abc' });
    expect(() => clearPropagationContext()).not.toThrow();
  });

  it('handles clear on empty stack without error (no baggage keys to pop)', () => {
    expect(() => clearPropagationContext()).not.toThrow();
  });

  it('restores outer baggage value when inner frame overwrites the same key', () => {
    bindPropagationContext({ baggage: 'foo=outer' });
    expect(getContext()['baggage.foo']).toBe('outer');

    bindPropagationContext({ baggage: 'foo=inner' });
    expect(getContext()['baggage.foo']).toBe('inner');

    clearPropagationContext();
    expect(getContext()['baggage.foo']).toBe('outer');

    clearPropagationContext();
    expect(getContext()['baggage.foo']).toBeUndefined();
  });

  it('unbinds baggage.* key introduced by the frame when no outer value existed', () => {
    bindPropagationContext({ baggage: 'brand-new=1' });
    expect(getContext()['baggage.brand-new']).toBe('1');
    clearPropagationContext();
    expect(getContext()['baggage.brand-new']).toBeUndefined();
  });
});

describe('bindPropagationContext — spanId without traceId covers traceId ?? "" branch', () => {
  beforeEach(() => {
    _resetPropagationForTests();
    _resetTraceContext();
  });
  afterEach(() => {
    _resetPropagationForTests();
    _resetContext();
    _resetTraceContext();
  });

  it('sets trace context with empty traceId when only spanId is provided', () => {
    bindPropagationContext({ spanId: 'only-span-id-no-trace' });
    const active = getActivePropagationContext();
    expect(active.spanId).toBe('only-span-id-no-trace');
  });

  it('does not call setTraceContext when neither traceId nor spanId is set', () => {
    const ctx = getContext();
    const prevTraceId = ctx.trace_id;
    bindPropagationContext({ baggage: 'k=v' });
    expect(getContext().trace_id).toBe(prevTraceId);
  });

  it('traceId without spanId: getTraceContext span_id is absent (not "Stryker was here!" fallback)', () => {
    bindPropagationContext({ traceId: 'aaaa1111bbbb2222cccc3333dddd4444' });
    const tc = getTraceContext();
    expect(tc.trace_id).toBe('aaaa1111bbbb2222cccc3333dddd4444');
    expect(tc.span_id).toBeUndefined();
  });

  it('spanId without traceId: getTraceContext trace_id is absent (kills StringLiteral mutation on ctx.traceId ?? "")', () => {
    bindPropagationContext({ spanId: 'only-span-id-no-trace' });
    const tc = getTraceContext();
    expect(tc.trace_id).toBeUndefined();
  });
});

describe('isFallbackMode — ALS availability check', () => {
  afterEach(() => _resetPropagationForTests());

  it('returns false when AsyncLocalStorage is available (default)', () => {
    expect(isFallbackMode()).toBe(false);
  });

  it('returns true when ALS is disabled', () => {
    const saved = _disablePropagationALSForTest();
    try {
      expect(isFallbackMode()).toBe(true);
    } finally {
      _restorePropagationALSForTest(saved);
    }
  });
});

describe('propagation — fallback warning emitted once', () => {
  beforeEach(() => _resetPropagationForTests());
  afterEach(() => {
    vi.restoreAllMocks();
    _resetPropagationForTests();
  });

  it('emits a console.warn when ALS is unavailable and store is accessed', () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const saved = _disablePropagationALSForTest();
    try {
      bindPropagationContext({ traceId: 'warn-test' });
      expect(warnSpy).toHaveBeenCalledTimes(1);
      expect(warnSpy).toHaveBeenCalledWith(expect.stringContaining('[provide-telemetry]'));
      expect(warnSpy).toHaveBeenCalledWith(
        expect.stringContaining('AsyncLocalStorage is unavailable'),
      );
    } finally {
      _restorePropagationALSForTest(saved);
    }
  });

  it('emits the warning exactly once across multiple store accesses', () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const saved = _disablePropagationALSForTest();
    try {
      bindPropagationContext({ traceId: 'first' });
      getActivePropagationContext();
      bindPropagationContext({ traceId: 'second' });
      getActivePropagationContext();
      expect(warnSpy).toHaveBeenCalledTimes(1);
    } finally {
      _restorePropagationALSForTest(saved);
    }
  });

  it('warning message mentions concurrent request danger', () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const saved = _disablePropagationALSForTest();
    try {
      bindPropagationContext({});
      expect(warnSpy).toHaveBeenCalledWith(
        expect.stringContaining('Concurrent requests will share propagation context'),
      );
    } finally {
      _restorePropagationALSForTest(saved);
    }
  });

  it('warning message mentions falling back to module-level context store (kills StringLiteral mutation on line 66)', () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const saved = _disablePropagationALSForTest();
    try {
      bindPropagationContext({});
      expect(warnSpy).toHaveBeenCalledWith(
        expect.stringContaining('falling back to module-level context store'),
      );
    } finally {
      _restorePropagationALSForTest(saved);
    }
  });

  it('warning message mentions unsafe production async environments (kills StringLiteral mutation on line 68)', () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const saved = _disablePropagationALSForTest();
    try {
      bindPropagationContext({});
      expect(warnSpy).toHaveBeenCalledWith(
        expect.stringContaining('This is unsafe in production async environments'),
      );
    } finally {
      _restorePropagationALSForTest(saved);
    }
  });

  it('_resetPropagationForTests resets the warned flag so warning fires again in next test', () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const saved = _disablePropagationALSForTest();
    try {
      bindPropagationContext({ traceId: 'pre-reset' });
      expect(warnSpy).toHaveBeenCalledTimes(1);
    } finally {
      _restorePropagationALSForTest(saved);
    }
    _resetPropagationForTests();
    warnSpy.mockClear();
    const saved2 = _disablePropagationALSForTest();
    try {
      bindPropagationContext({ traceId: 'post-reset' });
      expect(warnSpy).toHaveBeenCalledTimes(1);
    } finally {
      _restorePropagationALSForTest(saved2);
    }
  });
});

describe('clearPropagationContext — trace context restoration (Bug: empty-string trace IDs)', () => {
  beforeEach(() => {
    _resetPropagationForTests();
    _resetTraceContext();
  });
  afterEach(() => {
    _resetPropagationForTests();
    _resetTraceContext();
  });

  it('getTraceContext() returns {} after bind + clear with no outer context', () => {
    bindPropagationContext({
      traceId: '4bf92f3577b34da6a3ce929d0e0e4736', // pragma: allowlist secret
      spanId: '00f067aa0ba902b7',
    });
    clearPropagationContext();
    expect(getTraceContext()).toEqual({});
  });

  it('getTraceContext() returns {} when called without any bind/clear ever', () => {
    clearPropagationContext();
    expect(getTraceContext()).toEqual({});
  });

  it('nested bind: clearing inner frame restores outer trace ID exactly (not empty string)', () => {
    bindPropagationContext({
      traceId: 'aaaa1111bbbb2222cccc3333dddd4444',
      spanId: '1234567890abcdef', // pragma: allowlist secret
    });
    bindPropagationContext({
      traceId: 'ffff1111eeee2222dddd3333cccc4444',
      spanId: 'fedcba9876543210', // pragma: allowlist secret
    });
    expect(getTraceContext().trace_id).toBe('ffff1111eeee2222dddd3333cccc4444');

    clearPropagationContext();
    expect(getTraceContext().trace_id).toBe('aaaa1111bbbb2222cccc3333dddd4444');
    expect(getTraceContext().span_id).toBe('1234567890abcdef');

    clearPropagationContext();
    expect(getTraceContext()).toEqual({});
  });
});

describe('bindPropagationContext — baggagePriorStack pushed for no-baggage frames (kills line 270 BlockStatement)', () => {
  let _savedAls: ReturnType<typeof _disablePropagationALSForTest>;

  beforeEach(() => {
    _resetPropagationForTests();
    _resetContext();
    _resetTraceContext();
    _savedAls = _disablePropagationALSForTest();
  });

  afterEach(() => {
    _restorePropagationALSForTest(_savedAls);
    _resetPropagationForTests();
    _resetContext();
    _resetTraceContext();
  });

  it('clearing a no-baggage frame after a baggage frame keeps stacks balanced', () => {
    bindPropagationContext({ traceId: 'no-bag' });
    bindPropagationContext({ baggage: 'k=v' });
    expect(getContext()['baggage.k']).toBe('v');
    clearPropagationContext();
    expect(getContext()['baggage.k']).toBeUndefined();
    expect(() => clearPropagationContext()).not.toThrow();
    expect(getActivePropagationContext().traceId).toBeUndefined();
  });

  it('baggagePriorStack depth matches bind depth — no-baggage frames push empty map so pop succeeds', () => {
    bindPropagationContext({ traceId: 'a' });
    bindPropagationContext({ traceId: 'b' });
    bindPropagationContext({ traceId: 'c' });
    clearPropagationContext();
    expect(getActivePropagationContext().traceId).toBe('b');
    clearPropagationContext();
    expect(getActivePropagationContext().traceId).toBe('a');
    clearPropagationContext();
    expect(getActivePropagationContext().traceId).toBeUndefined();
  });

  it('no-baggage frame followed by baggage frame: outer frame baggage.* key is absent after both cleared', () => {
    bindPropagationContext({ traceId: 'outer' });
    bindPropagationContext({ baggage: 'x=1' });
    expect(getContext()['baggage.x']).toBe('1');
    clearPropagationContext();
    expect(getContext()['baggage.x']).toBeUndefined();
    clearPropagationContext();
    expect(getContext()['baggage.x']).toBeUndefined();
    expect(getActivePropagationContext().traceId).toBeUndefined();
  });
});

describe('_resetPropagationForTests — resets fallback stack arrays to empty (kills ArrayDeclaration mutants on lines 330/332/333)', () => {
  let _savedAls: ReturnType<typeof _disablePropagationALSForTest>;

  beforeEach(() => {
    _resetPropagationForTests();
    _resetContext();
    _resetTraceContext();
    _savedAls = _disablePropagationALSForTest();
  });

  afterEach(() => {
    _restorePropagationALSForTest(_savedAls);
    _resetPropagationForTests();
    _resetContext();
    _resetTraceContext();
  });

  it('stack[] is empty after reset — clearPropagationContext on empty stack does not restore stale active context', () => {
    clearPropagationContext();
    const active = getActivePropagationContext();
    expect(active).toEqual({});
    expect(Object.keys(active).length).toBe(0);
  });

  it('baggagePriorStack[] is empty after reset — clearPropagationContext does not iterate over stale string entry', () => {
    clearPropagationContext();
    const ctx = getContext();
    expect(ctx['0']).toBeUndefined();
    expect(ctx['1']).toBeUndefined();
    const numericKeys = Object.keys(ctx).filter((k) => /^\d+$/.test(k));
    expect(numericKeys).toHaveLength(0);
  });

  it('traceCtxStack[] is empty after reset — clearPropagationContext with no bind does not call setTraceContext', () => {
    bindPropagationContext({
      traceId: '4bf92f3577b34da6a3ce929d0e0e4736', // pragma: allowlist secret
      spanId: '00f067aa0ba902b7',
    });
    clearPropagationContext();
    clearPropagationContext();
    expect(getTraceContext()).toEqual({});
  });
});
