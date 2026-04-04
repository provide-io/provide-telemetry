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
import { awaitPropagationInit, isFallbackMode, isPropagationInitDone } from './propagation';
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
  /** Enforce strict event name validation (3-5 dot-separated segments). */
  strictSchema: boolean;
  /** Keys required on every log record when strictSchema is enabled. */
  requiredLogKeys: string[];
}

const DEFAULTS: TelemetryConfig = {
  serviceName: 'provide-service',
  environment: 'development',
  version: 'unknown',
  logLevel: 'info',
  logFormat: 'console',
  otelEnabled: true,
  sanitizeFields: [],
  captureToWindow: true,
  consoleOutput: false,
  strictSchema: false,
  requiredLogKeys: [],
};

let _config: TelemetryConfig = { ...DEFAULTS };

/** Incremented on every setupTelemetry() call so getRootLogger() knows to rebuild. */
let _configVersion = 0;

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
          .map((pair) => pair.split('=').map((s) => s.trim()) as [string, string]),
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
  _validateConfig(_config);
  const isNodeLike =
    typeof process !== 'undefined' &&
    typeof process.versions === 'object' &&
    typeof (process.versions as Record<string, unknown>).node === 'string';
  const fallbackMessage =
    'AsyncLocalStorage unavailable in a Node.js environment — ' +
    'concurrent requests would share propagation context. ' +
    'Check that node:async_hooks is not excluded from your bundler config.';
  if (isNodeLike && isFallbackMode()) {
    if (isPropagationInitDone()) {
      // Init has settled and ALS is genuinely unavailable — fail loud as before.
      throw new ConfigurationError(fallbackMessage);
    }
    // Init still racing (typical of tsx/ESM Node where propagation.ts loads
    // node:async_hooks via fire-and-forget `await import`). Defer the check
    // to after init resolves; record + warn instead of throwing because the
    // call site has already returned by the time we know the verdict.
    void awaitPropagationInit().then(() => {
      if (isFallbackMode()) {
        setSetupError(fallbackMessage);
        console.warn(`[provide-telemetry] ${fallbackMessage}`);
      }
    });
  }
  _configVersion++;
  _setActiveConfig(_config);
  try {
    applyConfigPolicies(_config);
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : String(err);
    setSetupError(message);
    // eslint-disable-next-line no-console
    console.warn(`setupTelemetry: applyConfigPolicies failed: ${message}`);
  }
}

/** Clamp rates to [0,1] and floor non-negative integers so getConfig() matches effective policy. */
function _normalizeConfig(cfg: TelemetryConfig): void {
  const clamp01 = (v: number): number => Math.max(0, Math.min(1, v));
  const floorNonNeg = (v: number): number => Math.max(0, Math.floor(v));
  cfg.samplingLogsRate = clamp01(cfg.samplingLogsRate);
  cfg.samplingTracesRate = clamp01(cfg.samplingTracesRate);
  cfg.samplingMetricsRate = clamp01(cfg.samplingMetricsRate);
  cfg.traceSampleRate = clamp01(cfg.traceSampleRate);
  cfg.backpressureLogsMaxsize = floorNonNeg(cfg.backpressureLogsMaxsize);
  cfg.backpressureTracesMaxsize = floorNonNeg(cfg.backpressureTracesMaxsize);
  cfg.backpressureMetricsMaxsize = floorNonNeg(cfg.backpressureMetricsMaxsize);
  cfg.exporterLogsRetries = floorNonNeg(cfg.exporterLogsRetries);
  cfg.exporterTracesRetries = floorNonNeg(cfg.exporterTracesRetries);
  cfg.exporterMetricsRetries = floorNonNeg(cfg.exporterMetricsRetries);
  cfg.securityMaxAttrValueLength = floorNonNeg(cfg.securityMaxAttrValueLength);
  cfg.securityMaxAttrCount = floorNonNeg(cfg.securityMaxAttrCount);
  cfg.piiMaxDepth = floorNonNeg(cfg.piiMaxDepth);
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
export const version = '0.2.0';
export const __version__ = version;
