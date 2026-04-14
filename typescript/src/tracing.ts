// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Tracing helpers — mirrors Python provide.telemetry @trace decorator and tracer access.
 *
 * Uses @opentelemetry/api which provides no-op implementations when no SDK is registered.
 * withTrace() / @trace work safely without any OTEL setup; they just don't export spans.
 */

import {
  type Tracer,
  type Span,
  SpanStatusCode,
  trace,
  context as otelContext,
} from '@opentelemetry/api';
import { _emittedField, _incrementHealth } from './health';
import { getActiveOtelContext } from './propagation';
import { randomHex } from './hash';
import { shouldAllow } from './consent';
import { shouldSample } from './sampling';
import { tryAcquire, release } from './backpressure';

// Stryker disable next-line StringLiteral: tracer name is not observable without a real SDK
const TRACER_NAME = '@provide-io/telemetry';

// ── Manual trace context (injected without an active OTEL span) ───────────────
//
// Module-level globals are the fallback storage.  They are **not** safe when
// two overlapping async flows each call setTraceContext / withTrace without
// awaiting each other — one flow's state would leak into the other's Promise
// continuation.  When running on Node we reach for AsyncLocalStorage so each
// async chain gets its own isolated pair of IDs; the globals are reserved for
// non-scoped callers (direct setTraceContext usage) and for browser/Deno
// environments where AsyncLocalStorage is not available.
//
// Reads check the ALS store first, then fall back to the globals.  Writes via
// setTraceContext() prefer the ALS store when one is active (so a per-request
// scope wins over the globals), otherwise fall back to the globals (so the
// classic "set it once at boot" pattern still works).

type _TraceIds = { traceId?: string; spanId?: string };

let _als: {
  run<T>(store: _TraceIds, fn: () => T): T;
  getStore(): _TraceIds | undefined;
} | null = null;

try {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { AsyncLocalStorage } = require('node:async_hooks') as typeof import('node:async_hooks');
  _als = new AsyncLocalStorage<_TraceIds>();
} catch {
  // Non-Node runtime (browser, Deno): fall back to module globals.
  /* c8 ignore next */
  _als = null;
}

let _manualTraceId: string | undefined;
let _manualSpanId: string | undefined;

/**
 * Manually inject trace/span IDs (e.g. from an incoming request header).
 * Returned by getTraceContext(); cleared by _resetTraceContext().
 * Pass undefined (or empty string) for either argument to clear that ID.
 */
export function setTraceContext(traceId: string | undefined, spanId: string | undefined): void {
  // Treat empty strings as clearing the value — prevents empty-string IDs in logs.
  const normalizedTraceId = traceId || undefined;
  const normalizedSpanId = spanId || undefined;
  const store = _als?.getStore();
  if (store !== undefined) {
    store.traceId = normalizedTraceId;
    store.spanId = normalizedSpanId;
    return;
  }
  _manualTraceId = normalizedTraceId;
  _manualSpanId = normalizedSpanId;
}

/**
 * Return the current trace context: manual injection first, then active OTEL span.
 */
export function getTraceContext(): { trace_id?: string; span_id?: string } {
  const store = _als?.getStore();
  const traceId = store?.traceId ?? _manualTraceId;
  const spanId = store?.spanId ?? _manualSpanId;
  // Stryker disable next-line ConditionalExpression,LogicalOperator: setTraceContext always sets both; partial state not reachable via public API
  if (traceId !== undefined || spanId !== undefined) {
    return {
      // Stryker disable next-line ConditionalExpression: _manualTraceId is always defined here (both set together)
      ...(_manualTraceId !== undefined && { traceId: _manualTraceId }),
      // Stryker disable next-line ConditionalExpression: _manualSpanId is always defined here (both set together)
      ...(_manualSpanId !== undefined && { spanId: _manualSpanId }),
    };
  }
  const ids = getActiveTraceIds();
  return {
    ...(ids.trace_id !== undefined && { trace_id: ids.trace_id }),
    ...(ids.span_id !== undefined && { span_id: ids.span_id }),
  };
}

