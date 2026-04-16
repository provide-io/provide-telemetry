// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Environment-variable parsing helpers and configFromEnv().
 * Split from config.ts to stay under 500 LOC per file.
 */

import type { TelemetryConfig } from './config';
import { DEFAULTS, parseOtlpHeaders } from './config';
import { ConfigurationError } from './exceptions';

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
      // Stryker disable next-line ConditionalExpression: 'console' is DEFAULTS.logFormat so removing its check returns the same default value
      if (fmt === 'json' || fmt === 'pretty' || fmt === 'console') return fmt;
      return DEFAULTS.logFormat;
    })(),
    otelEnabled: envBool('PROVIDE_TRACE_ENABLED', DEFAULTS.otelEnabled),
    otlpEndpoint: nodeEnv('OTEL_EXPORTER_OTLP_ENDPOINT'),
    otlpHeaders: parsedHeaders,
    otlpLogsEndpoint: (() => {
      const v = nodeEnv('OTEL_EXPORTER_OTLP_LOGS_ENDPOINT');
      return v ?? undefined;
    })(),
    otlpTracesEndpoint: (() => {
      const v = nodeEnv('OTEL_EXPORTER_OTLP_TRACES_ENDPOINT');
      return v ?? undefined;
    })(),
    otlpMetricsEndpoint: (() => {
      const v = nodeEnv('OTEL_EXPORTER_OTLP_METRICS_ENDPOINT');
      return v ?? undefined;
    })(),
    otlpLogsHeaders: (() => {
      const v = nodeEnv('OTEL_EXPORTER_OTLP_LOGS_HEADERS');
      return v ? parseOtlpHeaders(v) : undefined;
    })(),
    otlpTracesHeaders: (() => {
      const v = nodeEnv('OTEL_EXPORTER_OTLP_TRACES_HEADERS');
      return v ? parseOtlpHeaders(v) : undefined;
    })(),
    otlpMetricsHeaders: (() => {
      const v = nodeEnv('OTEL_EXPORTER_OTLP_METRICS_HEADERS');
      return v ? parseOtlpHeaders(v) : undefined;
    })(),
    sanitizeFields: DEFAULTS.sanitizeFields,
    captureToWindow: true,
    consoleOutput: true,
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
