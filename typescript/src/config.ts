// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * TelemetryConfig — mirrors Python provide.telemetry TelemetryConfig.
 *
 * Env vars (same names as Python package):
 *   PROVIDE_TELEMETRY_SERVICE_NAME, PROVIDE_TELEMETRY_ENV (fallback: PROVIDE_ENV),
 *   PROVIDE_TELEMETRY_VERSION (fallback: PROVIDE_VERSION),
 *   PROVIDE_LOG_LEVEL, PROVIDE_LOG_FORMAT, PROVIDE_TRACE_ENABLED,
 *   PROVIDE_TELEMETRY_STRICT_SCHEMA,
 *   OTEL_EXPORTER_OTLP_ENDPOINT, OTEL_EXPORTER_OTLP_HEADERS
 */

import { setSamplingPolicy } from './sampling.js';
import { setQueuePolicy } from './backpressure.js';
import { MAX_EXPORT_ATTEMPTS, setExporterPolicy } from './resilience.js';
import { ConfigurationError } from './exceptions.js';
import { setSetupError } from './health.js';
import { awaitPropagationInit, isFallbackMode, isPropagationInitDone } from './propagation.js';
import { _setActiveConfig } from './runtime.js';
import { configFromEnv } from './config-env.js';
export { configFromEnv } from './config-env.js';
export { parseOtlpHeaders, redactConfig } from './config-redact.js';
export interface TelemetryConfig {
  /** Service name injected into every log record. */
  serviceName: string;
  /** Deployment environment (e.g. "development", "production"). */
  environment: string;
  /** Application version injected into every log record. */
  version: string;
  /** Pino log level: trace | debug | info | warn | error. */
  logLevel: string;
  /** Output format: "json" (default), "pretty", or "console" (alias for pretty). */
  logFormat: 'json' | 'pretty' | 'console';
  /** When true, registerOtelProviders() will install OTEL SDK providers. setupTelemetry() stores this flag but does not register providers itself. */
  otelEnabled: boolean;
  /** Enable tracing decorators/instrumentation and trace-provider setup. */
  tracingEnabled: boolean;
  /** OTLP export endpoint (e.g. "http://localhost:4318"). */
  otlpEndpoint?: string;
  /** OTLP headers as key=value pairs. */
  otlpHeaders?: Record<string, string>;
  /** Per-signal OTLP endpoints (override shared otlpEndpoint). */
  otlpLogsEndpoint?: string;
  otlpTracesEndpoint?: string;
  otlpMetricsEndpoint?: string;
  /** Kill switch for OTLP log export, independent of trace/metrics flags. Env: `PROVIDE_LOG_OTLP_ENABLED`. */
  otlpLogsEnabled: boolean;
  /** Per-signal OTLP headers (override shared otlpHeaders). */
  otlpLogsHeaders?: Record<string, string>;
  otlpTracesHeaders?: Record<string, string>;
  otlpMetricsHeaders?: Record<string, string>;
  /** Fields whose values are replaced with "[REDACTED]". */
  sanitizeFields: string[];
  /** Push every log object into window.__pinoLogs (browser only). */
  captureToWindow: boolean;
  /**
   * Emit logs to browser console via console.debug/log/warn/error.
   * Default false — use captureToWindow + window.__pinoLogs or OTEL export instead.
   * Set true during local development for live devtools inspection.
   */
  consoleOutput: boolean;
  /** Master schema strictness switch. */
  strictSchema: boolean;
  /** Enforce strict event-name validation even when strictSchema is false. */
  strictEventName: boolean;
  /** Keys required on every log record. */
  requiredLogKeys: string[];

  /** Include timestamp in log output. */
  logIncludeTimestamp: boolean;
  /** Include caller info in log output. */
  logIncludeCaller: boolean;
  /** Enable PII/secret sanitization in logs. */
  logSanitize: boolean;
  /** Attach code.filepath / code.lineno attributes to log records. */
  logCodeAttributes: boolean;
  /** Per-module log level overrides (e.g. {"provide.server": "DEBUG"}). */
  logModuleLevels: Record<string, string>;
  /** Named ANSI color for pretty-rendered attribute keys. Empty string disables key color. */
  logPrettyKeyColor: string;
  /** Named ANSI color for pretty-rendered attribute values. Empty string disables value color. */
  logPrettyValueColor: string;
  /** Optional allow-list of pretty-rendered key=value fields. Empty means render all. */
  logPrettyFields: string[];

  /** Trace sampling rate (0.0–1.0). */
  traceSampleRate: number;

  /** Enable metrics collection. */
  metricsEnabled: boolean;

  /** Probabilistic sampling rate for logs (0.0–1.0). */
  samplingLogsRate: number;
  /** Probabilistic sampling rate for traces (0.0–1.0). */
  samplingTracesRate: number;
  /** Probabilistic sampling rate for metrics (0.0–1.0). */
  samplingMetricsRate: number;

