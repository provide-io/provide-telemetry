// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
// @vitest-environment node

import { beforeEach, describe, expect, it, vi } from 'vitest';

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
import { OTLPMetricExporter } from '@opentelemetry/exporter-metrics-otlp-http';
import { LoggerProvider, BatchLogRecordProcessor } from '@opentelemetry/sdk-logs';
import { OTLPLogExporter } from '@opentelemetry/exporter-logs-otlp-http';
import { MeterProvider, PeriodicExportingMetricReader } from '@opentelemetry/sdk-metrics';
import { logs } from '@opentelemetry/api-logs';
import { _resetConfig, getConfig, setupTelemetry } from '../../src/config';
import {
  _areProvidersRegistered,
  _getRegisteredProviders,
  _resetRuntimeForTests,
} from '../../src/runtime';
import { _resetOtelLogProviderForTests } from '../../src/otel-logs';
import { registerOtelProviders } from '../../src/otel.js';

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

describe('registerOtelProviders registration paths', () => {
  beforeEach(() => {
    _resetConfig();
    _resetRuntimeForTests();
    _resetOtelLogProviderForTests();
    vi.clearAllMocks();
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

  it('warns and still marks providers registered when metrics SDK throws', async () => {
    vi.mocked(OTLPMetricExporter).mockImplementation(function () {
      throw new Error('metrics peer dep missing');
    } as never);
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    setupTelemetry({
      serviceName: 'test',
      otelEnabled: true,
      otlpEndpoint: 'http://localhost:4318',
    });
    await registerOtelProviders(getConfig());
    expect(warnSpy).toHaveBeenCalledWith(
      expect.stringContaining('OTEL metrics setup failed'),
      expect.any(Error),
    );
    expect(vi.mocked(OTLPTraceExporter)).toHaveBeenCalled();
    expect(_areProvidersRegistered()).toBe(true);
    warnSpy.mockRestore();
  });

  it('constructs OTLPLogExporter with /v1/logs path', async () => {
    setupTelemetry({
      serviceName: 'log-svc',
      otelEnabled: true,
      otlpEndpoint: 'http://otel-collector:4318',
      otlpHeaders: { Authorization: 'Bearer tok' },
    });
    await registerOtelProviders(getConfig());
    expect(vi.mocked(OTLPLogExporter)).toHaveBeenCalledWith({
      url: 'http://otel-collector:4318/v1/logs',
      headers: { Authorization: 'Bearer tok' },
      timeoutMillis: 10000,
    });
  });

  it('wires BatchLogRecordProcessor with the log exporter', async () => {
    setupTelemetry({
      serviceName: 'test',
      otelEnabled: true,
      otlpEndpoint: 'http://localhost:4318',
    });
    const fakeExporter = { fake: 'log-exporter' };
    vi.mocked(OTLPLogExporter).mockImplementation(function () {
      return fakeExporter;
    } as never);
    await registerOtelProviders(getConfig());
    // Exporter is wrapped in a resilient-export proxy; identity is lost.
    expect(vi.mocked(BatchLogRecordProcessor)).toHaveBeenCalledWith(
      expect.objectContaining({ fake: 'log-exporter' }),
    );
  });

  it('registers all three providers (trace + metrics + logs)', async () => {
    setupTelemetry({
      serviceName: 'test',
      otelEnabled: true,
      otlpEndpoint: 'http://localhost:4318',
    });
    await registerOtelProviders(getConfig());
    expect(_getRegisteredProviders()).toHaveLength(3);
  });

  it('is idempotent — second call is a no-op when providers are already registered', async () => {
    setupTelemetry({
      serviceName: 'test',
      otelEnabled: true,
      otlpEndpoint: 'http://localhost:4318',
    });
    await registerOtelProviders(getConfig());
    const callCount = vi.mocked(OTLPTraceExporter).mock.calls.length;
    expect(callCount).toBeGreaterThan(0);
    await registerOtelProviders(getConfig());
    expect(vi.mocked(OTLPTraceExporter).mock.calls.length).toBe(callCount);
  });

  it('warns and continues when logs SDK throws — other providers still register', async () => {
    vi.mocked(OTLPLogExporter).mockImplementation(function () {
      throw new Error('logs peer dep missing');
    } as never);
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    setupTelemetry({
      serviceName: 'test',
      otelEnabled: true,
      otlpEndpoint: 'http://localhost:4318',
    });
    await registerOtelProviders(getConfig());
    expect(warnSpy).toHaveBeenCalledWith(
      expect.stringContaining('OTEL logs setup failed'),
      expect.any(Error),
    );
    expect(vi.mocked(OTLPTraceExporter)).toHaveBeenCalled();
    expect(vi.mocked(OTLPMetricExporter)).toHaveBeenCalled();
    expect(_areProvidersRegistered()).toBe(true);
    expect(_getRegisteredProviders()).toHaveLength(2);
    warnSpy.mockRestore();
  });

  it('leaves provider state unset when all OTEL provider setups fail', async () => {
    vi.mocked(OTLPTraceExporter).mockImplementation(function () {
      throw new Error('trace peer dep missing');
    } as never);
    vi.mocked(OTLPMetricExporter).mockImplementation(function () {
      throw new Error('metrics peer dep missing');
    } as never);
    vi.mocked(OTLPLogExporter).mockImplementation(function () {
      throw new Error('logs peer dep missing');
    } as never);
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    setupTelemetry({
      serviceName: 'test',
      otelEnabled: true,
      otlpEndpoint: 'http://localhost:4318',
    });
    await registerOtelProviders(getConfig());
    expect(_areProvidersRegistered()).toBe(false);
    expect(_getRegisteredProviders()).toHaveLength(0);
    expect(warnSpy).toHaveBeenCalledTimes(3);
    warnSpy.mockRestore();
  });
});
