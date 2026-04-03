// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, describe, expect, it, vi } from 'vitest';
import * as tracing from '../src/tracing';
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
import { setupTelemetry, _resetConfig } from '../src/config';

afterEach(() => {
  _resetSamplingForTests();
  _resetBackpressureForTests();
  _resetConfig();
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

describe('exemplar attachment', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('counter.add() merges trace_id and span_id into attributes when active trace exists', () => {
    vi.spyOn(tracing, 'getActiveTraceIds').mockReturnValue({ trace_id: 'abc', span_id: 'def' });
    const inner = { add: vi.fn() };
    const c = new CounterInstrument('test.counter', inner as never);
    c.add(1, { key: 'val' });
    expect(inner.add).toHaveBeenCalledWith(1, { key: 'val', trace_id: 'abc', span_id: 'def' });
  });

  it('counter.add() merges trace IDs even when no attributes provided', () => {
    vi.spyOn(tracing, 'getActiveTraceIds').mockReturnValue({ trace_id: 'abc', span_id: 'def' });
    const inner = { add: vi.fn() };
    const c = new CounterInstrument('test.counter', inner as never);
    c.add(1);
    expect(inner.add).toHaveBeenCalledWith(1, { trace_id: 'abc', span_id: 'def' });
  });

  it('counter.add() passes attributes unchanged when no active trace', () => {
    vi.spyOn(tracing, 'getActiveTraceIds').mockReturnValue({});
    const inner = { add: vi.fn() };
    const c = new CounterInstrument('test.counter', inner as never);
    c.add(1, { key: 'val' });
    expect(inner.add).toHaveBeenCalledWith(1, { key: 'val' });
  });

  it('counter.add() passes undefined attributes when no active trace and no attributes', () => {
    vi.spyOn(tracing, 'getActiveTraceIds').mockReturnValue({});
    const inner = { add: vi.fn() };
    const c = new CounterInstrument('test.counter', inner as never);
    c.add(1);
    expect(inner.add).toHaveBeenCalledWith(1, undefined);
  });

  it('histogram.record() merges trace_id and span_id into attributes when active trace exists', () => {
    vi.spyOn(tracing, 'getActiveTraceIds').mockReturnValue({ trace_id: 'abc', span_id: 'def' });
    const inner = { record: vi.fn() };
    const h = new HistogramInstrument('test.hist', inner as never);
    h.record(42, { route: '/api' });
    expect(inner.record).toHaveBeenCalledWith(42, {
      route: '/api',
      trace_id: 'abc',
      span_id: 'def',
    });
  });

  it('histogram.record() merges trace IDs even when no attributes provided', () => {
    vi.spyOn(tracing, 'getActiveTraceIds').mockReturnValue({ trace_id: 'abc', span_id: 'def' });
    const inner = { record: vi.fn() };
    const h = new HistogramInstrument('test.hist', inner as never);
    h.record(42);
    expect(inner.record).toHaveBeenCalledWith(42, { trace_id: 'abc', span_id: 'def' });
  });

  it('histogram.record() passes attributes unchanged when no active trace', () => {
    vi.spyOn(tracing, 'getActiveTraceIds').mockReturnValue({});
    const inner = { record: vi.fn() };
    const h = new HistogramInstrument('test.hist', inner as never);
    h.record(42, { route: '/api' });
    expect(inner.record).toHaveBeenCalledWith(42, { route: '/api' });
  });

  it('histogram.record() passes undefined attributes when no active trace and no attributes', () => {
    vi.spyOn(tracing, 'getActiveTraceIds').mockReturnValue({});
    const inner = { record: vi.fn() };
    const h = new HistogramInstrument('test.hist', inner as never);
    h.record(42);
    expect(inner.record).toHaveBeenCalledWith(42, undefined);
  });

  it('gauge.add() does NOT attach exemplars even when active trace exists', () => {
    vi.spyOn(tracing, 'getActiveTraceIds').mockReturnValue({ trace_id: 'abc', span_id: 'def' });
    const inner = { add: vi.fn() };
    const g = new GaugeInstrument('test.gauge', inner as never);
    g.add(10, { key: 'val' });
    expect(inner.add).toHaveBeenCalledWith(10, { key: 'val' });
  });

  it('gauge.set() does NOT attach exemplars even when active trace exists', () => {
    vi.spyOn(tracing, 'getActiveTraceIds').mockReturnValue({ trace_id: 'abc', span_id: 'def' });
    const inner = { add: vi.fn() };
    const g = new GaugeInstrument('test.gauge', inner as never);
    g.set(50, { key: 'val' });
    expect(inner.add).toHaveBeenCalledWith(50, { key: 'val' });
  });

  it('counter.add() does not attach exemplars when only trace_id present (no span_id)', () => {
    vi.spyOn(tracing, 'getActiveTraceIds').mockReturnValue({ trace_id: 'abc' });
    const inner = { add: vi.fn() };
    const c = new CounterInstrument('test.counter', inner as never);
    c.add(1, { key: 'val' });
    expect(inner.add).toHaveBeenCalledWith(1, { key: 'val' });
  });

  it('histogram.record() does not attach exemplars when only span_id present (no trace_id)', () => {
    vi.spyOn(tracing, 'getActiveTraceIds').mockReturnValue({ span_id: 'def' });
    const inner = { record: vi.fn() };
    const h = new HistogramInstrument('test.hist', inner as never);
    h.record(42, { route: '/api' });
    expect(inner.record).toHaveBeenCalledWith(42, { route: '/api' });
  });
});

describe('metricsEnabled toggle', () => {
  it('counter.add() does NOT call inner instrument when metricsEnabled is false', () => {
    setupTelemetry({ metricsEnabled: false });
    const inner = { add: vi.fn() };
    const c = new CounterInstrument('test.counter', inner as never);
    c.add(1, { key: 'val' });
    expect(inner.add).not.toHaveBeenCalled();
  });

  it('counter.add() DOES call inner instrument when metricsEnabled is true (default)', () => {
    setupTelemetry({ metricsEnabled: true });
    const inner = { add: vi.fn() };
    const c = new CounterInstrument('test.counter', inner as never);
    c.add(42, { key: 'val' });
    expect(inner.add).toHaveBeenCalledWith(42, { key: 'val' });
  });

  it('gauge.set() does NOT call inner instrument when metricsEnabled is false', () => {
    setupTelemetry({ metricsEnabled: false });
    const inner = { add: vi.fn() };
    const g = new GaugeInstrument('test.gauge', inner as never);
    g.set(50);
    expect(inner.add).not.toHaveBeenCalled();
  });

  it('gauge.add() does NOT call inner instrument when metricsEnabled is false', () => {
    setupTelemetry({ metricsEnabled: false });
    const inner = { add: vi.fn() };
    const g = new GaugeInstrument('test.gauge', inner as never);
    g.add(10);
    expect(inner.add).not.toHaveBeenCalled();
  });

  it('gauge.set() DOES call inner instrument when metricsEnabled is true', () => {
    setupTelemetry({ metricsEnabled: true });
    const inner = { add: vi.fn() };
    const g = new GaugeInstrument('test.gauge', inner as never);
    g.set(50);
    expect(inner.add).toHaveBeenCalledWith(50, undefined);
  });

  it('histogram.record() does NOT call inner instrument when metricsEnabled is false', () => {
    setupTelemetry({ metricsEnabled: false });
    const inner = { record: vi.fn() };
    const h = new HistogramInstrument('test.hist', inner as never);
    h.record(100);
    expect(inner.record).not.toHaveBeenCalled();
  });

  it('histogram.record() DOES call inner instrument when metricsEnabled is true', () => {
    setupTelemetry({ metricsEnabled: true });
    const inner = { record: vi.fn() };
    const h = new HistogramInstrument('test.hist', inner as never);
    h.record(42, { route: '/api' });
    expect(inner.record).toHaveBeenCalledWith(42, { route: '/api' });
  });
});

describe('.value property — CounterInstrument', () => {
  it('starts at 0', () => {
    const inner = { add: vi.fn() };
    const c = new CounterInstrument('test.counter', inner as never);
    expect(c.value).toBe(0);
  });

  it('accumulates across multiple add() calls', () => {
    const inner = { add: vi.fn() };
    const c = new CounterInstrument('test.counter', inner as never);
    c.add(5);
    c.add(3);
    expect(c.value).toBe(8);
  });

  it('does NOT accumulate when metricsEnabled is false', () => {
    setupTelemetry({ metricsEnabled: false });
    const inner = { add: vi.fn() };
    const c = new CounterInstrument('test.counter', inner as never);
    c.add(5);
    expect(c.value).toBe(0);
  });
});

describe('.value property — GaugeInstrument', () => {
  it('starts at 0', () => {
    const inner = { add: vi.fn() };
    const g = new GaugeInstrument('test.gauge', inner as never);
    expect(g.value).toBe(0);
  });

  it('reflects the most recent set() value', () => {
    const inner = { add: vi.fn() };
    const g = new GaugeInstrument('test.gauge', inner as never);
    g.set(65);
    expect(g.value).toBe(65);
    g.set(80);
    expect(g.value).toBe(80);
  });

  it('accumulates via add()', () => {
    const inner = { add: vi.fn() };
    const g = new GaugeInstrument('test.gauge', inner as never);
    g.add(10);
    g.add(5);
    expect(g.value).toBe(15);
  });

  it('does NOT update when metricsEnabled is false', () => {
    setupTelemetry({ metricsEnabled: false });
    const inner = { add: vi.fn() };
    const g = new GaugeInstrument('test.gauge', inner as never);
    g.set(65);
    expect(g.value).toBe(0);
  });
});

describe('.count and .total properties — HistogramInstrument', () => {
  it('starts at 0 for both count and total', () => {
    const inner = { record: vi.fn() };
    const h = new HistogramInstrument('test.hist', inner as never);
    expect(h.count).toBe(0);
    expect(h.total).toBe(0);
  });

  it('tracks count and total across multiple record() calls', () => {
    const inner = { record: vi.fn() };
    const h = new HistogramInstrument('test.hist', inner as never);
    h.record(10);
    h.record(20);
    expect(h.count).toBe(2);
    expect(h.total).toBe(30);
  });

  it('does NOT update when metricsEnabled is false', () => {
    setupTelemetry({ metricsEnabled: false });
    const inner = { record: vi.fn() };
    const h = new HistogramInstrument('test.hist', inner as never);
    h.record(10);
    expect(h.count).toBe(0);
    expect(h.total).toBe(0);
  });
});

// ─── Mutation-killing tests: backpressure ticket release ────────────────

describe('CounterInstrument — releases backpressure ticket after add()', () => {
  it('releases ticket so subsequent calls succeed under bounded queue', () => {
    setQueuePolicy({ maxMetrics: 1 });
    const inner = { add: vi.fn() };
    const c = new CounterInstrument('test.counter', inner as never);
    // First add should acquire and release the single slot
    c.add(1);
    expect(inner.add).toHaveBeenCalledTimes(1);
    // If release was removed (mutant), this second call would be blocked
    c.add(2);
    expect(inner.add).toHaveBeenCalledTimes(2);
    expect(c.value).toBe(3);
  });
});

describe('GaugeInstrument — releases backpressure ticket after set()', () => {
  it('releases ticket so subsequent set() calls succeed under bounded queue', () => {
    setQueuePolicy({ maxMetrics: 1 });
    const inner = { add: vi.fn() };
    const g = new GaugeInstrument('test.gauge', inner as never);
    g.set(10);
    expect(inner.add).toHaveBeenCalledTimes(1);
    // If release was removed (mutant), this second call would be blocked
    g.set(20);
    expect(inner.add).toHaveBeenCalledTimes(2);
    expect(g.value).toBe(20);
  });

  it('releases ticket so subsequent add() calls succeed under bounded queue', () => {
    setQueuePolicy({ maxMetrics: 1 });
    const inner = { add: vi.fn() };
    const g = new GaugeInstrument('test.gauge', inner as never);
    g.add(5);
    expect(inner.add).toHaveBeenCalledTimes(1);
    // If release was removed (mutant), this second call would be blocked
    g.add(10);
    expect(inner.add).toHaveBeenCalledTimes(2);
    expect(g.value).toBe(15);
  });
});

describe('HistogramInstrument — releases backpressure ticket after record()', () => {
  it('releases ticket so subsequent calls succeed under bounded queue', () => {
    setQueuePolicy({ maxMetrics: 1 });
    const inner = { record: vi.fn() };
    const h = new HistogramInstrument('test.hist', inner as never);
    h.record(10);
    expect(inner.record).toHaveBeenCalledTimes(1);
    // If release was removed (mutant), this second call would be blocked
    h.record(20);
    expect(inner.record).toHaveBeenCalledTimes(2);
    expect(h.total).toBe(30);
    expect(h.count).toBe(2);
  });
});

// ─── Mutation-killing tests: value accumulation ─────────────────────────

describe('CounterInstrument — _value += value accumulation', () => {
  it('value property reflects accumulated adds', () => {
    const inner = { add: vi.fn() };
    const c = new CounterInstrument('test.counter', inner as never);
    c.add(7);
    expect(c.value).toBe(7);
    c.add(3);
    expect(c.value).toBe(10);
    // If _value += value were removed, value would stay 0
  });
});

describe('GaugeInstrument — _lastValue += value accumulation in add()', () => {
  it('value property reflects accumulated adds', () => {
    const inner = { add: vi.fn() };
    const g = new GaugeInstrument('test.gauge', inner as never);
    g.add(4);
    expect(g.value).toBe(4);
    g.add(6);
    expect(g.value).toBe(10);
    // If _lastValue += value were removed, value would stay 0
  });
});

describe('HistogramInstrument — _total += value accumulation', () => {
  it('total property reflects accumulated records', () => {
    const inner = { record: vi.fn() };
    const h = new HistogramInstrument('test.hist', inner as never);
    h.record(15);
    expect(h.total).toBe(15);
    h.record(25);
    expect(h.total).toBe(40);
    // If _total += value were removed, total would stay 0
  });
});

// ─── Mutation-killing tests: tryAcquire signal string ───────────────────

describe('CounterInstrument — tryAcquire uses "metrics" signal', () => {
  it('is gated by metrics backpressure, not logs or traces', () => {
    // Set metrics to bounded, logs/traces unbounded
    setQueuePolicy({ maxMetrics: 1, maxLogs: 0, maxTraces: 0 });
    const inner = { add: vi.fn() };
    const c = new CounterInstrument('test.counter', inner as never);
    // Fill the metrics slot externally
    const ticket = tryAcquire('metrics');
    expect(ticket).not.toBeNull();
    // Counter should be blocked because metrics queue is full
    c.add(1);
    expect(inner.add).not.toHaveBeenCalled();
    // If the string were mutated to 'logs' or 'traces', it would NOT be blocked
  });
});

describe('GaugeInstrument — tryAcquire uses "metrics" signal for both add and set', () => {
  it('add() is gated by metrics backpressure', () => {
    setQueuePolicy({ maxMetrics: 1, maxLogs: 0, maxTraces: 0 });
    const inner = { add: vi.fn() };
    const g = new GaugeInstrument('test.gauge', inner as never);
    const ticket = tryAcquire('metrics');
    expect(ticket).not.toBeNull();
    g.add(1);
    expect(inner.add).not.toHaveBeenCalled();
  });

  it('set() is gated by metrics backpressure', () => {
    setQueuePolicy({ maxMetrics: 1, maxLogs: 0, maxTraces: 0 });
    const inner = { add: vi.fn() };
    const g = new GaugeInstrument('test.gauge', inner as never);
    const ticket = tryAcquire('metrics');
    expect(ticket).not.toBeNull();
    g.set(50);
    expect(inner.add).not.toHaveBeenCalled();
  });
});

describe('HistogramInstrument — tryAcquire uses "metrics" signal', () => {
  it('is gated by metrics backpressure, not logs or traces', () => {
    setQueuePolicy({ maxMetrics: 1, maxLogs: 0, maxTraces: 0 });
    const inner = { record: vi.fn() };
    const h = new HistogramInstrument('test.hist', inner as never);
    const ticket = tryAcquire('metrics');
    expect(ticket).not.toBeNull();
    h.record(100);
    expect(inner.record).not.toHaveBeenCalled();
  });
});

// ─── Mutation-killing: GaugeInstrument.set JSON.stringify key ───────────

describe('GaugeInstrument — set() attribute key via JSON.stringify', () => {
  it('tracks different attribute sets independently via JSON key', () => {
    const inner = { add: vi.fn() };
    const g = new GaugeInstrument('test.gauge', inner as never);
    g.set(10, { resource: 'cpu' });
    g.set(20, { resource: 'mem' });
    // Now set cpu again — delta should be based on previous cpu value (10), not mem (20)
    g.set(15, { resource: 'cpu' });
    // If JSON.stringify were mutated (e.g. to ''), all attributes would share one key
    // and delta would be 15 - 20 = -5 instead of 15 - 10 = 5
    expect(inner.add).toHaveBeenLastCalledWith(5, { resource: 'cpu' });
  });

  it('set() without attributes uses empty string key', () => {
    const inner = { add: vi.fn() };
    const g = new GaugeInstrument('test.gauge', inner as never);
    g.set(10);
    g.set(25);
    // delta = 25 - 10 = 15
    expect(inner.add).toHaveBeenLastCalledWith(15, undefined);
  });
});

// ─── Mutation-killing: partial trace context (only trace_id OR span_id) ─

describe('exemplar — partial trace context', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('counter does not enrich when only trace_id is present', () => {
    vi.spyOn(tracing, 'getActiveTraceIds').mockReturnValue({ trace_id: 'abc' });
    const inner = { add: vi.fn() };
    const c = new CounterInstrument('test.counter', inner as never);
    c.add(1, { key: 'val' });
    // Should pass original attributes, not enriched (both trace_id AND span_id required)
    expect(inner.add).toHaveBeenCalledWith(1, { key: 'val' });
  });

  it('counter does not enrich when only span_id is present', () => {
    vi.spyOn(tracing, 'getActiveTraceIds').mockReturnValue({ span_id: 'def' });
    const inner = { add: vi.fn() };
    const c = new CounterInstrument('test.counter', inner as never);
    c.add(1, { key: 'val' });
    expect(inner.add).toHaveBeenCalledWith(1, { key: 'val' });
  });

  it('histogram does not enrich when only trace_id is present', () => {
    vi.spyOn(tracing, 'getActiveTraceIds').mockReturnValue({ trace_id: 'abc' });
    const inner = { record: vi.fn() };
    const h = new HistogramInstrument('test.hist', inner as never);
    h.record(42, { route: '/api' });
    expect(inner.record).toHaveBeenCalledWith(42, { route: '/api' });
  });
});
