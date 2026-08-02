// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Fuzz the propagation surface — the only input that arrives from the network.
 *
 * Every other input to this package comes from the operator (env vars, config
 * objects) or the developer (log calls). W3C headers arrive from whoever made the
 * HTTP request, so these parsers are the attack surface, and the invariants below
 * are the ones an attacker must not be able to break:
 *
 * - nothing throws, whatever the bytes;
 * - a parsed trace/span id is always well-formed hex of the right length, so a
 *   malformed inbound header can never poison an outbound one;
 * - baggage keys are always RFC 7230 tokens and values never carry control
 *   characters, so a key can never forge a log record.
 *
 * Mirrors tests/fuzz in Python, go/fuzz_test.go and rust/tests/fuzz_test.rs.
 */

import fc from 'fast-check';
import { describe, expect, it } from 'vitest';
import { extractW3cContext, parseBaggage } from '../../src/propagation.js';

const HEX = '0123456789abcdef';
const TOKEN_RE = /^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$/;
// eslint-disable-next-line no-control-regex -- detecting control characters is the point
const CONTROL_RE = /[\x00-\x08\x0a-\x1f\x7f]/;
const ZERO_TRACE = '0'.repeat(32);
const ZERO_SPAN = '0'.repeat(16);

const anyText = fc.string({ maxLength: 2048 });
const hex = (n: number) =>
  fc
    .array(fc.constantFrom(...HEX.split('')), { minLength: n, maxLength: n })
    .map((a) => a.join(''));

describe('propagation fuzz', () => {
  it('parseBaggage never throws', () => {
    fc.assert(
      fc.property(anyText, (raw) => {
        parseBaggage(raw);
      }),
      { numRuns: 400 },
    );
  });

  it('parseBaggage keys are always RFC 7230 tokens', () => {
    fc.assert(
      fc.property(anyText, (raw) => {
        for (const key of Object.keys(parseBaggage(raw))) {
          expect(TOKEN_RE.test(key), `non-token key survived: ${JSON.stringify(key)}`).toBe(true);
        }
      }),
      { numRuns: 400 },
    );
  });

  it('parseBaggage values never carry control characters', () => {
    fc.assert(
      fc.property(anyText, (raw) => {
        for (const value of Object.values(parseBaggage(raw))) {
          expect(CONTROL_RE.test(value), `control char survived: ${JSON.stringify(value)}`).toBe(
            false,
          );
        }
      }),
      { numRuns: 400 },
    );
  });

  it('extractW3cContext never throws', () => {
    fc.assert(
      fc.property(anyText, anyText, anyText, (tp, ts, bg) => {
        extractW3cContext({ traceparent: tp, tracestate: ts, baggage: bg });
      }),
      { numRuns: 400 },
    );
  });

  it('parsed ids are always well-formed, or absent together', () => {
    fc.assert(
      fc.property(anyText, (tp) => {
        const ctx = extractW3cContext({ traceparent: tp });

        if (ctx.traceId != null) {
          expect(ctx.traceId).toMatch(/^[0-9a-f]{32}$/);
          expect(ctx.traceId).not.toBe(ZERO_TRACE);
        }
        if (ctx.spanId != null) {
          expect(ctx.spanId).toMatch(/^[0-9a-f]{16}$/);
          expect(ctx.spanId).not.toBe(ZERO_SPAN);
        }
        // All-or-nothing: a half-parsed header must not be forwarded.
        expect(ctx.traceId == null).toBe(ctx.spanId == null);
        if (ctx.traceId == null) {
          expect(ctx.traceparent == null).toBe(true);
        }
      }),
      { numRuns: 400 },
    );
  });

  it('well-formed traceparents round-trip', () => {
    fc.assert(
      fc.property(hex(32), hex(16), (traceId, spanId) => {
        fc.pre(traceId !== ZERO_TRACE && spanId !== ZERO_SPAN);
        const header = `00-${traceId}-${spanId}-01`;

        const ctx = extractW3cContext({ traceparent: header });

        expect(ctx.traceId).toBe(traceId);
        expect(ctx.spanId).toBe(spanId);
        expect(ctx.traceparent).toBe(header);
      }),
      { numRuns: 200 },
    );
  });
});
