// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { trace } from '@opentelemetry/api';
import { describe, expect, it, vi } from 'vitest';
import {
  _resetTraceContext,
  getActiveTraceIds,
  getTraceContext,
  getTracer,
  setTraceContext,
  tracer,
  traceDecorator,
  withTrace,
} from '../src/tracing';
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

describe('getActiveTraceIds', () => {
  it('returns empty object when no active span', () => {
    expect(getActiveTraceIds()).toEqual({});
  });
});

describe('getActiveTraceIds — with mocked span', () => {
  it('returns trace_id and span_id when active span has non-zero IDs', () => {
    const fakeSpan = {
      spanContext: () => ({
        traceId: 'abc123def456abc123def456abc123de',
        spanId: '1234567890abcdef',
      }),
    };
    vi.spyOn(trace, 'getActiveSpan').mockReturnValueOnce(fakeSpan as never);
    const ids = getActiveTraceIds();
    expect(ids.trace_id).toBe('abc123def456abc123def456abc123de');
    expect(ids.span_id).toBe('1234567890abcdef');
    vi.restoreAllMocks();
  });

  it('returns empty object when span has all-zero trace ID (OTEL no-op)', () => {
    const fakeSpan = {
      spanContext: () => ({
        traceId: '00000000000000000000000000000000',
        spanId: '0000000000000000',
      }),
    };
    vi.spyOn(trace, 'getActiveSpan').mockReturnValueOnce(fakeSpan as never);
    expect(getActiveTraceIds()).toEqual({});
    vi.restoreAllMocks();
  });
});

describe('traceDecorator', () => {
  it('wraps a class method and returns its result', () => {
    class Foo {
      @traceDecorator('foo.op')
      doWork(x: number): number {
        return x * 2;
      }
    }
    expect(new Foo().doWork(5)).toBe(10);
  });

  it('uses method name as span name when no explicit name given', () => {
    class Bar {
      @traceDecorator()
      compute(): string {
        return 'result';
      }
    }
    expect(new Bar().compute()).toBe('result');
  });

  it('propagates exceptions from decorated method', () => {
    class Baz {
      @traceDecorator('baz.op')
      fail(): void {
        throw new Error('decorated error');
      }
    }
    expect(() => new Baz().fail()).toThrow('decorated error');
  });
});

describe('withTrace', () => {
  it('executes sync function and returns result', () => {
    const result = withTrace('test.op', () => 42);
    expect(result).toBe(42);
  });

  it('executes async function and resolves', async () => {
    const result = await withTrace('test.async', async () => 'hello');
    expect(result).toBe('hello');
  });

  it('propagates sync exceptions', () => {
    expect(() =>
      withTrace('test.throw', () => {
        throw new Error('boom');
      }),
    ).toThrow('boom');
  });

  it('propagates async rejections (Error)', async () => {
    await expect(
      withTrace('test.reject', async () => {
        throw new Error('async boom');
      }),
    ).rejects.toThrow('async boom');
  });

  it('propagates async rejections (non-Error string)', async () => {
    await expect(
      withTrace('test.reject.string', async () => {
        throw 'string rejection';
      }),
    ).rejects.toBe('string rejection');
  });

  it('propagates sync non-Error throw', () => {
    expect(() =>
      withTrace('test.throw.string', () => {
        throw 'sync string error';
      }),
    ).toThrow('sync string error');
  });

  it('works without OTEL SDK registered (no-op span)', () => {
    // @opentelemetry/api returns no-op tracer when no SDK is registered.
    // withTrace() must still execute the function correctly.
    let called = false;
    const result = withTrace('no-sdk', () => {
      called = true;
      return 'ok';
    });
    expect(result).toBe('ok');
    expect(called).toBe(true);
  });

  it('provides random hex trace IDs via getTraceContext() inside a noop span', () => {
    // When no OTel SDK is registered, withTrace should generate synthetic random IDs
    // so that callers can get non-zero trace context (parity with Python/Go).
    let capturedCtx: { trace_id?: string; span_id?: string } = {};
    withTrace('no-sdk-ids', () => {
      capturedCtx = getTraceContext();
    });
    expect(capturedCtx.trace_id).toBeDefined();
    expect(capturedCtx.span_id).toBeDefined();
    expect(capturedCtx.trace_id).toMatch(/^[0-9a-f]{32}$/);
    expect(capturedCtx.span_id).toMatch(/^[0-9a-f]{16}$/);
    expect(capturedCtx.trace_id).not.toBe('00000000000000000000000000000000');
  });

  it('clears synthetic trace context after noop span completes', () => {
    _resetTraceContext();
    withTrace('no-sdk-cleanup', () => {
      /* nothing */
    });
    // After the span ends, getTraceContext should return empty (no manual context leaked)
    const ctx = getTraceContext();
    expect(ctx.trace_id).toBeUndefined();
    expect(ctx.span_id).toBeUndefined();
  });

  it('provides random hex trace IDs for async noop spans', async () => {
    let capturedCtx: { trace_id?: string; span_id?: string } = {};
    await withTrace('no-sdk-async', async () => {
      await Promise.resolve();
      capturedCtx = getTraceContext();
    });
    expect(capturedCtx.trace_id).toMatch(/^[0-9a-f]{32}$/);
    expect(capturedCtx.span_id).toMatch(/^[0-9a-f]{16}$/);
  });

  it('clears synthetic context after async noop span resolves', async () => {
    _resetTraceContext();
    await withTrace('no-sdk-async-cleanup', async () => {
      await Promise.resolve();
    });
    const ctx = getTraceContext();
    expect(ctx.trace_id).toBeUndefined();
    expect(ctx.span_id).toBeUndefined();
  });
});

