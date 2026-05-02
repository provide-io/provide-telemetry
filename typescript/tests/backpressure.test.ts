// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import {
  _resetBackpressureForTests,
  getQueuePolicy,
  release,
  setQueuePolicy,
  tryAcquire,
} from '../src/backpressure';
import { _resetHealthForTests, getHealthSnapshot } from '../src/health';

beforeEach(() => {
  _resetBackpressureForTests();
  _resetHealthForTests();
});
afterEach(() => {
  _resetBackpressureForTests();
  _resetHealthForTests();
});

describe('getQueuePolicy / setQueuePolicy', () => {
  it('defaults to unlimited (0)', () => {
    const p = getQueuePolicy();
    expect(p.maxLogs).toBe(0);
    expect(p.maxTraces).toBe(0);
    expect(p.maxMetrics).toBe(0);
  });

  it('updates policy', () => {
    setQueuePolicy({ maxLogs: 10 });
    expect(getQueuePolicy().maxLogs).toBe(10);
  });

  it('returns a copy (mutations do not affect policy)', () => {
    const p = getQueuePolicy();
    p.maxLogs = 99;
    expect(getQueuePolicy().maxLogs).toBe(0);
  });

  it('preserves in-flight occupancy when policy updates', () => {
    setQueuePolicy({ maxLogs: 2 });
    const first = tryAcquire('logs');
    expect(first).not.toBeNull();
    setQueuePolicy({ maxLogs: 3 });
    expect(tryAcquire('logs')).not.toBeNull();
    expect(tryAcquire('logs')).not.toBeNull();
    expect(tryAcquire('logs')).toBeNull();
  });
});

describe('tryAcquire', () => {
  it('returns token=0 when queue is unlimited (maxLogs=0)', () => {
    const ticket = tryAcquire('logs');
    expect(ticket).not.toBeNull();
    if (ticket === null) throw new Error('expected ticket');
    expect(ticket.token).toBe(0);
    expect(ticket.signal).toBe('logs');
  });

  it('acquires a token when capacity available', () => {
    setQueuePolicy({ maxLogs: 2 });
    const t1 = tryAcquire('logs');
    const t2 = tryAcquire('logs');
    expect(t1).not.toBeNull();
    expect(t2).not.toBeNull();
    if (t1 === null || t2 === null) throw new Error('expected tickets');
    expect(t1.token).toBeGreaterThan(0);
    expect(t2.token).toBeGreaterThan(0);
    expect(t1.token).not.toBe(t2.token);
  });

  it('returns null when at capacity', () => {
    setQueuePolicy({ maxLogs: 1 });
    const t1 = tryAcquire('logs');
    expect(t1).not.toBeNull();
    const t2 = tryAcquire('logs');
    expect(t2).toBeNull();
  });

  it('works for traces and metrics', () => {
    setQueuePolicy({ maxTraces: 1, maxMetrics: 1 });
    expect(tryAcquire('traces')).not.toBeNull();
    expect(tryAcquire('traces')).toBeNull();
    expect(tryAcquire('metrics')).not.toBeNull();
    expect(tryAcquire('metrics')).toBeNull();
  });
});

describe('release', () => {
  it('releases a token, allowing a new acquisition', () => {
    setQueuePolicy({ maxLogs: 1 });
    const t1 = tryAcquire('logs');
    expect(t1).not.toBeNull();
    if (t1 === null) throw new Error('expected ticket');
    expect(tryAcquire('logs')).toBeNull();
    release(t1);
    const t2 = tryAcquire('logs');
    expect(t2).not.toBeNull();
  });

  it('silently ignores token=0 (unlimited queue)', () => {
    const ticket = tryAcquire('logs'); // token=0
    if (ticket === null) throw new Error('expected ticket');
    expect(() => release(ticket)).not.toThrow();
  });

  it('silently ignores releasing an already-released token', () => {
    setQueuePolicy({ maxLogs: 2 });
    const t = tryAcquire('logs');
    if (t === null) throw new Error('expected ticket');
    release(t);
    expect(() => release(t)).not.toThrow();
  });
});

