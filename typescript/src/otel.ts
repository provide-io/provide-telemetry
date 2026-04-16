// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
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
import { validateOtlpEndpoint } from './endpoint';
import { setupOtelLogProvider } from './otel-logs';

// No default endpoint — when otlpEndpoint is unset, OTLP export is skipped
// entirely (safe no-export path per docs/ARCHITECTURE.md).
import {
  type ShutdownableProvider,
  _areProvidersRegistered,
  _markProvidersRegistered,
  _setProviderSignalInstalled,
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
  const endpoint = cfg.otlpEndpoint;
  if (!endpoint) {
    // No OTLP endpoint configured — skip export entirely (safe no-export path).
    // Providers are still marked registered so repeated calls are no-ops.
    _markProvidersRegistered();
    return;
  }
  const registered: ShutdownableProvider[] = [];

  // ── Context manager ──────────────────────────────────────────────────────────
  // Install AsyncLocalStorageContextManager so startActiveSpan propagates spans
  // through async boundaries in Node.js. Must happen before TracerProvider setup.
  try {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const ctxHooks: any = await import('@opentelemetry/context-async-hooks' as string);
    const { context } = await import('@opentelemetry/api');
    const ctxMgr = new ctxHooks.AsyncLocalStorageContextManager();
    ctxMgr.enable();
    context.setGlobalContextManager(ctxMgr);
  } catch {
    // Not a Node.js environment or peer dep not installed — skip silently.
  }

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

      const traceEndpoint = cfg.otlpTracesEndpoint ?? `${endpoint}/v1/traces`;
      validateOtlpEndpoint(traceEndpoint);
      const traceHeaders = cfg.otlpTracesHeaders ?? headers;
      const traceExporter = new OTLPTraceExporter({
        url: traceEndpoint,
        headers: traceHeaders,
      });

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
      _setProviderSignalInstalled('traces', true);
    } catch (err) {
      console.warn('[provide/telemetry] OTEL trace setup failed (missing peer deps?):', err);
    }
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

      const metricsEndpoint = cfg.otlpMetricsEndpoint ?? `${endpoint}/v1/metrics`;
      validateOtlpEndpoint(metricsEndpoint);
      const metricsHeaders = cfg.otlpMetricsHeaders ?? headers;
      const metricExporter = new OTLPMetricExporter({
        url: metricsEndpoint,
        headers: metricsHeaders,
      });

      const meterProvider = new MeterProvider({
        readers: [new PeriodicExportingMetricReader({ exporter: metricExporter })],
      });
      metrics.setGlobalMeterProvider(meterProvider);
      registered.push(meterProvider as ShutdownableProvider);
      _setProviderSignalInstalled('metrics', true);
    } catch (err) {
      console.warn('[provide/telemetry] OTEL metrics setup failed (missing peer deps?):', err);
    }
  }

  // ── Logs ─────────────────────────────────────────────────────────────────────
  try {
    registered.push(await setupOtelLogProvider(cfg));
    _setProviderSignalInstalled('logs', true);
  } catch (err) {
    console.warn('[provide/telemetry] OTEL logs setup failed (missing peer deps?):', err);
  }

  _storeRegisteredProviders(registered);
  if (registered.length > 0) {
    _markProvidersRegistered();
  }
}
