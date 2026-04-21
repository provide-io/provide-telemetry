// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Targeted Stryker mutation-kill test for resilient-exporter.ts.
 *
 * Addresses survivor L52:24 — OptionalChaining mutant that replaced
 * `result?.error` with `result.error`. If result is undefined/null the
 * original yields `undefined ?? Error('exporter reported FAILED')`, while
 * the mutant throws a TypeError for "Cannot read properties of undefined".
 */

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { _resetResilienceForTests, setExporterPolicy } from '../src/resilience';
import { type ExportResultLike, wrapResilientExporter } from '../src/resilient-exporter';

const EXPORT_RESULT_FAILED = 1;

type CallbackExporter = {
  export: (items: unknown, cb: (r: ExportResultLike) => void) => void;
  shutdown: () => Promise<void>;
};

beforeEach(() => _resetResilienceForTests());
afterEach(() => _resetResilienceForTests());

describe('wrapResilientExporter — optional chaining on undefined result', () => {
  it('handles inner.export cb(undefined) with a FAILED+fallback error, not a TypeError', async () => {
    // Under the mutant `result.error` (without ?.) this throws a TypeError
    // synchronously inside the user-supplied callback, which propagates out
    // of inner.export and is caught by the outer try/catch. The resulting
    // error message mentions "Cannot read properties" instead of our
    // "exporter reported FAILED" literal.
    setExporterPolicy('logs', { retries: 0, backoffMs: 0, timeoutMs: 0, failOpen: false });
    const inner: CallbackExporter = {
      export(_items, cb) {
        // Force the falsy `result` branch to exercise `result?.error ??` path.
        (cb as (r: ExportResultLike | undefined) => void)(undefined);
      },
      async shutdown() {
        /* no-op */
      },
    };
    const wrapped = wrapResilientExporter('logs', inner);
    const result = await new Promise<ExportResultLike>((resolve) =>
      wrapped.export(['batch'], resolve),
    );
    expect(result.code).toBe(EXPORT_RESULT_FAILED);
    // The original path resolves with Error('exporter reported FAILED');
    // the mutant produces a TypeError whose message contains "Cannot read properties".
    expect(result.error).toBeInstanceOf(Error);
    expect(result.error?.message).toBe('exporter reported FAILED');
    expect(result.error?.message).not.toMatch(/Cannot read/);
  });

  it('handles inner.export cb(null) with the fallback error, not a TypeError', async () => {
    setExporterPolicy('logs', { retries: 0, backoffMs: 0, timeoutMs: 0, failOpen: false });
    const inner: CallbackExporter = {
      export(_items, cb) {
        (cb as (r: ExportResultLike | null) => void)(null);
      },
      async shutdown() {
        /* no-op */
      },
    };
    const wrapped = wrapResilientExporter('logs', inner);
    const result = await new Promise<ExportResultLike>((resolve) =>
      wrapped.export(['batch'], resolve),
    );
    expect(result.code).toBe(EXPORT_RESULT_FAILED);
    expect(result.error?.message).toBe('exporter reported FAILED');
  });
});
