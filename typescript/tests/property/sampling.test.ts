// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import * as fc from 'fast-check';
import { afterEach, describe, it } from 'vitest';
import { _resetSamplingForTests, setSamplingPolicy, shouldSample } from '../../src/sampling';

afterEach(() => _resetSamplingForTests());

const validSignal = fc.constantFrom('logs', 'traces', 'metrics');

describe('property: shouldSample()', () => {
  it('always returns a boolean', () => {
    fc.assert(
      fc.property(fc.float({ min: 0, max: 1 }), validSignal, (rate, signal) => {
        _resetSamplingForTests();
        setSamplingPolicy(signal, { defaultRate: rate });
        return typeof shouldSample(signal) === 'boolean';
      }),
    );
  });

  it('rate=0.0 → always false (100 trials)', () => {
    fc.assert(
      fc.property(validSignal, (signal) => {
        _resetSamplingForTests();
        setSamplingPolicy(signal, { defaultRate: 0.0 });
        for (let i = 0; i < 100; i++) {
          if (shouldSample(signal)) return false;
        }
        return true;
      }),
    );
  });

  it('rate=1.0 → always true (100 trials)', () => {
    fc.assert(
      fc.property(validSignal, (signal) => {
        _resetSamplingForTests();
        setSamplingPolicy(signal, { defaultRate: 1.0 });
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
        setSamplingPolicy('logs', { defaultRate: rate });
        const result = shouldSample('logs');
        return typeof result === 'boolean';
      }),
    );
  });
});
