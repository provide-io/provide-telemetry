// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Injection tests for the untrusted-input surfaces.
 *
 * A baggage key becomes a log-attribute key, and the console renderer emits keys
 * bare, so a control character in a key from an untrusted inbound header would
 * forge an entire additional log record. Keys must be RFC 7230 tokens, which is
 * also what the W3C Baggage spec requires.
 */

import { describe, expect, it } from 'vitest';
import { parseBaggage } from '../../src/propagation.js';

const NUL = String.fromCharCode(0);

describe('baggage injection', () => {
  it.each([
    ['newline in key', 'ev\nil=x,ok=1'],
    ['carriage return in key', 'ev\ril=x,ok=1'],
    ['space in key', 'bad key=x,ok=1'],
    ['nul in key', `ev${NUL}il=x,ok=1`],
    ['tab in key', 'a\tb=x,ok=1'],
  ])('rejects a non-token key: %s', (_label, raw) => {
    expect(parseBaggage(raw)).toEqual({ ok: '1' });
  });

  it('strips control characters from values', () => {
    expect(parseBaggage(`k=a${NUL}b\nc`)).toEqual({ k: 'abc' });
  });

  it('keeps legitimate members and drops properties', () => {
    expect(parseBaggage('tenant=acme;role=admin,region=eu')).toEqual({
      tenant: 'acme',
      region: 'eu',
    });
  });
});
