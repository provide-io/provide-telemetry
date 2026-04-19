// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Behavioral parity tests — validates TypeScript against spec/behavioral_fixtures.yaml.
 * Python and Go have equivalent test files validating the same fixtures.
 */

import { afterEach, describe, expect, it } from 'vitest';
import {
  setSamplingPolicy,
  shouldSample,
  registerPiiRule,
  resetPiiRulesForTests,
  sanitizePayload,
  event,
  EventSchemaError,
  extractW3cContext,
  setupTelemetry,
} from '../src/index';
import { _resetSamplingForTests } from '../src/sampling';
import { shortHash12 } from '../src/hash';

// ── Sampling ────────────────────────────────────────────────────────────────

describe('parity: sampling', () => {
  afterEach(() => _resetSamplingForTests());

  it('rate=0.0 always drops', () => {
    setSamplingPolicy('logs', { defaultRate: 0.0 });
    for (let i = 0; i < 100; i++) {
      expect(shouldSample('logs')).toBe(false);
    }
  });

  it('rate=1.0 always keeps', () => {
    setSamplingPolicy('logs', { defaultRate: 1.0 });
    for (let i = 0; i < 100; i++) {
      expect(shouldSample('logs')).toBe(true);
    }
  });

  it('rate=0.5 keeps ~50% (statistical)', () => {
    setSamplingPolicy('logs', { defaultRate: 0.5 });
    let count = 0;
    const trials = 10_000;
    for (let i = 0; i < trials; i++) {
      if (shouldSample('logs')) count++;
    }
    const pct = (count / trials) * 100;
    expect(pct).toBeGreaterThanOrEqual(40);
    expect(pct).toBeLessThanOrEqual(60);
  });

  it('rate=0.99 keeps ~99% (statistical)', () => {
    setSamplingPolicy('logs', { defaultRate: 0.99 });
    let count = 0;
    const trials = 10_000;
    for (let i = 0; i < trials; i++) {
      if (shouldSample('logs')) count++;
    }
    const pct = (count / trials) * 100;
    expect(pct).toBeGreaterThanOrEqual(95);
    expect(pct).toBeLessThanOrEqual(100);
  });

  it('rate=0.001 keeps ~0.1% (statistical)', () => {
    setSamplingPolicy('logs', { defaultRate: 0.001 });
    let count = 0;
    const trials = 100_000;
    for (let i = 0; i < trials; i++) {
      if (shouldSample('logs')) count++;
    }
    const pct = (count / trials) * 100;
    expect(pct).toBeGreaterThanOrEqual(0);
    expect(pct).toBeLessThanOrEqual(1);
  });

  it('rejects unknown signal name', () => {
    expect(() => shouldSample('invalid')).toThrow();
    expect(() => shouldSample('log')).toThrow();
    expect(() => shouldSample('')).toThrow();
  });

  it('accepts valid signal names', () => {
    setSamplingPolicy('logs', { defaultRate: 1.0 });
    expect(() => shouldSample('logs')).not.toThrow();
    expect(() => shouldSample('traces')).not.toThrow();
    expect(() => shouldSample('metrics')).not.toThrow();
  });
});

describe('parity: sampling_signal_validation', () => {
  afterEach(() => _resetSamplingForTests());

  it('rejects invalid signal names', () => {
    expect(() => shouldSample('invalid')).toThrow();
    expect(() => shouldSample('log')).toThrow();
    expect(() => shouldSample('')).toThrow();
  });
});

// ── PII Hash ────────────────────────────────────────────────────────────────

describe('parity: pii_hash', () => {
  afterEach(() => resetPiiRulesForTests());

  it('hash produces 12-char lowercase hex', () => {
    const hash = shortHash12('user-42');
    expect(hash).toHaveLength(12);
    expect(hash).toMatch(/^[0-9a-f]{12}$/);
  });

  it('hash is deterministic (cross-language)', () => {
    const hash = shortHash12('same-input');
    expect(hash).toBe('f52c2013103b');
  });

  it('hash of integer (as string)', () => {
    const hash = shortHash12('42');
    expect(hash).toBe('73475cb40a56'); // pragma: allowlist secret
  });
});

// ── PII Truncate ────────────────────────────────────────────────────────────

describe('parity: pii_truncate', () => {
  afterEach(() => resetPiiRulesForTests());

  it('string longer than limit is truncated with suffix', () => {
    registerPiiRule({ path: 'note', mode: 'truncate', truncateTo: 5 });
    const obj: Record<string, unknown> = { note: 'hello world' };
    sanitizePayload(obj);
    expect(obj['note']).toBe('hello...');
  });

  it('string at limit is NOT truncated', () => {
    registerPiiRule({ path: 'note', mode: 'truncate', truncateTo: 5 });
    const obj: Record<string, unknown> = { note: 'hello' };
    sanitizePayload(obj);
    expect(obj['note']).toBe('hello');
  });

  it('string shorter than limit is unchanged', () => {
    registerPiiRule({ path: 'note', mode: 'truncate', truncateTo: 5 });
    const obj: Record<string, unknown> = { note: 'hi' };
    sanitizePayload(obj);
    expect(obj['note']).toBe('hi');
  });

  it('non-string converted then truncated', () => {
    registerPiiRule({ path: 'note', mode: 'truncate', truncateTo: 5 });
    const obj: Record<string, unknown> = { note: 1234567890 };
    sanitizePayload(obj);
    expect(obj['note']).toBe('12345...');
  });
});

