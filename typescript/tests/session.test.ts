// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, describe, expect, it } from 'vitest';
import {
  bindSessionContext,
  clearContext,
  clearSessionContext,
  getContext,
  getSessionId,
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
});
