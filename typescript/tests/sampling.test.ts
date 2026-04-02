// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  _resetSamplingForTests,
  getSamplingPolicy,
  setSamplingPolicy,
  shouldSample,
} from '../src/sampling';
import { _resetHealthForTests, getHealthSnapshot } from '../src/health';

afterEach(() => {
  _resetSamplingForTests();
  _resetHealthForTests();
});

describe('setSamplingPolicy / getSamplingPolicy', () => {
  it('defaults to rate=1.0', () => {
    expect(getSamplingPolicy('logs').defaultRate).toBe(1.0);
  });

  it('stores a policy', () => {
    setSamplingPolicy('logs', { defaultRate: 0.5 });
    expect(getSamplingPolicy('logs').defaultRate).toBe(0.5);
  });

  it('clamps rate to [0, 1]', () => {
    setSamplingPolicy('logs', { defaultRate: 2.0 });
    expect(getSamplingPolicy('logs').defaultRate).toBe(1.0);
    setSamplingPolicy('logs', { defaultRate: -0.1 });
    expect(getSamplingPolicy('logs').defaultRate).toBe(0.0);
  });

  it('stores overrides and clamps them', () => {
    setSamplingPolicy('logs', { defaultRate: 1.0, overrides: { traces: 0.5, logs: 1.5 } });
    const p = getSamplingPolicy('logs');
    expect(p.overrides?.['traces']).toBe(0.5);
    expect(p.overrides?.['logs']).toBe(1.0);
  });

  it('returns a copy — mutating does not affect stored policy', () => {
    setSamplingPolicy('logs', { defaultRate: 0.8, overrides: { a: 0.5 } });
    const p = getSamplingPolicy('logs');
    p.defaultRate = 0.1;
    if (p.overrides) p.overrides['a'] = 0.0;
    expect(getSamplingPolicy('logs').defaultRate).toBe(0.8);
    const overrides = getSamplingPolicy('logs').overrides;
    expect(overrides).toBeDefined();
    expect(overrides?.['a']).toBe(0.5);
  });
});

describe('shouldSample', () => {
  it('always returns true when rate=1.0', () => {
    setSamplingPolicy('logs', { defaultRate: 1.0 });
    for (let i = 0; i < 20; i++) {
      expect(shouldSample('logs')).toBe(true);
    }
  });

  it('always returns false when rate=0.0', () => {
    setSamplingPolicy('logs', { defaultRate: 0.0 });
    for (let i = 0; i < 20; i++) {
      expect(shouldSample('logs')).toBe(false);
    }
  });

  it('uses override rate for a specific key', () => {
    setSamplingPolicy('logs', { defaultRate: 1.0, overrides: { traces: 0.0 } });
    expect(shouldSample('logs', 'traces')).toBe(false);
    expect(shouldSample('logs')).toBe(true);
  });

  it('uses Math.random() for intermediate rates', () => {
    setSamplingPolicy('logs', { defaultRate: 0.5 });
    vi.spyOn(Math, 'random').mockReturnValueOnce(0.3); // < 0.5 → sample
    expect(shouldSample('logs')).toBe(true);
    vi.spyOn(Math, 'random').mockReturnValueOnce(0.7); // > 0.5 → drop
    expect(shouldSample('logs')).toBe(false);
    vi.restoreAllMocks();
  });

  it('returns a boolean', () => {
    expect(typeof shouldSample('metrics')).toBe('boolean');
  });
});

describe('sampling — reset restores default policy (kills BlockStatement + ObjectLiteral)', () => {
  it('_resetSamplingForTests restores defaultRate to 1.0', () => {
    setSamplingPolicy('logs', { defaultRate: 0.0 });
    expect(getSamplingPolicy('logs').defaultRate).toBe(0.0);
    _resetSamplingForTests();
    expect(getSamplingPolicy('logs').defaultRate).toBe(1.0);
  });

  it('_resetSamplingForTests clears overrides', () => {
    setSamplingPolicy('logs', { defaultRate: 1.0, overrides: { mySignal: 0.5 } });
    _resetSamplingForTests();
    expect(getSamplingPolicy('logs').overrides).toBeUndefined();
  });
});

describe('per-signal sampling isolation', () => {
  it('setting a policy for logs does NOT affect shouldSample for traces', () => {
    setSamplingPolicy('logs', { defaultRate: 0.0 });
    // traces has no policy set, so it should use default (1.0)
    expect(shouldSample('traces')).toBe(true);
    expect(shouldSample('logs')).toBe(false);
  });

  it('setting a policy for traces does NOT affect shouldSample for logs', () => {
    setSamplingPolicy('traces', { defaultRate: 0.0 });
    // logs has no policy set, so it should use default (1.0)
    expect(shouldSample('logs')).toBe(true);
    expect(shouldSample('traces')).toBe(false);
  });

  it('getSamplingPolicy for unknown signal returns the default policy', () => {
    const p = getSamplingPolicy('unknown');
    expect(p.defaultRate).toBe(1.0);
    expect(p.overrides).toBeUndefined();
  });

  it('each signal can have independent overrides', () => {
    setSamplingPolicy('logs', { defaultRate: 1.0, overrides: { special: 0.0 } });
    setSamplingPolicy('traces', { defaultRate: 0.0, overrides: { special: 1.0 } });
    // logs: override for 'special' = 0.0
    expect(shouldSample('logs', 'special')).toBe(false);
    // traces: override for 'special' = 1.0
    expect(shouldSample('traces', 'special')).toBe(true);
    // logs default is 1.0, traces default is 0.0
    expect(shouldSample('logs')).toBe(true);
    expect(shouldSample('traces')).toBe(false);
  });
});
