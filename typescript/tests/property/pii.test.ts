// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: AGPL-3.0-or-later

import * as fc from 'fast-check';
import { afterEach, describe, it, expect } from 'vitest';
import { registerPiiRule, resetPiiRulesForTests, sanitizePayload } from '../../src/pii';

afterEach(() => resetPiiRulesForTests());

const safeKey = fc
  .string({ minLength: 3, maxLength: 15 })
  .map((s) => 'prop_' + s.replace(/[^a-z0-9]/gi, 'x').slice(0, 10));

describe('property: PII mask modes', () => {
  it('redact mode: key value is always [REDACTED]', () => {
    fc.assert(
      fc.property(safeKey, fc.string(), (key, value) => {
        resetPiiRulesForTests();
        registerPiiRule({ path: key, mode: 'redact' });
        const obj: Record<string, unknown> = { [key]: value };
        sanitizePayload(obj);
        return obj[key] === '[REDACTED]';
      }),
    );
  });

  it('drop mode: key is always removed from object', () => {
    fc.assert(
      fc.property(safeKey, fc.string(), (key, value) => {
        resetPiiRulesForTests();
        registerPiiRule({ path: key, mode: 'drop' });
        const obj: Record<string, unknown> = { [key]: value, other: 'safe' };
        sanitizePayload(obj);
        return !(key in obj) && obj['other'] === 'safe';
      }),
    );
  });

  it('truncate mode: output length never exceeds truncateTo + 3 (for "...")', () => {
    fc.assert(
      fc.property(
        safeKey,
        fc.string({ minLength: 0, maxLength: 100 }),
        fc.integer({ min: 0, max: 30 }),
        (key, value, truncateTo) => {
          resetPiiRulesForTests();
          registerPiiRule({ path: key, mode: 'truncate', truncateTo });
          const obj: Record<string, unknown> = { [key]: value };
          sanitizePayload(obj);
          const result = String(obj[key]);
          return result.length <= truncateTo + 3;
        },
      ),
    );
  });

  it('hash mode: same input always produces same output (deterministic)', () => {
    fc.assert(
      fc.property(safeKey, fc.string({ minLength: 1 }), (key, value) => {
        resetPiiRulesForTests();
        registerPiiRule({ path: key, mode: 'hash' });
        const obj1: Record<string, unknown> = { [key]: value };
        const obj2: Record<string, unknown> = { [key]: value };
        sanitizePayload(obj1);
        sanitizePayload(obj2);
        return obj1[key] === obj2[key];
      }),
    );
  });
});
