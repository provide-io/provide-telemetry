// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Targeted Stryker mutation-kill tests for config.ts.
 *
 * Survivor L301:5 LogicalOperator — replaces the first `&&` of
 *   typeof process !== 'undefined' && typeof process.versions === 'object'
 *   && typeof process.versions.node === 'string'
 * with `||`. Under the mutant, isNodeLike is *always* true in any environment
 * where `process` is defined (i.e. all Node tests), even when process.versions
 * has been stubbed to look like a non-Node host. We force the
 * (process defined, versions not a node-like object) scenario together with
 * fallback ALS to make the original take the no-throw branch and the mutant
 * take the throw branch.
 */

import { afterEach, describe, expect, it } from 'vitest';
import { _resetConfig, setupTelemetry } from '../src/config';
import { ConfigurationError } from '../src/exceptions';
import {
  _disablePropagationALSForTest,
  _restorePropagationALSForTest,
  _setPropagationInitDoneForTest,
} from '../src/propagation';
import { resetTelemetryState } from '../src/testing';

afterEach(() => {
  _resetConfig();
  resetTelemetryState();
});

describe('setupTelemetry — isNodeLike guard (process.versions.node check)', () => {
  it('does not throw when process.versions has no `node` key, even if ALS is in fallback', () => {
    // Original: isNodeLike is false because process.versions.node is undefined,
    //           so the `if (isNodeLike && isFallbackMode())` branch is skipped.
    // Mutant (||): isNodeLike collapses to true because `process` is defined,
    //              so it enters the throw branch and raises ConfigurationError.
    const savedAls = _disablePropagationALSForTest();
    const savedDone = _setPropagationInitDoneForTest(true);
    const savedVersionsDescriptor = Object.getOwnPropertyDescriptor(
      process,
      'versions',
    ) as PropertyDescriptor;
    Object.defineProperty(process, 'versions', {
      // Provide a non-empty object that is missing the `node` key — this proves
      // the third clause (`typeof versions.node === 'string'`) is the deciding
      // factor under the original code, while the mutated `||` ignores it.
      value: { v8: '12.0.0', deno: '1.0.0' },
      configurable: true,
    });
    try {
      expect(() => setupTelemetry()).not.toThrow();
    } finally {
      Object.defineProperty(process, 'versions', savedVersionsDescriptor);
      _setPropagationInitDoneForTest(savedDone);
      _restorePropagationALSForTest(savedAls);
    }
  });

  it('still throws ConfigurationError when ALS is in fallback AND process.versions.node is set (Node)', () => {
    // Sanity: the throw path remains active for genuine Node environments.
    const savedAls = _disablePropagationALSForTest();
    const savedDone = _setPropagationInitDoneForTest(true);
    try {
      // Real process.versions.node is a string in this Node test runner.
      expect(typeof (process.versions as { node?: unknown }).node).toBe('string');
      expect(() => setupTelemetry()).toThrow(ConfigurationError);
    } finally {
      _setPropagationInitDoneForTest(savedDone);
      _restorePropagationALSForTest(savedAls);
    }
  });
});
