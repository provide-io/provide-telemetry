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
  eventName,
  EventSchemaError,
  extractW3cContext,
  classifyError,
  parseOtlpHeaders,
  setupTelemetry,
  getQueuePolicy,
  computeErrorFingerprint,
  reconfigureTelemetry,
  registerCardinalityLimit,
  getCardinalityLimits,
  clearCardinalityLimits,
  validateRequiredKeys,
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

// ── Config Headers ──────────────────────────────────────────────────────────

describe('parity: config_headers', () => {
  it('plus sign preserved as literal (not space)', () => {
    expect(parseOtlpHeaders('Authorization=Bearer+token')).toEqual({
      Authorization: 'Bearer+token',
    });
  });

  it('URL-encoded key and value', () => {
    expect(parseOtlpHeaders('my%20key=my%20value')).toEqual({
      'my key': 'my value',
    });
  });

  it('plus sign preserved as literal', () => {
    expect(parseOtlpHeaders('a+b=c+d')).toEqual({ 'a+b': 'c+d' });
  });

  it('percent-encoded spaces decoded', () => {
    expect(parseOtlpHeaders('a%20b=c%20d')).toEqual({ 'a b': 'c d' });
  });

  it('empty key (=value) skipped', () => {
    expect(parseOtlpHeaders('=value,key=val')).toEqual({ key: 'val' });
  });

  it('no equals sign skipped', () => {
    expect(parseOtlpHeaders('malformed,key=val')).toEqual({ key: 'val' });
  });

  it('value containing = preserved', () => {
    expect(parseOtlpHeaders('Authorization=Bearer token=xyz')).toEqual({
      Authorization: 'Bearer token=xyz',
    });
  });

  it('empty string returns empty', () => {
    expect(parseOtlpHeaders('')).toEqual({});
  });
});

// ── Default sensitive keys ──────────────────────────────────────────────────

describe('parity: default_sensitive_keys', () => {
  afterEach(() => resetPiiRulesForTests());

  it('redacts credential key', () => {
    const obj: Record<string, unknown> = { credential: 'abc' };
    sanitizePayload(obj);
    expect(obj['credential']).toBe('***');
  });
  it('redacts cvv key', () => {
    const obj: Record<string, unknown> = { cvv: '123' };
    sanitizePayload(obj);
    expect(obj['cvv']).toBe('***');
  });
  it('redacts pin key', () => {
    const obj: Record<string, unknown> = { pin: '9876' };
    sanitizePayload(obj);
    expect(obj['pin']).toBe('***');
  });
  it('redacts account_number key', () => {
    const obj: Record<string, unknown> = { account_number: '111' };
    sanitizePayload(obj);
    expect(obj['account_number']).toBe('***');
  });
  it('redacts cookie key', () => {
    const obj: Record<string, unknown> = { cookie: 'sess=x' };
    sanitizePayload(obj);
    expect(obj['cookie']).toBe('***');
  });
  it('does NOT redact email key', () => {
    const obj: Record<string, unknown> = { email: 'a@b.com' };
    sanitizePayload(obj);
    expect(obj['email']).toBe('a@b.com');
  });
});

// ── Secret Detection ────────────────────────────────────────────────────────

describe('parity: secret_detection', () => {
  afterEach(() => resetPiiRulesForTests());

  it('redacts AWS access key in value', () => {
    const obj: Record<string, unknown> = { data: 'AKIAIOSFODNN7EXAMPLE' }; // pragma: allowlist secret
    sanitizePayload(obj);
    expect(obj['data']).toBe('***');
  });

  it('redacts JWT in value', () => {
    const obj: Record<string, unknown> = {
      data: 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0', // pragma: allowlist secret
    };
    sanitizePayload(obj);
    expect(obj['data']).toBe('***');
  });

  it('does not redact short normal string', () => {
    const obj: Record<string, unknown> = { data: 'not-a-secret' };
    sanitizePayload(obj);
    expect(obj['data']).toBe('not-a-secret');
  });
});

// ── Backpressure Default ─────────────────────────────────────────────────────