  /** Max queue size for log export (0 = unbounded). */
  backpressureLogsMaxsize: number;
  /** Max queue size for trace export (0 = unbounded). */
  backpressureTracesMaxsize: number;
  /** Max queue size for metric export (0 = unbounded). */
  backpressureMetricsMaxsize: number;

  /** Max retries for log export. */
  exporterLogsRetries: number;
  /** Backoff between log export retries (ms). */
  exporterLogsBackoffMs: number;
  /** Timeout for log export (ms). */
  exporterLogsTimeoutMs: number;
  /** Per-provider deadline for shutdownTelemetry's flush+shutdown sequence (ms). Env: `PROVIDE_EXPORTER_LOGS_SHUTDOWN_TIMEOUT_SECONDS`. */
  exporterLogsShutdownTimeoutMs: number;
  /** If true, drop telemetry on export failure instead of crashing. */
  exporterLogsFailOpen: boolean;
  /** Max retries for trace export. */
  exporterTracesRetries: number;
  /** Backoff between trace export retries (ms). */
  exporterTracesBackoffMs: number;
  /** Timeout for trace export (ms). */
  exporterTracesTimeoutMs: number;
  /** If true, drop telemetry on export failure instead of crashing. */
  exporterTracesFailOpen: boolean;
  /** Max retries for metric export. */
  exporterMetricsRetries: number;
  /** Backoff between metric export retries (ms). */
  exporterMetricsBackoffMs: number;
  /** Timeout for metric export (ms). */
  exporterMetricsTimeoutMs: number;
  /** If true, drop telemetry on export failure instead of crashing. */
  exporterMetricsFailOpen: boolean;

  /** Enable RED (Rate/Error/Duration) metrics. */
  sloEnableRedMetrics: boolean;
  /** Enable USE (Utilization/Saturation/Errors) metrics. */
  sloEnableUseMetrics: boolean;

  /** Maximum recursion depth for PII sanitization of nested objects. */
  piiMaxDepth: number;

  /** Max length for any single attribute value. */
  securityMaxAttrValueLength: number;
  /** Max number of attributes on a single span/log/metric point. */
  securityMaxAttrCount: number;
}

/**
 * Hot-reloadable logging subset of `RuntimeOverrides.logging`. Mirrors
 * Python `LoggingConfig` field coverage (level, format, include-timestamp,
 * include-caller, sanitize, code-attributes, module-levels). OTLP endpoint
 * and headers are intentionally excluded — they require a cold reconfigure.
 */
export interface LoggingOverrides {
  logLevel?: string;
  logFormat?: 'json' | 'pretty' | 'console';
  logIncludeTimestamp?: boolean;
  logIncludeCaller?: boolean;
  logSanitize?: boolean;
  logCodeAttributes?: boolean;
  logModuleLevels?: Record<string, string>;
  logPrettyKeyColor?: string;
  logPrettyValueColor?: string;
  logPrettyFields?: string[];
}

/**
 * Hot-reloadable config subset. Only fields that can be changed at runtime
 * without restarting providers. All fields are optional.
 */
export interface RuntimeOverrides {
  samplingLogsRate?: number;
  samplingTracesRate?: number;
  samplingMetricsRate?: number;

  backpressureLogsMaxsize?: number;
  backpressureTracesMaxsize?: number;
  backpressureMetricsMaxsize?: number;

  exporterLogsRetries?: number;
  exporterLogsBackoffMs?: number;
  exporterLogsTimeoutMs?: number;
  exporterLogsFailOpen?: boolean;
  exporterTracesRetries?: number;
  exporterTracesBackoffMs?: number;
  exporterTracesTimeoutMs?: number;
  exporterTracesFailOpen?: boolean;
  exporterMetricsRetries?: number;
  exporterMetricsBackoffMs?: number;
  exporterMetricsTimeoutMs?: number;
  exporterMetricsFailOpen?: boolean;

  securityMaxAttrValueLength?: number;
  securityMaxAttrCount?: number;

  sloEnableRedMetrics?: boolean;
  sloEnableUseMetrics?: boolean;

  piiMaxDepth?: number;

  strictSchema?: boolean;
  strictEventName?: boolean;

  /** Hot-reloadable logging subset. Mirrors Python `RuntimeOverrides.logging`. */
  logging?: LoggingOverrides;
}

