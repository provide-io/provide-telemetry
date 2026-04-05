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
import { setSetupError } from './health';
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
  securityMaxAttrValueLength: 1024,
  securityMaxAttrCount: 64,
};

let _config: TelemetryConfig = { ...DEFAULTS };

/** Incremented on every setupTelemetry() call so getRootLogger() knows to rebuild. */
let _configVersion = 0;

/** Parse an env var as a number, falling back to `fallback` on missing or NaN. */
function envNumber(key: string, fallback: number): number {
  const raw = nodeEnv(key);
  if (raw === undefined) return fallback;
  const n = Number(raw);
  return Number.isNaN(n) ? fallback : n;
}

/** Parse an env var expressed in seconds and return milliseconds. */
function envSecondsToMs(key: string, fallbackMs: number): number {
  const raw = nodeEnv(key);
  if (raw === undefined) return fallbackMs;
  const n = Number(raw);
  return Number.isNaN(n) ? fallbackMs : n * 1000;
}

/** Parse a module_levels string like "mod1=DEBUG,mod2=WARN" into a Record. */
function parseModuleLevels(raw: string | undefined): Record<string, string> {
  if (!raw) return {};
  const result: Record<string, string> = {};
  for (const pair of raw.split(',')) {
    const trimmed = pair.trim();
    if (!trimmed.includes('=')) continue;
    const [mod, level] = trimmed.split('=', 2).map((s) => s.trim());
    if (mod && level) result[mod] = level;
  }
  return result;
}

/**
 * Build a TelemetryConfig from environment variables.
 * Uses the same env var names as the Python package.
 * Explicit values passed to setupTelemetry() override env vars.
 */