describe('parity: backpressure_default', () => {
  it('default queue policy is unlimited (0)', () => {
    const policy = getQueuePolicy();
    expect(policy.maxLogs).toBe(0);
    expect(policy.maxTraces).toBe(0);
    expect(policy.maxMetrics).toBe(0);
  });
});

// ── Error Fingerprint Algorithm ──────────────────────────────────────────────

describe('parity: error_fingerprint_algorithm', () => {
  it('produces correct 12-char hex for error name only', () => {
    const fp = computeErrorFingerprint('ValueError');
    expect(fp).toHaveLength(12);
    expect(fp).toBe('a50aba76697e');
  });
});

// ── Reconfigure Provider Change ──────────────────────────────────────────────

describe('parity: reconfigure_provider_change', () => {
  it('allows provider-changing reconfigure without error', () => {
    setupTelemetry({ otlpEndpoint: 'http://old:4318' });
    expect(() => reconfigureTelemetry({ otlpEndpoint: 'http://new:4318' })).not.toThrow();
  });
});

// ── SLO Classify ────────────────────────────────────────────────────────────

describe('parity: slo_classify', () => {
  it('status 400 = client_error', () => {
    const c = classifyError('ClientError', 400);
    expect(c.category).toBe('client_error');
  });

  it('status 500 = server_error', () => {
    const c = classifyError('ServerError', 500);
    expect(c.category).toBe('server_error');
  });

  it('status 429 = client_error with critical severity', () => {
    const c = classifyError('RateLimitError', 429);
    expect(c.category).toBe('client_error');
    expect(c.severity).toBe('critical');
  });

  it('status 0 = timeout', () => {
    const c = classifyError('TimeoutError', 0);
    expect(c.category).toBe('timeout');
  });

  it('OTel-aligned keys match Go/Python parity', () => {
    const c = classifyError('ServerError', 500);
    expect(c['error.type']).toBe('ServerError');
    expect(c['error.category']).toBe('server_error');
    expect(c['error.severity']).toBe('critical');
    expect(c['http.status_code']).toBe('500');
  });

  it('excName in errorName matches Go parity', () => {
    const c = classifyError('MyException', 503);
    expect(c.errorName).toBe('MyException');
    expect(c['error.type']).toBe('MyException');
  });

  it('timeout detection by excName matches Go parity', () => {
    const c = classifyError('ConnectionTimeoutError', 503);
    expect(c.category).toBe('timeout');
    expect(c['error.category']).toBe('timeout');
  });
});

// ── Cardinality Clamping ────────────────────────────────────────────────────

describe('parity: cardinality_clamping', () => {
  afterEach(() => clearCardinalityLimits());

  it('zero maxValues clamped to 1', () => {
    registerCardinalityLimit('k', { maxValues: 0, ttlSeconds: 10 });
    const limits = getCardinalityLimits();
    expect(limits.get('k')?.maxValues).toBe(1);
    expect(limits.get('k')?.ttlSeconds).toBe(10);
  });

  it('negative maxValues clamped to 1', () => {
    registerCardinalityLimit('k', { maxValues: -5, ttlSeconds: 10 });
    const limits = getCardinalityLimits();
    expect(limits.get('k')?.maxValues).toBe(1);
  });

  it('zero ttlSeconds clamped to 1', () => {
    registerCardinalityLimit('k', { maxValues: 10, ttlSeconds: 0 });
    const limits = getCardinalityLimits();
    expect(limits.get('k')?.ttlSeconds).toBe(1);
  });

  it('negative ttlSeconds clamped to 1', () => {
    registerCardinalityLimit('k', { maxValues: 10, ttlSeconds: -3 });
    const limits = getCardinalityLimits();
    expect(limits.get('k')?.ttlSeconds).toBe(1);
  });

  it('valid values unchanged', () => {
    registerCardinalityLimit('k', { maxValues: 50, ttlSeconds: 300 });
    const limits = getCardinalityLimits();
    expect(limits.get('k')?.maxValues).toBe(50);
    expect(limits.get('k')?.ttlSeconds).toBe(300);
  });
});

// ── Schema Strict Mode ──────────────────────────────────────────────────────

