// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Gate tests for metrics instruments: metricsEmitted health counter,
 * consent gate, and GaugeInstrument canonical key (order-insensitive attributes).
 * Core instrument behaviour and mutation-kill tests live in metrics.instruments.test.ts.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CounterInstrument, GaugeInstrument, HistogramInstrument } from '../src/metrics';
import { _resetHealthForTests, getHealthSnapshot } from '../src/health';
import { setSamplingPolicy, _resetSamplingForTests } from '../src/sampling';
import { _resetBackpressureForTests } from '../src/backpressure';
import { setupTelemetry, _resetConfig } from '../src/config';
import { setConsentLevel, resetConsentForTests } from '../src/consent';

describe('metrics instruments — metricsEmitted health counter', () => {
  beforeEach(() => {
    _resetHealthForTests();
    _resetSamplingForTests();
    _resetBackpressureForTests();
    _resetConfig();
    setupTelemetry({ metricsEnabled: true });
  });
  afterEach(() => {
    _resetHealthForTests();
    _resetSamplingForTests();
    _resetBackpressureForTests();
    _resetConfig();
  });

  it('CounterInstrument.add() increments metricsEmitted by 1', () => {
    const inner = { add: vi.fn() };
    const c = new CounterInstrument('test.counter', inner as never);
    expect(getHealthSnapshot().metricsEmitted).toBe(0);
    c.add(1);
    expect(getHealthSnapshot().metricsEmitted).toBe(1);
  });

  it('CounterInstrument.add() does NOT increment metricsEmitted when sampling drops the event', () => {
    setSamplingPolicy('metrics', { defaultRate: 0.0 });
    const inner = { add: vi.fn() };
    const c = new CounterInstrument('test.counter', inner as never);
    c.add(1);
    expect(getHealthSnapshot().metricsEmitted).toBe(0);
  });

  it('GaugeInstrument.add() increments metricsEmitted by 1', () => {
    const inner = { add: vi.fn() };
    const g = new GaugeInstrument('test.gauge', inner as never);
    g.add(5);
    expect(getHealthSnapshot().metricsEmitted).toBe(1);
  });

  it('GaugeInstrument.set() increments metricsEmitted by 1', () => {
    const inner = { add: vi.fn() };
    const g = new GaugeInstrument('test.gauge', inner as never);
    g.set(10);
    expect(getHealthSnapshot().metricsEmitted).toBe(1);
  });

  it('HistogramInstrument.record() increments metricsEmitted by 1', () => {
    const inner = { record: vi.fn() };
    const h = new HistogramInstrument('test.hist', inner as never);
    h.record(42);
    expect(getHealthSnapshot().metricsEmitted).toBe(1);
  });

  it('each call increments metricsEmitted independently', () => {
    const counterInner = { add: vi.fn() };
    const c = new CounterInstrument('test.counter', counterInner as never);
    const histInner = { record: vi.fn() };
    const h = new HistogramInstrument('test.hist', histInner as never);
    c.add(1);
    c.add(2);
    h.record(99);
    expect(getHealthSnapshot().metricsEmitted).toBe(3);
  });
});

describe('metrics instruments — consent gate', () => {
  beforeEach(() => {
    resetConsentForTests();
    _resetHealthForTests();
  });

  afterEach(() => {
    resetConsentForTests();
  });

  it('CounterInstrument.add() drops under ConsentNone', () => {
    setConsentLevel('NONE');
    const inner = { add: vi.fn() };
    const c = new CounterInstrument('test.consent.counter', inner as never);
    const before = getHealthSnapshot().metricsEmitted;
    c.add(1);
    expect(getHealthSnapshot().metricsEmitted).toBe(before);
    expect(inner.add).not.toHaveBeenCalled();
  });

  it('GaugeInstrument.add() drops under ConsentNone', () => {
    setConsentLevel('NONE');
    const inner = { add: vi.fn() };
    const g = new GaugeInstrument('test.consent.gauge', inner as never);
    const before = getHealthSnapshot().metricsEmitted;
    g.add(1);
    expect(getHealthSnapshot().metricsEmitted).toBe(before);
    expect(inner.add).not.toHaveBeenCalled();
  });

  it('GaugeInstrument.set() drops under ConsentNone', () => {
    setConsentLevel('NONE');
    const inner = { add: vi.fn() };
    const g = new GaugeInstrument('test.consent.gauge.set', inner as never);
    const before = getHealthSnapshot().metricsEmitted;
    g.set(3.14);
    expect(getHealthSnapshot().metricsEmitted).toBe(before);
    expect(inner.add).not.toHaveBeenCalled();
  });

  it('HistogramInstrument.record() drops under ConsentNone', () => {
    setConsentLevel('NONE');
    const inner = { record: vi.fn() };
    const h = new HistogramInstrument('test.consent.histogram', inner as never);
    const before = getHealthSnapshot().metricsEmitted;
    h.record(42);
    expect(getHealthSnapshot().metricsEmitted).toBe(before);
    expect(inner.record).not.toHaveBeenCalled();
  });
});

// ─── Bug fix: GaugeInstrument.set attribute key order-insensitivity ──────

describe('GaugeInstrument — set() attribute key is order-independent (canonical key fix)', () => {
  it('{a:1, b:2} then {b:2, a:1} treated as same series — second call emits delta not full value', () => {
    const inner = { add: vi.fn() };
    const g = new GaugeInstrument('test.gauge.canon', inner as never);
    g.set(5, { a: 1, b: 2 });
    expect(inner.add).toHaveBeenLastCalledWith(5, { a: 1, b: 2 });
    // Same attributes in different insertion order — must be treated as same series.
    // Delta = 7 - 5 = 2, NOT 7 (which would happen if key is order-sensitive).
    g.set(7, { b: 2, a: 1 });
    expect(inner.add).toHaveBeenLastCalledWith(2, { b: 2, a: 1 });
  });

  it('{a:1, b:2} and {a:1, b:3} are still different series (different values)', () => {
    const inner = { add: vi.fn() };
    const g = new GaugeInstrument('test.gauge.canon2', inner as never);
    g.set(10, { a: 1, b: 2 });
    g.set(20, { a: 1, b: 3 });
    // Different values → different series; second call is a fresh set of 20 (delta = 20 - 0 = 20)
    expect(inner.add).toHaveBeenLastCalledWith(20, { a: 1, b: 3 });
    // First series still tracks its own value independently
    g.set(15, { a: 1, b: 2 });
    expect(inner.add).toHaveBeenLastCalledWith(5, { a: 1, b: 2 });
  });

  it('set() with no attributes still uses stable empty-string key', () => {
    const inner = { add: vi.fn() };
    const g = new GaugeInstrument('test.gauge.noattr', inner as never);
    g.set(100);
    g.set(150);
    // delta = 150 - 100 = 50
    expect(inner.add).toHaveBeenLastCalledWith(50, undefined);
  });
});