/** Reset manually injected trace context (used in tests). */
export function _resetTraceContext(): void {
  _manualTraceId = undefined;
  _manualSpanId = undefined;
  const store = _als?.getStore();
  if (store !== undefined) {
    store.traceId = undefined;
    store.spanId = undefined;
  }
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

const NOOP_TRACE_ID = '00000000000000000000000000000000';

/**
 * Return true if the given span is a no-op (all-zero trace ID).
 * Used to decide whether to inject synthetic random IDs.
 */
function _isNoopSpan(span: Span): boolean {
  // Stryker disable next-line ConditionalExpression: without a registered OTel SDK all spans are noop — mutating to true is equivalent
  return span.spanContext().traceId === NOOP_TRACE_ID;
}

/**
 * Execute fn with random synthetic trace/span IDs set as manual context,
 * then restore the previous manual context when done.
 * Handles both sync and async results.
 */
function _withSyntheticIds<T>(fn: () => T): T {
  const prevTraceId = _manualTraceId;
  const prevSpanId = _manualSpanId;
  // Stryker disable next-line StringLiteral: random IDs are non-deterministic — exact value not observable in mutations
  setTraceContext(randomHex(16), randomHex(8));
  const result = fn();
  if (result instanceof Promise) {
    return result.then(
      (value) => {
        _manualTraceId = prevTraceId;
        _manualSpanId = prevSpanId;
        return value;
      },
      (err: unknown) => {
        _manualTraceId = prevTraceId;
        _manualSpanId = prevSpanId;
        throw err;
      },
    ) as T;
  }
  _manualTraceId = prevTraceId;
  _manualSpanId = prevSpanId;
  return result;
}

/** Shared span handler for withTrace — records exceptions and sets ERROR status. */
function _spanHandler<T>(fn: () => T, span: Span): T {
  _incrementHealth(_emittedField('traces'));
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
}

/**
 * Execute fn inside a new span named `name`.
 * Works for both sync and async functions.
 * Mirrors Python @trace decorator behaviour: records exceptions, sets ERROR status.
 */
export function withTrace<T>(name: string, fn: () => T): T {
  if (!getConfig().tracingEnabled) return fn();
  // Stryker disable next-line StringLiteral: 'traces' vs '' is equivalent — shouldAllow treats any non-'logs'/non-'context' signal identically across all consent levels
  if (!shouldAllow('traces')) return fn();
  if (!shouldSample('traces', name)) return fn();
  const ticket = tryAcquire('traces');
  if (!ticket) return fn();

  const tracer = trace.getTracer(TRACER_NAME);

  // If an OTel context was extracted from propagation headers, use it as parent.
  // Narrow the try/catch to getActiveOtelContext() only so that errors inside
  // otelContext.with() propagate naturally instead of being swallowed and causing
  // a second span attempt in the fallback path without holding a backpressure slot.
  let activeCtx: ReturnType<typeof getActiveOtelContext> | undefined;
  try {
    const activeCtx = getActiveOtelContext();
    if (activeCtx) {
      try {
        return otelContext.with(activeCtx as ReturnType<typeof otelContext.active>, () =>
          tracer.startActiveSpan(name, (span: Span) => {
            // Stryker disable next-line ConditionalExpression: noop detection is not observable without SDK — branch outcome equivalent under mutation
            /* v8 ignore start: noop-span false branch + real-span return are unreachable without a registered OTel provider */
            if (_isNoopSpan(span)) return _withSyntheticIds(() => _spanHandler(fn, span));
            return _spanHandler(fn, span);
            /* v8 ignore stop */
          }),
        );
      } finally {
        release(ticket);
      }
    }
  } catch {
    // getActiveOtelContext() threw — graceful degradation, fall through to default behaviour.
  }

  try {
    return tracer.startActiveSpan(name, (span: Span) => {
      // Stryker disable next-line ConditionalExpression: noop detection is not observable without SDK — branch outcome equivalent under mutation
      if (_isNoopSpan(span)) return _withSyntheticIds(() => _spanHandler(fn, span));
      return _spanHandler(fn, span);
    });
  } finally {
    release(ticket);
  }
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
