// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Module-level context binding — mirrors Python provide.telemetry bind_context/unbind_context.
 *
 * In browser environments, context is stored in a module-level object. All log calls
 * in the same JS execution context share the same bindings.
 *
 * In Node.js environments, AsyncLocalStorage provides per-async-context isolation
 * (useful for SSR / worker processes where multiple requests run concurrently).
 * Use runWithContext() to scope bindings to a single request/operation.
 */

type Context = Record<string, unknown>;

// ── AsyncLocalStorage type (Node.js / Cloudflare Workers) ─────────────────────
type ALS = {
  getStore(): Context | undefined;
  run<T>(store: Context, fn: () => T): T;
  enterWith(store: Context): void;
};

// ── AsyncLocalStorage (Node.js / Cloudflare Workers) ──────────────────────────
let _asyncLocalStorage: ALS | null = null;
let _AlsConstructor: (new () => ALS) | null = null;
try {
  // Dynamic require so the import doesn't break browser bundles.
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const als = require('node:async_hooks') as { AsyncLocalStorage: new () => ALS };
  _AlsConstructor = als.AsyncLocalStorage;
  _asyncLocalStorage = new _AlsConstructor();
} catch {
  // Not available — fall back to module-level context below.
}

// ── Fallback: module-level context (browser / single-thread) ──────────────────
let _moduleCtx: Context = {};

function getStore(): Context {
  if (_asyncLocalStorage) {
    return _asyncLocalStorage.getStore() ?? _moduleCtx;
  }
  return _moduleCtx;
}

function ensureStore(): Context {
  if (_asyncLocalStorage) {
    const store = _asyncLocalStorage.getStore();
    if (store) return store;
    const next = { ..._moduleCtx };
    _asyncLocalStorage.enterWith(next);
    return next;
  }
  return _moduleCtx;
}

/**
 * Bind key/value pairs into the current context.
 * These fields are merged into every log record emitted after this call.
 */
export function bindContext(values: Context): void {
  const store = ensureStore();
  Object.assign(store, values);
}

/**
 * Remove specific keys from the current context.
 */
export function unbindContext(...keys: string[]): void {
  const store = ensureStore();
  for (const k of keys) delete store[k];
}

/**
 * Clear all context bindings.
 */
export function clearContext(): void {
  if (_asyncLocalStorage) {
    const store = _asyncLocalStorage.getStore();
    if (store) {
      for (const k of Object.keys(store)) delete store[k];
      return;
    }
  }
  _moduleCtx = {};
}

/**
 * Return a snapshot of the current context (no side effects).
 */
export function getContext(): Context {
  return { ...getStore() };
}

/**
 * Run fn with additional context values scoped to its execution.
 * In Node.js, uses AsyncLocalStorage so the bindings are isolated per-request.
 * In browser, temporarily binds then restores the previous state.
 * Mirrors Python: contextvars copy_context().run(fn) pattern.
 */
export function runWithContext<T>(values: Context, fn: () => T): T {
  if (_asyncLocalStorage) {
    const inherited = { ...getStore(), ...values };
    return _asyncLocalStorage.run(inherited, fn);
  }
  const prev = { ...getStore() };
  bindContext(values);
  try {
    return fn();
  } finally {
    _moduleCtx = prev;
  }
}

/**
 * Bind a session ID that propagates across all telemetry events.
 */
export function bindSessionContext(sessionId: string): void {
  bindContext({ session_id: sessionId });
}

/**
 * Return the current session ID, or null if not set.
 */
export function getSessionId(): string | null {
  const sessionId = getStore()['session_id'];
  return typeof sessionId === 'string' ? sessionId : null;
}

/**
 * Clear the session ID.
 */
export function clearSessionContext(): void {
  unbindContext('session_id');
}

/** Reset to empty context (used in tests). */
export function _resetContext(): void {
  // Recreate ALS so no enterWith-seeded store leaks between tests.
  // The null branch is only reachable in environments without node:async_hooks (e.g. browsers).
  /* v8 ignore next */
  _asyncLocalStorage = _AlsConstructor ? new _AlsConstructor() : null;
  _moduleCtx = {};
}

/** Disable AsyncLocalStorage for testing the module-level fallback path. */
export function _disableAsyncLocalStorageForTest(): ALS | null {
  const prev = _asyncLocalStorage;
  _asyncLocalStorage = null;
  return prev;
}

/** Re-enable AsyncLocalStorage after testing (pass value from _disable call). */
// Stryker disable next-line BlockStatement: assignment-only body — removing leaves _asyncLocalStorage unchanged which is equivalent when tests always call _resetContext after restore
export function _restoreAsyncLocalStorageForTest(saved: ALS | null): void {
  _asyncLocalStorage = saved;
}
