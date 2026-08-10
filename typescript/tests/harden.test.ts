// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
//
// Recursive input hardening — the structural stage that runs before
// classification and PII in the canonical signal pipeline.
//
// Before this existed, TypeScript hardened only the top level of the OTel
// export path: one pass of string truncation and an attribute-count cap. A
// nested object went to the exporter unbounded, and a self-referential one
// reached its serializer intact.

import { describe, expect, it } from 'vitest';
import { harden, hardenRecord } from '../src/harden.js';
import { resetPiiRulesForTests, sanitizePayload } from '../src/pii.js';
import { formatPretty } from '../src/pretty.js';

describe('harden — cycles and repeated subtrees', () => {
  it('redacts arrays, objects, and cycles before capture', () => {
    resetPiiRulesForTests();
    const value: Record<string, unknown> = { items: [{ password: 'secret' }] };
    value.self = value;
    // harden is structural: it bounds the shape. Redacting the password is the
    // PII stage that runs immediately after it.
    const hardened = harden(value) as Record<string, unknown>;
    expect(hardened['self']).toBe('***');
    sanitizePayload(hardened);
    expect(hardened).toEqual({ items: [{ password: '***' }], self: '***' });
  });

  it('collapses a self-referential object rather than recursing forever', () => {
    const cyclic: Record<string, unknown> = { name: 'root' };
    cyclic['loop'] = cyclic;
    expect(harden(cyclic)).toEqual({ name: 'root', loop: '***' });
  });

  it('collapses a cycle reached through an array', () => {
    const node: Record<string, unknown> = { id: 1 };
    node['children'] = [node];
    expect(harden(node)).toEqual({ id: 1, children: ['***'] });
  });

  it('collapses a repeated subtree, bounding an n-fold blowup', () => {
    const shared = { big: 'value' };
    expect(harden({ a: shared, b: shared })).toEqual({ a: { big: 'value' }, b: '***' });
  });
});

describe('harden — scalar bounds', () => {
  it('strips control characters but keeps tab, newline, and carriage return', () => {
    // The kept set matches Python's harden_input character for character:
    // TAB/LF/CR are legitimate content in a message or a stack trace.
    expect(harden({ s: 'a\u0007b\u001fc\td\ne\rf' })).toEqual({ s: 'abc\td\ne\rf' });
  });

  it('truncates over-long strings with a suffix', () => {
    expect(harden({ s: 'x'.repeat(12) }, { maxValueLength: 10 })).toEqual({
      s: 'x'.repeat(10) + '...',
    });
  });

  it('leaves a string exactly at the limit untouched', () => {
    expect(harden({ s: 'x'.repeat(10) }, { maxValueLength: 10 })).toEqual({ s: 'x'.repeat(10) });
  });

  it('strips control characters before measuring length, not after', () => {
    // Otherwise a value padded with control bytes truncates real content that
    // would have fit once the padding was removed.
    expect(harden({ s: '\u0001\u0002abcd' }, { maxValueLength: 4 })).toEqual({ s: 'abcd' });
  });

  it('passes non-finite numbers through unchanged, matching Python and Go', () => {
    // harden_input and hardenScalar both leave NaN/±Infinity alone; the null
    // spelling belongs to canonicalization, not hardening. Redacting them here
    // diverged both the exported value and the receipt digest per SDK.
    const out = harden({
      a: Number.NaN,
      b: Number.POSITIVE_INFINITY,
      c: Number.NEGATIVE_INFINITY,
      d: 1.5,
    }) as Record<string, unknown>;
    expect(out['a']).toBeNaN();
    expect(out['b']).toBe(Number.POSITIVE_INFINITY);
    expect(out['c']).toBe(Number.NEGATIVE_INFINITY);
    expect(out['d']).toBe(1.5);
  });

  it('preserves null, undefined, booleans, and array order', () => {
    expect(harden({ n: null, u: undefined, t: true, list: [3, 1, 2] })).toEqual({
      n: null,
      u: undefined,
      t: true,
      list: [3, 1, 2],
    });
  });

  it('accepts a bare scalar as well as a record', () => {
    expect(harden('plain')).toBe('plain');
    expect(harden(42)).toBe(42);
    expect(harden(null)).toBeNull();
  });
});

