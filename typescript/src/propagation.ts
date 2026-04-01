// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * W3C trace context propagation helpers.
 * Mirrors Python provide.telemetry.propagation.
 */

import { bindContext, unbindContext } from './context';

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
 * Parse a W3C baggage header value into key-value pairs.
 * Format: ``key1=value1, key2=value2;prop=p``
 * Properties after ``;`` are stripped. Keys and values are whitespace-stripped.
 * Mirrors Python provide.telemetry.propagation.parse_baggage.
 */
export function parseBaggage(raw: string): Record<string, string> {
  const result: Record<string, string> = {};
  for (const member of raw.split(',')) {
    const kv = member.split(';', 1)[0]; // strip properties
    const eqIdx = kv.indexOf('=');
    if (eqIdx < 1) continue; // no '=' or empty key
    const key = kv.slice(0, eqIdx).trim();
    if (key) {
      result[key] = kv.slice(eqIdx + 1).trim();
    }
  }
  return result;
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

  // Size guards — treat oversized headers as absent.
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
      const carrier: Record<string, string> = { traceparent: ctx.traceparent };
      /* Stryker disable next-line ConditionalExpression: tracestate fallback '' vs undefined — OTel extract handles both identically */
      if (ctx.tracestate) carrier['tracestate'] = ctx.tracestate;
      const extracted = otelApi.propagation.extract(otelApi.context.active(), carrier);
      _otelContextStack.push(extracted);
    } catch {
      // OTel API not available — graceful degradation, push undefined sentinel.
      _otelContextStack.push(undefined);
    }
  } else {
    _otelContextStack.push(undefined);
  }
}

/**
 * Pop the last saved context, restoring the previous state.
 * Unbinds any baggage.* log context entries injected by the cleared frame.
 */
// Stryker disable BlockStatement
export function clearPropagationContext(): void {
  const store = _ensureStore();
  // Stryker disable next-line ConditionalExpression,EqualityOperator
  if (store.stack.length > 0) {
    // Stryker enable BlockStatement
    const restored = _stack.pop();
    /* v8 ignore next */
    _active = restored ?? {};
  } else {
    // Stryker disable BlockStatement: empty else body is equivalent — active is always {} here because pop() restores prior state
    store.active = {};
  }
  store.otelCtxStack.pop();
  // Unbind baggage.* keys injected by the frame being cleared.
  const baggageKeys = store.baggageKeyStack.pop() ?? [];
  for (const key of baggageKeys) {
    unbindContext(key);
  }
  _otelContextStack.pop();
}
// Stryker enable BlockStatement

/** Return the currently active propagation context. */
export function getActivePropagationContext(): PropagationContext {
  return { ..._getStore().active };
}

/** Return the top of the OTel context stack, or undefined if empty/no OTel wiring. */
export function getActiveOtelContext(): unknown | undefined {
  const stack = _getStore().otelCtxStack;
  // Stryker disable next-line ConditionalExpression: empty stack returns undefined; removing returns undefined from array[-1] which is also undefined
  if (stack.length === 0) return undefined;
  return stack[stack.length - 1];
}

/** Return the top of the OTel context stack, or undefined if empty/no OTel wiring. */
export function getActiveOtelContext(): unknown | undefined {
  if (_otelContextStack.length === 0) return undefined;
  return _otelContextStack[_otelContextStack.length - 1];
}

export function _resetPropagationForTests(): void {
  _stack.length = 0;
  _otelContextStack.length = 0;
  _active = {};
}
