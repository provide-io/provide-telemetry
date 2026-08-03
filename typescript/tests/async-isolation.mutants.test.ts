// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * AsyncLocalStorage has to actually be installed, in tracing and in context.
 *
 * Both modules build their ALS in a top-level `try` block. Emptying that block
 * leaves the module-level fallback in charge, which still passes every
 * single-task test: one task setting a value and reading it back sees the same
 * answer either way. The difference only shows with two tasks interleaved
 * across an await, where a shared module-level variable leaks one task's
 * context into the other — the exact failure ALS exists to prevent, and the one
 * that misattributes a trace id to the wrong request under load.
 */

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { _resetConfig, setupTelemetry } from '../src/config.js';
import { bindContext, clearContext, getContext, runWithContext } from '../src/context.js';
import { _resetTraceContext, getTraceContext, withTrace } from '../src/tracing.js';

beforeEach(() => {
  clearContext();
});

afterEach(() => {
  clearContext();
});

const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

describe('context isolation across interleaved tasks', () => {
  it('does not leak one task’s bound context into another', async () => {
    const seen: Record<string, unknown> = {};

    const task = (name: string, delay: number) =>
      runWithContext({ who: name }, async () => {
        await new Promise((resolve) => setTimeout(resolve, delay));
        seen[name] = getContext().who;
      });

    // Interleaved on purpose: `b` binds while `a` is suspended mid-await.
    await Promise.all([task('a', 20), task('b', 0)]);

    expect(seen.a).toBe('a');
    expect(seen.b).toBe('b');
  });

  it('keeps a nested run from overwriting the caller’s context', async () => {
    bindContext({ outer: 1 });

    await runWithContext({ inner: 2 }, async () => {
      await tick();
      expect(getContext().inner).toBe(2);
    });

    expect(getContext().outer).toBe(1);
    expect(getContext().inner).toBeUndefined();
  });
});

describe('trace context isolation across interleaved tasks', () => {
  beforeEach(() => {
    _resetConfig();
    _resetTraceContext();
    setupTelemetry({ serviceName: 'async-isolation' });
  });

  afterEach(() => {
    _resetTraceContext();
    _resetConfig();
  });

  it('gives each concurrent span its own trace id across an await', async () => {
    // withTrace opens an AsyncLocalStorage scope per call. Without one, the
    // synthetic ids live in module globals that the second task overwrites
    // while the first is suspended, and both report the same trace id.
    const seen: Record<string, string | undefined> = {};

    const task = (name: string, delay: number) =>
      withTrace(`span-${name}`, async () => {
        seen[`${name}-entry`] = getTraceContext().trace_id;
        await new Promise((resolve) => setTimeout(resolve, delay));
        seen[name] = getTraceContext().trace_id;
      });

    await Promise.all([task('a', 20), task('b', 0)]);

    // Each task still sees the id it entered with, and the two differ.
    expect(seen.a).toBe(seen['a-entry']);
    expect(seen.b).toBe(seen['b-entry']);
    expect(seen.a).not.toBe(seen.b);
    expect(seen.a).toBeDefined();
  });
});
