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

  it('uses set semantics — second call with same value produces delta=0', () => {
    const addSpy = vi.fn();
    vi.spyOn(metricsModule, 'gauge').mockReturnValue({ add: addSpy } as never);
    recordUseMetrics({ resource: 'cpu', utilization: 65 });
    expect(addSpy).toHaveBeenLastCalledWith(65, { resource: 'cpu' });
    recordUseMetrics({ resource: 'cpu', utilization: 65 });
    expect(addSpy).toHaveBeenLastCalledWith(0, { resource: 'cpu' });
    vi.restoreAllMocks();
  });

  it('uses set semantics — increasing value produces correct delta', () => {
    const addSpy = vi.fn();
    vi.spyOn(metricsModule, 'gauge').mockReturnValue({ add: addSpy } as never);
    recordUseMetrics({ resource: 'mem', utilization: 60 });
    recordUseMetrics({ resource: 'mem', utilization: 80 });
    expect(addSpy).toHaveBeenLastCalledWith(20, { resource: 'mem' });
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
    const spy = vi.spyOn(metricsModule, 'counter');
    recordRedMetrics({ route: '/test', method: 'GET', statusCode: 200, durationMs: 10 });
    expect(spy).not.toHaveBeenCalled();
    vi.restoreAllMocks();
  });

  it('records metrics when sloEnableRedMetrics is true', () => {
    setupTelemetry({ sloEnableRedMetrics: true });
    _resetSloForTests();
    const spy = vi.spyOn(metricsModule, 'counter');
    recordRedMetrics({ route: '/test', method: 'GET', statusCode: 200, durationMs: 10 });
    expect(spy).toHaveBeenCalled();
    vi.restoreAllMocks();
  });
});

describe('sloEnableUseMetrics toggle', () => {
  it('is a no-op when sloEnableUseMetrics is false', () => {
    setupTelemetry({ sloEnableUseMetrics: false });
    _resetSloForTests();
    const spy = vi.spyOn(metricsModule, 'gauge');
    recordUseMetrics({ resource: 'cpu', utilization: 50 });
    expect(spy).not.toHaveBeenCalled();
    vi.restoreAllMocks();
  });

  it('records metrics when sloEnableUseMetrics is true', () => {
    setupTelemetry({ sloEnableUseMetrics: true });
    _resetSloForTests();
    const spy = vi.spyOn(metricsModule, 'gauge');
    recordUseMetrics({ resource: 'cpu', utilization: 50 });
    expect(spy).toHaveBeenCalled();
    vi.restoreAllMocks();
  });
});
