// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { _resetResilienceForTests, getCircuitState, setExporterPolicy } from '../src/resilience';
import { type ExportResultLike, wrapResilientExporter } from '../src/resilient-exporter';

const EXPORT_RESULT_SUCCESS = 0;
const EXPORT_RESULT_FAILED = 1;

type CallbackExporter = {
  export: (items: unknown, cb: (r: ExportResultLike) => void) => void;
  shutdown: () => Promise<void>;
  forceFlush?: () => Promise<void>;
  marker?: string;
};

type FakeState = { calls: number; shutdownCalls: number; flushCalls: number };

function makeFake(
  opts: {
    behaviour?: 'success' | 'fail' | 'throw' | 'slow';
    slowMs?: number;
  } = {},
): CallbackExporter & { state: FakeState } {
  const state: FakeState = { calls: 0, shutdownCalls: 0, flushCalls: 0 };
  return {
    marker: 'inner',
    state,
    export(_items, cb) {
      state.calls += 1;
      const behaviour = opts.behaviour ?? 'success';
      if (behaviour === 'throw') {
        throw new Error('sync export threw');
      }
      if (behaviour === 'slow') {
        setTimeout(() => cb({ code: EXPORT_RESULT_SUCCESS }), opts.slowMs ?? 50);
        return;
      }
      if (behaviour === 'fail') {
        cb({ code: EXPORT_RESULT_FAILED, error: new Error('inner reported FAILED') });
        return;
      }
      cb({ code: EXPORT_RESULT_SUCCESS });
    },
    async shutdown() {
      state.shutdownCalls += 1;
    },
    async forceFlush() {
      state.flushCalls += 1;
    },
  };
}

async function exportAsync(wrapped: CallbackExporter, batch: unknown): Promise<ExportResultLike> {
  return await new Promise((resolve) => wrapped.export(batch, resolve));
}

beforeEach(() => {
  _resetResilienceForTests();
});

afterEach(() => {
  _resetResilienceForTests();
});

