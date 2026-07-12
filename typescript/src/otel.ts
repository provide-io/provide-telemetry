// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/*
 * Peer-dep loading note: all @opentelemetry/* imports below go through
 * dynImportOtel() (src/otel-dynimport.ts) rather than a literal
 * `import('pkg')`. That keeps every OTel peer dep tree-shakeable for
 * bundler users who set otelEnabled:false, AND stops bundlers (esbuild,
 * webpack, rollup) from statically resolving the specifier and failing the
 * build when a consumer hasn't installed the optional peer dep.
 *
 * Mutation-testing note (mirrored in typescript/stryker.config.mjs): this
 * file is still excluded from Stryker's `mutate` array. Routing through
 * dynImportOtel() fixed the old V8-coverage-tracing blind spot, but doing
 * so surfaced pre-existing untested edge cases (endpoint normalization,
 * provider-signal bookkeeping) that keep the measured score under the 95%
 * break threshold — latent debt, tracked separately from this change.
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
import { buildOtelResource } from './otel-resource';
import { setupOtelLogProvider } from './otel-logs';
import { dynImportOtel } from './otel-dynimport';
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
    const ctxHooks = await dynImportOtel('@opentelemetry/context-async-hooks');
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
      const traceBase = await dynImportOtel('@opentelemetry/sdk-trace-base');
      const otlpTrace = await dynImportOtel('@opentelemetry/exporter-trace-otlp-http');
      const res = await dynImportOtel('@opentelemetry/resources');
      const { trace } = await import('@opentelemetry/api');

      const {
        BasicTracerProvider,
        BatchSpanProcessor,
        ParentBasedSampler,
        TraceIdRatioBasedSampler,
        AlwaysOffSampler,
      } = traceBase;
      const { OTLPTraceExporter } = otlpTrace;

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

        // SDK sampler is authoritative for live OTel spans (global tracer,
        // instrumentations, withTrace). Facade shouldSample is skipped when
        // traces providers are registered to avoid double-sampling.
        const rate = Math.min(cfg.samplingTracesRate, cfg.traceSampleRate);
        const rootSampler = rate <= 0 ? new AlwaysOffSampler() : new TraceIdRatioBasedSampler(rate);
        const sampler = new ParentBasedSampler({ root: rootSampler });

        const provider = new BasicTracerProvider({
          resource: buildOtelResource(res, cfg),
          spanProcessors: [new BatchSpanProcessor(traceExporter)],
          sampler,
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
      const sdkMetrics = await dynImportOtel('@opentelemetry/sdk-metrics');
      const otlpMetrics = await dynImportOtel('@opentelemetry/exporter-metrics-otlp-http');
      const res = await dynImportOtel('@opentelemetry/resources');
      const { metrics } = await import('@opentelemetry/api');
      const { MeterProvider, PeriodicExportingMetricReader } = sdkMetrics;
      const { OTLPMetricExporter } = otlpMetrics;

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
          resource: buildOtelResource(res, cfg),
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
  // PROVIDE_LOG_OTLP_ENABLED gates the logs OTLP provider independently of
  // the trace/metrics flags. When disabled, no OTLP log handler is attached
  // even if the endpoint is configured — useful to escape shutdown hangs
  // against unreachable collectors without unsetting OTEL_EXPORTER_OTLP_ENDPOINT.
  if (logsEndpoint && cfg.otlpLogsEnabled) {
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
