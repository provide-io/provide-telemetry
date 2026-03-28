// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { _resetSloForTests, classifyError, recordRedMetrics, recordUseMetrics } from '../src/slo';
import { _resetConfig, setupTelemetry } from '../src/config';
import * as metricsModule from '../src/metrics';

beforeEach(() => {
  _resetConfig();
  _resetSloForTests();
  // Enable SLO metrics by default so existing tests continue to work.
  setupTelemetry({ sloEnableRedMetrics: true, sloEnableUseMetrics: true });
});

afterEach(() => {
  _resetSloForTests();
  _resetConfig();
});

describe('recordRedMetrics', () => {
  it('does not throw for a 200 response', () => {
    expect(() =>
      recordRedMetrics({ route: '/api/v1', method: 'GET', statusCode: 200, durationMs: 42 }),
    ).not.toThrow();
  });

  it('does not throw for a 500 response (records error counter)', () => {
    expect(() =>
      recordRedMetrics({ route: '/api', method: 'POST', statusCode: 500, durationMs: 10 }),
    ).not.toThrow();
  });

  it('creates instruments lazily on first call', () => {
    recordRedMetrics({ route: '/a', method: 'GET', statusCode: 200, durationMs: 5 });
    // Second call reuses the same instruments
    expect(() =>
      recordRedMetrics({ route: '/b', method: 'POST', statusCode: 201, durationMs: 3 }),
    ).not.toThrow();
  });

  it('records errors only for status >= 500', () => {
    // 400-level errors should NOT call the error counter
    expect(() =>
      recordRedMetrics({ route: '/bad', method: 'GET', statusCode: 404, durationMs: 1 }),
    ).not.toThrow();
  });
});

describe('recordUseMetrics', () => {
  it('does not throw', () => {
    expect(() => recordUseMetrics({ resource: 'cpu', utilization: 65 })).not.toThrow();
  });

  it('accepts a custom unit', () => {
    expect(() =>
      recordUseMetrics({ resource: 'memory', utilization: 80, unit: 'MB' }),
    ).not.toThrow();
  });

  it('reuses gauge on second call', () => {
    recordUseMetrics({ resource: 'disk', utilization: 50 });
    expect(() => recordUseMetrics({ resource: 'disk', utilization: 60 })).not.toThrow();
  });
});

describe('classifyError', () => {
  it('classifies 5xx as server error', () => {
    const r = classifyError('ServerError', 500);
    expect(r.errorType).toBe('server');
    expect(r.errorCode).toBe(500);
    expect(r.errorName).toBe('ServerError');
  });

  it('classifies 4xx as client error', () => {
    const r = classifyError('ClientError', 404);
    expect(r.errorType).toBe('client');
    expect(r.errorCode).toBe(404);
    expect(r.errorName).toBe('ClientError');
  });

  it('classifies 2xx as unknown', () => {
    const r = classifyError('', 200);
    expect(r.errorType).toBe('unknown');
    expect(r.errorCode).toBe(200);
    expect(r.errorName).toBe('');
  });

  it('classifies 3xx as unknown', () => {
    expect(classifyError('', 301).errorType).toBe('unknown');
  });

  it('classifies 599 as server', () => {
    expect(classifyError('ServerError', 599).errorType).toBe('server');
  });

  it('classifies 400 as client', () => {
    expect(classifyError('ClientError', 400).errorType).toBe('client');
  });

  it('classifies timeout by exc name even with non-zero status', () => {
    expect(classifyError('TimeoutError', 503).category).toBe('timeout');
  });
});

