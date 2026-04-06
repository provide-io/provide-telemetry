// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Propagation boundary tests for mutation killing.
 * Split from propagation.test.ts to stay under 500 LOC per file.
 */

import { afterEach, describe, expect, it } from 'vitest';
import {
  _resetPropagationForTests,
  extractW3cContext,
  MAX_HEADER_LENGTH,
  MAX_TRACESTATE_PAIRS,
  MAX_BAGGAGE_LENGTH,
} from '../src/propagation';

afterEach(() => _resetPropagationForTests());

const VALID_TRACEPARENT = '00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01';

describe('propagation — traceparent size boundary exactly at 512', () => {
  it('traceparent at exactly MAX_HEADER_LENGTH (512) is not rejected by size guard', () => {
    // Size guard uses > not >=, so 512-char string passes the size guard.
    // Build a 512-char string with no dashes to fail format parsing instead.
    const noDashes = 'a'.repeat(MAX_HEADER_LENGTH);
    expect(noDashes.length).toBe(512);
    const ctx = extractW3cContext({ traceparent: noDashes });
    // Size guard passes, but format parsing rejects (not 4 segments)
    expect(ctx.traceId).toBeUndefined();
    expect(ctx.traceparent).toBeUndefined();
  });

  it('traceparent at 513 bytes is rejected by size guard', () => {
    const oversized = 'x'.repeat(MAX_HEADER_LENGTH + 1);
    expect(oversized.length).toBe(513);
    const ctx = extractW3cContext({ traceparent: oversized });
    expect(ctx.traceparent).toBeUndefined();
    expect(ctx.traceId).toBeUndefined();
  });

  it('valid traceparent (55 chars) is well under limit and accepted', () => {
    expect(VALID_TRACEPARENT.length).toBeLessThan(MAX_HEADER_LENGTH);
    const ctx = extractW3cContext({ traceparent: VALID_TRACEPARENT });
    expect(ctx.traceparent).toBe(VALID_TRACEPARENT);
    expect(ctx.traceId).toBeDefined();
  });
});

describe('propagation — traceId AND spanId must both be non-zero', () => {
  it('all-zero traceId with valid spanId is rejected', () => {
    const ctx = extractW3cContext({
      traceparent: '00-00000000000000000000000000000000-00f067aa0ba902b7-01',
    });
    expect(ctx.traceId).toBeUndefined();
    expect(ctx.spanId).toBeUndefined();
    expect(ctx.traceparent).toBeUndefined();
  });

  it('valid traceId with all-zero spanId is rejected', () => {
    const ctx = extractW3cContext({
      traceparent: '00-4bf92f3577b34da6a3ce929d0e0e4736-0000000000000000-01',
    });
    expect(ctx.traceId).toBeUndefined();
    expect(ctx.spanId).toBeUndefined();
    expect(ctx.traceparent).toBeUndefined();
  });

  it('both all-zero traceId and spanId is rejected', () => {
    const ctx = extractW3cContext({
      traceparent: '00-00000000000000000000000000000000-0000000000000000-01',
    });
    expect(ctx.traceId).toBeUndefined();
    expect(ctx.spanId).toBeUndefined();
  });
});

describe('propagation — baggage parsing with key=value pairs', () => {
  it('baggage with single key=value is preserved', () => {
    const ctx = extractW3cContext({
      traceparent: VALID_TRACEPARENT,
      baggage: 'userId=alice',
    });
    expect(ctx.baggage).toBe('userId=alice');
  });

  it('baggage with multiple key=value pairs is preserved', () => {
    const ctx = extractW3cContext({
      traceparent: VALID_TRACEPARENT,
      baggage: 'userId=alice,sessionId=xyz',
    });
    expect(ctx.baggage).toBe('userId=alice,sessionId=xyz');
  });

  it('baggage at exactly MAX_BAGGAGE_LENGTH is accepted', () => {
    const baggage = 'k=' + 'v'.repeat(MAX_BAGGAGE_LENGTH - 2);
    expect(baggage.length).toBe(MAX_BAGGAGE_LENGTH);
    const ctx = extractW3cContext({
      traceparent: VALID_TRACEPARENT,
      baggage,
    });
    expect(ctx.baggage).toBe(baggage);
  });

  it('baggage at MAX_BAGGAGE_LENGTH+1 is rejected', () => {
    const baggage = 'k=' + 'v'.repeat(MAX_BAGGAGE_LENGTH - 1);
    expect(baggage.length).toBe(MAX_BAGGAGE_LENGTH + 1);
    const ctx = extractW3cContext({
      traceparent: VALID_TRACEPARENT,
      baggage,
    });
    expect('baggage' in ctx).toBe(false);
  });
});

describe('propagation — tracestate pair count boundary', () => {
  it('tracestate with exactly 32 pairs is accepted', () => {
    const pairs = Array.from({ length: MAX_TRACESTATE_PAIRS }, (_, i) => `k${i}=v${i}`);
    const tracestate = pairs.join(',');
    expect(tracestate.split(',').length).toBe(32);
    const ctx = extractW3cContext({
      traceparent: VALID_TRACEPARENT,
      tracestate,
    });
    expect(ctx.tracestate).toBe(tracestate);
  });

  it('tracestate with 33 pairs is rejected', () => {
    const pairs = Array.from({ length: MAX_TRACESTATE_PAIRS + 1 }, (_, i) => `k${i}=v${i}`);
    const tracestate = pairs.join(',');
    expect(tracestate.split(',').length).toBe(33);
    const ctx = extractW3cContext({
      traceparent: VALID_TRACEPARENT,
      tracestate,
    });
    expect(ctx.tracestate).toBeUndefined();
  });
});

describe('propagation — tracestate size boundary', () => {
  it('tracestate at exactly MAX_HEADER_LENGTH (512) is accepted', () => {
    const tracestate = 'k=' + 'v'.repeat(MAX_HEADER_LENGTH - 2);
    expect(tracestate.length).toBe(MAX_HEADER_LENGTH);
    const ctx = extractW3cContext({
      traceparent: VALID_TRACEPARENT,
      tracestate,
    });
    expect(ctx.tracestate).toBe(tracestate);
  });

  it('tracestate at MAX_HEADER_LENGTH+1 (513) is rejected', () => {
    const tracestate = 'k=' + 'v'.repeat(MAX_HEADER_LENGTH - 1);
    expect(tracestate.length).toBe(MAX_HEADER_LENGTH + 1);
    const ctx = extractW3cContext({
      traceparent: VALID_TRACEPARENT,
      tracestate,
    });
    expect(ctx.tracestate).toBeUndefined();
  });
});
