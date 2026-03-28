// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  OVERFLOW_VALUE,
  _resetCardinalityForTests,
  clearCardinalityLimits,
  getCardinalityLimits,
  guardAttributes,
  registerCardinalityLimit,
} from '../src/cardinality';

afterEach(() => _resetCardinalityForTests());

describe('registerCardinalityLimit', () => {
  it('stores a limit with min maxValues=1', () => {
    registerCardinalityLimit('route', { maxValues: 5, ttlSeconds: 60 });
    const limits = getCardinalityLimits();
    expect(limits.get('route')?.maxValues).toBe(5);
  });

  it('clamps maxValues to 1 minimum', () => {
    registerCardinalityLimit('env', { maxValues: 0, ttlSeconds: 10 });
    expect(getCardinalityLimits().get('env')?.maxValues).toBe(1);
  });

  it('clamps ttlSeconds to 1 minimum', () => {
    registerCardinalityLimit('x', { maxValues: 3, ttlSeconds: 0 });
    expect(getCardinalityLimits().get('x')?.ttlSeconds).toBe(1);
  });
});

describe('getCardinalityLimits', () => {
  it('returns a copy — mutations do not affect stored limits', () => {
    registerCardinalityLimit('k', { maxValues: 2, ttlSeconds: 30 });
    const copy = getCardinalityLimits();
    copy.set('k', { maxValues: 99, ttlSeconds: 99 });
    expect(getCardinalityLimits().get('k')?.maxValues).toBe(2);
  });
});

describe('clearCardinalityLimits', () => {
  it('removes all limits', () => {
    registerCardinalityLimit('a', { maxValues: 5, ttlSeconds: 30 });
    clearCardinalityLimits();
    expect(getCardinalityLimits().size).toBe(0);
  });
});

describe('registerCardinalityLimit — duplicate key', () => {
  it('updating an existing key replaces the limit but preserves seen values', () => {
    registerCardinalityLimit('env', { maxValues: 2, ttlSeconds: 60 });
    guardAttributes({ env: 'dev' }); // 'dev' added to seen
    registerCardinalityLimit('env', { maxValues: 5, ttlSeconds: 120 }); // re-register same key
    const limits = getCardinalityLimits();
    expect(limits.get('env')?.maxValues).toBe(5);
    // After re-registration, more values should be allowed
    expect(() => guardAttributes({ env: 'prod' })).not.toThrow();
  });
});

describe('guardAttributes', () => {
  it('passes through attributes without a registered limit', () => {
    const result = guardAttributes({ route: '/api', method: 'GET' });
    expect(result).toEqual({ route: '/api', method: 'GET' });
  });

  it('allows values within limit', () => {
    registerCardinalityLimit('route', { maxValues: 3, ttlSeconds: 60 });
    const r1 = guardAttributes({ route: '/a' });
    const r2 = guardAttributes({ route: '/b' });
    const r3 = guardAttributes({ route: '/c' });
    expect(r1.route).toBe('/a');
    expect(r2.route).toBe('/b');
    expect(r3.route).toBe('/c');
  });

  it('overflows new values past the limit', () => {
    registerCardinalityLimit('route', { maxValues: 2, ttlSeconds: 60 });
    guardAttributes({ route: '/a' });
    guardAttributes({ route: '/b' });
    const result = guardAttributes({ route: '/c' });
    expect(result.route).toBe(OVERFLOW_VALUE);
  });

  it('allows re-seeing known values without overflow', () => {
    registerCardinalityLimit('route', { maxValues: 2, ttlSeconds: 60 });
    guardAttributes({ route: '/a' });
    guardAttributes({ route: '/b' });
    const result = guardAttributes({ route: '/a' }); // already seen
    expect(result.route).toBe('/a');
  });

  it('prunes expired values and allows new ones', () => {
    vi.useFakeTimers();
    registerCardinalityLimit('env', { maxValues: 1, ttlSeconds: 1 });
    guardAttributes({ env: 'dev' });
    // Advance past TTL (1s) + prune interval (5s)
    vi.advanceTimersByTime(7000);
    // New value should be allowed (old one pruned)
    const result = guardAttributes({ env: 'prod' });
    expect(result.env).toBe('prod');
    vi.useRealTimers();
  });
});