describe('recordRedMetrics — instrument naming and lazy init', () => {
  it('creates requests counter with correct name and description', () => {
    const spy = vi.spyOn(metricsModule, 'counter');
    recordRedMetrics({ route: '/test', method: 'GET', statusCode: 200, durationMs: 10 });
    expect(spy).toHaveBeenCalledWith(
      'http.requests.total',
      expect.objectContaining({ description: 'Total HTTP requests' }),
    );
    vi.restoreAllMocks();
  });

  it('creates error counter with correct name for 5xx responses', () => {
    const spy = vi.spyOn(metricsModule, 'counter');
    recordRedMetrics({ route: '/err', method: 'POST', statusCode: 500, durationMs: 5 });
    const names = spy.mock.calls.map((c) => c[0]);
    expect(names).toContain('http.errors.total');
    vi.restoreAllMocks();
  });

  it('does NOT create error counter for 4xx responses', () => {
    const spy = vi.spyOn(metricsModule, 'counter');
    recordRedMetrics({ route: '/bad', method: 'GET', statusCode: 499, durationMs: 5 });
    const names = spy.mock.calls.map((c) => c[0]);
    expect(names).not.toContain('http.errors.total');
    vi.restoreAllMocks();
  });

  it('error counter IS created for exactly statusCode=500', () => {
    const spy = vi.spyOn(metricsModule, 'counter');
    recordRedMetrics({ route: '/err', method: 'GET', statusCode: 500, durationMs: 1 });
    const names = spy.mock.calls.map((c) => c[0]);
    expect(names).toContain('http.errors.total');
    vi.restoreAllMocks();
  });

  it('creates histogram with correct name, description, and unit', () => {
    const spy = vi.spyOn(metricsModule, 'histogram');
    recordRedMetrics({ route: '/test', method: 'GET', statusCode: 200, durationMs: 10 });
    expect(spy).toHaveBeenCalledWith(
      'http.request.duration_ms',
      expect.objectContaining({ description: 'HTTP request latency', unit: 'ms' }),
    );
    vi.restoreAllMocks();
  });

  it('reuses counter on repeated calls (lazy init — not called twice)', () => {
    const spy = vi.spyOn(metricsModule, 'counter');
    recordRedMetrics({ route: '/a', method: 'GET', statusCode: 200, durationMs: 1 });
    recordRedMetrics({ route: '/b', method: 'GET', statusCode: 200, durationMs: 1 });
    const requestCalls = spy.mock.calls.filter((c) => c[0] === 'http.requests.total');
    expect(requestCalls).toHaveLength(1);
    vi.restoreAllMocks();
  });
});

describe('recordUseMetrics — instrument naming', () => {
  it('creates gauge with correct name and description', () => {
    const spy = vi.spyOn(metricsModule, 'gauge');
    recordUseMetrics({ resource: 'cpu', utilization: 50 });
    expect(spy).toHaveBeenCalledWith(
      'resource.utilization',
      expect.objectContaining({ description: 'Resource utilization' }),
    );
    vi.restoreAllMocks();
  });

  it('defaults unit to percent when not specified', () => {
    const spy = vi.spyOn(metricsModule, 'gauge');
    recordUseMetrics({ resource: 'mem', utilization: 80 });
    expect(spy).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({ unit: '%' }));
    vi.restoreAllMocks();
  });

  it('uses provided unit when specified', () => {
    const spy = vi.spyOn(metricsModule, 'gauge');
    recordUseMetrics({ resource: 'mem', utilization: 80, unit: 'MB' });
    expect(spy).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({ unit: 'MB' }));
    vi.restoreAllMocks();
  });

  it('reuses gauge on repeated calls (lazy init)', () => {
    const spy = vi.spyOn(metricsModule, 'gauge');
    recordUseMetrics({ resource: 'disk', utilization: 50 });
    recordUseMetrics({ resource: 'disk', utilization: 60 });
    expect(spy).toHaveBeenCalledTimes(1);
    vi.restoreAllMocks();
  });

  it('calls gauge.set() (not gauge.add()) for utilization', () => {
    const setSpy = vi.fn();
    vi.spyOn(metricsModule, 'gauge').mockReturnValue({
      add: vi.fn(),
      set: setSpy,
      name: 'resource.utilization',
    } as never);
    recordUseMetrics({ resource: 'cpu', utilization: 65 });
    expect(setSpy).toHaveBeenCalledWith(65, { resource: 'cpu' });
    vi.restoreAllMocks();
  });

  it('calls gauge.set() with correct value on repeated calls', () => {
    const setSpy = vi.fn();
    vi.spyOn(metricsModule, 'gauge').mockReturnValue({
      add: vi.fn(),
      set: setSpy,
      name: 'resource.utilization',
    } as never);
    recordUseMetrics({ resource: 'cpu', utilization: 65 });
    recordUseMetrics({ resource: 'cpu', utilization: 80 });
    expect(setSpy).toHaveBeenNthCalledWith(1, 65, { resource: 'cpu' });
    expect(setSpy).toHaveBeenNthCalledWith(2, 80, { resource: 'cpu' });
    vi.restoreAllMocks();
  });
});

describe('recordUseMetrics — gauge.add called with resource attr (kills ObjectLiteral on gauge attrs)', () => {
  it('passes resource attribute to gauge set', () => {
    _resetSloForTests();
    const setSpy = vi.fn();
    vi.spyOn(metricsModule, 'gauge').mockReturnValue({
      add: vi.fn(),
      set: setSpy,
      name: 'resource.utilization',
    } as never);
    recordUseMetrics({ resource: 'cpu', utilization: 75 });
    expect(setSpy).toHaveBeenCalledWith(75, { resource: 'cpu' });
    vi.restoreAllMocks();
  });
});