describe('wrapResilientExporter', () => {
  it('forwards successful export results to the callback', async () => {
    const inner = makeFake();
    const wrapped = wrapResilientExporter('logs', inner);
    const result = await exportAsync(wrapped, ['batch']);
    expect(result.code).toBe(EXPORT_RESULT_SUCCESS);
    expect(inner.state.calls).toBe(1);
  });

  it('fail_open returns FAILED code when the inner exporter reports failure', async () => {
    setExporterPolicy('logs', { retries: 0, backoffMs: 0, timeoutMs: 0, failOpen: true });
    const inner = makeFake({ behaviour: 'fail' });
    const wrapped = wrapResilientExporter('logs', inner);
    const result = await exportAsync(wrapped, ['batch']);
    expect(result.code).toBe(EXPORT_RESULT_FAILED);
  });

  it('retries the inner exporter the configured number of times', async () => {
    setExporterPolicy('traces', { retries: 2, backoffMs: 0, timeoutMs: 0, failOpen: true });
    const inner = makeFake({ behaviour: 'fail' });
    const wrapped = wrapResilientExporter('traces', inner);
    const result = await exportAsync(wrapped, ['batch']);
    expect(result.code).toBe(EXPORT_RESULT_FAILED);
    // retries=2 ⇒ 1 initial + 2 retries = 3 underlying attempts
    expect(inner.state.calls).toBe(3);
  });

  it('surfaces synchronous export() throws as FAILED to the callback', async () => {
    setExporterPolicy('logs', { retries: 0, backoffMs: 0, timeoutMs: 0, failOpen: true });
    const inner = makeFake({ behaviour: 'throw' });
    const wrapped = wrapResilientExporter('logs', inner);
    const result = await exportAsync(wrapped, ['batch']);
    expect(result.code).toBe(EXPORT_RESULT_FAILED);
  });

  it('forwards shutdown and forceFlush to the wrapped exporter', async () => {
    const inner = makeFake();
    const wrapped = wrapResilientExporter('logs', inner);
    await wrapped.shutdown();
    await wrapped.forceFlush?.();
    expect(inner.state.shutdownCalls).toBe(1);
    expect(inner.state.flushCalls).toBe(1);
  });

  it('preserves non-method fields on the inner exporter for introspection', () => {
    const inner = makeFake();
    const wrapped = wrapResilientExporter('logs', inner) as CallbackExporter & { marker?: string };
    expect(wrapped.marker).toBe('inner');
  });

  it('opens the circuit after repeated timeouts', async () => {
    setExporterPolicy('metrics', {
      retries: 0,
      backoffMs: 0,
      timeoutMs: 10,
      failOpen: true,
    });
    const inner = makeFake({ behaviour: 'slow', slowMs: 120 });
    const wrapped = wrapResilientExporter('metrics', inner);
    // Three slow calls exceed the timeout and trip the breaker.
    for (let i = 0; i < 3; i++) {
      const result = await exportAsync(wrapped, ['batch']);
      expect(result.code).toBe(EXPORT_RESULT_FAILED);
    }
    const state = getCircuitState('metrics');
    expect(state.state).toBe('open');
  });

  it('omits forceFlush when the inner exporter does not expose one', async () => {
    const inner: CallbackExporter = {
      export(_items, cb) {
        cb({ code: EXPORT_RESULT_SUCCESS });
      },
      async shutdown() {
        /* no-op */
      },
    };
    const wrapped = wrapResilientExporter('logs', inner);
    expect(wrapped.forceFlush).toBeUndefined();
  });

  it('uses fallback error message when inner callback result has no error field', async () => {
    // Covers: result?.error ?? new Error('exporter reported FAILED')
    // Mutant: StringLiteral — changes the fallback string
    // Mutant: OptionalChaining — drops '?' on result?.error
    setExporterPolicy('logs', { retries: 0, backoffMs: 0, timeoutMs: 0, failOpen: false });
    const inner: CallbackExporter = {
      export(_items, cb) {
        // Report FAILED with no error property — exercises the nullish coalescing branch.
        cb({ code: EXPORT_RESULT_FAILED });
      },
      async shutdown() {
        /* no-op */
      },
    };
    const wrapped = wrapResilientExporter('logs', inner);
    const result = await exportAsync(wrapped, []);
    expect(result.code).toBe(EXPORT_RESULT_FAILED);
    expect(result.error?.message).toBe('exporter reported FAILED');
  });

  it('preserves the error object from inner callback when one is provided', async () => {
    // Covers: result?.error ?? ... — when result.error IS present, it must pass through.
    // Mutant: OptionalChaining — if ? is removed, non-nullish result.error still passes;
    // this test verifies the positive path so the logical operator mutant is also killed.
    setExporterPolicy('logs', { retries: 0, backoffMs: 0, timeoutMs: 0, failOpen: false });
    const innerError = new Error('specific inner error');
    const inner = makeFake({ behaviour: 'fail' });
    // Override to use a specific known error instance.
    inner.export = (_items, cb) => {
      inner.state.calls += 1;
      cb({ code: EXPORT_RESULT_FAILED, error: innerError });
    };
    const wrapped = wrapResilientExporter('logs', inner);
    const result = await exportAsync(wrapped, []);
    expect(result.code).toBe(EXPORT_RESULT_FAILED);
    expect(result.error).toBe(innerError);
  });

  it('wraps non-Error sync throw as Error in the fail-closed rejection path', async () => {
    // Covers: err instanceof Error ? err : new Error(String(err)) in the catch block
    // Mutant: ObjectLiteral — error field replaced with empty object {}
    setExporterPolicy('logs', { retries: 0, backoffMs: 0, timeoutMs: 0, failOpen: false });
    const inner: CallbackExporter = {
      export(_items, _cb) {
        // Throw a non-Error value (string) synchronously.
        throw 'string-throw-42';
      },
      async shutdown() {
        /* no-op */
      },
    };
    const wrapped = wrapResilientExporter('logs', inner);
    const result = await exportAsync(wrapped, []);
    expect(result.code).toBe(EXPORT_RESULT_FAILED);
    expect(result.error).toBeInstanceOf(Error);
    expect(result.error?.message).toContain('string-throw-42');
  });

  it('passes the Error instance through unchanged in the fail-closed rejection path', async () => {
    // Covers: err instanceof Error ? err : new Error(String(err)) — true branch
    // Mutant: ObjectLiteral — checks error field is the original Error, not a wrapped one
    setExporterPolicy('logs', { retries: 0, backoffMs: 0, timeoutMs: 0, failOpen: false });
    const thrownError = new Error('direct-throw');
    const inner: CallbackExporter = {
      export(_items, _cb) {
        throw thrownError;
      },
      async shutdown() {
        /* no-op */
      },
    };
    const wrapped = wrapResilientExporter('logs', inner);
    const result = await exportAsync(wrapped, []);
    expect(result.code).toBe(EXPORT_RESULT_FAILED);
    expect(result.error).toBe(thrownError);
  });

  it('distinguishes FAILED from SUCCESS: result.code check controls resolve vs reject', async () => {
    // Covers: result && result.code !== EXPORT_RESULT_FAILED
    // Mutant: LogicalOperator — '&&' changed to '||', or '!==' changed to '==='
    // The wrapped callback must resolve on SUCCESS and reject on FAILED.
    setExporterPolicy('logs', { retries: 1, backoffMs: 0, timeoutMs: 0, failOpen: true });
    let callCount = 0;
    const inner: CallbackExporter = {
      export(_items, cb) {
        callCount += 1;
        // First call: FAILED (triggers retry). Second call: SUCCESS.
        if (callCount === 1) {
          cb({ code: EXPORT_RESULT_FAILED });
        } else {
          cb({ code: EXPORT_RESULT_SUCCESS });
        }
      },
      async shutdown() {
        /* no-op */
      },
    };
    const wrapped = wrapResilientExporter('logs', inner);
    const result = await exportAsync(wrapped, []);
    expect(result.code).toBe(EXPORT_RESULT_SUCCESS);
    // retries=1 means 1 initial attempt + 1 retry = 2 total calls.
    expect(callCount).toBe(2);
  });
});
