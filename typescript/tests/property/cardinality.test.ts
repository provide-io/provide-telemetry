// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: AGPL-3.0-or-later

import * as fc from 'fast-check';
import { afterEach, describe, it } from 'vitest';
import {
  OVERFLOW_VALUE,
  _resetCardinalityForTests,
  guardAttributes,
  registerCardinalityLimit,
} from '../../src/cardinality';

afterEach(() => _resetCardinalityForTests());

describe('property: guardAttributes cardinality', () => {
  it('after maxValues unique values, all new values → OVERFLOW_VALUE', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 10 }),
        fc.integer({ min: 1, max: 5 }),
        (maxValues, extra) => {
          _resetCardinalityForTests();
          registerCardinalityLimit('tag', { maxValues, ttlSeconds: 3600 });
          // Fill up to maxValues
          for (let i = 0; i < maxValues; i++) {
            guardAttributes({ tag: `val${i}` });
          }
          // All new values beyond maxValues must overflow
          for (let i = 0; i < extra; i++) {
            const result = guardAttributes({ tag: `overflow${i}` });
            if (result['tag'] !== OVERFLOW_VALUE) return false;
          }
          return true;
        },
      ),
    );
  });

  it('non-limited keys are never modified', () => {
    fc.assert(
      fc.property(
        fc.string({ minLength: 1, maxLength: 20 }),
        fc.string({ minLength: 1, maxLength: 20 }),
        (key, value) => {
          // Ensure key is not 'limited'
          if (key === 'limited') return true;
          _resetCardinalityForTests();
          registerCardinalityLimit('limited', { maxValues: 1, ttlSeconds: 60 });
          const result = guardAttributes({ [key]: value, limited: 'x' });
          return result[key] === value;
        },
      ),
    );
  });
});