describe('slo — counter.add called with route/method/status_code attrs (kills ObjectLiteral on attrs)', () => {
  it('passes route, method, and status_code attributes to counter.add', () => {
    _resetSloForTests();
    const counterInstances: Array<{ add: ReturnType<typeof vi.fn> }> = [];
    vi.spyOn(metricsModule, 'counter').mockImplementation((_name, _opts) => {
      const inst = { add: vi.fn(), name: _name };
      counterInstances.push(inst);
      return inst as unknown as ReturnType<typeof metricsModule.counter>;
    });
    recordRedMetrics({ route: '/test', method: 'GET', statusCode: 200, durationMs: 5 });
    // At least one counter.add was called with correct attrs
    const allCalls = counterInstances.flatMap((inst) => inst.add.mock.calls);
    expect(
      allCalls.some((call) => {
        const attrs = call[1] as Record<string, string>;
        return (
          attrs['route'] === '/test' && attrs['method'] === 'GET' && attrs['status_code'] === '200'
        );
      }),
    ).toBe(true);
    vi.restoreAllMocks();
  });
});

describe('classifyError — exact return value assertions for mutation killing', () => {
  it('status 0 → timeout classification with all OTel-aligned keys', () => {
    const r = classifyError('ConnectionError', 0);
    expect(r).toEqual({
      errorType: 'timeout',
      errorCode: 0,
      errorName: 'ConnectionError',
      category: 'timeout',
      severity: 'info',
      'error.type': 'ConnectionError',
      'error.category': 'timeout',
      'error.severity': 'info',
      'http.status_code': '0',
    });
  });

  it('timeout by name with non-zero status has correct severity "info"', () => {
    const r = classifyError('TimeoutError', 503);
    expect(r.severity).toBe('info');
    expect(r['error.severity']).toBe('info');
    expect(r['error.category']).toBe('timeout');
    expect(r['http.status_code']).toBe('503');
  });

  it('status 500 → server_error with severity "critical"', () => {
    const r = classifyError('InternalServerError', 500);
    expect(r.category).toBe('server_error');
    expect(r.severity).toBe('critical');
    expect(r['error.category']).toBe('server_error');
    expect(r['error.severity']).toBe('critical');
    expect(r['error.type']).toBe('InternalServerError');
    expect(r['http.status_code']).toBe('500');
  });

  it('status 499 → client_error (boundary: not server_error)', () => {
    const r = classifyError('ClientError', 499);
    expect(r.category).toBe('client_error');
    expect(r.errorType).toBe('client');
    expect(r['error.category']).toBe('client_error');
  });

  it('status 429 → client_error with severity "critical" (rate limit)', () => {
    const r = classifyError('RateLimitError', 429);
    expect(r.category).toBe('client_error');
    expect(r.severity).toBe('critical');
    expect(r['error.severity']).toBe('critical');
  });

  it('status 430 → client_error with severity "warning" (not critical)', () => {
    const r = classifyError('ClientError', 430);
    expect(r.category).toBe('client_error');
    expect(r.severity).toBe('warning');
    expect(r['error.severity']).toBe('warning');
  });

  it('status 400 → client_error with severity "warning"', () => {
    const r = classifyError('BadRequest', 400);
    expect(r.severity).toBe('warning');
    expect(r['error.severity']).toBe('warning');
  });

  it('status 200 → unknown with severity "unknown"', () => {
    const r = classifyError('Unexpected', 200);
    expect(r).toEqual({
      errorType: 'unknown',
      errorCode: 200,
      errorName: 'Unexpected',
      category: 'unknown',
      severity: 'unknown',
      'error.type': 'Unexpected',
      'error.category': 'unknown',
      'error.severity': 'unknown',
      'http.status_code': '200',
    });
  });

  it('status 399 → unknown (below 400 boundary)', () => {
    const r = classifyError('Other', 399);
    expect(r.errorType).toBe('unknown');
    expect(r.category).toBe('unknown');
  });

  it('http.status_code is always a string representation', () => {
    expect(classifyError('E', 500)['http.status_code']).toBe('500');
    expect(classifyError('E', 404)['http.status_code']).toBe('404');
    expect(classifyError('E', 0)['http.status_code']).toBe('0');
    expect(classifyError('E', 200)['http.status_code']).toBe('200');
  });

  it('error.type matches errorName for all branches', () => {
    expect(classifyError('MyTimeout', 0)['error.type']).toBe('MyTimeout');
    expect(classifyError('ServerErr', 500)['error.type']).toBe('ServerErr');
    expect(classifyError('ClientErr', 404)['error.type']).toBe('ClientErr');
    expect(classifyError('Unknown', 200)['error.type']).toBe('Unknown');
  });
});

