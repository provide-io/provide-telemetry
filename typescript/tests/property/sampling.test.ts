// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: AGPL-3.0-or-later

import * as fc from 'fast-check';
import { afterEach, describe, it, expect } from 'vitest';
import { _resetSamplingForTests, setSamplingPolicy, shouldSample } from '../../src/sampling';

afterEach(() => _resetSamplingForTests());

describe('property: shouldSample()', () => {
  it('always returns a boolean', () => {
    fc.assert(
      fc.property(fc.float({ min: 0, max: 1 }), fc.string({ minLength: 1 }), (rate, signal) => {
        _resetSamplingForTests();
        setSamplingPolicy({ defaultRate: rate });
        return typeof shouldSample(signal) === 'boolean';
      }),
    );
  });

  it('rate=0.0 → always false (100 trials)', () => {
    fc.assert(
      fc.property(fc.string({ minLength: 1 }), (signal) => {
        _resetSamplingForTests();
        setSamplingPolicy({ defaultRate: 0.0 });
        for (let i = 0; i < 100; i++) {
          if (shouldSample(signal)) return false;
        }
        return true;
      }),
    );
  });

  it('rate=1.0 → always true (100 trials)', () => {
    fc.assert(
      fc.property(fc.string({ minLength: 1 }), (signal) => {
        _resetSamplingForTests();
        setSamplingPolicy({ defaultRate: 1.0 });
        for (let i = 0; i < 100; i++) {
          if (!shouldSample(signal)) return false;
        }
        return true;
      }),
    );
  });

  it('any rate value (even out-of-range) is clamped — no errors, result is boolean', () => {
    fc.assert(
      fc.property(fc.float({ noNaN: true }), (rate) => {
        _resetSamplingForTests();
        setSamplingPolicy({ defaultRate: rate });
        const result = shouldSample('logs');
        return typeof result === 'boolean';
      }),
    );
  });
});
