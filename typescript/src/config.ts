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

import { setSamplingPolicy } from './sampling';
import { setQueuePolicy } from './backpressure';
import { setExporterPolicy } from './resilience';
import { ConfigurationError } from './exceptions';
import { setSetupError } from './health';
import { isFallbackMode } from './propagation';
import { _setActiveConfig } from './runtime';
import { configFromEnv } from './config-env';
export { configFromEnv } from './config-env';
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

  // — Logging extras —
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

  // — Tracing —
  /** Trace sampling rate (0.0–1.0). */
  traceSampleRate: number;

  // — Metrics —
  /** Enable metrics collection. */
  metricsEnabled: boolean;

  // — Per-signal sampling —
  /** Probabilistic sampling rate for logs (0.0–1.0). */
  samplingLogsRate: number;
  /** Probabilistic sampling rate for traces (0.0–1.0). */
  samplingTracesRate: number;
  /** Probabilistic sampling rate for metrics (0.0–1.0). */
  samplingMetricsRate: number;

  // — Per-signal backpressure —
  /** Max queue size for log export (0 = unbounded). */
  backpressureLogsMaxsize: number;
  /** Max queue size for trace export (0 = unbounded). */
  backpressureTracesMaxsize: number;
  /** Max queue size for metric export (0 = unbounded). */
  backpressureMetricsMaxsize: number;

  // — Per-signal exporter resilience —
  /** Max retries for log export. */
  exporterLogsRetries: number;
  /** Backoff between log export retries (ms). */
  exporterLogsBackoffMs: number;
  /** Timeout for log export (ms). */
  exporterLogsTimeoutMs: number;
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

  // — SLO —
  /** Enable RED (Rate/Error/Duration) metrics. */
  sloEnableRedMetrics: boolean;
  /** Enable USE (Utilization/Saturation/Errors) metrics. */
  sloEnableUseMetrics: boolean;

  // — PII —
  /** Maximum recursion depth for PII sanitization of nested objects. */
  piiMaxDepth: number;

  // — Security —
  /** Max length for any single attribute value. */
  securityMaxAttrValueLength: number;
  /** Max number of attributes on a single span/log/metric point. */
  securityMaxAttrCount: number;
}

/**
 * Hot-reloadable config subset. Only fields that can be changed at runtime
 * without restarting providers. All fields are optional.
 */
export interface RuntimeOverrides {
  // Sampling
  samplingLogsRate?: number;
  samplingTracesRate?: number;
  samplingMetricsRate?: number;

  // Backpressure
  backpressureLogsMaxsize?: number;
  backpressureTracesMaxsize?: number;
  backpressureMetricsMaxsize?: number;

  // Exporter resilience
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

  // Security
  securityMaxAttrValueLength?: number;
  securityMaxAttrCount?: number;

  // SLO
  sloEnableRedMetrics?: boolean;
  sloEnableUseMetrics?: boolean;

  // PII
  piiMaxDepth?: number;

  // Schema
  strictSchema?: boolean;
  strictEventName?: boolean;
}

