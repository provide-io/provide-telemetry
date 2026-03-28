// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: AGPL-3.0-or-later

import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  _resetSamplingForTests,
  getSamplingPolicy,
  setSamplingPolicy,
  shouldSample,
} from '../src/sampling';

afterEach(() => _resetSamplingForTests());

describe('setSamplingPolicy / getSamplingPolicy', () => {
  it('defaults to rate=1.0', () => {
    expect(getSamplingPolicy().defaultRate).toBe(1.0);
  });

  it('stores a policy', () => {
    setSamplingPolicy({ defaultRate: 0.5 });
    expect(getSamplingPolicy().defaultRate).toBe(0.5);
  });

  it('clamps rate to [0, 1]', () => {
    setSamplingPolicy({ defaultRate: 2.0 });
    expect(getSamplingPolicy().defaultRate).toBe(1.0);
    setSamplingPolicy({ defaultRate: -0.1 });
    expect(getSamplingPolicy().defaultRate).toBe(0.0);
  });

  it('stores overrides and clamps them', () => {
    setSamplingPolicy({ defaultRate: 1.0, overrides: { traces: 0.5, logs: 1.5 } });
    const p = getSamplingPolicy();
    expect(p.overrides?.['traces']).toBe(0.5);
    expect(p.overrides?.['logs']).toBe(1.0);
  });

  it('returns a copy — mutating does not affect stored policy', () => {
    setSamplingPolicy({ defaultRate: 0.8, overrides: { a: 0.5 } });
    const p = getSamplingPolicy();
    p.defaultRate = 0.1;
    if (p.overrides) p.overrides['a'] = 0.0;
    expect(getSamplingPolicy().defaultRate).toBe(0.8);
    const overrides = getSamplingPolicy().overrides;
    expect(overrides).toBeDefined();
    expect(overrides?.['a']).toBe(0.5);
  });
});

describe('shouldSample', () => {
  it('always returns true when rate=1.0', () => {
    setSamplingPolicy({ defaultRate: 1.0 });
    for (let i = 0; i < 20; i++) {
      expect(shouldSample('logs')).toBe(true);
    }
  });

  it('always returns false when rate=0.0', () => {
    setSamplingPolicy({ defaultRate: 0.0 });
    for (let i = 0; i < 20; i++) {
      expect(shouldSample('logs')).toBe(false);
    }
  });

  it('uses override rate for a specific signal', () => {
    setSamplingPolicy({ defaultRate: 1.0, overrides: { traces: 0.0 } });
    expect(shouldSample('traces')).toBe(false);
    expect(shouldSample('logs')).toBe(true);
  });

  it('uses Math.random() for intermediate rates', () => {
    setSamplingPolicy({ defaultRate: 0.5 });
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
    setSamplingPolicy({ defaultRate: 0.0 });
    expect(getSamplingPolicy().defaultRate).toBe(0.0);
    _resetSamplingForTests();
    expect(getSamplingPolicy().defaultRate).toBe(1.0);
  });

  it('_resetSamplingForTests clears overrides', () => {
    setSamplingPolicy({ defaultRate: 1.0, overrides: { mySignal: 0.5 } });
    _resetSamplingForTests();
    expect(getSamplingPolicy().overrides).toBeUndefined();
  });
});
