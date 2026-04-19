// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  _resetConfig,
  applyConfigPolicies,
  configFromEnv,
  getConfig,
  setupTelemetry,
} from '../src/config';
import { getSamplingPolicy, _resetSamplingForTests } from '../src/sampling';
import { getQueuePolicy, _resetBackpressureForTests } from '../src/backpressure';
import { getExporterPolicy, _resetResilienceForTests } from '../src/resilience';
import { ConfigurationError } from '../src/exceptions';
import {
  awaitPropagationInit,
  isFallbackMode,
  isPropagationInitDone,
  _disablePropagationALSForTest,
  _restorePropagationALSForTest,
  _setPropagationInitDoneForTest,
} from '../src/propagation';
import { getHealthSnapshot, setSetupError } from '../src/health';
import { resetTelemetryState } from '../src/testing';

afterEach(() => {
  _resetConfig();
  _resetSamplingForTests();
  _resetBackpressureForTests();
  _resetResilienceForTests();
});

describe('DEFAULTS — new boolean fields kill mutations', () => {
  it('logIncludeTimestamp default is true (not false)', () => {
    _resetConfig();
    expect(getConfig().logIncludeTimestamp).toBe(true);
  });
  it('logIncludeCaller default is true (not false)', () => {
    _resetConfig();
    expect(getConfig().logIncludeCaller).toBe(true);
  });
  it('logSanitize default is true (not false)', () => {
    _resetConfig();
    expect(getConfig().logSanitize).toBe(true);
  });
  it('logCodeAttributes default is false (not true)', () => {
    _resetConfig();
    expect(getConfig().logCodeAttributes).toBe(false);
  });
  it('metricsEnabled default is true (not false)', () => {
    _resetConfig();
    expect(getConfig().metricsEnabled).toBe(true);
  });
  it('exporterLogsFailOpen default is true (not false)', () => {
    _resetConfig();
    expect(getConfig().exporterLogsFailOpen).toBe(true);
  });
  it('exporterTracesFailOpen default is true (not false)', () => {
    _resetConfig();
    expect(getConfig().exporterTracesFailOpen).toBe(true);
  });
  it('exporterMetricsFailOpen default is true (not false)', () => {
    _resetConfig();
    expect(getConfig().exporterMetricsFailOpen).toBe(true);
  });
  it('sloEnableRedMetrics default is false (not true)', () => {
    _resetConfig();
    expect(getConfig().sloEnableRedMetrics).toBe(false);
  });
  it('sloEnableUseMetrics default is false (not true)', () => {
    _resetConfig();
    expect(getConfig().sloEnableUseMetrics).toBe(false);
  });
  it('exporterLogsTimeoutMs default is 10000 (not 0)', () => {
    _resetConfig();
    expect(getConfig().exporterLogsTimeoutMs).toBe(10000);
  });
  it('exporterTracesTimeoutMs default is 10000 (not 0)', () => {
    _resetConfig();
    expect(getConfig().exporterTracesTimeoutMs).toBe(10000);
  });
  it('exporterMetricsTimeoutMs default is 10000 (not 0)', () => {
    _resetConfig();
    expect(getConfig().exporterMetricsTimeoutMs).toBe(10000);
  });
  it('securityMaxAttrValueLength default is 1024', () => {
    _resetConfig();
    expect(getConfig().securityMaxAttrValueLength).toBe(1024);
  });
  it('securityMaxAttrCount default is 64', () => {
    _resetConfig();
    expect(getConfig().securityMaxAttrCount).toBe(64);
  });
});

describe('setupTelemetry applies sampling policies', () => {
  it('applies custom samplingLogsRate', () => {
    setupTelemetry({ samplingLogsRate: 0.5 });
    expect(getSamplingPolicy('logs').defaultRate).toBe(0.5);
  });

  it('applies custom samplingTracesRate', () => {
    setupTelemetry({ samplingTracesRate: 0.3 });
    expect(getSamplingPolicy('traces').defaultRate).toBe(0.3);
  });

  it('applies custom samplingMetricsRate', () => {
    setupTelemetry({ samplingMetricsRate: 0.8 });
    expect(getSamplingPolicy('metrics').defaultRate).toBe(0.8);
  });

  it('applies default sampling rates (1.0) when no overrides', () => {
    setupTelemetry();
    expect(getSamplingPolicy('logs').defaultRate).toBe(1.0);
    expect(getSamplingPolicy('traces').defaultRate).toBe(1.0);
    expect(getSamplingPolicy('metrics').defaultRate).toBe(1.0);
  });
});

