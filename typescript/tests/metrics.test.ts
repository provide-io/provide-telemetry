// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  CounterInstrument,
  GaugeInstrument,
  HistogramInstrument,
  counter,
  gauge,
  getMeter,
  histogram,
} from '../src/metrics';
import { setSamplingPolicy, _resetSamplingForTests } from '../src/sampling';
import { setQueuePolicy, tryAcquire, _resetBackpressureForTests } from '../src/backpressure';

afterEach(() => {
  _resetSamplingForTests();
  _resetBackpressureForTests();
});

describe('metrics instruments', () => {
  it('counter() returns a CounterInstrument', () => {
    const c = counter('test.requests', { unit: 'request' });
    expect(c).toBeInstanceOf(CounterInstrument);
    expect(typeof c.add).toBe('function');
  });

  it('counter.add() does not throw without SDK', () => {
    const c = counter('test.requests2');
    expect(() => c.add(1, { path: '/api' })).not.toThrow();
    expect(() => c.add(5)).not.toThrow();
  });

  it('gauge() returns a GaugeInstrument', () => {
    const g = gauge('test.active_connections', { unit: 'connection' });
    expect(g).toBeInstanceOf(GaugeInstrument);
    expect(typeof g.add).toBe('function');
    expect(typeof g.set).toBe('function');
  });

  it('gauge.add() handles negative values', () => {
    const g = gauge('test.queue_depth');
    expect(() => g.add(10)).not.toThrow();
    expect(() => g.add(-3, { queue: 'main' })).not.toThrow();
  });

  it('histogram() returns a HistogramInstrument', () => {
    const h = histogram('test.latency_ms', { unit: 'ms' });
    expect(h).toBeInstanceOf(HistogramInstrument);
    expect(typeof h.record).toBe('function');
  });

  it('histogram.record() does not throw without SDK', () => {
    const h = histogram('test.response_size');
    expect(() => h.record(1024)).not.toThrow();
    expect(() => h.record(512, { route: '/api/v1' })).not.toThrow();
  });
});

describe('getMeter', () => {
  it('returns a Meter with default name', () => {
    const m = getMeter();
    expect(m).toBeDefined();
    expect(typeof m.createCounter).toBe('function');
  });

  it('returns a Meter with custom name', () => {
    const m = getMeter('custom-meter');
    expect(m).toBeDefined();
    expect(typeof m.createHistogram).toBe('function');
  });
});

describe('CounterInstrument — sampling gate', () => {
  it('does NOT call underlying instrument when sampling rate is 0', () => {
    const inner = { add: vi.fn() };
    const c = new CounterInstrument('test.counter', inner as never);
    setSamplingPolicy('metrics', { defaultRate: 0.0 });
    c.add(1, { key: 'val' });
    expect(inner.add).not.toHaveBeenCalled();
  });

  it('DOES call underlying instrument when sampling allows', () => {
    const inner = { add: vi.fn() };
    const c = new CounterInstrument('test.counter', inner as never);
    setSamplingPolicy('metrics', { defaultRate: 1.0 });
    c.add(42, { key: 'val' });
    expect(inner.add).toHaveBeenCalledWith(42, { key: 'val' });
  });

  it('calls add without attributes when none provided', () => {
    const inner = { add: vi.fn() };
    const c = new CounterInstrument('test.counter', inner as never);
    c.add(1);
    expect(inner.add).toHaveBeenCalledWith(1, undefined);
  });
});

describe('CounterInstrument — backpressure gate', () => {
  it('drops call when backpressure queue is full', () => {
    const inner = { add: vi.fn() };
    const c = new CounterInstrument('test.counter', inner as never);
    setQueuePolicy({ maxMetrics: 1 });
    // Acquire the only slot
    const ticket = tryAcquire('metrics');
    expect(ticket).not.toBeNull();
    // Now counter should be blocked
    c.add(1);
    expect(inner.add).not.toHaveBeenCalled();
  });
});

