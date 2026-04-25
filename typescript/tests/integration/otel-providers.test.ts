// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
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
vi.mock('@opentelemetry/sdk-logs', () => ({
  LoggerProvider: vi.fn(),
  BatchLogRecordProcessor: vi.fn(),
}));
vi.mock('@opentelemetry/exporter-logs-otlp-http', () => ({
  OTLPLogExporter: vi.fn(),
}));
vi.mock('@opentelemetry/api-logs', () => ({
  logs: {
    setGlobalLoggerProvider: vi.fn(),
    getLogger: vi.fn(),
  },
}));

import { BasicTracerProvider, BatchSpanProcessor } from '@opentelemetry/sdk-trace-base';
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-http';
import { resourceFromAttributes } from '@opentelemetry/resources';
import { MeterProvider, PeriodicExportingMetricReader } from '@opentelemetry/sdk-metrics';
import { OTLPMetricExporter } from '@opentelemetry/exporter-metrics-otlp-http';
import { LoggerProvider, BatchLogRecordProcessor } from '@opentelemetry/sdk-logs';
import { OTLPLogExporter } from '@opentelemetry/exporter-logs-otlp-http';
import { logs } from '@opentelemetry/api-logs';
import { _resetConfig, getConfig, setupTelemetry } from '../../src/config';
import {
  _areProvidersRegistered,
  _getRegisteredProviders,
  _resetRuntimeForTests,
} from '../../src/runtime';
import { _resetOtelLogProviderForTests } from '../../src/otel-logs';
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
const makeLogProviderStub = () => ({
  shutdown: vi.fn().mockResolvedValue(undefined),
  forceFlush: vi.fn().mockResolvedValue(undefined),
});

