// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: AGPL-3.0-or-later
// @vitest-environment node

/**
 * registerOtelProviders — covers src/otel.ts which is excluded from the default
 * happy-dom test environment.
 *
 * All OTEL peer deps are mocked so tests work without a live OTLP endpoint and
 * without incurring real network I/O. Provider globals are fully disabled in
 * afterEach so repeated setGlobalTracerProvider/setGlobalMeterProvider calls
 * do not trigger OTel diagnostic warnings in subsequent tests.
 *
 * vitest 4.x requires mockImplementation (not mockReturnValue) for class constructors.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { context, metrics, trace } from '@opentelemetry/api';

vi.mock('@opentelemetry/sdk-trace-base', () => ({
  BasicTracerProvider: vi.fn(),
  BatchSpanProcessor: vi.fn(),
}));
vi.mock('@opentelemetry/exporter-trace-otlp-http', () => ({
  OTLPTraceExporter: vi.fn(),
}));
vi.mock('@opentelemetry/resources', () => ({
  resourceFromAttributes: vi.fn().mockReturnValue({}),
}));
vi.mock('@opentelemetry/sdk-metrics', () => ({
  MeterProvider: vi.fn(),
  PeriodicExportingMetricReader: vi.fn(),
}));
vi.mock('@opentelemetry/exporter-metrics-otlp-http', () => ({
  OTLPMetricExporter: vi.fn(),
}));

import { BasicTracerProvider, BatchSpanProcessor } from '@opentelemetry/sdk-trace-base';
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-http';
import { resourceFromAttributes } from '@opentelemetry/resources';
import { MeterProvider, PeriodicExportingMetricReader } from '@opentelemetry/sdk-metrics';
import { OTLPMetricExporter } from '@opentelemetry/exporter-metrics-otlp-http';
import { _resetConfig, getConfig, setupTelemetry } from '../../src/config';
import {
  _areProvidersRegistered,
  _getRegisteredProviders,
  _resetRuntimeForTests,
} from '../../src/runtime';
import { registerOtelProviders } from '../../src/otel.js';

// Minimal stubs that satisfy OTel API interface checks for provider registration.
const makeTracerStub = () => ({
  getTracer: vi.fn().mockReturnValue({ startSpan: vi.fn(), startActiveSpan: vi.fn() }),
  shutdown: vi.fn().mockResolvedValue(undefined),
  forceFlush: vi.fn().mockResolvedValue(undefined),
});
const makeMeterStub = () => ({
  getMeter: vi.fn().mockReturnValue({ createCounter: vi.fn() }),
  shutdown: vi.fn().mockResolvedValue(undefined),
  forceFlush: vi.fn().mockResolvedValue(undefined),
});

describe('registerOtelProviders', () => {
  beforeEach(() => {
    _resetConfig();
    _resetRuntimeForTests();
    vi.clearAllMocks();
    // vitest 4.x: use mockImplementation (not mockReturnValue) for class constructors.
    // eslint-disable-next-line prefer-arrow-callback
    vi.mocked(BasicTracerProvider).mockImplementation(function () {
      return makeTracerStub();
    } as never);
    // eslint-disable-next-line prefer-arrow-callback
    vi.mocked(BatchSpanProcessor).mockImplementation(function () {
      return {};
    } as never);
    // eslint-disable-next-line prefer-arrow-callback
    vi.mocked(OTLPTraceExporter).mockImplementation(function () {
      return {};
    } as never);
    // eslint-disable-next-line prefer-arrow-callback
    vi.mocked(MeterProvider).mockImplementation(function () {
      return makeMeterStub();
    } as never);
    // eslint-disable-next-line prefer-arrow-callback
    vi.mocked(PeriodicExportingMetricReader).mockImplementation(function () {
      return {};
    } as never);
    // eslint-disable-next-line prefer-arrow-callback
    vi.mocked(OTLPMetricExporter).mockImplementation(function () {
      return {};
    } as never);
  });

  afterEach(() => {
    // Use disable() to fully clear global provider state so subsequent
    // setGlobalTracerProvider / setGlobalMeterProvider calls start fresh.
    trace.disable();
    metrics.disable();
    context.disable();
    _resetConfig();
    _resetRuntimeForTests();
  });

  it('is a no-op when otelEnabled is false', async () => {
    setupTelemetry({ serviceName: 'test', otelEnabled: false });
    await registerOtelProviders(getConfig());
    expect(_areProvidersRegistered()).toBe(false);
    expect(vi.mocked(OTLPTraceExporter)).not.toHaveBeenCalled();
    expect(vi.mocked(OTLPMetricExporter)).not.toHaveBeenCalled();
  });

  it('constructs exporters with default endpoint and empty headers when neither is configured', async () => {
    // Pass undefined explicitly so the env-derived OTEL_EXPORTER_OTLP_ENDPOINT is overridden.
    setupTelemetry({
      serviceName: 'my-svc',
      otelEnabled: true,
      otlpEndpoint: undefined,
      otlpHeaders: undefined,
    });
    await registerOtelProviders(getConfig());
    expect(vi.mocked(OTLPTraceExporter)).toHaveBeenCalledWith({
      url: 'http://localhost:4318/v1/traces',
      headers: {},
    });
    expect(vi.mocked(OTLPMetricExporter)).toHaveBeenCalledWith({
      url: 'http://localhost:4318/v1/metrics',
      headers: {},
    });
    expect(_areProvidersRegistered()).toBe(true);
    expect(_getRegisteredProviders()).toHaveLength(2);
  });

  it('passes provided otlpEndpoint and otlpHeaders to both exporters', async () => {
    setupTelemetry({
      serviceName: 'my-svc',
      otelEnabled: true,
      otlpEndpoint: 'http://otel-collector:4318',
      otlpHeaders: { Authorization: 'Bearer secret' },
    });
    await registerOtelProviders(getConfig());
    expect(vi.mocked(OTLPTraceExporter)).toHaveBeenCalledWith({
      url: 'http://otel-collector:4318/v1/traces',
      headers: { Authorization: 'Bearer secret' },
    });
    expect(vi.mocked(OTLPMetricExporter)).toHaveBeenCalledWith({
      url: 'http://otel-collector:4318/v1/metrics',
      headers: { Authorization: 'Bearer secret' },
    });
  });

  it('passes service resource attributes to resourceFromAttributes', async () => {
    setupTelemetry({ serviceName: 'attr-svc', otelEnabled: true });
    await registerOtelProviders(getConfig());
    expect(vi.mocked(resourceFromAttributes)).toHaveBeenCalledWith({
      'service.name': 'attr-svc',
      'deployment.environment': 'development',
      'service.version': 'unknown',
    });
  });

  it('wires BatchSpanProcessor with the trace exporter', async () => {
    setupTelemetry({ serviceName: 'test', otelEnabled: true });
    const fakeExporter = { fake: 'exporter' };
    // eslint-disable-next-line prefer-arrow-callback
    vi.mocked(OTLPTraceExporter).mockImplementation(function () {
      return fakeExporter;
    } as never);
    await registerOtelProviders(getConfig());
    expect(vi.mocked(BatchSpanProcessor)).toHaveBeenCalledWith(fakeExporter);
  });

  it('wires PeriodicExportingMetricReader with the metrics exporter', async () => {
    setupTelemetry({ serviceName: 'test', otelEnabled: true });
    const fakeExporter = { fake: 'metrics-exporter' };
    // eslint-disable-next-line prefer-arrow-callback
    vi.mocked(OTLPMetricExporter).mockImplementation(function () {
      return fakeExporter;
    } as never);
    await registerOtelProviders(getConfig());
    expect(vi.mocked(PeriodicExportingMetricReader)).toHaveBeenCalledWith({
      exporter: fakeExporter,
    });
  });

  it('warns and continues to metrics when trace SDK throws', async () => {
    vi.mocked(OTLPTraceExporter).mockImplementation(function () {
      throw new Error('trace peer dep missing');
    } as never);
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    setupTelemetry({ serviceName: 'test', otelEnabled: true });
    await registerOtelProviders(getConfig());
    expect(warnSpy).toHaveBeenCalledWith(
      expect.stringContaining('OTEL trace setup failed'),
      expect.any(Error),
    );
    expect(vi.mocked(OTLPMetricExporter)).toHaveBeenCalled();
    expect(_areProvidersRegistered()).toBe(true);
    expect(_getRegisteredProviders()).toHaveLength(1);
    warnSpy.mockRestore();
  });

  it('warns and still marks providers registered when metrics SDK throws', async () => {
    vi.mocked(OTLPMetricExporter).mockImplementation(function () {
      throw new Error('metrics peer dep missing');
    } as never);
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    setupTelemetry({ serviceName: 'test', otelEnabled: true });
    await registerOtelProviders(getConfig());
    expect(warnSpy).toHaveBeenCalledWith(
      expect.stringContaining('OTEL metrics setup failed'),
      expect.any(Error),
    );
    expect(vi.mocked(OTLPTraceExporter)).toHaveBeenCalled();
    expect(_areProvidersRegistered()).toBe(true);
    warnSpy.mockRestore();
  });
});
