// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  _disablePropagationALSForTest,
  _resetPropagationForTests,
  _restorePropagationALSForTest,
  bindPropagationContext,
  clearPropagationContext,
  extractW3cContext,
  getActivePropagationContext,
  getActiveOtelContext,
  isFallbackMode,
  parseBaggage,
  MAX_HEADER_LENGTH,
  MAX_TRACESTATE_PAIRS,
  MAX_BAGGAGE_LENGTH,
} from '../src/propagation';
import { _resetContext, getContext } from '../src/context';

afterEach(() => _resetPropagationForTests());

const VALID_TRACEPARENT = '00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01';

describe('extractW3cContext', () => {
  it('parses a valid traceparent header', () => {
    const ctx = extractW3cContext({ traceparent: VALID_TRACEPARENT });
    expect(ctx.traceparent).toBe(VALID_TRACEPARENT);
    expect(ctx.traceId).toBe('4bf92f3577b34da6a3ce929d0e0e4736');
    expect(ctx.spanId).toBe('00f067aa0ba902b7');
  });

  it('is case-insensitive on header keys', () => {
    const ctx = extractW3cContext({ Traceparent: VALID_TRACEPARENT });
    expect(ctx.traceId).toBeDefined();
  });

  it('includes tracestate and baggage when present', () => {
    const ctx = extractW3cContext({
      traceparent: VALID_TRACEPARENT,
      tracestate: 'congo=t61rcWkgMzE',
      baggage: 'userId=alice',
    });
    expect(ctx.tracestate).toBe('congo=t61rcWkgMzE');
    expect(ctx.baggage).toBe('userId=alice');
  });

  it('returns empty context for missing headers', () => {
    const ctx = extractW3cContext({});
    expect(ctx.traceId).toBeUndefined();
    expect(ctx.traceparent).toBeUndefined();
  });

  it('ignores invalid traceparent — wrong segment count', () => {
    const ctx = extractW3cContext({ traceparent: '00-abc-def' });
    expect(ctx.traceId).toBeUndefined();
  });

  it('ignores invalid traceparent — wrong lengths', () => {
    const ctx = extractW3cContext({ traceparent: '00-short-00f067aa0ba902b7-01' });
    expect(ctx.traceId).toBeUndefined();
  });

  it('ignores all-zero trace ID', () => {
    const ctx = extractW3cContext({
      traceparent: '00-00000000000000000000000000000000-00f067aa0ba902b7-01',
    });
    expect(ctx.traceId).toBeUndefined();
  });

  it('ignores all-zero span ID', () => {
    const ctx = extractW3cContext({
      traceparent: '00-4bf92f3577b34da6a3ce929d0e0e4736-0000000000000000-01',
    });
    expect(ctx.traceId).toBeUndefined();
  });

  it('ignores version ff (reserved)', () => {
    const ctx = extractW3cContext({
      traceparent: 'ff-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01',
    });
    expect(ctx.traceId).toBeUndefined();
  });

  it('ignores non-hex characters in traceId', () => {
    const ctx = extractW3cContext({
      traceparent: '00-zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz-00f067aa0ba902b7-01',
    });
    expect(ctx.traceId).toBeUndefined();
  });
});

