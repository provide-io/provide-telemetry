// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * TelemetryConfig — mirrors Python undef.telemetry TelemetryConfig.
 *
 * Env vars (same names as Python package):
 *   UNDEF_TELEMETRY_SERVICE_NAME, UNDEF_ENV, UNDEF_VERSION,
 *   UNDEF_LOG_LEVEL, UNDEF_LOG_FORMAT, UNDEF_TRACE_ENABLED,
 *   OTEL_EXPORTER_OTLP_ENDPOINT, OTEL_EXPORTER_OTLP_HEADERS
 */
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
}

const DEFAULTS: TelemetryConfig = {
  serviceName: 'undef-service',
  environment: 'development',
  version: 'unknown',
  logLevel: 'info',
  logFormat: 'json',
  otelEnabled: false,
  sanitizeFields: [],
  captureToWindow: true,
  consoleOutput: false,
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
    serviceName: nodeEnv('UNDEF_TELEMETRY_SERVICE_NAME') ?? DEFAULTS.serviceName,
    environment: nodeEnv('UNDEF_ENV') ?? DEFAULTS.environment,
    version: nodeEnv('UNDEF_VERSION') ?? DEFAULTS.version,
    logLevel: nodeEnv('UNDEF_LOG_LEVEL')?.toLowerCase() ?? DEFAULTS.logLevel,
    logFormat: (() => {
      const fmt = nodeEnv('UNDEF_LOG_FORMAT');
      // Stryker disable next-line ConditionalExpression: 'json' is DEFAULTS.logFormat so removing its check returns the same default value
      return fmt === 'json' || fmt === 'pretty' ? fmt : DEFAULTS.logFormat;
    })(),
    otelEnabled: nodeEnv('UNDEF_TRACE_ENABLED') === 'true',
    otlpEndpoint: nodeEnv('OTEL_EXPORTER_OTLP_ENDPOINT'),
    otlpHeaders: parsedHeaders,
    sanitizeFields: DEFAULTS.sanitizeFields,
    captureToWindow: true,
    consoleOutput: false,
  };
}

/** Return the active TelemetryConfig. */
export function getConfig(): TelemetryConfig {
  return _config;
}

/**
 * Configure telemetry. Call once at app startup.
 * Merges explicit values over the current config (which may include env-derived values).
 */
export function setupTelemetry(overrides?: Partial<TelemetryConfig>): void {
  _config = { ...configFromEnv(), ...overrides };
}

/** Reset to defaults (used in tests). */
export function _resetConfig(): void {
  _config = { ...DEFAULTS };
}

/** Package version — mirrors Python __version__. */
export const version = '0.3.18';
export const __version__ = version;
