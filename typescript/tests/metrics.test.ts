// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';
import { counter, gauge, getMeter, histogram } from '../src/metrics';

describe('metrics instruments', () => {
  it('counter() returns a callable instrument', () => {
    const c = counter('test.requests', { unit: 'request' });
    expect(c).toBeDefined();
    expect(typeof c.add).toBe('function');
  });

  it('counter.add() does not throw without SDK', () => {
    const c = counter('test.requests2');
    expect(() => c.add(1, { path: '/api' })).not.toThrow();
    expect(() => c.add(5)).not.toThrow();
  });

  it('gauge() returns a callable up-down counter', () => {
    const g = gauge('test.active_connections', { unit: 'connection' });
    expect(g).toBeDefined();
    expect(typeof g.add).toBe('function');
  });

  it('gauge.add() handles negative values', () => {
    const g = gauge('test.queue_depth');
    expect(() => g.add(10)).not.toThrow();
    expect(() => g.add(-3, { queue: 'main' })).not.toThrow();
  });

  it('histogram() returns a callable instrument', () => {
    const h = histogram('test.latency_ms', { unit: 'ms' });
    expect(h).toBeDefined();
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
