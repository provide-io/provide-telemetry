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
import { ConfigurationError } from './exceptions';
export interface TelemetryConfig {
  /** Service name injected into every log record. */
  serviceName: string;
  /** Deployment environment (e.g. "development", "production"). */
  environment: string;
  /** Application version injected into every log record. */
  version: string;
  /** Pino log level: trace | debug | info | warn | error. */
  logLevel: string;
  /** Output format: "json" (default) or "pretty". */
  logFormat: 'json' | 'pretty';
  /** Enable OTEL SDK registration on setupTelemetry(). */
  otelEnabled: boolean;
  /** OTLP export endpoint (e.g. "http://localhost:4318"). */
  otlpEndpoint?: string;
  /** OTLP headers as key=value pairs. */
  otlpHeaders?: Record<string, string>;
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
  /** Enforce strict event name validation (3-5 dot-separated segments). */
  strictSchema: boolean;
  /** Keys required on every log record when strictSchema is enabled. */
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
}

const DEFAULTS: TelemetryConfig = {
  serviceName: 'provide-service',
  environment: 'development',
  version: 'unknown',
  logLevel: 'info',
  logFormat: 'json',
  otelEnabled: false,
  sanitizeFields: [],
  captureToWindow: true,
  consoleOutput: false,
  strictSchema: false,
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
  piiMaxDepth: 8,
  securityMaxAttrValueLength: 1024,
  securityMaxAttrCount: 64,
};

let _config: TelemetryConfig = { ...DEFAULTS };

/** Read a string from Node process.env. Silently returns undefined in non-Node environments. */
// Stryker disable BlockStatement
function nodeEnv(key: string): string | undefined {
  try {
    // process.env is not available in browser builds after tree-shaking,
    // but some bundlers (esbuild, Vite) leave process.env.X inline replacements.
    // Stryker disable next-line ConditionalExpression,StringLiteral: process is always defined in Node.js/test environments
    return typeof process !== 'undefined' ? process.env[key] : undefined;
  } catch {
    return undefined;
  }
}
// Stryker enable BlockStatement

/** Parse an env var as a number, falling back to `fallback` on missing or NaN. */
function envNumber(key: string, fallback: number): number {
  const raw = nodeEnv(key);
  // Stryker disable next-line ConditionalExpression: undefined check — removing returns NaN path which NaN guard catches identically
  if (raw === undefined) return fallback;
  const n = Number(raw);
  return Number.isNaN(n) ? fallback : n;
}

function envBool(key: string, fallback: boolean): boolean {
  const raw = nodeEnv(key);
  if (raw === undefined || raw.trim() === '') return fallback;
  switch (raw.trim().toLowerCase()) {
    case '1':
    case 'true':
    case 'yes':
    case 'on':
      return true;
    case '0':
    case 'false':
    case 'no':
    case 'off':
      return false;
    default:
      throw new ConfigurationError(
        `invalid boolean for ${key}: ${JSON.stringify(raw)} (expected one of: 1,true,yes,on,0,false,no,off)`,
      );
  }
}

function envFloatInRange(key: string, fallback: number, min: number, max: number): number {
  const value = envNumber(key, fallback);
  if (!Number.isFinite(value) || value < min || value > max) {
    throw new ConfigurationError(`${key} must be in [${min}, ${max}], got ${String(value)}`);
  }
  return value;
}

function envNonNegativeInt(key: string, fallback: number): number {
  const value = envNumber(key, fallback);
  if (!Number.isInteger(value) || value < 0) {
    throw new ConfigurationError(`${key} must be a non-negative integer, got ${String(value)}`);
  }
  return value;
}

function envNonNegativeMsFromSeconds(key: string, fallbackMs: number): number {
  const value = envSecondsToMs(key, fallbackMs);
  if (!Number.isFinite(value) || value < 0) {
    throw new ConfigurationError(`${key} must be >= 0, got ${String(value)}`);
  }
  return value;
}

