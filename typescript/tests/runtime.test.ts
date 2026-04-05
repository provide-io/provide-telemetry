// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { _resetConfig } from '../src/config';
import {
  _areProvidersRegistered,
  _markProvidersRegistered,
  _resetRuntimeForTests,
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
});

describe('updateRuntimeConfig', () => {
  it('merges overrides into active config', () => {
    updateRuntimeConfig({ serviceName: 'my-service', logLevel: 'debug' });
    const cfg = getRuntimeConfig();
    expect(cfg.serviceName).toBe('my-service');
    expect(cfg.logLevel).toBe('debug');
  });

  it('persists across subsequent getRuntimeConfig calls', () => {
    updateRuntimeConfig({ version: '2.0.0' });
    expect(getRuntimeConfig().version).toBe('2.0.0');
  });
});

describe('reloadRuntimeFromEnv', () => {
  it('resets to env-derived config', () => {
    updateRuntimeConfig({ serviceName: 'overridden' });
    reloadRuntimeFromEnv();
    // After reload, serviceName should come from env (not 'overridden')
    const cfg = getRuntimeConfig();
    expect(cfg.serviceName).toBeDefined(); // just verify it doesn't throw
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
    updateRuntimeConfig({ otelEnabled: false });
    _markProvidersRegistered();
    expect(() => reconfigureTelemetry({ otelEnabled: true })).not.toThrow();
    expect(getRuntimeConfig().otelEnabled).toBe(true);
  });

  it('allows provider field changes when providers are NOT registered', () => {
    updateRuntimeConfig({ otelEnabled: false });
    expect(() => reconfigureTelemetry({ otelEnabled: true })).not.toThrow();
  });

  it('allows non-provider field changes even when providers are registered', () => {
    updateRuntimeConfig({ otelEnabled: false });
    _markProvidersRegistered();
    expect(() => reconfigureTelemetry({ logLevel: 'debug' })).not.toThrow();
  });

  it('allows otlpEndpoint to change after registration and applies new value', () => {
    updateRuntimeConfig({ otlpEndpoint: 'http://old:4318' });
    _markProvidersRegistered();
    expect(() => reconfigureTelemetry({ otlpEndpoint: 'http://new:4318' })).not.toThrow();
    expect(getRuntimeConfig().otlpEndpoint).toBe('http://new:4318');
  });
});

describe('reloadRuntimeFromEnv — resets config (kills BlockStatement)', () => {
  it('clears custom serviceName after reload', () => {
    updateRuntimeConfig({ serviceName: 'overridden-service' });
    expect(getRuntimeConfig().serviceName).toBe('overridden-service');
    reloadRuntimeFromEnv();
    // After reload, should come from env (default when no env var set)
    expect(getRuntimeConfig().serviceName).toBe('provide-service');
  });

  it('re-reads env-derived config after reload', () => {
    updateRuntimeConfig({ logLevel: 'error', version: '99.0.0' });
    reloadRuntimeFromEnv();
    expect(getRuntimeConfig().logLevel).toBe('info');
    expect(getRuntimeConfig().version).toBe('unknown');
  });
});

describe('reconfigureTelemetry — otlpHeaders change after init triggers restart (kills StringLiteral otlpHeaders)', () => {
  it('allows otlpHeaders to change after providers initialized (restart path)', () => {
    updateRuntimeConfig({ otlpHeaders: { 'x-api-key': 'old' } });
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
