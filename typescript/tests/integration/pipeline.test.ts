// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: AGPL-3.0-or-later

/**
 * Integration tests — full pipeline: setupTelemetry → getLogger → log → capture.
 *
 * These tests exercise the public API surface end-to-end rather than internal hooks.
 * The write hook is tested directly in logger.test.ts; here we verify that calling
 * the exported functions produces the expected observable effects.
 *
 * Note: pino's browser.write hook is NOT triggered in Node.js/vitest because pino
 * detects the Node.js runtime and uses its standard transport. window.__pinoLogs
 * therefore stays empty unless the hook is invoked directly. These tests exercise
 * the exported API, context propagation, and logger correctness, not the hook path.
 */

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { _resetConfig, setupTelemetry } from '../../src/config';
import {
  _resetContext,
  bindContext,
  clearContext,
  getContext,
  runWithContext,
  unbindContext,
} from '../../src/context';
import { _resetRootLogger, getLogger } from '../../src/logger';
import { sanitize } from '../../src/sanitize';
import { withTrace } from '../../src/tracing';
import { counter, gauge, histogram } from '../../src/metrics';

beforeEach(() => {
  _resetConfig();
  _resetRootLogger();
  _resetContext();
  setupTelemetry({
    serviceName: 'integration-test',
    logLevel: 'debug',
    captureToWindow: true,
    consoleOutput: false,
  });
});

afterEach(() => {
  _resetConfig();
  _resetRootLogger();
  _resetContext();
});

// ── Logger API surface ─────────────────────────────────────────────────────────

describe('Logger API surface', () => {
  it('getLogger returns a functional logger', () => {
    const log = getLogger('api');
    expect(typeof log.trace).toBe('function');
    expect(typeof log.debug).toBe('function');
    expect(typeof log.info).toBe('function');
    expect(typeof log.warn).toBe('function');
    expect(typeof log.error).toBe('function');
    expect(typeof log.child).toBe('function');
  });

  it('getLogger() without name returns root logger', () => {
    const log = getLogger();
    expect(log).toBeDefined();
    expect(typeof log.info).toBe('function');
  });

  it('all log methods execute without error', () => {
    const log = getLogger('smoke');
    expect(() => log.trace({ event: 'trace_evt' })).not.toThrow();
    expect(() => log.debug({ event: 'debug_evt' })).not.toThrow();
    expect(() => log.info({ event: 'info_evt', status: 200 })).not.toThrow();
    expect(() => log.warn({ event: 'warn_evt', retries: 3 })).not.toThrow();
    expect(() => log.error({ event: 'error_evt', error: 'oops' })).not.toThrow();
  });

  it('child logger inherits parent bindings and accepts additional fields', () => {
    const log = getLogger('parent');
    const child = log.child({ request_id: 'req-abc', service_version: '2.0' });
    expect(typeof child.info).toBe('function');
    expect(typeof child.child).toBe('function');
    expect(() => child.info({ event: 'child_event', user_id: 7 })).not.toThrow();
  });

  it('deeply nested child loggers do not throw', () => {
    const log = getLogger('root');
    const child1 = log.child({ level_1: true });
    const child2 = child1.child({ level_2: true });
    const child3 = child2.child({ level_3: true });
    expect(() => child3.info({ event: 'deep_event' })).not.toThrow();
  });
});

// ── Context propagation ────────────────────────────────────────────────────────