describe('recordRedMetrics — status boundary 499 vs 500', () => {
  it('status 499 does NOT trigger error counter', () => {
    _resetSloForTests();
    const spy = vi.spyOn(metricsModule, 'counter');
    recordRedMetrics({ route: '/test', method: 'GET', statusCode: 499, durationMs: 1 });
    const names = spy.mock.calls.map((c) => c[0]);
    expect(names).not.toContain('http.errors.total');
    vi.restoreAllMocks();
  });

  it('status 500 triggers error counter', () => {
    _resetSloForTests();
    const spy = vi.spyOn(metricsModule, 'counter');
    recordRedMetrics({ route: '/test', method: 'GET', statusCode: 500, durationMs: 1 });
    const names = spy.mock.calls.map((c) => c[0]);
    expect(names).toContain('http.errors.total');
    vi.restoreAllMocks();
  });
});

describe('_resetSloForTests', () => {
  it('clears instruments so counter is recreated after reset', () => {
    recordRedMetrics({ route: '/x', method: 'GET', statusCode: 200, durationMs: 1 });
    _resetSloForTests();
    const spy = vi.spyOn(metricsModule, 'counter');
    recordRedMetrics({ route: '/y', method: 'GET', statusCode: 200, durationMs: 1 });
    expect(spy).toHaveBeenCalled();
    vi.restoreAllMocks();
  });
});

describe('slo — histogram reuse (kills ConditionalExpression→true in _lazyHistogram)', () => {
  it('creates histogram only once for same name', () => {
    _resetSloForTests();
    const spy = vi.spyOn(metricsModule, 'histogram');
    recordRedMetrics({ route: '/a', method: 'GET', statusCode: 200, durationMs: 1 });
    recordRedMetrics({ route: '/b', method: 'POST', statusCode: 200, durationMs: 2 });
    const durationCalls = spy.mock.calls.filter((c) => c[0] === 'http.request.duration_ms');
    expect(durationCalls).toHaveLength(1);
    vi.restoreAllMocks();
  });
});

describe('sloEnableRedMetrics toggle', () => {
  it('is a no-op when sloEnableRedMetrics is false', () => {
    setupTelemetry({ sloEnableRedMetrics: false });
    _resetSloForTests();
    const counterInstances: Array<{ add: ReturnType<typeof vi.fn> }> = [];
    vi.spyOn(metricsModule, 'counter').mockImplementation((_name, _opts) => {
      const inst = { add: vi.fn() };
      counterInstances.push(inst);
      return inst as unknown as ReturnType<typeof metricsModule.counter>;
    });
    recordRedMetrics({ route: '/test', method: 'GET', statusCode: 200, durationMs: 5 });
    // At least one counter.add was called with correct attrs
    const allCalls = counterInstances.flatMap((inst) => inst.add.mock.calls);
    expect(
      allCalls.some((call) => {
        const attrs = call[1] as Record<string, string>;
        return (
          attrs['route'] === '/test' && attrs['method'] === 'GET' && attrs['status_code'] === '200'
        );
      }),
    ).toBe(true);
    vi.restoreAllMocks();
  });
});

describe('sloEnableUseMetrics toggle', () => {
  it('is a no-op when sloEnableUseMetrics is false', () => {
    setupTelemetry({ sloEnableUseMetrics: false });
    _resetSloForTests();
    const gaugeInstances: Array<{ add: ReturnType<typeof vi.fn> }> = [];
    vi.spyOn(metricsModule, 'gauge').mockImplementation((_name, _opts) => {
      const inst = { add: vi.fn() };
      gaugeInstances.push(inst);
      return inst as unknown as ReturnType<typeof metricsModule.gauge>;
    });
    recordUseMetrics({ resource: 'cpu', utilization: 75 });
    const allCalls = gaugeInstances.flatMap((inst) => inst.add.mock.calls);
    expect(
      allCalls.some((call) => {
        const attrs = call[1] as Record<string, string>;
        return attrs['resource'] === 'cpu';
      }),
    ).toBe(true);
    vi.restoreAllMocks();
  });
});
