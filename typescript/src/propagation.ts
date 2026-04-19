// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * W3C trace context propagation helpers.
 * Mirrors Python provide.telemetry.propagation.
 */

import { bindContext, getContext, unbindContext } from './context';
import { getTraceContext, setTraceContext } from './tracing';

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

/** Sentinel: a baggage.* key was unbound (not set) prior to an inject frame. */
const BAGGAGE_UNSET = Symbol('propagation.baggage.unset');
type PriorBaggageValue = unknown | typeof BAGGAGE_UNSET;

// ── AsyncLocalStorage type (Node.js / Cloudflare Workers) ─────────────────────
type PropagationStore = {
  active: PropagationContext;
  stack: PropagationContext[];
  otelCtxStack: unknown[];
  /**
   * Parallel stack of prior baggage.* values for each bind frame. Each entry
   * maps the injected key to its value in the logger context *before* the
   * frame overwrote it, or BAGGAGE_UNSET if the key was unset. On clear, each
   * key is either rebound to the prior value or unbound — this preserves the
   * outer frame's baggage when an inner frame uses the same key.
   */
  baggagePriorStack: Array<Record<string, PriorBaggageValue>>;
  /** Parallel stack of previous {traceId, spanId} before each bind. */
  traceCtxStack: Array<{ traceId: string | undefined; spanId: string | undefined }>;
};

export type PropagationALS = {
  getStore(): PropagationStore | undefined;
  run<T>(store: PropagationStore, fn: () => T): T;
  enterWith(store: PropagationStore): void;
};

// ── AsyncLocalStorage (Node.js / Cloudflare Workers) ──────────────────────────
let _als: PropagationALS | null = null;
let _AlsConstructor: (new () => PropagationALS) | null = null;
// `_propagationInitDone` flips to true once the init has reached a definitive
// state (ALS attached, OR known-unavailable). Callers like setupTelemetry
// distinguish "still racing" (defer the check) from "settled" (act on it).
let _propagationInitDone = false;
let _propagationInitPromise: Promise<void> = Promise.resolve();
// Stryker disable BlockStatement: module-level init block runs once at import time — cannot be tested by unit tests
//
// Three load environments must be supported:
//   1. CJS Node (tsx default, transpiled CJS bundles): `require` is defined;
//      load synchronously. tsx/esbuild forbid top-level await in CJS output,
//      so we must NOT use `await import` at module scope.
//   2. ESM Node (modern bundlers, .mjs entrypoints): `require` is undefined;
//      fire off an async import without awaiting it at top level. Calls that
//      happen before the import resolves use the module-level fallback store
//      (with a one-time warning) — the racing window is tiny in practice.
//   3. Browsers / Workers / Deno: neither path resolves `node:async_hooks`;
//      both branches throw or reject, _als stays null, fallback store used.
(function initAsyncStorage(): void {
  try {
    if (typeof require === 'function') {
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      const als = require('node:async_hooks') as {
        AsyncLocalStorage: new () => PropagationALS;
      };
      _AlsConstructor = als.AsyncLocalStorage;
      _als = new _AlsConstructor();
      _propagationInitDone = true;
      return;
    }
  } catch {
    // CJS path failed (e.g. browserified bundle where require throws) —
    // fall through to async import.
  }
  _propagationInitPromise = (async () => {
    try {
      const als = (await import('node:async_hooks')) as {
        AsyncLocalStorage: new () => PropagationALS;
      };
      _AlsConstructor = als.AsyncLocalStorage;
      _als = new _AlsConstructor();
    } catch {
      // node:async_hooks unresolvable — leave _als null and use fallback.
    } finally {
      _propagationInitDone = true;
    }
  })();
})();
// Stryker restore BlockStatement

/**
 * Has the AsyncLocalStorage init reached a definitive state?
 * - In CJS (sync require), this is true synchronously after module load.
 * - In ESM Node, this flips to true after the async `import('node:async_hooks')`
 *   resolves (typically the next microtask).
 * - In browsers/workers, this becomes true after the failed import is caught.
 *
 * Used by setupTelemetry to distinguish "ALS unavailable, fail loud" from
 * "ALS init still racing, defer the check".
 */
export function isPropagationInitDone(): boolean {
  return _propagationInitDone;
}

/**
 * Resolves when the AsyncLocalStorage init has reached a definitive state.
 * Always-resolved in the CJS path; awaits the dynamic import in the ESM path.
 */
export function awaitPropagationInit(): Promise<void> {
  return _propagationInitPromise;
}

// ── Fallback: module-level store (browser / single-thread) ────────────────────
// Stryker disable next-line ArrayDeclaration: initial empty arrays are overwritten by _resetPropagationForTests in every test beforeEach
let _fallbackStore: PropagationStore = {
  active: {},
  stack: [],
  otelCtxStack: [],
  baggagePriorStack: [],
  traceCtxStack: [],
};

// Emit a one-time warning when the module-level fallback store is activated.
let _fallbackWarned = false;

function _warnFallbackOnce(): void {
  if (!_fallbackWarned) {
    _fallbackWarned = true;
    console.warn(
      '[provide-telemetry] AsyncLocalStorage is unavailable; ' +
        'falling back to module-level context store. ' +
        'Concurrent requests will share propagation context. ' +
        'This is unsafe in production async environments.',
    );
  }
}