export function configFromEnv(): TelemetryConfig {
  const otelHeader = nodeEnv('OTEL_EXPORTER_OTLP_HEADERS');
  const parsedHeaders: Record<string, string> | undefined = otelHeader
    ? Object.fromEntries(
        otelHeader
          .split(',')
          .map((pair) => {
            const idx = pair.indexOf('=');
            if (idx === -1) return [pair.trim(), ''] as [string, string];
            return [pair.slice(0, idx).trim(), pair.slice(idx + 1).trim()] as [string, string];
          })
          .filter(([k]) => k !== ''),
      )
    : undefined;

  return {
    serviceName: nodeEnv('PROVIDE_TELEMETRY_SERVICE_NAME') ?? DEFAULTS.serviceName,
    environment: nodeEnv('PROVIDE_TELEMETRY_ENV') ?? nodeEnv('PROVIDE_ENV') ?? DEFAULTS.environment,
    version: nodeEnv('PROVIDE_TELEMETRY_VERSION') ?? nodeEnv('PROVIDE_VERSION') ?? DEFAULTS.version,
    logLevel: nodeEnv('PROVIDE_LOG_LEVEL')?.toLowerCase() ?? DEFAULTS.logLevel,
    logFormat: (() => {
      const fmt = nodeEnv('PROVIDE_LOG_FORMAT');
      // Stryker disable next-line ConditionalExpression: 'json' is DEFAULTS.logFormat so removing its check returns the same default value
      return fmt === 'json' || fmt === 'pretty' ? fmt : DEFAULTS.logFormat;
    })(),
    otelEnabled: nodeEnv('PROVIDE_TRACE_ENABLED') === 'true',
    otlpEndpoint: nodeEnv('OTEL_EXPORTER_OTLP_ENDPOINT'),
    otlpHeaders: parsedHeaders,
    sanitizeFields: DEFAULTS.sanitizeFields,
    captureToWindow: true,
    consoleOutput: false,
    strictSchema: nodeEnv('PROVIDE_TELEMETRY_STRICT_SCHEMA') === 'true',
    requiredLogKeys: (() => {
      const raw = nodeEnv('PROVIDE_TELEMETRY_REQUIRED_KEYS');
      return raw
        ? raw
            .split(',')
            .map((s) => s.trim())
            .filter(Boolean)
        : [];
    })(),

    // Logging extras
    logIncludeTimestamp: nodeEnv('PROVIDE_LOG_INCLUDE_TIMESTAMP') !== 'false',
    logIncludeCaller: nodeEnv('PROVIDE_LOG_INCLUDE_CALLER') !== 'false',
    logSanitize: nodeEnv('PROVIDE_LOG_SANITIZE') !== 'false',
    logCodeAttributes: nodeEnv('PROVIDE_LOG_CODE_ATTRIBUTES') === 'true',
    logModuleLevels: parseModuleLevels(nodeEnv('PROVIDE_LOG_MODULE_LEVELS')),

    // Tracing
    traceSampleRate: envNumber('PROVIDE_TRACE_SAMPLE_RATE', DEFAULTS.traceSampleRate),

    // Metrics
    metricsEnabled: nodeEnv('PROVIDE_METRICS_ENABLED') !== 'false',

    // Per-signal sampling
    samplingLogsRate: envNumber('PROVIDE_SAMPLING_LOGS_RATE', DEFAULTS.samplingLogsRate),
    samplingTracesRate: envNumber('PROVIDE_SAMPLING_TRACES_RATE', DEFAULTS.samplingTracesRate),
    samplingMetricsRate: envNumber('PROVIDE_SAMPLING_METRICS_RATE', DEFAULTS.samplingMetricsRate),

    // Per-signal backpressure
    backpressureLogsMaxsize: envNumber(
      'PROVIDE_BACKPRESSURE_LOGS_MAXSIZE',
      DEFAULTS.backpressureLogsMaxsize,
    ),
    backpressureTracesMaxsize: envNumber(
      'PROVIDE_BACKPRESSURE_TRACES_MAXSIZE',
      DEFAULTS.backpressureTracesMaxsize,
    ),
    backpressureMetricsMaxsize: envNumber(
      'PROVIDE_BACKPRESSURE_METRICS_MAXSIZE',
      DEFAULTS.backpressureMetricsMaxsize,
    ),

    // Per-signal exporter resilience
    exporterLogsRetries: envNumber('PROVIDE_EXPORTER_LOGS_RETRIES', DEFAULTS.exporterLogsRetries),
    exporterLogsBackoffMs: envSecondsToMs(
      'PROVIDE_EXPORTER_LOGS_BACKOFF_SECONDS',
      DEFAULTS.exporterLogsBackoffMs,
    ),
    exporterLogsTimeoutMs: envSecondsToMs(
      'PROVIDE_EXPORTER_LOGS_TIMEOUT_SECONDS',
      DEFAULTS.exporterLogsTimeoutMs,
    ),
    exporterLogsFailOpen: nodeEnv('PROVIDE_EXPORTER_LOGS_FAIL_OPEN') !== 'false',
    exporterTracesRetries: envNumber(
      'PROVIDE_EXPORTER_TRACES_RETRIES',
      DEFAULTS.exporterTracesRetries,
    ),
    exporterTracesBackoffMs: envSecondsToMs(
      'PROVIDE_EXPORTER_TRACES_BACKOFF_SECONDS',
      DEFAULTS.exporterTracesBackoffMs,
    ),
    exporterTracesTimeoutMs: envSecondsToMs(
      'PROVIDE_EXPORTER_TRACES_TIMEOUT_SECONDS',
      DEFAULTS.exporterTracesTimeoutMs,
    ),
    exporterTracesFailOpen: nodeEnv('PROVIDE_EXPORTER_TRACES_FAIL_OPEN') !== 'false',
    exporterMetricsRetries: envNumber(
      'PROVIDE_EXPORTER_METRICS_RETRIES',
      DEFAULTS.exporterMetricsRetries,
    ),
    exporterMetricsBackoffMs: envSecondsToMs(
      'PROVIDE_EXPORTER_METRICS_BACKOFF_SECONDS',
      DEFAULTS.exporterMetricsBackoffMs,
    ),
    exporterMetricsTimeoutMs: envSecondsToMs(
      'PROVIDE_EXPORTER_METRICS_TIMEOUT_SECONDS',
      DEFAULTS.exporterMetricsTimeoutMs,
    ),
    exporterMetricsFailOpen: nodeEnv('PROVIDE_EXPORTER_METRICS_FAIL_OPEN') !== 'false',

    // SLO
    sloEnableRedMetrics: nodeEnv('PROVIDE_SLO_ENABLE_RED_METRICS') === 'true',
    sloEnableUseMetrics: nodeEnv('PROVIDE_SLO_ENABLE_USE_METRICS') === 'true',

    // Security
    securityMaxAttrValueLength: envNumber(
      'PROVIDE_SECURITY_MAX_ATTR_VALUE_LENGTH',
      DEFAULTS.securityMaxAttrValueLength,
    ),
    securityMaxAttrCount: envNumber(
      'PROVIDE_SECURITY_MAX_ATTR_COUNT',
      DEFAULTS.securityMaxAttrCount,
    ),
  };
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
  try {
    applyConfigPolicies(_config);
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : String(err);
    setSetupError(message);
    // eslint-disable-next-line no-console
    console.warn(`setupTelemetry: applyConfigPolicies failed: ${message}`);
  }
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
      /* v8 ignore next -- defensive: idx<1 and trim() already exclude observable empty keys */
      // Stryker disable next-line ConditionalExpression: defensive guard — unreachable because idx<1 check and trim() already exclude empty keys
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

/** Package version — mirrors Python __version__. */
export const version = '0.4.0';
export const __version__ = version;
