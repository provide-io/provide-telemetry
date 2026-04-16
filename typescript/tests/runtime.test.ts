// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { _resetConfig, setupTelemetry } from '../src/config';
import type { RuntimeOverrides } from '../src/config';
import {
  _areProvidersRegistered,
  _getRegisteredProviders,
  _markProvidersRegistered,
  _resetRuntimeForTests,
  _setProviderSignalInstalled,
  _storeRegisteredProviders,
  getRuntimeConfig,
  getRuntimeStatus,
  reloadRuntimeFromEnv,
  reconfigureTelemetry,
  updateRuntimeConfig,
} from '../src/runtime';

beforeEach(() => {
  _resetRuntimeForTests();
  _resetConfig();
});
afterEach(() => {
  _resetRuntimeForTests();
  _resetConfig();
});

describe('getRuntimeConfig', () => {
  it('reflects env-derived identity before setupTelemetry()', () => {
    process.env['PROVIDE_TELEMETRY_SERVICE_NAME'] = 'env-service';
    process.env['PROVIDE_TELEMETRY_ENV'] = 'parity';
    process.env['PROVIDE_TELEMETRY_VERSION'] = '1.2.3';
    try {
      const cfg = getRuntimeConfig();
      expect(cfg.serviceName).toBe('env-service');
      expect(cfg.environment).toBe('parity');
      expect(cfg.version).toBe('1.2.3');
    } finally {
      delete process.env['PROVIDE_TELEMETRY_SERVICE_NAME'];
      delete process.env['PROVIDE_TELEMETRY_ENV'];
      delete process.env['PROVIDE_TELEMETRY_VERSION'];
    }
  });

  it('returns a config derived from env when nothing set', () => {
    const cfg = getRuntimeConfig();
    expect(cfg.serviceName).toBeDefined();
    expect(cfg.logLevel).toBeDefined();
    expect(typeof cfg.otelEnabled).toBe('boolean');
    expect(typeof cfg.tracingEnabled).toBe('boolean');
  });

  it('returns a frozen object', () => {
    const cfg = getRuntimeConfig();
    expect(Object.isFrozen(cfg)).toBe(true);
  });

  it('throws when mutating a frozen config property', () => {
    const cfg = getRuntimeConfig();
    expect(() => {
      (cfg as Record<string, unknown>)['samplingLogsRate'] = 0.5;
    }).toThrow();
  });

  it('deep-freezes nested objects', () => {
    setupTelemetry({ logModuleLevels: { 'my.mod': 'debug' } });
    updateRuntimeConfig({ samplingLogsRate: 1.0 });
    const cfg = getRuntimeConfig();
    expect(Object.isFrozen(cfg.logModuleLevels)).toBe(true);
    expect(() => {
      (cfg.logModuleLevels as Record<string, string>)['new.mod'] = 'info';
    }).toThrow();
  });

  it('reflects values set via setupTelemetry() without needing updateRuntimeConfig()', () => {
    _resetRuntimeForTests();
    _resetConfig();
    setupTelemetry({ serviceName: 'injected-service', logLevel: 'debug' });
    const cfg = getRuntimeConfig();
    expect(cfg.serviceName).toBe('injected-service');
    expect(cfg.logLevel).toBe('debug');
  });
});

describe('getRuntimeStatus', () => {
  it('reports fallback mode before setup', () => {
    const status = getRuntimeStatus();
    expect(status.setupDone).toBe(false);
    expect(status.providers).toEqual({ logs: false, traces: false, metrics: false });
    expect(status.fallback).toEqual({ logs: true, traces: true, metrics: true });
  });

  it('reports per-signal provider installation state', () => {
    setupTelemetry({ otelEnabled: true, tracingEnabled: false, metricsEnabled: true });
    _setProviderSignalInstalled('logs', true);
    _setProviderSignalInstalled('traces', false);
    _setProviderSignalInstalled('metrics', true);

    const status = getRuntimeStatus();
    expect(status.setupDone).toBe(true);
    expect(status.signals).toEqual({ logs: true, traces: false, metrics: true });
    expect(status.providers).toEqual({ logs: true, traces: false, metrics: true });
    expect(status.fallback).toEqual({ logs: false, traces: true, metrics: false });
  });
});

