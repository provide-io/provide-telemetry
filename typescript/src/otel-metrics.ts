// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

/**
 * The MeterProvider registerOtelProviders() installs: the OTLP push reader
 * and/or the Prometheus pull reader, per OTEL_METRICS_EXPORTER.
 *
 * Records the pull endpoint's status on every path, so metricsHandler() and
 * renderPrometheus() can say why they cannot serve. Mirrors Python
 * provide.telemetry.metrics.provider.setup_metrics.
 */

import { metrics } from '@opentelemetry/api';
import type { TelemetryConfig } from './config.js';
import { otlpMetricsReaderEnabled, prometheusReaderEnabled } from './config-prometheus.js';
import { validateOtlpEndpoint } from './endpoint.js';
import { dynImportOtel } from './otel-dynimport.js';
import { _isLiveMeterProviderInstalled } from './otel-probe.js';
import { buildOtelResource } from './otel-resource.js';
import { tlsReady } from './otlp-tls.js';
import { registerHealthOtlp } from './prom-health-otlp.js';
import {
  createPullReader,
  HOST_PROVIDER,
  markPullReady,
  METRICS_DISABLED,
  NOT_SELECTED,
  OTEL_DISABLED,
  OTEL_MISSING,
  optionsFor,
  SETUP_FAILED,
  setPullStatus,
  type PullReader,
} from './prom-pull.js';
import { wrapResilientExporter } from './resilient-exporter.js';
import type { ShutdownableProvider } from './runtime.js';

/** Record why there is no pull reader when registerOtelProviders() installs no meter provider. */
export function recordPullStatusWithoutProvider(cfg: TelemetryConfig): void {
  if (!cfg.metricsEnabled) setPullStatus(METRICS_DISABLED);
  else if (!prometheusReaderEnabled(cfg)) setPullStatus(NOT_SELECTED);
  else setPullStatus(cfg.otelEnabled ? OTEL_MISSING : OTEL_DISABLED);
}

/**
 * Build and install the meter provider, or return undefined when there is
 * nothing to install. Never throws: a failure is logged and recorded.
 */
export async function setupOtelMeterProvider(
  cfg: TelemetryConfig,
  otlpEndpoint: string | undefined,
  headers: Record<string, string>,
): Promise<ShutdownableProvider | undefined> {
  const wantPull = prometheusReaderEnabled(cfg);
  // A pull reader is unaffected by an unreadable OTLP TLS file; only OTLP is skipped.
  const wantOtlp =
    otlpEndpoint !== undefined && otlpMetricsReaderEnabled(cfg) && (await tlsReady('metrics'));
  if (!wantPull && !wantOtlp) {
    recordPullStatusWithoutProvider(cfg);
    return undefined;
  }
  /* eslint-disable @typescript-eslint/no-explicit-any */
  let sdkMetrics: any;
  let resources: any;
  /* eslint-enable @typescript-eslint/no-explicit-any */
  try {
    sdkMetrics = await dynImportOtel('@opentelemetry/sdk-metrics');
    resources = await dynImportOtel('@opentelemetry/resources');
  } catch (err) {
    setPullStatus(wantPull ? OTEL_MISSING : NOT_SELECTED);
    console.warn('[provide/telemetry] OTEL metrics setup failed (missing peer deps?):', err);
    return undefined;
  }
  const readers: unknown[] = [];
  if (wantOtlp) {
    try {
      const { OTLPMetricExporter } = await dynImportOtel(
        '@opentelemetry/exporter-metrics-otlp-http',
      );
      validateOtlpEndpoint(otlpEndpoint);
      const rawMetricExporter = new OTLPMetricExporter({
        url: otlpEndpoint,
        headers: cfg.otlpMetricsHeaders ?? headers,
        timeoutMillis: cfg.exporterMetricsTimeoutMs,
      });
      // Wrap so every batch export applies retry/timeout/circuit-breaker policy.
      const exporter = wrapResilientExporter('metrics', rawMetricExporter);
      readers.push(new sdkMetrics.PeriodicExportingMetricReader({ exporter }));
    } catch (err) {
      setPullStatus(SETUP_FAILED);
      console.warn('[provide/telemetry] OTEL metrics setup failed (missing peer deps?):', err);
      return undefined;
    }
  }
  // A live provider already on the global is the host application's: ours
  // would not become global, so instruments would never reach a reader on it.
  let pull: PullReader | undefined;
  if (wantPull && !_isLiveMeterProviderInstalled()) {
    pull = createPullReader(sdkMetrics);
    readers.push(pull);
  }
  if (readers.length === 0) {
    setPullStatus(HOST_PROVIDER);
    return undefined;
  }
  const provider = new sdkMetrics.MeterProvider({
    resource: buildOtelResource(resources, cfg),
    readers,
  });
  metrics.setGlobalMeterProvider(provider);
  // Never on a host's provider: this one is ours, built just above.
  if (cfg.metricsHealthOtlp) registerHealthOtlp(provider.getMeter('@provide-io/telemetry'));
  if (pull !== undefined) markPullReady(pull, optionsFor(cfg));
  else setPullStatus(wantPull ? HOST_PROVIDER : NOT_SELECTED);
  return provider as ShutdownableProvider;
}
