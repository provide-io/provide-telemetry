// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { _resetResilienceForTests, getCircuitState, setExporterPolicy } from '../src/resilience';
import { type ExportResultLike, wrapResilientExporter } from '../src/resilient-exporter';

/* Stryker disable all -- pending follow-up mutation strategy for this module */

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
});

/* Stryker restore all */