describe('updateRuntimeConfig', () => {
  it('merges overrides into active config', () => {
    updateRuntimeConfig({ samplingLogsRate: 0.5, samplingTracesRate: 0.3 });
    const cfg = getRuntimeConfig();
    expect(cfg.samplingLogsRate).toBe(0.5);
    expect(cfg.samplingTracesRate).toBe(0.3);
  });

  it('persists across subsequent getRuntimeConfig calls', () => {
    updateRuntimeConfig({ samplingMetricsRate: 0.7 });
    expect(getRuntimeConfig().samplingMetricsRate).toBe(0.7);
  });

  it('ignores undefined values in overrides', () => {
    updateRuntimeConfig({ samplingLogsRate: 0.5 });
    const before = getRuntimeConfig().samplingTracesRate;
    updateRuntimeConfig({ samplingLogsRate: undefined, samplingTracesRate: undefined });
    expect(getRuntimeConfig().samplingLogsRate).toBe(0.5);
    expect(getRuntimeConfig().samplingTracesRate).toBe(before);
  });

  it('rejects invalid override values before applying them', () => {
    updateRuntimeConfig({ samplingLogsRate: 0.5, backpressureLogsMaxsize: 5 });
    expect(() => updateRuntimeConfig({ samplingLogsRate: -0.1 })).toThrow();
    expect(() => updateRuntimeConfig({ samplingLogsRate: 1.1 })).toThrow();
    expect(() => updateRuntimeConfig({ backpressureLogsMaxsize: -1 })).toThrow();
    expect(() => updateRuntimeConfig({ exporterLogsRetries: -1 })).toThrow();
    expect(() => updateRuntimeConfig({ exporterLogsBackoffMs: -1 })).toThrow();
    expect(() => updateRuntimeConfig({ exporterLogsTimeoutMs: -1 })).toThrow();
    expect(() => updateRuntimeConfig({ securityMaxAttrCount: -1 })).toThrow();
    expect(getRuntimeConfig().samplingLogsRate).toBe(0.5);
    expect(getRuntimeConfig().backpressureLogsMaxsize).toBe(5);
  });

  it('accepts boundary value 0 for rate fields (kills < 0 → <= 0 mutation)', () => {
    expect(() => updateRuntimeConfig({ samplingLogsRate: 0 })).not.toThrow();
    expect(getRuntimeConfig().samplingLogsRate).toBe(0);
    expect(() => updateRuntimeConfig({ samplingTracesRate: 0 })).not.toThrow();
    expect(getRuntimeConfig().samplingTracesRate).toBe(0);
    expect(() => updateRuntimeConfig({ samplingMetricsRate: 0 })).not.toThrow();
    expect(getRuntimeConfig().samplingMetricsRate).toBe(0);
  });
});

describe('RuntimeOverrides', () => {
  it('accepts only hot-reloadable fields', () => {
    const overrides: RuntimeOverrides = {
      samplingLogsRate: 0.5,
      backpressureLogsMaxsize: 100,
      exporterLogsRetries: 3,
      exporterLogsBackoffMs: 200,
      exporterLogsTimeoutMs: 5000,
      exporterLogsFailOpen: false,
      securityMaxAttrValueLength: 512,
      securityMaxAttrCount: 32,
      sloEnableRedMetrics: true,
      sloEnableUseMetrics: true,
      piiMaxDepth: 4,
      strictSchema: true,
    };
    updateRuntimeConfig(overrides);
    const cfg = getRuntimeConfig();
    expect(cfg.samplingLogsRate).toBe(0.5);
    expect(cfg.backpressureLogsMaxsize).toBe(100);
    expect(cfg.exporterLogsRetries).toBe(3);
    expect(cfg.securityMaxAttrValueLength).toBe(512);
    expect(cfg.sloEnableRedMetrics).toBe(true);
    expect(cfg.piiMaxDepth).toBe(4);
    expect(cfg.strictSchema).toBe(true);
  });

  it('all fields are optional — empty object is valid', () => {
    const overrides: RuntimeOverrides = {};
    expect(() => updateRuntimeConfig(overrides)).not.toThrow();
  });
});

