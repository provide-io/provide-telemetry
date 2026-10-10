// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// @vitest-environment node

/**
 * registerOtelProviders() with the Prometheus reader, against the real SDK:
 * which readers it attaches, the pull status it records on each path, and the
 * listener it starts and shutdownTelemetry() stops.
 */

import { metrics } from '@opentelemetry/api';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { must } from './support/must.js';
import { getConfig, setupTelemetry, type TelemetryConfig } from '../src/config.js';
import { getHealthSnapshot, setSetupError } from '../src/health.js';
import { counter, gauge, histogram } from '../src/metrics.js';
import { observableGauge } from '../src/metrics-observable.js';
import { registerOtelProviders } from '../src/otel.js';
import { recordPullStatusWithoutProvider, setupOtelMeterProvider } from '../src/otel-metrics.js';
import { _getProvidersBySignal } from '../src/provider-registry.js';
import {
  getPullStatus,
  HOST_PROVIDER,
  METRICS_DISABLED,
  NOT_SELECTED,
  OTEL_DISABLED,
  OTEL_MISSING,
  READY,
  renderPrometheus,
  SETUP_FAILED,
  SHUT_DOWN,
} from '../src/prom-pull.js';
import { prometheusListenerAddress } from '../src/prom-setup.js';
import { shutdownTelemetry } from '../src/shutdown.js';
import { resetTelemetryState } from '../src/testing.js';
import { liveMeterProvider } from './fixtures/live-providers.js';
import { withEnv } from './support/prometheus-fixtures.js';

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

describe('registerOtelProviders with the pull reader', () => {
  it('attaches it with no OTLP endpoint and serves what instruments record', async () => {
    await registerOtelProviders(setup({ metricsExporters: ['prometheus'] }));
    expect(getPullStatus()).toBe(READY);
    expect(_getProvidersBySignal().metrics).toBeDefined();
    counter('real.requests').add(3, { route: '/a' });
    gauge('real.cpu', { unit: '1' }).set(1, { core: '0' });
    histogram('real.latency', { unit: 'ms' }).record(12);
    observableGauge('real.temperature', () => [{ value: 41.5 }], { unit: 'Cel' });
    const { body } = await renderPrometheus();
    expect(body).toContain('real_requests_total{route="/a"} 3\n');
    expect(body).toContain('real_cpu_ratio{core="0"} 1\n');
    expect(body).toContain('real_latency_milliseconds_sum 12\n');
    expect(body).toContain('real_temperature_celsius 41.5\n');
    expect(body).toContain('target_info{service_name="provide-service"');
    expect(body).toContain('provide_telemetry_emitted_total{signal="metrics"} 4\n');
    expect(prometheusListenerAddress()).toBeUndefined();
  });

  it('honours translation, scope labels and target_info', async () => {
    await registerOtelProviders(
      setup({
        metricsExporters: ['prometheus'],
        prometheusTranslation: 'UnderscoreEscapingWithoutSuffixes',
        prometheusScopeLabels: true,
        prometheusTargetInfo: false,
      }),
    );
    counter('opts.requests').add(1);
    const { body } = await renderPrometheus();
    expect(body).toContain('opts_requests{otel_scope_name="@provide-io/telemetry"} 1\n');
    expect(body).not.toContain('target_info');
  });

  it('runs beside the OTLP reader on one provider', async () => {
    await registerOtelProviders(
      setup({
        metricsExporters: ['otlp', 'prometheus'],
        otlpMetricsEndpoint: 'http://127.0.0.1:9/v1/metrics',
      }),
    );
    expect(getPullStatus()).toBe(READY);
    const provider = _getProvidersBySignal().metrics as unknown as {
      _sharedState: { metricCollectors: unknown[] };
    };
    expect(provider._sharedState.metricCollectors).toHaveLength(2);
  });

  it('OTLP alone attaches no pull reader', async () => {
    await registerOtelProviders(setup({ otlpMetricsEndpoint: 'http://127.0.0.1:9/v1/metrics' }));
    expect(getPullStatus()).toBe(NOT_SELECTED);
    const provider = _getProvidersBySignal().metrics as unknown as {
      _sharedState: { metricCollectors: unknown[] };
    };
    expect(provider._sharedState.metricCollectors).toHaveLength(1);
  });

  it('otlp without prometheus and without an endpoint installs nothing', async () => {
    await registerOtelProviders(setup({ otlpTracesEndpoint: 'http://127.0.0.1:9/v1/traces' }));
    expect(getPullStatus()).toBe(NOT_SELECTED);
    expect(_getProvidersBySignal().metrics).toBeUndefined();
  });

  it('prometheus without otlp ignores an OTLP endpoint', async () => {
    await registerOtelProviders(
      setup({
        metricsExporters: ['prometheus'],
        otlpMetricsEndpoint: 'http://127.0.0.1:9/v1/metrics',
      }),
    );
    const provider = _getProvidersBySignal().metrics as unknown as {
      _sharedState: { metricCollectors: unknown[] };
    };
    expect(provider._sharedState.metricCollectors).toHaveLength(1);
  });

  it('records why it cannot serve', async () => {
    await registerOtelProviders(setup({ metricsEnabled: false, metricsExporters: ['prometheus'] }));
    expect(getPullStatus()).toBe(METRICS_DISABLED);
    await registerOtelProviders(setup({ otelEnabled: false, metricsExporters: ['prometheus'] }));
    expect(getPullStatus()).toBe(OTEL_DISABLED);
    await registerOtelProviders(setup({ otelEnabled: false }));
    expect(getPullStatus()).toBe(NOT_SELECTED);
    await registerOtelProviders(setup({}));
    expect(getPullStatus()).toBe(NOT_SELECTED);
  });

  it('an invalid OTLP endpoint is a setup failure', async () => {
    await registerOtelProviders(
      setup({ metricsExporters: ['otlp', 'prometheus'], otlpMetricsEndpoint: 'not a url' }),
    );
    expect(getPullStatus()).toBe(SETUP_FAILED);
    expect(_getProvidersBySignal().metrics).toBeUndefined();
  });

  it('a host-owned provider is left alone', async () => {
    metrics.setGlobalMeterProvider(liveMeterProvider() as never);
    await registerOtelProviders(setup({ metricsExporters: ['prometheus'] }));
    expect(getPullStatus()).toBe(HOST_PROVIDER);
    expect(_getProvidersBySignal().metrics).toBeUndefined();
  });

  it('a host-owned provider still gets our OTLP provider, but no pull reader', async () => {
    metrics.setGlobalMeterProvider(liveMeterProvider() as never);
    await registerOtelProviders(
      setup({
        metricsExporters: ['otlp', 'prometheus'],
        otlpMetricsEndpoint: 'http://127.0.0.1:9/v1/metrics',
      }),
    );
    expect(getPullStatus()).toBe(HOST_PROVIDER);
    expect(_getProvidersBySignal().metrics).toBeDefined();
  });

  it('shutdown marks the endpoint shut down', async () => {
    await registerOtelProviders(setup({ metricsExporters: ['prometheus'] }));
    await shutdownTelemetry();
    expect(getPullStatus()).toBe(SHUT_DOWN);
    await expect(renderPrometheus()).rejects.toThrow('shut down');
  });

  it('recordPullStatusWithoutProvider covers each reason', () => {
    const base = setup({});
    recordPullStatusWithoutProvider({ ...base, metricsExporters: ['prometheus'] });
    expect(getPullStatus()).toBe(OTEL_MISSING);
    recordPullStatusWithoutProvider({ ...base, otelEnabled: false, prometheusListen: 'true' });
    expect(getPullStatus()).toBe(OTEL_DISABLED);
  });

  it('setupOtelMeterProvider passes the per-signal headers and timeout to the exporter', async () => {
    const cfg = setup({
      otlpMetricsEndpoint: 'http://127.0.0.1:9/v1/metrics',
      otlpMetricsHeaders: { a: 'b' },
      exporterMetricsTimeoutMs: 1234,
    });
    const provider = await setupOtelMeterProvider(cfg, cfg.otlpMetricsEndpoint, { c: 'd' });
    expect(provider).toBeDefined();
    await must(must(provider).shutdown).call(provider);
    metrics.disable();
  });
});