describe('setupTelemetry ALS guard', () => {
  it('does not throw when ALS is available (normal Node.js path)', () => {
    expect(isFallbackMode()).toBe(false);
    expect(() => setupTelemetry()).not.toThrow();
  });

  it('throws ConfigurationError when ALS is unavailable in a Node.js environment', () => {
    const savedAls = _disablePropagationALSForTest();
    try {
      expect(isFallbackMode()).toBe(true);
      expect(() => setupTelemetry()).toThrow(ConfigurationError);
      expect(() => setupTelemetry()).toThrow(/AsyncLocalStorage unavailable/);
    } finally {
      _restorePropagationALSForTest(savedAls);
      resetTelemetryState();
    }
  });

  it('does not throw when ALS is unavailable in a non-Node environment', () => {
    const savedAls = _disablePropagationALSForTest();
    const savedVersionsDescriptor = Object.getOwnPropertyDescriptor(
      process,
      'versions',
    ) as PropertyDescriptor;
    Object.defineProperty(process, 'versions', { value: {}, configurable: true });
    try {
      expect(isFallbackMode()).toBe(true);
      expect(() => setupTelemetry()).not.toThrow();
    } finally {
      Object.defineProperty(process, 'versions', savedVersionsDescriptor);
      _restorePropagationALSForTest(savedAls);
      resetTelemetryState();
    }
  });

  it('defers ALS check and clears (no setupError) when init resolves with ALS available', async () => {
    // Simulate the racing-window where ALS comes online BEFORE the deferred
    // .then() fires — exercises the false branch of the deferred isFallbackMode check.
    const savedAls = _disablePropagationALSForTest();
    const savedDone = _setPropagationInitDoneForTest(false);
    setSetupError(null);
    try {
      expect(isFallbackMode()).toBe(true);
      expect(() => setupTelemetry()).not.toThrow();
      // Restore ALS so the deferred callback observes the non-fallback state.
      _restorePropagationALSForTest(savedAls);
      await awaitPropagationInit();
      await Promise.resolve();
      expect(getHealthSnapshot().setupError).toBeNull();
    } finally {
      _setPropagationInitDoneForTest(savedDone);
      _restorePropagationALSForTest(savedAls);
      setSetupError(null);
      resetTelemetryState();
    }
  });

  it('defers ALS check (no throw, sets setupError) when init is still racing', async () => {
    // Simulate the tsx-ESM race: ALS hasn't initialized yet AND init isn't done.
    const savedAls = _disablePropagationALSForTest();
    const savedDone = _setPropagationInitDoneForTest(false);
    setSetupError(null);
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    try {
      expect(isFallbackMode()).toBe(true);
      expect(isPropagationInitDone()).toBe(false);
      // Must NOT throw — deferred check fires after awaitPropagationInit resolves.
      expect(() => setupTelemetry()).not.toThrow();
      // Drain the deferred .then() — awaitPropagationInit() resolves immediately
      // here because the real init has long settled; the fake `done=false` just
      // gates the sync branch in setupTelemetry.
      await awaitPropagationInit();
      // One more microtask for the .then() callback chained off it.
      await Promise.resolve();
      expect(getHealthSnapshot().setupError).toMatch(/AsyncLocalStorage unavailable/);
      expect(warnSpy).toHaveBeenCalledWith(expect.stringMatching(/AsyncLocalStorage unavailable/));
    } finally {
      warnSpy.mockRestore();
      _setPropagationInitDoneForTest(savedDone);
      _restorePropagationALSForTest(savedAls);
      setSetupError(null);
      resetTelemetryState();
    }
  });
});

describe('propagation init helpers', () => {
  it('isPropagationInitDone returns true after module load', () => {
    expect(isPropagationInitDone()).toBe(true);
  });

  it('awaitPropagationInit resolves to undefined', async () => {
    await expect(awaitPropagationInit()).resolves.toBeUndefined();
  });
});

describe('setupTelemetry applies backpressure policies', () => {
  it('applies custom backpressureTracesMaxsize', () => {
    setupTelemetry({ backpressureTracesMaxsize: 64 });
    expect(getQueuePolicy().maxTraces).toBe(64);
  });

  it('applies custom backpressureLogsMaxsize', () => {
    setupTelemetry({ backpressureLogsMaxsize: 100 });
    expect(getQueuePolicy().maxLogs).toBe(100);
  });

  it('applies custom backpressureMetricsMaxsize', () => {
    setupTelemetry({ backpressureMetricsMaxsize: 200 });
    expect(getQueuePolicy().maxMetrics).toBe(200);
  });

  it('applies default backpressure (0 = unbounded) when no overrides', () => {
    setupTelemetry();
    const policy = getQueuePolicy();
    expect(policy.maxLogs).toBe(0);
    expect(policy.maxTraces).toBe(0);
    expect(policy.maxMetrics).toBe(0);
  });
});

