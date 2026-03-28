// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Tracing helpers — mirrors Python undef.telemetry @trace decorator and tracer access.
 *
 * Uses @opentelemetry/api which provides no-op implementations when no SDK is registered.
 * withTrace() / @trace work safely without any OTEL setup; they just don't export spans.
 */

import { type Tracer, SpanStatusCode, trace } from '@opentelemetry/api';

// Stryker disable next-line StringLiteral: tracer name is not observable without a real SDK
const TRACER_NAME = '@undef-games/telemetry';

// ── Manual trace context (injected without an active OTEL span) ───────────────
let _manualTraceId: string | undefined;
let _manualSpanId: string | undefined;

/**
 * Manually inject trace/span IDs (e.g. from an incoming request header).
 * Returned by getTraceContext(); cleared by _resetTraceContext().
 */
export function setTraceContext(traceId: string, spanId: string): void {
  _manualTraceId = traceId;
  _manualSpanId = spanId;
}

/**
 * Return the current trace context: manual injection first, then active OTEL span.
 */
export function getTraceContext(): { traceId?: string; spanId?: string } {
  // Stryker disable next-line ConditionalExpression,LogicalOperator: setTraceContext always sets both; partial state not reachable via public API
  if (_manualTraceId !== undefined || _manualSpanId !== undefined) {
    return {
      // Stryker disable next-line ConditionalExpression: _manualTraceId is always defined here (both set together)
      ...(_manualTraceId !== undefined && { traceId: _manualTraceId }),
      // Stryker disable next-line ConditionalExpression: _manualSpanId is always defined here (both set together)
      ...(_manualSpanId !== undefined && { spanId: _manualSpanId }),
    };
  }
  const ids = getActiveTraceIds();
  return {
    ...(ids.trace_id !== undefined && { traceId: ids.trace_id }),
    ...(ids.span_id !== undefined && { spanId: ids.span_id }),
  };
}

/** Reset manually injected trace context (used in tests). */
export function _resetTraceContext(): void {
  _manualTraceId = undefined;
  _manualSpanId = undefined;
}

/** Return the tracer for the telemetry library. Noop when no SDK is registered. */
export function getTracer(): Tracer {
  return trace.getTracer(TRACER_NAME);
}

/** Module-level lazy singleton tracer — resolves provider at call time. */
export const tracer: Tracer = trace.getTracer(TRACER_NAME);

/**
 * Return trace_id and span_id from the currently active OTEL span.
 * Returns an empty object when no span is active or OTEL is not configured.
 */
export function getActiveTraceIds(): { trace_id?: string; span_id?: string } {
  const span = trace.getActiveSpan();
  if (!span) return {};
  const ctx = span.spanContext();
  // OTEL no-op spans have all-zero IDs — treat as no active span.
  if (ctx.traceId === '00000000000000000000000000000000') return {};
  return { trace_id: ctx.traceId, span_id: ctx.spanId };
}

/**
 * Execute fn inside a new span named `name`.
 * Works for both sync and async functions.
 * Mirrors Python @trace decorator behaviour: records exceptions, sets ERROR status.
 */
export function withTrace<T>(name: string, fn: () => T): T {
  const tracer = trace.getTracer(TRACER_NAME);
  return tracer.startActiveSpan(name, (span) => {
    try {
      const result = fn();
      if (result instanceof Promise) {
        return result.then(
          (value) => {
            span.end();
            return value;
          },
          (err: unknown) => {
            span.recordException(err instanceof Error ? err : new Error(String(err)));
            span.setStatus({ code: SpanStatusCode.ERROR, message: String(err) });
            span.end();
            throw err;
          },
        ) as T;
      }
      span.end();
      return result;
    } catch (err) {
      span.recordException(err instanceof Error ? err : new Error(String(err)));
      span.setStatus({ code: SpanStatusCode.ERROR, message: String(err) });
      span.end();
      throw err;
    }
  });
}

/**
 * Method/function decorator that wraps the target in withTrace().
 * Span name defaults to the decorated method name.
 *
 * Usage (requires experimentalDecorators: true):
 *   class Foo {
 *     @trace('my.operation')
 *     doWork() { ... }
 *   }
 */
// Stryker disable BlockStatement: outer and inner decorator fns returning undefined leave descriptors unchanged — equivalent
export function traceDecorator(name?: string) {
  return function (
    _target: object,
    propertyKey: string | symbol,
    descriptor: PropertyDescriptor,
  ): PropertyDescriptor {
    // Stryker enable BlockStatement
    // Stryker disable next-line LogicalOperator: span name not observable with no-op tracer
    const spanName = name ?? String(propertyKey);
    const original = descriptor.value as (...args: unknown[]) => unknown;
    descriptor.value = function (this: unknown, ...args: unknown[]) {
      return withTrace(spanName, () => original.apply(this, args));
    };
    return descriptor;
  };
}
