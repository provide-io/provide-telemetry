// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, describe, expect, it, vi } from 'vitest';

describe('withTrace AsyncLocalStorage fallback', () => {
  afterEach(() => {
    vi.doUnmock('node:async_hooks');
    vi.resetModules();
  });

  it('uses synthetic IDs when AsyncLocalStorage is unavailable', async () => {
    vi.resetModules();
    vi.doMock('node:async_hooks', () => ({ AsyncLocalStorage: undefined }));

    const tracing = await import('../src/tracing');

    let capturedCtx: { trace_id?: string; span_id?: string } = {};
    const result = tracing.withTrace('fallback.trace', () => {
      capturedCtx = tracing.getTraceContext();
      return 'ok';
    });

    expect(result).toBe('ok');
    expect(capturedCtx.trace_id).toMatch(/^[0-9a-f]{32}$/);
    expect(capturedCtx.span_id).toMatch(/^[0-9a-f]{16}$/);
    expect(tracing.getTraceContext()).toEqual({});
  });
});
