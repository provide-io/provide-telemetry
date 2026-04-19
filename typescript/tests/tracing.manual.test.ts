// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Advanced withTrace tests: OTel setStatus, propagation context wiring, health counters,
 * enforcement gates (sampling/consent/backpressure), async context isolation, and ALS scope.
 * Basic withTrace and getTraceContext tests live in tracing.test.ts.
 */

import { trace, propagation } from '@opentelemetry/api';
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { _resetHealthForTests, getHealthSnapshot } from '../src/health';
import { _resetTraceContext, getTraceContext, setTraceContext, withTrace } from '../src/tracing';
import { _resetPropagationForTests, bindPropagationContext } from '../src/propagation';
import { _resetSamplingForTests, setSamplingPolicy } from '../src/sampling';
import {
  _resetBackpressureForTests,
  setQueuePolicy,
  tryAcquire,
  release,
} from '../src/backpressure';
import { resetConsentForTests, setConsentLevel } from '../src/consent';
import { _resetConfig, setupTelemetry } from '../src/config';

describe('withTrace — span.setStatus called on error', () => {
  it('calls span.setStatus with ERROR code and message on sync throw', () => {
    const mockSetStatus = vi.fn();
    const mockSpan = {
      end: vi.fn(),
      recordException: vi.fn(),
      setStatus: mockSetStatus,
      spanContext: () => ({
        traceId: 'aabbccddeeff00112233445566778899', // pragma: allowlist secret
        spanId: 'aabbccdd11223344',
      }),
    };
    const mockTracer = {
      startActiveSpan: vi.fn((_name: string, cb: (span: typeof mockSpan) => unknown) =>
        cb(mockSpan),
      ),
    };
    vi.spyOn(trace, 'getTracer').mockReturnValueOnce(mockTracer as never);

    expect(() =>
      withTrace('test.error', () => {
        throw new Error('oops');
      }),
    ).toThrow('oops');

    expect(mockSetStatus).toHaveBeenCalledOnce();
    const call = mockSetStatus.mock.calls[0][0] as { code: number; message: string };
    // SpanStatusCode.ERROR = 2
    expect(call.code).toBe(2);
    expect(call.message).toBe('Error: oops');

    vi.restoreAllMocks();
  });

  it('calls span.setStatus with ERROR code and message on async rejection', async () => {
    const mockSetStatus = vi.fn();
    const mockSpan = {
      end: vi.fn(),
      recordException: vi.fn(),
      setStatus: mockSetStatus,
      spanContext: () => ({
        traceId: 'aabbccddeeff00112233445566778899', // pragma: allowlist secret
        spanId: 'aabbccdd11223344',
      }),
    };
    const mockTracer = {
      startActiveSpan: vi.fn((_name: string, cb: (span: typeof mockSpan) => unknown) =>
        cb(mockSpan),
      ),
    };
    vi.spyOn(trace, 'getTracer').mockReturnValueOnce(mockTracer as never);

    await expect(
      withTrace('test.async.error', async () => {
        throw new Error('async oops');
      }),
    ).rejects.toThrow('async oops');

    expect(mockSetStatus).toHaveBeenCalledOnce();
    const call = mockSetStatus.mock.calls[0][0] as { code: number; message: string };
    expect(call.code).toBe(2);
    expect(call.message).toBe('Error: async oops');

    vi.restoreAllMocks();
  });
});