describe('reloadRuntimeFromEnv', () => {
  it('resets hot fields to env-derived config', () => {
    updateRuntimeConfig({ samplingLogsRate: 0.1 });
    reloadRuntimeFromEnv();
    // After reload, samplingLogsRate should come from env (default 1.0)
    const cfg = getRuntimeConfig();
    expect(cfg.samplingLogsRate).toBe(1.0);
  });

  it('warns on cold-field drift', () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    // Set up active config with a specific serviceName via reconfigureTelemetry (which sets _activeConfig)
    reconfigureTelemetry({ serviceName: 'custom-service' });
    // Now reload from env — serviceName will differ (env default is 'provide-service')
    reloadRuntimeFromEnv();
    expect(warnSpy).toHaveBeenCalledWith(
      '[provide-telemetry] runtime.cold_field_drift:',
      expect.stringContaining('serviceName'),
      '— restart required to apply',
    );
    warnSpy.mockRestore();
  });

  it('does not warn when cold fields have not drifted', () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    // Set up with defaults — reloading from env should produce same cold fields
    updateRuntimeConfig({ samplingLogsRate: 0.5 });
    reloadRuntimeFromEnv();
    expect(warnSpy).not.toHaveBeenCalled();
    warnSpy.mockRestore();
  });

  it('does not warn when no active config exists', () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    // No prior updateRuntimeConfig call, _activeConfig is null
    reloadRuntimeFromEnv();
    expect(warnSpy).not.toHaveBeenCalled();
    warnSpy.mockRestore();
  });

  it('preserves cold fields from prior config (does not overwrite serviceName)', () => {
    reconfigureTelemetry({ serviceName: 'locked-service' });
    reloadRuntimeFromEnv();
    // serviceName should stay as 'locked-service' because reload only applies hot fields
    expect(getRuntimeConfig().serviceName).toBe('locked-service');
  });

  it('warns on environment cold-field drift (kills StringLiteral on _COLD_FIELDS entry)', () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    reconfigureTelemetry({ environment: 'custom-env' });
    reloadRuntimeFromEnv();
    expect(warnSpy).toHaveBeenCalledWith(
      '[provide-telemetry] runtime.cold_field_drift:',
      expect.stringContaining('environment'),
      '— restart required to apply',
    );
    warnSpy.mockRestore();
  });

  it('warns on version cold-field drift (kills StringLiteral on _COLD_FIELDS entry)', () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    reconfigureTelemetry({ version: 'custom-version' });
    reloadRuntimeFromEnv();
    expect(warnSpy).toHaveBeenCalledWith(
      '[provide-telemetry] runtime.cold_field_drift:',
      expect.stringContaining('version'),
      '— restart required to apply',
    );
    warnSpy.mockRestore();
  });

  it('warns on otelEnabled cold-field drift (kills StringLiteral on _COLD_FIELDS entry)', () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    reconfigureTelemetry({ otelEnabled: false });
    reloadRuntimeFromEnv();
    expect(warnSpy).toHaveBeenCalledWith(
      '[provide-telemetry] runtime.cold_field_drift:',
      expect.stringContaining('otelEnabled'),
      '— restart required to apply',
    );
    warnSpy.mockRestore();
  });

  it('warns on tracingEnabled cold-field drift', () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    reconfigureTelemetry({ tracingEnabled: false });
    reloadRuntimeFromEnv();
    expect(warnSpy).toHaveBeenCalledWith(
      '[provide-telemetry] runtime.cold_field_drift:',
      expect.stringContaining('tracingEnabled'),
      '— restart required to apply',
    );
    warnSpy.mockRestore();
  });

  it('warns on metricsEnabled cold-field drift', () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    reconfigureTelemetry({ metricsEnabled: false });
    reloadRuntimeFromEnv();
    expect(warnSpy).toHaveBeenCalledWith(
      '[provide-telemetry] runtime.cold_field_drift:',
      expect.stringContaining('metricsEnabled'),
      '— restart required to apply',
    );
    warnSpy.mockRestore();
  });

  it('warns on otlpEndpoint cold-field drift (kills StringLiteral on _COLD_FIELDS entry)', () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    reconfigureTelemetry({ otlpEndpoint: 'http://custom:4318' });
    reloadRuntimeFromEnv();
    expect(warnSpy).toHaveBeenCalledWith(
      '[provide-telemetry] runtime.cold_field_drift:',
      expect.stringContaining('otlpEndpoint'),
      '— restart required to apply',
    );
    warnSpy.mockRestore();
  });

  it('warns on otlpHeaders cold-field drift (kills StringLiteral on _COLD_FIELDS entry)', () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    reconfigureTelemetry({ otlpHeaders: { 'x-api-key': 'secret' } });
    reloadRuntimeFromEnv();
    expect(warnSpy).toHaveBeenCalledWith(
      '[provide-telemetry] runtime.cold_field_drift:',
      expect.stringContaining('otlpHeaders'),
      '— restart required to apply',
    );
    warnSpy.mockRestore();
  });

  it('warns on otlpTracesEndpoint cold-field drift', () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    reconfigureTelemetry({ otlpTracesEndpoint: 'http://traces:4318' });
    reloadRuntimeFromEnv();
    expect(warnSpy).toHaveBeenCalledWith(
      '[provide-telemetry] runtime.cold_field_drift:',
      expect.stringContaining('otlpTracesEndpoint'),
      '— restart required to apply',
    );
    warnSpy.mockRestore();
  });

  it('rejects per-signal OTLP endpoint change after providers registered', () => {
    reconfigureTelemetry({ otlpTracesEndpoint: 'http://traces:4318' });
    _markProvidersRegistered();
    expect(() => reconfigureTelemetry({ otlpTracesEndpoint: 'http://other:4318' })).toThrow(
      /provider-changing reconfiguration/,
    );
  });
});