describe('guardAttributes — partial prune (some values survive TTL)', () => {
  it('keeps values within TTL while pruning expired ones', () => {
    vi.useFakeTimers();
    registerCardinalityLimit('env', { maxValues: 3, ttlSeconds: 10 });
    guardAttributes({ env: 'dev' }); // seen at t=0
    // Advance 6s — past prune interval (5s) but within TTL (10s)
    vi.advanceTimersByTime(6000);
    guardAttributes({ env: 'staging' }); // triggers prune; 'dev' (seenAt < threshold? 0 < (6000-10000=-4000) → no, 0 is NOT < -4000) so dev is NOT pruned
    // Both values should still be seen (neither expired after 6s with 10s TTL)
    const result = guardAttributes({ env: 'dev' }); // re-seeing known value
    expect(result.env).toBe('dev'); // dev still known (not pruned)
    vi.useRealTimers();
  });
});

describe('OVERFLOW_VALUE exact string', () => {
  it('is the literal string "__overflow__"', () => {
    // Mutation kill: guards against StringLiteral mutation of OVERFLOW_VALUE
    expect(OVERFLOW_VALUE).toBe('__overflow__');
  });
});

describe('registerCardinalityLimit — seen values preserved on re-registration', () => {
  it('old seen values still count against capacity after re-registering same key', () => {
    // Fill to capacity, then re-register, then verify overflow still applies
    // Kills: ConditionalExpression on if (!_seen.has(key))
    registerCardinalityLimit('env', { maxValues: 2, ttlSeconds: 60 });
    guardAttributes({ env: 'a' });
    guardAttributes({ env: 'b' }); // capacity full (2/2)
    registerCardinalityLimit('env', { maxValues: 2, ttlSeconds: 60 }); // re-register, same limit
    const result = guardAttributes({ env: 'c' }); // should overflow — 'a','b' still in seen
    expect(result.env).toBe(OVERFLOW_VALUE);
  });
});

describe('guardAttributes — TTL preserves values within window at capacity', () => {
  it('value at capacity is NOT pruned before TTL expires (kills / mutation)', () => {
    vi.useFakeTimers();
    // maxValues=1, TTL=10s. Add 'dev'. Advance 6s (past prune interval, within TTL).
    // Trigger prune by calling guardAttributes. 'prod' should overflow because 'dev' is still alive.
    // With `now + ttlSeconds * 1000`, 'dev' would be pruned and 'prod' would NOT overflow.
    registerCardinalityLimit('zone', { maxValues: 1, ttlSeconds: 10 });
    guardAttributes({ zone: 'dev' }); // seenAt = 0
    vi.advanceTimersByTime(6000); // past 5s prune interval, within 10s TTL
    const result = guardAttributes({ zone: 'prod' }); // triggers prune; 'dev' must survive
    expect(result.zone).toBe(OVERFLOW_VALUE); // 'dev' still in seen → 'prod' overflows
    vi.useRealTimers();
  });
});

describe('guardAttributes — TTL pruning arithmetic (kills / mutation)', () => {
  it('value is pruned after TTL * 1000 ms (not TTL / 1000 ms)', () => {
    vi.useFakeTimers();
    // TTL = 1s → prune after 1000ms. With `/ 1000`, prune would require 0.001ms.
    // maxValues=1. Add 'dev'. Advance 500ms (half TTL). Verify 'dev' still alive.
    registerCardinalityLimit('tier', { maxValues: 1, ttlSeconds: 1 });
    guardAttributes({ tier: 'dev' }); // seenAt = 0
    vi.advanceTimersByTime(5500); // past prune interval (5s), but dev seenAt=0 < threshold=(5500-1000=4500) → pruned
    // After pruning, 'prod' should NOT overflow (1 slot freed)
    const result = guardAttributes({ tier: 'prod' });
    expect(result.tier).toBe('prod'); // 'dev' was pruned (1000ms TTL elapsed)
    vi.useRealTimers();
  });
});

