// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, describe, expect, it } from 'vitest';
import {
  _disableAsyncLocalStorageForTest,
  _resetContext,
  _restoreAsyncLocalStorageForTest,
  bindContext,
  clearContext,
  getContext,
  runWithContext,
  unbindContext,
} from '../src/context';

afterEach(() => {
  _resetContext();
});

describe('bindContext', () => {
  it('adds fields to context', () => {
    bindContext({ request_id: 'abc123', user_id: 42 });
    expect(getContext()).toMatchObject({ request_id: 'abc123', user_id: 42 });
  });

  it('merges multiple bind calls', () => {
    bindContext({ a: 1 });
    bindContext({ b: 2 });
    expect(getContext()).toMatchObject({ a: 1, b: 2 });
  });

  it('overwrites existing keys', () => {
    bindContext({ env: 'dev' });
    bindContext({ env: 'prod' });
    expect(getContext()['env']).toBe('prod');
  });
});

describe('unbindContext', () => {
  it('removes specific keys', () => {
    bindContext({ a: 1, b: 2, c: 3 });
    unbindContext('a', 'c');
    const ctx = getContext();
    expect(ctx).not.toHaveProperty('a');
    expect(ctx).not.toHaveProperty('c');
    expect(ctx['b']).toBe(2);
  });

  it('silently ignores missing keys', () => {
    bindContext({ a: 1 });
    expect(() => unbindContext('nonexistent')).not.toThrow();
    expect(getContext()['a']).toBe(1);
  });
});

describe('clearContext', () => {
  it('removes all bindings', () => {
    bindContext({ a: 1, b: 2 });
    clearContext();
    expect(getContext()).toEqual({});
  });

  it('is idempotent on empty context', () => {
    expect(() => clearContext()).not.toThrow();
    expect(getContext()).toEqual({});
  });

  it('clears context inside AsyncLocalStorage store', () => {
    // clearContext() inside an ALS-scoped runWithContext — covers ALS store clear path
    runWithContext({ x: 1 }, () => {
      expect(getContext()).toMatchObject({ x: 1 });
      clearContext();
      expect(getContext()).toEqual({});
    });
  });

  it('falls through to _moduleCtx when ALS is null', () => {
    // clearContext() with ALS disabled — covers the !_asyncLocalStorage branch
    const saved = _disableAsyncLocalStorageForTest();
    try {
      bindContext({ x: 1 });
      clearContext();
      expect(getContext()).toEqual({});
    } finally {
      _restoreAsyncLocalStorageForTest(saved);
      _resetContext();
    }
  });
});

describe('getContext', () => {
  it('returns empty object when no bindings', () => {
    expect(getContext()).toEqual({});
  });

  it('returns a snapshot (not a reference)', () => {
    bindContext({ a: 1 });
    const ctx = getContext();
    ctx['b'] = 99;
    expect(getContext()).not.toHaveProperty('b');
  });
});

describe('runWithContext — with AsyncLocalStorage (Node.js)', () => {
  it('scopes bindings to fn execution', () => {
    bindContext({ outer: true });
    runWithContext({ request_id: 'req-1' }, () => {
      const ctx = getContext();
      expect(ctx['request_id']).toBe('req-1');
      expect(ctx['outer']).toBe(true);
    });
    // Outside the scope, request_id should not be present
    expect(getContext()).not.toHaveProperty('request_id');
  });

  it('returns the value from fn', () => {
    const result = runWithContext({ x: 1 }, () => 42);
    expect(result).toBe(42);
  });

  it('async fn inherits context', async () => {
    const result = await runWithContext({ session: 'abc' }, async () => {
      await Promise.resolve();
      return getContext()['session'];
    });
    expect(result).toBe('abc');
  });
});

describe('runWithContext — without AsyncLocalStorage (browser fallback)', () => {
  it('scopes bindings and restores previous state', () => {
    const saved = _disableAsyncLocalStorageForTest();
    try {
      bindContext({ outer: 'yes' });
      runWithContext({ inner: 'only' }, () => {
        expect(getContext()['inner']).toBe('only');
        expect(getContext()['outer']).toBe('yes');
      });
      // After fn returns, outer is restored; inner is gone
      expect(getContext()).toMatchObject({ outer: 'yes' });
      expect(getContext()).not.toHaveProperty('inner');
    } finally {
      _restoreAsyncLocalStorageForTest(saved);
      _resetContext();
    }
  });

  it('restores context even when fn throws', () => {
    const saved = _disableAsyncLocalStorageForTest();
    try {
      bindContext({ before: 1 });
      expect(() =>
        runWithContext({ temp: 99 }, () => {
          throw new Error('oops');
        }),
      ).toThrow('oops');
      expect(getContext()).toMatchObject({ before: 1 });
      expect(getContext()).not.toHaveProperty('temp');
    } finally {
      _restoreAsyncLocalStorageForTest(saved);
      _resetContext();
    }
  });

  it('getStore() falls back to module-level context when ALS is null', () => {
    const saved = _disableAsyncLocalStorageForTest();
    try {
      bindContext({ fallback: true });
      expect(getContext()['fallback']).toBe(true);
    } finally {
      _restoreAsyncLocalStorageForTest(saved);
      _resetContext();
    }
  });
});

describe('_disableAsyncLocalStorageForTest / _restoreAsyncLocalStorageForTest', () => {
  it('returns the previous ALS instance and null-ifies it', () => {
    const saved = _disableAsyncLocalStorageForTest();
    expect(saved).not.toBeNull(); // ALS exists in Node.js/vitest
    _restoreAsyncLocalStorageForTest(saved);
  });

  it('restore with null leaves ALS as null', () => {
    const saved = _disableAsyncLocalStorageForTest();
    _restoreAsyncLocalStorageForTest(null);
    // Now ALS is null — verify module-level path works
    bindContext({ test: 1 });
    expect(getContext()['test']).toBe(1);
    // Restore properly
    _restoreAsyncLocalStorageForTest(saved);
    _resetContext();
  });
});

describe('round-trip: bind + unbind + clear', () => {
  it('full lifecycle works without errors', () => {
    bindContext({ session: 'abc', env: 'test', uid: 1 });
    expect(getContext()).toMatchObject({ session: 'abc', env: 'test', uid: 1 });
    unbindContext('env');
    expect(getContext()).not.toHaveProperty('env');
    expect(getContext()['session']).toBe('abc');
    clearContext();
    expect(getContext()).toEqual({});
  });

  it('consecutive binds and clears are idempotent', () => {
    for (let i = 0; i < 3; i++) {
      bindContext({ iter: i });
      clearContext();
    }
    expect(getContext()).toEqual({});
  });
});
