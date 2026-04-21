// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { context, metrics, trace } from '@opentelemetry/api';
import { logs } from '@opentelemetry/api-logs';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  type ShutdownableProvider,
  _areProvidersRegistered,
  _getRegisteredProviders,
  _markProvidersRegistered,
  _resetRuntimeForTests,
  _storeRegisteredProviders,
  reconfigureTelemetry,
} from '../src/runtime';
import { _resetConfig } from '../src/config';
import { shutdownTelemetry } from '../src/shutdown';
import { _getOtelLogProvider, _resetOtelLogProviderForTests, setupOtelLogProvider } from '../src/otel-logs';

beforeEach(() => _resetRuntimeForTests());
afterEach(() => {
  trace.disable();
  metrics.disable();
  context.disable();
  logs.disable();
  _resetOtelLogProviderForTests();
  _resetRuntimeForTests();
});

it('_resetRuntimeForTests clears all registered providers', () => {
  _storeRegisteredProviders([{ shutdown: vi.fn() }]);
  _resetRuntimeForTests();
  expect(_getRegisteredProviders()).toHaveLength(0);
});

describe('shutdownTelemetry', () => {
  it('resolves immediately when no providers have been registered', async () => {
    await expect(shutdownTelemetry()).resolves.toBeUndefined();
  });

  it('calls forceFlush then shutdown on each registered provider', async () => {
    const order: string[] = [];
    const provider: ShutdownableProvider = {
      forceFlush: vi.fn().mockImplementation(async () => {
        order.push('flush');
      }),
      shutdown: vi.fn().mockImplementation(async () => {
        order.push('shutdown');
      }),
    };
    _storeRegisteredProviders([provider]);
    await shutdownTelemetry();
    expect(provider.forceFlush).toHaveBeenCalledOnce();
    expect(provider.shutdown).toHaveBeenCalledOnce();
    expect(order).toEqual(['flush', 'shutdown']);
  });

  it('flushes and shuts down all providers when multiple are registered', async () => {
    const a: ShutdownableProvider = {
      forceFlush: vi.fn().mockResolvedValue(undefined),
      shutdown: vi.fn().mockResolvedValue(undefined),
    };
    const b: ShutdownableProvider = {
      forceFlush: vi.fn().mockResolvedValue(undefined),
      shutdown: vi.fn().mockResolvedValue(undefined),
    };
    _storeRegisteredProviders([a, b]);
    await shutdownTelemetry();
    expect(a.forceFlush).toHaveBeenCalledOnce();
    expect(a.shutdown).toHaveBeenCalledOnce();
    expect(b.forceFlush).toHaveBeenCalledOnce();
    expect(b.shutdown).toHaveBeenCalledOnce();
  });

  it('still calls shutdown when forceFlush rejects', async () => {
    const provider: ShutdownableProvider = {
      forceFlush: vi.fn().mockRejectedValue(new Error('flush failed')),
      shutdown: vi.fn().mockResolvedValue(undefined),
    };
    _storeRegisteredProviders([provider]);
    await expect(shutdownTelemetry()).resolves.toBeUndefined();
    expect(provider.shutdown).toHaveBeenCalledOnce();
  });

  it('calls shutdown on all providers even when one shutdown rejects', async () => {
    const a: ShutdownableProvider = {
      shutdown: vi.fn().mockRejectedValue(new Error('a failed')),
    };
    const b: ShutdownableProvider = {
      shutdown: vi.fn().mockResolvedValue(undefined),
    };
    _storeRegisteredProviders([a, b]);
    await expect(shutdownTelemetry()).resolves.toBeUndefined();
    expect(a.shutdown).toHaveBeenCalledOnce();
    expect(b.shutdown).toHaveBeenCalledOnce();
  });

  it('works with a provider that has no forceFlush method', async () => {
    const provider: ShutdownableProvider = {
      shutdown: vi.fn().mockResolvedValue(undefined),
    };
    _storeRegisteredProviders([provider]);
    await expect(shutdownTelemetry()).resolves.toBeUndefined();
    expect(provider.shutdown).toHaveBeenCalledOnce();
  });

  it('works with a provider that has no shutdown method', async () => {
    const provider: ShutdownableProvider = {
      forceFlush: vi.fn().mockResolvedValue(undefined),
    };
    _storeRegisteredProviders([provider]);
    await expect(shutdownTelemetry()).resolves.toBeUndefined();
    expect(provider.forceFlush).toHaveBeenCalledOnce();
  });

  it('awaits forceFlush promise resolution before continuing', async () => {
    let flushed = false;
    const provider: ShutdownableProvider = {
      forceFlush: () =>
        new Promise<void>((resolve) =>
          setTimeout(() => {
            flushed = true;
            resolve();
          }, 0),
        ),
      shutdown: vi.fn().mockResolvedValue(undefined),
    };
    _storeRegisteredProviders([provider]);
    await shutdownTelemetry();
    expect(flushed).toBe(true);
  });

  it('awaits shutdown promise resolution before completing', async () => {
    let shut = false;
    const provider: ShutdownableProvider = {
      shutdown: () =>
        new Promise<void>((resolve) =>
          setTimeout(() => {
            shut = true;
            resolve();
          }, 0),
        ),
    };
    _storeRegisteredProviders([provider]);
    await shutdownTelemetry();
    expect(shut).toBe(true);
  });

  it('clears the OTEL log bridge singleton after shutdown', async () => {
    await setupOtelLogProvider({
      serviceName: 'shutdown-test',
      otelEnabled: true,
      otlpEndpoint: 'http://localhost:4318',
    } as never);
    expect(_getOtelLogProvider()).not.toBeNull();
    await shutdownTelemetry();
    expect(_getOtelLogProvider()).toBeNull();
  });

  it('clears installed OTEL API globals after shutdown', async () => {
    const contextManager = {
      active: vi.fn(),
      with: vi.fn((_ctx, fn, thisArg, ...args) => fn.apply(thisArg, args)),
      bind: vi.fn((_ctx, target) => target),
      enable: vi.fn(),
      disable: vi.fn(),
    };
    const tracerProvider = { getTracer: vi.fn() };
    const meterProvider = { getMeter: vi.fn() };
    const loggerProvider = { getLogger: vi.fn() };

    expect(context.setGlobalContextManager(contextManager as never)).toBe(true);
    expect(trace.setGlobalTracerProvider(tracerProvider as never)).toBe(true);
    expect(metrics.setGlobalMeterProvider(meterProvider as never)).toBe(true);
    expect(logs.setGlobalLoggerProvider(loggerProvider as never)).toBe(loggerProvider);

    await shutdownTelemetry();

    expect(contextManager.disable).toHaveBeenCalledOnce();
    expect(trace.setGlobalTracerProvider({ getTracer: vi.fn() } as never)).toBe(true);
    expect(metrics.setGlobalMeterProvider({ getMeter: vi.fn() } as never)).toBe(true);
    const replacementLoggerProvider = { getLogger: vi.fn() };
    expect(logs.setGlobalLoggerProvider(replacementLoggerProvider as never)).toBe(
      replacementLoggerProvider,
    );
  });
});

describe('shutdownTelemetry — clears provider registration state', () => {
  beforeEach(() => {
    _resetRuntimeForTests();
    _resetConfig();
  });
  afterEach(() => {
    _resetRuntimeForTests();
  });

  it('clears _providersRegistered after shutdown', async () => {
    _markProvidersRegistered();
    expect(_areProvidersRegistered()).toBe(true);
    await shutdownTelemetry();
    expect(_areProvidersRegistered()).toBe(false);
  });

  it('clears registered provider list after shutdown', async () => {
    _storeRegisteredProviders([{ shutdown: vi.fn() }]);
    await shutdownTelemetry();
    expect(_getRegisteredProviders()).toHaveLength(0);
  });

  it('allows provider-changing reconfigureTelemetry after shutdown', async () => {
    _markProvidersRegistered();
    await shutdownTelemetry();
    expect(() => reconfigureTelemetry({ otelEnabled: true })).not.toThrow();
  });
});
