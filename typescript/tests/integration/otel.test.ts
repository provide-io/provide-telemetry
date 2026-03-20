// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: AGPL-3.0-or-later
// @vitest-environment node

/**
 * OTEL integration tests — verifies real SDK registration, span recording,
 * trace_id injection into log records, and metrics instrumentation.
 *
 * Uses @vitest-environment node so that the OTEL SDK runs in its native
 * Node.js environment with proper AsyncLocalStorage context propagation.
 */

import {
  BasicTracerProvider,
  InMemorySpanExporter,
  SimpleSpanProcessor,
} from '@opentelemetry/sdk-trace-base';
import { resourceFromAttributes } from '@opentelemetry/resources';
import { context, metrics, trace } from '@opentelemetry/api';
import { AsyncLocalStorageContextManager } from '@opentelemetry/context-async-hooks';
import { MeterProvider } from '@opentelemetry/sdk-metrics';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { _resetConfig, getConfig, setupTelemetry } from '../../src/config';
import { _resetContext } from '../../src/context';
import { _resetRootLogger, makeWriteHook } from '../../src/logger';
import { counter, gauge, histogram } from '../../src/metrics';
import { getActiveTraceIds, withTrace } from '../../src/tracing';
import { registerOtelProviders } from '../../src/otel.js';

// ── Shared provider setup ──────────────────────────────────────────────────────

let spanExporter: InMemorySpanExporter;
let tracerProvider: BasicTracerProvider;

function setupTracerProvider(): void {
  const ctxMgr = new AsyncLocalStorageContextManager();
  ctxMgr.enable();
  context.setGlobalContextManager(ctxMgr);

  spanExporter = new InMemorySpanExporter();
  tracerProvider = new BasicTracerProvider({
    resource: resourceFromAttributes({ 'service.name': 'otel-test' }),
    spanProcessors: [new SimpleSpanProcessor(spanExporter)],
  });
  trace.setGlobalTracerProvider(tracerProvider);
}

async function teardownTracerProvider(): Promise<void> {
  await tracerProvider.shutdown();
  // trace.disable() resets the singleton so setGlobalTracerProvider can succeed next time
  trace.disable();
  context.disable();
}

// ── getActiveTraceIds ──────────────────────────────────────────────────────────

describe('getActiveTraceIds — real OTEL provider', () => {
  beforeEach(() => {
    _resetConfig();
    setupTelemetry({ serviceName: 'otel-test' });
    setupTracerProvider();
  });
  afterEach(teardownTracerProvider);

  it('returns non-zero trace_id and span_id inside an active span', () => {
    const tracer = trace.getTracer('@undef/telemetry');
    tracer.startActiveSpan('test.op', (span) => {
      const ids = getActiveTraceIds();
      expect(ids.trace_id).toBeDefined();
      expect(ids.span_id).toBeDefined();
      expect(ids.trace_id).not.toBe('00000000000000000000000000000000');
      expect(ids.trace_id).toMatch(/^[0-9a-f]{32}$/);
      expect(ids.span_id).toMatch(/^[0-9a-f]{16}$/);
      span.end();
    });
  });

  it('returns empty object outside any active span', () => {
    expect(getActiveTraceIds()).toEqual({});
  });
});

// ── withTrace ─────────────────────────────────────────────────────────────────

describe('withTrace — real OTEL provider', () => {
  beforeEach(() => {
    _resetConfig();
    setupTelemetry({ serviceName: 'otel-test' });
    setupTracerProvider();
  });
  afterEach(teardownTracerProvider);

  it('creates a real span that appears in the exporter', () => {
    withTrace('my.operation', () => {
      /* sync work */
    });
    const spans = spanExporter.getFinishedSpans();
    expect(spans).toHaveLength(1);
    expect(spans[0].name).toBe('my.operation');
  });

  it('nested withTrace creates parent/child spans', () => {
    withTrace('outer', () => {
      withTrace('inner', () => {
        /* inner work */
      });
    });
    const spans = spanExporter.getFinishedSpans();
    expect(spans).toHaveLength(2);
    const inner = spans.find((s) => s.name === 'inner')!;
    const outer = spans.find((s) => s.name === 'outer')!;
    expect(inner.parentSpanContext?.spanId).toBe(outer.spanContext().spanId);
  });

  it('async withTrace records span after promise resolves', async () => {
    await withTrace('async.op', async () => {
      await Promise.resolve();
    });
    const spans = spanExporter.getFinishedSpans();
    expect(spans).toHaveLength(1);
    expect(spans[0].name).toBe('async.op');
  });

  it('records exception on thrown Error and sets ERROR status', () => {
    expect(() =>
      withTrace('failing.op', () => {
        throw new Error('intentional failure');
      }),
    ).toThrow('intentional failure');

    const spans = spanExporter.getFinishedSpans();
    expect(spans).toHaveLength(1);
    const exceptionEvent = spans[0].events.find((e) => e.name === 'exception');
    expect(exceptionEvent).toBeDefined();
    expect(exceptionEvent?.attributes?.['exception.message']).toBe('intentional failure');
  });

  it('records exception on async rejection', async () => {
    await expect(
      withTrace('async.failing', async () => {
        throw new Error('async failure');
      }),
    ).rejects.toThrow('async failure');

    const spans = spanExporter.getFinishedSpans();
    expect(spans).toHaveLength(1);
    const exceptionEvent = spans[0].events.find((e) => e.name === 'exception');
    expect(exceptionEvent).toBeDefined();
  });
});