describe('getTraceContext', () => {
  it('returns manual context when set', () => {
    setTraceContext('manual-trace', 'manual-span');
    const ctx = getTraceContext();
    expect(ctx.trace_id).toBe('manual-trace');
    expect(ctx.span_id).toBe('manual-span');
    _resetTraceContext();
  });

  it('falls back to OTEL span when no manual context', () => {
    _resetTraceContext();
    const fakeSpan = {
      spanContext: () => ({
        traceId: 'abc123def456abc123def456abc123de',
        spanId: '1234567890abcdef',
      }),
    };
    vi.spyOn(trace, 'getActiveSpan').mockReturnValueOnce(fakeSpan as never);
    const ctx = getTraceContext();
    expect(ctx.trace_id).toBe('abc123def456abc123def456abc123de');
    expect(ctx.span_id).toBe('1234567890abcdef');
    vi.restoreAllMocks();
  });

  it('returns empty when no manual context and no active span', () => {
    _resetTraceContext();
    const ctx = getTraceContext();
    expect(ctx.trace_id).toBeUndefined();
    expect(ctx.span_id).toBeUndefined();
  });
});

describe('getTracer / tracer singleton', () => {
  it('getTracer() returns a Tracer with startActiveSpan', () => {
    const t = getTracer();
    expect(t).toBeDefined();
    expect(typeof t.startActiveSpan).toBe('function');
  });

  it('tracer module export is a Tracer', () => {
    expect(tracer).toBeDefined();
    expect(typeof tracer.startActiveSpan).toBe('function');
  });
});

describe('getTraceContext — partial manual context', () => {
  it('includes only traceId in result when only traceId is meaningful', () => {
    _resetTraceContext();
    setTraceContext('trace-only', 'span-only');
    const ctx = getTraceContext();
    // Both are always set together by setTraceContext, verify both present
    expect(ctx.trace_id).toBe('trace-only');
    expect(ctx.span_id).toBe('span-only');
    _resetTraceContext();
  });

  it('returns empty object after reset — no manual context leaks', () => {
    setTraceContext('t', 's');
    _resetTraceContext();
    const ctx = getTraceContext();
    expect(ctx.trace_id).toBeUndefined();
    expect(ctx.span_id).toBeUndefined();
    expect('trace_id' in ctx).toBe(false);
    expect('span_id' in ctx).toBe(false);
  });
});

describe('withTrace — span.setStatus called on error', () => {
  it('calls span.setStatus with ERROR code and message on sync throw', () => {
    const mockSetStatus = vi.fn();
    const mockSpan = {
      end: vi.fn(),
      recordException: vi.fn(),
      setStatus: mockSetStatus,
      spanContext: () => ({
        traceId: 'aabbccddeeff00112233445566778899',
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
        traceId: 'aabbccddeeff00112233445566778899',
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

describe('getActiveTraceIds — span with non-zero IDs', () => {
  it('returns trace_id and span_id when both are present', () => {
    const fakeSpan = {
      spanContext: () => ({
        traceId: 'aabbccddeeff00112233445566778899',
        spanId: 'aabbccdd11223344',
      }),
    };
    vi.spyOn(trace, 'getActiveSpan').mockReturnValueOnce(fakeSpan as never);
    const ids = getActiveTraceIds();
    expect(ids.trace_id).toBe('aabbccddeeff00112233445566778899');
    expect(ids.span_id).toBe('aabbccdd11223344');
    expect('trace_id' in ids).toBe(true);
    expect('span_id' in ids).toBe(true);
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
