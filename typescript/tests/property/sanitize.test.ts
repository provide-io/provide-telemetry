// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import * as fc from 'fast-check';
import { afterEach, describe, it } from 'vitest';
import {
  DEFAULT_SANITIZE_FIELDS,
  registerPiiRule,
  resetPiiRulesForTests,
  sanitize,
  sanitizePayload,
} from '../../src/pii';

afterEach(() => resetPiiRulesForTests());

describe('property: sanitize()', () => {
  it('any object with a default PII field always has [REDACTED] after sanitize()', () => {
    fc.assert(
      fc.property(
        fc.constantFrom(...DEFAULT_SANITIZE_FIELDS),
        fc.string(),
        fc.dictionary(fc.string({ minLength: 1 }), fc.string()),
        (field, value, extra) => {
          const obj: Record<string, unknown> = { ...extra, [field]: value };
          sanitize(obj);
          return obj[field] === '***';
        },
      ),
    );
  });

  it('extra fields passed as extraFields are always redacted', () => {
    fc.assert(
      fc.property(fc.string({ minLength: 1, maxLength: 20 }), fc.string(), (field, value) => {
        // Only test fields not in DEFAULT_SANITIZE_FIELDS
        if (DEFAULT_SANITIZE_FIELDS.includes(field.toLowerCase())) return true;
        const obj: Record<string, unknown> = { [field]: value };
        sanitize(obj, [field]);
        return obj[field] === '***';
      }),
    );
  });

  it('keys NOT in sanitize list are never modified', () => {
    fc.assert(
      fc.property(fc.string({ minLength: 1, maxLength: 20 }), fc.string(), (field, value) => {
        // Ensure the field is not in the blocked list
        const blocked = DEFAULT_SANITIZE_FIELDS.map((f) => f.toLowerCase());
        const safeField = 'safe_' + field.replace(/[^a-z0-9_]/gi, '').slice(0, 10);
        if (blocked.includes(safeField.toLowerCase())) return true;
        const obj: Record<string, unknown> = { [safeField]: value };
        sanitize(obj);
        return obj[safeField] === value;
      }),
    );
  });
});

describe('property: sanitizePayload()', () => {
  it('registered rules always apply to matching keys', () => {
    fc.assert(
      fc.property(fc.string({ minLength: 1, maxLength: 15 }), fc.string(), (key, value) => {
        const safeKey = 'test_' + key.replace(/[^a-z0-9]/gi, '').slice(0, 8);
        if (!safeKey || safeKey === 'test_') return true;
        resetPiiRulesForTests();
        registerPiiRule({ path: safeKey, mode: 'redact' });
        const obj: Record<string, unknown> = { [safeKey]: value, other: 'untouched' };
        sanitizePayload(obj);
        return obj[safeKey] === '***' && obj['other'] === 'untouched';
      }),
    );
  });
});