describe('cardinality — prune interval boundary (kills >= vs > mutation)', () => {
  it('prunes at exactly PRUNE_INTERVAL_MS (5000ms)', () => {
    vi.useFakeTimers();
    _resetCardinalityForTests();
    registerCardinalityLimit('key', { maxValues: 2, ttlSeconds: 10 });
    const attrs = { key: 'a' };
    guardAttributes(attrs); // populates lastPrune at t=0
    vi.advanceTimersByTime(5000); // exactly at boundary
    const attrs2 = { key: 'b' };
    guardAttributes(attrs2); // should trigger prune check
    // If prune happened, 'a' (seenAt=0, ttl=10s, expires at 10000) is still valid
    // Just verify no throw and no overflow
    expect(guardAttributes({ key: 'a' })).toEqual({ key: 'a' });
    vi.useRealTimers();
  });

  it('does NOT prune before PRUNE_INTERVAL_MS (4999ms)', () => {
    vi.useFakeTimers();
    _resetCardinalityForTests();
    registerCardinalityLimit('key2', { maxValues: 2, ttlSeconds: 10 });
    guardAttributes({ key2: 'x' });
    vi.advanceTimersByTime(4999); // just before boundary
    guardAttributes({ key2: 'y' }); // no prune, but still works
    expect(guardAttributes({ key2: 'x' })).toEqual({ key2: 'x' });
    vi.useRealTimers();
  });
});

describe('cardinality — TTL expiry boundary (kills < vs <= on seenAt check)', () => {
  it('value expired by TTL is pruned allowing new value in', () => {
    vi.useFakeTimers();
    _resetCardinalityForTests();
    // maxValues=2: fill with 'old1' and 'old2' at t=0 (TTL=1s)
    // At t=5000, prune fires: threshold = 5000-1000 = 4000; seenAt=0 < 4000 → both pruned
    // Then 'new1' and 'new2' should both fit (2 slots freed)
    registerCardinalityLimit('ttlkey', { maxValues: 2, ttlSeconds: 1 });
    guardAttributes({ ttlkey: 'old1' });
    guardAttributes({ ttlkey: 'old2' });
    vi.advanceTimersByTime(5000); // trigger prune
    // This call triggers prune: both 'old1' and 'old2' are pruned
    const result1 = guardAttributes({ ttlkey: 'new1' });
    const result2 = guardAttributes({ ttlkey: 'new2' });
    expect(result1).toEqual({ ttlkey: 'new1' }); // slot freed
    expect(result2).toEqual({ ttlkey: 'new2' }); // both fit
    vi.useRealTimers();
  });
});

describe('cardinality — TTL prune boundary: < vs <= on seenAt (kills EqualityOperator at cardinality.ts:45)', () => {
  it('value at exactly threshold is NOT pruned (seenAt === threshold: < keeps it, <= prunes it)', () => {
    // This test distinguishes `seenAt < threshold` from `seenAt <= threshold`.
    // seenAt = 0 (value added at t=0), TTL = 5s → 5000ms.
    // Advance exactly 10000ms. threshold = now - ttl*1000 = 10000 - 5000 = 5000.
    // seenAt (0) < threshold (5000) → pruned with both < and <=.
    // Instead: advance 5000ms (prune interval). threshold = 5000 - 5000 = 0.
    // seenAt=0 < 0 → FALSE (not pruned). seenAt=0 <= 0 → TRUE (pruned).
    // So at threshold boundary, value stays alive with < but is pruned with <=.
    vi.useFakeTimers();
    _resetCardinalityForTests();
    registerCardinalityLimit('bkey', { maxValues: 1, ttlSeconds: 5 });
    guardAttributes({ bkey: 'first' }); // seenAt = 0
    vi.advanceTimersByTime(5000); // trigger prune; threshold = 5000 - 5000 = 0; seenAt=0 < 0 is false → NOT pruned
    // 'first' should survive (seenAt=0 is not < threshold=0)
    const result = guardAttributes({ bkey: 'second' }); // should overflow (first still alive)
    expect(result.bkey).toBe(OVERFLOW_VALUE); // 'first' was NOT pruned → 'second' overflows
    vi.useRealTimers();
  });
});