describe('registerOtelProviders', () => {
  beforeEach(() => {
    _resetConfig();
    _resetRuntimeForTests();
    _resetOtelLogProviderForTests();
    vi.clearAllMocks();
    // vitest 4.x: use mockImplementation (not mockReturnValue) for class constructors.
    vi.mocked(BasicTracerProvider).mockImplementation(function () {
      return makeTracerStub();
    } as never);
    vi.mocked(BatchSpanProcessor).mockImplementation(function () {
      return {};
    } as never);
    vi.mocked(OTLPTraceExporter).mockImplementation(function () {
      return {};
    } as never);
    vi.mocked(MeterProvider).mockImplementation(function () {
      return makeMeterStub();
    } as never);
    vi.mocked(PeriodicExportingMetricReader).mockImplementation(function () {
      return {};
    } as never);
    vi.mocked(OTLPMetricExporter).mockImplementation(function () {
      return {};
    } as never);
    vi.mocked(LoggerProvider).mockImplementation(function () {
      return makeLogProviderStub();
    } as never);
    vi.mocked(BatchLogRecordProcessor).mockImplementation(function () {
      return {};
    } as never);
    vi.mocked(OTLPLogExporter).mockImplementation(function () {
      return {};
    } as never);
    vi.mocked(logs.getLogger).mockReturnValue({ emit: vi.fn() } as never);
  });

  afterEach(() => {
    // Use disable() to fully clear global provider state so subsequent
    // setGlobalTracerProvider / setGlobalMeterProvider calls start fresh.
    trace.disable();
    metrics.disable();
    context.disable();
    _resetConfig();
    _resetRuntimeForTests();
    _resetOtelLogProviderForTests();
  });

  it('is a no-op when otelEnabled is false', async () => {
    setupTelemetry({ serviceName: 'test', otelEnabled: false });
    await registerOtelProviders(getConfig());
    expect(_areProvidersRegistered()).toBe(false);
    expect(vi.mocked(OTLPTraceExporter)).not.toHaveBeenCalled();
    expect(vi.mocked(OTLPMetricExporter)).not.toHaveBeenCalled();
  });

  it('skips trace provider installation when tracingEnabled is false', async () => {
    setupTelemetry({
      serviceName: 'test',
      otelEnabled: true,
      tracingEnabled: false,
      otlpEndpoint: 'http://localhost:4318',
    });
    await registerOtelProviders(getConfig());
    expect(vi.mocked(OTLPTraceExporter)).not.toHaveBeenCalled();
    expect(vi.mocked(OTLPMetricExporter)).toHaveBeenCalled();
    expect(_areProvidersRegistered()).toBe(true);
    expect(_getRegisteredProviders()).toHaveLength(2);
  });

  it('skips metrics provider installation when metricsEnabled is false', async () => {
    setupTelemetry({
      serviceName: 'test',
      otelEnabled: true,
      metricsEnabled: false,
      otlpEndpoint: 'http://localhost:4318',
    });
    await registerOtelProviders(getConfig());
    expect(vi.mocked(OTLPTraceExporter)).toHaveBeenCalled();
    expect(vi.mocked(OTLPMetricExporter)).not.toHaveBeenCalled();
    expect(_areProvidersRegistered()).toBe(true);
    expect(_getRegisteredProviders()).toHaveLength(2);
  });

  it('is a no-op (no exporters created) when no otlpEndpoint is configured', async () => {
    // Pass undefined explicitly so the env-derived OTEL_EXPORTER_OTLP_ENDPOINT is overridden.
    setupTelemetry({
      serviceName: 'my-svc',
      otelEnabled: true,
      otlpEndpoint: undefined,
      otlpHeaders: undefined,
    });
    await registerOtelProviders(getConfig());
    // No endpoint → safe no-export path: no exporters created, NOT marked registered
    // so reconfigureTelemetry() can install providers later when an endpoint is set.
    expect(vi.mocked(OTLPTraceExporter)).not.toHaveBeenCalled();
    expect(vi.mocked(OTLPMetricExporter)).not.toHaveBeenCalled();
    expect(vi.mocked(OTLPLogExporter)).not.toHaveBeenCalled();
    expect(_areProvidersRegistered()).toBe(false);
    expect(_getRegisteredProviders()).toHaveLength(0);
  });

  it('uses per-signal OTLP endpoints when shared otlpEndpoint is unset', async () => {
    setupTelemetry({
      serviceName: 'my-svc',
      otelEnabled: true,
      otlpEndpoint: undefined,
      otlpLogsEndpoint: 'http://logs-collector:4318',
      otlpTracesEndpoint: 'http://traces-collector:4318',
      otlpMetricsEndpoint: 'http://metrics-collector:4318',
    });

    await registerOtelProviders(getConfig());

    expect(vi.mocked(OTLPTraceExporter)).toHaveBeenCalledWith({
      url: 'http://traces-collector:4318',
      headers: {},
      timeoutMillis: 10000,
    });
    expect(vi.mocked(OTLPMetricExporter)).toHaveBeenCalledWith({
      url: 'http://metrics-collector:4318',
      headers: {},
      timeoutMillis: 10000,
    });
    expect(vi.mocked(OTLPLogExporter)).toHaveBeenCalledWith({
      url: 'http://logs-collector:4318',
      headers: {},
      timeoutMillis: 10000,
    });
    expect(_areProvidersRegistered()).toBe(true);
    expect(_getRegisteredProviders()).toHaveLength(3);
  });

  it('skips trace provider installation when no trace endpoint is configured', async () => {
    setupTelemetry({
      serviceName: 'my-svc',
      otelEnabled: true,
      otlpEndpoint: undefined,
      otlpLogsEndpoint: 'http://logs-collector:4318',
      otlpMetricsEndpoint: 'http://metrics-collector:4318',
    });

    await registerOtelProviders(getConfig());

    expect(vi.mocked(OTLPTraceExporter)).not.toHaveBeenCalled();
    expect(vi.mocked(OTLPMetricExporter)).toHaveBeenCalledWith({
      url: 'http://metrics-collector:4318',
      headers: {},
      timeoutMillis: 10000,
    });
    expect(vi.mocked(OTLPLogExporter)).toHaveBeenCalledWith({
      url: 'http://logs-collector:4318',
      headers: {},
      timeoutMillis: 10000,
    });
    expect(_areProvidersRegistered()).toBe(true);
    expect(_getRegisteredProviders()).toHaveLength(2);
  });

  it('skips metrics provider installation when no metrics endpoint is configured', async () => {
    setupTelemetry({
      serviceName: 'my-svc',
      otelEnabled: true,
      otlpEndpoint: undefined,
      otlpLogsEndpoint: 'http://logs-collector:4318',
      otlpTracesEndpoint: 'http://traces-collector:4318',
    });

    await registerOtelProviders(getConfig());

    expect(vi.mocked(OTLPTraceExporter)).toHaveBeenCalledWith({
      url: 'http://traces-collector:4318',
      headers: {},
      timeoutMillis: 10000,
    });
    expect(vi.mocked(OTLPMetricExporter)).not.toHaveBeenCalled();
    expect(vi.mocked(OTLPLogExporter)).toHaveBeenCalledWith({
      url: 'http://logs-collector:4318',
      headers: {},
      timeoutMillis: 10000,
    });
    expect(_areProvidersRegistered()).toBe(true);
    expect(_getRegisteredProviders()).toHaveLength(2);
  });

  it('skips log provider installation when no logs endpoint is configured', async () => {
    setupTelemetry({
      serviceName: 'my-svc',
      otelEnabled: true,
      otlpEndpoint: undefined,
      otlpTracesEndpoint: 'http://traces-collector:4318',
      otlpMetricsEndpoint: 'http://metrics-collector:4318',
    });

    await registerOtelProviders(getConfig());

    expect(vi.mocked(OTLPTraceExporter)).toHaveBeenCalledWith({
      url: 'http://traces-collector:4318',
      headers: {},
      timeoutMillis: 10000,
    });
    expect(vi.mocked(OTLPMetricExporter)).toHaveBeenCalledWith({
      url: 'http://metrics-collector:4318',
      headers: {},
      timeoutMillis: 10000,
    });
    expect(vi.mocked(OTLPLogExporter)).not.toHaveBeenCalled();
    expect(_areProvidersRegistered()).toBe(true);
    expect(_getRegisteredProviders()).toHaveLength(2);
  });

  it('treats empty per-signal endpoints as unset and falls back to the shared endpoint', async () => {
    setupTelemetry({
      serviceName: 'my-svc',
      otelEnabled: true,
      otlpEndpoint: 'http://otel-collector:4318',
      otlpLogsEndpoint: '',
    });

    await registerOtelProviders(getConfig());

    expect(vi.mocked(OTLPLogExporter)).toHaveBeenCalledWith({
      url: 'http://otel-collector:4318/v1/logs',
      headers: {},
      timeoutMillis: 10000,
    });
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
      timeoutMillis: 10000,
    });
    expect(vi.mocked(OTLPMetricExporter)).toHaveBeenCalledWith({
      url: 'http://otel-collector:4318/v1/metrics',
      headers: { Authorization: 'Bearer secret' },
      timeoutMillis: 10000,
    });
  });

  it('passes service resource attributes to resourceFromAttributes', async () => {
    setupTelemetry({
      serviceName: 'attr-svc',
      otelEnabled: true,
      otlpEndpoint: 'http://localhost:4318',
    });
    await registerOtelProviders(getConfig());
    expect(vi.mocked(resourceFromAttributes)).toHaveBeenCalledWith({
      'service.name': 'attr-svc',
      'deployment.environment': 'dev',
      'service.version': '0.0.0',
    });
  });

  it('passes service resource attributes to the metrics provider', async () => {
    vi.mocked(resourceFromAttributes).mockReturnValue({ resource: 'metrics' } as never);
    setupTelemetry({
      serviceName: 'metrics-svc',
      environment: 'prod',
      version: '1.2.3',
      otelEnabled: true,
      tracingEnabled: false,
      otlpMetricsEndpoint: 'http://metrics-collector:4318',
    });
    await registerOtelProviders(getConfig());
    expect(vi.mocked(resourceFromAttributes)).toHaveBeenCalledWith({
      'service.name': 'metrics-svc',
      'deployment.environment': 'prod',
      'service.version': '1.2.3',
    });
    expect(vi.mocked(MeterProvider)).toHaveBeenCalledWith(
      expect.objectContaining({
        resource: { resource: 'metrics' },
      }),
    );
  });

  it('wires BatchSpanProcessor with the trace exporter', async () => {
    setupTelemetry({
      serviceName: 'test',
      otelEnabled: true,
      otlpEndpoint: 'http://localhost:4318',
    });
    const fakeExporter = { fake: 'exporter' };
    vi.mocked(OTLPTraceExporter).mockImplementation(function () {
      return fakeExporter;
    } as never);
    await registerOtelProviders(getConfig());
    // Exporter is wrapped in a resilient-export proxy so every export() call
    // applies retry/timeout/circuit-breaker policy. Verify the underlying
    // fields are preserved via objectContaining rather than strict equality.
    expect(vi.mocked(BatchSpanProcessor)).toHaveBeenCalledWith(
      expect.objectContaining({ fake: 'exporter' }),
    );
  });

  it('wires PeriodicExportingMetricReader with the metrics exporter', async () => {
    setupTelemetry({
      serviceName: 'test',
      otelEnabled: true,
      otlpEndpoint: 'http://localhost:4318',
    });
    const fakeExporter = { fake: 'metrics-exporter' };
    vi.mocked(OTLPMetricExporter).mockImplementation(function () {
      return fakeExporter;
    } as never);
    await registerOtelProviders(getConfig());
    expect(vi.mocked(PeriodicExportingMetricReader)).toHaveBeenCalledWith({
      exporter: expect.objectContaining({ fake: 'metrics-exporter' }),
    });
  });

  it('warns and continues to metrics when trace SDK throws', async () => {
    vi.mocked(OTLPTraceExporter).mockImplementation(function () {
      throw new Error('trace peer dep missing');
    } as never);
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    setupTelemetry({
      serviceName: 'test',
      otelEnabled: true,
      otlpEndpoint: 'http://localhost:4318',
    });
    await registerOtelProviders(getConfig());
    expect(warnSpy).toHaveBeenCalledWith(
      expect.stringContaining('OTEL trace setup failed'),
      expect.any(Error),
    );
    expect(vi.mocked(OTLPMetricExporter)).toHaveBeenCalled();
    expect(_areProvidersRegistered()).toBe(true);
    expect(_getRegisteredProviders()).toHaveLength(2); // metrics + logs (trace threw)
    warnSpy.mockRestore();
  });
});