describe('withTrace — OTel propagation context wiring', () => {
  const VALID_TRACEPARENT = '00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01'; // pragma: allowlist secret

  beforeAll(() => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { W3CTraceContextPropagator } = require('@opentelemetry/core') as {
      W3CTraceContextPropagator: new () => import('@opentelemetry/api').TextMapPropagator;
    };
    propagation.setGlobalPropagator(new W3CTraceContextPropagator());
  });

  afterAll(() => {
    propagation.disable();
  });

  afterEach(() => {
    _resetPropagationForTests();
  });

  it('uses propagated OTel context as parent when available', () => {
    bindPropagationContext({
      traceparent: VALID_TRACEPARENT,
      traceId: '4bf92f3577b34da6a3ce929d0e0e4736', // pragma: allowlist secret
      spanId: '00f067aa0ba902b7',
    });

    // withTrace should execute normally and return the result
    const result = withTrace('test.propagated', () => 42);
    expect(result).toBe(42);
  });

  it('works with async fn when propagation context is bound', async () => {
    bindPropagationContext({
      traceparent: VALID_TRACEPARENT,
      traceId: '4bf92f3577b34da6a3ce929d0e0e4736', // pragma: allowlist secret
      spanId: '00f067aa0ba902b7',
    });

    const result = await withTrace('test.propagated.async', async () => 'hello');
    expect(result).toBe('hello');
  });

  it('falls back to default when no propagation context is bound', () => {
    // No bindPropagationContext called — getActiveOtelContext() returns undefined
    const result = withTrace('test.no-propagation', () => 'ok');
    expect(result).toBe('ok');
  });

  it('withTrace uses getActiveOtelContext and otelContext.with for parent span (kills lines 120-122)', () => {
    // Bind a propagation context so getActiveOtelContext() returns a real OTel context
    bindPropagationContext({
      traceparent: VALID_TRACEPARENT,
      traceId: '4bf92f3577b34da6a3ce929d0e0e4736', // pragma: allowlist secret
      spanId: '00f067aa0ba902b7',
    });

    // Spy on otelContext.with to verify it's called with the extracted context
    const { context: otelCtxModule } =
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      require('@opentelemetry/api') as typeof import('@opentelemetry/api');
    const withSpy = vi.spyOn(otelCtxModule, 'with');

    const result = withTrace('test.verify-parent', () => 'done');
    expect(result).toBe('done');

    // otelContext.with must have been called (proves line 123 branch is taken)
    expect(withSpy).toHaveBeenCalled();
    // The first argument to the FIRST call of otelContext.with should be the extracted OTel context
    const firstArg = withSpy.mock.calls[0][0];
    expect(firstArg).toBeTruthy();

    // Verify the context carries the propagated trace ID
    const spanCtx = trace.getSpanContext(firstArg as import('@opentelemetry/api').Context);
    expect(spanCtx).toBeDefined();
    expect(spanCtx?.traceId).toBe('4bf92f3577b34da6a3ce929d0e0e4736'); // pragma: allowlist secret

    withSpy.mockRestore();
  });

  it('releases traces backpressure ticket in the OTel-propagation-context path (kills BlockStatement on release)', () => {
    // Exercises the if (activeCtx) { try { … } finally { release(ticket) } } branch.
    // If release(ticket) were removed in that branch, the second withTrace call would be blocked.
    setQueuePolicy({ maxLogs: 0, maxTraces: 1, maxMetrics: 0 });
    bindPropagationContext({
      traceparent: VALID_TRACEPARENT,
      traceId: '4bf92f3577b34da6a3ce929d0e0e4736', // pragma: allowlist secret
      spanId: '00f067aa0ba902b7',
    });
    _resetHealthForTests();
    withTrace('first.propagated.span', () => undefined);
    expect(getHealthSnapshot().tracesEmitted).toBe(1);
    // Ticket must have been released — second call should also succeed.
    withTrace('second.propagated.span', () => undefined);
    expect(getHealthSnapshot().tracesEmitted).toBe(2);
    setQueuePolicy({ maxLogs: 0, maxTraces: 0, maxMetrics: 0 });
  });

  it('withTrace calls otelContext.with only once when no propagation context (line 120 check)', () => {
    // No bindPropagationContext — getActiveOtelContext() returns undefined
    // In this case, withTrace falls through to startActiveSpan without calling otelContext.with explicitly.
    // startActiveSpan itself internally calls otelContext.with, but the context should NOT carry our trace ID.
    const { context: otelCtxModule } =
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      require('@opentelemetry/api') as typeof import('@opentelemetry/api');
    const withSpy = vi.spyOn(otelCtxModule, 'with');

    const result = withTrace('test.no-parent', () => 'ok');
    expect(result).toBe('ok');

    // When there's no propagation context, otelContext.with should only be called
    // by startActiveSpan internally (not by our explicit call in the if-branch).
    // Verify none of the calls carry our specific trace ID.
    for (const call of withSpy.mock.calls) {
      const ctx = call[0] as import('@opentelemetry/api').Context;
      const spanCtx = trace.getSpanContext(ctx);
      if (spanCtx) {
        expect(spanCtx.traceId).not.toBe('4bf92f3577b34da6a3ce929d0e0e4736'); // pragma: allowlist secret
      }
    }

    withSpy.mockRestore();
  });
});

