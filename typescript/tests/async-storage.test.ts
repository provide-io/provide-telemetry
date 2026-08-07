// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
//
// Unit coverage for the shared AsyncLocalStorage holder. The acquisition IIFE
// itself is exercised end-to-end (see async-storage.ts for why no single
// loader can enter all four of its branches); what is pinned here is the
// observable holder contract the three call sites depend on.

import { describe, expect, it } from 'vitest';
import {
  _setAsyncStorageConstructorForTest,
  _setAsyncStorageInitDoneForTest,
  awaitAsyncStorageInit,
  createAsyncLocalStorage,
  createScopedStorage,
  isAsyncStorageInitDone,
} from '../src/async-storage.js';

/** Run fn with node:async_hooks pretended away, as in a browser or Deno. */
function withoutAsyncHooks<T>(fn: () => T): T {
  const saved = _setAsyncStorageConstructorForTest(null);
  try {
    return fn();
  } finally {
    _setAsyncStorageConstructorForTest(saved);
  }
}

describe('acquisition state', () => {
  it('is already settled after a synchronous (CJS) load', () => {
    expect(isAsyncStorageInitDone()).toBe(true);
  });

  it('awaitAsyncStorageInit resolves to undefined', async () => {
    await expect(awaitAsyncStorageInit()).resolves.toBeUndefined();
  });

  it('returns the same promise on repeated calls', () => {
    expect(awaitAsyncStorageInit()).toBe(awaitAsyncStorageInit());
  });

  it('_setAsyncStorageInitDoneForTest returns the previous value and applies the new one', () => {
    const saved = _setAsyncStorageInitDoneForTest(false);
    try {
      expect(saved).toBe(true);
      expect(isAsyncStorageInitDone()).toBe(false);
    } finally {
      expect(_setAsyncStorageInitDoneForTest(saved)).toBe(false);
    }
    expect(isAsyncStorageInitDone()).toBe(true);
  });
});

describe('createAsyncLocalStorage', () => {
  it('hands back a distinct live store per call', () => {
    const a = createAsyncLocalStorage<{ id: string }>();
    const b = createAsyncLocalStorage<{ id: string }>();
    expect(a).not.toBeNull();
    expect(b).not.toBeNull();
    expect(a).not.toBe(b);
    // Distinct instances must not observe each other's stores.
    a?.run({ id: 'a' }, () => {
      expect(a.getStore()).toEqual({ id: 'a' });
      expect(b?.getStore()).toBeUndefined();
    });
  });

  it('returns null where node:async_hooks never resolved', () => {
    expect(withoutAsyncHooks(() => createAsyncLocalStorage<{ id: string }>())).toBeNull();
  });

  it('_setAsyncStorageConstructorForTest returns the constructor it replaced', () => {
    const saved = _setAsyncStorageConstructorForTest(null);
    try {
      expect(saved).not.toBeNull();
      // Reinstating it must restore working acquisition, not just the pointer.
      expect(_setAsyncStorageConstructorForTest(saved)).toBeNull();
      expect(createAsyncLocalStorage<{ id: string }>()).not.toBeNull();
    } finally {
      _setAsyncStorageConstructorForTest(saved);
    }
  });
});

describe('createScopedStorage', () => {
  it('memoizes the instance across calls', () => {
    const storage = createScopedStorage<{ id: string }>();
    expect(storage.get()).toBe(storage.get());
  });

  it('gives each holder its own instance', () => {
    expect(createScopedStorage<{ id: string }>().get()).not.toBe(
      createScopedStorage<{ id: string }>().get(),
    );
  });

  it('reset() drops the instance so the next get() builds a fresh one', () => {
    const storage = createScopedStorage<{ id: string }>();
    const first = storage.get();
    storage.reset();
    const second = storage.get();
    expect(second).not.toBeNull();
    expect(second).not.toBe(first);
  });

  it('reset() discards an enterWith-seeded store', () => {
    const storage = createScopedStorage<{ id: string }>();
    storage.get()?.enterWith({ id: 'leaked' });
    expect(storage.get()?.getStore()).toEqual({ id: 'leaked' });
    storage.reset();
    expect(storage.get()?.getStore()).toBeUndefined();
  });

  it('suppress() returns the replaced instance and forces get() to null', () => {
    const storage = createScopedStorage<{ id: string }>();
    const live = storage.get();
    expect(storage.suppress()).toBe(live);
    expect(storage.get()).toBeNull();
  });

  it('stays suppressed across repeated get() calls rather than re-acquiring', () => {
    // Without the suppression flag the lazy retry would immediately undo the
    // seam every fallback-path test depends on.
    const storage = createScopedStorage<{ id: string }>();
    storage.suppress();
    expect(storage.get()).toBeNull();
    expect(storage.get()).toBeNull();
  });

  it('restore() reinstates the saved instance', () => {
    const storage = createScopedStorage<{ id: string }>();
    const saved = storage.suppress();
    storage.restore(saved);
    expect(storage.get()).toBe(saved);
  });

  it('restore(null) lifts suppression and lets the next get() re-acquire', () => {
    const storage = createScopedStorage<{ id: string }>();
    storage.suppress();
    storage.restore(null);
    expect(storage.get()).not.toBeNull();
  });

  it('yields null in a runtime without node:async_hooks, and retries once it appears', () => {
    // The retry is the fix: on the ESM path the constructor lands after the
    // importing modules finish evaluating, so a holder that gave up on its
    // first miss would stay on the fallback store forever.
    const storage = createScopedStorage<{ id: string }>();
    expect(withoutAsyncHooks(() => storage.get())).toBeNull();
    expect(storage.get()).not.toBeNull();
  });

  it('reset() also lifts suppression, matching the pre-refactor reset behavior', () => {
    // _resetContext / _resetPropagationForTests used to reassign the ALS
    // unconditionally, so a test that suppressed and then reset got a live
    // store back. Preserved here so a missing restore() cannot silently leave
    // every later test on the fallback path.
    const storage = createScopedStorage<{ id: string }>();
    storage.suppress();
    storage.reset();
    expect(storage.get()).not.toBeNull();
  });
});