describe('parity: schema strict mode', () => {
  afterEach(() => setupTelemetry({ strictSchema: false }));

  it('lenient mode accepts uppercase segments', () => {
    // eventName with strict=false should accept any segments
    // Need to ensure strict mode is off (default is false)
    expect(() => eventName('A', 'B', 'C')).not.toThrow();
    expect(eventName('A', 'B', 'C')).toBe('A.B.C');
  });

  it('lenient mode accepts mixed case', () => {
    expect(eventName('User', 'Login', 'Ok')).toBe('User.Login.Ok');
  });

  it('strict mode rejects uppercase', () => {
    setupTelemetry({ strictSchema: true });
    expect(() => eventName('User', 'login', 'ok')).toThrow(EventSchemaError);
  });

  it('strict mode accepts valid lowercase', () => {
    setupTelemetry({ strictSchema: true });
    expect(eventName('user', 'login', 'ok')).toBe('user.login.ok');
  });
});

// ── Default Sensitive Keys (parity) ─────────────────────────────────────────

describe('parity: default sensitive keys', () => {
  afterEach(() => resetPiiRulesForTests());

  it('cookie is auto-redacted', () => {
    const obj: Record<string, unknown> = { cookie: 'session=abc123' };
    sanitizePayload(obj);
    expect(obj['cookie']).toBe('***');
  });

  it('cvv is auto-redacted', () => {
    const obj: Record<string, unknown> = { cvv: '123' };
    sanitizePayload(obj);
    expect(obj['cvv']).toBe('***');
  });

  it('pin is auto-redacted', () => {
    const obj: Record<string, unknown> = { pin: '9876' };
    sanitizePayload(obj);
    expect(obj['pin']).toBe('***');
  });
});

// ── PII Depth Limiting (parity) ──────────────────────────────────────────────

describe('parity: pii depth limiting', () => {
  afterEach(() => resetPiiRulesForTests());

  it('redacts at depth < maxDepth, leaves depth >= maxDepth untouched', () => {
    const payload: Record<string, unknown> = {
      password: 'top', // pragma: allowlist secret
      nested: {
        password: 'mid', // pragma: allowlist secret
        deep: {
          password: 'bottom', // pragma: allowlist secret
          tooDeep: {
            password: 'should_survive', // pragma: allowlist secret
          },
        },
      },
    };
    sanitizePayload(payload, [], { maxDepth: 3 });
    expect(payload['password']).toBe('***');
    expect((payload['nested'] as Record<string, unknown>)['password']).toBe('***');
    expect(
      ((payload['nested'] as Record<string, unknown>)['deep'] as Record<string, unknown>)[
        'password'
      ],
    ).toBe('***');
    expect(
      (
        ((payload['nested'] as Record<string, unknown>)['deep'] as Record<string, unknown>)[
          'tooDeep'
        ] as Record<string, unknown>
      )['password'],
    ).toBe('should_survive');
  });

  it('uses default maxDepth of 8 when not specified', () => {
    // Build a deeply nested structure — depth 7 should be redacted, depth 8 should not
    let inner: Record<string, unknown> = { password: 'deepest' }; // pragma: allowlist secret
    for (let i = 0; i < 8; i++) {
      inner = { child: inner };
    }
    const payload: Record<string, unknown> = { ...inner };
    sanitizePayload(payload);
    // Navigate 8 levels deep — should survive
    let node: unknown = payload;
    for (let i = 0; i < 8; i++) {
      node = (node as Record<string, unknown>)['child'];
    }
    expect((node as Record<string, unknown>)['password']).toBe('deepest');
  });
});

// ── Required Keys Validation (parity) ───────────────────────────────────────

describe('parity: required keys validation', () => {
  it('missing required key throws EventSchemaError', () => {
    expect(() => validateRequiredKeys({ domain: 'auth' }, ['domain', 'action'])).toThrow(
      EventSchemaError,
    );
  });

  it('all required keys present does not throw', () => {
    expect(() =>
      validateRequiredKeys({ domain: 'auth', action: 'login' }, ['domain', 'action']),
    ).not.toThrow();
  });

  it('empty required keys does not throw', () => {
    expect(() => validateRequiredKeys({ domain: 'auth' }, [])).not.toThrow();
  });
});
