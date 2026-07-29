// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { metrics, trace } from '@opentelemetry/api';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import {
  _isLiveMeterProviderInstalled,
  _isLiveTracerProvider,
  _isLiveTracerProviderInstalled,
} from '../src/otel-probe.js';
import { liveMeterProvider, liveTracerProvider } from './fixtures/live-providers.js';

beforeEach(() => {
  trace.disable();
  metrics.disable();
});
afterEach(() => {
  trace.disable();
  metrics.disable();
});

describe('_isLiveTracerProvider', () => {
  it('accepts a provider carrying the full flush/shutdown lifecycle', () => {
    expect(_isLiveTracerProvider(liveTracerProvider() as never)).toBe(true);
  });

  it('rejects a bare TracerProvider with neither lifecycle method', () => {
    expect(_isLiveTracerProvider({ getTracer: () => ({}) } as never)).toBe(false);
  });

  it('rejects a provider that can flush but not shut down', () => {
    expect(
      _isLiveTracerProvider({ getTracer: () => ({}), forceFlush: async () => {} } as never),
    ).toBe(false);
  });

  it('rejects a provider that can shut down but not flush', () => {
    expect(
      _isLiveTracerProvider({ getTracer: () => ({}), shutdown: async () => {} } as never),
    ).toBe(false);
  });

  it('rejects non-callable lifecycle properties', () => {
    expect(
      _isLiveTracerProvider({ getTracer: () => ({}), forceFlush: true, shutdown: true } as never),
    ).toBe(false);
  });

  it('unwraps a proxy provider and judges its delegate', () => {
    const delegate = liveTracerProvider();
    expect(
      _isLiveTracerProvider({ getTracer: () => ({}), getDelegate: () => delegate } as never),
    ).toBe(true);
  });

  it('rejects a proxy provider whose delegate is a no-op', () => {
    const delegate = { getTracer: () => ({}) };
    expect(
      _isLiveTracerProvider({ getTracer: () => ({}), getDelegate: () => delegate } as never),
    ).toBe(false);
  });
});

describe('_isLiveTracerProviderInstalled', () => {
  it('is false when nothing owns the tracer global', () => {
    expect(_isLiveTracerProviderInstalled()).toBe(false);
  });

  it('is true for a provider registered by anyone — not only by registerOtelProviders', () => {
    expect(trace.setGlobalTracerProvider(liveTracerProvider() as never)).toBe(true);
    expect(_isLiveTracerProviderInstalled()).toBe(true);
  });

  it('is false again once the global is disabled', () => {
    trace.setGlobalTracerProvider(liveTracerProvider() as never);
    trace.disable();
    expect(_isLiveTracerProviderInstalled()).toBe(false);
  });
});

describe('_isLiveMeterProviderInstalled', () => {
  it('is false when nothing owns the meter global', () => {
    expect(_isLiveMeterProviderInstalled()).toBe(false);
  });

  it('is true for a provider registered by anyone — not only by registerOtelProviders', () => {
    expect(metrics.setGlobalMeterProvider(liveMeterProvider() as never)).toBe(true);
    expect(_isLiveMeterProviderInstalled()).toBe(true);
  });

  it('rejects a meter provider that can flush but not shut down', () => {
    metrics.setGlobalMeterProvider({ getMeter: () => ({}), forceFlush: async () => {} } as never);
    expect(_isLiveMeterProviderInstalled()).toBe(false);
  });

  it('rejects a meter provider that can shut down but not flush', () => {
    metrics.setGlobalMeterProvider({ getMeter: () => ({}), shutdown: async () => {} } as never);
    expect(_isLiveMeterProviderInstalled()).toBe(false);
  });

  it('is false again once the global is disabled', () => {
    metrics.setGlobalMeterProvider(liveMeterProvider() as never);
    metrics.disable();
    expect(_isLiveMeterProviderInstalled()).toBe(false);
  });
});
