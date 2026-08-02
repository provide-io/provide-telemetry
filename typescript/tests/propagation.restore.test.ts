// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Trace-context restoration and fallback-store reset — split out of
 * propagation.context.test.ts to keep both files under the 500-line ceiling
 * enforced by scripts/check_max_loc.py.
 */

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import {
  _disablePropagationALSForTest,
  _resetPropagationForTests,
  _restorePropagationALSForTest,
  bindPropagationContext,
  clearPropagationContext,
  getActivePropagationContext,
} from '../src/propagation.js';
import { _resetContext, getContext } from '../src/context.js';
import { getTraceContext, _resetTraceContext } from '../src/tracing.js';

afterEach(() => _resetPropagationForTests());

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
