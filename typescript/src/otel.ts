// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/*
 * Mutation-testing note (mirrored in typescript/stryker.config.mjs):
 *
 * This file is excluded from Stryker's `mutate` array because it uses
 * `await import('pkg' as string)` so Stryker's V8 perTest coverage
 * instrumentor cannot trace which test exercises which mutant — every mutant
 * reports covered:0 and is labelled "no coverage" rather than being killed.
 * Switching to static imports is out of scope: the dynamic pattern is the
 * load-bearing mechanism that keeps all OTel peer deps tree-shakeable for
 * bundler users who set otelEnabled:false.
 *
 * TRADEOFF: mutations in this file are not killed by unit tests.
 * The risk is accepted because:
 *   1. Integration tests in tests/integration/otel-providers-registration.test.ts
 *      and tests/integration/otel-providers.test.ts exercise every branch
 *      with real OTel SDK objects, giving strong behavioural confidence.
 *   2. The logic here is thin wiring (endpoint resolution + provider
 *      construction); the resilience-policy and export-path mutations that
 *      matter most are covered at 100% in resilient-exporter.ts and
 *      resilience.ts, which use static imports.
 *
 * If a future Stryker version can track V8 coverage through dynamic imports,
 * remove the `!src/otel.ts` exemption in stryker.config.mjs and add targeted
 * unit tests.
 */

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
import { wrapResilientExporter } from './resilient-exporter';

// No default endpoint — when otlpEndpoint is unset, OTLP export is skipped
// entirely (safe no-export path per docs/ARCHITECTURE.md).
import {
  type ShutdownableProvider,
  _areProvidersRegistered,
  _markProvidersRegistered,
  _setProviderSignalInstalled,
  _storeRegisteredProviders,
} from './runtime';

function normalizeEndpoint(endpoint: string | undefined): string | undefined {
  const trimmed = endpoint?.trim();
  return trimmed ? trimmed : undefined;
}

function appendSignalPath(endpoint: string, signalPath: string): string {
  return `${endpoint.replace(/\/+$/, '')}${signalPath}`;
}

/**
 * Register OTEL TracerProvider and MeterProvider using OTLP HTTP exporters.
 * Safe to call multiple times — subsequent calls are no-ops if already registered.
 */
export async function registerOtelProviders(cfg: TelemetryConfig): Promise<void> {
  if (!cfg.otelEnabled) return;
  if (_areProvidersRegistered()) return;

  const headers = cfg.otlpHeaders ?? {};
  const sharedEndpoint = normalizeEndpoint(cfg.otlpEndpoint);
  const logsEndpoint =
    normalizeEndpoint(cfg.otlpLogsEndpoint) ??
    (sharedEndpoint ? appendSignalPath(sharedEndpoint, '/v1/logs') : undefined);
  const tracesEndpoint =
    normalizeEndpoint(cfg.otlpTracesEndpoint) ??
    (sharedEndpoint ? appendSignalPath(sharedEndpoint, '/v1/traces') : undefined);
  const metricsEndpoint =
    normalizeEndpoint(cfg.otlpMetricsEndpoint) ??
    (sharedEndpoint ? appendSignalPath(sharedEndpoint, '/v1/metrics') : undefined);
  const hasAnyEndpoint =
    logsEndpoint !== undefined || tracesEndpoint !== undefined || metricsEndpoint !== undefined;
  if (!hasAnyEndpoint) {
    // No OTLP endpoint configured for any signal — skip export entirely
    // (safe no-export path).
    // Do NOT mark providers as registered: no real providers exist, so
    // reconfigureTelemetry() should remain free to install them later
    // when an endpoint is provided.
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

      if (tracesEndpoint) {
        validateOtlpEndpoint(tracesEndpoint);
        const traceHeaders = cfg.otlpTracesHeaders ?? headers;
        const rawTraceExporter = new OTLPTraceExporter({
          url: tracesEndpoint,
          headers: traceHeaders,
          timeoutMillis: cfg.exporterTracesTimeoutMs,
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
        _setProviderSignalInstalled('traces', true);
      }
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
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const res: any = await import('@opentelemetry/resources' as string);
      const { metrics } = await import('@opentelemetry/api');
      const { MeterProvider, PeriodicExportingMetricReader } = sdkMetrics;
      const { OTLPMetricExporter } = otlpMetrics;
      const { resourceFromAttributes } = res;

      if (metricsEndpoint) {
        validateOtlpEndpoint(metricsEndpoint);
        const metricsHeaders = cfg.otlpMetricsHeaders ?? headers;
        const rawMetricExporter = new OTLPMetricExporter({
          url: metricsEndpoint,
          headers: metricsHeaders,
          timeoutMillis: cfg.exporterMetricsTimeoutMs,
        });
        // Wrap so every batch export applies retry/timeout/circuit-breaker policy.
        const metricExporter = wrapResilientExporter('metrics', rawMetricExporter);

        const meterProvider = new MeterProvider({
          resource: resourceFromAttributes({
            'service.name': cfg.serviceName,
            'deployment.environment': cfg.environment,
            'service.version': cfg.version,
          }),
          readers: [new PeriodicExportingMetricReader({ exporter: metricExporter })],
        });
        metrics.setGlobalMeterProvider(meterProvider);
        registered.push(meterProvider as ShutdownableProvider);
        _setProviderSignalInstalled('metrics', true);
      }
    } catch (err) {
      console.warn('[provide/telemetry] OTEL metrics setup failed (missing peer deps?):', err);
    }
  }

  // ── Logs ─────────────────────────────────────────────────────────────────────
  if (logsEndpoint) {
    try {
      registered.push(await setupOtelLogProvider(cfg));
      _setProviderSignalInstalled('logs', true);
    } catch (err) {
      console.warn('[provide/telemetry] OTEL logs setup failed (missing peer deps?):', err);
    }
  }

  _storeRegisteredProviders(registered);
  if (registered.length > 0) {
    _markProvidersRegistered();
  }
}
