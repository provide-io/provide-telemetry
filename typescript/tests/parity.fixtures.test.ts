// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Behavioral parity tests — health, SLO, cardinality, schema, backpressure, and more.
 */

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import {
  sanitizePayload,
  resetPiiRulesForTests,
  classifyError,
  parseOtlpHeaders,
  setupTelemetry,
  getQueuePolicy,
  getHealthSnapshot,
  setQueuePolicy,
  tryAcquire,
  release,
  computeErrorFingerprint,
  reconfigureTelemetry,
  registerCardinalityLimit,
  getCardinalityLimits,
  clearCardinalityLimits,
  eventName,
  EventSchemaError,
  validateRequiredKeys,
} from '../src/index';
import { _resetHealthForTests } from '../src/health';
import { _resetResilienceForTests } from '../src/resilience';

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

describe('parity: backpressure_unlimited', () => {
  afterEach(() => setQueuePolicy({ maxLogs: 0, maxTraces: 0, maxMetrics: 0 }));

  it('does not block acquisitions when queue limits are unlimited', () => {
    const first = tryAcquire('logs');
    const second = tryAcquire('logs');

    expect(first).toEqual({ signal: 'logs', token: 0 });
    expect(second).toEqual({ signal: 'logs', token: 0 });

    if (first) release(first);
    if (second) release(second);
  });
});

describe('parity: health_snapshot', () => {
  const canonicalFields = [
    'logsEmitted',
    'logsDropped',
    'exportFailuresLogs',
    'retriesLogs',
    'exportLatencyMsLogs',
    'asyncBlockingRiskLogs',
    'circuitStateLogs',
    'circuitOpenCountLogs',
    'tracesEmitted',
    'tracesDropped',
    'exportFailuresTraces',
    'retriesTraces',
    'exportLatencyMsTraces',
    'asyncBlockingRiskTraces',
    'circuitStateTraces',
    'circuitOpenCountTraces',
    'metricsEmitted',
    'metricsDropped',
    'exportFailuresMetrics',
    'retriesMetrics',
    'exportLatencyMsMetrics',
    'asyncBlockingRiskMetrics',
    'circuitStateMetrics',
    'circuitOpenCountMetrics',
    'setupError',
  ];

  beforeEach(() => {
    _resetHealthForTests();
    _resetResilienceForTests();
  });

  afterEach(() => {
    _resetHealthForTests();
    _resetResilienceForTests();
  });

  it('returns the canonical 25-field layout with reset defaults', () => {
    const snapshot = getHealthSnapshot();

    expect(Object.keys(snapshot)).toEqual(canonicalFields);
    expect(snapshot).toEqual({
      logsEmitted: 0,
      logsDropped: 0,
      exportFailuresLogs: 0,
      retriesLogs: 0,
      exportLatencyMsLogs: 0,
      asyncBlockingRiskLogs: 0,
      circuitStateLogs: 'closed',
      circuitOpenCountLogs: 0,
      tracesEmitted: 0,
      tracesDropped: 0,
      exportFailuresTraces: 0,
      retriesTraces: 0,
      exportLatencyMsTraces: 0,
      asyncBlockingRiskTraces: 0,
      circuitStateTraces: 'closed',
      circuitOpenCountTraces: 0,
      metricsEmitted: 0,
      metricsDropped: 0,
      exportFailuresMetrics: 0,
      retriesMetrics: 0,
      exportLatencyMsMetrics: 0,
      asyncBlockingRiskMetrics: 0,
      circuitStateMetrics: 'closed',
      circuitOpenCountMetrics: 0,
      setupError: null,
    });
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
    let inner: Record<string, unknown> = { password: 'deepest' }; // pragma: allowlist secret
    for (let i = 0; i < 8; i++) {
      inner = { child: inner };
    }
    const payload: Record<string, unknown> = { ...inner };
    sanitizePayload(payload);
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
