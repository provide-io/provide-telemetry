// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Targeted Stryker mutation-kill tests for config-env.ts — the pieces not
 * already covered by config-env.mutants.test.ts (which handles the traces/
 * metrics endpoint `?? undefined` IIFEs).
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import { configFromEnv } from '../src/config-env.js';

afterEach(() => vi.unstubAllEnvs());

describe('configFromEnv — logPrettyFields (splitTrimmed)', () => {
  it('is an empty array when the env var is unset', () => {
    vi.stubEnv('PROVIDE_LOG_PRETTY_FIELDS', undefined);
    expect(configFromEnv().logPrettyFields).toEqual([]);
  });

  it('splits, trims, and drops empty entries', () => {
    vi.stubEnv('PROVIDE_LOG_PRETTY_FIELDS', ' a , b ,, c');
    expect(configFromEnv().logPrettyFields).toEqual(['a', 'b', 'c']);
  });
});

describe('configFromEnv — otlpLogsEndpoint', () => {
  it('is undefined when OTEL_EXPORTER_OTLP_LOGS_ENDPOINT is unset', () => {
    vi.stubEnv('OTEL_EXPORTER_OTLP_LOGS_ENDPOINT', undefined);
    expect(configFromEnv().otlpLogsEndpoint).toBeUndefined();
  });

  it('reads OTEL_EXPORTER_OTLP_LOGS_ENDPOINT into otlpLogsEndpoint', () => {
    vi.stubEnv('OTEL_EXPORTER_OTLP_LOGS_ENDPOINT', 'http://logs-collector:4318');
    expect(configFromEnv().otlpLogsEndpoint).toBe('http://logs-collector:4318');
  });
});