describe('harden — structural bounds', () => {
  it('caps attribute count at every level, not only the top', () => {
    expect(harden({ inner: { a: 1, b: 2, c: 3 } }, { maxAttrCount: 2 })).toEqual({
      inner: { a: 1, b: 2 },
    });
  });

  it('treats maxAttrCount 0 as no cap', () => {
    expect(harden({ a: 1, b: 2 }, { maxAttrCount: 0 })).toEqual({ a: 1, b: 2 });
  });

  it('collapses composites past the depth limit', () => {
    expect(harden({ a: { b: { c: 1 } } }, { maxDepth: 2 })).toEqual({ a: { b: '***' } });
  });

  it('counts array nesting toward the depth limit too', () => {
    // Arrays recurse through their own branch, so the depth increment has to
    // be asserted there as well as on objects.
    expect(harden([[['deep']]], { maxDepth: 2 })).toEqual([['***']]);
  });

  it('collapses values JSON cannot represent', () => {
    expect(
      harden({
        fn: () => 1,
        sym: Symbol('s'),
        big: 10n,
        map: new Map([['k', 'v']]),
        set: new Set([1]),
        date: new Date(0),
      }),
    ).toEqual({ fn: '***', sym: '***', big: '***', map: '***', set: '***', date: '***' });
  });

  it('treats a null-prototype object as plain', () => {
    const bare = Object.create(null) as Record<string, unknown>;
    bare['a'] = 1;
    expect(harden(bare)).toEqual({ a: 1 });
  });
});

describe('harden — key hardening', () => {
  it('strips control characters from keys, including TAB, LF, and CR', () => {
    // Values keep TAB/LF/CR; keys cannot — the pretty renderer emits keys
    // bare, so any of the three splits or misaligns the rendered line.
    expect(harden({ 'a\tb\nc\rd\u0000e\u001ff': 1 })).toEqual({ abcdef: 1 });
  });

  it('cleans keys of nested objects, not only the top level', () => {
    expect(harden({ outer: { 'in\nner': [{ 'de\u0007ep': 2 }] } })).toEqual({
      outer: { inner: [{ deep: 2 }] },
    });
  });

  it('never lets a sanitized key displace a genuine key already present', () => {
    // Cleaning is many-to-one: "trace_i\x00d" also comes out as "trace_id".
    // A plain rebuild would let the forged late key replace the real bound
    // value and correlate the record to an attacker-chosen trace.
    expect(harden({ trace_id: 'real', 'trace_i\u0000d': 'evil' })).toEqual({ trace_id: 'real' });
  });

  it('lets a verbatim key reclaim its slot from a sanitized squatter, in place', () => {
    const out = harden({ 'trace_i\u0000d': 'evil', trace_id: 'real', z: 1 }) as Record<
      string,
      unknown
    >;
    expect(out).toEqual({ trace_id: 'real', z: 1 });
    // Re-assignment keeps the original insertion position, so reclaiming does
    // not reorder the record.
    expect(Object.keys(out)).toEqual(['trace_id', 'z']);
  });

  it('keeps the first of two sanitized keys that collide', () => {
    expect(harden({ 'a\u0000': 1, 'a\u0001': 2 })).toEqual({ a: 1 });
  });

  it('stops a newline-bearing key from forging a second pretty log line', () => {
    const record: Record<string, unknown> = {
      level: 30,
      time: 0,
      event: 'checkout.started',
      '\n2026-08-10 [error] payment.failed amount=9999': 'x',
    };
    hardenRecord(record);
    const line = formatPretty(record, false);
    expect(line).not.toContain('\n');
    // The forged text survives as inert content on the same line, not as a
    // second record.
    expect(line).toContain('payment.failed');
  });
});

describe('hardenRecord — in-place hardening', () => {
  it('mutates the caller object rather than returning a copy', () => {
    const record: Record<string, unknown> = { s: 'a\u0000b' };
    record['self'] = record;
    hardenRecord(record);
    expect(record).toEqual({ s: 'ab', self: '***' });
  });

  it('drops keys the attribute cap removed', () => {
    const record: Record<string, unknown> = { a: 1, b: 2, c: 3 };
    hardenRecord(record, { maxAttrCount: 2 });
    expect(Object.keys(record)).toEqual(['a', 'b']);
  });
});