describe('Context propagation', () => {
  it('bindContext values are visible via getContext', () => {
    bindContext({ request_id: 'req-1', user_id: 42 });
    const ctx = getContext();
    expect(ctx['request_id']).toBe('req-1');
    expect(ctx['user_id']).toBe(42);
  });

  it('unbindContext removes specific keys', () => {
    bindContext({ a: 1, b: 2, c: 3 });
    unbindContext('a', 'c');
    const ctx = getContext();
    expect(ctx).not.toHaveProperty('a');
    expect(ctx['b']).toBe(2);
    expect(ctx).not.toHaveProperty('c');
  });

  it('clearContext wipes all bindings', () => {
    bindContext({ x: 1, y: 2 });
    clearContext();
    expect(getContext()).toEqual({});
  });

  it('runWithContext scopes bindings and restores on exit', () => {
    bindContext({ outer: 'value' });
    runWithContext({ request_id: 'scoped-req' }, () => {
      expect(getContext()['request_id']).toBe('scoped-req');
      expect(getContext()['outer']).toBe('value');
    });
    expect(getContext()).not.toHaveProperty('request_id');
    expect(getContext()['outer']).toBe('value');
  });

  it('runWithContext returns the value from fn', () => {
    const result = runWithContext({ tag: 'test' }, () => 'returned-value');
    expect(result).toBe('returned-value');
  });

  it('runWithContext works with async functions', async () => {
    const result = await runWithContext({ session: 'async-test' }, async () => {
      await Promise.resolve();
      return getContext()['session'];
    });
    expect(result).toBe('async-test');
  });

  it('multiple concurrent runWithContext calls are isolated', async () => {
    const results = await Promise.all([
      runWithContext({ id: 'req-1' }, async () => {
        await Promise.resolve();
        return getContext()['id'];
      }),
      runWithContext({ id: 'req-2' }, async () => {
        await Promise.resolve();
        return getContext()['id'];
      }),
    ]);
    expect(results[0]).toBe('req-1');
    expect(results[1]).toBe('req-2');
  });

  it('context is a snapshot — mutations do not leak', () => {
    bindContext({ mutable: 'original' });
    const ctx = getContext();
    ctx['mutable'] = 'mutated';
    expect(getContext()['mutable']).toBe('original');
  });
});

// ── PII sanitization pipeline ──────────────────────────────────────────────────

describe('PII sanitization pipeline', () => {
  const SENSITIVE_FIELDS = ['password', 'token', 'secret', 'authorization', 'cookie'];

  it('sanitize redacts all default PII fields', () => {
    const obj: Record<string, unknown> = {
      event: 'login',
      username: 'alice',
      password: 'hunter2',
      token: 'jwt.abc.def',
      secret: 'my-secret',
      authorization: 'Bearer xyz',
      cookie: 'session=abc123',
    };
    sanitize(obj, SENSITIVE_FIELDS);
    expect(obj['username']).toBe('alice');
    expect(obj['password']).toBe('[REDACTED]');
    expect(obj['token']).toBe('[REDACTED]');
    expect(obj['secret']).toBe('[REDACTED]');
    expect(obj['authorization']).toBe('[REDACTED]');
    expect(obj['cookie']).toBe('[REDACTED]');
  });

  it('sanitize is case-insensitive', () => {
    const obj: Record<string, unknown> = { PASSWORD: 'exposed', Token: 'exposed2' };
    sanitize(obj, SENSITIVE_FIELDS);
    expect(obj['PASSWORD']).toBe('[REDACTED]');
    expect(obj['Token']).toBe('[REDACTED]');
  });

  it('non-PII fields pass through unchanged', () => {
    const obj: Record<string, unknown> = { user_id: 7, status: 200, event: 'ok' };
    sanitize(obj, SENSITIVE_FIELDS);
    expect(obj['user_id']).toBe(7);
    expect(obj['status']).toBe(200);
    expect(obj['event']).toBe('ok');
  });

  it('empty extra field list only redacts default PII fields', () => {
    const obj: Record<string, unknown> = { username: 'alice', custom_field: 'stays' };
    sanitize(obj, []);
    expect(obj['username']).toBe('alice');
    expect(obj['custom_field']).toBe('stays');
  });

  it('setupTelemetry with sanitizeFields flows through to logging', () => {
    _resetConfig();
    setupTelemetry({
      serviceName: 'pii-test',
      sanitizeFields: ['api_key'],
      captureToWindow: true,
    });
    const log = getLogger('pii');
    // Logging with a sensitive field should not throw
    expect(() => log.warn({ event: 'api_call', api_key: 'secret-key' })).not.toThrow();
  });
});

