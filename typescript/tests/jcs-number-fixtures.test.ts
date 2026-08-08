// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
//
// Cross-language JCS number vectors: spec/jcs_number_fixtures.yaml.
//
// One vector per branch of the ECMAScript Number::toString algorithm that
// RFC 8785 defers to. They exist because spec/receipt_fixtures.yaml's seven
// whole receipts are realistic payloads, and realistic payloads never reach the
// exponent thresholds, the significand-trimming path, or the zero-padding
// branch — so two real bugs shipped past them. Python rendered 1e21 as "0.1",
// colliding with 0.1 and 1e22 on a single receipt digest; C# rendered 1e-6 as
// "1e-6" where every other SDK emits "0.000001". Both are fixed, and these
// vectors are what turn a regression into a failing test.
//
// JavaScript is the normative oracle here — JSON.stringify is what RFC 8785
// points at — so this suite is less likely to catch a bug in canonicalJson than
// to catch the fixture drifting away from the runtime every other SDK is
// imitating. That is worth pinning on its own: if these ever disagree, the
// fixture is wrong and the other four SDKs are wrong with it.

import { existsSync, readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { parse } from 'yaml';
import { canonicalJson } from '../src/receipts.js';

interface NumberVector {
  id: string;
  branch: string;
  /** The number rendered on its own, e.g. `1e+21`. */
  canonical: string;
  /** The same number inside `{"v": ...}`, e.g. `{"v":1e+21}`. */
  in_object: string;
}

// Walk up rather than counting parents: Stryker runs the suite from a sandbox
// copy of the package, where a fixed '../../spec' resolves to a directory that
// does not exist.
function findFixtures(): string {
  let directory = __dirname;
  for (;;) {
    const candidate = resolve(directory, 'spec', 'jcs_number_fixtures.yaml');
    if (existsSync(candidate)) return candidate;
    const parent = dirname(directory);
    if (parent === directory) {
      throw new Error('spec/jcs_number_fixtures.yaml not found in any parent directory');
    }
    directory = parent;
  }
}

const vectors = (parse(readFileSync(findFixtures(), 'utf8')) as { cases: NumberVector[] }).cases;

// The committed vector count, one per branch of Number::toString.
const EXPECTED_CASES = 21;

/**
 * Recover the float64 the vector describes.
 *
 * JSON.parse is the whole story in JavaScript — there is a single number type,
 * and `1e20` written without a decimal point is already a double. The typed
 * SDKs have to work for this.
 */
function valueOf(vector: NumberVector): number {
  return (JSON.parse(vector.in_object) as { v: number }).v;
}

describe('JCS number vectors', () => {
  it('loads every committed case', () => {
    // Guards against a silently empty suite: a parse that yields no cases would
    // otherwise make every it.each below vacuously pass.
    expect(vectors.length).toBeGreaterThanOrEqual(EXPECTED_CASES);
  });

  it.each(vectors)('renders $id ($branch) on its own', (vector) => {
    expect(canonicalJson(valueOf(vector))).toBe(vector.canonical);
  });

  it.each(vectors)('renders $id ($branch) the same inside an object', (vector) => {
    // Both forms are committed because a serializer can format correctly in
    // isolation and still lose the value in context.
    expect(canonicalJson({ v: valueOf(vector) })).toBe(vector.in_object);
  });
});
