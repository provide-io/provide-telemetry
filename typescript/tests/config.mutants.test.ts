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
import { _getConfigVersion, _resetConfig, setupTelemetry } from '../src/config';
import { ConfigurationError } from '../src/exceptions';
import { _resetSamplingForTests } from '../src/sampling';
import { _resetBackpressureForTests } from '../src/backpressure';
import { _resetResilienceForTests } from '../src/resilience';
import {
  _disablePropagationALSForTest,
  _restorePropagationALSForTest,
  _setPropagationInitDoneForTest,
} from '../src/propagation';
import { resetTelemetryState } from '../src/testing';

afterEach(() => {
  _resetConfig();
  _resetSamplingForTests();
  _resetBackpressureForTests();
  _resetResilienceForTests();
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

describe('_configVersion increments on each setupTelemetry call (kills UpdateOperator)', () => {
  it('increments by at least 1 after first call', () => {
    _resetConfig();
    const v0 = _getConfigVersion();
    setupTelemetry();
    expect(_getConfigVersion()).toBeGreaterThan(v0);
  });

  it('increments again on a second call', () => {
    _resetConfig();
    setupTelemetry();
    const v1 = _getConfigVersion();
    setupTelemetry();
    expect(_getConfigVersion()).toBeGreaterThan(v1);
  });
});

describe('_validateConfig — error messages include field names (kills StringLiteral on name args)', () => {
  it('samplingLogsRate error names the field', () => {
    expect(() => setupTelemetry({ samplingLogsRate: 2 })).toThrow(/samplingLogsRate/);
  });
  it('samplingTracesRate error names the field', () => {
    expect(() => setupTelemetry({ samplingTracesRate: -0.1 })).toThrow(/samplingTracesRate/);
  });
  it('samplingMetricsRate error names the field', () => {
    expect(() => setupTelemetry({ samplingMetricsRate: 1.5 })).toThrow(/samplingMetricsRate/);
  });
  it('traceSampleRate error names the field', () => {
    expect(() => setupTelemetry({ traceSampleRate: 2 })).toThrow(/traceSampleRate/);
  });
  it('backpressureLogsMaxsize error names the field', () => {
    expect(() => setupTelemetry({ backpressureLogsMaxsize: -1 })).toThrow(
      /backpressureLogsMaxsize/,
    );
  });
  it('backpressureTracesMaxsize error names the field', () => {
    expect(() => setupTelemetry({ backpressureTracesMaxsize: -1 })).toThrow(
      /backpressureTracesMaxsize/,
    );
  });
  it('backpressureMetricsMaxsize error names the field', () => {
    expect(() => setupTelemetry({ backpressureMetricsMaxsize: -1 })).toThrow(
      /backpressureMetricsMaxsize/,
    );
  });
  it('exporterLogsRetries error names the field', () => {
    expect(() => setupTelemetry({ exporterLogsRetries: -1 })).toThrow(/exporterLogsRetries/);
  });
  it('exporterTracesRetries error names the field', () => {
    expect(() => setupTelemetry({ exporterTracesRetries: -1 })).toThrow(/exporterTracesRetries/);
  });
  it('exporterMetricsRetries error names the field', () => {
    expect(() => setupTelemetry({ exporterMetricsRetries: -1 })).toThrow(/exporterMetricsRetries/);
  });
  it('securityMaxAttrValueLength error names the field', () => {
    expect(() => setupTelemetry({ securityMaxAttrValueLength: -1 })).toThrow(
      /securityMaxAttrValueLength/,
    );
  });
  it('securityMaxAttrCount error names the field', () => {
    expect(() => setupTelemetry({ securityMaxAttrCount: -1 })).toThrow(/securityMaxAttrCount/);
  });
  it('piiMaxDepth error names the field', () => {
    expect(() => setupTelemetry({ piiMaxDepth: -1 })).toThrow(/piiMaxDepth/);
  });
  it('requireRate message says "must be in [0, 1]" (kills StringLiteral on error template)', () => {
    expect(() => setupTelemetry({ samplingLogsRate: 2 })).toThrow(/must be in \[0, 1\]/);
  });
  it('requireNonNegInt message says "non-negative integer" (kills StringLiteral on error template)', () => {
    expect(() => setupTelemetry({ backpressureLogsMaxsize: -1 })).toThrow(/non-negative integer/);
  });
});
