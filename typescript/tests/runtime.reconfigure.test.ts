// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { _resetConfig } from '../src/config';
import {
  _areProvidersRegistered,
  _clearProviderState,
  _getRegisteredProviders,
  _markProvidersRegistered,
  _resetRuntimeForTests,
  _setProviderSignalInstalled,
  _storeRegisteredProviders,
  getRuntimeConfig,
  getRuntimeStatus,
  reconfigureTelemetry,
} from '../src/runtime';

beforeEach(() => {
  _resetRuntimeForTests();
  _resetConfig();
});
afterEach(() => {
  _resetRuntimeForTests();
  _resetConfig();
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

  it('rejects service identity changes after providers are registered', () => {
    reconfigureTelemetry({
      serviceName: 'old-service',
      environment: 'dev',
      version: '1.0.0',
    });
    _markProvidersRegistered();

    expect(() =>
      reconfigureTelemetry({
        serviceName: 'new-service',
        environment: 'prod',
        version: '2.0.0',
      }),
    ).toThrow(/provider-changing reconfiguration is unsupported/);
    expect(getRuntimeConfig().serviceName).toBe('old-service');
    expect(getRuntimeConfig().environment).toBe('dev');
    expect(getRuntimeConfig().version).toBe('1.0.0');
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

describe('reconfigureTelemetry — per-signal OTLP fields trigger provider-change rejection', () => {
  it('rejects otlpLogsEndpoint change after providers registered', () => {
    reconfigureTelemetry({ otlpLogsEndpoint: 'http://logs-old:4318' });
    _markProvidersRegistered();
    expect(() => reconfigureTelemetry({ otlpLogsEndpoint: 'http://logs-new:4318' })).toThrow(
      /provider-changing reconfiguration is unsupported/,
    );
    expect(getRuntimeConfig().otlpLogsEndpoint).toBe('http://logs-old:4318');
  });

  it('rejects otlpLogsHeaders change after providers registered', () => {
    reconfigureTelemetry({ otlpLogsHeaders: { key: 'old' } });
    _markProvidersRegistered();
    expect(() => reconfigureTelemetry({ otlpLogsHeaders: { key: 'new' } })).toThrow(
      /provider-changing reconfiguration is unsupported/,
    );
    expect(getRuntimeConfig().otlpLogsHeaders).toEqual({ key: 'old' });
  });

  it('rejects otlpTracesHeaders change after providers registered', () => {
    reconfigureTelemetry({ otlpTracesHeaders: { key: 'old' } });
    _markProvidersRegistered();
    expect(() => reconfigureTelemetry({ otlpTracesHeaders: { key: 'new' } })).toThrow(
      /provider-changing reconfiguration is unsupported/,
    );
    expect(getRuntimeConfig().otlpTracesHeaders).toEqual({ key: 'old' });
  });

  it('rejects otlpMetricsEndpoint change after providers registered', () => {
    reconfigureTelemetry({ otlpMetricsEndpoint: 'http://metrics-old:4318' });
    _markProvidersRegistered();
    expect(() => reconfigureTelemetry({ otlpMetricsEndpoint: 'http://metrics-new:4318' })).toThrow(
      /provider-changing reconfiguration is unsupported/,
    );
    expect(getRuntimeConfig().otlpMetricsEndpoint).toBe('http://metrics-old:4318');
  });

  it('rejects otlpMetricsHeaders change after providers registered', () => {
    reconfigureTelemetry({ otlpMetricsHeaders: { key: 'old' } });
    _markProvidersRegistered();
    expect(() => reconfigureTelemetry({ otlpMetricsHeaders: { key: 'new' } })).toThrow(
      /provider-changing reconfiguration is unsupported/,
    );
    expect(getRuntimeConfig().otlpMetricsHeaders).toEqual({ key: 'old' });
  });
});

describe('_clearProviderState — resets all provider state', () => {
  it('clears _providersRegistered flag', () => {
    _markProvidersRegistered();
    _clearProviderState();
    expect(_areProvidersRegistered()).toBe(false);
  });

  it('clears _registeredProviders list', () => {
    _storeRegisteredProviders([{ forceFlush: vi.fn().mockResolvedValue(undefined) }]);
    _clearProviderState();
    expect(_getRegisteredProviders()).toHaveLength(0);
  });

  it('resets logs provider signal to false', () => {
    _setProviderSignalInstalled('logs', true);
    _clearProviderState();
    expect(getRuntimeStatus().providers.logs).toBe(false);
    expect(getRuntimeStatus().fallback.logs).toBe(true);
  });

  it('resets traces provider signal to false', () => {
    _setProviderSignalInstalled('traces', true);
    _clearProviderState();
    expect(getRuntimeStatus().providers.traces).toBe(false);
    expect(getRuntimeStatus().fallback.traces).toBe(true);
  });

  it('resets metrics provider signal to false', () => {
    _setProviderSignalInstalled('metrics', true);
    _clearProviderState();
    expect(getRuntimeStatus().providers.metrics).toBe(false);
    expect(getRuntimeStatus().fallback.metrics).toBe(true);
  });

  it('resets all three signals and registered flag simultaneously', () => {
    _setProviderSignalInstalled('logs', true);
    _setProviderSignalInstalled('traces', true);
    _setProviderSignalInstalled('metrics', true);
    _markProvidersRegistered();
    _storeRegisteredProviders([{ forceFlush: vi.fn().mockResolvedValue(undefined) }]);
    _clearProviderState();
    expect(_areProvidersRegistered()).toBe(false);
    expect(_getRegisteredProviders()).toHaveLength(0);
    expect(getRuntimeStatus().providers).toEqual({ logs: false, traces: false, metrics: false });
    expect(getRuntimeStatus().fallback).toEqual({ logs: true, traces: true, metrics: true });
  });
});
