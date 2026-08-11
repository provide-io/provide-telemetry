// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * W3C trace context propagation helpers.
 * Mirrors Python provide.telemetry.propagation.
 */

import {
  type AsyncLocalStorageLike,
  _setAsyncStorageInitDoneForTest,
  awaitAsyncStorageInit,
  createScopedStorage,
  isAsyncStorageInitDone,
} from './async-storage.js';
import { bindContext, getContext, unbindContext } from './context.js';
import { getTraceContext, setTraceContext } from './tracing.js';

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

export type PropagationALS = AsyncLocalStorageLike<PropagationStore>;

// ── AsyncLocalStorage (Node.js / Cloudflare Workers) ──────────────────────────
// The require/import dance that used to live here now lives in
// src/async-storage.ts, shared with context.ts and tracing.ts so all three
// behave identically in the published ESM artifact.
const _storage = createScopedStorage<PropagationStore>();

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
  return isAsyncStorageInitDone();
}

/**
 * Resolves when the AsyncLocalStorage init has reached a definitive state.
 * Always-resolved in the CJS path; awaits the dynamic import in the ESM path.
 */
export function awaitPropagationInit(): Promise<void> {
  return awaitAsyncStorageInit();
}

// ── Fallback: module-level store (browser / single-thread) ────────────────────
// Stryker disable ArrayDeclaration: initial empty arrays are equivalent —
// every test file resets this store via _resetPropagationForTests before
// asserting on it, and a stray "Stryker was here" entry as the sole element
// of an otherwise-untouched stack is never observed by any test.
let _fallbackStore: PropagationStore = {
  active: {},
  stack: [],
  otelCtxStack: [],
  baggagePriorStack: [],
  traceCtxStack: [],
};
// Stryker restore ArrayDeclaration

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
  return _storage.get() === null;
}

function _getStore(): PropagationStore {
  const als = _storage.get();
  if (als) {
    return als.getStore() ?? _fallbackStore;
  }
  _warnFallbackOnce();
  return _fallbackStore;
}

// Stryker disable ConditionalExpression,BlockStatement,ArrayDeclaration: _ensureStore ALS-to-fallback clone path — tested by "clones fallback stack" test; remaining mutants are equivalent because _resetPropagationForTests empties both stores
function _ensureStore(): PropagationStore {
  const als = _storage.get();
  if (als) {
    const store = als.getStore();
    if (store) return store;
    const next: PropagationStore = {
      active: { ..._fallbackStore.active },
      stack: _fallbackStore.stack.map((entry) => ({ ...entry })),
      otelCtxStack: [..._fallbackStore.otelCtxStack],
      baggagePriorStack: _fallbackStore.baggagePriorStack.map((entry) => ({ ...entry })),
      traceCtxStack: _fallbackStore.traceCtxStack.map((ctx) => ({ ...ctx })),
    };
    als.enterWith(next);
    return next;
  }
  _warnFallbackOnce();
  return _fallbackStore;
}
// Stryker restore ConditionalExpression,BlockStatement,ArrayDeclaration

/**
 * True when every tracestate list member fits the W3C grammar: OWS, a key
 * starting with lcalpha/digit followed by up to 255 of the spec's key
 * characters (multi-tenant "@" included), "=", a value of printable ASCII
 * minus comma and equals, OWS. One bad member discards the whole header.
 *
 * A security boundary, not pedantry: a kept tracestate is forwarded verbatim
 * into outbound headers (and the OTel carrier), so a surviving control
 * character — CR/LF especially — is header injection at the next hop. Mirrors
 * Python's `_is_forwardable_tracestate` (parity category:
 * propagation_tracestate_grammar).
 *
 * The pattern lives inside the function, not at module level, for the same
 * reason as isBaggageToken: a module-level regex is a static mutant Stryker
 * can never kill, and this is a security boundary that must stay genuinely
 * covered.
 */
function isForwardableTracestate(value: string): boolean {
  const member = /^[ \t]*[a-z0-9][a-z0-9_\-*/@]{0,255}=[\x20-\x2b\x2d-\x3c\x3e-\x7e]*[ \t]*$/;
  return value.split(',').every((part) => member.test(part));
}

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
/**
 * True when `key` is an RFC 7230 token, which the W3C Baggage spec requires.
 *
 * The pattern lives inside the function rather than in a module-level const on
 * purpose. A module-level regex is a *static* mutant: it is evaluated once at
 * import, before Stryker flips its per-test mutant switch, so mutations of it
 * can never be killed no matter what the tests assert — they are reported as
 * survived and the pattern effectively escapes mutation testing. This is a
 * security boundary (see parseBaggage), so it must be genuinely covered. The
 * cost is one RegExp wrapper per call; V8 caches the compiled pattern.
 */
function isBaggageToken(key: string): boolean {
  return /^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$/.test(key);
}

/** Strip C0/C1 controls except TAB from a baggage value. Inlined for the same reason. */
function stripBaggageControls(value: string): string {
  // eslint-disable-next-line no-control-regex -- stripping control characters is the point
  return value.replace(/[\x00-\x08\x0a-\x1f\x7f]/g, '');
}

/**
 * Parse a W3C baggage header into key-value pairs.
 *
 * Keys must be RFC 7230 tokens and control characters are stripped from values.
 * This is a security boundary: a baggage key becomes a log-attribute key, and the
 * console renderer emits keys bare, so a newline in a key from an untrusted
 * inbound header would forge an entire additional log record.
 */
export function parseBaggage(raw: string): Record<string, string> {
  const result: Record<string, string> = {};
  for (const member of raw.split(',')) {
    const kv = member.split(';', 1)[0]; // strip properties
    const eqIdx = kv.indexOf('=');
    if (eqIdx < 1) continue; // no '=' or empty key
    const key = kv.slice(0, eqIdx).trim();
    if (key && isBaggageToken(key)) {
      result[key] = stripBaggageControls(kv.slice(eqIdx + 1).trim());
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
    } else if (!isForwardableTracestate(tracestate)) {
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
  // Drop the ALS instance so no enterWith-seeded store leaks between tests;
  // the next access builds a fresh one.
  _storage.reset();
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
  return _storage.suppress();
}

/** Re-enable AsyncLocalStorage after testing (pass value from _disable call). */
export function _restorePropagationALSForTest(saved: PropagationALS | null): void {
  _storage.restore(saved);
}

/**
 * Override the propagation-init-done flag for testing. Returns the previous
 * value so the caller can restore it. Used to exercise setupTelemetry's
 * deferred-check branch (which fires only when init is still racing — a state
 * not naturally reachable in unit tests because module-level init has long
 * since settled by the time the test runs).
 */
export function _setPropagationInitDoneForTest(done: boolean): boolean {
  return _setAsyncStorageInitDoneForTest(done);
}