/** Parse an env var expressed in seconds and return milliseconds. */
function envSecondsToMs(key: string, fallbackMs: number): number {
  const raw = nodeEnv(key);
  // Stryker disable next-line ConditionalExpression: same as envNumber — undefined falls through to NaN guard
  if (raw === undefined) return fallbackMs;
  const n = Number(raw);
  return Number.isNaN(n) ? fallbackMs : n * 1000;
}

/** Parse a module_levels string like "mod1=DEBUG,mod2=WARN" into a Record. */
function parseModuleLevels(raw: string | undefined): Record<string, string> {
  if (!raw) return {};
  const result: Record<string, string> = {};
  for (const pair of raw.split(',')) {
    /* Stryker disable MethodExpression,StringLiteral,ConditionalExpression: trim + includes('=') guard — removing produces malformed but non-crashing output */
    const trimmed = pair.trim();
    if (!trimmed.includes('=')) continue;
    /* Stryker restore MethodExpression,StringLiteral,ConditionalExpression */
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
  const parsedHeaders = otelHeader ? parseOtlpHeaders(otelHeader) : undefined;

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
    otelEnabled: envBool('PROVIDE_TRACE_ENABLED', DEFAULTS.otelEnabled),
    otlpEndpoint: nodeEnv('OTEL_EXPORTER_OTLP_ENDPOINT'),
    otlpHeaders: parsedHeaders,
    sanitizeFields: DEFAULTS.sanitizeFields,
    captureToWindow: true,
    consoleOutput: false,
    strictSchema: envBool('PROVIDE_TELEMETRY_STRICT_SCHEMA', DEFAULTS.strictSchema),
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
    logIncludeTimestamp: envBool('PROVIDE_LOG_INCLUDE_TIMESTAMP', DEFAULTS.logIncludeTimestamp),
    logIncludeCaller: envBool('PROVIDE_LOG_INCLUDE_CALLER', DEFAULTS.logIncludeCaller),
    logSanitize: envBool('PROVIDE_LOG_SANITIZE', DEFAULTS.logSanitize),
    logCodeAttributes: envBool('PROVIDE_LOG_CODE_ATTRIBUTES', DEFAULTS.logCodeAttributes),
    logModuleLevels: parseModuleLevels(nodeEnv('PROVIDE_LOG_MODULE_LEVELS')),

    // Tracing
    traceSampleRate: envFloatInRange('PROVIDE_TRACE_SAMPLE_RATE', DEFAULTS.traceSampleRate, 0, 1),

    // Metrics
    metricsEnabled: envBool('PROVIDE_METRICS_ENABLED', DEFAULTS.metricsEnabled),

    // Per-signal sampling
    samplingLogsRate: envFloatInRange(
      'PROVIDE_SAMPLING_LOGS_RATE',
      DEFAULTS.samplingLogsRate,
      0,
      1,
    ),
    samplingTracesRate: envFloatInRange(
      'PROVIDE_SAMPLING_TRACES_RATE',
      DEFAULTS.samplingTracesRate,
      0,
      1,
    ),
    samplingMetricsRate: envFloatInRange(
      'PROVIDE_SAMPLING_METRICS_RATE',
      DEFAULTS.samplingMetricsRate,
      0,
      1,
    ),

    // Per-signal backpressure
    backpressureLogsMaxsize: envNonNegativeInt(
      'PROVIDE_BACKPRESSURE_LOGS_MAXSIZE',
      DEFAULTS.backpressureLogsMaxsize,
    ),
    backpressureTracesMaxsize: envNonNegativeInt(
      'PROVIDE_BACKPRESSURE_TRACES_MAXSIZE',
      DEFAULTS.backpressureTracesMaxsize,
    ),
    backpressureMetricsMaxsize: envNonNegativeInt(
      'PROVIDE_BACKPRESSURE_METRICS_MAXSIZE',
      DEFAULTS.backpressureMetricsMaxsize,
    ),

    // Per-signal exporter resilience
    exporterLogsRetries: envNonNegativeInt(
      'PROVIDE_EXPORTER_LOGS_RETRIES',
      DEFAULTS.exporterLogsRetries,
    ),
    exporterLogsBackoffMs: envNonNegativeMsFromSeconds(
      'PROVIDE_EXPORTER_LOGS_BACKOFF_SECONDS',
      DEFAULTS.exporterLogsBackoffMs,
    ),
    exporterLogsTimeoutMs: envNonNegativeMsFromSeconds(
      'PROVIDE_EXPORTER_LOGS_TIMEOUT_SECONDS',
      DEFAULTS.exporterLogsTimeoutMs,
    ),
    exporterLogsFailOpen: envBool('PROVIDE_EXPORTER_LOGS_FAIL_OPEN', DEFAULTS.exporterLogsFailOpen),
    exporterTracesRetries: envNonNegativeInt(
      'PROVIDE_EXPORTER_TRACES_RETRIES',
      DEFAULTS.exporterTracesRetries,
    ),
    exporterTracesBackoffMs: envNonNegativeMsFromSeconds(
      'PROVIDE_EXPORTER_TRACES_BACKOFF_SECONDS',
      DEFAULTS.exporterTracesBackoffMs,
    ),
    exporterTracesTimeoutMs: envNonNegativeMsFromSeconds(
      'PROVIDE_EXPORTER_TRACES_TIMEOUT_SECONDS',
      DEFAULTS.exporterTracesTimeoutMs,
    ),
    exporterTracesFailOpen: envBool(
      'PROVIDE_EXPORTER_TRACES_FAIL_OPEN',
      DEFAULTS.exporterTracesFailOpen,
    ),
    exporterMetricsRetries: envNonNegativeInt(
      'PROVIDE_EXPORTER_METRICS_RETRIES',
      DEFAULTS.exporterMetricsRetries,
    ),
    exporterMetricsBackoffMs: envNonNegativeMsFromSeconds(
      'PROVIDE_EXPORTER_METRICS_BACKOFF_SECONDS',
      DEFAULTS.exporterMetricsBackoffMs,
    ),
    exporterMetricsTimeoutMs: envNonNegativeMsFromSeconds(
      'PROVIDE_EXPORTER_METRICS_TIMEOUT_SECONDS',
      DEFAULTS.exporterMetricsTimeoutMs,
    ),
    exporterMetricsFailOpen: envBool(
      'PROVIDE_EXPORTER_METRICS_FAIL_OPEN',
      DEFAULTS.exporterMetricsFailOpen,
    ),

    // SLO
    sloEnableRedMetrics: envBool('PROVIDE_SLO_ENABLE_RED_METRICS', DEFAULTS.sloEnableRedMetrics),
    sloEnableUseMetrics: envBool('PROVIDE_SLO_ENABLE_USE_METRICS', DEFAULTS.sloEnableUseMetrics),

    // PII
    piiMaxDepth: envNonNegativeInt('PROVIDE_LOG_PII_MAX_DEPTH', DEFAULTS.piiMaxDepth),

    // Security
    securityMaxAttrValueLength: envNonNegativeInt(
      'PROVIDE_SECURITY_MAX_ATTR_VALUE_LENGTH',
      DEFAULTS.securityMaxAttrValueLength,
    ),
    securityMaxAttrCount: envNonNegativeInt(
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
  setSamplingPolicy('traces', { defaultRate: cfg.samplingTracesRate });
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
    console.warn(`setupTelemetry: applyConfigPolicies failed: ${message}`);
  }
}

/** Reset to defaults (used in tests). */
export function _resetConfig(): void {
  _config = { ...DEFAULTS };
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
export const version = '0.2.0';
export const __version__ = version;
