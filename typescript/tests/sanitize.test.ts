// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: AGPL-3.0-or-later

import { describe, expect, it } from 'vitest';
import { DEFAULT_SANITIZE_FIELDS, sanitize } from '../src/sanitize';

describe('sanitize', () => {
  it('redacts default PII fields', () => {
    const obj: Record<string, unknown> = { password: 'secret123', status: 200 };
    sanitize(obj);
    expect(obj['password']).toBe('[REDACTED]');
    expect(obj['status']).toBe(200);
  });

  it('redacts all default fields', () => {
    const obj: Record<string, unknown> = {};
    for (const field of DEFAULT_SANITIZE_FIELDS) {
      obj[field] = 'sensitive';
    }
    sanitize(obj);
    for (const field of DEFAULT_SANITIZE_FIELDS) {
      expect(obj[field]).toBe('[REDACTED]');
    }
  });

  it('redacts extra fields from config', () => {
    const obj: Record<string, unknown> = { my_secret_field: 'value', other: 'ok' };
    sanitize(obj, ['my_secret_field']);
    expect(obj['my_secret_field']).toBe('[REDACTED]');
    expect(obj['other']).toBe('ok');
  });

  it('is case-insensitive on key names', () => {
    const obj: Record<string, unknown> = { PASSWORD: 'abc', Token: 'xyz' };
    sanitize(obj);
    expect(obj['PASSWORD']).toBe('[REDACTED]');
    expect(obj['Token']).toBe('[REDACTED]');
  });

  it('leaves clean objects untouched', () => {
    const obj: Record<string, unknown> = { event: 'request_ok', status: 200, path: '/api' };
    sanitize(obj);
    expect(obj).toEqual({ event: 'request_ok', status: 200, path: '/api' });
  });

  it('handles empty object', () => {
    const obj: Record<string, unknown> = {};
    expect(() => sanitize(obj)).not.toThrow();
  });

  it('redacts token field', () => {
    const obj: Record<string, unknown> = { token: 'jwt.abc.def' };
    sanitize(obj);
    expect(obj['token']).toBe('[REDACTED]');
  });
});
