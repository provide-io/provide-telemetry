// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// @vitest-environment node

/**
 * Setup warns about ignored OTEL_METRICS_EXPORTER entries and reports them as
 * setupError. See prometheus_metrics.metrics_exporter_warnings in
 * spec/telemetry-api.yaml.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { getConfig, setupTelemetry } from '../src/config.js';
import { reportExporterWarnings } from '../src/config-prometheus.js';
import { ConfigurationError } from '../src/exceptions.js';
import { getHealthSnapshot, setSetupError } from '../src/health.js';
import { registerOtelProviders } from '../src/otel.js';
import { shutdownTelemetry } from '../src/shutdown.js';
import { resetTelemetryState } from '../src/testing.js';
import { withEnv } from './support/prometheus-fixtures.js';

const UNKNOWN = 'OTEL_METRICS_EXPORTER: unknown exporter statsd, ignored';
const CONSOLE = 'OTEL_METRICS_EXPORTER: console is not supported by provide-telemetry, ignored';
const FALLBACK = 'OTEL_METRICS_EXPORTER: no supported exporter left, using otlp';

function ignoredLogs(): string[] {
  return vi
    .mocked(console.warn)
    .mock.calls.map((args) => String(args[0]))
    .filter((line) => line.includes('config.metrics_exporter.value_ignored'));
}

function setupWith(env: Record<string, string>, overrides = {}): void {
  withEnv(env, () => setupTelemetry({ consoleOutput: false, ...overrides }));
}

beforeEach(() => {
  resetTelemetryState();
  vi.spyOn(console, 'warn').mockImplementation(() => {});
});
afterEach(async () => {
  delete process.env['OTEL_EXPORTER_OTLP_CERTIFICATE'];
  await shutdownTelemetry();
  resetTelemetryState();
  vi.restoreAllMocks();
});

describe('ignored OTEL_METRICS_EXPORTER entries at setup', () => {
  it('setup succeeds, logs each message once and records setupError', () => {
    setupWith({ OTEL_METRICS_EXPORTER: 'console' });
    expect(getConfig().metricsExporters).toEqual(['otlp']);
    expect(ignoredLogs()).toEqual([
      `[provide/telemetry] config.metrics_exporter.value_ignored: reason=${CONSOLE}`,
      `[provide/telemetry] config.metrics_exporter.value_ignored: reason=${FALLBACK}`,
    ]);
    expect(getHealthSnapshot().setupError).toBe(`${CONSOLE}; ${FALLBACK}`);
  });

  it('a later clean setup clears only the error it set', () => {
    setupWith({ OTEL_METRICS_EXPORTER: 'otlp,statsd' });
    expect(getHealthSnapshot().setupError).toBe(UNKNOWN);
    setupWith({});
    expect(getHealthSnapshot().setupError).toBeNull();
    expect(ignoredLogs()).toHaveLength(1);
    setSetupError('unrelated');
    setupWith({ OTEL_METRICS_EXPORTER: 'prometheus' });
    expect(getHealthSnapshot().setupError).toBe('unrelated');
  });

  it('an exporter list given in code drops the environment warnings', () => {
    setupWith({ OTEL_METRICS_EXPORTER: 'statsd' }, { metricsExporters: ['prometheus'] });
    expect(getConfig().metricsExporterWarnings).toEqual([]);
    expect(getHealthSnapshot().setupError).toBeNull();
    setupWith(
      { OTEL_METRICS_EXPORTER: 'statsd' },
      { metricsExporters: ['prometheus'], metricsExporterWarnings: ['kept'] },
    );
    expect(getConfig().metricsExporterWarnings).toEqual(['kept']);
    setupWith({ OTEL_METRICS_EXPORTER: 'otlp,statsd' }, { serviceName: 'svc' });
    expect(getConfig().metricsExporterWarnings).toEqual([UNKNOWN]);
  });

  it('strict config throws instead, and publishes nothing', () => {
    expect(() =>
      setupWith({ OTEL_METRICS_EXPORTER: 'otlp,statsd', PROVIDE_TELEMETRY_STRICT_CONFIG: 'true' }),
    ).toThrow(
      new ConfigurationError(
        'PROVIDE_TELEMETRY_STRICT_CONFIG: OTEL_METRICS_EXPORTER: unknown exporter statsd, ignored',
      ),
    );
    expect(ignoredLogs()).toEqual([]);
    expect(getHealthSnapshot().setupError).toBeNull();
  });
});

describe('resetTelemetryState and the reported warnings', () => {
  it('a reset run reports the warning afresh and does not own the old text', () => {
    reportExporterWarnings([UNKNOWN]);
    expect(getHealthSnapshot().setupError).toBe(UNKNOWN);
    resetTelemetryState();
    expect(getHealthSnapshot().setupError).toBeNull();
    reportExporterWarnings([UNKNOWN]);
    expect(ignoredLogs()).toHaveLength(2);
    expect(getHealthSnapshot().setupError).toBe(UNKNOWN);
    resetTelemetryState();
    // The same text set by something else after the reset is not this run's to clear.
    setSetupError(UNKNOWN);
    reportExporterWarnings([]);
    expect(getHealthSnapshot().setupError).toBe(UNKNOWN);
  });
});

describe('ignored entries and OTLP TLS problems', () => {
  it('lists the ignored entries ahead of the TLS problems, and keeps them when TLS clears', async () => {
    setupWith({
      OTEL_METRICS_EXPORTER: 'otlp,statsd',
      OTEL_EXPORTER_OTLP_ENDPOINT: 'https://127.0.0.1:9',
    });
    const cfg = getConfig();
    process.env['OTEL_EXPORTER_OTLP_CERTIFICATE'] = '/nonexistent/ca.pem';
    await registerOtelProviders({ ...cfg, tracingEnabled: false, otlpLogsEnabled: false });
    const tls = 'OTEL_EXPORTER_OTLP_CERTIFICATE=/nonexistent/ca.pem: ENOENT';
    expect(getHealthSnapshot().setupError).toBe(`${UNKNOWN}; ${tls}`);
    await shutdownTelemetry();
    delete process.env['OTEL_EXPORTER_OTLP_CERTIFICATE'];
    await registerOtelProviders({ ...cfg, tracingEnabled: false, otlpLogsEnabled: false });
    expect(getHealthSnapshot().setupError).toBe(UNKNOWN);
  });

  it('with no ignored entries a cleared TLS error leaves no setupError', async () => {
    setupWith({ OTEL_EXPORTER_OTLP_ENDPOINT: 'https://127.0.0.1:9' });
    const cfg = { ...getConfig(), tracingEnabled: false, otlpLogsEnabled: false };
    process.env['OTEL_EXPORTER_OTLP_CERTIFICATE'] = '/nonexistent/ca.pem';
    await registerOtelProviders(cfg);
    expect(getHealthSnapshot().setupError).toMatch(/^OTEL_EXPORTER_OTLP_CERTIFICATE=/);
    await shutdownTelemetry();
    delete process.env['OTEL_EXPORTER_OTLP_CERTIFICATE'];
    await registerOtelProviders(cfg);
    expect(getHealthSnapshot().setupError).toBeNull();
  });
});
