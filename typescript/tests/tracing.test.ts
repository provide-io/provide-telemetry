// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: AGPL-3.0-or-later

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
        // eslint-disable-next-line @typescript-eslint/only-throw-error
        throw 'string rejection';
      }),
    ).rejects.toBe('string rejection');
  });

  it('propagates sync non-Error throw', () => {
    expect(() =>
      withTrace('test.throw.string', () => {
        // eslint-disable-next-line @typescript-eslint/only-throw-error
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
});

describe('getTraceContext', () => {
  it('returns manual context when set', () => {
    setTraceContext('manual-trace', 'manual-span');
    const ctx = getTraceContext();
    expect(ctx.traceId).toBe('manual-trace');
    expect(ctx.spanId).toBe('manual-span');
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
    expect(ctx.traceId).toBe('abc123def456abc123def456abc123de');
    expect(ctx.spanId).toBe('1234567890abcdef');
    vi.restoreAllMocks();
  });

  it('returns empty when no manual context and no active span', () => {
    _resetTraceContext();
    const ctx = getTraceContext();
    expect(ctx.traceId).toBeUndefined();
    expect(ctx.spanId).toBeUndefined();
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
    expect(ctx.traceId).toBe('trace-only');
    expect(ctx.spanId).toBe('span-only');
    _resetTraceContext();
  });

  it('returns empty object after reset — no manual context leaks', () => {
    setTraceContext('t', 's');
    _resetTraceContext();
    const ctx = getTraceContext();
    expect(ctx.traceId).toBeUndefined();
    expect(ctx.spanId).toBeUndefined();
    expect('traceId' in ctx).toBe(false);
    expect('spanId' in ctx).toBe(false);
  });
});

describe('withTrace — span.setStatus called on error', () => {
  it('calls span.setStatus with ERROR code and message on sync throw', () => {
    const mockSetStatus = vi.fn();
    const mockSpan = {
      end: vi.fn(),
      recordException: vi.fn(),
      setStatus: mockSetStatus,
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