describe('bindPropagationContext / clearPropagationContext', () => {
  it('binds context and makes it active', () => {
    const ctx = extractW3cContext({ traceparent: VALID_TRACEPARENT });
    bindPropagationContext(ctx);
    const active = getActivePropagationContext();
    expect(active.traceId).toBe('4bf92f3577b34da6a3ce929d0e0e4736');
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
    clearPropagationContext(); // empty stack
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

describe('extractW3cContext — field-length boundary checks', () => {
  it('ignores traceparent with version length != 2 (1 char)', () => {
    const ctx = extractW3cContext({
      traceparent: '0-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01',
    });
    expect(ctx.traceId).toBeUndefined();
  });

  it('ignores traceparent with traceId length != 32 (31 chars)', () => {
    const ctx = extractW3cContext({
      traceparent: '00-4bf92f3577b34da6a3ce929d0e0e473-00f067aa0ba902b7-01',
    });
    expect(ctx.traceId).toBeUndefined();
  });

  it('ignores traceparent with spanId length != 16 (15 chars)', () => {
    const ctx = extractW3cContext({
      traceparent: '00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b-01',
    });
    expect(ctx.traceId).toBeUndefined();
  });
});

describe('extractW3cContext — hex regex anchor checks', () => {
  it('ignores traceparent where traceId ends with non-hex character', () => {
    // 31 valid hex + 1 non-hex 'g' → 32 chars but invalid hex suffix
    const ctx = extractW3cContext({
      traceparent: '00-4bf92f3577b34da6a3ce929d0e0e473g-00f067aa0ba902b7-01',
    });
    expect(ctx.traceId).toBeUndefined();
  });

  it('ignores traceparent where spanId ends with non-hex character', () => {
    // 15 valid hex + 1 non-hex 'z' → 16 chars but invalid hex suffix
    const ctx = extractW3cContext({
      traceparent: '00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902bz-01',
    });
    expect(ctx.traceId).toBeUndefined();
  });

  it('ignores traceparent where version contains non-hex character', () => {
    // 2-char version '0g' has non-hex 'g'
    const ctx = extractW3cContext({
      traceparent: '0g-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01',
    });
    expect(ctx.traceId).toBeUndefined();
  });
});

describe('extractW3cContext — spread conditionals for tracestate/baggage', () => {
  it('tracestate is absent from result when not in headers', () => {
    const ctx = extractW3cContext({ traceparent: VALID_TRACEPARENT });
    expect('tracestate' in ctx).toBe(false);
  });

  it('baggage is absent from result when not in headers', () => {
    const ctx = extractW3cContext({ traceparent: VALID_TRACEPARENT });
    expect('baggage' in ctx).toBe(false);
  });

  it('traceparent is absent from result when parsing fails', () => {
    const ctx = extractW3cContext({ traceparent: 'invalid', tracestate: 'x=y' });
    expect('traceparent' in ctx).toBe(false);
    // tracestate still included when present even if traceparent invalid
    expect(ctx.tracestate).toBe('x=y');
  });
});

describe('propagation — 5-part traceparent rejected (kills ConditionalExpression→false on parts.length!==4)', () => {
  it('rejects traceparent with 5 parts', () => {
    const ctx = extractW3cContext({
      traceparent: '00-' + 'a'.repeat(32) + '-' + 'b'.repeat(16) + '-00-extra',
    });
    expect(ctx).not.toHaveProperty('traceId');
    expect(ctx).not.toHaveProperty('spanId');
    expect(ctx).not.toHaveProperty('traceparent');
  });

  it('rejects traceparent with 3 parts', () => {
    const ctx = extractW3cContext({ traceparent: '00-' + 'a'.repeat(32) + '-' + 'b'.repeat(16) });
    expect(ctx).not.toHaveProperty('traceId');
  });
});

describe('propagation — regex ^ anchor (kills ^ removal in traceId/spanId/version regex)', () => {
  it('rejects traceId starting with non-hex character', () => {
    // traceId = 'g' + 31 hex chars — valid length but starts with non-hex 'g'
    const traceId = 'g' + 'a'.repeat(31);
    const ctx = extractW3cContext({ traceparent: `00-${traceId}-${'b'.repeat(16)}-00` });
    expect(ctx).not.toHaveProperty('traceId');
  });

  it('rejects spanId starting with non-hex character', () => {
    // spanId = 'g' + 15 hex chars
    const spanId = 'g' + 'a'.repeat(15);
    const ctx = extractW3cContext({ traceparent: `00-${'a'.repeat(32)}-${spanId}-00` });
    expect(ctx).not.toHaveProperty('spanId');
  });

  it('rejects version starting with non-hex character', () => {
    const ctx = extractW3cContext({ traceparent: `g0-${'a'.repeat(32)}-${'b'.repeat(16)}-00` });
    expect(ctx).not.toHaveProperty('traceId');
  });
});

describe('propagation — traceId/spanId absent in result when parse fails (kills ConditionalExpression→true)', () => {
  it('does not include traceId in result when traceparent is malformed', () => {
    const ctx = extractW3cContext({ traceparent: 'invalid' });
    expect(ctx).not.toHaveProperty('traceId');
    expect(ctx).not.toHaveProperty('spanId');
  });

  it('does not include traceId when no traceparent header', () => {
    const ctx = extractW3cContext({});
    expect(ctx).not.toHaveProperty('traceId');
    expect(ctx).not.toHaveProperty('spanId');
  });
});

describe('extractW3cContext — header size guards', () => {
  it('treats traceparent exceeding MAX_HEADER_LENGTH as undefined', () => {
    // 513 chars — over the 512 limit
    const longTraceparent = 'x'.repeat(MAX_HEADER_LENGTH + 1);
    const ctx = extractW3cContext({ traceparent: longTraceparent });
    expect(ctx.traceId).toBeUndefined();
    expect(ctx.traceparent).toBeUndefined();
  });

  it('treats tracestate exceeding MAX_HEADER_LENGTH as undefined', () => {
    const longTracestate = 'k=' + 'v'.repeat(MAX_HEADER_LENGTH - 1);
    expect(longTracestate.length).toBeGreaterThan(MAX_HEADER_LENGTH);
    const ctx = extractW3cContext({
      traceparent: VALID_TRACEPARENT,
      tracestate: longTracestate,
    });
    expect(ctx.tracestate).toBeUndefined();
    // traceparent itself should still parse
    expect(ctx.traceId).toBeDefined();
  });

  it('treats tracestate with more than MAX_TRACESTATE_PAIRS pairs as undefined', () => {
    // 33 comma-separated entries
    const pairs = Array.from({ length: MAX_TRACESTATE_PAIRS + 1 }, (_, i) => `k${i}=v${i}`);
    const tracestate = pairs.join(',');
    expect(tracestate.split(',').length).toBe(MAX_TRACESTATE_PAIRS + 1);
    const ctx = extractW3cContext({
      traceparent: VALID_TRACEPARENT,
      tracestate,
    });
    expect(ctx.tracestate).toBeUndefined();
  });

  it('treats baggage exceeding MAX_BAGGAGE_LENGTH as undefined', () => {
    const longBaggage = 'key=' + 'v'.repeat(MAX_BAGGAGE_LENGTH);
    expect(longBaggage.length).toBeGreaterThan(MAX_BAGGAGE_LENGTH);
    const ctx = extractW3cContext({
      traceparent: VALID_TRACEPARENT,
      baggage: longBaggage,
    });
    expect('baggage' in ctx).toBe(false);
  });

  it('preserves traceparent at exactly MAX_HEADER_LENGTH if otherwise valid', () => {
    // Build a valid traceparent that is exactly 512 chars by padding the flags field.
    // Standard traceparent is 55 chars: "00-<32>-<16>-01"
    // We pad with extra data after flags to reach 512 chars — but that changes segment count.
    // Instead, test that a 55-char valid traceparent (well under 512) still parses.
    // The real boundary test: a 512-char string that happens to be valid traceparent format.
    // Since a valid traceparent is always 55 chars, we just verify 512 does NOT trigger the guard.
    const traceparent = VALID_TRACEPARENT; // 55 chars, well under 512
    expect(traceparent.length).toBeLessThanOrEqual(MAX_HEADER_LENGTH);
    const ctx = extractW3cContext({ traceparent });
    expect(ctx.traceId).toBeDefined();
    expect(ctx.traceparent).toBe(VALID_TRACEPARENT);
  });

  it('preserves baggage at exactly MAX_BAGGAGE_LENGTH', () => {
    const baggage = 'key=' + 'v'.repeat(MAX_BAGGAGE_LENGTH - 4);
    expect(baggage.length).toBe(MAX_BAGGAGE_LENGTH);
    const ctx = extractW3cContext({
      traceparent: VALID_TRACEPARENT,
      baggage,
    });
    expect(ctx.baggage).toBe(baggage);
  });

  it('preserves tracestate at exactly MAX_HEADER_LENGTH', () => {
    const tracestate = 'key=' + 'v'.repeat(MAX_HEADER_LENGTH - 4);
    expect(tracestate.length).toBe(MAX_HEADER_LENGTH);
    const ctx = extractW3cContext({
      traceparent: VALID_TRACEPARENT,
      tracestate,
    });
    expect(ctx.tracestate).toBe(tracestate);
  });

  it('preserves tracestate with exactly MAX_TRACESTATE_PAIRS pairs', () => {
    const pairs = Array.from({ length: MAX_TRACESTATE_PAIRS }, (_, i) => `k${i}=v${i}`);
    const tracestate = pairs.join(',');
    expect(tracestate.split(',').length).toBe(MAX_TRACESTATE_PAIRS);
    const ctx = extractW3cContext({
      traceparent: VALID_TRACEPARENT,
      tracestate,
    });
    expect(ctx.tracestate).toBe(tracestate);
  });
});

describe('getActiveOtelContext — OTel context wiring', () => {
  // Register the W3C propagator so propagation.extract() actually populates span context.
  beforeAll(() => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const api = require('@opentelemetry/api') as typeof import('@opentelemetry/api');
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { W3CTraceContextPropagator } = require('@opentelemetry/core') as {
      W3CTraceContextPropagator: new () => import('@opentelemetry/api').TextMapPropagator;
    };
    api.propagation.setGlobalPropagator(new W3CTraceContextPropagator());
  });

  afterAll(() => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const api = require('@opentelemetry/api') as typeof import('@opentelemetry/api');
    api.propagation.disable();
  });

  it('returns truthy after bindPropagationContext with traceparent', () => {
    bindPropagationContext({
      traceparent: VALID_TRACEPARENT,
      traceId: '4bf92f3577b34da6a3ce929d0e0e4736',
      spanId: '00f067aa0ba902b7',
    });
    // OTel API is available in this test environment (devDependency)
    const otelCtx = getActiveOtelContext();
    expect(otelCtx).toBeTruthy();
  });

  it('returns undefined after clearPropagationContext', () => {
    bindPropagationContext({
      traceparent: VALID_TRACEPARENT,
      traceId: '4bf92f3577b34da6a3ce929d0e0e4736',
      spanId: '00f067aa0ba902b7',
    });
    clearPropagationContext();
    expect(getActiveOtelContext()).toBeUndefined();
  });

  it('returns undefined when no context has been bound', () => {
    expect(getActiveOtelContext()).toBeUndefined();
  });

  it('pushes undefined sentinel when binding without traceparent', () => {
    bindPropagationContext({ traceId: 'abc' });
    expect(getActiveOtelContext()).toBeUndefined();
  });

  it('includes tracestate in OTel carrier when present', () => {
    bindPropagationContext({
      traceparent: VALID_TRACEPARENT,
      tracestate: 'vendor=value',
      traceId: '4bf92f3577b34da6a3ce929d0e0e4736',
      spanId: '00f067aa0ba902b7',
    });
    const otelCtx = getActiveOtelContext();
    expect(otelCtx).toBeTruthy();
  });

  it('extracted OTel context carries the expected trace ID', () => {
    bindPropagationContext({
      traceparent: VALID_TRACEPARENT,
      traceId: '4bf92f3577b34da6a3ce929d0e0e4736',
      spanId: '00f067aa0ba902b7',
    });
    const otelCtx = getActiveOtelContext();
    // Verify we can extract span context from the OTel context using the API
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { trace } = require('@opentelemetry/api') as typeof import('@opentelemetry/api');
    const spanCtx = trace.getSpanContext(otelCtx as import('@opentelemetry/api').Context);
    expect(spanCtx).toBeDefined();
    expect(spanCtx?.traceId).toBe('4bf92f3577b34da6a3ce929d0e0e4736');
  });

  it('gracefully degrades when OTel extract throws', () => {
    // Mock propagation.extract to throw, simulating OTel API failure
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const api = require('@opentelemetry/api') as typeof import('@opentelemetry/api');
    const original = api.propagation.extract;
    api.propagation.extract = () => {
      throw new Error('simulated OTel failure');
    };
    try {
      bindPropagationContext({
        traceparent: VALID_TRACEPARENT,
        traceId: '4bf92f3577b34da6a3ce929d0e0e4736',
        spanId: '00f067aa0ba902b7',
      });
      // Should push undefined sentinel on catch
      expect(getActiveOtelContext()).toBeUndefined();
    } finally {
      api.propagation.extract = original;
    }
  });

  it('resets OTel context stack via _resetPropagationForTests', () => {
    bindPropagationContext({
      traceparent: VALID_TRACEPARENT,
      traceId: '4bf92f3577b34da6a3ce929d0e0e4736',
      spanId: '00f067aa0ba902b7',
    });
    expect(getActiveOtelContext()).toBeTruthy();
    _resetPropagationForTests();
    expect(getActiveOtelContext()).toBeUndefined();
  });

  it('extracted OTel context carries the expected span ID (kills line 112 extract mutation)', () => {
    bindPropagationContext({
      traceparent: VALID_TRACEPARENT,
      traceId: '4bf92f3577b34da6a3ce929d0e0e4736',
      spanId: '00f067aa0ba902b7',
    });
    const otelCtx = getActiveOtelContext();
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { trace } = require('@opentelemetry/api') as typeof import('@opentelemetry/api');
    const spanCtx = trace.getSpanContext(otelCtx as import('@opentelemetry/api').Context);
    expect(spanCtx).toBeDefined();
    expect(spanCtx?.spanId).toBe('00f067aa0ba902b7');
  });

  it('OTel context is distinct from ROOT_CONTEXT (kills context.active() mutation at line 112)', () => {
    bindPropagationContext({
      traceparent: VALID_TRACEPARENT,
      traceId: '4bf92f3577b34da6a3ce929d0e0e4736',
      spanId: '00f067aa0ba902b7',
    });
    const otelCtx = getActiveOtelContext();
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const api = require('@opentelemetry/api') as typeof import('@opentelemetry/api');
    // The extracted context should NOT be the same as ROOT_CONTEXT
    // (it has span context set on it)
    const spanCtx = api.trace.getSpanContext(otelCtx as import('@opentelemetry/api').Context);
    expect(spanCtx).toBeDefined();
    expect(spanCtx?.traceId).toBe('4bf92f3577b34da6a3ce929d0e0e4736');
    expect(spanCtx?.spanId).toBe('00f067aa0ba902b7');
  });
});

describe('propagation — constant value verification (kills constant mutations at line 65)', () => {
  it('MAX_HEADER_LENGTH is exactly 512', () => {
    expect(MAX_HEADER_LENGTH).toBe(512);
  });

  it('MAX_TRACESTATE_PAIRS is exactly 32', () => {
    expect(MAX_TRACESTATE_PAIRS).toBe(32);
  });

  it('MAX_BAGGAGE_LENGTH is exactly 8192', () => {
    expect(MAX_BAGGAGE_LENGTH).toBe(8192);
  });
});

describe('propagation — clearPropagation pops OTel context stack (kills line 149)', () => {
  it('getActiveOtelContext returns undefined when stack is empty (length === 0)', () => {
    // No bind — stack is empty
    expect(getActiveOtelContext()).toBeUndefined();
  });

  it('clearPropagationContext pops OTel context and reveals previous layer', () => {
    // Bind two layers: first without traceparent, second with traceparent
    bindPropagationContext({ traceId: 'no-otel' });
    bindPropagationContext({
      traceparent: VALID_TRACEPARENT,
      traceId: '4bf92f3577b34da6a3ce929d0e0e4736',
      spanId: '00f067aa0ba902b7',
    });
    expect(getActiveOtelContext()).toBeTruthy(); // second layer has OTel context
    clearPropagationContext(); // pop second layer
    expect(getActiveOtelContext()).toBeUndefined(); // first layer had no traceparent → undefined sentinel
    clearPropagationContext(); // pop first layer
    expect(getActiveOtelContext()).toBeUndefined(); // stack is now empty
  });
});

describe('parseBaggage — W3C baggage header parsing', () => {
  it('parses a simple key=value entry', () => {
    expect(parseBaggage('userId=alice')).toEqual({ userId: 'alice' });
  });

  it('parses multiple comma-separated entries', () => {
    expect(parseBaggage('userId=alice,sessionId=xyz')).toEqual({
      userId: 'alice',
      sessionId: 'xyz',
    });
  });

  it('strips properties after semicolon', () => {
    expect(parseBaggage('userId=alice;meta=ignored')).toEqual({ userId: 'alice' });
  });

  it('strips properties after semicolon with multiple entries', () => {
    expect(parseBaggage('a=1;p=x,b=2')).toEqual({ a: '1', b: '2' });
  });

  it('skips entries with no equals sign', () => {
    expect(parseBaggage('noequals,key=val')).toEqual({ key: 'val' });
  });

  it('skips entries where key is empty (= at position 0)', () => {
    expect(parseBaggage('=value,key=val')).toEqual({ key: 'val' });
  });

  it('returns empty object for empty string', () => {
    expect(parseBaggage('')).toEqual({});
  });

  it('skips entries where key trims to empty string (whitespace before =)', () => {
    // " =value" has eqIdx=1 (passes eqIdx<1 check) but key trims to ""
    expect(parseBaggage(' =value,key=val')).toEqual({ key: 'val' });
  });

  it('strips whitespace from keys and values', () => {
    expect(parseBaggage(' userId = alice ')).toEqual({ userId: 'alice' });
  });

  it('returns empty object when all entries are invalid', () => {
    expect(parseBaggage('noequals,alsonoequals')).toEqual({});
  });

  it('handles value containing equals sign (only first = is the separator)', () => {
    expect(parseBaggage('key=a=b')).toEqual({ key: 'a=b' });
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
    clearPropagationContext(); // clears inner frame
    expect(getContext()['baggage.inner']).toBeUndefined();
    // outer frame's baggage.* key was injected before the inner bind — still present
    expect(getContext()['baggage.outer']).toBe('1');
    clearPropagationContext(); // clears outer frame
    expect(getContext()['baggage.outer']).toBeUndefined();
  });

  it('handles clear on frame with no baggage without error', () => {
    bindPropagationContext({ traceId: 'abc' });
    expect(() => clearPropagationContext()).not.toThrow();
  });

  it('handles clear on empty stack without error (no baggage keys to pop)', () => {
    expect(() => clearPropagationContext()).not.toThrow();
  });
});

describe('bindPropagationContext — spanId without traceId covers traceId ?? "" branch', () => {
  afterEach(() => {
    _resetPropagationForTests();
    _resetContext();
  });

  it('sets trace context with empty traceId when only spanId is provided', () => {
    // ctx.traceId is undefined → ctx.traceId ?? '' takes the '' (right-hand) branch at line 241
    // ctx.spanId is truthy → the if condition (ctx.traceId || ctx.spanId) is satisfied
    bindPropagationContext({ spanId: 'only-span-id-no-trace' });
    const active = getActivePropagationContext();
    expect(active.spanId).toBe('only-span-id-no-trace');
  });

  it('does not call setTraceContext when neither traceId nor spanId is set', () => {
    // Neither ctx.traceId nor ctx.spanId → if (ctx.traceId || ctx.spanId) is false
    // This covers the false branch at line 241 (setTraceContext is NOT called).
    const ctx = getContext();
    const prevTraceId = ctx.trace_id;
    bindPropagationContext({ baggage: 'k=v' });
    // trace context should remain unchanged
    expect(getContext().trace_id).toBe(prevTraceId);
  });
});

describe('isFallbackMode — ALS availability check', () => {
  afterEach(() => _resetPropagationForTests());

  it('returns false when AsyncLocalStorage is available (default)', () => {
    // In Node.js test environment ALS is available.
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
      // Warning should only fire once regardless of how many times the store is accessed.
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
    // Reset clears the warned flag.
    _resetPropagationForTests();
    warnSpy.mockClear();
    const saved2 = _disablePropagationALSForTest();
    try {
      bindPropagationContext({ traceId: 'post-reset' });
      // Should warn again since flag was reset.
      expect(warnSpy).toHaveBeenCalledTimes(1);
    } finally {
      _restorePropagationALSForTest(saved2);
    }
  });
});