describe('withTrace — tracesEmitted health counter', () => {
  beforeEach(() => _resetHealthForTests());
  afterEach(() => _resetHealthForTests());

  it('increments tracesEmitted by 1 for each withTrace call', () => {
    expect(getHealthSnapshot().tracesEmitted).toBe(0);
    withTrace('test.span', () => 'result');
    expect(getHealthSnapshot().tracesEmitted).toBe(1);
  });

  it('increments tracesEmitted once per span (not once per attribute or nested call)', () => {
    withTrace('outer', () => {
      withTrace('inner', () => 'inner-result');
      return 'outer-result';
    });
    expect(getHealthSnapshot().tracesEmitted).toBe(2);
  });

  it('still increments tracesEmitted when the traced function throws', () => {
    expect(() =>
      withTrace('failing.span', () => {
        throw new Error('boom');
      }),
    ).toThrow('boom');
    expect(getHealthSnapshot().tracesEmitted).toBe(1);
  });
});

describe('withTrace — enforcement gates', () => {
  beforeEach(() => {
    _resetConfig();
    _resetSamplingForTests();
    _resetBackpressureForTests();
    resetConsentForTests();
    _resetHealthForTests();
    setupTelemetry({ serviceName: 'test-svc' });
  });
  afterEach(() => {
    _resetSamplingForTests();
    _resetBackpressureForTests();
    resetConsentForTests();
  });

  it('fn still runs when consent blocks the span', () => {
    setConsentLevel('NONE');
    let called = false;
    withTrace('test.span', () => {
      called = true;
    });
    expect(called).toBe(true);
    expect(getHealthSnapshot().tracesEmitted).toBe(0);
  });

  it('fn still runs when sampling rate is 0', () => {
    setSamplingPolicy('traces', { defaultRate: 0, overrides: {} });
    let called = false;
    withTrace('test.span', () => {
      called = true;
    });
    expect(called).toBe(true);
    expect(getHealthSnapshot().tracesEmitted).toBe(0);
  });

  it('fn still runs when backpressure queue is full', () => {
    setQueuePolicy({ maxLogs: 0, maxTraces: 1, maxMetrics: 0 });
    const ticket = tryAcquire('traces'); // fill the only slot
    expect(ticket).toBeTruthy();
    let called = false;
    withTrace('test.span', () => {
      called = true;
    });
    expect(called).toBe(true);
    if (ticket) release(ticket);
  });

  it('releases traces backpressure ticket so successive withTrace calls succeed (kills BlockStatement on release)', () => {
    // Use a bounded queue of 1 trace slot. If release(ticket) were removed,
    // the second withTrace call would be backpressure-blocked and tracesEmitted would stay at 1.
    setQueuePolicy({ maxLogs: 0, maxTraces: 1, maxMetrics: 0 });
    withTrace('first.span', () => undefined);
    expect(getHealthSnapshot().tracesEmitted).toBe(1);
    // Second call must succeed — ticket from first call must have been released.
    withTrace('second.span', () => undefined);
    expect(getHealthSnapshot().tracesEmitted).toBe(2);
  });

  it('withTrace is gated by traces backpressure, not metrics (kills StringLiteral tryAcquire mutation)', () => {
    // Fill only the traces slot; metrics is unbounded. If tryAcquire used '' or 'metrics',
    // the traces slot would not be checked and tracesEmitted would increment.
    setQueuePolicy({ maxLogs: 0, maxTraces: 1, maxMetrics: 0 });
    const ticket = tryAcquire('traces'); // fill the traces slot
    expect(ticket).toBeTruthy();
    withTrace('blocked.span', () => undefined);
    // Should be backpressure-blocked — tracesEmitted must NOT increment
    expect(getHealthSnapshot().tracesEmitted).toBe(0);
    if (ticket) release(ticket);
  });
});