describe('the listener follows setup and shutdown', () => {
  const LISTEN = { metricsExporters: ['prometheus'], prometheusListen: 'true', prometheusPort: 0 };

  it('starts with setup, restarts on a changed path, and stops with shutdown', async () => {
    await registerOtelProviders(setup(LISTEN));
    const first = prometheusListenerAddress();
    expect(first).toBeDefined();
    const res = await fetch(`http://127.0.0.1:${must(first).port}/metrics`);
    expect(res.status).toBe(200);
    expect(await res.text()).toContain('provide_telemetry_setup_error 0');
    // Already registered: the providers stay, the listener follows the config.
    await registerOtelProviders(setup({ ...LISTEN, prometheusPath: '/other' }));
    const second = must(prometheusListenerAddress());
    expect((await fetch(`http://127.0.0.1:${second.port}/other`)).status).toBe(200);
    await shutdownTelemetry();
    expect(prometheusListenerAddress()).toBeUndefined();
  });

  it('a broken web config is setup_error, not a failed setup, and clears on a good one', async () => {
    await registerOtelProviders(setup({ ...LISTEN, prometheusWebConfig: '/nonexistent/web.yml' }));
    expect(prometheusListenerAddress()).toBeUndefined();
    expect(getHealthSnapshot().setupError).toMatch(
      /^prometheus listener: web config \/nonexistent/,
    );
    expect(getPullStatus()).toBe(READY);
    await registerOtelProviders(setup(LISTEN));
    expect(getHealthSnapshot().setupError).toBeNull();
    expect(prometheusListenerAddress()).toBeDefined();
  });

  it('leaves an unrelated setup error alone', async () => {
    setSetupError('something else');
    await registerOtelProviders(setup(LISTEN));
    expect(getHealthSnapshot().setupError).toBe('something else');
  });

  it('a listener without a reader serves the reason', async () => {
    await registerOtelProviders(setup({ ...LISTEN, otelEnabled: false }));
    const bound = must(prometheusListenerAddress());
    const res = await fetch(`http://127.0.0.1:${bound.port}/metrics`);
    expect(res.status).toBe(503);
    expect(await res.text()).toBe(
      'provide-telemetry: OpenTelemetry is disabled (otelEnabled: false)\n',
    );
  });
});
