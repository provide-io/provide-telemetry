// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
// @vitest-environment node

/**
 * Targeted mutation-killing tests for `src/otel.ts`.
 *
 * otel-providers.test.ts covers the shapes a user configures on purpose: a
 * shared endpoint, all three per-signal endpoints, or two of the three. What it
 * never exercises is the wiring *between* those cases — the early returns, the
 * endpoint normalization, the signal tags each provider is filed under, and the
 * signal name each exporter's resilience policy is keyed by. Those are what a
 * copy-paste between the three near-identical signal blocks breaks first, and
 * they are what Stryker reported as survivors.
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

import { AsyncLocalStorageContextManager } from '@opentelemetry/context-async-hooks';
import {
  BasicTracerProvider,
  BatchSpanProcessor,
  ParentBasedSampler,
  TraceIdRatioBasedSampler,
  AlwaysOffSampler,
} from '@opentelemetry/sdk-trace-base';
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-http';
import { resourceFromAttributes } from '@opentelemetry/resources';
import { MeterProvider, PeriodicExportingMetricReader } from '@opentelemetry/sdk-metrics';
import { OTLPMetricExporter } from '@opentelemetry/exporter-metrics-otlp-http';
import { LoggerProvider, BatchLogRecordProcessor } from '@opentelemetry/sdk-logs';
import { OTLPLogExporter } from '@opentelemetry/exporter-logs-otlp-http';
import { logs } from '@opentelemetry/api-logs';
import { _resetConfig, getConfig, setupTelemetry } from '../../src/config.js';
import { _resetHealthForTests, getHealthSnapshot } from '../../src/health.js';
import { _resetResilienceForTests } from '../../src/resilience.js';
import {
  _areProvidersRegistered,
  _getProvidersBySignal,
  _getRegisteredProviders,
  _isLogsProviderInstalled,
} from '../../src/provider-registry.js';
import { _resetRuntimeForTests } from '../../src/runtime.js';
import { _resetOtelLogProviderForTests } from '../../src/otel-logs.js';
import { registerOtelProviders } from '../../src/otel.js';

/**
 * An exporter whose every export() reports FAILED, to drive the retry path.
 *
 * A function expression, not an arrow: the OTel exporters are mocked as
 * constructors and `new` on an arrow throws.
 */
function failingExporter() {
  return {
    export: (_items: unknown, cb: (r: { code: number; error: Error }) => void) => {
      cb({ code: 1, error: new Error('collector down') });
    },
    shutdown: async () => {},
  };
}

/** Fire one export through a wrapped exporter and wait for its callback. */
function exportOnce(exporter: {
  export: (items: unknown, cb: (r: unknown) => void) => void;
}): Promise<void> {
  return new Promise<void>((resolve) => {
    exporter.export([], () => {
      resolve();
    });
  });
}

let ctxSpy: ReturnType<typeof vi.spyOn>;
let warnSpy: ReturnType<typeof vi.spyOn>;

