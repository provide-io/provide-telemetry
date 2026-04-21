// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, describe, expect, it } from 'vitest';
import {
  bindSessionContext,
  clearContext,
  clearSessionContext,
  getContext,
  getSessionId,
  runWithContext,
} from '../src/context';

describe('Session Correlation', () => {
  afterEach(() => {
    clearSessionContext();
    clearContext();
  });

  it('bindSessionContext sets session ID', () => {
    bindSessionContext('sess-abc');
    expect(getSessionId()).toBe('sess-abc');
  });

  it('session ID appears in context', () => {
    bindSessionContext('sess-xyz');
    const ctx = getContext();
    expect(ctx['session_id']).toBe('sess-xyz');
  });

  it('clearSessionContext removes session ID', () => {
    bindSessionContext('sess-123');
    clearSessionContext();
    expect(getSessionId()).toBeNull();
    expect(getContext()['session_id']).toBeUndefined();
  });

  it('default session ID is null', () => {
    expect(getSessionId()).toBeNull();
  });

  it('isolates session ID between concurrent async contexts', async () => {
    const first = runWithContext({}, async () => {
      bindSessionContext('sess-first');
      await Promise.resolve();
      return getSessionId();
    });
    const second = runWithContext({}, async () => {
      bindSessionContext('sess-second');
      await Promise.resolve();
      return getSessionId();
    });

    await expect(first).resolves.toBe('sess-first');
    await expect(second).resolves.toBe('sess-second');
  });
});