describe('_markProvidersRegistered / _areProvidersRegistered', () => {
  it('starts as false', () => {
    expect(_areProvidersRegistered()).toBe(false);
  });

  it('becomes true after mark', () => {
    _markProvidersRegistered();
    expect(_areProvidersRegistered()).toBe(true);
  });

  it('resets to false after _resetRuntimeForTests', () => {
    _markProvidersRegistered();
    _resetRuntimeForTests();
    expect(_areProvidersRegistered()).toBe(false);
  });
});

describe('reconfigureTelemetry', () => {
  it('applies non-provider-changing config without error', () => {
    expect(() => reconfigureTelemetry({ serviceName: 'updated', logLevel: 'warn' })).not.toThrow();
    expect(getRuntimeConfig().serviceName).toBe('updated');
  });

  it('rejects provider fields after providers are registered', () => {
    reconfigureTelemetry({ otelEnabled: false });
    _markProvidersRegistered();
    expect(() => reconfigureTelemetry({ otelEnabled: true })).toThrow(
      /provider-changing reconfiguration is unsupported/,
    );
    expect(getRuntimeConfig().otelEnabled).toBe(false);
  });

  it('rejects tracingEnabled changes after providers are registered', () => {
    reconfigureTelemetry({ tracingEnabled: false });
    _markProvidersRegistered();
    expect(() => reconfigureTelemetry({ tracingEnabled: true })).toThrow(
      /provider-changing reconfiguration is unsupported/,
    );
    expect(getRuntimeConfig().tracingEnabled).toBe(false);
  });

  it('rejects metricsEnabled changes after providers are registered', () => {
    reconfigureTelemetry({ metricsEnabled: false });
    _markProvidersRegistered();
    expect(() => reconfigureTelemetry({ metricsEnabled: true })).toThrow(
      /provider-changing reconfiguration is unsupported/,
    );
    expect(getRuntimeConfig().metricsEnabled).toBe(false);
  });

  it('allows provider field changes when providers are NOT registered', () => {
    reconfigureTelemetry({ otelEnabled: false });
    expect(() => reconfigureTelemetry({ otelEnabled: true })).not.toThrow();
  });

  it('allows non-provider field changes even when providers are registered', () => {
    reconfigureTelemetry({ otelEnabled: false });
    _markProvidersRegistered();
    expect(() => reconfigureTelemetry({ logLevel: 'debug' })).not.toThrow();
  });

  it('rejects otlpEndpoint changes after registration', () => {
    reconfigureTelemetry({ otlpEndpoint: 'http://old:4318' });
    _markProvidersRegistered();
    expect(() => reconfigureTelemetry({ otlpEndpoint: 'http://new:4318' })).toThrow(
      /provider-changing reconfiguration is unsupported/,
    );
    expect(getRuntimeConfig().otlpEndpoint).toBe('http://old:4318');
  });
});

describe('reconfigureTelemetry — otlpHeaders change after init triggers restart (kills StringLiteral otlpHeaders)', () => {
  it('rejects otlpHeaders changes after providers initialized', () => {
    reconfigureTelemetry({ otlpHeaders: { 'x-api-key': 'old' } });
    _markProvidersRegistered();
    expect(() => reconfigureTelemetry({ otlpHeaders: { 'x-api-key': 'new' } })).toThrow(
      /provider-changing reconfiguration is unsupported/,
    );
    expect(getRuntimeConfig().otlpHeaders).toEqual({ 'x-api-key': 'old' });
  });
});

describe('reconfigureTelemetry — provider change after init resets registered flag (kills StringLiteral on field list)', () => {
  it('providers remain registered after a rejected provider-changing reconfigure', () => {
    _markProvidersRegistered();
    expect(_areProvidersRegistered()).toBe(true);
    expect(() => reconfigureTelemetry({ otelEnabled: false })).toThrow();
    expect(_areProvidersRegistered()).toBe(true);
  });
});

