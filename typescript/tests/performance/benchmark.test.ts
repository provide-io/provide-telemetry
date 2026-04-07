// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// @vitest-environment node

/**
 * In-process performance smoke tests for hot-path telemetry operations.
 *
 * These are NOT hard benchmarks — they verify that hot-path operations complete
 * within a generous budget and detect catastrophic regressions (e.g. accidental
 * O(n^2) loops or lock contention).
 */

import { performance } from 'node:perf_hooks';

import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import {
  tryAcquire,
  release,
  setQueuePolicy,
  _resetBackpressureForTests,
} from '../../src/backpressure';
import { _resetConfig, setupTelemetry } from '../../src/config';
import { getHealthSnapshot, _resetHealthForTests } from '../../src/health';
import { _resetRootLogger } from '../../src/logger';
import { counter, gauge, histogram } from '../../src/metrics';
import { sanitize, resetPiiRulesForTests } from '../../src/pii';
import { setSamplingPolicy, shouldSample, _resetSamplingForTests } from '../../src/sampling';
import { eventName } from '../../src/schema';

const ITERATIONS = 50_000;
// Budget: generous thresholds (10x slower than typical) to avoid CI flakes.
const MAX_NS_PER_OP = 25_000;

function nsPerOp(fn: () => void, iterations = ITERATIONS): number {
  // Warmup
  for (let i = 0; i < 1000; i++) fn();

  const start = performance.now();
  for (let i = 0; i < iterations; i++) fn();
  const elapsed = performance.now() - start;
  return (elapsed * 1_000_000) / iterations;
}

describe('performance: hot-path operations', () => {
  beforeEach(() => {
    _resetConfig();
    _resetRootLogger();
    _resetSamplingForTests();
    _resetBackpressureForTests();
    _resetHealthForTests();
    resetPiiRulesForTests();
    setupTelemetry({ serviceName: 'perf-test', logLevel: 'silent' });
  });

  afterEach(() => {
    _resetConfig();
    _resetRootLogger();
    _resetSamplingForTests();
    _resetBackpressureForTests();
    _resetHealthForTests();
    resetPiiRulesForTests();
  });

  describe('eventName', () => {
    it('3 segments completes within budget', () => {
      const ns = nsPerOp(() => eventName('auth', 'login', 'success'));
      expect(ns).toBeLessThan(MAX_NS_PER_OP);
    });

    it('5 segments completes within budget', () => {
      const ns = nsPerOp(() =>
        eventName('payment', 'subscription', 'renewal', 'charge', 'success'),
      );
      expect(ns).toBeLessThan(MAX_NS_PER_OP);
    });
  });

  describe('shouldSample', () => {
    it('rate=1.0 completes within budget', () => {
      setSamplingPolicy('logs', { defaultRate: 1.0 });
      const ns = nsPerOp(() => shouldSample('logs'));
      expect(ns).toBeLessThan(MAX_NS_PER_OP);
    });

    it('rate=0.0 completes within budget', () => {
      setSamplingPolicy('logs', { defaultRate: 0.0 });
      const ns = nsPerOp(() => shouldSample('logs'));
      expect(ns).toBeLessThan(MAX_NS_PER_OP);
    });

    it('with key override completes within budget', () => {
      setSamplingPolicy('logs', { defaultRate: 0.5, overrides: { 'auth.login': 1.0 } });
      const ns = nsPerOp(() => shouldSample('logs', 'auth.login'));
      expect(ns).toBeLessThan(MAX_NS_PER_OP);
    });
  });

  describe('sanitize (PII)', () => {
    it('small payload completes within budget', () => {
      const ns = nsPerOp(() => {
        const payload: Record<string, unknown> = {
          password: 'secret', // pragma: allowlist secret
          token: 'abc',
          request_id: 'r1',
        };
        sanitize(payload);
      });
      expect(ns).toBeLessThan(MAX_NS_PER_OP);
    });

    it('large payload completes within budget', () => {
      const ns = nsPerOp(() => {
        const payload: Record<string, unknown> = {};
        for (let i = 0; i < 50; i++) payload[`field_${i}`] = `value_${i}`;
        payload['password'] = 'secret'; // pragma: allowlist secret
        sanitize(payload);
      }, 10_000);
      expect(ns).toBeLessThan(MAX_NS_PER_OP * 20);
    });
  });

  describe('backpressure', () => {
    it('tryAcquire+release (unlimited) completes within budget', () => {
      setQueuePolicy({ maxLogs: 0, maxTraces: 0, maxMetrics: 0 });
      const ns = nsPerOp(() => {
        const ticket = tryAcquire('logs');
        if (ticket) release(ticket);
      });
      expect(ns).toBeLessThan(MAX_NS_PER_OP);
    });
  });

  describe('getHealthSnapshot', () => {
    it('completes within budget', () => {
      const ns = nsPerOp(() => getHealthSnapshot(), 10_000);
      expect(ns).toBeLessThan(MAX_NS_PER_OP);
    });
  });

  describe('metrics', () => {
    it('counter.add completes within budget', () => {
      const c = counter('bench_counter');
      const ns = nsPerOp(() => c.add(1));
      expect(ns).toBeLessThan(MAX_NS_PER_OP);
    });

    it('gauge.set completes within budget', () => {
      const g = gauge('bench_gauge');
      const ns = nsPerOp(() => g.set(42.0));
      expect(ns).toBeLessThan(MAX_NS_PER_OP);
    });

    it('histogram.record completes within budget', () => {
      const h = histogram('bench_histogram');
      const ns = nsPerOp(() => h.record(3.14));
      expect(ns).toBeLessThan(MAX_NS_PER_OP);
    });
  });
});