// ── trace_id injection into write hook ────────────────────────────────────────

describe('write hook trace_id injection — real OTEL provider', () => {
  beforeEach(() => {
    _resetConfig();
    _resetRootLogger();
    _resetContext();
    setupTelemetry({ serviceName: 'hook-test', captureToWindow: false, consoleOutput: false });
    setupTracerProvider();
  });
  afterEach(async () => {
    await teardownTracerProvider();
    _resetConfig();
    _resetRootLogger();
    _resetContext();
  });

  it('injects real trace_id and span_id into log objects inside a span', () => {
    const hook = makeWriteHook(getConfig());
    const tracer = trace.getTracer('@undef/telemetry');
    let capturedObj: Record<string, unknown> = {};

    tracer.startActiveSpan('hook.test', (span) => {
      const obj: Record<string, unknown> = { level: 30, event: 'inside_span' };
      hook(obj);
      capturedObj = obj;
      span.end();
    });

    expect(capturedObj['trace_id']).toBeDefined();
    expect(capturedObj['span_id']).toBeDefined();
    expect(capturedObj['trace_id']).toMatch(/^[0-9a-f]{32}$/);
    expect(capturedObj['span_id']).toMatch(/^[0-9a-f]{16}$/);

    // Verify IDs match the actual finished span
    const spans = spanExporter.getFinishedSpans();
    expect(spans).toHaveLength(1);
    expect(capturedObj['trace_id']).toBe(spans[0].spanContext().traceId);
    expect(capturedObj['span_id']).toBe(spans[0].spanContext().spanId);
  });

  it('does not inject trace_id outside any span', () => {
    const hook = makeWriteHook(getConfig());
    const obj: Record<string, unknown> = { level: 30, event: 'outside_span' };
    hook(obj);
    expect(obj['trace_id']).toBeUndefined();
    expect(obj['span_id']).toBeUndefined();
  });
});

// ── Metrics with real MeterProvider ───────────────────────────────────────────

describe('metrics — real MeterProvider', () => {
  let meterProvider: MeterProvider;

  beforeEach(() => {
    _resetConfig();
    setupTelemetry({ serviceName: 'metrics-test' });
    meterProvider = new MeterProvider();
    metrics.setGlobalMeterProvider(meterProvider);
  });

  afterEach(async () => {
    await meterProvider.shutdown();
    metrics.setGlobalMeterProvider(undefined as never);
    _resetConfig();
  });

  it('counter.add records increments without throwing', () => {
    const requests = counter('test.http.requests');
    expect(() => {
      requests.add(1, { path: '/api' });
      requests.add(3, { path: '/static' });
    }).not.toThrow();
  });

  it('gauge.add handles positive and negative values', () => {
    const connections = gauge('test.db.connections');
    expect(() => {
      connections.add(5);
      connections.add(-2, { pool: 'read' });
    }).not.toThrow();
  });

  it('histogram.record captures observations', () => {
    const latency = histogram('test.request.duration', { unit: 'ms' });
    expect(() => {
      latency.record(42, { route: '/api/users' });
      latency.record(1500, { route: '/api/slow' });
    }).not.toThrow();
  });
});

// ── registerOtelProviders ──────────────────────────────────────────────────────

describe('registerOtelProviders', () => {
  beforeEach(() => {
    _resetConfig();
    setupTelemetry({ serviceName: 'reg-test' });
  });
  afterEach(() => _resetConfig());

  it('is a no-op when otelEnabled: false', async () => {
    setupTelemetry({ serviceName: 'test', otelEnabled: false });
    await expect(registerOtelProviders(getConfig())).resolves.toBeUndefined();
  });
});
