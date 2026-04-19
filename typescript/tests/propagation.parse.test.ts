// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import {
  _resetPropagationForTests,
  bindPropagationContext,
  clearPropagationContext,
  extractW3cContext,
  getActiveOtelContext,
  parseBaggage,
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
    expect(ctx.traceId).toBe('4bf92f3577b34da6a3ce929d0e0e4736'); // pragma: allowlist secret
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
    const ctx = extractW3cContext({
      traceparent: '00-4bf92f3577b34da6a3ce929d0e0e473g-00f067aa0ba902b7-01',
    });
    expect(ctx.traceId).toBeUndefined();
  });

  it('ignores traceparent where spanId ends with non-hex character', () => {
    const ctx = extractW3cContext({
      traceparent: '00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902bz-01',
    });
    expect(ctx.traceId).toBeUndefined();
  });

  it('ignores traceparent where version contains non-hex character', () => {
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
    const traceId = 'g' + 'a'.repeat(31);
    const ctx = extractW3cContext({ traceparent: `00-${traceId}-${'b'.repeat(16)}-00` });
    expect(ctx).not.toHaveProperty('traceId');
  });

  it('rejects spanId starting with non-hex character', () => {
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
    expect(ctx.traceId).toBeDefined();
  });

  it('treats tracestate with more than MAX_TRACESTATE_PAIRS pairs as undefined', () => {
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
    const traceparent = VALID_TRACEPARENT;
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

describe('getActiveOtelContext — OTel context wiring', () => {
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
      traceId: '4bf92f3577b34da6a3ce929d0e0e4736', // pragma: allowlist secret
      spanId: '00f067aa0ba902b7',
    });
    const otelCtx = getActiveOtelContext();
    expect(otelCtx).toBeTruthy();
  });

  it('returns undefined after clearPropagationContext', () => {
    bindPropagationContext({
      traceparent: VALID_TRACEPARENT,
      traceId: '4bf92f3577b34da6a3ce929d0e0e4736', // pragma: allowlist secret
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
      traceId: '4bf92f3577b34da6a3ce929d0e0e4736', // pragma: allowlist secret
      spanId: '00f067aa0ba902b7',
    });
    const otelCtx = getActiveOtelContext();
    expect(otelCtx).toBeTruthy();
  });

  it('extracted OTel context carries the expected trace ID', () => {
    bindPropagationContext({
      traceparent: VALID_TRACEPARENT,
      traceId: '4bf92f3577b34da6a3ce929d0e0e4736', // pragma: allowlist secret
      spanId: '00f067aa0ba902b7',
    });
    const otelCtx = getActiveOtelContext();
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { trace } = require('@opentelemetry/api') as typeof import('@opentelemetry/api');
    const spanCtx = trace.getSpanContext(otelCtx as import('@opentelemetry/api').Context);
    expect(spanCtx).toBeDefined();
    expect(spanCtx?.traceId).toBe('4bf92f3577b34da6a3ce929d0e0e4736'); // pragma: allowlist secret
  });

  it('gracefully degrades when OTel extract throws', () => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const api = require('@opentelemetry/api') as typeof import('@opentelemetry/api');
    const original = api.propagation.extract;
    api.propagation.extract = () => {
      throw new Error('simulated OTel failure');
    };
    try {
      bindPropagationContext({
        traceparent: VALID_TRACEPARENT,
        traceId: '4bf92f3577b34da6a3ce929d0e0e4736', // pragma: allowlist secret
        spanId: '00f067aa0ba902b7',
      });
      expect(getActiveOtelContext()).toBeUndefined();
    } finally {
      api.propagation.extract = original;
    }
  });

  it('resets OTel context stack via _resetPropagationForTests', () => {
    bindPropagationContext({
      traceparent: VALID_TRACEPARENT,
      traceId: '4bf92f3577b34da6a3ce929d0e0e4736', // pragma: allowlist secret
      spanId: '00f067aa0ba902b7',
    });
    expect(getActiveOtelContext()).toBeTruthy();
    _resetPropagationForTests();
    expect(getActiveOtelContext()).toBeUndefined();
  });

  it('extracted OTel context carries the expected span ID (kills line 112 extract mutation)', () => {
    bindPropagationContext({
      traceparent: VALID_TRACEPARENT,
      traceId: '4bf92f3577b34da6a3ce929d0e0e4736', // pragma: allowlist secret
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
      traceId: '4bf92f3577b34da6a3ce929d0e0e4736', // pragma: allowlist secret
      spanId: '00f067aa0ba902b7',
    });
    const otelCtx = getActiveOtelContext();
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const api = require('@opentelemetry/api') as typeof import('@opentelemetry/api');
    const spanCtx = api.trace.getSpanContext(otelCtx as import('@opentelemetry/api').Context);
    expect(spanCtx).toBeDefined();
    expect(spanCtx?.traceId).toBe('4bf92f3577b34da6a3ce929d0e0e4736'); // pragma: allowlist secret
    expect(spanCtx?.spanId).toBe('00f067aa0ba902b7');
  });
});

describe('propagation — clearPropagation pops OTel context stack (kills line 149)', () => {
  it('getActiveOtelContext returns undefined when stack is empty (length === 0)', () => {
    expect(getActiveOtelContext()).toBeUndefined();
  });

  it('clearPropagationContext pops OTel context and reveals previous layer', () => {
    bindPropagationContext({ traceId: 'no-otel' });
    bindPropagationContext({
      traceparent: VALID_TRACEPARENT,
      traceId: '4bf92f3577b34da6a3ce929d0e0e4736', // pragma: allowlist secret
      spanId: '00f067aa0ba902b7',
    });
    expect(getActiveOtelContext()).toBeTruthy();
    clearPropagationContext();
    expect(getActiveOtelContext()).toBeUndefined();
    clearPropagationContext();
    expect(getActiveOtelContext()).toBeUndefined();
  });
});