describe('reconfigureTelemetry — provider lifecycle safety', () => {
  it('does not flush, shutdown, or clear providers when provider-field changes are rejected', () => {
    const flushFn = vi.fn().mockResolvedValue(undefined);
    const shutdownFn = vi.fn().mockResolvedValue(undefined);
    _storeRegisteredProviders([{ forceFlush: flushFn, shutdown: shutdownFn }]);
    _markProvidersRegistered();
    expect(() => reconfigureTelemetry({ otelEnabled: false })).toThrow(
      /provider-changing reconfiguration is unsupported/,
    );
    expect(flushFn).not.toHaveBeenCalled();
    expect(shutdownFn).not.toHaveBeenCalled();
    expect(_areProvidersRegistered()).toBe(true);
    expect(_getRegisteredProviders()).toHaveLength(1);
  });

  it('does NOT call flush/shutdown when provider fields are unchanged', async () => {
    const flushFn = vi.fn().mockResolvedValue(undefined);
    const shutdownFn = vi.fn().mockResolvedValue(undefined);
    reconfigureTelemetry({ otelEnabled: true });
    _storeRegisteredProviders([{ forceFlush: flushFn, shutdown: shutdownFn }]);
    _markProvidersRegistered();
    // Change a non-provider field
    reconfigureTelemetry({ logLevel: 'debug' });
    await new Promise((r) => setTimeout(r, 50));
    expect(flushFn).not.toHaveBeenCalled();
    expect(shutdownFn).not.toHaveBeenCalled();
    // Providers should still be registered
    expect(_areProvidersRegistered()).toBe(true);
  });

  it('JSON.stringify deep comparison detects equivalent objects as unchanged', () => {
    // Same content, different references — should NOT trigger restart
    const flushFn = vi.fn().mockResolvedValue(undefined);
    reconfigureTelemetry({ otlpHeaders: { key: 'value' } });
    _storeRegisteredProviders([{ forceFlush: flushFn }]);
    _markProvidersRegistered();
    reconfigureTelemetry({ otlpHeaders: { key: 'value' } });
    expect(flushFn).not.toHaveBeenCalled();
    expect(_areProvidersRegistered()).toBe(true);
  });

  it('JSON.stringify deep comparison detects different objects as rejected provider changes', () => {
    const flushFn = vi.fn().mockResolvedValue(undefined);
    reconfigureTelemetry({ otlpHeaders: { key: 'old' } });
    _storeRegisteredProviders([{ forceFlush: flushFn }]);
    _markProvidersRegistered();
    expect(() => reconfigureTelemetry({ otlpHeaders: { key: 'new' } })).toThrow(
      /provider-changing reconfiguration is unsupported/,
    );
    expect(flushFn).not.toHaveBeenCalled();
  });

  it('rejects provider-changing reconfigure even when the registered provider list is empty', () => {
    _storeRegisteredProviders([]);
    _markProvidersRegistered();
    expect(() => reconfigureTelemetry({ otelEnabled: false })).toThrow(
      /provider-changing reconfiguration is unsupported/,
    );
  });

  it('does not clear stored providers when _providersRegistered is false (kills ConditionalExpression→true)', () => {
    // Store providers but do NOT mark as registered
    const provider = { forceFlush: vi.fn().mockResolvedValue(undefined) };
    _storeRegisteredProviders([provider]);
    // _providersRegistered is false; change a provider field
    reconfigureTelemetry({ otelEnabled: true });
    // Providers should still be stored (not cleared by the shutdown path)
    expect(_getRegisteredProviders()).toHaveLength(1);
  });

  it('otlpHeaders specifically triggers rejection (kills StringLiteral→"" on field name)', () => {
    reconfigureTelemetry({ otlpHeaders: { old: 'val' } });
    const flushFn = vi.fn().mockResolvedValue(undefined);
    _storeRegisteredProviders([{ forceFlush: flushFn }]);
    _markProvidersRegistered();
    expect(() => reconfigureTelemetry({ otlpHeaders: { new: 'val' } })).toThrow(
      /provider-changing reconfiguration is unsupported/,
    );
    expect(_areProvidersRegistered()).toBe(true);
    expect(_getRegisteredProviders()).toHaveLength(1);
  });

  it('otlpEndpoint specifically triggers rejection (kills StringLiteral→"" on field name)', () => {
    reconfigureTelemetry({ otlpEndpoint: 'http://old:4318' });
    const flushFn = vi.fn().mockResolvedValue(undefined);
    _storeRegisteredProviders([{ forceFlush: flushFn }]);
    _markProvidersRegistered();
    expect(() => reconfigureTelemetry({ otlpEndpoint: 'http://new:4318' })).toThrow(
      /provider-changing reconfiguration is unsupported/,
    );
    expect(_areProvidersRegistered()).toBe(true);
    expect(_getRegisteredProviders()).toHaveLength(1);
  });
});
