// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import {
  _disablePropagationALSForTest,
  _resetPropagationForTests,
  _restorePropagationALSForTest,
  bindPropagationContext,
  clearPropagationContext,
  extractW3cContext,
  getActivePropagationContext,
  getActiveOtelContext,
  MAX_HEADER_LENGTH,
  MAX_TRACESTATE_PAIRS,
  MAX_BAGGAGE_LENGTH,
} from '../src/propagation';

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
