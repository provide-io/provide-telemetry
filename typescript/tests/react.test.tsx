// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import React, { type ErrorInfo } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, render, renderHook } from '@testing-library/react';
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

// ── TelemetryErrorBoundary ───────────────────────────────────────────────────

import * as loggerModule from '../src/logger';
import type { Logger } from '../src/logger';
import { TelemetryErrorBoundary } from '../src/react';

/** A component that throws when shouldThrow is true. */
function Bomb({ shouldThrow }: { shouldThrow: boolean }): React.ReactElement {
  if (shouldThrow) throw new Error('boom');
  return <span>safe</span>;
}

describe('TelemetryErrorBoundary', () => {
  let mockLogError: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    mockLogError = vi.fn();
    vi.spyOn(loggerModule, 'getLogger').mockReturnValue({
      trace: vi.fn(),
      debug: vi.fn(),
      info: vi.fn(),
      warn: vi.fn(),
      error: mockLogError,
      child: vi.fn(),
    } as unknown as Logger);
    // Suppress React's own error output in test console
    vi.spyOn(console, 'error').mockImplementation(() => {});
  });

  it('renders children when no error', () => {
    const { getByText } = render(
      <TelemetryErrorBoundary fallback={<p>oops</p>}>
        <Bomb shouldThrow={false} />
      </TelemetryErrorBoundary>,
    );
    expect(getByText('safe')).toBeTruthy();
  });

  it('renders static ReactNode fallback when child throws', () => {
    const { getByText } = render(
      <TelemetryErrorBoundary fallback={<p>fallback rendered</p>}>
        <Bomb shouldThrow={true} />
      </TelemetryErrorBoundary>,
    );
    expect(getByText('fallback rendered')).toBeTruthy();
  });

  it('renders render-prop fallback with error and reset', () => {
    const { getByText } = render(
      <TelemetryErrorBoundary
        fallback={(error, reset) => (
          <div>
            <span>{error.message}</span>
            <button onClick={reset}>retry</button>
          </div>
        )}
      >
        <Bomb shouldThrow={true} />
      </TelemetryErrorBoundary>,
    );
    expect(getByText('boom')).toBeTruthy();
    expect(getByText('retry')).toBeTruthy();
  });

  it('logs error via getLogger on catch', () => {
    render(
      <TelemetryErrorBoundary fallback={<p>oops</p>}>
        <Bomb shouldThrow={true} />
      </TelemetryErrorBoundary>,
    );
    expect(loggerModule.getLogger).toHaveBeenCalledWith('react.error_boundary');
    expect(mockLogError).toHaveBeenCalledOnce();
    const [logObj] = mockLogError.mock.calls[0] as [Record<string, unknown>];
    expect(logObj['event']).toBe('react_error_caught');
    expect(logObj['error_message']).toBe('boom');
    expect(typeof logObj['component_stack']).toBe('string');
  });

  it('calls onError prop after logging', () => {
    const onError = vi.fn();
    render(
      <TelemetryErrorBoundary fallback={<p>oops</p>} onError={onError}>
        <Bomb shouldThrow={true} />
      </TelemetryErrorBoundary>,
    );
    expect(onError).toHaveBeenCalledOnce();
    const [err, info] = onError.mock.calls[0] as [Error, ErrorInfo];
    expect(err.message).toBe('boom');
    expect(typeof info.componentStack).toBe('string');
  });

  it('reset clears error state and re-renders children', async () => {
    const throwRef = { current: true };
    function ToggleBomb(): React.ReactElement {
      if (throwRef.current) throw new Error('boom');
      return <span>safe</span>;
    }
    const { getByText } = render(
      <TelemetryErrorBoundary
        fallback={(_, reset) => <button onClick={reset}>retry</button>}
      >
        <ToggleBomb />
      </TelemetryErrorBoundary>,
    );
    expect(getByText('retry')).toBeTruthy(); // fallback shown

    throwRef.current = false;
    await act(async () => {
      getByText('retry').click();
    });

    // After reset with non-throwing child, children render successfully
    expect(getByText('safe')).toBeTruthy();
  });

  it('handles error with no stack and no componentStack', () => {
    /** Throws an error whose .stack is explicitly undefined. */
    function StacklessBomb(): React.ReactElement {
      const err = new Error('no-stack');
      delete err.stack;
      throw err;
    }
    render(
      <TelemetryErrorBoundary fallback={<p>fallback</p>}>
        <StacklessBomb />
      </TelemetryErrorBoundary>,
    );
    expect(mockLogError).toHaveBeenCalledOnce();
    const [logObj] = mockLogError.mock.calls[0] as [Record<string, unknown>];
    expect(logObj['error_stack']).toBe('');
  });

  it('handles null componentStack in ErrorInfo', () => {
    // Directly exercise the componentStack ?? '' branch by calling componentDidCatch
    // with a null componentStack — React guarantees a string in practice, but the
    // TypeScript type allows null and we need the fallback branch covered.
    const boundary = new TelemetryErrorBoundary({
      children: null,
      fallback: <p>fb</p>,
    });
    const err = new Error('direct');
    boundary.componentDidCatch(err, { componentStack: null as unknown as string });
    expect(mockLogError).toHaveBeenCalledOnce();
    const [logObj] = mockLogError.mock.calls[0] as [Record<string, unknown>];
    expect(logObj['component_stack']).toBe('');
  });
});