export const DEFAULTS: TelemetryConfig = {
  serviceName: 'provide-service',
  environment: 'dev',
  version: '0.0.0',
  logLevel: 'info',
  logFormat: 'console',
  otelEnabled: true,
  otlpLogsEnabled: true,
  sanitizeFields: [],
  captureToWindow: true,
  consoleOutput: true,
  strictSchema: false,
  strictEventName: false,
  requiredLogKeys: [],
  logIncludeTimestamp: true,
  logIncludeCaller: true,
  logSanitize: true,
  logCodeAttributes: false,
  logModuleLevels: {},
  logPrettyKeyColor: 'dim',
  logPrettyValueColor: '',
  logPrettyFields: [],
  traceSampleRate: 1.0,
  tracingEnabled: true,
  metricsEnabled: true,
  samplingLogsRate: 1.0,
  samplingTracesRate: 1.0,
  samplingMetricsRate: 1.0,
  backpressureLogsMaxsize: 0,
  backpressureTracesMaxsize: 0,
  backpressureMetricsMaxsize: 0,
  exporterLogsRetries: 0,
  exporterLogsBackoffMs: 0,
  exporterLogsTimeoutMs: 10000,
  exporterLogsShutdownTimeoutMs: 5000,
  exporterLogsFailOpen: true,
  exporterTracesRetries: 0,
  exporterTracesBackoffMs: 0,
  exporterTracesTimeoutMs: 10000,
  exporterTracesFailOpen: true,
  exporterMetricsRetries: 0,
  exporterMetricsBackoffMs: 0,
  exporterMetricsTimeoutMs: 10000,
  exporterMetricsFailOpen: true,
  sloEnableRedMetrics: false,
  sloEnableUseMetrics: false,
  piiMaxDepth: 8,
  securityMaxAttrValueLength: 1024,
  securityMaxAttrCount: 64,
};

let _config: TelemetryConfig = { ...DEFAULTS };

/** Incremented on every setupTelemetry() call so getRootLogger() knows to rebuild. */
let _configVersion = 0;

/** Return the current config version (used by logger to detect stale root). */
export function _getConfigVersion(): number {
  return _configVersion;
}

/** Return the active TelemetryConfig. */
export function getConfig(): TelemetryConfig {
  return _config;
}

/**
 * Apply parsed config fields to the runtime policy engines (sampling, backpressure, resilience).
 * Mirrors Python provide.telemetry.runtime.apply_runtime_config.
 */
export function applyConfigPolicies(cfg: TelemetryConfig): void {
  // Sampling
  setSamplingPolicy('logs', { defaultRate: cfg.samplingLogsRate });
  setSamplingPolicy('traces', {
    defaultRate: Math.min(cfg.samplingTracesRate, cfg.traceSampleRate),
  });
  setSamplingPolicy('metrics', { defaultRate: cfg.samplingMetricsRate });

  // Backpressure
  setQueuePolicy({
    maxLogs: cfg.backpressureLogsMaxsize,
    maxTraces: cfg.backpressureTracesMaxsize,
    maxMetrics: cfg.backpressureMetricsMaxsize,
  });

  // Exporter resilience (per-signal)
  setExporterPolicy('logs', {
    retries: cfg.exporterLogsRetries,
    backoffMs: cfg.exporterLogsBackoffMs,
    timeoutMs: cfg.exporterLogsTimeoutMs,
    failOpen: cfg.exporterLogsFailOpen,
  });
  setExporterPolicy('traces', {
    retries: cfg.exporterTracesRetries,
    backoffMs: cfg.exporterTracesBackoffMs,
    timeoutMs: cfg.exporterTracesTimeoutMs,
    failOpen: cfg.exporterTracesFailOpen,
  });
  setExporterPolicy('metrics', {
    retries: cfg.exporterMetricsRetries,
    backoffMs: cfg.exporterMetricsBackoffMs,
    timeoutMs: cfg.exporterMetricsTimeoutMs,
    failOpen: cfg.exporterMetricsFailOpen,
  });
}

const _FALLBACK_MESSAGE =
  'AsyncLocalStorage unavailable in a Node.js environment — concurrent requests would share propagation context. Check that node:async_hooks is not excluded from your bundler config.';

function _isNodeLike(): boolean {
  // Only the host-presence half is suppressed, and only for
  // ConditionalExpression: `process` is defined and `process.versions` is a
  // real object in every environment this suite runs in (only `.node` is ever
  // stubbed away, in config.mutants.test.ts), so forcing this line true or
  // false is unobservable. Everything else stays live — the `'object'` and
  // `'string'` literals and the `.node` check all change what _isNodeLike
  // reports, and config.mutants2.test.ts asserts both directions.
  // Stryker disable next-line ConditionalExpression
  const hasProcess = typeof process !== 'undefined' && typeof process.versions === 'object';
  return hasProcess && typeof (process.versions as Record<string, unknown>).node === 'string';
}

