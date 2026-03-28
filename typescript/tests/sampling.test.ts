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
    expect(getSamplingPolicy().defaultRate).toBe(0.8);
    const overrides = getSamplingPolicy().overrides;
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

  it('getSamplingPolicy for unknown signal throws ConfigurationError', () => {
    expect(() => getSamplingPolicy('unknown')).toThrow();
  });

  it('getSamplingPolicy error message contains the signal name', () => {
    expect(() => getSamplingPolicy('badSignal')).toThrow(/badSignal/);
  });

  it('setSamplingPolicy error message for unknown signal is non-empty', () => {
    expect(() => setSamplingPolicy('badSignal', { defaultRate: 1.0 })).toThrow(/unknown signal/);
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

describe('shouldSample — health counter integration', () => {
  it('does NOT increment emitted counter when sample is accepted (rate=1) — emitted is counted downstream', () => {
    // emitted is incremented at the emission site (logger/tracer), not here.
    setSamplingPolicy('logs', { defaultRate: 1.0 });
    const before = getHealthSnapshot().logsEmitted;
    shouldSample('logs');
    expect(getHealthSnapshot().logsEmitted).toBe(before); // unchanged
  });

  it('increments dropped counter when sample is rejected (rate=0)', () => {
    setSamplingPolicy('logs', { defaultRate: 0.0 });
    const before = getHealthSnapshot().logsDropped;
    shouldSample('logs');
    expect(getHealthSnapshot().logsDropped).toBe(before + 1);
  });

  it('does NOT increment tracesEmitted when traces are sampled (rate=1)', () => {
    setSamplingPolicy('traces', { defaultRate: 1.0 });
    const before = getHealthSnapshot().tracesEmitted;
    shouldSample('traces');
    expect(getHealthSnapshot().tracesEmitted).toBe(before); // unchanged
  });

  it('increments tracesDropped when traces are dropped', () => {
    setSamplingPolicy('traces', { defaultRate: 0.0 });
    const before = getHealthSnapshot().tracesDropped;
    shouldSample('traces');
    expect(getHealthSnapshot().tracesDropped).toBe(before + 1);
  });

  it('does NOT increment metricsEmitted when metrics are sampled (rate=1)', () => {
    setSamplingPolicy('metrics', { defaultRate: 1.0 });
    const before = getHealthSnapshot().metricsEmitted;
    shouldSample('metrics');
    expect(getHealthSnapshot().metricsEmitted).toBe(before); // unchanged
  });

  it('increments metricsDropped when metrics are dropped', () => {
    setSamplingPolicy('metrics', { defaultRate: 0.0 });
    const before = getHealthSnapshot().metricsDropped;
    shouldSample('metrics');
    expect(getHealthSnapshot().metricsDropped).toBe(before + 1);
  });

  it('does NOT increment emitted on intermediate rate when sampled', () => {
    setSamplingPolicy('logs', { defaultRate: 0.5 });
    vi.spyOn(Math, 'random').mockReturnValueOnce(0.3);
    const before = getHealthSnapshot().logsEmitted;
    shouldSample('logs');
    expect(getHealthSnapshot().logsEmitted).toBe(before); // unchanged — counted downstream
    vi.restoreAllMocks();
  });

  it('increments dropped on intermediate rate when not sampled', () => {
    setSamplingPolicy('logs', { defaultRate: 0.5 });
    vi.spyOn(Math, 'random').mockReturnValueOnce(0.7);
    const before = getHealthSnapshot().logsDropped;
    shouldSample('logs');
    expect(getHealthSnapshot().logsDropped).toBe(before + 1);
    vi.restoreAllMocks();
  });
});

describe('shouldSample — shadow-override hazard fix', () => {
  it('unkeyed call does NOT use signal-named override (shadow-override hazard)', () => {
    // Register an override keyed "logs" with rate 0.0.
    // An unkeyed shouldSample("logs") must use defaultRate, NOT the override.
    setSamplingPolicy('logs', { defaultRate: 1.0, overrides: { logs: 0.0 } });
    // Without the fix (key ?? signal), this would return false because "logs" override = 0.0.
    // With the fix, key is undefined so defaultRate=1.0 is used.
    expect(shouldSample('logs')).toBe(true);
  });

  it('explicit key "logs" DOES use the signal-named override', () => {
    // When the caller explicitly passes key="logs", the override IS consulted.
    setSamplingPolicy('logs', { defaultRate: 1.0, overrides: { logs: 0.0 } });
    expect(shouldSample('logs', 'logs')).toBe(false);
  });

  it('unkeyed call does NOT use "traces" override on traces signal', () => {
    setSamplingPolicy('traces', { defaultRate: 1.0, overrides: { traces: 0.0 } });
    expect(shouldSample('traces')).toBe(true);
  });

  it('unkeyed call does NOT use "metrics" override on metrics signal', () => {
    setSamplingPolicy('metrics', { defaultRate: 1.0, overrides: { metrics: 0.0 } });
    expect(shouldSample('metrics')).toBe(true);
  });
});

describe('shouldSample — health counter double-counting fix', () => {
  it('shouldSample returning true (rate=1) does NOT increment dropped', () => {
    setSamplingPolicy('logs', { defaultRate: 1.0 });
    _resetHealthForTests();
    expect(shouldSample('logs')).toBe(true);
    expect(getHealthSnapshot().logsDropped).toBe(0);
  });

  it('shouldSample returning false (rate=0) increments dropped exactly once', () => {
    setSamplingPolicy('logs', { defaultRate: 0.0 });
    _resetHealthForTests();
    expect(shouldSample('logs')).toBe(false);
    expect(getHealthSnapshot().logsDropped).toBe(1);
  });

  it('shouldSample returning false via intermediate rate increments dropped once', () => {
    setSamplingPolicy('logs', { defaultRate: 0.5 });
    vi.spyOn(Math, 'random').mockReturnValueOnce(0.9); // > 0.5 → drop
    _resetHealthForTests();
    expect(shouldSample('logs')).toBe(false);
    expect(getHealthSnapshot().logsDropped).toBe(1);
    vi.restoreAllMocks();
  });

  it('shouldSample returning true via intermediate rate does NOT increment dropped', () => {
    setSamplingPolicy('logs', { defaultRate: 0.5 });
    vi.spyOn(Math, 'random').mockReturnValueOnce(0.1); // < 0.5 → sample
    _resetHealthForTests();
    expect(shouldSample('logs')).toBe(true);
    expect(getHealthSnapshot().logsDropped).toBe(0);
    vi.restoreAllMocks();
  });
});
