// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/* Stryker disable all -- dynamic import('...' as string) prevents Stryker's V8 perTest
   coverage from attributing any coverage to specific tests; all mutations in this file
   show covered:0 even though integration tests exercise every branch. */

/**
 * Optional OTEL SDK wiring — only activated when setupTelemetry({ otelEnabled: true }) is called.
 *
 * All imports are dynamic so this module adds zero bundle overhead when OTEL is unused.
 * Peer deps required:
 *   @opentelemetry/sdk-trace-base   — BasicTracerProvider, span processors/exporters
 *   @opentelemetry/sdk-metrics      — MeterProvider, metric readers
 *   @opentelemetry/resources        — resourceFromAttributes
 *   @opentelemetry/exporter-trace-otlp-http   — OTLPTraceExporter
 *   @opentelemetry/exporter-metrics-otlp-http — OTLPMetricExporter
 *
 * Mirrors Python provide.telemetry _otel.py lazy-load approach.
 */

import type { TelemetryConfig } from './config';

const DEFAULT_OTLP_ENDPOINT = 'http://localhost:4318';
import {
  type ShutdownableProvider,
  _markProvidersRegistered,
  _storeRegisteredProviders,
} from './runtime';

/**
 * Register OTEL TracerProvider and MeterProvider using OTLP HTTP exporters.
 * Safe to call multiple times — subsequent calls are no-ops if already registered.
 */
export async function registerOtelProviders(cfg: TelemetryConfig): Promise<void> {
  if (!cfg.otelEnabled) return;
  if (_areProvidersRegistered()) return;

  const headers = cfg.otlpHeaders ?? {};
  const endpoint = cfg.otlpEndpoint ?? DEFAULT_OTLP_ENDPOINT;
  const registered: ShutdownableProvider[] = [];

  // ── Tracing ──────────────────────────────────────────────────────────────────
  if (cfg.tracingEnabled) {
    try {
      // These are optional peer deps — TypeScript checks are suppressed intentionally.
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const traceBase: any = await import('@opentelemetry/sdk-trace-base' as string);
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const otlpTrace: any = await import('@opentelemetry/exporter-trace-otlp-http' as string);
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const res: any = await import('@opentelemetry/resources' as string);
      const { trace } = await import('@opentelemetry/api');

      const { BasicTracerProvider, BatchSpanProcessor } = traceBase;
      const { OTLPTraceExporter } = otlpTrace;
      const { resourceFromAttributes } = res;

      if (tracesEndpoint) {
        validateOtlpEndpoint(tracesEndpoint);
        const traceHeaders = cfg.otlpTracesHeaders ?? headers;
        const rawTraceExporter = new OTLPTraceExporter({
          url: tracesEndpoint,
          headers: traceHeaders,
          timeoutMillis: cfg.exporterTracesTimeoutMs ?? 10000,
        });
        // Wrap so every batch export applies retry/timeout/circuit-breaker policy.
        const traceExporter = wrapResilientExporter('traces', rawTraceExporter);

    const provider = new BasicTracerProvider({
      resource: resourceFromAttributes({
        'service.name': cfg.serviceName,
        'deployment.environment': cfg.environment,
        'service.version': cfg.version,
      }),
      spanProcessors: [new BatchSpanProcessor(traceExporter)],
    });
    trace.setGlobalTracerProvider(provider);
    registered.push(provider as ShutdownableProvider);
  } catch (err) {
    console.warn('[undef/telemetry] OTEL trace setup failed (missing peer deps?):', err);
  }

  // ── Metrics ──────────────────────────────────────────────────────────────────
  if (cfg.metricsEnabled) {
    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const sdkMetrics: any = await import('@opentelemetry/sdk-metrics' as string);
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const otlpMetrics: any = await import('@opentelemetry/exporter-metrics-otlp-http' as string);
      const { metrics } = await import('@opentelemetry/api');
      const { MeterProvider, PeriodicExportingMetricReader } = sdkMetrics;
      const { OTLPMetricExporter } = otlpMetrics;

      if (metricsEndpoint) {
        validateOtlpEndpoint(metricsEndpoint);
        const metricsHeaders = cfg.otlpMetricsHeaders ?? headers;
        const rawMetricExporter = new OTLPMetricExporter({
          url: metricsEndpoint,
          headers: metricsHeaders,
          timeoutMillis: cfg.exporterMetricsTimeoutMs ?? 10000,
        });
        // Wrap so every batch export applies retry/timeout/circuit-breaker policy.
        const metricExporter = wrapResilientExporter('metrics', rawMetricExporter);

    const meterProvider = new MeterProvider({
      readers: [new PeriodicExportingMetricReader({ exporter: metricExporter })],
    });
    metrics.setGlobalMeterProvider(meterProvider);
    registered.push(meterProvider as ShutdownableProvider);
  } catch (err) {
    console.warn('[undef/telemetry] OTEL metrics setup failed (missing peer deps?):', err);
  }

  _storeRegisteredProviders(registered);
  _markProvidersRegistered();
}
