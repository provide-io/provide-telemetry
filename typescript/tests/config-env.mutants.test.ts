// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Targeted Stryker mutation-kill tests for config-env.ts.
 *
 * Survivors addressed:
 *   L134:25 StringLiteral — `nodeEnv('OTEL_EXPORTER_OTLP_TRACES_ENDPOINT')`
 *           → `nodeEnv("")`. Replace with empty env key yields undefined,
 *           so otlpTracesEndpoint would silently drop the env var value.
 *   L139:14 LogicalOperator — for OTEL_EXPORTER_OTLP_METRICS_ENDPOINT the
 *           expression `v ?? undefined` was mutated to `v && undefined`,
 *           which flips a non-empty value to `undefined`.
 */

import { afterEach, describe, expect, it } from 'vitest';
import { _resetConfig, configFromEnv } from '../src/config';

const TRACES_ENV = 'OTEL_EXPORTER_OTLP_TRACES_ENDPOINT';
const METRICS_ENV = 'OTEL_EXPORTER_OTLP_METRICS_ENDPOINT';

afterEach(() => {
  _resetConfig();
  delete process.env[TRACES_ENV];
  delete process.env[METRICS_ENV];
});

describe('configFromEnv — OTEL_EXPORTER_OTLP_TRACES_ENDPOINT / METRICS_ENDPOINT', () => {
  it('reads OTEL_EXPORTER_OTLP_TRACES_ENDPOINT into otlpTracesEndpoint', () => {
    // Kills StringLiteral mutant at L134:25 that changes the env key to "".
    process.env[TRACES_ENV] = 'http://traces.example.com:4318';
    const cfg = configFromEnv();
    expect(cfg.otlpTracesEndpoint).toBe('http://traces.example.com:4318');
  });

  it('reads OTEL_EXPORTER_OTLP_METRICS_ENDPOINT into otlpMetricsEndpoint (kills v ?? undefined mutant)', () => {
    // Kills LogicalOperator mutant at L139:14 where `v ?? undefined` becomes
    // `v && undefined` — any truthy env value would be collapsed to undefined.
    process.env[METRICS_ENV] = 'http://metrics.example.com:4318';
    const cfg = configFromEnv();
    expect(cfg.otlpMetricsEndpoint).toBe('http://metrics.example.com:4318');
  });

  it('returns undefined otlpMetricsEndpoint when the env var is unset', () => {
    // Pins the undefined branch too so both sides of `v ?? undefined` are observed.
    delete process.env[METRICS_ENV];
    const cfg = configFromEnv();
    expect(cfg.otlpMetricsEndpoint).toBeUndefined();
  });

  it('returns undefined otlpTracesEndpoint when the env var is unset', () => {
    delete process.env[TRACES_ENV];
    const cfg = configFromEnv();
    expect(cfg.otlpTracesEndpoint).toBeUndefined();
  });
});
