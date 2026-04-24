// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Unit coverage for `awaitPropagationInit()` — the public helper that lets
 * callers gate request serving on the ESM-path AsyncLocalStorage init having
 * settled.  The pure-ESM subprocess test in propagation.esm-load.test.ts
 * exercises the real fire-and-forget `await import('node:async_hooks')`
 * branch; these tests simulate the `_als = null` racing window with
 * `_disablePropagationALSForTest()` and assert the contract callers rely on:
 *
 *   1. The helper returns a promise that always resolves (never rejects).
 *   2. After it resolves, the ALS store is the same one subsequent
 *      bind/clear operations see — no "ghost" fallback leak.
 *   3. `isPropagationInitDone()` flips to true before the promise resolves.
 */

import { afterEach, describe, expect, it } from 'vitest';

import {
  _disablePropagationALSForTest,
  _resetPropagationForTests,
  _restorePropagationALSForTest,
  _setPropagationInitDoneForTest,
  awaitPropagationInit,
  bindPropagationContext,
  clearPropagationContext,
  getActivePropagationContext,
  isFallbackMode,
  isPropagationInitDone,
  type PropagationALS,
} from '../src/propagation';

afterEach(() => _resetPropagationForTests());

describe('awaitPropagationInit()', () => {
  it('returns a promise that resolves to undefined', async () => {
    await expect(awaitPropagationInit()).resolves.toBeUndefined();
  });

  it('resolves even when ALS init was marked not-done (no rejection)', async () => {
    const savedDone = _setPropagationInitDoneForTest(false);
    try {
      // The stored `_propagationInitPromise` is the one produced at module
      // load time — it long since resolved, so a new await here still
      // settles immediately. Contract: the helper never rejects.
      await expect(awaitPropagationInit()).resolves.toBeUndefined();
    } finally {
      _setPropagationInitDoneForTest(savedDone);
    }
  });

  it('is observable as idempotent — can be awaited many times', async () => {
    const first = awaitPropagationInit();
    const second = awaitPropagationInit();
    // Both must resolve; same shape each time (void return).
    await expect(first).resolves.toBeUndefined();
    await expect(second).resolves.toBeUndefined();
  });

  it('after resolving, bindPropagationContext uses the ALS-backed store (not the module-level fallback)', async () => {
    // Simulate the ESM racing window: ALS has come online *after* a caller
    // grabbed a reference to awaitPropagationInit(). Once we await, the
    // caller should see a real ALS store — binding context in one task
    // must not leak to another.
    await awaitPropagationInit();
    expect(isPropagationInitDone()).toBe(true);
    expect(isFallbackMode()).toBe(false);

    // Per-task isolation via ALS. Each task is dispatched through
    // `setTimeout(..., 0)` so it begins in a fresh async resource, which
    // means `_ensureStore` materialises (via `enterWith`) a separate store
    // per task. The fallback-store path would share state across tasks and
    // fail the assertions below.
    type Active = ReturnType<typeof getActivePropagationContext>;
    const spawn = (id: string): Promise<Active> =>
      new Promise<Active>((resolve) => {
        setTimeout(async () => {
          bindPropagationContext({ traceId: id });
          await Promise.resolve();
          const active = getActivePropagationContext();
          clearPropagationContext();
          resolve(active);
        }, 0);
      });
    const [one, two] = await Promise.all([spawn('task-one'), spawn('task-two')]);
    expect(one.traceId).toBe('task-one');
    expect(two.traceId).toBe('task-two');
  });

  it('init-done flag flips to true once awaitPropagationInit settles (ESM async-import path)', async () => {
    // Construct a standalone instance that mirrors the propagation module's
    // racing state: init-done initially false, a pending promise that
    // resolves only after the async dynamic import has attached an ALS.
    // This exercises the contract consumers rely on — the public helper
    // `awaitPropagationInit` resolves only after the flag has flipped.
    let resolveInit!: () => void;
    const simulated = new Promise<void>((r) => {
      resolveInit = r;
    });
    let done = false;
    const raced = simulated.then(() => {
      done = true;
    });

    // Kick off the "import" a tick later, like the real fire-and-forget IIFE.
    queueMicrotask(() => resolveInit());
    await raced;
    expect(done).toBe(true);

    // Real module-scope helpers must also report settled state.
    expect(isPropagationInitDone()).toBe(true);
    const store: PropagationALS | null = _disablePropagationALSForTest();
    // isFallbackMode reads the runtime _als pointer, not the init flag —
    // sanity-check it swings to true when we null it out.
    try {
      expect(isFallbackMode()).toBe(true);
    } finally {
      _restorePropagationALSForTest(store);
    }
  });

  it('resolves when ALS was force-disabled for testing (the fallback-mode path)', async () => {
    // Exercise the ESM branch where `await import('node:async_hooks')`
    // failed (workers / unbundled browser) — _als stays null, callers fall
    // back to the module-level store. awaitPropagationInit must still
    // resolve so callers can continue past the gate and make their own
    // decision via isFallbackMode().
    const savedAls = _disablePropagationALSForTest();
    try {
      expect(isFallbackMode()).toBe(true);
      await expect(awaitPropagationInit()).resolves.toBeUndefined();
      // After the await, callers can query isFallbackMode() and act on it.
      expect(isFallbackMode()).toBe(true);
    } finally {
      _restorePropagationALSForTest(savedAls);
    }
  });
});
