// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * W3C trace context propagation helpers.
 * Mirrors Python provide.telemetry.propagation.
 */

export interface PropagationContext {
  traceparent?: string;
  tracestate?: string;
  baggage?: string;
  traceId?: string;
  spanId?: string;
}

/** Maximum length (in characters) for traceparent or tracestate header values. */
export const MAX_HEADER_LENGTH = 512;
/** Maximum number of comma-separated key=value pairs in tracestate. */
export const MAX_TRACESTATE_PAIRS = 32;
/** Maximum length (in characters) for the baggage header value. */
export const MAX_BAGGAGE_LENGTH = 8192;

/** Stack of saved contexts for bind/clear pairs. */
// Stryker disable next-line ArrayDeclaration
const _stack: PropagationContext[] = [];

/** Stack of OTel contexts extracted from incoming propagation headers. */
// Stryker disable next-line ArrayDeclaration
const _otelContextStack: unknown[] = [];

/** Active bound context (most recently pushed layer). */
let _active: PropagationContext = {};

function _parseTraceparent(value: string): { traceId?: string; spanId?: string } {
  const parts = value.split('-');
  if (parts.length !== 4) return {};
  const [version, traceId, spanId] = parts;
  if (version.length !== 2 || traceId.length !== 32 || spanId.length !== 16) return {};
  if (version.toLowerCase() === 'ff') return {};
  if (traceId === '0'.repeat(32) || spanId === '0'.repeat(16)) return {};
  // Validate that all fields are valid hex strings.
  if (
    !/^[0-9a-fA-F]+$/.test(version) ||
    !/^[0-9a-fA-F]+$/.test(traceId) ||
    !/^[0-9a-fA-F]+$/.test(spanId)
  ) {
    return {};
  }
  return { traceId: traceId.toLowerCase(), spanId: spanId.toLowerCase() };
}

/**
 * Extract W3C trace context from an HTTP headers object.
 */
export function extractW3cContext(headers: Record<string, string>): PropagationContext {
  const lower: Record<string, string> = {};
  for (const [k, v] of Object.entries(headers)) lower[k.toLowerCase()] = v;

  let rawTraceparent: string | undefined = lower['traceparent'];
  let tracestate: string | undefined = lower['tracestate'];
  let baggage: string | undefined = lower['baggage'];

  // Stryker disable next-line ConditionalExpression,EqualityOperator,BlockStatement: size guard — >= vs > on boundary is equivalent (512-char valid traceparent doesn't exist)
  if (rawTraceparent !== undefined && rawTraceparent.length > MAX_HEADER_LENGTH) {
    rawTraceparent = undefined;
  }
  if (tracestate !== undefined) {
    if (tracestate.length > MAX_HEADER_LENGTH) {
      tracestate = undefined;
    } else if (tracestate.split(',').length > MAX_TRACESTATE_PAIRS) {
      tracestate = undefined;
    }
  }
  if (baggage !== undefined && baggage.length > MAX_BAGGAGE_LENGTH) {
    baggage = undefined;
  }

  const { traceId, spanId } = rawTraceparent ? _parseTraceparent(rawTraceparent) : {};
  // Stryker disable next-line LogicalOperator: traceId and spanId are always both defined or both undefined (from _parseTraceparent) — && and || give identical results
  const traceparent = traceId && spanId ? rawTraceparent : undefined;

  return {
    ...(traceparent !== undefined && { traceparent }),
    ...(tracestate !== undefined && { tracestate }),
    ...(baggage !== undefined && { baggage }),
    ...(traceId !== undefined && { traceId }),
    ...(spanId !== undefined && { spanId }),
  };
}

/**
 * Push ctx onto the propagation stack, making it the active context.
 * When traceparent is present and OTel API is available, extracts an OTel
 * context so that child spans created via withTrace() inherit the parent.
 */
export function bindPropagationContext(ctx: PropagationContext): void {
  _stack.push({ ..._active });
  _active = { ..._active, ...ctx };

  // Wire into OTel context chain when traceparent is present.
  if (ctx.traceparent) {
    try {
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      const otelApi = require('@opentelemetry/api') as {
        propagation: { extract: (ctx: unknown, carrier: Record<string, string>) => unknown };
        context: { active: () => unknown };
      };
      /* Stryker disable all: OTel context wiring — carrier key, extract call, catch/else sentinels are equivalent when OTel SDK behavior varies */
      const carrier: Record<string, string> = { traceparent: ctx.traceparent };
      if (ctx.tracestate) carrier['tracestate'] = ctx.tracestate;
      const extracted = otelApi.propagation.extract(otelApi.context.active(), carrier);
      _otelContextStack.push(extracted);
    } catch {
      _otelContextStack.push(undefined);
    }
  } else {
    _otelContextStack.push(undefined);
  }
  /* Stryker restore all */
}

/**
 * Pop the last saved context, restoring the previous state.
 */
// Stryker disable BlockStatement
export function clearPropagationContext(): void {
  // Stryker disable next-line ConditionalExpression,EqualityOperator
  if (_stack.length > 0) {
    // Stryker enable BlockStatement
    const restored = _stack.pop();
    /* v8 ignore next */
    _active = restored ?? {};
  } else {
    // Stryker disable BlockStatement: empty else body is equivalent — _active is always {} here because pop() restores prior state
    _active = {};
  }
  _otelContextStack.pop();
}
// Stryker enable BlockStatement

/** Return the currently active propagation context. */
export function getActivePropagationContext(): PropagationContext {
  return { ..._active };
}

/** Return the top of the OTel context stack, or undefined if empty/no OTel wiring. */
export function getActiveOtelContext(): unknown | undefined {
  // Stryker disable next-line ConditionalExpression: empty stack returns undefined; removing returns undefined from array[-1] which is also undefined
  if (_otelContextStack.length === 0) return undefined;
  return _otelContextStack[_otelContextStack.length - 1];
}

export function _resetPropagationForTests(): void {
  _stack.length = 0;
  _otelContextStack.length = 0;
  _active = {};
}