describe('tryAcquire — signal independence', () => {
  it('maxTraces limits only traces, not logs', () => {
    setQueuePolicy({ maxLogs: 5, maxTraces: 1 });
    // Exhaust traces capacity
    const t1 = tryAcquire('traces');
    expect(t1).not.toBeNull();
    const t2 = tryAcquire('traces');
    expect(t2).toBeNull(); // at capacity
    // Logs should still be available
    const l1 = tryAcquire('logs');
    expect(l1).not.toBeNull();
    const l2 = tryAcquire('logs');
    expect(l2).not.toBeNull();
  });

  it('maxLogs limits only logs, not metrics', () => {
    setQueuePolicy({ maxLogs: 1, maxMetrics: 3 });
    // Exhaust logs
    tryAcquire('logs');
    expect(tryAcquire('logs')).toBeNull();
    // Metrics still available
    expect(tryAcquire('metrics')).not.toBeNull();
    expect(tryAcquire('metrics')).not.toBeNull();
  });

  it('each signal has its own independent capacity counter', () => {
    setQueuePolicy({ maxLogs: 2, maxTraces: 1, maxMetrics: 3 });
    // Fill traces to capacity
    expect(tryAcquire('traces')).not.toBeNull();
    expect(tryAcquire('traces')).toBeNull();
    // logs and metrics are unaffected
    expect(tryAcquire('logs')).not.toBeNull();
    expect(tryAcquire('metrics')).not.toBeNull();
    expect(tryAcquire('metrics')).not.toBeNull();
    expect(tryAcquire('metrics')).not.toBeNull();
    expect(tryAcquire('metrics')).toBeNull();
  });
});

describe('DEFAULT_POLICY — static-init mutation kill', () => {
  it('getQueuePolicy returns maxLogs=0 after reset (kills ObjectLiteral on DEFAULT_POLICY)', () => {
    setQueuePolicy({ maxLogs: 99 });
    _resetBackpressureForTests();
    expect(getQueuePolicy().maxLogs).toBe(0);
  });

  it('getQueuePolicy returns maxTraces=0 after reset', () => {
    setQueuePolicy({ maxTraces: 99 });
    _resetBackpressureForTests();
    expect(getQueuePolicy().maxTraces).toBe(0);
  });

  it('getQueuePolicy returns maxMetrics=0 after reset', () => {
    setQueuePolicy({ maxMetrics: 99 });
    _resetBackpressureForTests();
    expect(getQueuePolicy().maxMetrics).toBe(0);
  });

  it('reset policy object has exactly three zero fields', () => {
    setQueuePolicy({ maxLogs: 1, maxTraces: 2, maxMetrics: 3 });
    _resetBackpressureForTests();
    expect(getQueuePolicy()).toEqual({ maxLogs: 0, maxTraces: 0, maxMetrics: 0 });
  });
});

describe('tryAcquire — health drop counter on overflow', () => {
  it('increments logsDropped when logs queue is full', () => {
    setQueuePolicy({ maxLogs: 1 });
    tryAcquire('logs');
    expect(tryAcquire('logs')).toBeNull();
    expect(getHealthSnapshot().logsDropped).toBe(1);
  });

  it('increments tracesDropped when traces queue is full', () => {
    setQueuePolicy({ maxTraces: 1 });
    tryAcquire('traces');
    expect(tryAcquire('traces')).toBeNull();
    expect(getHealthSnapshot().tracesDropped).toBe(1);
  });

  it('increments metricsDropped when metrics queue is full', () => {
    setQueuePolicy({ maxMetrics: 1 });
    tryAcquire('metrics');
    expect(tryAcquire('metrics')).toBeNull();
    expect(getHealthSnapshot().metricsDropped).toBe(1);
  });

  it('increments drop counter on each overflow attempt', () => {
    setQueuePolicy({ maxLogs: 1 });
    tryAcquire('logs');
    tryAcquire('logs');
    tryAcquire('logs');
    expect(getHealthSnapshot().logsDropped).toBe(2);
  });
});