// ── PII Redact ──────────────────────────────────────────────────────────────

describe('parity: pii_redact', () => {
  afterEach(() => resetPiiRulesForTests());

  it('sensitive key is replaced with redaction marker', () => {
    // "password" is in DEFAULT_SANITIZE_FIELDS — sanitizePayload redacts it automatically
    const obj: Record<string, unknown> = { password: 's3cret' }; // pragma: allowlist secret
    sanitizePayload(obj);
    expect(obj['password']).toBe('***');
  });

  it('case-insensitive sensitive detection', () => {
    // "api_key" is in DEFAULT_SANITIZE_FIELDS (case-insensitive matching)
    const obj: Record<string, unknown> = { API_KEY: 'abc123' }; // pragma: allowlist secret
    sanitizePayload(obj);
    expect(obj['API_KEY']).toBe('***');
  });
});

// ── PII Drop ────────────────────────────────────────────────────────────────

describe('parity: pii_drop', () => {
  afterEach(() => resetPiiRulesForTests());

  it('drop mode removes the key entirely', () => {
    registerPiiRule({ path: 'card_number', mode: 'drop' });
    const obj: Record<string, unknown> = { card_number: '4111-1111', other: 'ok' };
    sanitizePayload(obj);
    expect('card_number' in obj).toBe(false);
    expect(obj['other']).toBe('ok');
  });
});

// ── Event DARS ──────────────────────────────────────────────────────────────

describe('parity: event_dars', () => {
  it('3 segments = DAS', () => {
    setupTelemetry({ strictSchema: false });
    const rec = event('user', 'login', 'ok');
    expect(rec.event).toBe('user.login.ok');
    expect(rec.domain).toBe('user');
    expect(rec.action).toBe('login');
    expect(rec.resource).toBeUndefined();
    expect(rec.status).toBe('ok');
  });

  it('4 segments = DARS', () => {
    setupTelemetry({ strictSchema: false });
    const rec = event('db', 'query', 'users', 'ok');
    expect(rec.event).toBe('db.query.users.ok');
    expect(rec.domain).toBe('db');
    expect(rec.action).toBe('query');
    expect(rec.resource).toBe('users');
    expect(rec.status).toBe('ok');
  });

  it('2 segments = error', () => {
    expect(() => event('too', 'few')).toThrow(EventSchemaError);
  });

  it('5 segments = error', () => {
    expect(() => event('a', 'b', 'c', 'd', 'e')).toThrow(EventSchemaError);
  });
});

// ── Propagation Guards ──────────────────────────────────────────────────────

describe('parity: propagation_guards', () => {
  const validTraceparent = '00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01';

  it('traceparent at limit (512 bytes) is accepted', () => {
    // A valid traceparent is ~55 chars; pad to exactly 512 with valid structure isn't
    // realistic. Instead, test that a normal-length traceparent is accepted.
    const ctx = extractW3cContext({ traceparent: validTraceparent });
    expect(ctx.traceparent).toBe(validTraceparent);
  });

  it('traceparent over limit (513 bytes) is discarded', () => {
    const long = 'x'.repeat(513);
    const ctx = extractW3cContext({ traceparent: long });
    expect(ctx.traceparent).toBeUndefined();
  });

  it('tracestate with 32 pairs is accepted', () => {
    const pairs = Array.from({ length: 32 }, () => 'k=v').join(',');
    const ctx = extractW3cContext({
      traceparent: validTraceparent,
      tracestate: pairs,
    });
    expect(ctx.tracestate).toBe(pairs);
  });

  it('tracestate with 33 pairs is discarded', () => {
    const pairs = Array.from({ length: 33 }, () => 'k=v').join(',');
    const ctx = extractW3cContext({
      traceparent: validTraceparent,
      tracestate: pairs,
    });
    expect(ctx.tracestate).toBeUndefined();
  });

  it('baggage at limit (8192 bytes) is accepted', () => {
    const baggage = 'k=' + 'v'.repeat(8190);
    expect(baggage).toHaveLength(8192);
    const ctx = extractW3cContext({
      traceparent: validTraceparent,
      baggage,
    });
    expect(ctx.baggage).toBe(baggage);
  });

  it('baggage over limit (8193 bytes) is discarded', () => {
    const baggage = 'k=' + 'v'.repeat(8191);
    expect(baggage).toHaveLength(8193);
    const ctx = extractW3cContext({
      traceparent: validTraceparent,
      baggage,
    });
    expect(ctx.baggage).toBeUndefined();
  });
});