export const DEFAULTS: TelemetryConfig = {
  serviceName: 'provide-service',
  environment: 'dev',
  version: '0.0.0',
  logLevel: 'info',
  logFormat: 'console',
  otelEnabled: true,
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

/**
 * Configure telemetry. Call once at app startup.
 * Merges explicit values over the current config (which may include env-derived values).
 */
export function setupTelemetry(overrides?: Partial<TelemetryConfig>): void {
  _config = { ...configFromEnv(), ...overrides };
  _validateConfig(_config);
  if (isFallbackMode()) {
    const isNodeLike =
      typeof process !== 'undefined' &&
      typeof process.versions === 'object' &&
      typeof (process.versions as Record<string, unknown>).node === 'string';
    if (isNodeLike) {
      throw new ConfigurationError(
        'AsyncLocalStorage unavailable in a Node.js environment — ' +
          'concurrent requests would share propagation context. ' +
          'Check that node:async_hooks is not excluded from your bundler config.',
      );
    }
  }
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
  requireNonNegInt('exporterLogsRetries', cfg.exporterLogsRetries);
  requireNonNegInt('exporterTracesRetries', cfg.exporterTracesRetries);
  requireNonNegInt('exporterMetricsRetries', cfg.exporterMetricsRetries);
  requireNonNegInt('securityMaxAttrValueLength', cfg.securityMaxAttrValueLength);
  requireNonNegInt('securityMaxAttrCount', cfg.securityMaxAttrCount);
  requireNonNegInt('piiMaxDepth', cfg.piiMaxDepth);
}

/** Reset to defaults (used in tests). */
export function _resetConfig(): void {
  _config = { ...DEFAULTS };
  _configVersion = 0;
}

/**
 * Parse OTLP-style header string "key=value,key2=value2" into a Record.
 * Keys and values are URL-decoded. Malformed pairs (no '=') and empty keys are skipped.
 * Values may contain '=' characters (only the first '=' splits key from value).
 */
export function parseOtlpHeaders(raw: string): Record<string, string> {
  const result: Record<string, string> = {};
  // Stryker disable next-line ConditionalExpression: early return is an optimization — empty string splits to [""], idx<1 skips the only pair, returns {} identically
  if (!raw) return result;
  for (const pair of raw.split(',')) {
    const idx = pair.indexOf('=');
    if (idx < 1) continue; // no '=' or empty key
    const rawKey = pair.slice(0, idx).trim();
    const rawVal = pair.slice(idx + 1).trim();
    try {
      const key = decodeURIComponent(rawKey);
      // Stryker disable next-line ConditionalExpression: defensive guard — unreachable because idx<1 check and trim() already exclude empty keys
      /* v8 ignore next: defensive — idx<1 and trim() already exclude observable empty keys */
      if (!key) continue;
      const val = decodeURIComponent(rawVal);
      result[key] = val;
    } catch {
      // Skip pairs with invalid URL encoding
      continue;
    }
  }
  return result;
}

/** Mask a single header value: show first 4 chars + **** if >= 8 chars, else ****. */
function maskHeaderValue(v: string): string {
  return v.length < 8 ? '****' : v.slice(0, 4) + '****';
}

/** Mask the password component of a URL's userinfo, if present. */
function maskEndpointUrl(raw: string): string {
  try {
    const u = new URL(raw);
    if (u.password) {
      u.password = '****';
      return u.toString();
    }
  } catch {
    /* not a valid URL — return as-is */
  }
  return raw;
}

/**
 * Return a copy of the config with OTLP secrets masked.
 * Safe to log or serialize — never leaks header values or endpoint credentials.
 */
export function redactConfig(config: TelemetryConfig): Record<string, unknown> {
  const result: Record<string, unknown> = { ...config };
  // Stryker disable next-line EqualityOperator,ConditionalExpression: empty headers produce {} from Object.fromEntries — equivalent; undefined headers throw on Object.keys but caught identically
  if (config.otlpHeaders && Object.keys(config.otlpHeaders).length > 0) {
    result.otlpHeaders = Object.fromEntries(
      Object.entries(config.otlpHeaders).map(([k, v]) => [k, maskHeaderValue(v)]),
    );
  }
  // Mask per-signal headers
  for (const field of ['otlpLogsHeaders', 'otlpTracesHeaders', 'otlpMetricsHeaders'] as const) {
    const hdrs = config[field];
    if (hdrs && Object.keys(hdrs).length > 0) {
      result[field] = Object.fromEntries(
        Object.entries(hdrs).map(([k, v]) => [k, maskHeaderValue(v)]),
      );
    }
  }
  // Stryker disable next-line ConditionalExpression: maskEndpointUrl(undefined) returns undefined via catch — equivalent to skipping the block
  if (config.otlpEndpoint) {
    result.otlpEndpoint = maskEndpointUrl(config.otlpEndpoint);
  }
  // Mask per-signal endpoints
  for (const field of ['otlpLogsEndpoint', 'otlpTracesEndpoint', 'otlpMetricsEndpoint'] as const) {
    if (config[field]) {
      result[field] = maskEndpointUrl(config[field]);
    }
  }
  return result;
}

/** Package version — mirrors Python __version__. */
export const version = '0.3.18';
export const __version__ = version;