describe('setupTelemetry applies exporter resilience policies', () => {
  it('applies custom exporterLogsRetries', () => {
    setupTelemetry({ exporterLogsRetries: 3 });
    expect(getExporterPolicy('logs').retries).toBe(3);
  });

  it('applies custom exporterLogsBackoffMs', () => {
    setupTelemetry({ exporterLogsBackoffMs: 500 });
    expect(getExporterPolicy('logs').backoffMs).toBe(500);
  });

  it('applies custom exporterLogsTimeoutMs', () => {
    setupTelemetry({ exporterLogsTimeoutMs: 5000 });
    expect(getExporterPolicy('logs').timeoutMs).toBe(5000);
  });

  it('applies custom exporterLogsFailOpen', () => {
    setupTelemetry({ exporterLogsFailOpen: false });
    expect(getExporterPolicy('logs').failOpen).toBe(false);
  });

  it('applies custom exporterTracesRetries', () => {
    setupTelemetry({ exporterTracesRetries: 5 });
    expect(getExporterPolicy('traces').retries).toBe(5);
  });

  it('applies custom exporterTracesBackoffMs', () => {
    setupTelemetry({ exporterTracesBackoffMs: 1000 });
    expect(getExporterPolicy('traces').backoffMs).toBe(1000);
  });

  it('applies custom exporterTracesTimeoutMs', () => {
    setupTelemetry({ exporterTracesTimeoutMs: 20000 });
    expect(getExporterPolicy('traces').timeoutMs).toBe(20000);
  });

  it('applies custom exporterTracesFailOpen', () => {
    setupTelemetry({ exporterTracesFailOpen: false });
    expect(getExporterPolicy('traces').failOpen).toBe(false);
  });

  it('applies custom exporterMetricsRetries', () => {
    setupTelemetry({ exporterMetricsRetries: 2 });
    expect(getExporterPolicy('metrics').retries).toBe(2);
  });

  it('applies custom exporterMetricsBackoffMs', () => {
    setupTelemetry({ exporterMetricsBackoffMs: 750 });
    expect(getExporterPolicy('metrics').backoffMs).toBe(750);
  });

  it('applies custom exporterMetricsTimeoutMs', () => {
    setupTelemetry({ exporterMetricsTimeoutMs: 15000 });
    expect(getExporterPolicy('metrics').timeoutMs).toBe(15000);
  });

  it('applies custom exporterMetricsFailOpen', () => {
    setupTelemetry({ exporterMetricsFailOpen: false });
    expect(getExporterPolicy('metrics').failOpen).toBe(false);
  });

  it('applies default exporter policies when no overrides', () => {
    setupTelemetry();
    for (const signal of ['logs', 'traces', 'metrics']) {
      const policy = getExporterPolicy(signal);
      expect(policy.retries).toBe(0);
      expect(policy.backoffMs).toBe(0);
      expect(policy.timeoutMs).toBe(10000);
      expect(policy.failOpen).toBe(true);
    }
  });
});

describe('applyConfigPolicies standalone', () => {
  it('can be called directly with a full config', () => {
    const cfg = { ...configFromEnv(), samplingLogsRate: 0.1, backpressureLogsMaxsize: 42 };
    applyConfigPolicies(cfg);
    expect(getSamplingPolicy('logs').defaultRate).toBe(0.1);
    expect(getQueuePolicy().maxLogs).toBe(42);
  });
});

describe('DEFAULTS — strictSchema and requiredLogKeys kill mutations', () => {
  it('strictSchema default is false (not true) via _resetConfig', () => {
    _resetConfig();
    expect(getConfig().strictSchema).toBe(false);
  });

  it('requiredLogKeys default is empty array (not populated) via _resetConfig', () => {
    _resetConfig();
    expect(getConfig().requiredLogKeys).toEqual([]);
    expect(getConfig().requiredLogKeys).toHaveLength(0);
  });
});

describe('_validateConfig — requireRate throws on out-of-range values', () => {
  it('throws ConfigurationError when samplingLogsRate is greater than 1', () => {
    expect(() => setupTelemetry({ samplingLogsRate: 1.5 })).toThrow(ConfigurationError);
  });

  it('throws ConfigurationError when traceSampleRate is negative', () => {
    expect(() => setupTelemetry({ traceSampleRate: -0.1 })).toThrow(ConfigurationError);
  });

  it('throws ConfigurationError when backpressureLogsMaxsize is negative', () => {
    expect(() => setupTelemetry({ backpressureLogsMaxsize: -1 })).toThrow(ConfigurationError);
  });

  it('throws ConfigurationError when backpressureTracesMaxsize is a non-integer', () => {
    expect(() => setupTelemetry({ backpressureTracesMaxsize: 1.5 })).toThrow(ConfigurationError);
  });
});

describe('setupTelemetry — emergency fallback', () => {
  it('does not throw when applyConfigPolicies fails with Error', async () => {
    const samplingModule = await import('../src/sampling');
    vi.spyOn(samplingModule, 'setSamplingPolicy').mockImplementation(() => {
      throw new Error('policy explosion');
    });
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    expect(() => setupTelemetry()).not.toThrow();
    expect(warnSpy).toHaveBeenCalledWith(expect.stringContaining('policy explosion'));
    warnSpy.mockRestore();
    vi.restoreAllMocks();
  });

  it('does not throw when applyConfigPolicies fails with non-Error', async () => {
    const samplingModule = await import('../src/sampling');
    vi.spyOn(samplingModule, 'setSamplingPolicy').mockImplementation(() => {
      throw 'string-failure';
    });
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    expect(() => setupTelemetry()).not.toThrow();
    expect(warnSpy).toHaveBeenCalledWith(expect.stringContaining('string-failure'));
    warnSpy.mockRestore();
    vi.restoreAllMocks();
  });
});
