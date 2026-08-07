// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
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

import { type AsyncLocalStorageLike, createScopedStorage } from './async-storage.js';

type Context = Record<string, unknown>;

// ── AsyncLocalStorage type (Node.js / Cloudflare Workers) ─────────────────────
type ALS = AsyncLocalStorageLike<Context>;

// ── AsyncLocalStorage (Node.js / Cloudflare Workers) ──────────────────────────
// Acquired lazily through the shared loader rather than with a bare
// `require('node:async_hooks')` at module scope: the published package is ESM,
// where `require` is undefined, so the old eager path pinned this to null and
// every consumer silently shared one module-level context across concurrent
// requests. See src/async-storage.ts.
const _storage = createScopedStorage<Context>();

// ── Fallback: module-level context (browser / single-thread) ──────────────────
let _moduleCtx: Context = {};

function getStore(): Context {
  const als = _storage.get();
  if (als) {
    return als.getStore() ?? _moduleCtx;
  }
  return _moduleCtx;
}

function ensureStore(): Context {
  const als = _storage.get();
  if (als) {
    const store = als.getStore();
    if (store) return store;
    const next = { ..._moduleCtx };
    als.enterWith(next);
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
  const als = _storage.get();
  if (als) {
    const store = als.getStore();
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
  const als = _storage.get();
  if (als) {
    const inherited = { ...getStore(), ...values };
    return als.run(inherited, fn);
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
  // Drop the ALS instance so no enterWith-seeded store leaks between tests;
  // the next access builds a fresh one.
  _storage.reset();
  _moduleCtx = {};
}

/** Disable AsyncLocalStorage for testing the module-level fallback path. */
export function _disableAsyncLocalStorageForTest(): ALS | null {
  return _storage.suppress();
}

/** Re-enable AsyncLocalStorage after testing (pass value from _disable call). */
export function _restoreAsyncLocalStorageForTest(saved: ALS | null): void {
  _storage.restore(saved);
}