describe('registerOtelProviders — mutation pins', () => {
  beforeEach(() => {
    _resetConfig();
    _resetRuntimeForTests();
    _resetOtelLogProviderForTests();
    _resetHealthForTests();
    _resetResilienceForTests();
    vi.clearAllMocks();
    vi.mocked(BasicTracerProvider).mockImplementation(function () {
      return { shutdown: async () => {}, forceFlush: async () => {} };
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
      return { shutdown: async () => {}, forceFlush: async () => {} };
    } as never);
    vi.mocked(PeriodicExportingMetricReader).mockImplementation(function () {
      return {};
    } as never);
    vi.mocked(OTLPMetricExporter).mockImplementation(function () {
      return {};
    } as never);
    vi.mocked(LoggerProvider).mockImplementation(function () {
      return { shutdown: async () => {}, forceFlush: async () => {} };
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
    // Stubbed rather than allowed through: the point of these assertions is
    // *whether* the global context manager is installed, and actually
    // installing one leaks an AsyncLocalStorage across the rest of the suite.
    ctxSpy = vi.spyOn(context, 'setGlobalContextManager').mockReturnValue(true);
    warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
  });

  afterEach(() => {
    ctxSpy.mockRestore();
    warnSpy.mockRestore();
    trace.disable();
    metrics.disable();
    context.disable();
    _resetConfig();
    _resetRuntimeForTests();
    _resetOtelLogProviderForTests();
    _resetHealthForTests();
    _resetResilienceForTests();
  });

  it('does nothing when otelEnabled is false, even with an endpoint configured', async () => {
    // The existing no-op test passes a config with no endpoint at all, so
    // dropping the otelEnabled guard would still hit the no-endpoint return
    // two lines later. With an endpoint present, the guard is the only thing
    // standing between a disabled consumer and three live OTLP exporters.
    setupTelemetry({
      serviceName: 'disabled-svc',
      otelEnabled: false,
      otlpEndpoint: 'http://collector:4318',
    });
    await registerOtelProviders(getConfig());
    expect(vi.mocked(OTLPTraceExporter)).not.toHaveBeenCalled();
    expect(vi.mocked(OTLPMetricExporter)).not.toHaveBeenCalled();
    expect(vi.mocked(OTLPLogExporter)).not.toHaveBeenCalled();
    expect(ctxSpy).not.toHaveBeenCalled();
    expect(_areProvidersRegistered()).toBe(false);
  });

  it('trims whitespace around the shared endpoint before composing signal URLs', async () => {
    setupTelemetry({
      serviceName: 'trim-svc',
      otelEnabled: true,
      otlpEndpoint: '  http://collector:4318  ',
    });
    await registerOtelProviders(getConfig());
    expect(vi.mocked(OTLPTraceExporter)).toHaveBeenCalledWith(
      expect.objectContaining({ url: 'http://collector:4318/v1/traces' }),
    );
    expect(vi.mocked(OTLPMetricExporter)).toHaveBeenCalledWith(
      expect.objectContaining({ url: 'http://collector:4318/v1/metrics' }),
    );
  });

  it('collapses a run of trailing slashes on the shared endpoint, not just the last one', async () => {
    setupTelemetry({
      serviceName: 'slash-svc',
      otelEnabled: true,
      otlpEndpoint: 'http://collector:4318///',
    });
    await registerOtelProviders(getConfig());
    expect(vi.mocked(OTLPTraceExporter)).toHaveBeenCalledWith(
      expect.objectContaining({ url: 'http://collector:4318/v1/traces' }),
    );
    expect(vi.mocked(OTLPMetricExporter)).toHaveBeenCalledWith(
      expect.objectContaining({ url: 'http://collector:4318/v1/metrics' }),
    );
  });

  it('touches no OTel global when no signal has an endpoint', async () => {
    setupTelemetry({
      serviceName: 'no-endpoint-svc',
      otelEnabled: true,
      otlpEndpoint: undefined,
      otlpLogsEndpoint: undefined,
      otlpTracesEndpoint: undefined,
      otlpMetricsEndpoint: undefined,
    });
    await registerOtelProviders(getConfig());
    // The safe no-export path is not just "no exporters" — it must also leave
    // the process's context manager alone. Installing an AsyncLocalStorage for
    // a consumer who configured no collector is a side effect they did not ask
    // for, and it is the only thing that changes if the early return goes.
    expect(ctxSpy).not.toHaveBeenCalled();
    expect(_getRegisteredProviders()).toHaveLength(0);
    expect(_areProvidersRegistered()).toBe(false);
  });

  it('installs the async-hooks context manager once an endpoint is configured', async () => {
    setupTelemetry({
      serviceName: 'ctx-svc',
      otelEnabled: true,
      otlpEndpoint: 'http://collector:4318',
    });
    await registerOtelProviders(getConfig());
    expect(ctxSpy).toHaveBeenCalledTimes(1);
    expect(ctxSpy.mock.calls[0][0]).toBeInstanceOf(AsyncLocalStorageContextManager);
  });

  describe('a single configured signal installs that signal and only that signal', () => {
    // hasAnyEndpoint ORs the three signals together. Every existing test
    // configures at least two of them, so each operand can be forced to a
    // constant — or the OR turned into an AND — and the suite stays green.
    // One-signal configs are what separate them, and they are a real shape:
    // exporting only traces to a collector is a normal deployment.
    it.each([
      ['logs', 'otlpLogsEndpoint', OTLPLogExporter],
      ['traces', 'otlpTracesEndpoint', OTLPTraceExporter],
      ['metrics', 'otlpMetricsEndpoint', OTLPMetricExporter],
    ] as const)('%s only', async (signal, field, exporter) => {
      setupTelemetry({
        serviceName: `${signal}-only-svc`,
        otelEnabled: true,
        otlpEndpoint: undefined,
        otlpLogsEndpoint: undefined,
        otlpTracesEndpoint: undefined,
        otlpMetricsEndpoint: undefined,
        [field]: `http://${signal}-collector:4318`,
      });
      await registerOtelProviders(getConfig());
      expect(vi.mocked(exporter)).toHaveBeenCalledWith(
        expect.objectContaining({ url: `http://${signal}-collector:4318` }),
      );
      expect(_getRegisteredProviders()).toHaveLength(1);
      expect(Object.keys(_getProvidersBySignal())).toEqual([signal]);
      expect(_areProvidersRegistered()).toBe(true);
      // The two unconfigured signals are skipped, not attempted-and-warned:
      // dropping either endpoint guard sends `undefined` into
      // validateOtlpEndpoint, which throws into the catch and logs.
      expect(warnSpy).not.toHaveBeenCalled();
    });
  });

  it('files each provider under the signal it drains', async () => {
    const traceProvider = { shutdown: async () => {}, forceFlush: async () => {} };
    const meterProvider = { shutdown: async () => {}, forceFlush: async () => {} };
    const logProvider = { shutdown: async () => {}, forceFlush: async () => {} };
    vi.mocked(BasicTracerProvider).mockImplementation(function () {
      return traceProvider;
    } as never);
    vi.mocked(MeterProvider).mockImplementation(function () {
      return meterProvider;
    } as never);
    vi.mocked(LoggerProvider).mockImplementation(function () {
      return logProvider;
    } as never);
    setupTelemetry({
      serviceName: 'tagged-svc',
      otelEnabled: true,
      otlpEndpoint: 'http://collector:4318',
    });
    await registerOtelProviders(getConfig());
    // The signal list is positional against the provider list, so a stray
    // leading entry or a mistyped name silently shifts every provider onto the
    // wrong signal — and flushSignals then reports the trace provider's drain
    // as the logs result.
    const bySignal = _getProvidersBySignal();
    expect(Object.keys(bySignal).sort()).toEqual(['logs', 'metrics', 'traces']);
    expect(bySignal.traces).toBe(traceProvider);
    expect(bySignal.metrics).toBe(meterProvider);
    expect(bySignal.logs).toBe(logProvider);
    expect(_isLogsProviderInstalled()).toBe(true);
  });

  it('gives ParentBasedSampler the configured sampler as its root', async () => {
    setupTelemetry({
      serviceName: 'sampler-svc',
      otelEnabled: true,
      otlpEndpoint: 'http://collector:4318',
      traceSampleRate: 0.25,
      samplingTracesRate: 1,
    });
    await registerOtelProviders(getConfig());
    // Passing ParentBasedSampler an options object without `root` is not a
    // no-op: its root default is AlwaysOnSampler, so every root span would be
    // sampled at 100% while the config says 25%. Assert the exact options.
    expect(vi.mocked(ParentBasedSampler)).toHaveBeenCalledWith({ root: { rate: 0.25 } });
  });

  it.each([
    ['traces', BatchSpanProcessor, OTLPTraceExporter],
    ['metrics', PeriodicExportingMetricReader, OTLPMetricExporter],
  ] as const)(
    'wraps the %s exporter under that signal’s resilience policy',
    async (signal, processor, exporterCtor) => {
      vi.mocked(exporterCtor).mockImplementation(failingExporter as never);
      // Configured through setupTelemetry rather than setExporterPolicy: setup
      // installs the per-signal policies from the config itself, so a policy
      // set beforehand would just be overwritten.
      setupTelemetry({
        serviceName: 'resilience-svc',
        otelEnabled: true,
        otlpEndpoint: 'http://collector:4318',
        exporterTracesRetries: 2,
        exporterTracesTimeoutMs: 0,
        exporterMetricsRetries: 2,
        exporterMetricsTimeoutMs: 0,
      });
      await registerOtelProviders(getConfig());
      // BatchSpanProcessor takes the exporter positionally, the metric reader
      // takes it as `{ exporter }`.
      const arg = vi.mocked(processor).mock.calls[0][0] as Record<string, unknown>;
      const wrapped = (arg.exporter ?? arg) as Parameters<typeof exportOnce>[0];
      await exportOnce(wrapped);
      const health = getHealthSnapshot();
      // Retries and failure accounting are keyed by signal name: the wrong name
      // silently falls back to the logs policy and the logs counters.
      if (signal === 'traces') {
        expect(health.exportFailuresTraces).toBe(3);
        expect(health.retriesTraces).toBe(2);
      } else {
        expect(health.exportFailuresMetrics).toBe(3);
        expect(health.retriesMetrics).toBe(2);
      }
      expect(health.exportFailuresLogs).toBe(0);
    },
  );
});
