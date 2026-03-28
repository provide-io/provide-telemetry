// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: AGPL-3.0-or-later

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
 * Mirrors Python undef.telemetry _otel.py lazy-load approach.
 */

import type { TelemetryConfig } from './config';
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

  const headers = cfg.otlpHeaders ?? {};
  const endpoint = cfg.otlpEndpoint ?? 'http://localhost:4318';
  const registered: ShutdownableProvider[] = [];

  // ── Tracing ──────────────────────────────────────────────────────────────────
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

    const traceExporter = new OTLPTraceExporter({
      url: `${endpoint}/v1/traces`,
      headers,
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
  } catch (err) {
    console.warn('[undef/telemetry] OTEL trace setup failed (missing peer deps?):', err);
  }

  // ── Metrics ──────────────────────────────────────────────────────────────────
  try {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const sdkMetrics: any = await import('@opentelemetry/sdk-metrics' as string);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const otlpMetrics: any = await import('@opentelemetry/exporter-metrics-otlp-http' as string);
    const { metrics } = await import('@opentelemetry/api');
    const { MeterProvider, PeriodicExportingMetricReader } = sdkMetrics;
    const { OTLPMetricExporter } = otlpMetrics;

    const metricExporter = new OTLPMetricExporter({
      url: `${endpoint}/v1/metrics`,
      headers,
    });

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
