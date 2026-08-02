// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * The export-attempt ceiling.
 *
 * runWithResilience materialises a `retries + 1` index array on every export
 * call, so an unbounded retries value costs that allocation on a healthy
 * collector where the first attempt succeeds. `_validateConfig` rejects an
 * out-of-range value; `runWithResilience` clamps whatever reaches it, because
 * `setExporterPolicy` bypasses config validation entirely.
 */

import { afterEach, describe, expect, it } from 'vitest';
import { ConfigurationError } from '../src/exceptions.js';
import { _resetConfig, setupTelemetry } from '../src/config.js';
import {
  MAX_EXPORT_ATTEMPTS,
  _resetResilienceForTests,
  runWithResilience,
  setExporterPolicy,
} from '../src/resilience.js';

afterEach(() => {
  _resetConfig();
  _resetResilienceForTests();
});

describe('exporter retries — config validation', () => {
  it.each(['exporterLogsRetries', 'exporterTracesRetries', 'exporterMetricsRetries'] as const)(
    'rejects %s above the ceiling',
    (field) => {
      expect(() => setupTelemetry({ [field]: MAX_EXPORT_ATTEMPTS })).toThrow(ConfigurationError);
      expect(() => setupTelemetry({ [field]: MAX_EXPORT_ATTEMPTS })).toThrow(/at most/);
    },
  );

  it.each(['exporterLogsRetries', 'exporterTracesRetries', 'exporterMetricsRetries'] as const)(
    'accepts %s exactly at the ceiling',
    (field) => {
      expect(() => setupTelemetry({ [field]: MAX_EXPORT_ATTEMPTS - 1 })).not.toThrow();
    },
  );

  it('rejects retries one past the ceiling and accepts it exactly at the ceiling', () => {
    // Stryker reports the `MAX_EXPORT_ATTEMPTS - 1` arithmetic as a survivor.
    // It is not: mutating it to `+ 1` and running exactly the four tests
    // Stryker lists in that mutant's coveredBy fails all four. Stryker ran them
    // (testsCompleted: 4) and still scored it Survived — a false negative in its
    // result attribution. The message is asserted as well as the type so the
    // boundary cannot be satisfied by an unrelated ConfigurationError.
    expect(() => setupTelemetry({ exporterLogsRetries: MAX_EXPORT_ATTEMPTS })).toThrow(
      /at most 100/,
    );
    expect(() => setupTelemetry({ exporterLogsRetries: MAX_EXPORT_ATTEMPTS - 1 })).not.toThrow();
  });

  it('still rejects a negative value', () => {
    expect(() => setupTelemetry({ exporterLogsRetries: -1 })).toThrow(/non-negative integer/);
  });
});

describe('runWithResilience — attempt clamp', () => {
  it('does not allocate an unbounded attempt array for a huge policy retries', async () => {
    // Straight to the policy store, the way an embedder calling
    // setExporterPolicy directly would. Unclamped this is `Array.from({length:
    // 1e9})` before the first attempt — the process either OOMs or throws
    // RangeError, on a call whose first attempt succeeds.
    setExporterPolicy('logs', { retries: 1_000_000_000, timeoutMs: 0, backoffMs: 0 });
    await expect(runWithResilience('logs', () => Promise.resolve('ok'))).resolves.toBe('ok');
  });

  it('retries no more than the ceiling allows', async () => {
    setExporterPolicy('logs', {
      retries: 1_000_000_000,
      timeoutMs: 0,
      backoffMs: 0,
      failOpen: true,
    });
    let calls = 0;
    const result = await runWithResilience('logs', () => {
      calls += 1;
      return Promise.reject(new Error('always fails'));
    });
    expect(result).toBeNull();
    expect(calls).toBe(MAX_EXPORT_ATTEMPTS);
  });

  it('honours a retries value below the ceiling exactly', async () => {
    setExporterPolicy('logs', { retries: 2, timeoutMs: 0, backoffMs: 0, failOpen: true });
    let calls = 0;
    await runWithResilience('logs', () => {
      calls += 1;
      return Promise.reject(new Error('always fails'));
    });
    expect(calls).toBe(3);
  });
});