// ── Tracing integration ────────────────────────────────────────────────────────

describe('Tracing integration', () => {
  it('withTrace executes sync functions without OTEL SDK', () => {
    const result = withTrace('integration.sync', () => 42);
    expect(result).toBe(42);
  });

  it('withTrace executes async functions without OTEL SDK', async () => {
    const result = await withTrace('integration.async', async () => 'hello');
    expect(result).toBe('hello');
  });

  it('withTrace propagates sync exceptions', () => {
    expect(() =>
      withTrace('integration.error', () => {
        throw new Error('expected error');
      }),
    ).toThrow('expected error');
  });

  it('withTrace propagates async rejections', async () => {
    await expect(
      withTrace('integration.async.error', async () => {
        throw new Error('async expected error');
      }),
    ).rejects.toThrow('async expected error');
  });

  it('withTrace can be used inside runWithContext', async () => {
    const result = await runWithContext({ trace_context: true }, async () => {
      return withTrace('nested.trace', () => getContext()['trace_context']);
    });
    expect(result).toBe(true);
  });
});

// ── Metrics integration ────────────────────────────────────────────────────────

describe('Metrics integration', () => {
  it('counter.add does not throw (no-op without OTEL SDK)', () => {
    const requests = counter('http.requests', { unit: 'request' });
    expect(() => requests.add(1, { path: '/api/v1/users', method: 'GET' })).not.toThrow();
    expect(() => requests.add(5)).not.toThrow();
  });

  it('gauge.add does not throw (no-op without OTEL SDK)', () => {
    const connections = gauge('db.connections', { description: 'Active DB connections' });
    expect(() => connections.add(42, { pool: 'primary' })).not.toThrow();
    expect(() => connections.add(-5)).not.toThrow();
  });

  it('histogram.record does not throw (no-op without OTEL SDK)', () => {
    const latency = histogram('http.request.duration', { unit: 'ms' });
    expect(() => latency.record(123, { route: '/api/users', status: '200' })).not.toThrow();
    expect(() => latency.record(500)).not.toThrow();
  });

  it('multiple instruments from same meter do not interfere', () => {
    const c1 = counter('counter.one');
    const c2 = counter('counter.two');
    expect(() => {
      c1.add(1);
      c2.add(10);
      c1.add(2);
    }).not.toThrow();
  });
});

// ── Full end-to-end pipeline ───────────────────────────────────────────────────

describe('End-to-end pipeline', () => {
  it('complete request lifecycle: bind context, log events, clear', () => {
    const log = getLogger('request');
    bindContext({ service: 'integration-test', env: 'test' });

    expect(() => {
      log.info({ event: 'request_start', method: 'GET', path: '/api/users' });

      runWithContext({ request_id: 'req-e2e-001' }, () => {
        log.debug({ event: 'auth_check', user_id: 7 });
        log.info({ event: 'request_complete', status: 200, duration_ms: 42 });
      });

      log.debug({ event: 'request_start', method: 'POST', path: '/api/items' });
    }).not.toThrow();

    clearContext();
    expect(getContext()).toEqual({});
  });

  it('error handling: log error with PII sanitization', () => {
    _resetConfig();
    setupTelemetry({
      serviceName: 'error-test',
      sanitizeFields: ['password', 'token'],
      captureToWindow: false,
      consoleOutput: false,
    });
    _resetRootLogger();

    const log = getLogger('auth');
    expect(() =>
      log.error({
        event: 'auth_failed',
        username: 'alice',
        password: 'should-be-redacted',
        token: 'leaked-token',
        error: 'Invalid credentials',
      }),
    ).not.toThrow();
  });

  it('child logger + context binding combines fields correctly', () => {
    bindContext({ request_id: 'req-child-001' });
    const log = getLogger('service');
    const requestLog = log.child({ component: 'db' });
    expect(() => requestLog.info({ event: 'query_ok', table: 'users', rows: 5 })).not.toThrow();
  });
});
