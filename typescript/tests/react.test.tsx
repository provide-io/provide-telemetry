// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderHook } from '@testing-library/react';
import { _resetContext, getContext } from '../src/context';
import { useTelemetryContext } from '../src/react';

afterEach(() => {
  _resetContext();
  vi.restoreAllMocks();
});

// ── useTelemetryContext ──────────────────────────────────────────────────────

describe('useTelemetryContext', () => {
  it('binds values into telemetry context on mount', () => {
    renderHook(() => useTelemetryContext({ user_id: 'u1', tenant: 'acme' }));
    expect(getContext()).toMatchObject({ user_id: 'u1', tenant: 'acme' });
  });

  it('unbinds keys on unmount', () => {
    const { unmount } = renderHook(() =>
      useTelemetryContext({ user_id: 'u1', tenant: 'acme' }),
    );
    unmount();
    const ctx = getContext();
    expect(ctx).not.toHaveProperty('user_id');
    expect(ctx).not.toHaveProperty('tenant');
  });

  it('updates context when values change', () => {
    const { rerender } = renderHook(
      ({ vals }: { vals: Record<string, unknown> }) => useTelemetryContext(vals),
      { initialProps: { vals: { user_id: 'u1' } as Record<string, unknown> } },
    );
    rerender({ vals: { user_id: 'u2', role: 'admin' } });
    const ctx = getContext();
    expect(ctx['user_id']).toBe('u2');
    expect(ctx['role']).toBe('admin');
  });

  it('unbinds removed keys when values object changes keys', () => {
    const { rerender } = renderHook(
      ({ vals }: { vals: Record<string, unknown> }) => useTelemetryContext(vals),
      { initialProps: { vals: { user_id: 'u1', old_key: 'gone' } as Record<string, unknown> } },
    );
    rerender({ vals: { user_id: 'u1' } });
    const ctx = getContext();
    expect(ctx['user_id']).toBe('u1');
    expect(ctx).not.toHaveProperty('old_key');
  });

  it('does not re-bind when reference changes but content is equal', async () => {
    // ESM-spy test: spies on a named export via dynamic import. Works in Vitest today,
    // but may need updating if Vitest's module interop or ESM handling changes.
    const contextModule = await import('../src/context');
    const spy = vi.spyOn(contextModule, 'bindContext');

    const { rerender } = renderHook(
      ({ vals }: { vals: Record<string, unknown> }) => useTelemetryContext(vals),
      { initialProps: { vals: { user_id: 'u1' } as Record<string, unknown> } },
    );
    // Initial mount calls bindContext once — reset the count
    spy.mockClear();

    rerender({ vals: { user_id: 'u1' } }); // same content, new object reference
    expect(spy).not.toHaveBeenCalled();
  });
});
