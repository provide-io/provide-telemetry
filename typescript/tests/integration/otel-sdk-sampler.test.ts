// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
// @vitest-environment node

/**
 * SDK sampler wiring for registerOtelProviders — companion to otel-providers.test.ts.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { context, metrics, trace } from '@opentelemetry/api';

vi.mock('@opentelemetry/sdk-trace-base', () => ({
  BasicTracerProvider: vi.fn(),
  BatchSpanProcessor: vi.fn(),
  ParentBasedSampler: vi.fn(),
  TraceIdRatioBasedSampler: vi.fn(),
  AlwaysOffSampler: vi.fn(),
}));
vi.mock('@opentelemetry/exporter-trace-otlp-http', () => ({
  OTLPTraceExporter: vi.fn(),
}));
vi.mock('@opentelemetry/resources', () => {
  const resourceStub: { merge: ReturnType<typeof vi.fn> } = { merge: vi.fn() };
  resourceStub.merge.mockReturnValue(resourceStub);
  return {
    resourceFromAttributes: vi.fn().mockReturnValue(resourceStub),
    detectResources: vi.fn().mockReturnValue(resourceStub),
    envDetector: {},
  };
});
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

import {
  AlwaysOffSampler,
  BasicTracerProvider,
  BatchSpanProcessor,
  ParentBasedSampler,
  TraceIdRatioBasedSampler,
} from '@opentelemetry/sdk-trace-base';
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-http';
import { resourceFromAttributes } from '@opentelemetry/resources';
import { MeterProvider, PeriodicExportingMetricReader } from '@opentelemetry/sdk-metrics';
import { OTLPMetricExporter } from '@opentelemetry/exporter-metrics-otlp-http';
import { LoggerProvider, BatchLogRecordProcessor } from '@opentelemetry/sdk-logs';
import { OTLPLogExporter } from '@opentelemetry/exporter-logs-otlp-http';
import { logs } from '@opentelemetry/api-logs';
import { _resetConfig, getConfig, setupTelemetry } from '../../src/config';
import { _resetRuntimeForTests } from '../../src/runtime';
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

describe('registerOtelProviders SDK sampler', () => {
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
    vi.mocked(ParentBasedSampler).mockImplementation(function (cfg: { root: unknown }) {
      return { root: cfg.root };
    } as never);
    vi.mocked(TraceIdRatioBasedSampler).mockImplementation(function (rate: number) {
      return { rate };
    } as never);
    vi.mocked(AlwaysOffSampler).mockImplementation(function () {
      return { alwaysOff: true };
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
    const resourceStub: { merge: ReturnType<typeof vi.fn> } = { merge: vi.fn() };
    resourceStub.merge.mockReturnValue(resourceStub);
    vi.mocked(resourceFromAttributes).mockReturnValue(resourceStub as never);
  });

  afterEach(() => {
    trace.disable();
    metrics.disable();
    context.disable();
    _resetConfig();
    _resetRuntimeForTests();
    _resetOtelLogProviderForTests();
  });

  it('wires ParentBased TraceIdRatioBased sampler at the effective rate', async () => {
    setupTelemetry({
      serviceName: 'test',
      otelEnabled: true,
      otlpEndpoint: 'http://localhost:4318',
      traceSampleRate: 0.25,
      samplingTracesRate: 0.5,
    });
    await registerOtelProviders(getConfig());
    expect(vi.mocked(TraceIdRatioBasedSampler)).toHaveBeenCalledWith(0.25);
    expect(vi.mocked(ParentBasedSampler)).toHaveBeenCalled();
    expect(vi.mocked(BasicTracerProvider)).toHaveBeenCalledWith(
      expect.objectContaining({ sampler: expect.anything() }),
    );
  });

  it('uses AlwaysOffSampler when effective rate is zero', async () => {
    setupTelemetry({
      serviceName: 'test',
      otelEnabled: true,
      otlpEndpoint: 'http://localhost:4318',
      traceSampleRate: 0,
      samplingTracesRate: 1,
    });
    await registerOtelProviders(getConfig());
    expect(vi.mocked(AlwaysOffSampler)).toHaveBeenCalled();
    expect(vi.mocked(TraceIdRatioBasedSampler)).not.toHaveBeenCalled();
  });
});
