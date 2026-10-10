// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// @vitest-environment node

/** PROVIDE_METRICS_HEALTH_OTLP: the health families as observable instruments on our provider. */

import { metrics } from '@opentelemetry/api';
import { MeterProvider, MetricReader, type ResourceMetrics } from '@opentelemetry/sdk-metrics';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { getConfig, setupTelemetry, type TelemetryConfig } from '../src/config.js';
import { setConsentLevel } from '../src/consent.js';
import { _incrementHealth, getHealthSnapshot, setSetupError } from '../src/health.js';
import { registerOtelProviders } from '../src/otel.js';
import { registerHealthOtlp } from '../src/prom-health-otlp.js';
import { HEALTH_METRIC_NAMES, renderPrometheus } from '../src/prom-pull.js';
import { _getProvidersBySignal } from '../src/provider-registry.js';
import { shutdownTelemetry } from '../src/shutdown.js';
import { resetTelemetryState } from '../src/testing.js';
import { must } from './support/must.js';
import { promSpec, withEnv } from './support/prometheus-fixtures.js';

class TestReader extends MetricReader {
  protected async onForceFlush(): Promise<void> {}
  protected async onShutdown(): Promise<void> {}
}

type Series = Map<string, number>;

function series(rm: ResourceMetrics): { series: Series; types: Map<string, number> } {
  const out: Series = new Map();
  const types = new Map<string, number>();
  for (const sm of rm.scopeMetrics) {
    for (const m of sm.metrics) {
      types.set(m.descriptor.name, m.dataPointType);
      expect(m.descriptor.unit).toBe('');
      expect(m.descriptor.description).toBe('');
      for (const p of m.dataPoints) {
        out.set(`${m.descriptor.name}${JSON.stringify(p.attributes)}`, p.value as number);
      }
    }
  }
  return { series: out, types };
}

function setup(overrides: Partial<TelemetryConfig>): TelemetryConfig {
  withEnv({}, () =>
    setupTelemetry({
      consoleOutput: false,
      tracingEnabled: false,
      otlpLogsEnabled: false,
      ...overrides,
    }),
  );
  return getConfig();
}

beforeEach(() => {
  resetTelemetryState();
  vi.spyOn(console, 'warn').mockImplementation(() => {});
});

afterEach(async () => {
  await shutdownTelemetry();
  resetTelemetryState();
  vi.restoreAllMocks();
});

describe('registerHealthOtlp', () => {
  it('reports the 26 series from a fresh snapshot, typed per the spec, ungated and uncounted', async () => {
    const reader = new TestReader();
    const provider = new MeterProvider({ readers: [reader] });
    registerHealthOtlp(provider.getMeter('t'));
    _incrementHealth('logsEmitted', 5);
    setSetupError('boom');
    setConsentLevel('NONE');
    const before = getHealthSnapshot().metricsEmitted;
    const { series: got, types } = series((await reader.collect()).resourceMetrics);
    expect(got.size).toBe(26);
    expect(got.get('provide_telemetry_emitted_total{"signal":"logs"}')).toBe(5);
    expect(got.get('provide_telemetry_circuit_state{"signal":"traces"}')).toBe(0);
    expect(got.get('provide_telemetry_setup_error{}')).toBe(1);
    expect(got.get('provide_telemetry_receipt_failures_total{}')).toBe(0);
    setSetupError(null);
    const again = series((await reader.collect()).resourceMetrics).series;
    expect(again.get('provide_telemetry_setup_error{}')).toBe(0);
    expect(getHealthSnapshot().metricsEmitted).toBe(before);
    const spec = promSpec['health_metrics'] as Record<string, { metric: string; type: string }[]>;
    for (const entry of [...(spec['per_signal'] ?? []), ...(spec['global'] ?? [])]) {
      // SUM is 3, GAUGE is 2 in sdk-metrics' DataPointType.
      expect(types.get(entry.metric), entry.metric).toBe(entry.type === 'counter' ? 3 : 2);
    }
    await provider.shutdown();
  });
});

describe('registerOtelProviders with metricsHealthOtlp', () => {
  for (const healthOtlp of [false, true]) {
    it(`a scrape carries each health family once (health_otlp=${String(healthOtlp)})`, async () => {
      await registerOtelProviders(
        setup({ metricsExporters: ['prometheus'], metricsHealthOtlp: healthOtlp }),
      );
      const { body } = await renderPrometheus();
      for (const name of HEALTH_METRIC_NAMES) {
        expect(
          body.split('\n').filter((l) => l === `# TYPE ${name} ${l.split(' ')[3] ?? ''}`),
        ).toHaveLength(1);
      }
      const provider = must(_getProvidersBySignal().metrics) as unknown as {
        _sharedState: {
          meterSharedStates: Map<string, { observableRegistry: { _callbacks: unknown[] } }>;
        };
      };
      const callbacks = [...provider._sharedState.meterSharedStates.values()].reduce(
        (n, s) => n + s.observableRegistry._callbacks.length,
        0,
      );
      expect(callbacks).toBe(healthOtlp ? 10 : 0);
    });
  }

  it('never registers on a host-owned provider', async () => {
    const host = new MeterProvider({ readers: [new TestReader()] });
    metrics.setGlobalMeterProvider(host);
    const spy = vi.spyOn(host, 'getMeter');
    await registerOtelProviders(
      setup({
        metricsExporters: ['otlp'],
        metricsHealthOtlp: true,
        otlpMetricsEndpoint: 'http://127.0.0.1:9/v1/metrics',
      }),
    );
    expect(spy).not.toHaveBeenCalled();
    await host.shutdown();
  });
});
