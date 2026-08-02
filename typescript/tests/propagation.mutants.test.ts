// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Targeted Stryker mutation-kill tests for propagation.ts.
 *
 * Most of these are the module-init IIFE's CJS branch: in this Vitest/tsx
 * process `typeof require === 'function'` is genuinely true, so the sync path
 * runs and sets `_propagationInitDone = true` synchronously, before the
 * dynamic `import('../src/propagation.js')` in a fresh-module test even
 * resolves. Forcing the async path instead (mutating the guard, or leaving
 * the flag false) is observable *immediately* after a fresh import with no
 * `await` of anything else — the async branch's own `await
 * import('node:async_hooks')` has not had a chance to resolve yet.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  _resetPropagationForTests,
  bindPropagationContext,
  clearPropagationContext,
} from '../src/propagation.js';
import { _resetTraceContext, getTraceContext, setTraceContext } from '../src/tracing.js';

afterEach(() => {
  _resetPropagationForTests();
  _resetTraceContext();
});

describe('propagation.ts — module init takes the synchronous CJS require path', () => {
  it('isPropagationInitDone() is already true immediately after a fresh import', async () => {
    // No await of anything but the import itself: real code's sync-require
    // branch has already run to completion by the time this resolves. Any
    // mutation that forces the async import('node:async_hooks') branch
    // instead would still be pending here.
    vi.resetModules();
    const p = await import('../src/propagation.js');
    expect(p.isPropagationInitDone()).toBe(true);
  });

  it('is not in fallback mode immediately after a fresh import', async () => {
    vi.resetModules();
    const p = await import('../src/propagation.js');
    expect(p.isFallbackMode()).toBe(false);
  });
});

describe('propagation.ts — fallback-mode warning fires exactly once', () => {
  it('warns on first fallback access, from a fresh module', async () => {
    vi.resetModules();
    const p = await import('../src/propagation.js');
    const spy = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    try {
      const saved = p._disablePropagationALSForTest();
      try {
        p.getActivePropagationContext(); // first fallback access — must warn
        p.getActivePropagationContext(); // second access — must NOT warn again
      } finally {
        p._restorePropagationALSForTest(saved);
      }
      expect(spy).toHaveBeenCalledTimes(1);
    } finally {
      spy.mockRestore();
    }
  });
});

describe('bindPropagationContext — trace context is only touched when the ctx carries an id', () => {
  it('leaves an existing trace context untouched when binding a ctx with neither id', () => {
    setTraceContext('parent-trace', 'parent-span');

    bindPropagationContext({});

    expect(getTraceContext()).toEqual({ trace_id: 'parent-trace', span_id: 'parent-span' });
    clearPropagationContext();
  });

  it('sets the trace context when the ctx carries a traceId', () => {
    bindPropagationContext({ traceId: 'new-trace' });

    expect(getTraceContext().trace_id).toBe('new-trace');
    clearPropagationContext();
  });
});

describe('propagation.ts — fallback store literal is a real PropagationStore, not {}', () => {
  it('binds and reads context via the fallback store on a fresh, never-reset module', async () => {
    vi.resetModules();
    const p = await import('../src/propagation.js');
    const saved = p._disablePropagationALSForTest();
    try {
      p.bindPropagationContext({ traceId: 'fresh-fallback' });
      expect(p.getActivePropagationContext().traceId).toBe('fresh-fallback');
      p.clearPropagationContext();
      expect(p.getActivePropagationContext().traceId).toBeUndefined();
    } finally {
      p._restorePropagationALSForTest(saved);
    }
  });
});
