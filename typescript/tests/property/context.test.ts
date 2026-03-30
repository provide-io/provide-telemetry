// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import * as fc from 'fast-check';
import { afterEach, describe, it } from 'vitest';
import { _resetContext, getContext, runWithContext } from '../../src/context';

afterEach(() => _resetContext());

describe('property: runWithContext()', () => {
  it('never leaks bindings outside its scope', () => {
    // Use keys with a unique prefix to avoid collision with Object.prototype methods.
    const safeDict = fc.dictionary(
      fc.string({ minLength: 1, maxLength: 8 }).map((s) => 'ctx_' + s),
      fc.string(),
    );
    fc.assert(
      fc.property(safeDict, (values) => {
        _resetContext();
        let innerCtx: Record<string, unknown> = {};
        runWithContext(values, () => {
          innerCtx = getContext();
        });
        const outerCtx = getContext();
        // Inner context should contain the values
        for (const [k, v] of Object.entries(values)) {
          if (innerCtx[k] !== v) return false;
        }
        // Outer context should NOT contain the runWithContext values
        for (const k of Object.keys(values)) {
          if (Object.prototype.hasOwnProperty.call(outerCtx, k)) return false;
        }
        return true;
      }),
    );
  });

  it('nested runWithContext calls always restore outer context on return', () => {
    fc.assert(
      fc.property(
        fc.dictionary(fc.string({ minLength: 1, maxLength: 10 }), fc.string()),
        fc.dictionary(fc.string({ minLength: 1, maxLength: 10 }), fc.string()),
        (outer, inner) => {
          _resetContext();
          let afterInner: Record<string, unknown> = {};
          runWithContext(outer, () => {
            runWithContext(inner, () => {
              // discard
            });
            afterInner = getContext();
          });
          // After inner completed, outer context should be restored
          for (const [k, v] of Object.entries(outer)) {
            if (afterInner[k] !== v) return false;
          }
          return true;
        },
      ),
    );
  });

  it('fn return value is always passed through', () => {
    fc.assert(
      fc.property(fc.string(), (val) => {
        const result = runWithContext({}, () => val);
        return result === val;
      }),
    );
  });
});