describe('GaugeInstrument — set semantics', () => {
  it('set(65) then set(65) — underlying gets add(65) then add(0)', () => {
    const inner = { add: vi.fn() };
    const g = new GaugeInstrument('test.gauge', inner as never);
    g.set(65);
    expect(inner.add).toHaveBeenLastCalledWith(65, undefined);
    g.set(65);
    expect(inner.add).toHaveBeenLastCalledWith(0, undefined);
  });

  it('set(80) after set(65) — underlying gets add(65) then add(15)', () => {
    const inner = { add: vi.fn() };
    const g = new GaugeInstrument('test.gauge', inner as never);
    g.set(65);
    expect(inner.add).toHaveBeenLastCalledWith(65, undefined);
    g.set(80);
    expect(inner.add).toHaveBeenLastCalledWith(15, undefined);
  });

  it('tracks per-attribute-key values independently', () => {
    const inner = { add: vi.fn() };
    const g = new GaugeInstrument('test.gauge', inner as never);
    g.set(10, { resource: 'cpu' });
    g.set(20, { resource: 'mem' });
    g.set(15, { resource: 'cpu' });
    // cpu: delta = 15 - 10 = 5
    expect(inner.add).toHaveBeenLastCalledWith(5, { resource: 'cpu' });
  });

  it('does NOT call underlying when sampling rate is 0 (set)', () => {
    const inner = { add: vi.fn() };
    const g = new GaugeInstrument('test.gauge', inner as never);
    setSamplingPolicy('metrics', { defaultRate: 0.0 });
    g.set(100);
    expect(inner.add).not.toHaveBeenCalled();
  });

  it('does NOT call underlying when sampling rate is 0 (add)', () => {
    const inner = { add: vi.fn() };
    const g = new GaugeInstrument('test.gauge', inner as never);
    setSamplingPolicy('metrics', { defaultRate: 0.0 });
    g.add(10);
    expect(inner.add).not.toHaveBeenCalled();
  });

  it('drops set() when backpressure queue is full', () => {
    const inner = { add: vi.fn() };
    const g = new GaugeInstrument('test.gauge', inner as never);
    setQueuePolicy({ maxMetrics: 1 });
    const ticket = tryAcquire('metrics');
    expect(ticket).not.toBeNull();
    g.set(50);
    expect(inner.add).not.toHaveBeenCalled();
  });

  it('drops add() when backpressure queue is full', () => {
    const inner = { add: vi.fn() };
    const g = new GaugeInstrument('test.gauge', inner as never);
    setQueuePolicy({ maxMetrics: 1 });
    const ticket = tryAcquire('metrics');
    expect(ticket).not.toBeNull();
    g.add(10);
    expect(inner.add).not.toHaveBeenCalled();
  });
});

describe('HistogramInstrument — sampling gate', () => {
  it('does NOT call underlying when sampling rate is 0', () => {
    const inner = { record: vi.fn() };
    const h = new HistogramInstrument('test.hist', inner as never);
    setSamplingPolicy('metrics', { defaultRate: 0.0 });
    h.record(100);
    expect(inner.record).not.toHaveBeenCalled();
  });

  it('DOES call underlying when sampling allows', () => {
    const inner = { record: vi.fn() };
    const h = new HistogramInstrument('test.hist', inner as never);
    h.record(42, { route: '/api' });
    expect(inner.record).toHaveBeenCalledWith(42, { route: '/api' });
  });

  it('calls record without attributes when none provided', () => {
    const inner = { record: vi.fn() };
    const h = new HistogramInstrument('test.hist', inner as never);
    h.record(10);
    expect(inner.record).toHaveBeenCalledWith(10, undefined);
  });

  it('drops call when backpressure queue is full', () => {
    const inner = { record: vi.fn() };
    const h = new HistogramInstrument('test.hist', inner as never);
    setQueuePolicy({ maxMetrics: 1 });
    const ticket = tryAcquire('metrics');
    expect(ticket).not.toBeNull();
    h.record(100);
    expect(inner.record).not.toHaveBeenCalled();
  });
});

describe('wrapper name property', () => {
  it('CounterInstrument exposes name', () => {
    const c = counter('my.counter');
    expect(c.name).toBe('my.counter');
  });

  it('GaugeInstrument exposes name', () => {
    const g = gauge('my.gauge');
    expect(g.name).toBe('my.gauge');
  });

  it('HistogramInstrument exposes name', () => {
    const h = histogram('my.histogram');
    expect(h.name).toBe('my.histogram');
  });
});