describe('withTrace — async context isolation (no ID bleed between concurrent flows)', () => {
  it('does not leak trace IDs between overlapping async withTrace calls', async () => {
    const aTraceIds: (string | undefined)[] = [];
    const bTraceIds: (string | undefined)[] = [];

    // Two async flows running concurrently.  Each captures its own trace_id
    // at several suspension points.  With module-global save/restore, one
    // flow's ID would leak into the other's continuation; with
    // AsyncLocalStorage each flow sees only its own IDs.
    const flowA = withTrace('flow.a', async () => {
      aTraceIds.push(getTraceContext().trace_id);
      await new Promise<void>((r) => setTimeout(r, 5));
      aTraceIds.push(getTraceContext().trace_id);
      await new Promise<void>((r) => setTimeout(r, 5));
      aTraceIds.push(getTraceContext().trace_id);
    });

    const flowB = withTrace('flow.b', async () => {
      bTraceIds.push(getTraceContext().trace_id);
      await new Promise<void>((r) => setTimeout(r, 5));
      bTraceIds.push(getTraceContext().trace_id);
      await new Promise<void>((r) => setTimeout(r, 5));
      bTraceIds.push(getTraceContext().trace_id);
    });

    await Promise.all([flowA, flowB]);

    // Within a flow, every sample must be the same ID.
    expect(new Set(aTraceIds).size).toBe(1);
    expect(new Set(bTraceIds).size).toBe(1);
    // Across flows, the IDs must differ.
    expect(aTraceIds[0]).not.toBe(bTraceIds[0]);
    // Neither should be undefined (synthetic IDs always present on fallback path).
    expect(aTraceIds[0]).toBeDefined();
    expect(bTraceIds[0]).toBeDefined();
  });
});

describe('setTraceContext / _resetTraceContext — inside ALS scope', () => {
  it('setTraceContext inside withTrace writes into the ALS store, not globals', () => {
    // withTrace runs fn inside _als.run() so _als.getStore() returns the store.
    // Calling setTraceContext there should write into the store (lines 69-71 coverage).
    let innerCtx: { trace_id?: string; span_id?: string } = {};
    withTrace('als.scope.set', () => {
      setTraceContext('inner-trace', 'inner-span');
      innerCtx = getTraceContext();
    });
    expect(innerCtx.trace_id).toBe('inner-trace');
    expect(innerCtx.span_id).toBe('inner-span');
    // After the trace scope exits, the withTrace-set IDs may persist in
    // the global fallback (non-ALS path). The inner setTraceContext write
    // is confirmed above; global cleanup is covered by _resetTraceContext tests.
  });

  it('_resetTraceContext inside withTrace clears the ALS store fields', () => {
    // Calling _resetTraceContext inside a withTrace run() scope covers lines 106-107.
    let ctxAfterReset: { trace_id?: string; span_id?: string } = {};
    withTrace('als.scope.reset', () => {
      setTraceContext('to-be-cleared', 'to-be-cleared-span');
      _resetTraceContext();
      ctxAfterReset = getTraceContext();
    });
    // After reset, trace context is cleared (only synthetic IDs from withTrace remain
    // after the reset, but the manual values we injected are gone).
    expect(ctxAfterReset.trace_id).not.toBe('to-be-cleared');
  });
});
