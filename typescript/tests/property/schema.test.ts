// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import * as fc from 'fast-check';
import { describe, it } from 'vitest';
import { EventSchemaError, eventName, validateEventName } from '../../src/schema';

const validSegment = fc
  .tuple(
    fc.constantFrom(...'abcdefghijklmnopqrstuvwxyz'.split('')),
    fc.stringMatching(/^[a-z0-9_]{0,10}$/),
  )
  .map(([first, rest]) => first + rest);

const validEventArgs = fc
  .integer({ min: 3, max: 5 })
  .chain((n) => fc.array(validSegment, { minLength: n, maxLength: n }));

describe('property: eventName()', () => {
  it('valid 3-5 segment event names always pass strict validation', () => {
    fc.assert(
      fc.property(validEventArgs, (segs) => {
        const name = eventName(...segs);
        return name === segs.join('.');
      }),
    );
  });

  it('eventName(...segs) always equals segs.join(".")', () => {
    fc.assert(
      fc.property(validEventArgs, (segs) => {
        return eventName(...segs) === segs.join('.');
      }),
    );
  });

  it('fewer than 3 segments always throws EventSchemaError', () => {
    fc.assert(
      fc.property(fc.array(validSegment, { minLength: 0, maxLength: 2 }), (segs) => {
        try {
          eventName(...segs);
          return false; // should have thrown
        } catch (e) {
          return e instanceof EventSchemaError;
        }
      }),
    );
  });

  it('more than 5 segments in strict mode always throws', () => {
    fc.assert(
      fc.property(fc.array(validSegment, { minLength: 6, maxLength: 10 }), (segs) => {
        try {
          eventName(...segs);
          return false;
        } catch (e) {
          return e instanceof EventSchemaError;
        }
      }),
    );
  });
});

describe('property: validateEventName()', () => {
  it('valid strict names always pass', () => {
    fc.assert(
      fc.property(validEventArgs, (segs) => {
        const name = segs.join('.');
        try {
          validateEventName(name, true);
          return true;
        } catch {
          return false;
        }
      }),
    );
  });

  it('segments with uppercase always fail strict validation', () => {
    fc.assert(
      fc.property(validSegment, fc.string({ minLength: 1, maxLength: 10 }), (seg1, badSeg) => {
        // Create a segment with at least one uppercase letter
        const upperSeg = badSeg.toUpperCase();
        if (upperSeg === upperSeg.toLowerCase()) return true; // no uppercase chars, skip
        const name = [seg1, seg1, upperSeg].join('.');
        try {
          validateEventName(name, true);
          return false; // should have thrown
        } catch (e) {
          return e instanceof EventSchemaError;
        }
      }),
    );
  });
});
