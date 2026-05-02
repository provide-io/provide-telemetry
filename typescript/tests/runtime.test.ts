// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { _resetConfig, setupTelemetry } from '../src/config';
import type { RuntimeOverrides } from '../src/config';
import {
  _markProvidersRegistered,
  _resetRuntimeForTests,
  _setProviderSignalInstalled,
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

  it('applies strictEventName as a hot runtime field', () => {
    updateRuntimeConfig({ strictEventName: true });
    expect(getRuntimeConfig().strictEventName).toBe(true);
  });

  it('ignores undefined values in overrides', () => {
    updateRuntimeConfig({ samplingLogsRate: 0.5 });
    const before = getRuntimeConfig().samplingTracesRate;
    updateRuntimeConfig({ samplingLogsRate: undefined, samplingTracesRate: undefined });
    expect(getRuntimeConfig().samplingLogsRate).toBe(0.5);
    expect(getRuntimeConfig().samplingTracesRate).toBe(before);
  });

  it('ignores undefined values inside nested logging overrides', () => {
    updateRuntimeConfig({ logging: { logLevel: 'debug' } });
    updateRuntimeConfig({ logging: { logLevel: undefined, logFormat: 'json' } });
    const cfg = getRuntimeConfig();
    expect(cfg.logLevel).toBe('debug');
    expect(cfg.logFormat).toBe('json');
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

  it('warns on otlpLogsEndpoint cold-field drift (kills StringLiteral on _COLD_FIELDS entry)', () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    reconfigureTelemetry({ otlpLogsEndpoint: 'http://logs:4318' });
    reloadRuntimeFromEnv();
    expect(warnSpy).toHaveBeenCalledWith(
      '[provide-telemetry] runtime.cold_field_drift:',
      expect.stringContaining('otlpLogsEndpoint'),
      '— restart required to apply',
    );
    warnSpy.mockRestore();
  });

  it('warns on otlpLogsHeaders cold-field drift (kills StringLiteral on _COLD_FIELDS entry)', () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    reconfigureTelemetry({ otlpLogsHeaders: { 'x-log-key': 'val' } });
    reloadRuntimeFromEnv();
    expect(warnSpy).toHaveBeenCalledWith(
      '[provide-telemetry] runtime.cold_field_drift:',
      expect.stringContaining('otlpLogsHeaders'),
      '— restart required to apply',
    );
    warnSpy.mockRestore();
  });

  it('warns on otlpMetricsEndpoint cold-field drift (kills StringLiteral on _COLD_FIELDS entry)', () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    reconfigureTelemetry({ otlpMetricsEndpoint: 'http://metrics:4318' });
    reloadRuntimeFromEnv();
    expect(warnSpy).toHaveBeenCalledWith(
      '[provide-telemetry] runtime.cold_field_drift:',
      expect.stringContaining('otlpMetricsEndpoint'),
      '— restart required to apply',
    );
    warnSpy.mockRestore();
  });

  it('warns on otlpMetricsHeaders cold-field drift (kills StringLiteral on _COLD_FIELDS entry)', () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    reconfigureTelemetry({ otlpMetricsHeaders: { 'x-metrics-key': 'val' } });
    reloadRuntimeFromEnv();
    expect(warnSpy).toHaveBeenCalledWith(
      '[provide-telemetry] runtime.cold_field_drift:',
      expect.stringContaining('otlpMetricsHeaders'),
      '— restart required to apply',
    );
    warnSpy.mockRestore();
  });
});