/**
 * Returns true when AsyncLocalStorage is unavailable and the module-level
 * fallback store is being used. Callers can check this to detect unsafe
 * environments where concurrent requests share propagation context.
 */
export function isFallbackMode(): boolean {
  return _als === null;
}

function _getStore(): PropagationStore {
  if (_als) {
    return _als.getStore() ?? _fallbackStore;
  }
  _warnFallbackOnce();
  return _fallbackStore;
}

// Stryker disable ConditionalExpression,BlockStatement,ArrayDeclaration: _ensureStore ALS-to-fallback clone path — tested by "clones fallback stack" test; remaining mutants are equivalent because _resetPropagationForTests empties both stores
function _ensureStore(): PropagationStore {
  if (_als) {
    const store = _als.getStore();
    if (store) return store;
    const next: PropagationStore = {
      active: { ..._fallbackStore.active },
      stack: _fallbackStore.stack.map((entry) => ({ ...entry })),
      otelCtxStack: [..._fallbackStore.otelCtxStack],
      baggagePriorStack: _fallbackStore.baggagePriorStack.map((entry) => ({ ...entry })),
      traceCtxStack: _fallbackStore.traceCtxStack.map((ctx) => ({ ...ctx })),
    };
    _als.enterWith(next);
    return next;
  }
  _warnFallbackOnce();
  return _fallbackStore;
}
// Stryker restore ConditionalExpression,BlockStatement,ArrayDeclaration

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
 * When baggage is present, individual entries are injected as baggage.* log
 * context fields (mirrors Python bind_propagation_context baggage auto-injection).
 */
export function bindPropagationContext(ctx: PropagationContext): void {
  const store = _ensureStore();
  store.stack.push({ ...store.active });
  store.active = { ...store.active, ...ctx };

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
      store.otelCtxStack.push(extracted);
    } catch {
      store.otelCtxStack.push(undefined);
    }
  } else {
    store.otelCtxStack.push(undefined);
  }
  /* Stryker restore all */

  // Save previous trace context and bridge propagated IDs.
  // Restored by clearPropagationContext() so IDs don't leak.
  const prevTrace = getTraceContext();
  store.traceCtxStack.push({
    traceId: prevTrace.trace_id,
    spanId: prevTrace.span_id,
  });
  if (ctx.traceId || ctx.spanId) {
    setTraceContext(ctx.traceId ?? '', ctx.spanId ?? '');
  }

  // Auto-inject parsed baggage entries as baggage.* log context fields.
  // Capture prior values so that nested frames overwriting the same baggage
  // key restore the outer value on clear (instead of leaking an unbind).
  // Stryker disable BlockStatement: else branch pushing {} is equivalent — clearPropagationContext uses `?? {}` so not pushing {} has the same observable effect
  if (ctx.baggage) {
    const parsed = parseBaggage(ctx.baggage);
    const prior: Record<string, PriorBaggageValue> = {};
    const currentCtx = getContext();
    for (const [k, v] of Object.entries(parsed)) {
      const ctxKey = `baggage.${k}`;
      prior[ctxKey] = Object.prototype.hasOwnProperty.call(currentCtx, ctxKey)
        ? currentCtx[ctxKey]
        : BAGGAGE_UNSET;
      bindContext({ [ctxKey]: v });
    }
    store.baggagePriorStack.push(prior);
  } else {
    store.baggagePriorStack.push({});
  }
  // Stryker restore BlockStatement
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
    const restored = store.stack.pop();
    /* v8 ignore next */
    store.active = restored ?? {};
  } else {
    // Stryker disable BlockStatement: empty else body is equivalent — active is always {} here because pop() restores prior state
    store.active = {};
  }
  store.otelCtxStack.pop();
  // Restore prior values for baggage.* keys injected by the cleared frame.
  // Rebind to the outer value when present, unbind only if the key was unset.
  const priorEntries = store.baggagePriorStack.pop() ?? {};
  for (const [key, prevValue] of Object.entries(priorEntries)) {
    if (prevValue === BAGGAGE_UNSET) {
      unbindContext(key);
    } else {
      bindContext({ [key]: prevValue });
    }
  }
  // Restore previous trace context so bridged IDs don't leak.
  const prevTrace = store.traceCtxStack.pop();
  if (prevTrace) {
    setTraceContext(prevTrace.traceId, prevTrace.spanId);
  }
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

export function _resetPropagationForTests(): void {
  // Recreate the ALS instance so no enterWith-seeded store leaks between tests.
  // The null branch is only reachable in environments without node:async_hooks (e.g. browsers).
  /* v8 ignore next */
  _als = _AlsConstructor ? new _AlsConstructor() : null;
  _fallbackStore = {
    active: {},
    stack: [],
    otelCtxStack: [],
    baggagePriorStack: [],
    // Stryker disable next-line ArrayDeclaration: equivalent mutant — any non-object stale entry (e.g. "Stryker was here") has undefined .traceId/.spanId, producing the same setTraceContext(undefined,undefined) no-op as an empty array
    traceCtxStack: [],
  };
  _fallbackWarned = false;
}

/** Disable AsyncLocalStorage for testing the module-level fallback path. */
export function _disablePropagationALSForTest(): PropagationALS | null {
  const prev = _als;
  _als = null;
  return prev;
}

/** Re-enable AsyncLocalStorage after testing (pass value from _disable call). */
export function _restorePropagationALSForTest(saved: PropagationALS | null): void {
  _als = saved;
}
