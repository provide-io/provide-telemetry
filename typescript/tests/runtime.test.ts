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
  _storeRegisteredProviders,
  getRuntimeConfig,
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
  it('returns a config derived from env when nothing set', () => {
    const cfg = getRuntimeConfig();
    expect(cfg.serviceName).toBeDefined();
    expect(cfg.logLevel).toBeDefined();
    expect(typeof cfg.otelEnabled).toBe('boolean');
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
    };
    updateRuntimeConfig(overrides);
    const cfg = getRuntimeConfig();
    expect(cfg.samplingLogsRate).toBe(0.5);
    expect(cfg.backpressureLogsMaxsize).toBe(100);
    expect(cfg.exporterLogsRetries).toBe(3);
    expect(cfg.securityMaxAttrValueLength).toBe(512);
    expect(cfg.sloEnableRedMetrics).toBe(true);
    expect(cfg.piiMaxDepth).toBe(4);
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

  it('allows provider fields to change after providers are registered (restart)', () => {
    reconfigureTelemetry({ otelEnabled: false });
    _markProvidersRegistered();
    expect(() => reconfigureTelemetry({ otelEnabled: true })).not.toThrow();
    expect(getRuntimeConfig().otelEnabled).toBe(true);
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

  it('allows otlpEndpoint to change after registration and applies new value', () => {
    reconfigureTelemetry({ otlpEndpoint: 'http://old:4318' });
    _markProvidersRegistered();
    expect(() => reconfigureTelemetry({ otlpEndpoint: 'http://new:4318' })).not.toThrow();
    expect(getRuntimeConfig().otlpEndpoint).toBe('http://new:4318');
  });
});

describe('reconfigureTelemetry — otlpHeaders change after init triggers restart (kills StringLiteral otlpHeaders)', () => {
  it('allows otlpHeaders to change after providers initialized (restart path)', () => {
    reconfigureTelemetry({ otlpHeaders: { 'x-api-key': 'old' } });
    _markProvidersRegistered();
    expect(() => reconfigureTelemetry({ otlpHeaders: { 'x-api-key': 'new' } })).not.toThrow();
    expect(getRuntimeConfig().otlpHeaders).toEqual({ 'x-api-key': 'new' });
  });
});

describe('reconfigureTelemetry — provider change after init resets registered flag (kills StringLiteral on field list)', () => {
  it('providers are no longer registered after a provider-changing reconfigure', () => {
    _markProvidersRegistered();
    expect(_areProvidersRegistered()).toBe(true);
    reconfigureTelemetry({ otelEnabled: true });
    // After restart path, providers are re-setup; _providersRegistered resets then setupTelemetry runs
    // Since there are no real providers in tests, it stays false after reset
    expect(_areProvidersRegistered()).toBe(false);
  });
});

describe('reconfigureTelemetry — mock provider flush/shutdown calls', () => {
  it('calls forceFlush then shutdown on registered providers when provider fields change', async () => {
    const flushFn = vi.fn().mockResolvedValue(undefined);
    const shutdownFn = vi.fn().mockResolvedValue(undefined);
    _storeRegisteredProviders([{ forceFlush: flushFn, shutdown: shutdownFn }]);
    _markProvidersRegistered();
    reconfigureTelemetry({ otelEnabled: true });
    // Wait for fire-and-forget promises
    await new Promise((r) => setTimeout(r, 50));
    expect(flushFn).toHaveBeenCalledTimes(1);
    expect(shutdownFn).toHaveBeenCalledTimes(1);
  });

  it('handles providers with only forceFlush (no shutdown)', async () => {
    const flushFn = vi.fn().mockResolvedValue(undefined);
    _storeRegisteredProviders([{ forceFlush: flushFn }]);
    _markProvidersRegistered();
    expect(() => reconfigureTelemetry({ otelEnabled: true })).not.toThrow();
    await new Promise((r) => setTimeout(r, 50));
    expect(flushFn).toHaveBeenCalledTimes(1);
  });

  it('handles providers with only shutdown (no forceFlush)', async () => {
    const shutdownFn = vi.fn().mockResolvedValue(undefined);
    _storeRegisteredProviders([{ shutdown: shutdownFn }]);
    _markProvidersRegistered();
    expect(() => reconfigureTelemetry({ otelEnabled: true })).not.toThrow();
    await new Promise((r) => setTimeout(r, 50));
    expect(shutdownFn).toHaveBeenCalledTimes(1);
  });

  it('handles providers with neither forceFlush nor shutdown', async () => {
    _storeRegisteredProviders([{}]);
    _markProvidersRegistered();
    expect(() => reconfigureTelemetry({ otelEnabled: true })).not.toThrow();
  });

  it('does NOT call flush/shutdown when provider fields are unchanged', async () => {
    const flushFn = vi.fn().mockResolvedValue(undefined);
    const shutdownFn = vi.fn().mockResolvedValue(undefined);
    reconfigureTelemetry({ otelEnabled: false });
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

  it('clears registered providers list after provider-changing reconfigure', () => {
    _storeRegisteredProviders([{ forceFlush: vi.fn().mockResolvedValue(undefined) }]);
    _markProvidersRegistered();
    reconfigureTelemetry({ otelEnabled: true });
    expect(_getRegisteredProviders()).toHaveLength(0);
  });

  it('flushes and shuts down multiple providers', async () => {
    const flush1 = vi.fn().mockResolvedValue(undefined);
    const shutdown1 = vi.fn().mockResolvedValue(undefined);
    const flush2 = vi.fn().mockResolvedValue(undefined);
    const shutdown2 = vi.fn().mockResolvedValue(undefined);
    _storeRegisteredProviders([
      { forceFlush: flush1, shutdown: shutdown1 },
      { forceFlush: flush2, shutdown: shutdown2 },
    ]);
    _markProvidersRegistered();
    reconfigureTelemetry({ otelEnabled: true });
    await new Promise((r) => setTimeout(r, 50));
    expect(flush1).toHaveBeenCalledTimes(1);
    expect(flush2).toHaveBeenCalledTimes(1);
    expect(shutdown1).toHaveBeenCalledTimes(1);
    expect(shutdown2).toHaveBeenCalledTimes(1);
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

  it('JSON.stringify deep comparison detects different objects as changed', async () => {
    const flushFn = vi.fn().mockResolvedValue(undefined);
    reconfigureTelemetry({ otlpHeaders: { key: 'old' } });
    _storeRegisteredProviders([{ forceFlush: flushFn }]);
    _markProvidersRegistered();
    reconfigureTelemetry({ otlpHeaders: { key: 'new' } });
    await new Promise((r) => setTimeout(r, 50));
    expect(flushFn).toHaveBeenCalledTimes(1);
  });

  it('empty providers array does not throw on provider-changing reconfigure', () => {
    _storeRegisteredProviders([]);
    _markProvidersRegistered();
    expect(() => reconfigureTelemetry({ otelEnabled: true })).not.toThrow();
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

  it('otlpHeaders specifically triggers restart (kills StringLiteral→"" on field name)', () => {
    reconfigureTelemetry({ otlpHeaders: { old: 'val' } });
    const flushFn = vi.fn().mockResolvedValue(undefined);
    _storeRegisteredProviders([{ forceFlush: flushFn }]);
    _markProvidersRegistered();
    // Only change otlpHeaders (not otelEnabled or otlpEndpoint)
    reconfigureTelemetry({ otlpHeaders: { new: 'val' } });
    // Providers should be cleared because otlpHeaders is in PROVIDER_CHANGING_FIELDS
    expect(_areProvidersRegistered()).toBe(false);
    expect(_getRegisteredProviders()).toHaveLength(0);
  });

  it('otlpEndpoint specifically triggers restart (kills StringLiteral→"" on field name)', () => {
    reconfigureTelemetry({ otlpEndpoint: 'http://old:4318' });
    const flushFn = vi.fn().mockResolvedValue(undefined);
    _storeRegisteredProviders([{ forceFlush: flushFn }]);
    _markProvidersRegistered();
    // Only change otlpEndpoint (not otelEnabled or otlpHeaders)
    reconfigureTelemetry({ otlpEndpoint: 'http://new:4318' });
    expect(_areProvidersRegistered()).toBe(false);
    expect(_getRegisteredProviders()).toHaveLength(0);
  });
});