function _applySetupBody(overrides?: Partial<TelemetryConfig>): void {
  // Validate the candidate before publishing it. Assigning `_config` first left
  // `getConfig()` returning the rejected values after setupTelemetry threw, so a
  // caller that caught the error kept emitting under a config it had been told
  // was invalid.
  const candidate = { ...configFromEnv(), ...overrides };
  _validateConfig(candidate);
  _config = candidate;
  _configVersion++;
  _setActiveConfig(_config);
  try {
    applyConfigPolicies(_config);
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : String(err);
    setSetupError(message);
    console.warn(`setupTelemetry: applyConfigPolicies failed: ${message}`);
  }
}

/**
 * Configure telemetry. Merges explicit values over env-derived defaults.
 * Best-effort ALS check: defers a warning when init is still racing.
 * Prefer `setupTelemetryAsync` from ESM entry points that need a hard
 * "safe or throws" guarantee.
 */
export function setupTelemetry(overrides?: Partial<TelemetryConfig>): void {
  const isNode = _isNodeLike();
  if (isNode && isFallbackMode()) {
    if (isPropagationInitDone()) {
      // Init has settled and ALS is genuinely unavailable — fail loud as before.
      throw new ConfigurationError(_FALLBACK_MESSAGE);
    }
    // Init still racing (typical of tsx/ESM Node where propagation.ts loads
    // node:async_hooks via fire-and-forget `await import`). Defer the check
    // to after init resolves; record + warn instead of throwing because the
    // call site has already returned by the time we know the verdict.
    void awaitPropagationInit().then(() => {
      if (isFallbackMode()) {
        setSetupError(_FALLBACK_MESSAGE);
        console.warn(`[provide-telemetry] ${_FALLBACK_MESSAGE}`);
      }
    });
  }
  _applySetupBody(overrides);
}

/**
 * Async variant of `setupTelemetry` that awaits AsyncLocalStorage init
 * before returning. Use this from ESM entry points (e.g. servers starting
 * at module scope) so you get an "either safe or throws" contract rather
 * than the best-effort deferred warning of the sync variant. Throws
 * `ConfigurationError` when ALS is genuinely unavailable on a Node runtime.
 */
export async function setupTelemetryAsync(overrides?: Partial<TelemetryConfig>): Promise<void> {
  _applySetupBody(overrides);
  if (!_isNodeLike()) return;
  await awaitPropagationInit();
  if (isFallbackMode()) {
    setSetupError(_FALLBACK_MESSAGE);
    throw new ConfigurationError(_FALLBACK_MESSAGE);
  }
}

/** Validate config values — reject out-of-range instead of silently clamping (fail-fast contract). */
function _validateConfig(cfg: TelemetryConfig): void {
  const requireRate = (name: string, v: number): void => {
    if (!Number.isFinite(v) || v < 0 || v > 1) {
      throw new ConfigurationError(`${name} must be in [0, 1], got ${String(v)}`);
    }
  };
  const requireNonNegInt = (name: string, v: number): void => {
    if (!Number.isInteger(v) || v < 0) {
      throw new ConfigurationError(`${name} must be a non-negative integer, got ${String(v)}`);
    }
  };
  requireRate('samplingLogsRate', cfg.samplingLogsRate);
  requireRate('samplingTracesRate', cfg.samplingTracesRate);
  requireRate('samplingMetricsRate', cfg.samplingMetricsRate);
  requireRate('traceSampleRate', cfg.traceSampleRate);
  requireNonNegInt('backpressureLogsMaxsize', cfg.backpressureLogsMaxsize);
  requireNonNegInt('backpressureTracesMaxsize', cfg.backpressureTracesMaxsize);
  requireNonNegInt('backpressureMetricsMaxsize', cfg.backpressureMetricsMaxsize);
  // Retries get a ceiling as well as a floor: runWithResilience builds a
  // retries+1 index array per export call, so an unbounded value costs memory
  // on every healthy export, not only on a failing one.
  const requireRetries = (name: string, v: number): void => {
    requireNonNegInt(name, v);
    if (v > MAX_EXPORT_ATTEMPTS - 1) {
      throw new ConfigurationError(
        `${name} must be at most ${String(MAX_EXPORT_ATTEMPTS - 1)}, got ${String(v)}`,
      );
    }
  };
  requireRetries('exporterLogsRetries', cfg.exporterLogsRetries);
  requireRetries('exporterTracesRetries', cfg.exporterTracesRetries);
  requireRetries('exporterMetricsRetries', cfg.exporterMetricsRetries);
  requireNonNegInt('securityMaxAttrValueLength', cfg.securityMaxAttrValueLength);
  requireNonNegInt('securityMaxAttrCount', cfg.securityMaxAttrCount);
  requireNonNegInt('piiMaxDepth', cfg.piiMaxDepth);
}

/** Reset to defaults (used in tests). */
export function _resetConfig(): void {
  _config = { ...DEFAULTS };
  _configVersion = 0;
}

/** Package version — mirrors Python __version__. */
export const version = '0.7.0';
export const __version__ = version;
