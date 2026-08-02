// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * redactConfig's presence guards, asserted in both directions.
 *
 * The guards used to carry `Stryker disable ConditionalExpression` on the
 * grounds that forcing them true is equivalent — `maskEndpointUrl(undefined)`
 * comes back undefined through the catch. That only covers the true direction:
 * forcing one false leaves a real secret unmasked, which is the whole point of
 * the function. These tests pin both, so the suppressions could be removed.
 */

import { describe, expect, it } from 'vitest';
import { DEFAULTS, redactConfig, type TelemetryConfig } from '../src/config.js';

/** A config carrying none of the optional OTLP fields as own properties. */
function bareConfig(): TelemetryConfig {
  const cfg = { ...DEFAULTS };
  for (const field of [
    'otlpEndpoint',
    'otlpHeaders',
    'otlpLogsEndpoint',
    'otlpTracesEndpoint',
    'otlpMetricsEndpoint',
    'otlpLogsHeaders',
    'otlpTracesHeaders',
    'otlpMetricsHeaders',
  ] as const) {
    delete cfg[field];
  }
  return cfg;
}

describe('redactConfig — absent optional fields stay absent', () => {
  it.each([
    'otlpEndpoint',
    'otlpLogsEndpoint',
    'otlpTracesEndpoint',
    'otlpMetricsEndpoint',
    'otlpHeaders',
    'otlpLogsHeaders',
    'otlpTracesHeaders',
    'otlpMetricsHeaders',
  ])('does not introduce an %s key', (field) => {
    const result = redactConfig(bareConfig());
    // A forced-true guard would write `undefined` here — an own property the
    // input never had. toEqual would not notice; hasOwn does.
    expect(Object.hasOwn(result, field)).toBe(false);
  });
});

describe('redactConfig — absent optional fields, asserted in one pass', () => {
  // Stryker reports the two header guards as survivors. They are not: mutating
  // either to `true` and running this file alone fails, because maskHeaders()
  // throws on the undefined the forced branch hands it. Stryker lists this file
  // in the mutants' coveredBy and reports testsCompleted > 0, so it ran these
  // tests and did not observe the failure — a false negative in its per-test
  // result attribution, not a gap here. Left as a single pass over every field
  // so the intent survives the next person to read the report.
  it('introduces no OTLP key that the input did not carry', () => {
    const result = redactConfig(bareConfig());
    for (const field of [
      'otlpEndpoint',
      'otlpLogsEndpoint',
      'otlpTracesEndpoint',
      'otlpMetricsEndpoint',
      'otlpHeaders',
      'otlpLogsHeaders',
      'otlpTracesHeaders',
      'otlpMetricsHeaders',
    ] as const) {
      expect(Object.hasOwn(result, field)).toBe(false);
    }
  });
});

describe('redactConfig — present secrets are always masked', () => {
  it('masks the shared endpoint password', () => {
    const result = redactConfig({
      ...bareConfig(),
      otlpEndpoint: 'https://user:hunter2@collector.example:4318',
    });
    expect(result.otlpEndpoint).toContain('****');
    expect(result.otlpEndpoint).not.toContain('hunter2');
  });

  it.each(['otlpLogsEndpoint', 'otlpTracesEndpoint', 'otlpMetricsEndpoint'] as const)(
    'masks the %s password',
    (field) => {
      const result = redactConfig({
        ...bareConfig(),
        [field]: 'https://user:hunter2@collector.example:4318',
      });
      expect(result[field]).toContain('****');
      expect(result[field]).not.toContain('hunter2');
    },
  );

  it('masks the shared header values', () => {
    const result = redactConfig({
      ...bareConfig(),
      otlpHeaders: { authorization: 'super-secret-value' },
    });
    expect(result.otlpHeaders).toEqual({ authorization: 'supe****' });
  });

  it.each(['otlpLogsHeaders', 'otlpTracesHeaders', 'otlpMetricsHeaders'] as const)(
    'masks the %s values',
    (field) => {
      const result = redactConfig({
        ...bareConfig(),
        [field]: { authorization: 'super-secret-value' },
      });
      expect(result[field]).toEqual({ authorization: 'supe****' });
    },
  );
});
