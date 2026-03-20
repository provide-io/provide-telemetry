// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: AGPL-3.0-or-later

/**
 * W3C trace context propagation helpers.
 * Mirrors Python undef.telemetry.propagation.
 */

export interface PropagationContext {
  traceparent?: string;
  tracestate?: string;
  baggage?: string;
  traceId?: string;
  spanId?: string;
}

/** Stack of saved contexts for bind/clear pairs. */
// Stryker disable next-line ArrayDeclaration
const _stack: PropagationContext[] = [];

/** Active bound context (most recently pushed layer). */
let _active: PropagationContext = {};

function _parseTraceparent(value: string): { traceId?: string; spanId?: string } {
  const parts = value.split('-');
  if (parts.length !== 4) return {};
  const [version, traceId, spanId, _flags] = parts;
  if (version.length !== 2 || traceId.length !== 32 || spanId.length !== 16) return {};
  if (version.toLowerCase() === 'ff') return {};
  if (traceId === '0'.repeat(32) || spanId === '0'.repeat(16)) return {};
  // Validate that all fields are valid hex strings.
  if (!/^[0-9a-fA-F]+$/.test(version) || !/^[0-9a-fA-F]+$/.test(traceId) || !/^[0-9a-fA-F]+$/.test(spanId)) {
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

  const rawTraceparent = lower['traceparent'];
  const tracestate = lower['tracestate'];
  const baggage = lower['baggage'];

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
 */
export function bindPropagationContext(ctx: PropagationContext): void {
  _stack.push({ ..._active });
  _active = { ..._active, ...ctx };
}

/**
 * Pop the last saved context, restoring the previous state.
 */
// Stryker disable BlockStatement
export function clearPropagationContext(): void {
  // Stryker disable next-line ConditionalExpression,EqualityOperator
  if (_stack.length > 0) {
    // Stryker enable BlockStatement
    _active = _stack.pop()!;
  } else {
    // Stryker disable BlockStatement: empty else body is equivalent — _active is always {} here because pop() restores prior state
    _active = {};
  }
}
// Stryker enable BlockStatement

/** Return the currently active propagation context. */
export function getActivePropagationContext(): PropagationContext {
  return { ..._active };
}

export function _resetPropagationForTests(): void {
  _stack.length = 0;
  _active = {};
}
